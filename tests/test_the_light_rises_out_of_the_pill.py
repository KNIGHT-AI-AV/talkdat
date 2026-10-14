"""The Pill's update light on a real Pill (run through scripts/run_tests_offscreen.py).

2026-10-09, the owner: the green and red dots "look cut and paste"; they must be
designed lights that animate out of the Pill. Overwatch's conditions for it: animate
on a state change only, never in a loop; honour reduced motion; no idle CPU
regression. So: after its entrance the Pill draws nothing at rest; it sinks back when
cleared and is gone after; under reduced motion it only fades.
"""
from __future__ import annotations

import sys
import time
import unittest

from tests.pill_harness import build_overlay, destroy_overlay, pump


@unittest.skipUnless(sys.platform == "win32", "the layered Pill is Windows")
class TheLightRisesOutTests(unittest.TestCase):
    def tearDown(self) -> None:
        destroy_overlay(getattr(self, "overlay", None))

    def count_draws(self) -> dict:
        draws = {"n": 0}
        original = self.overlay._draw_visual

        def counted(*args, **kwargs):
            draws["n"] += 1
            return original(*args, **kwargs)

        self.overlay._draw_visual = counted
        return draws

    def test_after_its_entrance_the_pill_draws_nothing_at_rest(self) -> None:
        self.overlay = build_overlay()
        pump(self.overlay.root, 1.0)  # the Pill's own opening settles first
        draws = self.count_draws()
        pump(self.overlay.root, 1.5)
        idle = draws["n"]  # what this Pill draws at rest with no light: the control
        self.overlay.set_update_flag("green")
        draws["n"] = 0
        pump(self.overlay.root, 0.6)
        self.assertGreater(draws["n"], 3, "the light did not animate in")
        draws["n"] = 0
        pump(self.overlay.root, 1.5)
        self.assertLessEqual(draws["n"], idle + 1, "the Pill keeps drawing at rest with the light on")

    def test_it_sinks_back_and_is_gone(self) -> None:
        self.overlay = build_overlay()
        self.overlay.set_update_flag("red")
        pump(self.overlay.root, 0.6)
        self.overlay.set_update_flag("")
        self.assertIsNotNone(self.overlay._pip_look(), "the light vanished instead of sinking back")
        pump(self.overlay.root, 0.6)
        self.assertIsNone(self.overlay._pip_look(), "the light is still there after its exit")
        self.assertFalse(self.overlay._update_flag_hit(0, 0))

    def test_reduced_motion_only_fades(self) -> None:
        self.overlay = build_overlay(reduce_motion=True)
        self.overlay.set_update_flag("green")
        severity, look = self.overlay._pip_look(time.perf_counter() * 1000.0 + 50.0)
        self.assertEqual(severity, "green")
        self.assertEqual((look[0], look[2], look[4]), (1.0, 1.0, 0.0), "the light moved under reduced motion")


if __name__ == "__main__":
    unittest.main()
