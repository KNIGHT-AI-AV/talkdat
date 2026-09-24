"""X-170: the draw loop may never starve the input queue.

Reported three separate ways, all one bug:

    "Non animating pill super lag wtf"
    "the pill trigger is very laggy and graphically unstable"
    "Trigger glitching out!! press to hold not holding sometimes not
     triggering at all!!!"

The reschedule was:

    self.root.after(max(4, int(delay) - render_elapsed_ms), self._animate)

With delay 16 and a frame that cost 60ms, `16 - 60` is -44, so `max(4, -44)` is
**4**. A frame too slow for its budget queued the next one 4ms later, forever.
Drawing then owned ~94% of the UI thread, Tk's event queue never drained, and a
keypress waited behind a backlog of frames. The pill did not look slow, it
looked frozen, and the trigger looked broken.

Measured on the founder's machine with a game running -- the case he reported
from -- before and after:

    effective fps    16.0  ->  31.0
    draw cost avg    44.3  ->  16.7 ms
    p95              80.9  ->  29.4 ms
    worst           178.4  ->  53.0 ms

Two rules are pinned, and neither is visible on screen: the loop keeps input
headroom at every frame cost, and the expensive visual stands down by itself on
a machine that cannot afford it.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

from knight_flow.pill_motion import (
    FRAME_BUDGET_MS,
    FRAME_DUTY_CYCLE,
    FRAME_RECOVERY_MS,
    effects_downgrade_decision,
    next_frame_delay_ms,
    sustained_frame_cost_ms,
)

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "knight_flow" / "overlay.py"


class TheLoopAlwaysLeavesInputHeadroomTests(unittest.TestCase):
    def test_the_original_bug_cannot_recur(self) -> None:
        """delay 16, cost 60: the old code waited 4ms. It must not."""
        self.assertGreater(
            next_frame_delay_ms(16, 60.0), 4,
            "a 60ms frame still reschedules itself immediately",
        )

    def test_the_duty_cycle_holds_at_every_cost(self) -> None:
        for cost in (1.0, 8.0, 16.0, 30.0, 60.0, 120.0, 200.0):
            with self.subTest(cost=cost):
                wait = next_frame_delay_ms(16, cost)
                share = cost / (cost + wait)
                self.assertLessEqual(
                    share, FRAME_DUTY_CYCLE + 0.05,
                    f"drawing takes {share:.0%} of the thread at a {cost}ms frame cost",
                )

    def test_a_cheap_frame_still_runs_at_the_target_rate(self) -> None:
        """The fix must not slow down a machine that was already fine."""
        self.assertEqual(next_frame_delay_ms(16, 2.0), 14, "a 2ms frame no longer paces at 16ms")
        self.assertEqual(next_frame_delay_ms(33, 3.0), 30)

    def test_a_pathological_frame_does_not_freeze_the_animation(self) -> None:
        self.assertLessEqual(next_frame_delay_ms(16, 5_000.0), 250)

    def test_the_delay_is_never_zero_or_negative(self) -> None:
        for cost in (0.0, 0.4, 15.9, 16.0, 16.1, 1e6):
            self.assertGreaterEqual(next_frame_delay_ms(16, cost), 1)


class TheEffectsStandDownByThemselvesTests(unittest.TestCase):
    def test_sustained_slow_frames_downgrade(self) -> None:
        self.assertTrue(effects_downgrade_decision([60.0] * 5, downgraded=False))

    def test_one_hitch_does_not(self) -> None:
        """A garbage collection or a game grabbing the GPU is not a verdict."""
        self.assertFalse(effects_downgrade_decision([8.0, 8.0, 180.0, 8.0, 8.0], downgraded=False))

    def test_cheap_frames_restore_the_effect(self) -> None:
        self.assertFalse(effects_downgrade_decision([6.0] * 5, downgraded=True))

    def test_there_is_hysteresis_so_it_cannot_flap(self) -> None:
        """The band between the two thresholds is where a single threshold oscillates.

        Downgrading makes frames cheap; if cheap immediately restored the effect,
        the effect would make them expensive again and the pill would visibly
        pulse between two looks.
        """
        self.assertLess(FRAME_RECOVERY_MS, FRAME_BUDGET_MS)
        middle = (FRAME_RECOVERY_MS + FRAME_BUDGET_MS) / 2.0
        self.assertFalse(
            effects_downgrade_decision([middle] * 5, downgraded=False),
            "a mid-band cost turns effects off",
        )
        self.assertTrue(
            effects_downgrade_decision([middle] * 5, downgraded=True),
            "a mid-band cost turns effects back on",
        )

    def test_it_waits_for_enough_frames_before_judging(self) -> None:
        self.assertEqual(sustained_frame_cost_ms([500.0, 500.0], sustained=5), 0.0)
        self.assertFalse(effects_downgrade_decision([500.0, 500.0], downgraded=False))

    def test_the_median_is_used_not_the_mean(self) -> None:
        """A mean of [8,8,180,8,8] is 42.4 and would cross the budget; the median is 8."""
        self.assertEqual(sustained_frame_cost_ms([8.0, 8.0, 180.0, 8.0, 8.0], 5), 8.0)


class TheOverlayActuallyUsesItTests(unittest.TestCase):
    def _animate_source(self) -> str:
        tree = ast.parse(OVERLAY.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_animate":
                return ast.get_source_segment(OVERLAY.read_text(encoding="utf-8"), node) or ""
        raise AssertionError("_animate not found")

    def test_the_old_clamp_is_gone(self) -> None:
        source = self._animate_source()
        self.assertNotIn(
            "max(4, int(delay) - render_elapsed_ms)", source,
            "the reschedule that collapses to 4ms on a slow frame is back",
        )
        self.assertIn("next_frame_delay_ms(", source)

    def test_the_downgrade_is_decided_from_measured_cost(self) -> None:
        source = self._animate_source()
        self.assertIn("effects_downgrade_decision(", source)
        self.assertIn("self._frame_costs.append(", source)

    def test_the_budget_charges_the_draw_and_not_the_queue_drain(self) -> None:
        """Charging queued UI work to the frame budget would slow the animation
        in response to work the animation never did."""
        source = self._animate_source()
        drain = source.index("_drain_ui_commands")
        started = source.index("draw_started =")
        self.assertLess(drain, started, "the draw timer starts before the queue drain")

    def test_the_expensive_visual_respects_the_downgrade(self) -> None:
        text = OVERLAY.read_text(encoding="utf-8")
        gate = text.index("_voice_refracted_active_visual(\n")
        window = text[max(0, gate - 1200):gate]
        self.assertIn("_effects_downgraded", window, "the refraction ignores the downgrade")

    def test_reduce_motion_is_still_the_person_own_choice(self) -> None:
        """The automatic downgrade must be additional to the setting, never replace it."""
        text = OVERLAY.read_text(encoding="utf-8")
        self.assertIn('self.config.get("ui", {}).get("reduce_motion", False)', text)


if __name__ == "__main__":
    unittest.main()
