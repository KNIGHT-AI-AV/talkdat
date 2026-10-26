"""His own dictation, 2026-10-23: a question after a fronted clause, and the brand heard as "talk TAT".

"When someone says things in a different tone, are we able to actually detect that" reached the chat with a period.
Talk DAT punctuates from the words, and is_question read only the first word: "When" followed by a subject is a
fronted clause ("When I open a window, that window should come to the front"), so it stopped there and never looked
at the clause after it, where the inversion ("are we") is the question. "If you have a minute, could you look at
this" and "Before we ship, do we need another test" fell the same way. The same message also said "usually using talk
TAT": the brand's list of hearings had "talk dat", "talk that" and eight more, but not this one.
"""

from __future__ import annotations

import unittest

from knight_flow import formatting, vocabulary

HIS_SENTENCE = "When someone says things in a different tone, are we able to actually detect that"

QUESTIONS = (
    HIS_SENTENCE,
    "when someone says things in a different tone are we able to actually detect that",
    "If you have a minute, could you look at this",
    "If you have a minute could you look at this",
    "Before we ship, do we need another test",
    "As we discussed, can you send it over",
    "When you get a chance, what do you think of the draft",
    "If you do it can you tell me",
)
STATEMENTS = (
    "When I open a window, that window should come to the front",
    "When I open a window that window should come to the front",
    "If it fails, we retry once",
    "When you get home, call me",
    "Because we can, we should",
    "Because we can we should",
    "If you can, do the dishes",
    "Before we ship, the tests have to pass",
    "When I did it was fine",
    "When I tried it the problem is that it froze",
    "If you know what I mean, you know it works",
)
LOCAL = {"transforms": {"llm": {"provider": "none"}}}


class AQuestionAfterAFrontedClauseTests(unittest.TestCase):
    def test_the_clause_after_the_fronted_one_decides(self) -> None:
        for sentence in QUESTIONS:
            with self.subTest(sentence=sentence):
                self.assertTrue(formatting.is_question(sentence))

    def test_a_fronted_clause_before_a_statement_stays_a_statement(self) -> None:
        for sentence in STATEMENTS:
            with self.subTest(sentence=sentence):
                self.assertFalse(formatting.is_question(sentence))

    def test_his_sentence_ends_on_a_question_mark_through_the_local_formatter(self) -> None:
        for raw in (HIS_SENTENCE + ".", HIS_SENTENCE.lower()):
            with self.subTest(raw=raw):
                self.assertTrue(formatting.smart_format(raw, LOCAL, local_only=True).endswith("?"))
                self.assertTrue(formatting.heuristic_format(raw).endswith("?"))


class TheBrandHeardAsTalkTatTests(unittest.TestCase):
    TERMS = list(vocabulary.DEFAULT_TERMS)

    def test_talk_tat_is_the_brand(self) -> None:
        out = vocabulary.apply_vocabulary(
            "By the way, every text I send you here is usually using talk TAT, so always scan for new issues.",
            self.TERMS)
        self.assertIn("Talk DAT!", out)
        self.assertNotIn("TAT", out)

    def test_the_guard_still_keeps_talk_tat_over_as_said(self) -> None:
        said = "we can talk tat over the weekend"
        self.assertEqual(vocabulary.apply_vocabulary(said, self.TERMS), said)


if __name__ == "__main__":
    unittest.main()
