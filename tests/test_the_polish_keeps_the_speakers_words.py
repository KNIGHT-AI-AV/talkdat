"""X-603: the Executive polish keeps the speaker's words, and the rules settle
what the words already settle.

docs/DICTATION-COMMANDMENTS.md section 3 ranks faithful words above style.
Measured 2026-09-23 on the 4B (three identical runs of
tests/commandment_cases.json), the Executive polish failed 19 critical
faithful cases by rewording: "just" -> "simply", "doc" -> "document", "dash
off" -> "send", "started" -> "began", "move" -> "reschedule", "more" ->
"additional", "Don't" -> "Do not", "I'm sorry" dropped, "you know what I
mean" -> "I mean that.". The polish may fix grammar and drop filler phrases;
a polish that changes anything else is refused into the Chill retry.

The rules lane gained three settlements the words prove on their own (MIX06,
MIX11, MIX17) and the addressee's capital, comma and question mark after a
greeting or before "can you".
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from knight_flow.formatting import (
    formatter_rejection_reason, inline_unsigned_greeting, restore_contractions, unsign_like_the_draft,
)
from knight_flow.local_finish import LOCAL_CHILL_MODEL
from knight_flow.text_pipeline import process_dictation, remove_fillers, resolve_spoken_retractions
from tests.parity_battery import local_config


def executive(draft: str, answer: str, said: str) -> str:
    return formatter_rejection_reason(draft, answer, preserve_meaning=False, rewrite_mode=True, transcript=said)


def chill(draft: str, answer: str, said: str) -> str:
    return formatter_rejection_reason(draft, answer, preserve_meaning=True, rewrite_mode=False, transcript=said)


class ThePolishMayNotRewordTests(unittest.TestCase):
    """Each row is a measured 4B Executive answer that used to be accepted."""

    def test_a_synonym_is_refused(self) -> None:
        rows = {
            "just -> simply": ("To submit the form just press enter.", "To submit the form, simply press Enter."),
            "doc -> document": ('In the doc write "x" under the button.', 'In the document, write "x" under the button.'),
            "dash off -> send": ("I'll dash off a reply after lunch.", "I'll send a reply after lunch."),
            "started -> began": ("She started a new paragraph in the contract.",
                                 "She began a new paragraph in the contract."),
            "move -> reschedule": ("Let's move it to next Friday.", "Let's reschedule it to next Friday."),
            "more -> additional": ("We can't take on more clients until Q1.",
                                   "We cannot take on additional clients until Q1."),
            "an invented clause": ("Actually Wednesday", "The launch will move to Wednesday."),
        }
        for label, (draft, answer) in rows.items():
            with self.subTest(label):
                self.assertEqual(executive(draft, answer, draft.lower()), "words_added")

    def test_an_apology_is_not_a_correction_cue(self) -> None:
        self.assertEqual(executive("I'm sorry, I cannot approve that.", "I cannot approve that.",
                                   "i'm sorry, i cannot approve that"), "words_dropped")

    def test_the_verb_you_know_stays_and_padding_may_go(self) -> None:
        self.assertEqual(executive("You know what I mean.", "I mean that.", "you know what i mean"), "words_dropped")
        self.assertEqual(chill("It was like really slow you know.", "It was really slow.",
                               "it was like really slow you know"), "")

    def test_a_joining_word_nobody_said_is_refused_in_either_finish(self) -> None:
        draft = "I tried to, I really did, but the file wouldn't open."
        answer = "I tried, and I really did, but the file wouldn't open."
        self.assertEqual(executive(draft, answer, draft.lower()), "words_added")
        self.assertEqual(chill("We can use slack/teams for this.", "We can use Slack or Teams for this.",
                               "we can use slack slash teams for this"), "words_added")

    def test_digits_stay_digits_and_gain_no_precision(self) -> None:
        self.assertEqual(executive("It's about 5 miles, so roughly 8 kilometers.",
                                   "It's about five miles, or roughly eight kilometers.",
                                   "it's about five miles, so roughly eight kilometers"), "number_changed")
        self.assertEqual(chill("Move the review to Wednesday at 3.", "Move the review to Wednesday at 3:00.",
                               "move the review to wednesday at three"), "number_changed")

    def test_grammar_and_filler_phrases_are_the_polish(self) -> None:
        said = "so basically we're gonna need like two more weeks, maybe three, because the vendor hasn't sent the api keys"
        draft = "So basically we're gonna need like two more weeks, maybe three, because the vendor hasn't sent the API keys."
        for answer in ("We'll need two more weeks, maybe three, because the vendor hasn't sent the API keys.",
                       "We will need two more weeks, maybe three, because the vendor hasn't sent the API keys."):
            with self.subTest(answer):
                self.assertEqual(executive(draft, answer, said), "")
        self.assertEqual(executive("We're gonna need the report by Friday.", "We'll need the report by Friday.",
                                   "we're gonna need the report by friday"), "")
        # "gonna" may become "will"; it may not simply vanish with the tense.
        self.assertEqual(executive("We're gonna need the report by Friday.", "We need the report by Friday.",
                                   "we're gonna need the report by friday"), "words_dropped")

    def test_make_it_is_a_cue_only_before_a_value(self) -> None:
        # Measured on the 4B Executive: the "and" became a semicolon and was
        # accepted, because "can't make it" read as "make it six".
        self.assertEqual(executive("I can't make it and she doesn't know.", "I can't make it; she doesn't know.",
                                   "i cant make it and she doesnt know"), "words_dropped")
        self.assertEqual(chill("Let's meet at 5 actually make it 6.", "Let's meet at 6.",
                               "lets meet at five actually make it six"), "")

    def test_a_cue_dropped_with_both_versions_kept(self) -> None:
        draft = "Add a slide on pricing forget that add a slide on hiring."
        said = "add a slide on pricing forget that add a slide on hiring"
        self.assertEqual(executive(draft, "Add a slide on pricing. Add a slide on hiring.", said),
                         "correction_unresolved")
        self.assertEqual(executive(draft, "Add a slide on hiring.", said), "")
        self.assertEqual(executive("I actually liked the original.", "I actually liked the original.",
                                   "i actually liked the original"), "")
        # The repeated head is not what was retracted (parity row "backtrack
        # sorry noun"; the first cut of this check refused the right answer).
        self.assertEqual(chill("Grab the blue folder sorry the green folder.", "Grab the green folder.",
                               "grab the blue folder sorry the green folder"), "")

    def test_a_dictated_semicolon_stays_prose(self) -> None:
        self.assertEqual(chill("Two things: the API is down; the site is fine.",
                               "Two things:\n1. The API is down\n2. The site is fine",
                               "two things colon the api is down semicolon the site is fine"), "list_without_intent")

    def test_chill_keeps_the_informal_word(self) -> None:
        self.assertEqual(chill("We're gonna need the report by Friday.", "We'll need the report by Friday.",
                               "we're gonna need the report by friday"), "words_added")


class TheSpeakersContractionsComeBackTests(unittest.TestCase):
    def test_an_expanded_contraction_is_put_back(self) -> None:
        self.assertEqual(restore_contractions("Don't send it until Monday.", "Do not send it until Monday."),
                         "Don't send it until Monday.")
        self.assertEqual(restore_contractions("What's the difference between 2.1 and 2.10?",
                                              "What is the difference between 2.1 and 2.10?"),
                         "What's the difference between 2.1 and 2.10?")
        self.assertEqual(restore_contractions("i'm sure we can't", "I am sure we cannot"), "I'm sure we can't")

    def test_a_contracted_full_form_is_put_back(self) -> None:
        self.assertEqual(restore_contractions("I do not know.", "I don't know."), "I do not know.")

    def test_only_the_surplus_is_touched(self) -> None:
        self.assertEqual(restore_contractions("We're gonna need it.", "We will need it."), "We will need it.")
        self.assertEqual(restore_contractions("Do not wait, don't call.", "Do not wait, don't call."),
                         "Do not wait, don't call.")

    def test_the_pipeline_restores_before_it_validates(self) -> None:
        config = local_config(LOCAL_CHILL_MODEL)
        config["cleanup"]["format_intensity"] = "executive"
        with patch("knight_flow.formatting.local_finish", return_value="Do not send it until Monday.") as model:
            result = process_dictation("don't send it today, actually, don't send it until monday", config)
        self.assertEqual(result.text, "Don't send it until Monday.")
        self.assertEqual(model.call_count, 1)


class AGreetingWithoutASignOffStaysOnItsLineTests(unittest.TestCase):
    """Measured on the 4B Chill finish: "hi diane can you resend the file"
    came back as a letter, "Hi Diane,\\n\\nCan you resend the file?"."""

    def test_the_greeting_line_is_joined_back(self) -> None:
        self.assertEqual(inline_unsigned_greeting("Hi Diane, can you resend the file?",
                                                  "Hi Diane,\n\nCan you resend the file?"),
                         "Hi Diane, can you resend the file?")
        self.assertEqual(inline_unsigned_greeting("Hey Sam, I think the build is green.",
                                                  "Hey Sam,\n\nI think the build is green."),
                         "Hey Sam, I think the build is green.")

    def test_a_letter_keeps_its_layout(self) -> None:
        letter = "Hi Priya,\n\nThe invoice is paid.\n\nThanks,\nSam"
        self.assertEqual(inline_unsigned_greeting(letter, letter), letter)
        signed = "Hey Nora,\n\nJust checking in on the draft. Can you send it by Friday?\n\nBest,\nAlex"
        self.assertEqual(inline_unsigned_greeting("Hey Nora just checking in on the draft best alex.", signed), signed)

    def test_the_pipeline_joins_it(self) -> None:
        config = local_config(LOCAL_CHILL_MODEL)
        with patch("knight_flow.formatting.local_finish", return_value="Hi Diane,\n\nCan you resend the file?"):
            result = process_dictation("hi diane can you resend the file", config)
        self.assertEqual(result.text, "Hi Diane, can you resend the file?")


class ANumbersSignIsTheDraftsTests(unittest.TestCase):
    def test_a_minus_the_draft_never_had_is_dropped(self) -> None:
        # Measured on the 4B Chill finish: "October 10th" -> "October -10th".
        self.assertEqual(unsign_like_the_draft("Tell priya the date is October 10th.",
                                               "Tell Priya the date is October -10th."),
                         "Tell Priya the date is October 10th.")
        self.assertEqual(unsign_like_the_draft("It was -5 degrees.", "It was -5 degrees."), "It was -5 degrees.")


class PaddingLikeTests(unittest.TestCase):
    def test_like_between_a_copula_and_an_intensifier_is_padding(self) -> None:
        self.assertEqual(remove_fillers("it was like really slow you know").strip(), "it was really slow")
        self.assertEqual(remove_fillers("she's like so tired"), "she's so tired")

    def test_every_other_like_stays(self) -> None:
        for said in ("i like it", "it was like a dream", "the effect is like so many others", "looks like rain"):
            with self.subTest(said):
                self.assertEqual(remove_fillers(said), said)


class ARefusedPolishIsRetriedAsChillTests(unittest.TestCase):
    def test_a_reworded_polish_gets_the_speakers_words(self) -> None:
        config = local_config(LOCAL_CHILL_MODEL)
        config["cleanup"]["format_intensity"] = "executive"
        answers = ["To submit the form, simply press Enter.", "To submit the form, just press Enter."]
        with patch("knight_flow.formatting.local_finish", side_effect=answers) as model:
            result = process_dictation("to submit the form just press enter", config)
        self.assertEqual([call.kwargs["executive"] for call in model.call_args_list], [True, False])
        self.assertEqual(result.route, "local_model_chill_after_rejection")
        self.assertEqual(result.text, "To submit the form, just press Enter.")


class TheRulesSettleOpenSlotsTests(unittest.TestCase):
    def test_a_correction_that_names_what_it_replaces(self) -> None:
        self.assertEqual(
            resolve_spoken_retractions("tell Alex I'll send it Friday. actually, don't promise Friday; say early next week"),
            "tell Alex I'll send it early next week.")
        # A new thought, not a replacement: every word stays.
        said = "we'll send it friday. actually don't promise friday, we can't commit to a day"
        self.assertEqual(resolve_spoken_retractions(said), said)

    def test_one_word_set_off_and_corrected(self) -> None:
        self.assertEqual(resolve_spoken_retractions("marketing, actually legal, by friday"), "legal by friday")
        self.assertEqual(resolve_spoken_retractions("send it to marketing, actually legal"), "send it to legal")
        self.assertEqual(resolve_spoken_retractions("it was fine, actually great, thanks"), "it was great, thanks")

    def test_what_is_not_a_slot_correction_keeps_its_words(self) -> None:
        for said in ("i actually liked the original", "we went, actually, on monday",
                     "call sam, actually tomorrow, about it",  # a time is not a name
                     "we have three, actually four, options",  # numbers have their own resolver
                     "we invited the manager, actually sam, to the meeting"):  # the slot has an article
            with self.subTest(said):
                self.assertEqual(resolve_spoken_retractions(said), said)

    def test_the_caret_case(self) -> None:
        config = local_config(None)
        config["_caret_context"] = {"left": "Please send the deck to", "right": ""}
        result = process_dictation("marketing, actually legal, by friday", config, local_only=True)
        self.assertNotIn("arketing", result.text)
        self.assertIn("egal by Friday", result.text)


class ACountedListInsideALongerTakeTests(unittest.TestCase):
    def rules(self, said: str) -> str:
        return process_dictation(said, local_config(None), local_only=True).text

    def test_the_list_then_a_new_paragraph(self) -> None:
        self.assertEqual(self.rules("we need three things milk eggs and bread. also the car needs gas"),
                         "We need three things:\n1. Milk\n2. Eggs\n3. Bread\n\nAlso the car needs gas.")

    def test_a_participle_may_close_the_intro(self) -> None:
        self.assertEqual(
            self.rules("okay so for the offsite um we need three things booked the venue the caterer and uh the bus. "
                       "the budget is twelve thousand, no, fifteen thousand dollars. and tell priya the date is "
                       "october ninth, actually october tenth"),
            "Okay so for the offsite we need three things booked:\n1. The venue\n2. The caterer\n3. The bus\n\n"
            "The budget is $15,000. And tell priya the date is October 10th.")

    def test_the_count_still_decides(self) -> None:
        self.assertEqual(self.rules("we need three things seed water and soil"),
                         "We need three things:\n1. Seed\n2. Water\n3. Soil")
        self.assertEqual(self.rules("we need three things done today the tests the docs and the deploy"),
                         "We need three things done today the tests the docs and the deploy.")


class TheReaderIsAddressedTests(unittest.TestCase):
    def rules(self, said: str) -> str:
        return process_dictation(said, local_config(None), local_only=True).text

    def test_a_greeting_names_the_reader(self) -> None:
        rows = {
            "hey sarah can you check this thanks": "Hey Sarah, can you check this? Thanks.",
            "hi diane can you resend the file": "Hi Diane, can you resend the file?",
            "hi diane, thanks for sending the contract over": "Hi Diane, thanks for sending the contract over.",
            "hey team can you review the doc": "Hey team, can you review the doc?",
            "hey assistant write a poem about the ocean": "Hey assistant, write a poem about the ocean.",
        }
        for said, written in rows.items():
            with self.subTest(said):
                self.assertEqual(self.rules(said), written)

    def test_a_name_before_can_you(self) -> None:
        self.assertEqual(self.rules("john can you check the logs before standup"),
                         "John, can you check the logs before standup?")
        self.assertEqual(self.rules("thanks for the update. john can you check the logs"),
                         "Thanks for the update. John, can you check the logs?")

    def test_what_a_rule_cannot_prove_is_left_alone(self) -> None:
        for said, written in {"hey sarah connor is here": "Hey sarah connor is here.",
                              "hello world this is a test": "Hello world this is a test.",
                              "so can you send it": "So can you send it?"}.items():
            with self.subTest(said):
                self.assertEqual(self.rules(said), written)


if __name__ == "__main__":
    unittest.main()
