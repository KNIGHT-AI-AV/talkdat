"""X-158: never pack() and grid() into the same parent.

Tk refuses it outright:

    TclError: cannot use geometry manager pack inside <frame> which already
    has slaves managed by grid

The onboarding microphone page did exactly this. `body` gridded into
`self.content` and a "Run Mic Doctor" row packed into the same `self.content`,
so step five of ten raised for every new user: the page drew everything above
that line, then threw, and the button never appeared.

It was invisible for two compounding reasons. Tk routes callback exceptions to
stderr, and a `--windowed` build has no stderr, so nothing was logged. And the
page still looked plausible, because the failure was the ABSENCE of a control
rather than a broken one.

No runtime test would have caught it either: the onboarding GUI tests skip
without a display, which is exactly the environment where the bug is silent.
So this is a static check, and it runs everywhere.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "knight_flow"


def _parent_of(call: ast.Call) -> str | None:
    """The expression a widget was constructed with, rendered back to source.

    Only the first positional argument matters -- in tkinter that is always the
    master. Returned as text so `self.content` and `body` compare as strings
    without needing to resolve anything.
    """
    if not call.args:
        return None
    try:
        return ast.unparse(call.args[0])
    except Exception:
        return None


def mixed_geometry_parents(source: str) -> dict[str, set[str]]:
    """Parents that receive BOTH a .pack() and a .grid() child.

    Walks each function's statements in SOURCE ORDER, keeping a live map of
    variable -> parent, because a name is routinely rebound to a different
    widget further down a long builder. `holder` in open_settings is bound to
    four different widgets under four different parents; collapsing them by
    name reported two conflicts that do not exist. A guard that cries wolf is
    a guard someone deletes, so the binding is reset on every reassignment and
    only the parent in force at the call site counts.
    """
    tree = ast.parse(source)
    offenders: dict[str, set[str]] = {}

    def analyse(scope: ast.AST, name: str) -> None:
        bindings: dict[str, str] = {}
        managed: dict[str, set[str]] = {}

        def visit(node: ast.AST) -> None:
            # Rebinding first: `x = tk.Frame(a)` replaces any earlier parent.
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.value, ast.Call):
                parent = _parent_of(node.value)
                try:
                    key = ast.unparse(node.targets[0])
                except Exception:
                    key = None
                if key is not None:
                    if parent is None:
                        bindings.pop(key, None)
                    else:
                        bindings[key] = parent

            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in {"pack", "grid"}:
                if isinstance(node.func.value, ast.Call):
                    parent = _parent_of(node.func.value)
                else:
                    try:
                        parent = bindings.get(ast.unparse(node.func.value))
                    except Exception:
                        parent = None
                if parent is not None:
                    managed.setdefault(parent, set()).add(node.func.attr)

            for child in ast.iter_child_nodes(node):
                # Nested functions get their own pass, with their own bindings.
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    analyse(child, child.name)
                    continue
                visit(child)

        for statement in getattr(scope, "body", []):
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
                analyse(statement, statement.name)
                continue
            visit(statement)

        for parent, managers in managed.items():
            if len(managers) > 1:
                offenders.setdefault(name, set()).add(parent)

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            analyse(node, node.name)
        elif isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    analyse(item, item.name)

    return offenders


class NoParentGetsTwoGeometryManagersTests(unittest.TestCase):
    def test_the_checker_catches_the_bug_that_shipped(self) -> None:
        """The exact shape of the microphone page, so this cannot rot."""
        source = (
            "def render(self):\n"
            "    body = tk.Frame(self.content)\n"
            "    body.grid(row=1, column=0)\n"
            "    doctor_row = tk.Frame(self.content)\n"
            "    doctor_row.pack(fill='x')\n"
        )
        self.assertEqual(mixed_geometry_parents(source), {"render": {"self.content"}})

    def test_one_manager_per_parent_is_clean(self) -> None:
        source = (
            "def render(self):\n"
            "    body = tk.Frame(self.content)\n"
            "    body.grid(row=1, column=0)\n"
            "    doctor_row = tk.Frame(body)\n"
            "    doctor_row.grid(row=4, column=0)\n"
        )
        self.assertEqual(mixed_geometry_parents(source), {})

    def test_different_parents_may_use_different_managers(self) -> None:
        """Packing into one frame while gridding into another is correct Tk."""
        source = (
            "def render(self):\n"
            "    left = tk.Frame(self.content)\n"
            "    left.grid(row=0, column=0)\n"
            "    chip = tk.Label(left)\n"
            "    chip.pack(side='left')\n"
        )
        self.assertEqual(mixed_geometry_parents(source), {})

    def test_no_shipped_module_mixes_them(self) -> None:
        offenders: dict[str, dict[str, list[str]]] = {}
        for path in sorted(PACKAGE.rglob("*.py")):
            found = mixed_geometry_parents(path.read_text(encoding="utf-8"))
            if found:
                offenders[path.name] = {fn: sorted(parents) for fn, parents in found.items()}
        self.assertEqual(
            offenders, {},
            "these parents receive both pack() and grid(), which Tk refuses at "
            f"runtime: {offenders}",
        )


if __name__ == "__main__":
    unittest.main()
