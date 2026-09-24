"""X-602: the settled words survive, on the rules lane and past the model.

Each rule below is a docs/DICTATION-COMMANDMENTS.md commandment the 09-23
measurement (section 6.8) found broken, with its counterexample beside it,
because a rule that fires too broadly is how every one of these broke.
"""
from __future__ import annotations

import unittest

from knight_flow.caret_context import join_at_caret
from knight_flow.formatting import formatter_rejection_reason, resolve_value_corrections
from knight_flow.number_text import normalize_numbers
from knight_flow.text_pipeline import (
    process_dictation,
    remove_fillers,
    resolve_restarts,
)
from tests.parity_battery import local_config


def rules(text: str) -> str:
    return process_dictation(text, local_config(None), local_only=True).text


class FillersAreOnlyFillersTests(unittest.TestCase):
    def test_a_hyphenated_response_word_is_a_word(self):
        self.assertEqual(rules("uh-uh, that's not what i said"), "Uh-uh, that's not what I said.")
        self.assertEqual(remove_fillers("uh-huh sounds good"), "uh-huh sounds good")
        self.assertEqual(remove_fillers("uh we should go"), "we should go")

    def test_hedges_stay(self):
        self.assertEqual(rules("it's kind of expensive for what it does"), "It's kind of expensive for what it does.")
        self.assertEqual(rules("so it's kind of, it's kind of expensive"), "So it's kind of expensive.")
        self.assertEqual(rules("it sort of works on my machine"), "It sort of works on my machine.")

    def test_a_hesitation_takes_its_commas_with_it(self):
        self.assertEqual(rules("we need, um, three copies and, uh, a stapler"), "We need three copies and a stapler.")

    def test_um_in_portuguese_is_a_word(self):
        self.assertEqual(rules("the sign says um dia de cada vez"), "The sign says um dia de cada vez.")
        self.assertEqual(rules("um the sign says one day at a time"), "The sign says one day at a time.")


class RestartsKeepTheSettledWordsTests(unittest.TestCase):
    def test_a_closed_class_word_swapped_in_a_restart(self):
        for spoken, settled in (
            ("we might, we will need the second server", "We will need the second server."),
            ("all of the, some of the tests failed", "Some of the tests failed."),
            ("I can, sorry, I cannot approve that", "I cannot approve that."),
            ("I can—sorry, I cannot approve that.", "I cannot approve that."),
            ("it's about, it's exactly fifty dollars", "It's exactly $50."),
            ("the results is, the results are in", "The results are in."),
            ("we don't, we can't take on more clients", "We can't take on more clients."),
        ):
            with self.subTest(spoken=spoken):
                self.assertEqual(rules(spoken), settled)

    def test_a_contraction_restated_in_full(self):
        self.assertEqual(resolve_restarts("don't, do not ship it"), "do not ship it")

    def test_what_is_not_a_restart_keeps_every_word(self):
        for spoken in (
            "we can, we should, we must act",
            "we need a plan, a real plan, before monday",
            "i tried to, i really did, but the file wouldn't open",
            "the first is good, the second is bad",
            "no, no, no",
            "very, very important",
        ):
            with self.subTest(spoken=spoken):
                self.assertEqual(resolve_restarts(spoken), spoken)

    def test_a_correction_that_restates_the_verb_settles_the_negation(self):
        self.assertEqual(rules("don't send it today, actually, send it today"), "Send it today.")
        self.assertEqual(rules("don't send it today, actually, don't send it until monday"), "Don't send it until Monday.")

    def test_i_mean_with_the_same_object_swaps_the_verb(self):
        self.assertIn("merge this", rules("hey sarah can you check this, i mean merge this, thanks"))
        self.assertNotIn("check", rules("hey sarah can you check this, i mean merge this, thanks"))


class ValueCorrectionsTests(unittest.TestCase):
    def test_a_bare_no_between_commas(self):
        self.assertEqual(rules("the deadline is friday, no, monday"), "The deadline is Monday.")
        self.assertEqual(rules("send it to marketing on tuesday, not wednesday"),
                         "Send it to marketing on Tuesday, not Wednesday.")
        # Without the commas "no" is just a word.
        self.assertEqual(resolve_value_corrections("friday no monday"), "friday no monday")

    def test_chains_settle_on_the_last_value(self):
        self.assertEqual(rules("make it fifteen, no, fifty, actually keep it at fifteen"), "Make it 15.")
        self.assertEqual(rules("move the review to tuesday at two, no, three, no wait, wednesday at three"),
                         "Move the review to Wednesday at 3.")

    def test_units_thousands_dates_and_hundreds(self):
        self.assertEqual(
            rules("the upload limit is two hundred megabytes, sorry, two hundred fifty megabytes, and the timeout is "
                  "thirty seconds"),
            "The upload limit is 250 megabytes, and the timeout is 30 seconds.")
        self.assertIn("$15,000", rules("the budget is twelve thousand, no, fifteen thousand dollars"))
        self.assertIn("October 10th", rules("tell priya the date is october ninth, actually october tenth"))
        self.assertIn("450", rules("tell sam the price is four hundred, no, four fifty"))
        self.assertIn("400. No, that's the old price",
                      rules("tell sam the price is four hundred. no, that's the old price"))


