from __future__ import annotations

import unittest
from unittest.mock import patch

from knight_flow.learned_words import remember, remember_correction
from knight_flow.name_repair import repair_names
from knight_flow.text_pipeline import (
    apply_vocabulary_terms, complete_prepared_dictation, prepare_dictation,
)
from knight_flow.vocabulary import Term, apply_vocabulary


class CommonWordsSurvivePersonalSpellingsTests(unittest.TestCase):
    def test_learned_wild_keeps_the_owners_would_sentences(self) -> None:
        config: dict = {}
        remember("WILD", config)
        for text in (
            "Our branding would be similar.",
            "We would record harmonies.",
            "It would be high quality, and we would do a study.",
            '"Would" is an everyday word.',
        ):
            with self.subTest(text=text):
                self.assertEqual(apply_vocabulary_terms(text, config), text)

    def test_a_manually_saved_word_also_keeps_common_prose(self) -> None:
        config = {"dictionary": {"words": ["WILD"]}}
        self.assertEqual(apply_vocabulary_terms("I would like that.", config),
                         "I would like that.")

    def test_other_sound_collisions_are_protected_too(self) -> None:
        for text, spelling in (("We have one.", "HIVE"),
                               ("I made it.", "MODE"),
                               ("Those are good.", "GUIDE")):
            with self.subTest(text=text):
                self.assertEqual(apply_vocabulary(text, [Term(spelling)]), text)

    def test_exact_saved_spelling_keeps_the_requested_case(self) -> None:
        self.assertEqual(apply_vocabulary("would you help?", [Term("WOULD")]),
                         "WOULD you help?")
        config: dict = {}
        remember("WILD", config)
        self.assertEqual(apply_vocabulary_terms("That was wild.", config),
                         "That was WILD.")

    def test_a_deliberate_pronunciation_alias_is_honored(self) -> None:
        config: dict = {}
        self.assertTrue(remember_correction("would", "WILD", config))
        self.assertEqual(apply_vocabulary_terms("The brand is would.", config),
                         "The brand is WILD.")

    def test_learned_names_and_product_aliases_still_work(self) -> None:
        config: dict = {}
        remember("Mayowa", config)
        self.assertEqual(apply_vocabulary_terms("ask my yo wa about it", config),
                         "ask Mayowa about it")
        self.assertEqual(apply_vocabulary_terms("I built talk that for Windows", config),
                         "I built Talk DAT! for Windows")

    def test_low_confidence_does_not_turn_common_words_into_names(self) -> None:
        for text, spelling, word in (("We would record.", "WILD", "would"),
                                     ("We have one.", "HIVE", "have"),
                                     ("I made it.", "MODE", "made")):
            config = {"dictionary": {"words": [spelling]}, "_asr_confidence": {word: 0.3}}
            with self.subTest(text=text):
                self.assertEqual(repair_names(text, config), text)

    def test_low_confidence_keeps_exact_personal_case_and_real_names(self) -> None:
        config = {"dictionary": {"words": ["WOULD", "Kaelyn"]},
                  "_asr_confidence": {"would": 0.3, "kalen": 0.4}}
        self.assertEqual(repair_names("I would ask kalen.", config), "I WOULD ask Kaelyn.")

    def test_the_delivered_text_preserves_the_owners_would_example(self) -> None:
        raw = "Our branding would be similar, but it would be high quality."
        for level in ("none", "light"):
            for confidence in ({}, {"would": 0.3}):
                config = {"cleanup": {"level": level, "smart_format": False},
                          "_asr_confidence": confidence}
                remember("WILD", config)
                with self.subTest(level=level, confidence=confidence):
                    prepared = prepare_dictation(raw, config, local_only=True)
                    with patch("knight_flow.text_pipeline.plugin_text_filters", return_value=[]), \
                            patch("knight_flow.format_journal.record_formatting"):
                        delivered = complete_prepared_dictation(prepared, config, local_only=True)
                    self.assertEqual(delivered.text, raw)

    def test_the_delivered_text_honors_a_deliberate_alias(self) -> None:
        config = {"cleanup": {"level": "none", "smart_format": False},
                  "_asr_confidence": {"would": 0.3}}
        remember_correction("would", "WILD", config)
        prepared = prepare_dictation("The brand is would.", config, local_only=True)
        with patch("knight_flow.text_pipeline.plugin_text_filters", return_value=[]), \
                patch("knight_flow.format_journal.record_formatting"):
            delivered = complete_prepared_dictation(prepared, config, local_only=True)
        self.assertEqual(delivered.text, "The brand is WILD.")


if __name__ == "__main__":
    unittest.main()
