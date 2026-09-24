from __future__ import annotations

import unittest
from unittest import mock
from unittest.mock import patch

from knight_flow.formatting import (
    FORMAT_SYSTEM_PROMPT,
    _refine_formatted_output,
    _repair_question_terminals,
    heuristic_format,
    smart_format,
)
from knight_flow.text_pipeline import process_dictation


# X-465: this module is about the world where local-only is OFF.
#
# Talk DAT! is local-only by default now: the speech route, the formatter and
# the door that lets text leave all read one switch, and a config that has
# never heard of that switch is treated as local-only, which is the right
# answer for a real install upgrading from an older version. The fixtures
# below are bare dicts asking for the managed or bring-your-own-key route, so
# without this they would resolve to local and test nothing they mean to.
#
# That route still exists for anybody who deliberately turns the switch off,
# and it still has to work. Naming the world here is the point: these
# assertions are about the cloud contract, not about whichever default happens
# to be in force.
_LOCAL_ONLY_OFF = mock.patch("knight_flow.stt_registry.local_only", return_value=False)


def setUpModule() -> None:
    _LOCAL_ONLY_OFF.start()


def tearDownModule() -> None:
    _LOCAL_ONLY_OFF.stop()


class FormattingTests(unittest.TestCase):
    def test_question_gets_question_mark(self) -> None:
        self.assertEqual(heuristic_format("how are they doing that"), "How are they doing that?")

    def test_spoken_numbered_list(self) -> None:
        text = "i need three things first make updater real second improve formatting third smooth animations"
        self.assertEqual(
            heuristic_format(text),
            "I need three things:\n"
            "1. Make updater real.\n"
            "2. Improve formatting.\n"
            "3. Smooth animations.",
        )

    def test_bullet_point_commands_are_not_printed(self) -> None:
        self.assertEqual(
            heuristic_format("bullet point updater bullet point formatting bullet point animations"),
            "- Updater\n- Formatting\n- Animations",
        )

    def test_literal_bullet_point_phrase_survives(self) -> None:
        self.assertEqual(
            heuristic_format("do not turn every sentence into a bullet point"),
            "Do not turn every sentence into a bullet point.",
        )

    def test_spoken_punctuation_commands(self) -> None:
        config = {"cleanup": {"smart_format": True, "level": "high", "format_mode": "heuristic"}}
        processed = process_dictation("can we ship this question mark", config)
        self.assertEqual(processed.text, "Can we ship this?")

    def test_literal_question_mark_phrase_survives(self) -> None:
        config = {"cleanup": {"smart_format": True, "level": "high", "format_mode": "heuristic"}}
        processed = process_dictation("this should end with a question mark", config)
        self.assertEqual(processed.text, "This should end with a question mark.")

    def test_backtrack_removes_previous_sentence(self) -> None:
        config = {"cleanup": {"smart_format": True, "level": "high", "format_mode": "heuristic"}}
        processed = process_dictation("use the old logo scratch that use the new talk stone logo", config)
        self.assertEqual(processed.text, "Use the new talk stone logo.")

    def test_run_on_transition_breaks(self) -> None:
        """Sentence boundaries, not line breaks.

        This asserted three separate lines, which is what made ordinary
        dictation read as a transcript: one thought arriving as a ragged
        column. The requirement was always that a run-on utterance gains
        punctuation, and that still holds -- the sentences are simply in a
        paragraph now, which is where sentences go.
        """
        self.assertEqual(
            heuristic_format("fix the updater and then smooth the animation also improve the formatter"),
            "Fix the updater. Then smooth the animation. Also improve the formatter.",
        )

    def test_transition_split_does_not_strand_conjunction(self) -> None:
        """A transition cue starts a new sentence and never leaves "and." alone.

        Previously asserted as separate lines. The sentences are the point; the
        line breaks were an accident of how they were joined.
        """
        out = heuristic_format(
            "we need to update the installer and then verify the microphone recovery "
            "and after that make sure the clipboard stays safe but do not change any "
            "of the user data"
        )
        self.assertIn("We need to update the installer.", out)
        self.assertIn("Then verify the microphone recovery.", out)
        self.assertIn("After that make sure the clipboard stays safe", out)
        self.assertNotIn(" and.", out)
        self.assertNotIn("\n", out, "one thought belongs in one paragraph")

    def test_intro_list_becomes_bullets(self) -> None:
        self.assertEqual(
            heuristic_format("the fixes are clean the left edge, smooth the release bounce, and improve the formatter"),
            "The fixes:\n"
            "- Clean the left edge\n"
            "- Smooth the release bounce\n"
            "- Improve the formatter",
        )

    def test_intro_list_splits_embedded_requirements(self) -> None:
        self.assertEqual(
            heuristic_format(
                "the fixes are clean the left edge, smooth the release bounce, "
                "and improve the formatter it needs to use bullet points "
                "it needs to preserve quotes"
            ),
            "The fixes:\n"
            "- Clean the left edge\n"
            "- Smooth the release bounce\n"
            "- Improve the formatter\n"
            "- Use bullet points\n"
            "- Preserve quotes",
        )

    def test_repeated_requirements_become_bullets(self) -> None:
        self.assertEqual(
            heuristic_format("it needs to look sharp it needs to stay centered it needs to format lists"),
            "- It needs to look sharp.\n"
            "- It needs to stay centered.\n"
            "- It needs to format lists.",
        )

    def test_repeated_requirements_do_not_swallow_following_explanation(self) -> None:
        result = heuristic_format(
            "the speed needs to be addressed we need to speed up the paste "
            "we need to speed up the formatting model look at what I am sending "
            "because the current output shows the problem"
        )
        self.assertNotIn("\n- ", result)
        self.assertIn("Look at what I am sending", result)

    def test_mentioning_a_list_does_not_create_fragment_bullets(self) -> None:
        source = (
            "make sure nothing gets forgotten and a grand list of things to do don't care how many "
            "items you add you can add 50 if you need to as long as it's all exactly what you need"
        )

        result = heuristic_format(source)

        self.assertNotIn("\n- ", result)
        self.assertFalse(result.startswith("- "))
        self.assertIn("you can add 50 if you need to", result.lower())

    def test_common_contractions_are_polished(self) -> None:
        self.assertEqual(
            heuristic_format("im testing this and i dont want ugly contractions"),
            "I'm testing this and I don't want ugly contractions.",
        )

    def test_numbered_item_drops_stranded_connector(self) -> None:
        self.assertEqual(
            heuristic_format(
                "we need three things first make it smooth second speed it up and third keep it centered"
            ),
            "We need three things:\n"
            "1. Make it smooth.\n"
            "2. Speed it up.\n"
            "3. Keep it centered.",
        )

    def test_clear_question_period_is_repaired_without_restructuring(self) -> None:
        self.assertEqual(
            _repair_question_terminals("Send it today. Can you confirm Friday works."),
            "Send it today. Can you confirm Friday works?",
        )

    def test_ai_prompt_explicitly_preserves_announced_order(self) -> None:
        """Assert the rules, not their wording.

        This previously pinned the exact phrase "announces a count", so
        rewording the same rule to "a count is announced" failed the build while
        the behaviour was unchanged. What matters is that each rule is still
        stated somewhere, not the sentence it is stated in.
        """
        lowered = FORMAT_SYSTEM_PROMPT.lower()
        # A numbered list needs an announced count and an ordered sequence.
        self.assertIn("numbered list", lowered)
        self.assertIn("count is announced", lowered)
        self.assertIn("ordered sequence", lowered)
        # A trailing remark after the last item returns to prose. Asserted as
        # the rule rather than the sentence: this pinned "ordered item" and
        # broke when the same rule was reworded to cover bulleted lists too,
        # which is the third time this class has failed for a wording change
        # its own docstring says it should tolerate.
        self.assertIn("after the last item", lowered)
        self.assertIn("returns to prose", lowered)
        # The word "list" alone must not authorise bullets.
        self.assertIn("list, items", lowered)
        self.assertIn("never authorize bullets", lowered)
        # One sentence never becomes several bullets.
        self.assertIn("never split one grammatical sentence", lowered)

    def test_follow_up_request_is_not_glued_to_final_numbered_item(self) -> None:
        """The requirement is that it leaves the item. It now also gets a blank
        line, so it reads as a new thought rather than a fourth step."""
        self.assertEqual(
            _refine_formatted_output(
                "1. Make it smooth.\n"
                "2. Make it fast.\n"
                "3. Keep it centered. Also, install updates inside the app."
            ),
            "1. Make it smooth.\n"
            "2. Make it fast.\n"
            "3. Keep it centered.\n"
            "\n"
            "Also, install updates inside the app.",
        )

    def test_ai_markdown_hard_break_spaces_are_removed(self) -> None:
        self.assertEqual(
            _refine_formatted_output("We need two things:  \n1. Make it smooth.  \n2. Make it fast."),
            "We need two things:\n1. Make it smooth.\n2. Make it fast.",
        )

    def test_explicit_numbered_list_is_the_rules_answer_when_the_model_declines(self) -> None:
        # 2026-09-22: every non-trivial take is offered to the model; the
        # rules list is the draft it finishes and the answer when it declines.
        config = {"cleanup": {"format_mode": "ai"}}
        text = (
            "I need three things. First, fix the animation. Second, speed up the paste. "
            "Third, keep the local history. Also, can you confirm the checksum"
        )
        with patch("knight_flow.formatting.llm_complete", return_value=None) as complete:
            self.assertEqual(
                smart_format(text, config),
                "I need three things:\n"
                "1. Fix the animation.\n"
                "2. Speed up the paste.\n"
                "3. Keep the local history.\n"
                "\n"
                "Also, can you confirm the checksum?",
            )
        complete.assert_called_once()

    def test_short_clear_question_is_offered_to_the_model(self) -> None:
        config = {"cleanup": {"format_mode": "ai"}}
        with patch("knight_flow.formatting.llm_complete", return_value=None) as complete:
            self.assertEqual(
                smart_format("can you confirm whether the installer is ready", config),
                "Can you confirm whether the installer is ready?",
            )
        complete.assert_called_once()

    def test_ambiguous_long_dictation_still_uses_llm(self) -> None:
        config = {"cleanup": {"format_mode": "ai"}}
        text = (
            "The launch plan needs another pass because the current sequence mixes the installer, "
            "the demo, and the privacy explanation in a way that may confuse a new user"
        )
        output = (
            "The launch plan needs another pass. The current sequence mixes the installer, "
            "the demo, and the privacy explanation in a way that may confuse a new user."
        )
        with patch("knight_flow.formatting.llm_complete", return_value=output) as complete:
            self.assertEqual(smart_format(text, config), output)
        complete.assert_called_once()
        request = complete.call_args.args[1]
        self.assertIn("<dictation>\n", request)
        self.assertIn("\n</dictation>", request)
        self.assertIn(text, request)

    def test_profile_tone_is_folded_into_the_bounded_formatting_pass(self) -> None:
        config = {
            "cleanup": {"format_mode": "ai", "tone": "formal", "max_ai_format_ms": 900},
        }
        text = (
            "The release message needs a careful rewrite because the current wording mixes "
            "several unrelated details and may confuse a new user"
        )
        output = (
            "The release message requires revision because its current wording combines "
            "unrelated details and may confuse a new user."
        )
        with patch("knight_flow.formatting.llm_complete", return_value=output) as complete:
            self.assertEqual(smart_format(text, config), output)

        self.assertIn("Use a formal tone", complete.call_args.args[1])
        # The configured base plus the per-word share for this take.
        from knight_flow.formatting import model_budget_seconds

        self.assertEqual(
            complete.call_args.kwargs["timeout_override"], model_budget_seconds(config["cleanup"], text)
        )
        self.assertGreaterEqual(complete.call_args.kwargs["timeout_override"], 0.9)


