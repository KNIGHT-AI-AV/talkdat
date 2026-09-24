"""X-544: a crash during delivery must not cost the words.

On 2026-09-14 at 11:26 local the founder's copy died with
`Windows fatal exception: code 0xc0000374` (heap corruption) inside
`snapshot_clipboard`, on the paste path of a finished dictation. The raw audio
survived as a protected voice session and was recovered at the next launch; the
TRANSCRIPT did not reach History, because History is written after delivery and
delivery is what killed the process.

The words were not actually gone at that moment. `write_live_draft` had already
put them on disk -- that is exactly what it exists for. They were destroyed 63
seconds LATER, when the first interim update of his next dictation overwrote the
same draft file. The app recovered his audio, said nothing about the draft that
held his words, and then let the next sentence he spoke erase it.

These tests pin the draft surviving the dictation that follows a crash.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from knight_flow.config import (
    live_draft_path,
    preserve_live_draft_for_recovery,
    recovered_draft_path,
)
from knight_flow.reset import CATEGORY_BY_KEY

HIS_WORDS = "Talk DAT! live draft\nStatus: final-ish\n\nthe sentence the crash ate\n"


class CrashDraftRecoveryTests(unittest.TestCase):
    def test_the_next_dictation_cannot_erase_a_recovered_draft(self) -> None:
        """The reported failure: recovered at 18:37:04, erased at 18:38:07."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch("knight_flow.config.app_dir", return_value=root):
                live_draft_path().write_text(HIS_WORDS, encoding="utf-8")

                kept = preserve_live_draft_for_recovery(save_history=True)

                self.assertIsNotNone(kept)
                self.assertEqual(kept, recovered_draft_path())
                # The next dictation's first interim update lands on the live
                # draft, exactly as it did at 18:38:07.
                live_draft_path().write_text("a brand new sentence\n", encoding="utf-8")
                self.assertIn(
                    "the sentence the crash ate",
                    recovered_draft_path().read_text(encoding="utf-8"),
                )

    def test_history_off_leaves_nothing_on_disk(self) -> None:
        """X-222: off has to mean off, including anything already kept."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch("knight_flow.config.app_dir", return_value=root):
                live_draft_path().write_text(HIS_WORDS, encoding="utf-8")
                recovered_draft_path().write_text("an older crash\n", encoding="utf-8")

                kept = preserve_live_draft_for_recovery(save_history=False)

                self.assertIsNone(kept)
                self.assertFalse(recovered_draft_path().exists())

    def test_an_absent_or_empty_draft_preserves_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch("knight_flow.config.app_dir", return_value=root):
                self.assertIsNone(preserve_live_draft_for_recovery(save_history=True))
                live_draft_path().write_text("   \n", encoding="utf-8")
                self.assertIsNone(preserve_live_draft_for_recovery(save_history=True))
                self.assertFalse(recovered_draft_path().exists())

    def test_clearing_dictation_history_reaches_the_recovered_draft(self) -> None:
        """A new plaintext file the erase paths cannot see is the X-195 bug."""
        self.assertIn(
            recovered_draft_path().name,
            CATEGORY_BY_KEY["history"].paths,
        )


if __name__ == "__main__":
    unittest.main()
