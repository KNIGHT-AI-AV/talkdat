from __future__ import annotations

import unittest

from knight_flow.learned_words import (
    add_tombstone,
    auto_learn_mode,
    forget,
    note_fix_evidence,
    remember,
    tombstoned,
)


class AutoStoreV2Tests(unittest.TestCase):
    """X-80: repetition is the proof for plain words, and a dismissal is
    permanent. Evidence stays on this PC (the X-37 fence)."""

    def setUp(self) -> None:
        self.config: dict = {"dictionary": {}}

    def test_shapely_words_still_learn_on_the_first_fix(self) -> None:
        self.assertEqual(note_fix_evidence("SAHVVV", self.config, 1000.0), "learn")

    def test_a_plain_word_is_offered_on_the_second_fix_never_stored(self) -> None:
        """X-80 stored it on the second sighting; X-466 is his report that
        this was wrong -- "if a user copies something twice, it stores as a
        new single word in the dictionary" -- because copying a name twice is
        ordinary use, not a correction. The second sighting now ASKS."""
        self.assertEqual(note_fix_evidence("Mayowa", self.config, 1000.0), "ignore")
        self.assertEqual(note_fix_evidence("Mayowa", self.config, 2000.0), "offer")

    def test_evidence_older_than_two_weeks_does_not_count(self) -> None:
        self.assertEqual(note_fix_evidence("Mayowa", self.config, 1000.0), "ignore")
        fifteen_days = 1000.0 + 15 * 86400
        self.assertEqual(note_fix_evidence("Mayowa", self.config, fifteen_days), "ignore")

    def test_offer_mode_offers_instead_of_learning(self) -> None:
        """Since X-466 every plain word is offered, so this mode no longer
        changes the answer -- it is kept because turning it off still must."""
        self.config["dictionary"]["auto_learn_mode"] = "offer"
        note_fix_evidence("Mayowa", self.config, 1000.0)
        self.assertEqual(note_fix_evidence("Mayowa", self.config, 2000.0), "offer")

    def test_off_mode_ignores_everything(self) -> None:
        self.config["dictionary"]["auto_learn_mode"] = "off"
        self.assertEqual(note_fix_evidence("SAHVVV", self.config, 1000.0), "ignore")

    def test_a_dismissal_is_a_tombstone_and_never_returns(self) -> None:
        remember("SAHVVV", self.config)
        self.assertTrue(forget("SAHVVV", self.config))
        self.assertTrue(tombstoned("SAHVVV", self.config))
        self.assertEqual(note_fix_evidence("SAHVVV", self.config, 5000.0), "ignore")

    def test_known_words_are_never_re_evidenced(self) -> None:
        remember("SAHVVV", self.config)
        self.assertEqual(note_fix_evidence("SAHVVV", self.config, 1000.0), "ignore")

    def test_sentences_and_junk_stay_ignored(self) -> None:
        self.assertEqual(note_fix_evidence("hello there friend", self.config, 1.0), "ignore")
        self.assertEqual(note_fix_evidence("", self.config, 1.0), "ignore")

    def test_mode_defaults_survive_bad_values(self) -> None:
        self.config["dictionary"]["auto_learn_mode"] = "nonsense"
        self.assertEqual(auto_learn_mode(self.config), "auto-on-second")

    def test_tombstones_do_not_duplicate(self) -> None:
        add_tombstone("Word", self.config)
        add_tombstone("word", self.config)
        self.assertEqual(len(self.config["dictionary"]["learn_tombstones"]), 1)


if __name__ == "__main__":
    unittest.main()