class IntonationQuestionMarksAreReJudgedTests(unittest.TestCase):
    """Speech providers punctuate by pitch, and trailing hedges rise.

    "...so make sure that I add that to the list?" arrived exactly like that
    from real dictation -- a statement wearing a question mark because the
    voice went up at the end. The mark is now re-judged by the sentence's own
    grammar, and only kept where the words themselves can carry a question or
    the sentence is short enough that pitch is the best evidence there is.
    """

    def test_a_hedged_statement_loses_its_question_mark(self) -> None:
        from knight_flow.formatting import demote_false_questions

        for heard, expected in (
            ("So make sure that I add that to the list?",
             "So make sure that I add that to the list."),
            ("We need to make sure the key mapping works for every feature by the way?",
             "We need to make sure the key mapping works for every feature by the way."),
            ("I think we just need to fine tune that even more?",
             "I think we just need to fine tune that even more."),
        ):
            with self.subTest(heard=heard[:40]):
                self.assertEqual(demote_false_questions(heard), expected)

    def test_fronted_when_clauses_are_statements(self) -> None:
        """X-15, from Mayowa's own dictation: 'When I open a window?' is a
        fronted subordinate clause, not a question -- only an auxiliary right
        after the wh-word ('When do we...') makes it one. A lowercase
        continuation after the mark earns the comma he asked for."""
        from knight_flow.formatting import demote_false_questions

        self.assertEqual(
            demote_false_questions("When I open a window? that window should get the menu"),
            "When I open a window, that window should get the menu",
        )
        self.assertEqual(
            demote_false_questions("Where we landed on pricing is what matters to everyone here?"),
            "Where we landed on pricing is what matters to everyone here.",
        )

    def test_adverbial_questions_with_auxiliaries_survive(self) -> None:
        from knight_flow.formatting import demote_false_questions

        for heard in (
            "When do we actually ship the new release to everyone?",
            "Why is the installer still showing the old artwork today?",
            "How can we make the menu faster for keyboard users overall?",
        ):
            with self.subTest(heard=heard[:40]):
                self.assertEqual(demote_false_questions(heard), heard)

    def test_real_questions_keep_their_mark(self) -> None:
        from knight_flow.formatting import demote_false_questions

        for question in (
            "Can we ship the update this afternoon or not?",
            "What time does the meeting start tomorrow morning?",
            "You already sent the invoice to them, right?",
            "Do you think the second version reads better than the first?",
        ):
            with self.subTest(question=question[:40]):
                self.assertEqual(demote_false_questions(question), question)

    def test_short_declarative_questions_trust_the_provider(self) -> None:
        """"It works?" has no grammatical tell; at that length pitch is the
        only evidence, and the provider heard the pitch."""
        from knight_flow.formatting import demote_false_questions

        self.assertEqual(demote_false_questions("It works?"), "It works?")
        self.assertEqual(demote_false_questions("You're serious?"), "You're serious?")

    def test_only_the_statement_in_a_mixed_dictation_is_demoted(self) -> None:
        from knight_flow.formatting import demote_false_questions

        text = "Can we talk tomorrow? I already sent the file over by the way so just check it?"
        self.assertEqual(
            demote_false_questions(text),
            "Can we talk tomorrow? I already sent the file over by the way so just check it.",
        )


