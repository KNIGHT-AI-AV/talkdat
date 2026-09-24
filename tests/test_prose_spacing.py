from __future__ import annotations

import unittest

from knight_flow.config import DEFAULT_CONFIG
from knight_flow.formatting import heuristic_format
from knight_flow.text_pipeline import process_dictation


def spoken(text: str) -> str:
    return process_dictation(text, DEFAULT_CONFIG, local_only=True).text


class SentencesBelongInAParagraphTests(unittest.TestCase):
    """Reported as "the spacing is still stupid as fuck".

    Every sentence was being put on its own line. "Hey Sarah, quick update. The
    build is green. I will deploy tomorrow morning." arrived as three stacked
    lines -- one thought, three sentences, rendered as a ragged column. It read
    as a transcript with line breaks rather than as something a person wrote,
    and it happened on every dictation longer than one sentence, which is most
    of them.

    Paragraphs still exist. A dictated "new paragraph" still splits them, list
    items still keep their own lines. What is gone is the break nobody asked
    for.
    """

    def test_related_sentences_stay_on_one_line(self) -> None:
        out = spoken("Hey Sarah, quick update. The build is green. I will deploy tomorrow morning.")
        self.assertEqual(out, "Hey Sarah, quick update. The build is green. I will deploy tomorrow morning.")
        self.assertNotIn("\n", out)

    def test_a_run_on_utterance_gains_full_stops_not_line_breaks(self) -> None:
        out = heuristic_format("fix the updater and then smooth the animation also improve the formatter")
        self.assertEqual(out.count("."), 3, "the sentences must still be separated")
        self.assertNotIn("\n", out, "but not onto separate lines")

    def test_a_dictated_new_paragraph_still_breaks(self) -> None:
        """The break somebody actually asked for is the one that survives."""
        out = spoken("This is the first thought. New paragraph. This is the second thought.")
        self.assertIn("\n\n", out)

    def test_a_single_sentence_is_unchanged(self) -> None:
        self.assertEqual(spoken("Just one sentence here."), "Just one sentence here.")

    def test_no_line_ends_with_a_space(self) -> None:
        out = spoken("Here are the steps. Number one open the file. Number two edit it.")
        for line in out.splitlines():
            self.assertEqual(line, line.rstrip(), f"trailing space on {line!r}")

    def test_there_are_never_three_newlines_in_a_row(self) -> None:
        """One blank line separates blocks. Two is a gap nobody dictated."""
        out = spoken("Here are the steps. Number one go. Number two stop. After that we are done.")
        self.assertNotIn("\n\n\n", out)


class AListIsSeparatedFromWhatFollowsItTests(unittest.TestCase):
    """A closing thought was being buried inside the last item.

    "Number three save it, after that you can close everything and go home"
    came out as `3. Save it. After that you can close everything and go home.`
    -- the remark reading as part of the step. The AI prompt has always said a
    new remark after the last item returns to prose; the rules never did it.
    """

    def test_a_closing_remark_leaves_the_last_item(self) -> None:
        out = spoken(
            "Here are the steps. Number one open the file. Number two edit it. "
            "Number three save it. After that you can close everything and go home."
        )
        lines = out.splitlines()
        self.assertEqual(lines[3], "3. Save it.")
        self.assertEqual(lines[4], "", "a blank line, so it reads as a new thought")
        self.assertEqual(lines[5], "After that you can close everything and go home.")

    def test_a_trailing_question_is_not_a_list_item(self) -> None:
        """It was becoming a fifth thing to choose between."""
        out = spoken("Okay here is a bullet list. Apples, trees, bicycles, guns. Let me know which one you want.")
        self.assertNotIn("- Let me know", out)
        self.assertIn("\n\nLet me know which one you want.", out)

    def test_a_list_with_no_remark_gains_no_trailing_blank_line(self) -> None:
        out = spoken("Okay here is a bullet list. Apples, trees, bicycles, guns.")
        self.assertFalse(out.endswith("\n"), out)
        self.assertEqual(out.splitlines()[-1], "- Guns")

    def test_a_slightly_longer_entry_is_still_an_entry(self) -> None:
        """Length decides, measured against the list, and the threshold has to
        leave normal variation alone."""
        out = spoken("Give me a numbered list. Wake up, brush teeth, leave the house.")
        self.assertEqual(out.splitlines()[-1], "3. Leave the house")

    def test_items_of_one_list_are_never_separated_by_blank_lines(self) -> None:
        out = spoken("Here are the steps. Number one go. Number two stop.")
        body = out.splitlines()[1:]
        self.assertNotIn("", body)



