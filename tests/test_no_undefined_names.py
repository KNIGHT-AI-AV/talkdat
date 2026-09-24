from __future__ import annotations

import ast
import builtins
import unittest
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "knight_flow"


def unresolved_names(source: str) -> dict[str, int]:
    """Names read but never bound anywhere in the module.

    Deliberately scope-blind: a name bound in any function counts as defined
    everywhere. That makes it useless for finding shadowing mistakes and
    completely reliable for the one thing it is for -- a name that exists
    nowhere at all, which is always a crash rather than a style opinion.
    """
    tree = ast.parse(source)
    defined = set(dir(builtins)) | {"__name__", "__file__", "__doc__", "__spec__", "__package__"}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                defined.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defined.add(node.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            defined.add(node.id)
        elif isinstance(node, ast.arg):
            defined.add(node.arg)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            defined.add(node.name)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            defined.update(node.names)

    found: dict[str, int] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id not in defined:
            found.setdefault(node.id, node.lineno)
    return found


class NoUndefinedNamesTests(unittest.TestCase):
    """A name that does not exist is a crash waiting on the right input.

    overlay.py shipped with `log.warning(...)` in an except block while never
    defining `log`. It was the only logging call in a 9,000-line file, so
    nothing else revealed the missing import. Reaching it raised NameError from
    inside the handler that existed to stop a failure being fatal.

    The path there is worse than a normal crash. It sits in an `after_idle`
    callback, so Tk prints the traceback to stderr, and a --windowed
    PyInstaller build has no stderr. The window opens undecorated and the log
    stays empty -- the same silent-failure shape as the blank unclosable
    settings panel that shipped earlier.

    Imports and syntax are checked by simply running the program. Names on
    error paths are not, because those paths do not run until something else
    has already gone wrong.
    """

    def test_the_checker_catches_a_name_that_exists_nowhere(self) -> None:
        """Proves the guard works wherever it runs.

        Without this the suite could pass by silently checking nothing, which
        is the failure mode of every linter that is configured but not loaded.
        """
        self.assertEqual(unresolved_names("def f():\n    return nope\n"), {"nope": 2})
        self.assertEqual(unresolved_names("import logging\nlog = logging.getLogger(__name__)\nlog.info('x')\n"), {})
        # Bound only inside a function, read at module level: intentionally not
        # reported, so the guard stays free of false positives.
        self.assertEqual(unresolved_names("def f():\n    later = 1\n\nprint(later)\n"), {})

    def test_no_module_reads_a_name_it_never_defines(self) -> None:
        offenders: dict[str, dict[str, int]] = {}
        for path in sorted(PACKAGE.rglob("*.py")):
            found = unresolved_names(path.read_text(encoding="utf-8"))
            if found:
                offenders[path.name] = found
        self.assertEqual(offenders, {}, f"names read but never defined: {offenders}")

    def test_no_function_hides_code_behind_an_unconditional_return(self) -> None:
        """Code after a plain `return` never runs and never gets maintained.

        open_local_models was rewritten to redirect into Settings, and its
        original 900x660 window was left in place below the return -- 195
        lines that read like a live feature, referenced real widgets, and
        could not execute. Anyone reading it to learn how local models are
        presented would have learned the wrong thing.

        Tests do not catch this, because the dead code passes every test by
        never running. Only the parser sees it.
        """
        offenders: list[str] = []
        for path in sorted(PACKAGE.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for index, statement in enumerate(node.body[:-1]):
                    if isinstance(statement, ast.Return):
                        dead = node.body[index + 1].lineno
                        offenders.append(f"{path.name}:{dead} after {node.name} returns")
        self.assertEqual(offenders, [], f"unreachable code: {offenders}")


if __name__ == "__main__":
    unittest.main()
