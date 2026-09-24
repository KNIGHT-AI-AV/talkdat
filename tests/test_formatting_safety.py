from __future__ import annotations

import re
import unittest
from unittest import mock
from unittest.mock import patch

from knight_flow.formatting import _valid_formatter_output, heuristic_format, smart_format
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


LONG_DICTATION = (
    "The launch plan needs another pass because the current sequence mixes the installer, "
    "the demo, and the privacy explanation in a way that may confuse a new user"
)


class FormattingStructureSafetyTests(unittest.TestCase):
    def test_comparative_first_and_second_stay_prose(self) -> None:
        self.assertEqual(
            heuristic_format(
                "the first proposal is faster than the second because it caches the result"
            ),
            "The first proposal is faster than the second because it caches the result.",
        )

    def test_comparative_ordinal_references_without_articles_stay_prose(self) -> None:
        self.assertEqual(
            heuristic_format(
                "we compared first proposal with second proposal and kept the cheaper one"
            ),
            "We compared first proposal with second proposal and kept the cheaper one.",
        )

    def test_ordered_items_preserve_internal_sequence_and_complete_clauses(self) -> None:
        self.assertEqual(
            heuristic_format(
                "first the client should validate the payload and then preserve the checksum "
                "second the server must retry the upload and report any failure"
            ),
            "1. The client should validate the payload and then preserve the checksum.\n"
            "2. The server must retry the upload and report any failure.",
        )

    def test_spoken_bullets_preserve_actors_modals_and_internal_conjunctions(self) -> None:
        config = {"cleanup": {"format_mode": "ai"}}
        text = (
            "bullet point Alice should validate the payload and Bob must preserve the checksum "
            "bullet point Carol can retry the upload and report any failure"
        )
        # 2026-09-22: offered to the model; the rules list stands when it declines.
        with patch("knight_flow.formatting.llm_complete", return_value=None) as complete:
            self.assertEqual(
                smart_format(text, config),
                "- Alice should validate the payload and Bob must preserve the checksum\n"
                "- Carol can retry the upload and report any failure",
            )
        complete.assert_called_once()

    def test_intro_bullets_preserve_complete_parallel_clauses(self) -> None:
        self.assertEqual(
            heuristic_format(
                "the requirements are the client must authenticate and retain its session, "
                "and the worker should retry and report failures"
            ),
            "The requirements:\n"
            "- The client must authenticate and retain its session\n"
            "- The worker should retry and report failures",
        )

    def test_unpunctuated_intro_bullets_split_only_at_new_clause_actors(self) -> None:
        self.assertEqual(
            heuristic_format(
                "the requirements are the client must authenticate and retain its session "
                "and the worker should retry and report failures"
            ),
            "The requirements:\n"
            "- The client must authenticate and retain its session\n"
            "- The worker should retry and report failures",
        )


class FormatterOutputValidationTests(unittest.TestCase):
    CONFIG = {"cleanup": {"format_mode": "ai"}}

    def assert_falls_back(self, output: str, text: str = LONG_DICTATION) -> None:
        with patch("knight_flow.formatting.llm_complete", return_value=output):
            self.assertEqual(smart_format(text, self.CONFIG), heuristic_format(text))

    def test_severe_detail_loss_falls_back(self) -> None:
        self.assert_falls_back("The launch plan needs another pass.")

    def test_one_word_output_falls_back(self) -> None:
        self.assert_falls_back("Done.")

    def test_refusal_output_falls_back(self) -> None:
        self.assert_falls_back("I'm sorry, but I can't help with that.")

    def test_short_source_refusal_output_falls_back(self) -> None:
        self.assert_falls_back("I cannot fulfill this request.", "Send the update now")

    def test_fenced_output_falls_back(self) -> None:
        self.assert_falls_back(
            "```text\n"
            "The launch plan needs another pass. The current sequence mixes the installer, "
            "the demo, and the privacy explanation in a way that may confuse a new user.\n"
            "```"
        )

    def test_malformed_numbered_output_falls_back(self) -> None:
        text = "We need two changes for release: fix the installer, and preserve the existing settings"
        self.assert_falls_back(
            "We need two changes for release:\n"
            "1. Fix the installer.\n"
            "3. Preserve the existing settings.",
            text,
        )

    def test_fragment_bullets_from_one_sentence_fall_back_to_prose(self) -> None:
        text = (
            "make sure nothing gets forgotten and a grand list of things to do don't care how many "
            "items you add you can add 50 if you need to as long as it's all exactly what you need"
        )
        malformed = (
            "- Make sure nothing gets forgotten and a grand list of things to do don't care how many items.\n"
            "- You add you can.\n"
            "- Add 50 if.\n"
            "- You need to. As long as it's all exactly what you need."
        )

        self.assertFalse(_valid_formatter_output(text, malformed))
        self.assert_falls_back(malformed, text)

    def test_ai_cannot_invent_bullets_without_list_intent(self) -> None:
        text = "The formatter should preserve this explanation because it is one continuous thought"
        malformed = (
            "- The formatter should preserve this explanation.\n"
            "- It is one continuous thought."
        )

        self.assertFalse(_valid_formatter_output(text, malformed))

    def test_changed_number_falls_back(self) -> None:
        text = "Ship release 0.3.31 on July 28 with all 12 model files preserved"
        self.assert_falls_back(
            "Ship release 0.3.32 on July 28 with all 12 model files preserved.",
            text,
        )

    def test_removed_negation_falls_back(self) -> None:
        text = "Do not upload the audio because it must remain on this computer"
        self.assert_falls_back(
            "Upload the audio because it must remain on this computer.",
            text,
        )

    def test_changed_url_or_email_falls_back(self) -> None:
        text = "Send the build to dev@example.com and link https://example.com/release"
        self.assert_falls_back(
            "Send the build to support@example.com and link https://example.com/latest.",
            text,
        )

    def test_structural_list_numbers_are_not_treated_as_changed_facts(self) -> None:
        source = "The release needs the installer, updater, and rollback receipt"
        output = (
            "The release needs:\n"
            "1. The installer.\n"
            "2. The updater.\n"
            "3. The rollback receipt."
        )
        self.assertTrue(_valid_formatter_output(source, output))

    def test_quoted_literal_must_survive_formatter(self) -> None:
        source = 'Keep the button label "Paste last" in the recovery menu'
        output = 'Keep the button label "Retry" in the recovery menu.'
        self.assertFalse(_valid_formatter_output(source, output))


