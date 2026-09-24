from __future__ import annotations

import unittest

from knight_flow.formatting import FORMAT_SYSTEM_PROMPT


class FormatPromptTests(unittest.TestCase):
    """The formatting contract, pinned.

    Every rule here exists because the opposite behaviour was observed in real
    dictation, not because it sounded sensible. The prompt is the only thing
    standing between a transcript and what the speaker meant to write, so a rule
    silently disappearing from it is a regression worth failing a build over.
    """

    def test_prose_is_the_default(self) -> None:
        """Observed: continuous speech came back as one bullet per sentence."""
        self.assertIn("prose", FORMAT_SYSTEM_PROMPT.lower())

    def test_it_forbids_bulleting_a_continuous_thought(self) -> None:
        lowered = FORMAT_SYSTEM_PROMPT.lower()
        self.assertIn("never", lowered)
        self.assertTrue(
            "one grammatical sentence" in lowered or "continuous" in lowered,
            "the rule against splitting a sentence into bullets is missing",
        )

    def test_it_removes_stutters_and_restarts(self) -> None:
        """Observed: 'I- I don't you- I don't want' survived intact."""
        lowered = FORMAT_SYSTEM_PROMPT.lower()
        self.assertIn("false start", lowered)
        self.assertTrue("stutter" in lowered or "repetition" in lowered)

    def test_every_emphasis_form_is_available(self) -> None:
        lowered = FORMAT_SYSTEM_PROMPT.lower()
        for capability in ("bold", "italic", "parenthes", "quote"):
            self.assertIn(capability, lowered, f"{capability} is not covered")

    def test_both_list_forms_are_covered(self) -> None:
        lowered = FORMAT_SYSTEM_PROMPT.lower()
        self.assertIn("numbered", lowered)
        self.assertIn("bullet", lowered)

    def test_it_refuses_to_act_on_the_dictation(self) -> None:
        """The text is content to edit. A dictated question must not be answered."""
        lowered = FORMAT_SYSTEM_PROMPT.lower()
        self.assertIn("never an assistant", lowered)
        self.assertIn("not a request", lowered)

    def test_it_forbids_inventing_content(self) -> None:
        lowered = FORMAT_SYSTEM_PROMPT.lower()
        self.assertTrue("never add" in lowered or "invent" in lowered)

    def test_it_corrects_misheard_technical_terms(self) -> None:
        """Observed: 'italisis' for italics. Speech-to-text mangles jargon and
        proper nouns most, which is exactly where errors are least acceptable."""
        self.assertIn("misheard", FORMAT_SYSTEM_PROMPT.lower())

    def test_uncertainty_resolves_to_leaving_it_alone(self) -> None:
        """A wrong guess is worse than a plain sentence."""
        self.assertIn("uncertain", FORMAT_SYSTEM_PROMPT.lower())

    def test_it_returns_only_the_text(self) -> None:
        lowered = FORMAT_SYSTEM_PROMPT.lower()
        self.assertIn("only", lowered)
        self.assertTrue("commentary" in lowered or "preamble" in lowered)


if __name__ == "__main__":
    unittest.main()


