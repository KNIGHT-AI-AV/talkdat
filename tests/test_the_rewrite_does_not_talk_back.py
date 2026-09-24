"""X-500: the rewrite does the work instead of answering the person.

Mayowa, using 0.4.137 minutes after it shipped: he asked for a reformat, spoke,
and got back

    Certainly. Here is the rewritten text:

sitting above his own words. "Almost like it went to ask ChatGPT. We don't want
that to occur. It just needs to do it."

X-491 caused it and the cause is worth keeping. Rewrite and Fix That used to go
to the managed service, which never chatted. They go to a LOCAL model or the
person's own provider now, and those talk back -- so a class of output that
could not previously exist started arriving, and the cleaner had never had to
handle it. Moving work to a different engine changes the SHAPE of what comes
back, not just where it comes from.

Half of these tests are the failing direction. A preamble stripper that is too
eager silently eats the first line of somebody's writing, which is a far worse
bug than the one it fixes and would be almost impossible to report.
"""
from __future__ import annotations

import unittest

from knight_flow.llm import _clean_llm_output


class ThePreambleIsRemoved(unittest.TestCase):
    def test_the_exact_line_he_saw(self) -> None:
        got = _clean_llm_output(
            "Certainly. Here is the rewritten text:\n\nThe meeting moved to Friday."
        )
        self.assertEqual(got, "The meeting moved to Friday.")

    def test_the_common_variants(self) -> None:
        for reply in (
            "Sure! Here's the rewritten version:\n\nHello there.",
            "Of course. Here is the corrected text:\nHello there.",
            "Here you go:\n\nHello there.",
            "Here is the rewritten text: Hello there.",
            "Rewritten text:\nHello there.",
            "Output: Hello there.",
            "Okay - here's the polished copy:\n\nHello there.",
        ):
            with self.subTest(reply=reply):
                self.assertEqual(_clean_llm_output(reply), "Hello there.")

    def test_thinking_still_goes(self) -> None:
        """The older half of this function has to keep working."""
        got = _clean_llm_output("<think>hmm</think>Certainly. Here is the rewritten text:\nDone.")
        self.assertEqual(got, "Done.")


class RealWritingSurvives(unittest.TestCase):
    """THE HALF THAT MATTERS MORE. Eating a line of his writing would be a
    worse bug than the chatty opener, and much harder for him to notice."""

    def test_a_courtesy_word_alone_is_not_a_preamble(self) -> None:
        for text in (
            "Certainly a good idea, and we should do it.",
            "Sure thing works for me.",
            "Okay so the plan is unchanged.",
        ):
            with self.subTest(text=text):
                self.assertEqual(_clean_llm_output(text), text)

    def test_a_line_ending_in_a_colon_is_not_a_preamble(self) -> None:
        for text in (
            "Dear Sarah:\n\nThanks for the update.",
            "Note: the meeting moved to Friday.",
            "Agenda:\n1. Budget\n2. Hiring",
            "Warning: this deletes everything.",
        ):
            with self.subTest(text=text):
                self.assertEqual(_clean_llm_output(text), text)

    def test_here_is_inside_a_sentence_is_not_a_preamble(self) -> None:
        """The give-away has to be an OPENER, not any occurrence."""
        text = "The report is attached, and here is the summary: revenue rose."
        self.assertEqual(_clean_llm_output(text), text)

    def test_a_reply_that_is_only_a_preamble_is_not_wiped(self) -> None:
        """If stripping would leave nothing, the reply is all we have.
        Returning empty would silently wipe the selection he asked to fix."""
        self.assertNotEqual(_clean_llm_output("Here is the rewritten text:"), "")


if __name__ == "__main__":
    unittest.main()
