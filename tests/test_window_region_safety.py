from __future__ import annotations

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "knight_flow" / "overlay.py"
CHROME = ROOT / "knight_flow" / "win32_chrome.py"


def function_source(path: Path, name: str) -> str:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    matches = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name == name
    ]
    if len(matches) != 1:
        raise AssertionError(f"expected one {name}, found {len(matches)}")
    return ast.get_source_segment(source, matches[0]) or ""


class OrdinaryWindowsNeverUseAliasedRegionsTests(unittest.TestCase):
    """GDI window regions are a one-bit stencil, not antialiased chrome.

    Windows 11 can draw ordinary corners in DWM. Windows 10 cannot, so a clean
    square fallback is more intentional than a jagged simulated curve. The
    microphone Pill is the single shaped-window exception.
    """

    def test_overlay_region_helper_is_only_called_by_the_pill(self) -> None:
        source = OVERLAY.read_text(encoding="utf-8")
        tree = ast.parse(source)
        parents: dict[ast.AST, ast.AST] = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parents[child] = node

        owners: list[str] = []
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "_apply_window_region"
            ):
                continue
            owner: ast.AST | None = node
            while owner is not None and not isinstance(owner, ast.FunctionDef):
                owner = parents.get(owner)
            owners.append(owner.name if isinstance(owner, ast.FunctionDef) else "")
        self.assertEqual(owners, ["_apply_pill_region"])

    def test_region_helper_delegates_to_the_explicit_shaped_policy(self) -> None:
        body = function_source(OVERLAY, "_apply_window_region")
        self.assertIn("apply_shaped_window_region", body)
        self.assertNotIn("CreateRoundRectRgn", body)
        self.assertNotIn("SetWindowRgn", body)

    def test_ordinary_chrome_never_creates_a_region(self) -> None:
        body = function_source(CHROME, "apply_window_chrome")
        self.assertNotIn("create_round_region", body)
        self.assertIn('mode = "square"', body)
        self.assertIn("WINDOWS_11_BUILD", body)

    def test_shaped_region_targets_one_outer_handle(self) -> None:
        body = function_source(CHROME, "apply_shaped_window_region")
        self.assertIn("native_toplevel_handle", body)
        self.assertNotIn("for handle in", body)
        self.assertNotIn("GetParent", body)

    def test_failed_transfer_deletes_but_successful_transfer_does_not(self) -> None:
        body = function_source(CHROME, "apply_shaped_window_region")
        transfer = body[: body.index("except Exception:")]
        cleanup = body[body.index("except Exception:") :]
        self.assertNotIn("delete_region", transfer)
        self.assertIn("delete_region", cleanup)

    def test_region_application_never_requests_a_synchronous_redraw(self) -> None:
        chrome_api = function_source(CHROME, "_CtypesChromeApi")
        body = chrome_api[
            chrome_api.index("def set_region") : chrome_api.index("def delete_region")
        ]
        self.assertIn("False", body)
        self.assertNotIn("True", body)

    def test_all_ctypes_window_handles_are_pointer_sized(self) -> None:
        body = function_source(CHROME, "_CtypesChromeApi")
        for function in (
            "GetAncestor.argtypes",
            "SetWindowRgn.argtypes",
            "_get_window_long_ptr.argtypes",
            "_set_window_long_ptr.argtypes",
            "SetWindowPos.argtypes",
            "MonitorFromWindow.argtypes",
            "GetMonitorInfoW.argtypes",
            "DwmSetWindowAttribute.argtypes",
            "DwmGetWindowAttribute.argtypes",
        ):
            with self.subTest(function=function):
                self.assertIn(function, body)
        self.assertIn("wintypes.HWND", body)


if __name__ == "__main__":
    unittest.main()
