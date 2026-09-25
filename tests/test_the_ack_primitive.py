"""X-620: the ACK, the answer a gesture gets when it has no function where it landed.

Interaction grid, "The ACK primitive": the control's own press response at a
small scale, then stillness. Never a message, never a sound, never a layout,
geometry or focus change. 1 to 2 px over 180 ms (0, +1.5 px at 30%, -0.6 px
at 65%, 0); under reduced motion an opacity dip to 0.88 and back over 140 ms;
one per surface per 700 ms and at most 4 per 3 s app-wide, and a repeat inside
the window does nothing.

The first half is the pure maths in pill_motion. The second half is a real
Pill (run through scripts/run_tests_offscreen.py): one ACK moves the picture
and nothing else, and the limits hold. The last test is the sabotage: with
the rate limit removed, the limit's own check must go red.
"""
from __future__ import annotations

import unittest
from unittest import mock

from knight_flow import pill_motion
from knight_flow.pill_motion import (
    ACK_DURATION_MS,
    ACK_REDUCED_FLOOR,
    ACK_REDUCED_MS,
    AckLimiter,
    ack_offset,
    ack_opacity,
)


class TheMotionTests(unittest.TestCase):
    def test_it_starts_and_ends_still(self) -> None:
        self.assertEqual(ack_offset(0.0), (0, 0))
        self.assertEqual(ack_offset(ACK_DURATION_MS), (0, 0))
        self.assertEqual(ack_offset(ACK_DURATION_MS + 50), (0, 0))

    def test_a_press_goes_down_then_rebounds(self) -> None:
        self.assertEqual(ack_offset(54), (0, 2))    # the +1.5 px peak at 30%, in whole pixels
        self.assertEqual(ack_offset(117), (0, -1))  # the -0.6 px rebound at 65%
        travel = [ack_offset(ms)[1] for ms in range(0, ACK_DURATION_MS + 1)]
        self.assertEqual(max(travel), 2)
        self.assertEqual(min(travel), -1)
        self.assertLess(travel.index(2), travel.index(-1), "the rebound came before the press")

    def test_a_drag_moves_along_its_own_direction(self) -> None:
        self.assertEqual(ack_offset(54, (30.0, 0.0)), (2, 0))
        self.assertEqual(ack_offset(54, (0.0, -4.0)), (0, -2))

    def test_a_late_first_frame_draws_the_key_moment(self) -> None:
        from knight_flow.pill_motion import ack_catch_up

        self.assertEqual(ack_catch_up(30.0, key_shown=False, reduced_motion=False), (30.0, False))
        self.assertEqual(ack_catch_up(90.0, key_shown=False, reduced_motion=False), (54.0, True))
        self.assertEqual(ack_catch_up(90.0, key_shown=True, reduced_motion=False), (90.0, True))
        self.assertEqual(ack_catch_up(100.0, key_shown=False, reduced_motion=True), (70.0, True))

    def test_reduced_motion_dips_to_088_and_back(self) -> None:
        self.assertEqual(ack_opacity(0.0), 1.0)
        self.assertAlmostEqual(ack_opacity(ACK_REDUCED_MS / 2), ACK_REDUCED_FLOOR, places=6)
        self.assertEqual(ack_opacity(ACK_REDUCED_MS), 1.0)
        self.assertTrue(all(ACK_REDUCED_FLOOR - 1e-9 <= ack_opacity(ms) <= 1.0 for ms in range(0, 141)))


def limiter_results(limiter: AckLimiter, calls: list[tuple[str, float]]) -> list[bool]:
    return [limiter.allow(surface, at) for surface, at in calls]


FIVE_IN_THREE_SECONDS = [("pill", 0.0), ("pill", 700.0), ("pill", 1400.0), ("pill", 2100.0), ("pill", 2800.0)]


def the_rate_limit_held(results: list[bool]) -> bool:
    """The limit's own check: of five spaced ACKs inside 3 s, exactly four play."""
    return results == [True, True, True, True, False]


