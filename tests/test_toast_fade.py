from __future__ import annotations

import unittest

from knight_flow.pill_motion import toast_fade_alpha, toast_is_finished


class ToastFadeTests(unittest.TestCase):
    """A "you are on the latest version" toast.

    Right-clicking the pill and choosing Check for updates previously reported
    "up to date" only by changing the pill's own state text. If the pill was not
    being watched, the click looked like it did nothing at all -- which is what
    prompted this.
    """

    HOLD = 1600
    FADE = 500
    TOTAL = HOLD + FADE

    def alpha(self, elapsed: float) -> float:
        return toast_fade_alpha(elapsed, hold_ms=self.HOLD, fade_ms=self.FADE)

    def test_it_is_fully_opaque_the_moment_it_appears(self) -> None:
        self.assertEqual(self.alpha(0), 1.0)

    def test_it_stays_fully_opaque_for_the_whole_hold(self) -> None:
        for elapsed in (1, 400, 800, 1599, self.HOLD):
            self.assertEqual(self.alpha(elapsed), 1.0, f"faded early at {elapsed}ms")

    def test_it_fades_out_over_the_fade_window(self) -> None:
        midpoint = self.alpha(self.HOLD + self.FADE / 2)
        self.assertAlmostEqual(midpoint, 0.5, places=2)

    def test_it_is_fully_transparent_at_the_end(self) -> None:
        self.assertEqual(self.alpha(self.TOTAL), 0.0)

    def test_it_never_leaves_a_ghost_window_after_the_end(self) -> None:
        """Past the end the alpha must stay pinned at zero, not go negative.

        A negative alpha is rejected by Tk's -alpha attribute, which would raise
        inside the animation callback and leave the toast on screen forever.
        """
        for elapsed in (self.TOTAL + 1, self.TOTAL + 5000):
            self.assertEqual(self.alpha(elapsed), 0.0)

    def test_alpha_never_leaves_the_zero_to_one_range(self) -> None:
        for elapsed in range(-200, self.TOTAL + 400, 17):
            self.assertGreaterEqual(self.alpha(elapsed), 0.0)
            self.assertLessEqual(self.alpha(elapsed), 1.0)

    def test_it_decreases_monotonically_once_fading(self) -> None:
        previous = 1.1
        for elapsed in range(self.HOLD, self.TOTAL + 1, 25):
            current = self.alpha(elapsed)
            self.assertLessEqual(current, previous, f"alpha rose at {elapsed}ms")
            previous = current

    def test_a_zero_length_fade_disappears_immediately_instead_of_dividing_by_zero(self) -> None:
        self.assertEqual(toast_fade_alpha(self.HOLD, hold_ms=self.HOLD, fade_ms=0), 0.0)
        self.assertEqual(toast_fade_alpha(0, hold_ms=self.HOLD, fade_ms=0), 1.0)

    def test_finished_only_reports_true_once_the_toast_is_gone(self) -> None:
        self.assertFalse(toast_is_finished(0, hold_ms=self.HOLD, fade_ms=self.FADE))
        self.assertFalse(toast_is_finished(self.TOTAL - 1, hold_ms=self.HOLD, fade_ms=self.FADE))
        self.assertTrue(toast_is_finished(self.TOTAL, hold_ms=self.HOLD, fade_ms=self.FADE))
        self.assertTrue(toast_is_finished(self.TOTAL + 900, hold_ms=self.HOLD, fade_ms=self.FADE))


if __name__ == "__main__":
    unittest.main()
