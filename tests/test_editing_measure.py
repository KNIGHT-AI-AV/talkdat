"""T10: the measurement's arithmetic, on synthetic task timings. The five-person
pilot needs separate participant approval and is not run here.
"""
from __future__ import annotations

import unittest

from knight_flow.editing_measure import (
    MIN_TASKS, Task, estimated_minutes_saved, measure, stats_rows, task_order,
)


def tasks(typing_spw: list[float], dictation_spw: list[float], words: int = 40) -> list[Task]:
    return ([Task("typing", words, spw * words, 3) for spw in typing_spw]
            + [Task("dictation", words, spw * words, 5) for spw in dictation_spw])


class TheMeasurement(unittest.TestCase):
    def test_dictation_faster(self):
        result = measure(tasks([1.5, 1.6, 1.4, 1.5], [1.0, 1.1, 0.9, 1.2]))
        self.assertTrue(result.enough)
        self.assertAlmostEqual(result.typing_median_spw, 1.5)
        self.assertAlmostEqual(result.dictation_median_spw, 1.05)
        self.assertAlmostEqual(result.net_seconds_per_word, -0.45)
        self.assertAlmostEqual(result.median_change, -0.3)
        self.assertAlmostEqual(result.minutes_saved(600), 4.5)

    def test_dictation_slower_is_reported_as_slower(self):
        result = measure(tasks([0.8, 0.9, 0.85], [1.2, 1.3, 1.25]))
        self.assertTrue(result.enough)
        self.assertGreater(result.net_seconds_per_word, 0)
        self.assertLess(result.minutes_saved(600), 0)

    def test_not_enough_tasks(self):
        result = measure(tasks([1.5] * (MIN_TASKS - 1), [1.0] * MIN_TASKS))
        self.assertFalse(result.enough)
        self.assertEqual([row["label"] for row in stats_rows(result, 500)], ["estimated"])

    def test_the_spread(self):
        result = measure(tasks([1.5] * 4, [1.0, 2.0, 3.0, 4.0, 5.0]))
        low, high = result.dictation_spread
        self.assertLessEqual(low, result.dictation_median_spw)
        self.assertGreaterEqual(high, result.dictation_median_spw)
        self.assertEqual((low, high), (2.0, 4.0))

    def test_one_slow_task_does_not_move_the_median(self):
        result = measure(tasks([1.0, 1.0, 1.0, 4.0], [0.8, 0.8, 0.8]))
        self.assertAlmostEqual(result.typing_median_spw, 1.0)
        self.assertAlmostEqual(result.median_change, -0.2)

    def test_empty_tasks_are_ignored(self):
        result = measure([Task("typing", 0, 10.0)] + tasks([1.5] * 3, [1.0] * 3))
        self.assertEqual(result.typing_tasks, 3)


class TheOrder(unittest.TestCase):
    def test_alternating_order(self):
        self.assertEqual(task_order(2, start_with_typing=True), ["typing", "dictation", "dictation", "typing"])
        self.assertEqual(task_order(2, start_with_typing=False), ["dictation", "typing", "typing", "dictation"])
        order = task_order(6, start_with_typing=True)
        self.assertEqual(order.count("typing"), order.count("dictation"))


class WhatStatsShows(unittest.TestCase):
    def test_estimate_stays_labeled_and_measured_appears_apart(self):
        result = measure(tasks([1.5] * 4, [1.0] * 4))
        rows = stats_rows(result, 1500)
        self.assertEqual(rows[0], {"label": "estimated", "minutes": round(estimated_minutes_saved(1500))})
        self.assertEqual(rows[1]["label"], "measured")
        self.assertEqual(rows[1]["tasks"], 8)
        self.assertAlmostEqual(rows[1]["minutes"], 12.5)

    def test_the_estimate_matches_the_old_counter(self):
        # history.py: max(0.0, dictated_words / 40 - dictated_words / 150)
        for words in (0, 10, 1500, 10_000):
            self.assertAlmostEqual(estimated_minutes_saved(words), max(0.0, words / 40 - words / 150))

    def test_no_text_is_part_of_a_task(self):
        self.assertEqual(set(Task.__dataclass_fields__), {"mode", "words", "seconds", "corrections"})


if __name__ == "__main__":
    unittest.main()
