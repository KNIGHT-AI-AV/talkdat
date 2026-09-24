"""The formatter model is a measured choice, not a remembered one.

anthropic/claude-haiku-4.5 was the default for three days. Artificial
Analysis measures it at 96 output tokens/second against gemini-3.5-flash-lite's
379, with lower intelligence (30 vs 37) and double the price. The app gives
the model ~1.2 seconds before the rules path answers instead, so at 96 tok/s a
100-token paragraph spends the entire budget on generation alone -- the AI
formatter was timing out into the fallback on anything longer than a sentence.

These pin the fix, and the migration that carries existing machines over. A
default change alone would have left every install that ran since 2026-08-04
on the slow model, including the owner's.
"""
from __future__ import annotations

import unittest

from knight_flow.config import _migrate_formatter_off_haiku
from knight_flow.llm import PROVIDER_DEFAULTS


class FormatterModelTests(unittest.TestCase):
    def test_the_openrouter_default_is_the_fast_model(self) -> None:
        self.assertEqual(
            "google/gemini-3.5-flash-lite",
            PROVIDER_DEFAULTS["openrouter"]["model"],
        )

    def test_no_default_reaches_for_a_slow_tier_over_openrouter(self) -> None:
        """Guards the specific regression: reaching for a familiar name."""
        self.assertNotIn("haiku", PROVIDER_DEFAULTS["openrouter"]["model"].lower())

    def test_the_anthropic_route_keeps_haiku_deliberately(self) -> None:
        """Haiku is still Anthropic's ONLY fast tier -- Sonnet 5 cannot answer
        inside the budget. This route only runs for someone who brought an
        Anthropic key, so the question is 'best Anthropic option', not 'best'."""
        self.assertIn("haiku", PROVIDER_DEFAULTS["anthropic"]["model"].lower())


class MigrationTests(unittest.TestCase):
    def test_a_saved_haiku_config_is_carried_over(self) -> None:
        config = {"transforms": {"llm": {"provider": "openrouter", "model": "anthropic/claude-haiku-4.5"}}}
        _migrate_formatter_off_haiku(config)
        self.assertEqual("google/gemini-3.5-flash-lite", config["transforms"]["llm"]["model"])

    def test_a_deliberate_choice_is_never_overridden(self) -> None:
        """A migration that overrides real choices is worse than the stale
        default it was meant to fix."""
        for chosen in ("openai/gpt-5.2", "google/gemini-3.6-flash", "moonshotai/kimi-k3"):
            config = {"transforms": {"llm": {"model": chosen}}}
            _migrate_formatter_off_haiku(config)
            self.assertEqual(chosen, config["transforms"]["llm"]["model"])

    def test_it_survives_a_config_with_nothing_in_it(self) -> None:
        for config in ({}, {"transforms": {}}, {"transforms": {"llm": "junk"}}):
            _migrate_formatter_off_haiku(config)  # must not raise


if __name__ == "__main__":
    unittest.main()