class LayoutCommandsNeedCommandPositionTests(unittest.TestCase):
    def test_a_sentence_about_a_paragraph(self):
        self.assertEqual(rules("she started a new paragraph in the contract"),
                         "She started a new paragraph in the contract.")
        self.assertEqual(rules("write a new line of code"), "Write a new line of code.")
        self.assertEqual(rules("i went to the store new paragraph i bought milk"), "I went to the store.\n\nI bought milk.")

    def test_a_take_that_opens_with_a_break(self):
        self.assertEqual(rules("new paragraph the budget is final"), "\n\nThe budget is final.")


class NumbersAndNamesTests(unittest.TestCase):
    def test_hundreds_money_years_versions(self):
        self.assertEqual(rules("the invoice came to twelve hundred dollars and fifty cents"),
                         "The invoice came to $1,200.50.")
        self.assertEqual(rules("the track is twelve hundred meters"), "The track is 1,200 meters.")
        self.assertEqual(normalize_numbers("in nineteen hundred"), "in 1900")
        self.assertEqual(rules("the deadline is september eighteenth twenty twenty seven"),
                         "The deadline is September 18th, 2027.")
        self.assertEqual(rules("what's the difference between version two point one and two point ten"),
                         "What's the difference between version 2.1 and 2.10?")
        self.assertEqual(normalize_numbers("we offer twenty four seven support"), "we offer 24/7 support")
        self.assertEqual(normalize_numbers("fifteen thousand dollars"), "$15,000")
        self.assertEqual(normalize_numbers("two point five thousand dollars"), "$2.5 thousand")

    def test_a_brand_is_never_forced_onto_other_words(self):
        self.assertEqual(rules("we need to get hub caps for the van"), "We need to get hub caps for the van.")
        self.assertEqual(rules("push it to get hub and use c plus plus for the parser"),
                         "Push it to GitHub and use C++ for the parser.")

    def test_dotfiles_and_compounds(self):
        self.assertEqual(rules("run npm install dash dash save dev and check the dot env file"),
                         "Run npm install --save-dev and check the .env file.")
        self.assertEqual(rules("it's a well dash known issue"), "It's a well-known issue.")
        self.assertEqual(rules("the fix is small dash one line dash but it needs a test"),
                         "The fix is small, one line, but it needs a test.")
        self.assertEqual(rules("the answer em dash as always em dash is no"), "The answer, as always, is no.")

    def test_languages_are_proper_adjectives(self):
        self.assertEqual(rules("how do you say thank you in spanish"), "How do you say thank you in Spanish?")
        self.assertEqual(rules("please polish the draft before friday"), "Please polish the draft before Friday.")

    def test_an_unfinished_sentence_is_not_finished(self):
        self.assertEqual(rules("so the thing about the budget is"), "So the thing about the budget is...")
        self.assertEqual(rules("i don't know what it is"), "I don't know what it is.")

    def test_every_word_of_a_leading_and_then(self):
        self.assertEqual(rules("and then we ship it"), "And then we ship it.")

    def test_near_verbatim_composes_no_address(self):
        from tests.parity_battery import preset_config

        config = preset_config(local_config(None), "verbatim")
        # X-607 (spec section 3.1): near-verbatim starts with a capital; the
        # address stays as said.
        self.assertEqual(process_dictation("email jane dot doe at gmail dot com", config, local_only=True).text,
                         "Email jane dot doe at gmail dot com")


class ExactlyOneSpaceAtTheCaretTests(unittest.TestCase):
    def test_after_a_period_or_comma(self):
        self.assertEqual(join_at_caret("Next we test.", {"left": "Done.", "right": ""}), " Next we test.")
        self.assertEqual(join_at_caret("and then", {"left": "first,", "right": ""}), " and then")
        self.assertEqual(join_at_caret("Next", {"left": "Done.\n", "right": ""}), "Next")
        self.assertEqual(join_at_caret("Next", {"left": "Done. ", "right": ""}), "Next")
        self.assertEqual(join_at_caret("hi", {"left": 'He said "', "right": ""}), "hi")
        self.assertEqual(join_at_caret("Done.", {"left": "", "right": "Next"}), "Done. ")


