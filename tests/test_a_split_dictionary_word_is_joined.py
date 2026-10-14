"""A saved word the recognizer splits in two is joined back, but only on its exact letters.

Owner report, 2026-10-12: "OpenAI" is in his dictionary and still comes out "open AI". The recognizer writes it as
two words, and the vocabulary pass keys every word from its first letter, so "open AI" keys as "opna" against
"OpenAI"'s "opn" (similarity 0.75, under the 0.86 bar) and is never repaired. When the writing model joins it
anyway, the meaning check reads the join as two dropped words, and the take falls back to the built-in rules with
the notice. So the repair belongs to the vocabulary pass: a window whose letters ARE the saved word's letters is
that word, split.

The guards keep ordinary speech as said. X-14's "open a" cannot match, because its letters are not "openai". A
first piece that the previous word makes a verb or an adjective ("please open AI settings", "an open AI model",
"to open AI tools") stays as said: a missed correction costs less than a rewritten sentence.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from knight_flow.formatting import formatter_rejection_reason
from knight_flow.text_pipeline import apply_vocabulary_terms, complete_prepared_dictation, prepare_dictation

OPENAI = {"dictionary": {"words": ["OpenAI"]}}


class TheSplitWordIsJoinedTests(unittest.TestCase):
    def test_a_split_saved_word_is_joined_in_any_case(self) -> None:
        for said in ("I asked open AI about the pricing.", "I asked Open AI about the pricing.",
                     "I asked open ai about the pricing."):
            with self.subTest(said=said):
                self.assertEqual(apply_vocabulary_terms(said, OPENAI), "I asked OpenAI about the pricing.")

    def test_it_is_joined_at_the_start_and_the_end_of_a_sentence(self) -> None:
        self.assertEqual(apply_vocabulary_terms("Open AI released a new model.", OPENAI),
                         "OpenAI released a new model.")
        self.assertEqual(apply_vocabulary_terms("We pay open AI.", OPENAI), "We pay OpenAI.")

    def test_another_saved_word_split_before_a_vowel_is_joined_too(self) -> None:
        config = {"dictionary": {"words": ["DataOps"]}}
        self.assertEqual(apply_vocabulary_terms("We run data ops on Fridays.", config),
                         "We run DataOps on Fridays.")

    def test_the_delivered_text_says_openai(self) -> None:
        config = {"cleanup": {"level": "none", "smart_format": False}, "dictionary": {"words": ["OpenAI"]}}
        prepared = prepare_dictation("I asked open AI about the pricing.", config, local_only=True)
        with patch("knight_flow.text_pipeline.plugin_text_filters", return_value=[]), \
                patch("knight_flow.format_journal.record_formatting"):
            delivered = complete_prepared_dictation(prepared, config, local_only=True)
        self.assertEqual(delivered.text, "I asked OpenAI about the pricing.")

    def test_after_the_join_the_meaning_check_keeps_the_models_openai(self) -> None:
        # Before the repair the draft and the transcript said "open AI", and the model's "OpenAI" was refused as
        # words_dropped in both modes: that refusal is one source of the rules-formatting notice.
        joined = apply_vocabulary_terms("I asked open AI about the pricing.", OPENAI)
        for preserve, rewrite in ((True, False), (False, True)):
            with self.subTest(preserve_meaning=preserve, rewrite_mode=rewrite):
                # "" is the check's own word for accepted (its docstring); a reason string is a refusal.
                self.assertEqual(formatter_rejection_reason(
                    joined, "I asked OpenAI about the pricing.", preserve_meaning=preserve,
                    rewrite_mode=rewrite, censor_profanity=False, transcript=joined), "")


class OrdinarySpeechStaysAsSaidTests(unittest.TestCase):
    def test_a_verb_or_adjective_reading_is_left_alone(self) -> None:
        for said in ("Please open AI settings and check it.", "I need to open AI tools today.",
                     "We want an open AI model.", "It should be more open AI research.",
                     "You can open AI tools from the menu."):
            with self.subTest(said=said):
                self.assertEqual(apply_vocabulary_terms(said, OPENAI), said)

    def test_open_a_never_becomes_openai(self) -> None:
        # X-14: "open a" is the bigram the retired brand alias rewrote three times in one message.
        for said in ("Open a new tab.", "Please open a file.", "I will open an account."):
            with self.subTest(said=said):
                self.assertEqual(apply_vocabulary_terms(said, OPENAI), said)

    def test_a_near_spelling_is_not_joined(self) -> None:
        for said in ("I asked open AIs about it.", "I asked opens AI about it.", "I asked open air about it."):
            with self.subTest(said=said):
                self.assertEqual(apply_vocabulary_terms(said, OPENAI), said)

    def test_without_the_saved_word_nothing_is_joined(self) -> None:
        self.assertEqual(apply_vocabulary_terms("I asked open AI about the pricing.", {}),
                         "I asked open AI about the pricing.")


if __name__ == "__main__":
    unittest.main()
