"""Data-shaped speech comes out as data, spoken numbers as written forms.

The report that created this file, verbatim from a real dictation:

    heard:   "Group one, twelve fifteen p.m. Three people. Group two,
              twelve thirty p.m. Two people."
    shipped: exactly that, as flat prose
    wanted:  Group 1:
             12:15 P.M. (3 People)

             Group 2:
             12:30 P.M. (2 People)

The original wanted form is what Wispr Flow produced for the same speech, and the
first test now applies the September 18 owner-requested undotted AM/PM style. The industry name for the numeric
half is inverse text normalization; the rules here carry the conversions that
are unambiguous from local context, and the model prompt carries the rest.

The counterexamples matter as much as the case: a wrong conversion in prose
is the failure people stop trusting a formatter over, so every rule needs an
anchor -- a meridiem for times, a repeated label plus digit-bearing payloads
for record blocks -- and refuses without one.
"""
from __future__ import annotations

import unittest

from knight_flow.formatting import (
    FORMAT_SYSTEM_PROMPT,
    _convert_spoken_times,
    _refine_formatted_output,
    _shape_record_blocks,
    _small_number,
    _valid_formatter_output,
    heuristic_format,
)


WANTED = (
    "Group 1:\n"
    "12:15 PM (3 People)\n"
    "\n"
    "Group 2:\n"
    "12:30 PM (2 People)"
)
HEARD = "Group one, twelve fifteen p.m. Three people. Group two, twelve thirty p.m. Two people."


class TheReportedCaseTests(unittest.TestCase):
    def test_the_exact_transcript_renders_exactly_as_wanted(self) -> None:
        self.assertEqual(WANTED, _refine_formatted_output(HEARD))

    def test_the_heuristic_fallback_path_reaches_the_same_answer(self) -> None:
        """The original failure happened on the rules path -- the model was
        down behind a 402 -- so the rules path is the one that must not
        regress. Every formatting path funnels through the same refine."""
        self.assertEqual(WANTED, _refine_formatted_output(heuristic_format(HEARD)))

    def test_a_correct_model_answer_passes_through_untouched(self) -> None:
        """When the model already produced the written form, refine must not
        double-convert or restructure it."""
        self.assertEqual(WANTED, _refine_formatted_output(WANTED))

    def test_the_validator_accepts_the_conversion(self) -> None:
        """"twelve" and "12" are the same content. Before the canonical pass,
        a perfect model answer was rejected for having "lost" the number
        words -- which silently forbade the model from ever doing ITN."""
        self.assertTrue(_valid_formatter_output(HEARD, WANTED, preserve_meaning=True))


class SpokenTimeTests(unittest.TestCase):
    def test_the_common_forms(self) -> None:
        cases = {
            "the meeting is at six forty five p m tomorrow": "the meeting is at 6:45 PM tomorrow",
            "see you at twelve fifteen p.m. sharp": "see you at 12:15 PM sharp",
            "call me at nine a m": "call me at 9 AM",
            "nine oh five a.m. works": "9:05 AM works",
            "twelve o'clock p m": "12 PM",
            "it starts at 7 30 pm": "it starts at 7:30 PM",
        }
        for heard, wanted in cases.items():
            with self.subTest(heard=heard):
                self.assertEqual(wanted, _convert_spoken_times(heard))

    def test_no_meridiem_means_no_conversion(self) -> None:
        """"twelve fifteen" alone could be a time, a price or a year. The
        meridiem is the anchor that makes the reading unambiguous, and
        without it the words stay words."""
        self.assertEqual(
            "I counted twelve fifteen times",
            _convert_spoken_times("I counted twelve fifteen times"),
        )

    def test_nonsense_hours_are_left_alone(self) -> None:
        self.assertEqual(
            "thirty p.m. is not a time",
            _convert_spoken_times("thirty p.m. is not a time"),
        )


class RecordBlockSafetyTests(unittest.TestCase):
    def test_narrative_with_the_same_openings_stays_prose(self) -> None:
        """"Group one was late" is a sentence about group one, not a record.
        Verbs and pronouns are the tell, and one narrative payload aborts
        the whole conversion -- a half-converted roster is worse than
        either form."""
        text = "Group one was late. Group two never came."
        self.assertEqual(text, _shape_record_blocks(_convert_spoken_times(text)))

    def test_a_roster_mentioned_mid_sentence_stays_prose(self) -> None:
        text = "I told them about Group one, 12:15 PM Three people came anyway."
        self.assertEqual(text, _shape_record_blocks(text))

    def test_mixed_labels_are_not_a_roster(self) -> None:
        text = "Group one, 12:15 PM Table two, 12:30 PM"
        self.assertEqual(text, _shape_record_blocks(text))

    def test_payloads_without_a_single_digit_stay_prose(self) -> None:
        text = "Option one, the quiet approach. Option two, the loud approach."
        self.assertEqual(text, _shape_record_blocks(text))

    def test_a_single_record_is_a_sentence_not_a_roster(self) -> None:
        text = "Group one, 12:15 PM Three people."
        self.assertEqual(text, _shape_record_blocks(text))

    def test_other_data_shapes_convert_too(self) -> None:
        got = _refine_formatted_output(
            "Table one, six p.m. Four guests. Table two, six thirty p.m. Six guests."
        )
        self.assertEqual(
            "Table 1:\n6 PM (4 Guests)\n\nTable 2:\n6:30 PM (6 Guests)",
            got,
        )


class NumberWordTests(unittest.TestCase):
    def test_small_numbers_parse(self) -> None:
        for words, value in (("twelve", 12), ("forty five", 45), ("forty-five", 45), ("7", 7), ("twenty", 20)):
            self.assertEqual(value, _small_number(words), words)

    def test_junk_does_not(self) -> None:
        for words in ("banana", "twelve banana", ""):
            self.assertIsNone(_small_number(words), words)


class PromptCarriesTheStandardTests(unittest.TestCase):
    def test_the_model_is_taught_the_same_example(self) -> None:
        """The rules cover the unambiguous cases; everything contextual is the
        model's job, so the prompt must carry the exact reported case and the
        ITN principle. If this fails, the "brain" half of the fix is gone."""
        self.assertIn("DATA-SHAPED SPEECH", FORMAT_SYSTEM_PROMPT)
        self.assertIn("12:15 PM (3 People)", FORMAT_SYSTEM_PROMPT)
        self.assertIn("support@help.com", FORMAT_SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()
