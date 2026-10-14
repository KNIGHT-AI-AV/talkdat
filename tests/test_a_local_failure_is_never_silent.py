"""X-465, second half: closing the cloud door must not open a silent one.

Before this, a PC with no local engine had the managed cloud quietly finish
its text. With the door shut, the same PC drops to the rules formatter, and
without this the person would watch Chill and Executive do nothing with no
reason offered anywhere. That is the same silence pointing the other way, and
it is the fault the whole change exists to remove.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from knight_flow.formatting import note_local_finish_refusal, take_local_finish_notice

ROOT = Path(__file__).resolve().parents[1]
FORMATTING = (ROOT / "knight_flow" / "formatting.py").read_text(encoding="utf-8")
APP = (ROOT / "knight_flow" / "app.py").read_text(encoding="utf-8")


class TheReasonSurvivesTheFallbackTests(unittest.TestCase):
    def setUp(self) -> None:
        take_local_finish_notice()  # start clean

    def tearDown(self) -> None:
        take_local_finish_notice()

    def test_the_notice_is_delivered_once(self) -> None:
        note_local_finish_refusal("the local model is not running")
        self.assertEqual(take_local_finish_notice(), "the local model is not running")
        self.assertEqual(take_local_finish_notice(), "", "a single failure must not nag on every dictation after it")

    def test_an_empty_reason_is_not_a_notice(self) -> None:
        note_local_finish_refusal("")
        note_local_finish_refusal("   ")
        self.assertEqual(take_local_finish_notice(), "")

    def test_the_newest_reason_wins(self) -> None:
        note_local_finish_refusal("model not pulled")
        note_local_finish_refusal("machine too slow")
        self.assertEqual(take_local_finish_notice(), "machine too slow")

    def test_formatting_records_it_where_the_engine_declines(self) -> None:
        block = re.search(
            r'if (?:local_route|resolved_llm_provider\(config\) == "ollama"):.*?'
            r'note_local_finish_refusal\(last_local_finish_reason\(\) or local_finish_refusal\(config\)\)',
            FORMATTING,
            re.S,
        )
        self.assertIsNotNone(block, "the refusal is no longer recorded at the local call site")
        self.assertIn("if not output:", block.group(0))

    def test_the_app_says_it_before_it_says_anything_else(self) -> None:
        """A reason the person can act on (no engine, too slow) is said before
        anything else. Since 2026-10-09 (the owner) a per-take fallback, such
        as the meaning check refusing the model's edit, is a normal take and
        only logged: tests/test_quiet_formatting_fallbacks.py."""
        self.assertIn("local_notice = take_local_finish_notice()", APP)
        block = APP[APP.index("local_notice = take_local_finish_notice()"):]
        block = block[: block.index("elif guided_sink_still_owned")]
        self.assertIn("formatting_line = local_finish_feedback(local_notice)", block)
        self.assertIn("if routine_success and formatting_line:\n            self.overlay.set_state(*formatting_line)", block)
        from knight_flow.app import local_finish_feedback
        state, title, _ = local_finish_feedback("too_slow")
        self.assertIn("Your text was formatted by the built-in rules, not the model.", title)
        self.assertEqual(state, "error")
        # It comes first on a routine take; the translation branch is an elif under it.
        # Overwatch's review J-B1 (2026-10-10): a failed translation, like a failed
        # insertion, is the take's own news, so the reason never takes its place
        # (routine_success excludes it), and with Auto paste off the reason follows
        # "Captured locally" (F1). Behaviour: tests/test_quiet_formatting_fallbacks.py.
        self.assertRegex(block, r"elif translation_error(?: and not withheld and not partial_delivery)?:")


if __name__ == "__main__":
    unittest.main()
