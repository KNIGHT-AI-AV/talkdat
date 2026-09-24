"""X-185: a shipped default is not a user's choice.

X-41 set out to stop paid accounts hitting the five-minute wall that cut a long
dictation off mid-sentence. It computed:

    max_seconds = min(int(configured), ceiling) if configured is not None else ceiling

and `configured` is `dictation.get("max_seconds")`, which DEFAULT_CONFIG always
supplies as 300. So for a paid account on the cloud engine, whose ceiling is an
hour, the sum was `min(300, 3600) = 300`. The five-minute wall X-41 existed to
remove WAS the shipped default, and the fix could never fire for anyone.

Nothing failed loudly. The comment above the code described the intended
behaviour, the plan lookup ran, the ceiling was computed correctly, and then the
default quietly won. That is why it survived: every part looked right except the
comparison, which cannot tell "the value we shipped" from "the value they chose".

These tests are written against the decision rather than the code path, so they
stay meaningful if the surrounding lookup is refactored.
"""

from __future__ import annotations

import unittest

from knight_flow.config import DEFAULT_CONFIG


def decide(configured, shipped, ceiling, default):
    """The rule under test, stated once.

    Mirrors the branch in `TalkDatApp` so the reasoning can be exercised without
    a licence manager, an audio device or a display.
    """
    customised = (
        configured is not None and shipped is not None and int(configured) != int(shipped)
    )
    if ceiling is None:
        return int(configured) if configured is not None else default
    if customised:
        return min(int(configured), ceiling)
    return ceiling


class APaidCeilingBeatsAnUntouchedDefaultTests(unittest.TestCase):
    def test_the_exact_case_that_was_broken(self) -> None:
        """Paid, cloud engine, factory settings: an hour, not five minutes."""
        shipped = DEFAULT_CONFIG["dictation"]["max_seconds"]
        self.assertEqual(shipped, 300, "the shipped default moved; update this test deliberately")
        self.assertEqual(
            decide(configured=shipped, shipped=shipped, ceiling=3600, default=300), 3600,
            "an untouched default still caps a paid account at the free limit",
        )

    def test_a_hold_session_too(self) -> None:
        shipped = DEFAULT_CONFIG["dictation"]["hold_max_seconds"]
        self.assertEqual(
            decide(configured=shipped, shipped=shipped, ceiling=36000, default=1800), 36000,
        )


class ADeliberateChoiceIsStillRespectedTests(unittest.TestCase):
    def test_a_smaller_chosen_limit_wins(self) -> None:
        """Someone who asked for two minutes gets two minutes, paid or not."""
        self.assertEqual(decide(configured=120, shipped=300, ceiling=3600, default=300), 120)

    def test_a_chosen_limit_never_exceeds_the_ceiling(self) -> None:
        """The ceiling is the plan's, and a config value cannot buy past it."""
        self.assertEqual(decide(configured=99999, shipped=300, ceiling=3600, default=300), 3600)

    def test_a_choice_that_happens_to_equal_the_default_is_indistinguishable(self) -> None:
        """An honest limitation, recorded rather than hidden.

        Someone who deliberately types 300 gets the ceiling instead. That is the
        acceptable side of the trade: the alternative is capping every paid
        account at the free limit forever, and this direction errs toward giving
        people MORE of what they paid for rather than less.
        """
        self.assertEqual(decide(configured=300, shipped=300, ceiling=3600, default=300), 3600)


class WithNoCeilingNothingChangesTests(unittest.TestCase):
    def test_free_accounts_keep_the_modest_defaults(self) -> None:
        self.assertEqual(decide(configured=300, shipped=300, ceiling=None, default=300), 300)

    def test_a_free_account_can_still_lower_its_own_limit(self) -> None:
        self.assertEqual(decide(configured=60, shipped=300, ceiling=None, default=300), 60)

    def test_a_missing_value_falls_back_to_the_default(self) -> None:
        self.assertEqual(decide(configured=None, shipped=300, ceiling=None, default=300), 300)


class TheShippedCodeUsesThisRuleTests(unittest.TestCase):
    def test_the_app_compares_against_the_shipped_default(self) -> None:
        """Pins the mechanism, not just the arithmetic: without this comparison
        the branch silently reverts to letting the default win."""
        import ast
        from pathlib import Path

        app = Path(__file__).resolve().parents[1] / "knight_flow" / "app.py"
        text = app.read_text(encoding="utf-8")
        block = text[text.index('key = "hold_max_seconds" if hold else "max_seconds"'):][:2200]
        code = " ".join(l for l in block.splitlines() if not l.lstrip().startswith("#"))
        self.assertIn("DEFAULT_CONFIG", code, "the shipped default is no longer consulted")
        self.assertIn("customised", code)
        ast.parse(text)


if __name__ == "__main__":
    unittest.main()
