from __future__ import annotations

import unittest

from knight_flow.config import load_config
from knight_flow.text_pipeline import pre_clean_for_format, resolve_spoken_retractions


class SpokenRetractionRulesTests(unittest.TestCase):
    """X-68 behaviors 1/2/7 resolve deterministically before the model.

    The formatter prompt asks for these repairs too, but a sampled model is
    a coin with provider-dependent odds -- measured 97% one week, near 50%
    another, same prompt. The canonical shapes carry their own evidence (a
    repeated clause head or an exact repeated phrase), so the rules own
    them and the model can only polish."""

    def test_stutter_restart_retraction_drops_the_retracted_name(self) -> None:
        self.assertEqual(
            resolve_spoken_retractions(
                "How is, how is, not OpenRouter, how is Wispr Flow doing this"
            ),
            "how is Wispr Flow doing this",
        )

    def test_i_mean_replacement_keeps_the_second_take(self) -> None:
        self.assertEqual(
            resolve_spoken_retractions("call mom, I mean call dad, tonight about the thing"),
            "call dad, tonight about the thing",
        )

    def test_repeated_phrase_collapses_to_one_take(self) -> None:
        self.assertEqual(
            resolve_spoken_retractions("we need to, we need to fix this today"),
            "we need to fix this today",
        )

    def test_a_bare_negation_is_meaning_and_survives(self) -> None:
        self.assertEqual(
            resolve_spoken_retractions("do not send it to Sarah"),
            "do not send it to Sarah",
        )
        self.assertEqual(
            resolve_spoken_retractions("the answer is not OpenRouter, it is the local model"),
            "the answer is not OpenRouter, it is the local model",
        )

    def test_ordinary_lists_are_not_stutters(self) -> None:
        self.assertEqual(
            resolve_spoken_retractions("I saw Anna, Beth, and Carol at the fair"),
            "I saw Anna, Beth, and Carol at the fair",
        )


class TheRulesAreActuallyWiredTests(unittest.TestCase):
    """A helper with no caller is not a feature.

    resolve_spoken_retractions shipped in 0.4.69 with a green unit test and
    NOTHING calling it: the end-to-end test kept passing on the formatter
    model's ~97% coin instead of on the deterministic path, and only exposed
    the gap when the provider had a bad night and failed three for three.
    These assert the pipeline itself, with no model in the loop.
    """

    def setUp(self) -> None:
        self.config = load_config()

    def test_the_pipeline_drops_a_retracted_name_without_any_model(self) -> None:
        cleaned = pre_clean_for_format(
            "Um, so I was thinking that we should probably push the release to Friday. "
            "How is, how is, not OpenRouter, how is Wispr Flow doing this",
            self.config,
        )
        self.assertNotIn("OpenRouter", cleaned)
        self.assertIn("Wispr Flow", cleaned)

    def test_the_pipeline_keeps_the_second_take(self) -> None:
        cleaned = pre_clean_for_format("call mom, I mean call dad, tonight about the thing", self.config)
        self.assertNotIn("mom", cleaned)
        self.assertIn("call dad", cleaned)

    def test_the_pipeline_leaves_a_real_negation_alone(self) -> None:
        cleaned = pre_clean_for_format("do not send it to Sarah", self.config)
        self.assertIn("do not send it to Sarah", cleaned)


if __name__ == "__main__":
    unittest.main()