class FormatterPrivacyTests(unittest.TestCase):
    def test_remote_formatter_receives_redacted_sensitive_values(self) -> None:
        config = {
            "cleanup": {"smart_format": True, "level": "high", "format_mode": "ai"},
            "privacy": {"redact_pii": True},
        }
        text = (
            "send the account summary to maya@example.com and call 415-555-0199 after verifying "
            "123-45-6789 and 4111 1111 1111 1111 tomorrow morning"
        )
        output = (
            "Send the account summary to [email] and call [phone] after verifying [ssn] and "
            "[card] tomorrow morning."
        )

        # Exercise the remote request boundary even when this short utterance
        # is normally finished by the deterministic fast path.
        with patch("knight_flow.formatting._high_confidence_fast_format", return_value=None), patch(
            "knight_flow.formatting.llm_complete", return_value=output
        ) as complete:
            processed = process_dictation(text, config)

        formatter_request = complete.call_args.args[1]
        for sensitive_value in (
            "maya@example.com",
            "415-555-0199",
            "123-45-6789",
            "4111 1111 1111 1111",
        ):
            self.assertNotIn(sensitive_value, formatter_request)
        for token in ("[email]", "[phone]", "[ssn]", "[card]"):
            self.assertIn(token, formatter_request)
        self.assertEqual(processed.original, text)
        self.assertEqual(processed.text, output)

    def test_local_formatter_keeps_existing_final_redaction_behavior(self) -> None:
        config = {
            "cleanup": {"smart_format": True, "level": "high", "format_mode": "heuristic"},
            "privacy": {"redact_pii": True},
        }

        processed = process_dictation("contact maya@example.com tomorrow morning", config)

        self.assertEqual(processed.text, "Contact [email] tomorrow morning.")


if __name__ == "__main__":
    unittest.main()


class DictationMustNotBeMangledTests(unittest.TestCase):
    """Both of these reached a user as "it's doing some weird stuff".

    The formatter's own rule is that prose is correct far more often than any
    list, and that the words things, items, features and options never
    authorize bullets on their own. The heuristics did the opposite.
    """

    def test_an_ordinary_sentence_does_not_become_a_bullet_list(self) -> None:
        # Split on the bare "and", this produced:
        #   I need three things:
        #   - Done today the tests the docs
        #   - The deploy
        # The content is mangled, not merely mis-shaped -- "done today" was
        # swallowed into an item it was never part of.
        out = heuristic_format("i need three things done today the tests the docs and the deploy")
        self.assertNotIn("- ", out)
        self.assertNotIn("\n", out)
        self.assertIn("three things done today", out)

    def test_a_sentence_containing_and_is_not_an_enumeration(self) -> None:
        out = heuristic_format("we need a few changes before we ship this thing")
        self.assertNotIn("- ", out)

    def test_a_genuinely_spoken_list_still_becomes_a_list(self) -> None:
        """The fix must not buy safety by refusing to ever build a list."""
        out = heuristic_format("the fixes are login, payment, and the dashboard")
        self.assertEqual(out.count("- "), 3)

    def test_a_list_with_no_punctuation_survives_via_clause_actors(self) -> None:
        """A change of subject is real evidence of enumeration where "and" is
        not, so this path has to keep working without commas."""
        out = heuristic_format(
            "the requirements are the client must authenticate and retain its session "
            "and the worker should retry and report failures"
        )
        self.assertEqual(out.count("- "), 2)
        self.assertIn("retain its session", out)

    def test_no_sentence_is_left_ending_on_a_conjunction(self) -> None:
        # "...fix the login bug and also the payment thing is broken" split at
        # "also" and closed the first sentence as "...the login bug and."
        cases = [
            "so the thing is we need to fix the login bug and also the payment thing is broken and honestly the whole dashboard needs work",
            "we shipped the update and then after that we need to tell everyone and also update the docs",
            "first fix the tests but finally we can ship it once the build is green and everything passes",
        ]
        dangling = re.compile(r"\b(?:and|but|or|so|then)\s*[.!?]")
        for text in cases:
            with self.subTest(text=text[:40]):
                self.assertIsNone(dangling.search(heuristic_format(text)))