class CalendarWordsAreCapitalisedWhereTheyAreDatesTests(unittest.TestCase):
    """"we ship on friday" is otherwise correct and still obviously dictated.

    The AI formatter has always been told to capitalise weekdays and months.
    The rules -- which produce the text that appears first, and the only text
    at all when no model is configured -- never did.

    Weekdays are a closed set with no common-word collisions, so they are
    always safe. Months are not: "may" is usually the modal, "march" is usually
    walking, "august" is usually an adjective, and April, May and June are all
    names. A month is only capitalised where the sentence has already said it
    is talking about a date.
    """

    def test_weekdays_are_always_capitalised(self) -> None:
        self.assertEqual(
            spoken("we ship on friday and the review is on monday"),
            "We ship on Friday and the review is on Monday.",
        )

    def test_a_weekday_mid_sentence_is_caught(self) -> None:
        self.assertIn("Tuesday", spoken("send it to john on tuesday"))

    def test_a_month_after_a_date_preposition_is_capitalised(self) -> None:
        self.assertIn("in January", spoken("the deadline is in january"))
        self.assertIn("in May", spoken("the release is in may"))

    def test_a_month_before_a_day_number_is_capitalised(self) -> None:
        self.assertIn("June 5", spoken("the meeting is on june 5"))

    def test_the_modal_may_is_left_alone(self) -> None:
        """The one that would be wrong most often if months were capitalised
        on sight."""
        self.assertEqual(spoken("you may want to check that"), "You may want to check that.")

    def test_ordinary_words_that_happen_to_be_months_are_left_alone(self) -> None:
        for text, word in (("we will march to the office", "march"),
                           ("it is an august decision", "august")):
            with self.subTest(text=text):
                self.assertIn(word, spoken(text))

    def test_code_and_paths_are_left_exactly_as_dictated(self) -> None:
        """A weekday inside backticks is part of a name, not prose."""
        self.assertIn("`cron.friday`", spoken("run the friday script in `cron.friday`"))

    def test_it_does_not_capitalise_in_the_middle_of_a_word(self) -> None:
        for text in ("the mayor called", "we are marching now", "it is sundry"):
            with self.subTest(text=text):
                out = spoken(text)
                self.assertNotIn("May", out)
                self.assertNotIn("March", out)
                self.assertNotIn("Sun", out)

class TheListIntroductionIsProseAndIsFormattedLikeItTests(unittest.TestCase):
    """The lead-in was taken as a raw slice of the recogniser's output.

    Speech-to-text hands over lowercase text and the sentence pass fixes it --
    but the list builder cut the introduction out before that ran, so a
    lowercase sentence sat above a properly capitalised list. It only looked
    right in testing because the examples were typed with capitals already.
    """

    def test_a_lowercase_lead_in_is_capitalised(self) -> None:
        out = spoken("okay here is a bullet list. apples, trees, bicycles, guns.")
        self.assertEqual(out.splitlines()[0], "Okay here is a bullet list:")

    def test_several_sentences_before_the_list_are_all_formatted(self) -> None:
        out = spoken(
            "hey team quick update. the build is green and i pushed it. "
            "here is a bullet list. one, two, three."
        )
        first = out.splitlines()[0]
        self.assertTrue(first.startswith("Hey team"), first)
        self.assertIn("The build is green", first)
        self.assertIn("I pushed it", first, "the bare i has to become I")
        self.assertTrue(first.endswith(":"), first)

    def test_the_lead_in_keeps_exactly_one_colon(self) -> None:
        out = spoken("okay here is a bullet list. apples, trees, bicycles, guns.")
        self.assertEqual(out.splitlines()[0].count(":"), 1)
        self.assertNotIn(".:", out)


if __name__ == "__main__":
    unittest.main()
