from __future__ import annotations

import unittest

from knight_flow.usage import (
    CLOUD_RATES_PER_MINUTE,
    estimated_monthly_cost,
    spoken_minutes,
    usage_summary,
)


class SpokenMinutesTests(unittest.TestCase):
    """Words are the only length signal kept in history.

    Audio is not retained, so minutes are derived from word count at a normal
    speaking rate. That is an estimate and is labelled as one in the UI --
    quoting a precise figure from an approximation would be dishonest.
    """

    def test_no_words_is_no_time(self) -> None:
        self.assertEqual(spoken_minutes(0), 0.0)

    def test_one_minute_of_speech_is_about_a_hundred_and_fifty_words(self) -> None:
        self.assertAlmostEqual(spoken_minutes(150), 1.0, places=2)

    def test_it_scales_linearly(self) -> None:
        self.assertAlmostEqual(spoken_minutes(1500), 10.0, places=2)

    def test_negative_input_cannot_produce_negative_time(self) -> None:
        self.assertEqual(spoken_minutes(-500), 0.0)


class MonthlyCostTests(unittest.TestCase):
    def test_a_local_provider_costs_nothing(self) -> None:
        self.assertEqual(estimated_monthly_cost("local", "parakeet-tdt-0.6b-v3", 60.0), 0.0)

    def test_an_unknown_model_is_reported_as_unknown_rather_than_zero(self) -> None:
        """Showing $0.00 for a model we have no rate for would be a lie.

        None means "we do not know", which the UI renders as a dash.
        """
        self.assertIsNone(estimated_monthly_cost("openrouter", "some/unlisted-model", 60.0))

    def test_a_known_cloud_model_is_priced_from_its_per_minute_rate(self) -> None:
        rate = CLOUD_RATES_PER_MINUTE["microsoft/mai-transcribe-1.5"]
        # 10 minutes a day for 30 days.
        self.assertAlmostEqual(
            estimated_monthly_cost("openrouter", "microsoft/mai-transcribe-1.5", 10.0),
            rate * 10.0 * 30,
            places=4,
        )

    def test_the_accuracy_tier_costs_more_than_the_value_tier(self) -> None:
        """A sanity check on the table itself, not just the arithmetic."""
        self.assertGreater(
            CLOUD_RATES_PER_MINUTE["microsoft/mai-transcribe-1.5"],
            CLOUD_RATES_PER_MINUTE["x-ai/grok-stt-1.0"],
        )


class UsageSummaryTests(unittest.TestCase):
    def test_it_reports_the_provider_and_model_actually_in_use(self) -> None:
        config = {"stt": {"provider": "openrouter",
                          "providers": {"openrouter": {"model": "microsoft/mai-transcribe-1.5"}}}}
        summary = usage_summary(config, words=3000, days_active=10)
        self.assertEqual(summary["provider"], "openrouter")
        self.assertEqual(summary["model"], "microsoft/mai-transcribe-1.5")
        self.assertTrue(summary["is_cloud"])

    def test_a_local_setup_is_marked_as_free_and_private(self) -> None:
        config = {"stt": {"provider": "local", "providers": {"local": {"model": "parakeet-tdt-0.6b-v3"}}}}
        summary = usage_summary(config, words=3000, days_active=10)
        self.assertFalse(summary["is_cloud"])
        self.assertEqual(summary["estimated_monthly_cost"], 0.0)

    def test_daily_average_uses_active_days_not_calendar_days(self) -> None:
        """Someone who dictates twice a week should not have their average
        divided by 30 -- that would understate their real session length."""
        summary = usage_summary({}, words=1500, days_active=2)
        self.assertAlmostEqual(summary["minutes_per_active_day"], 5.0, places=2)

    def test_zero_active_days_does_not_divide_by_zero(self) -> None:
        summary = usage_summary({}, words=0, days_active=0)
        self.assertEqual(summary["minutes_per_active_day"], 0.0)
        self.assertEqual(summary["total_minutes"], 0.0)

    def test_a_missing_config_does_not_raise(self) -> None:
        """This renders in the Stats window; raising here would blank it."""
        for config in ({}, {"stt": None}, {"stt": {"providers": None}}):
            summary = usage_summary(config, words=100, days_active=1)
            self.assertIn("provider", summary)


if __name__ == "__main__":
    unittest.main()
