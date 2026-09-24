from __future__ import annotations

import ast
import unittest
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "knight_flow"

# Modules where a swallowed exception costs someone their text, their history,
# or their money. Decoration and best-effort cosmetics are deliberately not on
# this list: a title bar that fails to draw is worth surviving quietly, and a
# dictation that fails to arrive is not.
CRITICAL_MODULES = (
    "app.py",
    "paste.py",
    "licensing.py",
    "text_pipeline.py",
    "history.py",
    "updater.py",
)

LOG_METHODS = {"warning", "error", "exception", "info", "debug"}


def handler_logs(handler: ast.ExceptHandler) -> bool:
    return any(
        isinstance(node, ast.Attribute) and node.attr in LOG_METHODS
        for statement in handler.body
        for node in ast.walk(statement)
    )


def swallows_silently(handler: ast.ExceptHandler) -> bool:
    """A handler whose whole body is `pass` or a bare `return`, with no log.

    Re-raising, returning a fallback the caller inspects, or setting an error
    field are all fine -- something downstream can still notice. These two
    shapes leave nothing behind at all.
    """
    if handler_logs(handler):
        return False
    body = handler.body
    return len(body) == 1 and isinstance(body[0], (ast.Pass, ast.Return))


class FailuresOnCriticalPathsAreVisibleTests(unittest.TestCase):
    """Every serious defect found on 2026-08-05 failed without saying so.

    Managed cloud answered 503 to every paid request while the site advertised
    it. Three windows built a title bar and never displayed it. A NameError in
    an error handler reached stderr, which a --windowed PyInstaller build does
    not have. The local model list ran 1,526 pixels past the window edge.

    None of those threw anything a user or a log would show. Across the package
    294 exception handlers were counted and 275 of them said nothing, which is
    the shape of the problem rather than a coincidence.

    Fixing all 275 would be wrong -- most guard decoration, where surviving
    quietly is the correct behaviour. This guards the paths where silence costs
    someone their dictation, their transcript history, or their money.
    """

    def offenders(self, module: str) -> list[int]:
        source = (PACKAGE / module).read_text(encoding="utf-8")
        tree = ast.parse(source)
        return [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.ExceptHandler) and swallows_silently(node)
        ]

    def test_every_way_text_can_be_delivered_reports_its_failure(self) -> None:
        """Losing dictated text is the worst thing this product can do, and it
        used to do it without a trace: paste.py had no logger at all, so a
        failed insertion reported itself as a bare False.

        Named rather than counted, because the functions that actually put
        characters into someone's document are the ones that matter, and a
        count would let a new one appear while an old one was deleted.
        """
        source = (PACKAGE / "paste.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        for function in ast.walk(tree):
            if not isinstance(function, ast.FunctionDef):
                continue
            if function.name not in {"_type_text", "replace_typed_text", "replace_by_undo"}:
                continue
            with self.subTest(function=function.name):
                handlers = [n for n in ast.walk(function) if isinstance(n, ast.ExceptHandler)]
                self.assertTrue(handlers, "expected this to guard its keystrokes")
                for handler in handlers:
                    self.assertFalse(
                        swallows_silently(handler),
                        f"{function.name} can fail without saying why, and the "
                        "person is left with missing or half-replaced text",
                    )

    def test_deleting_history_says_so_when_it_does_not_work(self) -> None:
        """The worst silence in the file: someone asked for their transcripts
        to be deleted, the sqlite half failed, and they believe it is gone."""
        source = (PACKAGE / "history.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        clear = next(
            n for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "clear_all_history"
        )
        for handler in (n for n in ast.walk(clear) if isinstance(n, ast.ExceptHandler)):
            self.assertFalse(swallows_silently(handler))

    def test_the_critical_modules_do_not_regress(self) -> None:
        """A budget, not zero.

        The remainder are lookup helpers that return a neutral value the caller
        already checks -- `foreground_window_id` returning 0 is documented as
        deliberate, and `config_int` returning its default is what a parsing
        helper should do. Rewriting those adds risk without removing any.

        16 is where this stands today, not a target -- a budget picked by
        guessing would either pass while the count grew or fail on arrival. It
        only goes down. If it needs to go up, the handler being added is
        probably on the wrong side of this line.
        """
        counts = {module: len(self.offenders(module)) for module in CRITICAL_MODULES}
        total = sum(counts.values())
        self.assertLessEqual(
            total, 16,
            f"silent handlers on critical paths grew: {counts}. "
            "Log the failure, or move the code off the critical path.",
        )

    def test_the_guard_would_notice_a_new_one(self) -> None:
        """Proves the check works, so the suite cannot pass by checking nothing."""
        quiet = ast.parse("try:\n    x()\nexcept Exception:\n    pass\n").body[0].handlers[0]
        loud = ast.parse(
            "try:\n    x()\nexcept Exception:\n    log.warning('why', exc_info=True)\n"
        ).body[0].handlers[0]
        reraises = ast.parse("try:\n    x()\nexcept Exception:\n    raise\n").body[0].handlers[0]
        self.assertTrue(swallows_silently(quiet))
        self.assertFalse(swallows_silently(loud))
        self.assertFalse(swallows_silently(reraises), "re-raising is not swallowing")


if __name__ == "__main__":
    unittest.main()
