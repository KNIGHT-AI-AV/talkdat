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
            r'note_local_finish_refusal\(local_finish_refusal\(config\)\)',
            FORMATTING,
            re.S,
        )
        self.assertIsNotNone(block, "the refusal is no longer recorded at the local call site")
        self.assertIn("if not output:", block.group(0))

    def test_the_app_says_it_before_it_says_anything_else(self) -> None:
        """A dictation that came back in rules formatting when Executive was
        asked for is not an ordinary success and must not read like one."""
        self.assertIn("local_notice = take_local_finish_notice()", APP)
        block = APP[APP.index("local_notice = take_local_finish_notice()"):]
        block = block[: block.index("elif guided_sink_still_owned")]
        self.assertIn("Your text was formatted by the built-in rules, not the model.", block)
        self.assertIn('"error"', block)
        # It comes first: the translation branch is now an elif under it.
        self.assertIn("elif translation_error:", block)


if __name__ == "__main__":
    unittest.main()
