"""Reference/guard qualification only; no sound, model, OS input or user files."""
import copy
import re
import unittest
from unittest.mock import patch

from knight_flow.config import DEFAULT_CONFIG
from knight_flow import formatting
from knight_flow.formatting import formatter_rejection_reason
from knight_flow.text_pipeline import process_dictation, pre_clean_for_format
from tests.owner_formatting_reference import REFERENCES, cases_for
from tests.parity_battery import preset_config, run, violations


class OwnerReferenceTests(unittest.TestCase):
    def test_references_cover_the_owner_contract_and_have_distinct_styles(self):
        families = {reference.family for reference in REFERENCES}
        self.assertGreaterEqual(len(REFERENCES), 20)
        self.assertTrue({"revision", "ramble", "professional_email", "casual", "list", "names",
                         "amount", "date", "ambiguity", "emphasis", "quotation", "multilingual",
                         "code", "terminal", "prompt", "negation", "verbatim"} <= families)
        self.assertEqual(len({reference.label for reference in REFERENCES}), len(REFERENCES))
        self.assertGreaterEqual(sum(reference.casual != reference.corporate for reference in REFERENCES), 3)

    def test_references_preserve_every_annotated_fact_and_clear_settled_values(self):
        for reference in REFERENCES:
            for target in (reference.casual, reference.corporate, *reference.alternatives):
                with self.subTest(case=reference.label, target=target):
                    for fact in reference.facts:
                        self.assertRegex(target, re.compile(fact, re.I))
                    for old in reference.retracted:
                        self.assertNotRegex(target, re.compile(old, re.I))

    def test_real_guards_accept_faithful_references_and_refuse_adversarial_edits(self):
        for reference in REFERENCES:
            if reference.preset:
                continue  # Verbatim and terminal bypass the model contract.
            for executive, target in ((False, reference.casual), (True, reference.corporate)):
                with self.subTest(case=reference.label, executive=executive):
                    # The real validator receives resolved speech, not the old
                    # correction cue's "no" as a permanent negation claim.
                    source = pre_clean_for_format(reference.spoken, DEFAULT_CONFIG)
                    reason = formatter_rejection_reason(source, target,
                        preserve_meaning=not executive, rewrite_mode=executive, transcript=source)
                    self.assertEqual(reason, "")
                    if reference.unsafe:
                        self.assertTrue(formatter_rejection_reason(source, reference.unsafe,
                            preserve_meaning=not executive, rewrite_mode=executive, transcript=source))

    def test_written_values_cannot_swap_roles_even_when_all_digits_survive(self):
        pairs = (("Send Maya $42.50, not $43.50.", "Send Maya $43.50, not $42.50."),
                 ("Maya gets 42 and Riley gets 43.", "Maya gets 43 and Riley gets 42."),
                 ("The review is at 3:30 and the call is at 4:45.",
                  "The review is at 4:45 and the call is at 3:30."))
        for source, candidate in pairs:
            for executive in (False, True):
                with self.subTest(source=source, executive=executive):
                    self.assertTrue(formatter_rejection_reason(source, candidate,
                        preserve_meaning=not executive, rewrite_mode=executive, transcript=source))

    def test_remote_formats_preserve_numeric_roles_order_and_precision(self):
        pairs = (("Pay Alice 15 and Bob 20.", "Pay Alice 20 and Bob 15."),
                 ("Maya gets fifteen and Riley gets twenty.", "Maya gets 20 and Riley gets 15."),
                 ("Version 2.10 is installed.", "Version 2-10 is installed."),
                 ("The number is 5.", "The number is 5.0."))
        for source, candidate in pairs:
            for executive in (False, True):
                with self.subTest(source=source, executive=executive):
                    self.assertEqual(formatter_rejection_reason(source, candidate,
                        preserve_meaning=not executive, rewrite_mode=executive), "number_changed")

    def test_remote_formats_allow_spoken_numbers_and_structural_list_counters(self):
        pairs = (("Maya gets fifteen and Riley gets twenty.", "Maya gets 15 and Riley gets 20."),
                 ("The budget is forty two thousand dollars.", "The budget is $42,000."),
                 ("The review is at twelve fifteen p m.", "The review is at 12:15 PM."),
                 ("The budget is 1000 dollars.", "The budget is $1,000."),
                 ("First Maya gets 42, second Riley gets 43.", "1. Maya gets 42\n2. Riley gets 43"))
        for source, candidate in pairs:
            for executive in (False, True):
                with self.subTest(source=source, executive=executive):
                    self.assertEqual(formatter_rejection_reason(source, candidate,
                        preserve_meaning=not executive, rewrite_mode=executive), "")

    def test_a_remote_value_swap_keeps_safe_text(self):
        source = "Pay Alice 15 and Bob 20."
        for intensity in ("standard", "executive"):
            config = copy.deepcopy(DEFAULT_CONFIG)
            config["cleanup"]["format_intensity"] = intensity
            config["transforms"]["llm"] = {"provider": "openrouter", "api_key": "test-key"}
            config["privacy"]["local_only"] = False
            config["stt"]["route_mode"] = "byok"
            config["stt"]["provider"] = "openrouter"
            config["stt"]["providers"] = {"openrouter": {"api_key": "test-key"}}
            with patch.object(formatting, "llm_complete", return_value="Pay Alice 20 and Bob 15."):
                processed = process_dictation(source, config)
            self.assertEqual(processed.text, source)
            self.assertEqual(processed.route, "rules_after_rejection")
            self.assertEqual(processed.rejection, "number_changed")

    def test_quoted_value_corrections_remain_a_record_of_the_words(self):
        sources = ('She said "Tuesday, no wait, Wednesday."',
                   'She said “$15, no wait, $20.”',
                   "She said '3:30, no wait, 4:45.'",
                   "She said 'I don't want Tuesday, no wait, Wednesday.'",
                   "She said ‘I don’t want Tuesday, no wait, Wednesday.’",
                   'She said «Tuesday, no wait, Wednesday.»')
        for source in sources:
            with self.subTest(source=source):
                self.assertEqual(formatting.resolve_value_corrections(source), source)
                processed = process_dictation(source, copy.deepcopy(DEFAULT_CONFIG), local_only=True)
                self.assertEqual(processed.text, source)

    def test_unquoted_values_still_correct_beside_a_quotation(self):
        for quotation in ('"Tuesday, no wait, Wednesday."',
                          "'I don't want Tuesday, no wait, Wednesday.'",
                          '‘I don’t want Tuesday, no wait, Wednesday.’',
                          '«Tuesday, no wait, Wednesday.»'):
            with self.subTest(quotation=quotation):
                source = f'She said {quotation} Meet Tuesday, no wait, Thursday.'
                target = f'She said {quotation} Meet Thursday.'
                self.assertEqual(formatting.resolve_value_corrections(source), target)

    def test_formatting_a_numbered_list_can_preserve_values_without_preserving_markers(self):
        source = "First Maya gets 42, second Riley gets 43."
        candidate = "1. Maya gets 42\n2. Riley gets 43"
        self.assertEqual(formatter_rejection_reason(source, candidate), "")

    def test_a_rejected_value_swap_keeps_safe_text_and_explains_rules_delivery(self):
        source = "Please send Maya $42.50, not $43.50."
        bad = "Please send Maya $43.50, not $42.50."
        for intensity in ("standard", "executive"):
            config = copy.deepcopy(DEFAULT_CONFIG)
            config["cleanup"]["format_intensity"] = intensity
            with patch.object(formatting, "llm_configured", return_value=True), \
                 patch.object(formatting, "resolved_llm_provider", return_value="ollama"), \
                 patch.object(formatting, "local_finish", return_value=bad):
                processed = process_dictation(source, config)
            self.assertEqual(processed.text, source)
            self.assertEqual(processed.route, "rules_after_rejection")
            self.assertEqual(processed.rejection, "number_changed")
            self.assertEqual(formatting.take_local_finish_notice(), "model_safety_fallback")

    def test_terminal_and_verbatim_use_the_existing_pipeline_without_a_model(self):
        for reference in REFERENCES:
            if not reference.preset:
                continue
            config = preset_config(copy.deepcopy(DEFAULT_CONFIG), reference.preset)
            with patch("knight_flow.formatting.local_finish", side_effect=AssertionError("Model forbidden")):
                processed = process_dictation(reference.spoken, config)
            self.assertEqual(processed.text, reference.casual)
            self.assertFalse(processed.send_enter)

    def test_a_completed_quote_does_not_receive_a_second_full_stop(self):
        for source in ('She said "call Maya, I mean call NavOrb."',
                       'She wrote “we are gonna wait.”',
                       "He said 'Stop!'", 'She asked «Are you ready?»',
                       'She said "press enter."', 'Did he say "Hello."?', 'Open "notes.txt".'):
            with self.subTest(source=source):
                processed = process_dictation(source, copy.deepcopy(DEFAULT_CONFIG), local_only=True)
                self.assertEqual(processed.text, source)
                self.assertFalse(processed.send_enter)

    def test_existing_rules_scoring_does_not_claim_model_or_audio_acceptance(self):
        for intensity in ("chill", "executive"):
            rows = run(corpus=cases_for(intensity), intensity=intensity)
            self.assertEqual(len(rows), len(REFERENCES))
            self.assertEqual(violations(rows), [])
            self.assertFalse(any("model" in row["route"] for row in rows))


if __name__ == "__main__":
    unittest.main()