class TheFinishIsCheckedAgainstWhatWasSaidTests(unittest.TestCase):
    """Each refusal named, with the correct answer beside it accepted."""

    def chill(self, draft: str, candidate: str, said: str) -> str:
        return formatter_rejection_reason(draft, candidate, transcript=said)

    def executive(self, draft: str, candidate: str, said: str) -> str:
        return formatter_rejection_reason(draft, candidate, preserve_meaning=False, rewrite_mode=True, transcript=said)

    def test_chill_may_not_merge_a_restart_the_wrong_way(self):
        said = "all of the, some of the tests failed"
        self.assertEqual(self.chill("All of the, some of the tests failed.", "All of the tests failed.", said),
                         "words_dropped")
        # "all" was said (and abandoned), so it is not new; losing "some" is.
        self.assertEqual(self.chill("Some of the tests failed.", "All of the tests failed.", said),
                         "words_dropped")
        self.assertEqual(self.chill("Some of the tests failed.", "All of the tests failed.",
                                    "some of the tests failed"), "words_added")
        self.assertEqual(self.chill("Some of the tests failed.", "Some of the tests failed.", said), "")

    def test_chill_keeps_the_corrected_verb(self):
        said = "hey sarah can you check this, i mean merge this, thanks"
        draft = "Hey sarah can you check this, I mean merge this, thanks."
        self.assertEqual(self.chill(draft, "Hey Sarah, can you check this? Thanks.", said), "correction_reversed")
        self.assertEqual(self.chill(draft, "Hey Sarah, can you merge this? Thanks.", said), "")

    def test_chill_adds_no_word_and_drops_none(self):
        self.assertEqual(self.chill("I'll dash off a reply after lunch.", "I'll reply after lunch.",
                                    "i'll dash off a reply after lunch"), "words_dropped")
        self.assertEqual(self.chill("The flue was blocked.", "The flu was blocked.", "the flue was blocked"),
                         "words_added")
        self.assertEqual(self.chill("It's kind of expensive.", "It's expensive.", "it's kind of expensive"),
                         "words_dropped")
        self.assertEqual(self.chill("I'll drop it at there office.", "I'll drop it at their office.",
                                    "i'll drop it at there office"), "")
        self.assertEqual(self.chill("It was like really slow you know.", "It was really slow.",
                                    "it was like really slow you know"), "")
        self.assertEqual(self.chill("The steps are first open settings second click privacy third turn off sync.",
                                    "The steps are:\n1. Open settings\n2. Click privacy\n3. Turn off sync",
                                    "the steps are first open settings second click privacy third turn off sync"), "")

    def test_no_currency_number_or_joining_word_changes(self):
        self.assertEqual(self.chill("The budget is 10,000.", "The budget is $10,000.", "the budget is ten thousand"),
                         "currency_added")
        self.assertEqual(self.chill("It came to $5.", "It came to $5.", "it came to five dollars"), "")
        self.assertEqual(self.chill("We upgraded to version 2.10.", "We upgraded to version 2-10.",
                                    "we upgraded to version two point ten"), "number_changed")
        self.assertEqual(self.chill("The date is October 10th.", "The date is October -10th.",
                                    "the date is october tenth"), "number_changed")
        said = "do not ship the android build until qa signs off, and the ios build can go out thursday"
        self.assertEqual(self.chill("Do not ship the Android build until QA signs off, and the iOS build can go out "
                                    "Thursday.", "Do not ship the Android build until QA signs off. The iOS build "
                                    "can go out Thursday.", said), "words_dropped")
        self.assertEqual(self.chill("Tell maria it is at 3 PM.", "Tell Maria it is 3 PM.", "tell maria it is at three pm"),
                         "words_dropped")

    def test_portuguese_um_is_language_not_filler(self):
        self.assertEqual(self.chill("The sign says um dia de cada vez.", "The sign says dia de cada vez.",
                                    "the sign says um dia de cada vez"), "language_changed")

    def test_no_word_of_another_language_appears(self):
        self.assertEqual(self.chill("Tell maria que la reunión es mañana at 3 PM.",
                                    "Tell Maria que la reunión es mañana a las 3 PM.",
                                    "tell maria que la reunión es mañana at three pm"), "language_changed")

    def test_executive_keeps_the_voice_the_hedge_and_the_quantifier(self):
        self.assertEqual(self.executive("We cannot accept late submissions.", "Late submissions will not be accepted.",
                                        "we cannot accept late submissions"), "perspective_changed")
        self.assertEqual(self.executive("I think we should wait.", "We should wait.", "i think we should wait"),
                         "hedge_dropped")
        self.assertEqual(self.executive("Some of the tests failed.", "All of the tests failed.",
                                        "some of the tests failed"), "quantifier_changed")
        self.assertEqual(self.executive("We're gonna need the report by Friday.", "We will need the report by Friday.",
                                        "we're gonna need the report by friday"), "")

    def test_without_a_transcript_the_old_contract_holds(self):
        # Direct callers that pass no transcript keep the 09-23 validator.
        self.assertEqual(formatter_rejection_reason("It's kind of expensive.", "It's expensive."), "")


if __name__ == "__main__":
    unittest.main()
