"""The fast path is for trivial input only; every other take reaches the model.

2026-09-22, the owner's complaint since 09-03: "I'm not seeing the genius
formatting". His journal since 09-21 showed 35 of 92 takes answered by rules
because every confident take of 24 words or fewer skipped the model. The
contract is now: a few words, one clause and no cue -> rules; anything else ->
the model, with the rules draft as the safety net and the answer when the
model declines.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from knight_flow.formatting import (
    TRIVIAL_MAX_WORDS,
    _high_confidence_fast_format,
    model_budget_seconds,
)
from knight_flow.text_pipeline import process_dictation
from tests.parity_battery import local_config


class TrivialInputStaysOnRulesTests(unittest.TestCase):
    def test_a_few_plain_words_never_wait_for_a_model(self):
        for spoken in ("sounds good", "quarterly report", "see you soon", "ok"):
            with self.subTest(spoken=spoken):
                cfg = local_config('qwen3:1.7b')
                with patch('knight_flow.formatting.local_finish', return_value=None) as model:
                    result = process_dictation(spoken, cfg)
                self.assertEqual(model.call_count, 0)
                self.assertEqual(result.route, "rules_fast")
                self.assertTrue(result.text)

    def test_the_trivial_ceiling_is_four_words(self):
        self.assertEqual(TRIVIAL_MAX_WORDS, 4)
        self.assertIsNotNone(_high_confidence_fast_format("see you on friday"))
        self.assertIsNone(_high_confidence_fast_format("see you on friday then"))

    def test_cue_words_are_never_trivial(self):
        """Short is not the same as simple: each of these has something only
        a model (or the draft it finishes) gets right."""
        for spoken in ("at five actually six", "tuesday no wait wednesday", "new paragraph thanks",
                       "three things milk eggs", "hey sarah", "best alex", "call me at five",
                       "config dot json", "twenty percent", "coming tonight right"):
            with self.subTest(spoken=spoken):
                self.assertIsNone(_high_confidence_fast_format(spoken))


class EveryOtherTakeReachesTheModelTests(unittest.TestCase):
    def test_clean_short_dictation_reaches_the_model_in_both_finishes(self):
        for intensity in ("standard", "executive"):
            for spoken in ("we can send the final report tomorrow", "are you coming to the meeting",
                           "the total is five dollars and fifty cents",
                           "number one ship it number two measure it number three decide"):
                with self.subTest(intensity=intensity, spoken=spoken):
                    cfg = local_config('qwen3:1.7b')
                    cfg['cleanup']['format_intensity'] = intensity
                    with patch('knight_flow.formatting.local_finish', return_value=None) as model:
                        result = process_dictation(spoken, cfg)
                    self.assertEqual(model.call_count, 1)
                    # The model declined, so the rules draft is the answer.
                    self.assertEqual(result.route, "rules_after_unavailable_model")
                    self.assertTrue(result.text)

    def test_the_model_finishes_the_rules_draft_not_the_raw_transcript(self):
        cfg = local_config('qwen3:1.7b')
        with patch('knight_flow.formatting.local_finish', return_value=None) as model:
            process_dictation("our q three revenue was one point two million dollars", cfg)
        self.assertIn("Q3", model.call_args.args[0])
        self.assertIn("$1.2 million", model.call_args.args[0])

    def test_a_selected_tone_still_gets_its_requested_model_transform(self):
        cfg = local_config('qwen3:1.7b')
        cfg['cleanup']['tone'] = 'formal'
        with patch('knight_flow.formatting.local_finish', return_value=None) as model:
            process_dictation('please send it', cfg)
        model.assert_called_once()

    def test_an_unresolved_retraction_still_reaches_intelligence(self):
        with patch('knight_flow.formatting.local_finish', return_value=None) as model:
            process_dictation('call mom I mean call dad tonight', local_config('qwen3:1.7b'))
        model.assert_called_once()

    def test_the_rules_lane_answers_without_a_wait(self):
        with patch('knight_flow.formatting.local_finish') as model:
            result = process_dictation("we can send the final report tomorrow", local_config(), local_only=True)
        model.assert_not_called()
        self.assertEqual(result.text, "We can send the final report tomorrow.")


class TheBudgetScalesWithTheTakeTests(unittest.TestCase):
    def test_base_plus_per_word_capped(self):
        cleanup = {"max_ai_format_ms": 1200}
        self.assertAlmostEqual(model_budget_seconds(cleanup, ""), 1.2)
        self.assertAlmostEqual(model_budget_seconds(cleanup, "word " * 20), 1.2 + 20 * 0.012)
        self.assertAlmostEqual(model_budget_seconds(cleanup, "word " * 1000), 3.0)

    def test_the_owners_misses_now_fit(self):
        """His log, 09-22: the model needed 1.4-1.9 s against a flat 1.2 s on
        takes of about 20 to 60 words. A 60-word take now gets 1.92 s."""
        self.assertGreaterEqual(model_budget_seconds({"max_ai_format_ms": 1200}, "word " * 60), 1.9)

    def test_a_user_budget_above_the_ceiling_is_kept(self):
        self.assertAlmostEqual(model_budget_seconds({"max_ai_format_ms": 5000}, "word " * 10), 5.0)

    def test_settings_can_tune_both_parts(self):
        cleanup = {"max_ai_format_ms": 800, "ai_format_ms_per_word": 20, "ai_format_cap_ms": 2000}
        self.assertAlmostEqual(model_budget_seconds(cleanup, "word " * 30), 1.4)
        self.assertAlmostEqual(model_budget_seconds(cleanup, "word " * 300), 2.0)

    def test_garbage_settings_fall_back_to_the_defaults(self):
        self.assertAlmostEqual(model_budget_seconds({"max_ai_format_ms": "fast"}, ""), 1.2)

    def test_executive_uses_the_same_scaled_budget(self):
        cfg = local_config('qwen3:1.7b')
        cfg['cleanup'].update(format_intensity='executive', max_ai_format_ms=1200)
        spoken = ('the production report needs a careful review before we send the final numbers '
                  'to the studio because several people have asked for an explanation of the revised schedule')
        with patch('knight_flow.formatting.local_finish', return_value=None) as model:
            process_dictation(spoken, cfg)
        model.assert_called_once()
        budget = model.call_args.kwargs['budget_seconds']
        self.assertGreater(budget, 1.2)
        self.assertLessEqual(budget, 3.0)


if __name__ == '__main__':
    unittest.main()
