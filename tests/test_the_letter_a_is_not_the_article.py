"""His own dictation, 2026-10-26: the letter A read as the article "a", twice in one take.

He was ranking things by letter grade, and the rules route (no formatting model on the machine) changed what he
meant twice. "above a A minus" lost its letter: the stutter rule drops a function word said twice ("the the"), and it
matched "a A" without looking at the capital. Mid-sentence a function word is lowercase, so a capital there is the
letter, a name or a title ("the The Who documentary"), not the same word again. "is above an A." came out "is above
an A...": a thought that stops on an article trails off ("the one thing I wanted was a..."), and that check lowercased
the sentence first, so the letter at the end read as the article. "We should go with plan A." trailed off the same
way. A formatting model that writes "an A minus" for "a A minus" drops no repeat either: the two were never the same
word. The sentences below are made up; only their shapes are his.
"""

from __future__ import annotations

import unittest

from knight_flow import formatting
from knight_flow.text_pipeline import process_dictation
from tests.parity_battery import local_config

LOCAL = {"transforms": {"llm": {"provider": "none"}}}


def rules(said: str) -> str:
    return formatting.smart_format(said, LOCAL, local_only=True)


def dictated(said: str) -> str:
    return process_dictation(said, local_config(None), local_only=True).text


class ACapitalAfterAFunctionWordIsAnotherWordTests(unittest.TestCase):
    def test_the_grade_after_the_article_stays(self) -> None:
        for said, grade in (
            ("only keep the essays graded above a A minus", r"\ban? A minus\b"),
            ("she got a A on the final exam", r"\ban? A on the final\b"),
        ):
            for run in (rules, dictated):
                with self.subTest(said=said, route=run.__name__):
                    self.assertRegex(run(said), grade)

    def test_a_title_after_the_article_stays(self) -> None:
        self.assertIn("the The Who", rules("we watched the The Who documentary last night"))

    def test_a_stuttered_function_word_still_goes(self) -> None:
        for said, settled in (
            ("we need a a new plan for the launch", "We need a new plan for the launch."),
            ("The the dog ran home after lunch", "The dog ran home after lunch."),
            ("yesterday i I think it broke twice", "Yesterday I think it broke twice."),
        ):
            with self.subTest(said=said):
                self.assertEqual(rules(said), settled)


class ASentenceEndingOnTheLetterAEndsTests(unittest.TestCase):
    def test_it_ends_with_a_full_stop(self) -> None:
        for said in (
            "the report would be graded above an A",
            "The report would be graded above an A.",
            "we should go with plan A",
            "after all that work she earned an A",
        ):
            for run in (rules, dictated):
                with self.subTest(said=said, route=run.__name__):
                    out = run(said)
                    self.assertTrue(out.endswith(" A."), out)

    def test_a_thought_that_stops_on_the_article_still_trails_off(self) -> None:
        for said in ("the one thing I really wanted was a", "the thing about the budget is"):
            with self.subTest(said=said):
                out = rules(said)
                self.assertTrue(out.endswith("..."), out)


class AFinishThatWritesAnBeforeTheLetterDropsNoRepeatTests(unittest.TestCase):
    def test_an_before_the_grade_is_accepted(self) -> None:
        self.assertEqual(formatting.formatter_rejection_reason(
            "only keep the essays graded above a A minus", "Only keep the essays graded above an A minus."), "")

    def test_a_repeat_the_finish_drops_is_still_refused(self) -> None:
        self.assertEqual(formatting.formatter_rejection_reason(
            "she had had enough of the noise", "She had enough of the noise."), "repetition_dropped")


if __name__ == "__main__":
    unittest.main()
