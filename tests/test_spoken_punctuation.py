from __future__ import annotations

import unittest

from knight_flow.formatting import apply_spoken_punctuation


class SpokenPunctuationIsJudgmentNotAModeTests(unittest.TestCase):
    """X-28. Mayowa's spec: "if I'm saying quote this is what I wanna say end
    quote it should logically put quotes and if I say period out of habit
    then you should logically put a period... it should decipher whether the
    user is wanting 1 thing or another." The preceder guard is the decipher:
    the word before the mark-word tells a noun from a dictated mark."""

    def test_quote_end_quote_becomes_real_quotes(self) -> None:
        self.assertEqual(
            apply_spoken_punctuation("quote this is what I wanna say end quote"),
            '"this is what I wanna say"',
        )
        self.assertEqual(
            apply_spoken_punctuation("she said quote ship it end quote and left"),
            'she said "ship it" and left',
        )

    def test_habitual_period_becomes_a_period(self) -> None:
        self.assertEqual(apply_spoken_punctuation("I will do it period"), "I will do it.")
        self.assertEqual(apply_spoken_punctuation("send the invoice full stop"), "send the invoice.")

    def test_the_noun_period_is_left_alone(self) -> None:
        for sentence in (
            "the trial period ends tomorrow",
            "a period of time passed",
            "each period has its own rules",
            "the grace period is thirty days",
        ):
            with self.subTest(sentence=sentence):
                self.assertEqual(apply_spoken_punctuation(sentence), sentence)

    def test_the_noun_comma_and_colon_are_left_alone(self) -> None:
        for sentence in ("use an oxford comma here", "that colon looks wrong"):
            with self.subTest(sentence=sentence):
                self.assertEqual(apply_spoken_punctuation(sentence), sentence)

    def test_the_rest_of_the_family(self) -> None:
        self.assertEqual(apply_spoken_punctuation("wait comma that is wrong"), "wait, that is wrong")
        self.assertEqual(apply_spoken_punctuation("no exclamation point"), "no!")
        self.assertEqual(apply_spoken_punctuation("is that right question mark"), "is that right?")
        self.assertEqual(
            apply_spoken_punctuation("first item new line second item"),
            "first item\nsecond item",
        )

    def test_a_dictated_mark_never_doubles_a_real_one(self) -> None:
        self.assertEqual(apply_spoken_punctuation("done period."), "done.")


if __name__ == "__main__":
    unittest.main()
