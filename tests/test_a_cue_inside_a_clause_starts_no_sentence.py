"""His own dictation, 2026-10-26: a cue word broke a sentence in the middle.

A spoken cue ("also", "plus", "finally", "after that") starts a new sentence when the recognizer returns a run-on:
"fix the updater and then smooth the animation also improve the formatter" is three sentences. The rule split at every
cue wherever it stood, so a grade said as "a A plus" came out "a A. Plus", and "I finally got" came out "I. Finally
got". A subject, an auxiliary or "to" right before the cue means the clause is still open ("we also need", "it was
finally done", "to also check"), and "plus" starts a sentence only when a clause follows it ("plus the service was
fast"); otherwise it is a grade, a sum or a noun ("a B plus", "a big plus for the team"). The sentences below are made
up; only their shapes are his.
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


class ACueInsideAClauseStartsNoSentenceTests(unittest.TestCase):
    def test_his_two_shapes(self) -> None:
        for said, settled in (
            ("she got a A plus on the final exam", "She got a A plus on the final exam."),
            ("after all that work I finally got an A", "After all that work I finally got an A."),
        ):
            for run in (rules, dictated):
                with self.subTest(said=said, route=run.__name__):
                    self.assertEqual(run(said), settled)

    def test_a_subject_keeps_the_clause_open(self) -> None:
        for said, settled in (
            ("we also need to fix the login page", "We also need to fix the login page."),
            ("it finally works on my laptop", "It finally works on my laptop."),
        ):
            with self.subTest(said=said):
                self.assertEqual(rules(said), settled)

    def test_an_auxiliary_keeps_the_clause_open(self) -> None:
        self.assertEqual(rules("the report was finally done by noon"), "The report was finally done by noon.")

    def test_to_keeps_the_clause_open(self) -> None:
        self.assertEqual(rules("remember to also check the logs"), "Remember to also check the logs.")

    def test_plus_without_a_clause_after_it_stays(self) -> None:
        for said, settled in (
            ("he scored a B plus in chemistry", "He scored a B plus in chemistry."),
            ("that is a big plus for the team", "That is a big plus for the team."),
        ):
            with self.subTest(said=said):
                self.assertEqual(rules(said), settled)


class ACueThatOpensAClauseStillStartsOneTests(unittest.TestCase):
    def test_a_new_clause_after_the_cue_starts_a_sentence(self) -> None:
        for said, settled in (
            ("fix the updater and then smooth the animation also improve the formatter",
             "Fix the updater. Then smooth the animation. Also improve the formatter."),
            ("send the notes to them also book the room", "Send the notes to them. Also book the room."),
            ("we shipped the build finally we can rest", "We shipped the build. Finally we can rest."),
            ("the food was great plus the service was fast", "The food was great. Plus the service was fast."),
        ):
            with self.subTest(said=said):
                self.assertEqual(rules(said), settled)


if __name__ == "__main__":
    unittest.main()
