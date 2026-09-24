from __future__ import annotations

import ast
import unittest
from pathlib import Path


OVERLAY = Path(__file__).resolve().parents[1] / "knight_flow" / "overlay.py"


def overlay_tree() -> tuple[str, ast.Module, dict[ast.AST, ast.AST]]:
    source = OVERLAY.read_text(encoding="utf-8")
    tree = ast.parse(source)
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    return source, tree, parents


def owner_name(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> str:
    current: ast.AST | None = node
    while current is not None and not isinstance(current, ast.FunctionDef):
        current = parents.get(current)
    return current.name if isinstance(current, ast.FunctionDef) else ""


class EveryToplevelHasOneChromeRoleTests(unittest.TestCase):
    def test_tk_toplevel_is_created_only_in_the_shared_factory(self) -> None:
        _source, tree, parents = overlay_tree()
        direct: list[tuple[int, str]] = []
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "tk"
                and node.func.attr == "Toplevel"
            ):
                continue
            direct.append((node.lineno, owner_name(node, parents)))
        # Two sites: the factory, and the Pill itself. The Pill hangs off a
        # withdrawn real root (the split root in Overlay.__init__) because on
        # Aqua a borderless, per-pixel-transparent surface is only possible on
        # a Toplevel, and it takes no chrome role: it IS the keyed surface.
        self.assertEqual(sorted(owner for _line, owner in direct), ["__init__", "_new_toplevel"])

    def test_every_factory_call_declares_its_role(self) -> None:
        _source, tree, parents = overlay_tree()
        missing: list[tuple[int, str]] = []
        calls = 0
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "_new_toplevel"
            ):
                continue
            calls += 1
            if not any(keyword.arg == "role" for keyword in node.keywords):
                missing.append((node.lineno, owner_name(node, parents)))
        self.assertGreaterEqual(calls, 16, "the inventory unexpectedly lost a Toplevel")
        self.assertEqual(missing, [])

    def test_context_menu_uses_opaque_native_chrome_not_a_color_key(self) -> None:
        source, tree, _parents = overlay_tree()
        methods = {
            node.name: ast.get_source_segment(source, node) or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
            and node.name in {"_open_context_menu", "_context_menu_background"}
        }
        self.assertNotIn("transparentcolor", methods["_open_context_menu"])
        self.assertNotIn("_apply_window_region", methods["_open_context_menu"])
        self.assertNotIn("rounded_rectangle", methods["_context_menu_background"])
        self.assertIn("draw.rectangle", methods["_context_menu_background"])

    def test_utility_and_rail_resize_paths_never_recut_the_window(self) -> None:
        source, tree, _parents = overlay_tree()
        methods = {
            node.name: ast.get_source_segment(source, node) or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
            and node.name in {"_utility_window", "_attach_menu_rail"}
        }
        for name, body in methods.items():
            with self.subTest(method=name):
                self.assertNotIn("_apply_window_region", body)
                self.assertNotIn("schedule_region", body)
                self.assertNotIn("last_region", body)


if __name__ == "__main__":
    unittest.main()