class SpokenListsSurviveTheProvidersNumberFormat(unittest.TestCase):
    """A list must form whether the provider sends words or digits.

    Deepgram runs with `numerals: True`, so "number one" arrives as "number 1".
    The local Whisper models send the words. The list rules matched only the
    words, so on the cloud path no list was ever produced -- and because the
    model was still called and still returned, it looked like the formatter
    was ignoring the request rather than never being reached.

    Reported from real use as "talking just now did not format shit", with a
    log line showing 231 characters in, 230 out, 803ms of model time spent.
    """

    def test_digits_from_the_cloud_provider_make_a_list(self) -> None:
        from knight_flow.formatting import _numbered_from_run_on

        out = _numbered_from_run_on(
            "number 1 fix the login flow number 2 add the export button "
            "number 3 ship the update"
        )
        self.assertIsNotNone(out, "digits from the cloud provider produced no list")
        self.assertIn("1. Fix the login flow.", out)
        self.assertIn("3. Ship the update.", out)

    def test_words_from_the_local_provider_still_make_a_list(self) -> None:
        from knight_flow.formatting import _numbered_from_run_on

        out = _numbered_from_run_on(
            "number one fix the login flow number two add the export button "
            "number three ship the update"
        )
        self.assertIsNotNone(out, "the local provider's spelled-out numbers regressed")
        self.assertIn("1. Fix the login flow.", out)

    def test_a_counted_list_does_not_need_a_punctuated_lead_in(self) -> None:
        """Speech does not pause to punctuate before starting to count.

        The lead-in requirement exists because bare "first" is an adjective as
        often as it is a marker. "number 1" is never an adjective, and demanding
        a comma before it rejected an unmistakable list.
        """
        from knight_flow.formatting import _numbered_from_run_on

        out = _numbered_from_run_on(
            "whatever's happening now is very fast number 1 I like the speed "
            "number 2 the formatting is better number 3 I am testing it"
        )
        self.assertIsNotNone(out, "an unpunctuated lead-in still blocks a counted list")
        self.assertIn("1. I like the speed.", out)

    def test_ordinals_used_as_adjectives_stay_prose(self) -> None:
        """The guard that was relaxed must still hold where it was earning its keep."""
        from knight_flow.formatting import _numbered_from_run_on

        for prose in (
            "The first thing I noticed was the second album is better than the first",
            "My first car was a Honda and the second was a Toyota",
        ):
            with self.subTest(prose=prose[:40]):
                self.assertIsNone(_numbered_from_run_on(prose), "prose was turned into a list")


if __name__ == "__main__":
    unittest.main()
