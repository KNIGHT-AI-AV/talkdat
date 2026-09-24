from __future__ import annotations

import unittest

from knight_flow.learned_words import already_known, forget, looks_learnable, remember


class OnlyFoughtForSpellingsQualifyTests(unittest.TestCase):
    """A false add interrupts with a pop-over and pollutes the dictionary; a
    miss costs two clicks in the add-words window. The bar sits accordingly."""

    def test_shapes_ordinary_prose_never_takes_are_learnable(self) -> None:
        for word in ("SAHVVV", "iPhone", "McRae", "B2B", "GPT4", "v2ray",
                     "build@knightaiav.com", "user.name", "NVMe"):
            with self.subTest(word=word):
                self.assertTrue(looks_learnable(word))

    def test_ordinary_words_and_sentences_pass_by(self) -> None:
        for text in ("the", "hello", "Tomorrow", "meeting notes",
                     "we should talk that over", "a", "",
                     "this is a whole copied sentence from somewhere"):
            with self.subTest(text=text[:24]):
                self.assertFalse(looks_learnable(text))

    def test_common_vowelless_english_is_not_mistaken_for_an_initialism(self) -> None:
        for word in ("why", "gym", "myth", "rhythm", "hmm"):
            with self.subTest(word=word):
                self.assertFalse(looks_learnable(word))

    def test_true_initialisms_still_qualify(self) -> None:
        for word in ("MSFT", "TDT", "PLLC"):
            with self.subTest(word=word):
                self.assertTrue(looks_learnable(word))


class LearningIsReversibleAndPoliteTests(unittest.TestCase):
    def test_remember_adds_once_and_marks_the_entry_as_learned(self) -> None:
        config: dict = {}
        self.assertTrue(remember("SAHVVV", config))
        self.assertFalse(remember("SAHVVV", config), "the same word was learned twice")
        entry = config["dictionary"]["terms"][0]
        self.assertEqual(entry["text"], "SAHVVV")
        self.assertTrue(entry["learned"])

    def test_the_brand_defaults_count_as_already_known(self) -> None:
        """Copying "Talk DAT!" must not trigger a pop-over about learning it."""
        self.assertTrue(already_known("talk dat!", {}))
        self.assertTrue(already_known("Knight AI+AV", {}))

    def test_forget_removes_only_what_this_feature_added(self) -> None:
        """"Don't save" on a pop-over must never reach a hand-added term."""
        config = {"dictionary": {"terms": [
            {"text": "SAHVVV", "sounds_like": ["salve"]},          # hand-added
            {"text": "NVMe", "sounds_like": [], "learned": True},  # learned
        ]}}
        self.assertFalse(forget("SAHVVV", config))
        self.assertTrue(forget("NVMe", config))
        remaining = [t["text"] for t in config["dictionary"]["terms"]]
        self.assertEqual(remaining, ["SAHVVV"])

    def test_a_learned_word_feeds_the_same_correction_pipeline(self) -> None:
        """Learning is only worth anything if the next dictation uses it."""
        from knight_flow.text_pipeline import apply_vocabulary_terms

        config: dict = {}
        remember("Mayowa", config)
        self.assertEqual(
            apply_vocabulary_terms("ask my yo wa about it", config),
            "ask Mayowa about it",
        )


if __name__ == "__main__":
    unittest.main()
