"""X-466: copying an ordinary word twice is not a spelling correction.

His report, 2026-09-05: "audio auto-word capture, if a user copies something
twice, it stores as a new single word in the dictionary."

`looks_learnable` sets a deliberately high bar with the reason written beside
it: a false add interrupts with a pop-over and pollutes the dictionary, while
a miss costs nothing. A second path then let any plain word in on its second
appearance on the clipboard, which is something people do all day with a name
or an address.

Worse, the caller treated the "offer" verdict exactly like "learn" -- both
called `remember()` and the difference reached the log alone -- so the setting
meant to ask never asked and the pop-over was an undo rather than a question.
"""
from __future__ import annotations

import copy
import re
import unittest
from pathlib import Path

from knight_flow.learned_words import looks_learnable, note_fix_evidence

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "knight_flow" / "app.py").read_text(encoding="utf-8")
OVERLAY = (ROOT / "knight_flow" / "overlay.py").read_text(encoding="utf-8")


def fresh() -> dict:
    return {"dictionary": {"auto_learn": True}}


class APlainWordIsNeverStoredOnRepetitionTests(unittest.TestCase):
    def test_the_second_copy_only_offers(self) -> None:
        config = fresh()
        self.assertEqual(note_fix_evidence("Ramble", config, 1000.0), "ignore")
        self.assertEqual(note_fix_evidence("Ramble", config, 1100.0), "offer")

    def test_a_third_and_fourth_copy_do_not_escalate_to_learn(self) -> None:
        config = fresh()
        verdicts = [note_fix_evidence("Copper", config, 1000.0 + n * 60) for n in range(4)]
        self.assertNotIn("learn", verdicts, verdicts)

    def test_a_shape_nobody_types_by_accident_still_learns_at_once(self) -> None:
        """The case the feature was built for, unchanged."""
        for token in ("SAHVVV", "B2B", "build@knightaiav.com", "iPhone"):
            with self.subTest(token=token):
                self.assertTrue(looks_learnable(token))
                self.assertEqual(note_fix_evidence(token, fresh(), 1000.0), "learn")


class AnOfferIsAQuestionNotADecisionTests(unittest.TestCase):
    def test_the_caller_only_remembers_on_learn(self) -> None:
        tick = re.search(r"def _clipboard_learn_tick.*?\n    def ", APP, re.S).group(0)
        self.assertIn('if verdict == "learn" and remember(captured, self.config):', tick)
        self.assertNotIn('if verdict != "ignore" and remember(', tick,
                         "an offer is being stored before anybody is asked")

    def test_an_offer_shows_a_pop_over_that_writes_only_on_yes(self) -> None:
        tick = re.search(r"def _clipboard_learn_tick.*?\n    def ", APP, re.S).group(0)
        branch = tick[tick.index('elif verdict == "offer":'):]
        self.assertIn("def accept(", branch)
        self.assertIn("remember(word, self.config)", branch)
        self.assertIn("offer_learned_word(captured, accept)", branch)

    def test_the_pop_over_asks_rather_than_announces(self) -> None:
        self.assertIn("def offer_learned_word(self, word: str, on_accept: Any) -> None:", OVERLAY)
        self.assertIn('label_text = f"Add “{word}”?" if asking else f"Added “{word}”"', OVERLAY)
        self.assertIn('text="Add" if asking else "Don\'t save",', OVERLAY)
        # Pressing it in asking mode adds the word instead of striking it out.
        button = OVERLAY[OVERLAY.index("def strike_and_reject("):]
        button = button[: button.index("\n        reject.configure")]
        self.assertIn("if asking:", button)
        self.assertIn("on_reject(word)", button)


if __name__ == "__main__":
    unittest.main()
