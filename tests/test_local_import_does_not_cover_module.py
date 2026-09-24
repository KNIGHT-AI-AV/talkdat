"""X-153: a name imported INSIDE one function is not available in another.

This shipped and crashed the app on startup for every Windows user:

    knight_flow/app.py, in run
    NameError: name 'sys' is not defined

`app.py` used `sys.platform` in `run()` while importing `sys` only inside
three OTHER functions. The existing guard in test_no_undefined_names is
documented as scope-blind on purpose ("a name bound in any function counts as
defined everywhere") to stay free of false positives, and that is exactly the
blind spot: it saw the three local imports and pronounced the file clean.

The rule here is narrow on purpose, so it keeps that freedom from false
positives while catching the one case the other guard cannot see: a name with
NO module-level binding, read inside a function that does not bind it either,
and not reachable from any enclosing function's scope.
"""

from __future__ import annotations

import ast
import builtins
import unittest
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "knight_flow"

SAFE = set(dir(builtins)) | {
    "__name__", "__file__", "__doc__", "__spec__", "__package__", "__builtins__",
}


def _bindings(node: ast.AST) -> set[str]:
    """Every name this scope binds, without descending into nested scopes."""
    bound: set[str] = set()
    stack = list(ast.iter_child_nodes(node))
    while stack:
        current = stack.pop()
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            # The nested scope's own name is bound here; its body is not.
            bound.add(current.name)
            continue
        if isinstance(current, ast.Lambda):
            continue
        if isinstance(current, (ast.Import, ast.ImportFrom)):
            for alias in current.names:
                bound.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(current, ast.Name) and isinstance(current.ctx, (ast.Store, ast.Del)):
            bound.add(current.id)
        elif isinstance(current, ast.arg):
            bound.add(current.arg)
        elif isinstance(current, ast.ExceptHandler) and current.name:
            bound.add(current.name)
        elif isinstance(current, (ast.Global, ast.Nonlocal)):
            bound.update(current.names)
        stack.extend(ast.iter_child_nodes(current))
    return bound


def _arguments(node: ast.AST) -> set[str]:
    args = getattr(node, "args", None)
    if not isinstance(args, ast.arguments):
        return set()
    collected = {a.arg for a in (*args.posonlyargs, *args.args, *args.kwonlyargs)}
    for extra in (args.vararg, args.kwarg):
        if extra:
            collected.add(extra.arg)
    return collected


def _reads(node: ast.AST) -> dict[str, int]:
    """Names this scope reads, excluding nested scopes' bodies."""
    seen: dict[str, int] = {}
    stack = list(ast.iter_child_nodes(node))
    while stack:
        current = stack.pop()
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        if isinstance(current, ast.Name) and isinstance(current.ctx, ast.Load):
            seen.setdefault(current.id, current.lineno)
        stack.extend(ast.iter_child_nodes(current))
    return seen


def unbound_in_function_scope(source: str) -> dict[str, int]:
    tree = ast.parse(source)
    module_level = _bindings(tree) | SAFE

    offenders: dict[str, int] = {}

    def walk(node: ast.AST, enclosing: set[str]) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                visible = enclosing | _bindings(child) | _arguments(child)
                for name, line in _reads(child).items():
                    if name not in visible:
                        offenders.setdefault(name, line)
                walk(child, visible)
            elif isinstance(child, ast.ClassDef):
                # A class body does not create a scope its methods can read
                # from, so methods keep the enclosing scope, not the class's.
                walk(child, enclosing | _bindings(child))
            else:
                walk(child, enclosing)

    walk(tree, module_level)
    return offenders


class ALocalImportDoesNotCoverTheModuleTests(unittest.TestCase):
    def test_the_checker_sees_the_bug_that_shipped(self) -> None:
        """The exact shape of the crash, so the guard cannot rot into a no-op."""
        source = (
            "import logging\n"
            "\n"
            "def helper():\n"
            "    import sys\n"
            "    return sys.platform\n"
            "\n"
            "def run():\n"
            "    if sys.platform == 'darwin':\n"
            "        return 1\n"
            "    return 0\n"
        )
        self.assertEqual(unbound_in_function_scope(source), {"sys": 8})

    def test_a_module_level_import_is_enough(self) -> None:
        source = (
            "import sys\n"
            "\n"
            "def run():\n"
            "    return sys.platform\n"
        )
        self.assertEqual(unbound_in_function_scope(source), {})

    def test_a_closure_may_read_its_enclosing_function(self) -> None:
        """Guards against the obvious false positive."""
        source = (
            "def outer():\n"
            "    import json\n"
            "    def inner():\n"
            "        return json.dumps({})\n"
            "    return inner\n"
        )
        self.assertEqual(unbound_in_function_scope(source), {})

    def test_arguments_and_comprehensions_are_not_reported(self) -> None:
        source = (
            "def run(items, *rest, flag=False, **kw):\n"
            "    return [x for x in items if x != flag and rest and kw]\n"
        )
        self.assertEqual(unbound_in_function_scope(source), {})

    def test_no_shipped_module_reads_a_name_only_imported_elsewhere(self) -> None:
        offenders: dict[str, dict[str, int]] = {}
        for path in sorted(PACKAGE.rglob("*.py")):
            found = unbound_in_function_scope(path.read_text(encoding="utf-8"))
            if found:
                offenders[path.name] = found
        self.assertEqual(
            offenders, {},
            "names read in a function that neither it nor the module binds: "
            f"{offenders}",
        )


if __name__ == "__main__":
    unittest.main()
