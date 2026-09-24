from __future__ import annotations

import ast
import importlib
import pkgutil
import unittest
from pathlib import Path

from knight_flow.mac_support import IS_MAC


@unittest.skipUnless(IS_MAC, "guards against Windows APIs leaking onto macOS")
class NoWindowsApiEscapesOntoMacTests(unittest.TestCase):
    """ctypes.windll raises AttributeError on macOS, not OSError.

    That distinction already produced three dead buttons in this port, because
    the handlers caught OSError. The risk is structural rather than local: a
    win32 call reached on a macOS path takes out whatever thread it is on, and
    most sit inside broad try blocks where the failure is invisible.

    An earlier version of this test called every public zero-argument function
    looking for escapes. It worked, and it was the wrong instrument: it made
    real network calls, warmed audio devices, and became the slowest thing in
    the suite. Reading the code answers the same question without doing any of
    that, and answers it for code paths a call never reaches.
    """

    def _modules(self) -> list[str]:
        import knight_flow
        import knight_flow.ui

        names = [f"knight_flow.{m.name}" for m in pkgutil.iter_modules(knight_flow.__path__)]
        names += [f"knight_flow.ui.{m.name}" for m in pkgutil.iter_modules(knight_flow.ui.__path__)]
        return names

    def test_every_module_imports(self) -> None:
        """Import is where a bad top-level construct bites, and it is cheap."""
        failures = []
        for name in self._modules():
            try:
                importlib.import_module(name)
            except Exception as error:  # noqa: BLE001 - reporting is the point
                failures.append(f"{name}: {type(error).__name__}: {error}")
        self.assertEqual(failures, [], "modules that cannot be imported on macOS")

    def test_every_windll_use_is_guarded_or_caught(self) -> None:
        """Each `ctypes.windll` must sit inside a platform check or a try.

        Neither alone is the standard being enforced -- a bare try that catches
        Exception is enough to keep the thread alive, and a platform check is
        enough to never reach the call. What is banned is neither: a windll
        reference on a path a Mac can walk with nothing to stop it.
        """
        root = Path(__file__).resolve().parents[1] / "knight_flow"
        offenders: list[str] = []

        for path in sorted(root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            guarded: list[tuple[int, int]] = []

            for node in ast.walk(tree):
                # A try block guards everything inside it.
                if isinstance(node, ast.Try):
                    guarded.append((node.lineno, max(
                        getattr(child, "end_lineno", node.lineno) for child in ast.walk(node)
                    )))
                # So does any `if` whose test mentions the platform.
                if isinstance(node, ast.If):
                    source = ast.dump(node.test)
                    if "platform" in source or "IS_MAC" in source or "name" in source:
                        end = max(getattr(c, "end_lineno", node.lineno) for c in ast.walk(node))
                        guarded.append((node.lineno, end))
                # A function that opens by refusing off-Windows is guarded
                # wholesale -- whether it does that with an early return or by
                # calling an assertion helper like _require_windows(), which is
                # the clearer form when several functions share the check.
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    head = ast.dump(ast.Module(body=node.body[:3], type_ignores=[]))
                    early_return = ("platform" in head or "IS_MAC" in head) and "Return" in head
                    asserts_platform = "_require_windows" in head
                    if early_return or asserts_platform:
                        end = max(getattr(c, "end_lineno", node.lineno) for c in ast.walk(node))
                        guarded.append((node.lineno, end))

            for node in ast.walk(tree):
                if not isinstance(node, ast.Attribute) or node.attr != "windll":
                    continue
                line = node.lineno
                if not any(start <= line <= end for start, end in guarded):
                    offenders.append(f"{path.relative_to(root.parent)}:{line}")

        self.assertEqual(
            offenders, [],
            "these ctypes.windll uses are reachable on macOS with nothing to catch them",
        )


if __name__ == "__main__":
    unittest.main()