class TheLimitsTests(unittest.TestCase):
    def test_one_per_surface_per_700_ms(self) -> None:
        limiter = AckLimiter()
        self.assertEqual(limiter_results(limiter, [("pill", 0.0), ("pill", 699.0), ("pill", 700.0)]),
                         [True, False, True])

    def test_a_refused_repeat_does_not_restart_the_window(self) -> None:
        limiter = AckLimiter()
        self.assertEqual(limiter_results(limiter, [("pill", 0.0), ("pill", 600.0), ("pill", 710.0)]),
                         [True, False, True])

    def test_surfaces_are_separate_but_the_app_cap_is_shared(self) -> None:
        limiter = AckLimiter()
        calls = [("pill", 0.0), ("ramble_bar", 10.0), ("pill_menu", 20.0), ("x", 30.0), ("y", 40.0)]
        self.assertEqual(limiter_results(limiter, calls), [True, True, True, True, False])
        self.assertTrue(limiter.allow("z", 3001.0))

    def test_the_fifth_inside_three_seconds_plays_nothing(self) -> None:
        self.assertTrue(the_rate_limit_held(limiter_results(AckLimiter(), FIVE_IN_THREE_SECONDS)))


class OnARealPillTests(unittest.TestCase):
    def tearDown(self) -> None:
        from tests.pill_harness import destroy_overlay

        destroy_overlay(getattr(self, "overlay", None))
        self.overlay = None

    def build(self, *, reduce_motion: bool = False):
        from tests.pill_harness import build_overlay

        self.overlay = build_overlay({}, reduce_motion=reduce_motion)
        # Every frame the Pill draws, not a sample after each update(): on a
        # loaded machine one update() can run several frames, and sampling
        # afterwards misses the ones in between.
        self.frames: list[tuple[int, int]] = []
        real = self.overlay._ack_frame

        def recorded(now=None):
            result = real(now)
            self.frames.append((result[0], result[1]))
            return result

        self.overlay._ack_frame = recorded
        return self.overlay

    def watch(self, overlay, seconds: float) -> list[tuple[int, int]]:
        import time

        start = len(self.frames)
        end = time.perf_counter() + seconds
        while time.perf_counter() < end:
            overlay.root.update()
            time.sleep(0.005)
        return self.frames[start:]

    def test_one_ack_moves_the_picture_and_nothing_else(self) -> None:
        import knight_flow.chimes as chimes
        import knight_flow.overlay as overlay_module

        overlay = self.build()
        overlay.set_state("listening", "Hands-free: toggle to stop.")
        self.watch(overlay, 0.5)
        geometry = overlay.root.winfo_geometry()
        last_geometry = overlay._last_geometry
        with mock.patch.object(overlay, "_apply_pill_region") as region, \
                mock.patch.object(chimes, "play_chime") as chime, \
                mock.patch.object(chimes, "play_sound_named") as sound, \
                mock.patch.object(overlay_module, "play_sound_named") as overlay_sound, \
                mock.patch.object(overlay, "_show_toast_now") as toast:
            self.assertTrue(overlay.acknowledge())
            seen = self.watch(overlay, 0.35)
            for _ in range(40):   # a loaded machine draws slowly; let it finish
                if not overlay._ack_is_live():
                    break
                seen += self.watch(overlay, 0.05)
            seen += self.watch(overlay, 0.1)
        # The press itself always reaches the screen (X-620b); how much of the
        # rebound is seen depends on how fast this machine draws frames.
        self.assertIn((0, 2), seen, f"the ACK never showed the press: {seen}")
        self.assertTrue(all(abs(dx) == 0 and -1 <= dy <= 2 for dx, dy in seen), seen)
        self.assertEqual(seen[-1], (0, 0), "the picture did not come to rest")
        self.assertEqual(overlay.root.winfo_geometry(), geometry)
        self.assertEqual(overlay._last_geometry, last_geometry)
        region.assert_not_called()
        for silent in (chime, sound, overlay_sound, toast):
            silent.assert_not_called()
        self.assertEqual(overlay._ack_counts.get("pill"), 1)

    def test_a_slow_frame_still_shows_the_press(self) -> None:
        """X-620b: at 90 ms a frame (X-170's loaded machine) the curve's
        own value is past the press; the frame draws the press instead."""
        overlay = self.build()
        self.assertTrue(overlay.acknowledge())
        start = 1000.0
        self.assertEqual(overlay._ack_frame(start), (0, 0, 1.0))
        self.assertEqual(overlay._ack_frame(start + 0.090), (0, 2, 1.0))
        rest = overlay._ack_frame(start + 0.090 + 0.2)
        self.assertEqual(rest, (0, 0, 1.0))
        self.assertFalse(overlay._ack_is_live())

    def test_an_idle_pill_wakes_for_it_and_sleeps_again(self) -> None:
        overlay = self.build()
        self.watch(overlay, 0.6)   # long enough for the idle loop to be asleep
        self.assertTrue(overlay.acknowledge())
        seen = self.watch(overlay, 0.35)
        self.assertTrue([dy for _dx, dy in seen if dy >= 1], f"a sleeping Pill never showed the ACK: {seen}")
        # A loaded machine draws slowly; give the curve time to finish.
        for _ in range(40):
            if not overlay._ack_is_live():
                break
            seen += self.watch(overlay, 0.05)
        self.assertFalse(overlay._ack_is_live(), "the ACK never ended")
        self.assertEqual(seen[-1], (0, 0))

    def test_a_second_inside_700_ms_plays_nothing(self) -> None:
        overlay = self.build()
        self.assertTrue(overlay.acknowledge())
        self.assertFalse(overlay.acknowledge())
        self.assertEqual(overlay._ack_counts.get("pill"), 1)

    def test_the_fifth_inside_three_seconds_plays_nothing(self) -> None:
        overlay = self.build()
        clock = iter(at for _surface, at in FIVE_IN_THREE_SECONDS)
        with mock.patch.object(overlay, "_ack_clock_ms", side_effect=lambda: next(clock)):
            results = [overlay.acknowledge() for _ in FIVE_IN_THREE_SECONDS]
        self.assertTrue(the_rate_limit_held(results), results)

    def test_reduced_motion_never_moves_it_and_dips_it(self) -> None:
        import knight_flow.overlay as overlay_module

        overlay = self.build(reduce_motion=True)
        real = overlay_module.ImageTk.PhotoImage
        alphas: list[int] = []

        def spy(image=None, *args, **kwargs):
            if image is not None and getattr(image, "mode", "") == "RGBA":
                alphas.append(int(image.getchannel("A").getextrema()[1]))
            return real(image, *args, **kwargs)

        real_layered = overlay._present_layered

        def layered_spy(image, *args, **kwargs):
            if getattr(image, "mode", "") == "RGBA":
                alphas.append(int(image.getchannel("A").getextrema()[1]))
            return real_layered(image, *args, **kwargs)

        with mock.patch.object(overlay_module.ImageTk, "PhotoImage", side_effect=spy), \
                mock.patch.object(overlay, "_present_layered", side_effect=layered_spy):
            self.assertTrue(overlay.acknowledge())
            seen = self.watch(overlay, 0.3)
        self.assertEqual(set(seen), {(0, 0)}, "reduced motion moved the Pill")
        self.assertTrue(any(value <= int(255 * ACK_REDUCED_FLOOR) + 2 for value in alphas),
                        f"no dipped frame was drawn: {alphas}")


class TheSabotageTests(unittest.TestCase):
    def test_without_the_rate_limit_its_own_check_goes_red(self) -> None:
        with mock.patch.object(pill_motion.AckLimiter, "allow", return_value=True):
            results = limiter_results(AckLimiter(), FIVE_IN_THREE_SECONDS)
        self.assertFalse(the_rate_limit_held(results), "the check passed with the limit removed")


if __name__ == "__main__":
    unittest.main()