class SelfCorrectionSurvivesTheMeaningGuardTests(unittest.TestCase):
    """The self-correction rules were being discarded before reaching anyone.

    _valid_formatter_output compares "meaning words" -- negations and modals
    like not, should, must -- and required them to match exactly, so the model
    could never turn "how is OpenRouter, not OpenRouter, how is Wispr Flow"
    into "how is Wispr Flow": that drops a "not". Every sentence the feature
    applied to was silently rejected and replaced with the unrepaired
    heuristic output, which is why it looked like the model was being skipped.
    """

    def test_a_retraction_may_drop_its_negation(self) -> None:
        source = ("so I was thinking we should push the release to Friday. "
                  "How is, how is, not OpenRouter, how is Wispr Flow doing this")
        fixed = "So I was thinking we should push the release to Friday. How is Wispr Flow doing this?"
        self.assertTrue(_valid_formatter_output(source, fixed, preserve_meaning=True))

    def test_inventing_a_negation_is_still_refused(self) -> None:
        """Removals are the job; additions are hallucination."""
        source = "call mom, I mean call dad, tonight"
        invented = "Do not call dad tonight."
        self.assertFalse(_valid_formatter_output(source, invented, preserve_meaning=True))

    def test_wholesale_negation_loss_is_still_refused(self) -> None:
        """Dropping the "not" from a retraction is repair. Dropping every
        negation in the sentence inverts what the person said."""
        source = "don't send it, I mean don't send it today, we should not do that"
        inverted = "Send it today, we should do that."
        self.assertFalse(_valid_formatter_output(source, inverted, preserve_meaning=True))

    def test_clean_speech_is_still_held_to_exact_meaning(self) -> None:
        """The relaxation applies only where repair is detected, so ordinary
        dictation keeps the strict guarantee it had."""
        source = "we should not ship this today"
        self.assertTrue(_valid_formatter_output(source, "We should not ship this today.", preserve_meaning=True))
        self.assertFalse(_valid_formatter_output(source, "We should ship this today.", preserve_meaning=True))


class EllipsesArePausesNotSentenceEndsTests(unittest.TestCase):
    """Found by running 380 of this user's real transcripts through the
    formatter rather than by inventing inputs.

    Speech-to-text emits an ellipsis for hesitation. The sentence splitter read
    each one as a full stop, so "I think the cost should be... 24.99" came back
    as "The cost should be." and "24.99." -- two fragments, neither a sentence.
    It also stranded conjunctions: "and then... like..." became "and then."
    followed by "Like."
    """

    def test_a_hesitation_does_not_split_the_thought(self) -> None:
        self.assertEqual(heuristic_format("the cost should be... 24.99"),
                         "The cost should be 24.99.")

    def test_it_does_not_strand_a_conjunction(self) -> None:
        out = heuristic_format("let's do 24.99 and then... like...")
        self.assertNotIn("and.", out)
        self.assertNotIn(" then.", out.replace("Then.", ""))

    def test_mid_sentence_hesitation_joins_up(self) -> None:
        self.assertEqual(heuristic_format("I was thinking... maybe friday"),
                         "I was thinking maybe friday.")

    def test_real_sentence_boundaries_still_split(self) -> None:
        """The fix must not make every full stop a pause.

        Counted newlines, which stopped being the evidence when sentences began
        joining into paragraphs instead of stacking into a column. What matters
        is that three sentences are still recognised as three, so that is what
        is asserted -- three terminators, and each sentence capitalised.
        """
        out = heuristic_format("wait. this is a real sentence. and another one.")
        self.assertEqual(out.count("."), 3)
        self.assertIn("Wait.", out)
        self.assertIn("This is a real sentence.", out)

    def test_the_unicode_ellipsis_is_handled_too(self) -> None:
        self.assertEqual(heuristic_format("I was thinking… maybe friday"),
                         "I was thinking maybe friday.")

    def test_no_real_transcript_crashes_the_formatter(self) -> None:
        """380 real transcripts produced zero crashes and zero empty output;
        this keeps a representative sample of the awkward ones in the suite."""
        for text in [
            "I think the cost should be... 24.99. That just feels like a more fair number.",
            "Wait but don't I deploy this to my normal website or does it need to be a github repo",
            "Not my main monitor, basically, the one that has, like, I don't know",
        ]:
            with self.subTest(text=text[:40]):
                out = heuristic_format(text)
                self.assertTrue(out.strip(), "formatter returned nothing")
