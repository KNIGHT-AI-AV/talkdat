from __future__ import annotations

import unittest

from knight_flow.model_quality import (
    MODEL_RATINGS,
    accuracy_rating,
    meter,
    quality_line,
    speed_rating,
)


class RatingScaleTests(unittest.TestCase):
    """Ratings are derived from measurements, not opinion.

    Accuracy comes from Artificial Analysis AA-WER and speed from its speed
    factor, both read 2026-08-04. Deriving them from a table means a model
    cannot quietly be marketed as better than it measures.
    """

    def test_a_lower_error_rate_scores_higher(self) -> None:
        self.assertGreater(accuracy_rating(2.4), accuracy_rating(5.2))

    def test_the_best_measured_model_reaches_the_top_of_the_scale(self) -> None:
        self.assertEqual(accuracy_rating(2.2), 5.0)

    def test_a_poor_error_rate_does_not_score_well(self) -> None:
        self.assertLessEqual(accuracy_rating(13.5), 2.0)

    def test_a_faster_model_scores_higher(self) -> None:
        self.assertGreater(speed_rating(505), speed_rating(37))

    def test_ratings_stay_inside_the_scale(self) -> None:
        for wer in (0.1, 2.0, 4.0, 8.0, 40.0):
            self.assertGreaterEqual(accuracy_rating(wer), 0.5)
            self.assertLessEqual(accuracy_rating(wer), 5.0)
        for factor in (0.5, 50, 900, 5000):
            self.assertGreaterEqual(speed_rating(factor), 0.5)
            self.assertLessEqual(speed_rating(factor), 5.0)

    def test_ratings_land_on_half_steps(self) -> None:
        """Half steps read as considered; 3.7482 reads as noise."""
        for wer in (1.0, 2.4, 3.3, 4.5, 5.2, 6.4, 10.1):
            self.assertEqual((accuracy_rating(wer) * 2) % 1, 0.0)


class MeterTests(unittest.TestCase):
    """A compact bar, not stars. Stars imply a review score; this is a
    measurement, and the bar reads as a level."""

    def test_it_renders_five_slots(self) -> None:
        self.assertEqual(len(meter(3.0)), 5)

    def test_a_full_rating_fills_every_slot(self) -> None:
        self.assertEqual(meter(5.0), "▰▰▰▰▰")

    def test_a_half_step_shows_a_half_slot(self) -> None:
        self.assertEqual(meter(3.5), "▰▰▰▱▱".replace("▱", "▨", 1))

    def test_the_lowest_rating_still_shows_something(self) -> None:
        """An entirely empty bar looks like a rendering failure."""
        self.assertNotEqual(meter(0.5).strip("▱"), "")


class ModelRatingTableTests(unittest.TestCase):
    def test_the_models_we_recommend_are_all_rated(self) -> None:
        for model_id in (
            "microsoft/mai-transcribe-1.5",
            "x-ai/grok-stt-1.0",
            "deepgram/nova-3",
            "parakeet-tdt-0.6b-v3",
        ):
            self.assertIn(model_id, MODEL_RATINGS, model_id)

    def test_the_accuracy_leader_outranks_the_speed_leader_on_accuracy(self) -> None:
        """Nova-3 is the fastest and measurably less accurate. The UI must not
        blur that, because it is the whole reason to pay for the other one."""
        best = MODEL_RATINGS["microsoft/mai-transcribe-1.5"]
        fastest = MODEL_RATINGS["deepgram/nova-3"]
        self.assertGreater(best["accuracy"], fastest["accuracy"])
        self.assertGreater(fastest["speed"], best["speed"])

    def test_the_free_local_default_beats_nova_3_on_accuracy(self) -> None:
        """It genuinely does -- 4.5% against 5.2% -- and hiding that would sell
        a paid downgrade."""
        local = MODEL_RATINGS["parakeet-tdt-0.6b-v3"]
        self.assertGreater(local["accuracy"], MODEL_RATINGS["deepgram/nova-3"]["accuracy"])

    def test_an_unknown_model_reports_no_line_rather_than_inventing_one(self) -> None:
        self.assertEqual(quality_line("something/never-measured"), "")

    def test_a_known_model_reads_clearly(self) -> None:
        line = quality_line("microsoft/mai-transcribe-1.5")
        self.assertIn("Accuracy", line)
        self.assertIn("Speed", line)
        self.assertIn("▰", line)


if __name__ == "__main__":
    unittest.main()