class EditorialCoverageTests(unittest.TestCase):
    """The prompt is the entire formatting engine -- there is no rule code
    behind it, so a rule that is not written here does not exist.

    The first version covered speech repair, structure and emphasis, and was
    silent on most of what a copy editor actually decides. Every assertion
    below marks a decision that reached the user as wrong output before it was
    specified. They pin coverage, not wording; rephrase freely, but do not drop
    a domain.
    """

    def prompt(self) -> str:
        return FORMAT_SYSTEM_PROMPT.lower()

    def test_it_resolves_homophones_by_grammar_not_by_sound(self) -> None:
        # A recognizer cannot hear the difference; only grammar decides.
        for pair in ("their/there", "your/you're", "its/it's", "affect/effect"):
            self.assertIn(pair, self.prompt(), f"{pair} is unspecified")

    def test_it_recovers_questions_that_lost_their_intonation(self) -> None:
        self.assertIn("question mark", self.prompt())
        self.assertIn("intonation", self.prompt())

    def test_it_rules_on_numerals_versus_words(self) -> None:
        self.assertIn("under ten", self.prompt())
        self.assertIn("never begin a sentence with a numeral", self.prompt())

    def test_it_distinguishes_the_three_dashes(self) -> None:
        for mark in ("em dash", "en dash", "hyphen"):
            self.assertIn(mark, self.prompt())

    def test_it_settles_the_serial_comma_rather_than_leaving_it_to_chance(self) -> None:
        self.assertIn("serial comma", self.prompt())

    def test_it_places_punctuation_against_quotation_marks(self) -> None:
        self.assertIn("inside closing quotation marks", self.prompt())

    def test_it_separates_colon_from_semicolon(self) -> None:
        self.assertIn("colon", self.prompt())
        self.assertIn("semicolon", self.prompt())

    def test_it_forbids_the_apostrophe_plural(self) -> None:
        self.assertIn("never a plural", self.prompt())

    def test_it_hyphenates_compound_modifiers_by_position(self) -> None:
        self.assertIn("well-known author", self.prompt())
        self.assertIn("-ly adverb", self.prompt())

    def test_it_preserves_capitalized_product_spellings(self) -> None:
        # Sentence-casing these is the most visible possible error.
        for name in ("iphone", "macos", "github"):
            self.assertIn(name, self.prompt())

    def test_it_requires_parallel_grammar_in_lists(self) -> None:
        self.assertIn("parallel", self.prompt())

    def test_it_refuses_to_sanitize_the_speakers_register(self) -> None:
        """Cleaning up someone's voice is the one failure they notice
        immediately and cannot correct, because the original is gone."""
        self.assertIn("profanity", self.prompt())
        self.assertIn("register", self.prompt())

    def test_it_still_refuses_to_act_on_the_dictation(self) -> None:
        # Prompt injection: the dictation is data, never instructions.
        self.assertIn("<dictation>", FORMAT_SYSTEM_PROMPT)
        self.assertIn("never an assistant", self.prompt())

    def test_it_stays_small_enough_to_send_on_every_dictation(self) -> None:
        """This ships with every request, so it is latency on the hot path.
        Thorough is the goal; unbounded is not."""
        self.assertLess(len(FORMAT_SYSTEM_PROMPT), 15500)


class SelfCorrectionAndVoiceTests(unittest.TestCase):
    """Speech revises itself out loud, and the formatter has to pick a side.

    Reported from real use: "how is OpenRouter doing this, dude? How is, how
    is, freaking, not OpenRouter, how is, Wispr Flow doing this?" reached the
    screen intact -- the wrong name, the retraction, and both restarts. The
    prompt could already fix it; a fast-path short circuit meant the model was
    never asked. See needs_intelligence in formatting.py.
    """

    def prompt(self) -> str:
        return FORMAT_SYSTEM_PROMPT.lower()

    def test_retraction_markers_are_named(self) -> None:
        for marker in ("i mean", "scratch that", "no wait", "rather"):
            self.assertIn(marker, self.prompt(), f"{marker} is unspecified")

    def test_it_forbids_keeping_both_the_error_and_the_correction(self) -> None:
        """Keeping both is worse than keeping neither: the reader has to work
        out which one the speaker meant."""
        self.assertIn("never leave both", self.prompt())

    def test_a_restarted_clause_keeps_only_its_finished_form(self) -> None:
        self.assertIn("we need to fix this today", self.prompt())

    def test_deliberate_profanity_is_never_softened(self) -> None:
        self.assertIn("never censor", self.prompt())
        self.assertIn("asterisk", self.prompt())

    def test_a_repeated_intensifier_is_treated_as_padding(self) -> None:
        """A word used once is a choice; the same word four times is a tic.
        Repetition is the signal, not the word itself."""
        self.assertIn("keep the first occurrence only", self.prompt())
        self.assertIn("verbal tic", self.prompt())

    def test_the_goal_is_email_not_transcript(self) -> None:
        self.assertIn("colleague", self.prompt())
        self.assertIn("not a transcript", self.prompt())
