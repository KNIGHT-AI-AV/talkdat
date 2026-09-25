"""X-625 (interaction grid, Pill double-click): a double-click is one decision.

A double-click on the Pill started a hands-free take and stopped it again a
beat later. Nothing is recorded in that half second, so the Pill flashed and
went back to idle, which reads as broken. The hand meant "do it, I was not
sure the first one took".

Now a second click inside the person's double-click time is an ACK, measured
from the previous click so a triple click is one decision as well. A click
after the double-click time is a new decision as before.

Runs through scripts/run_tests_offscreen.py.
"""
from __future__ import annotations

import unittest
from unittest import mock

from tests.pill_harness import Counter, body_point, build_overlay, click, destroy_overlay, pump


class _FakeClock:
    """A monotonic clock the test moves by hand.

    Real Aqua compositing (there is no hidden virtual desktop here, unlike
    Windows) adds a real, load-dependent tens-to-hundreds of ms to every
    click's own ACK redraw. The Pill's double-click bookkeeping reads
    time.monotonic() directly, so a gap expressed as a real `pump()` sleep
    landed right on the 500 ms boundary and flaked under load. Faking the
    clock makes the gap exact no matter how long a real redraw takes.
    """

    def __init__(self) -> None:
        self.value = 1_000_000.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class APillDoubleClickIsOneDecisionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.hands_free = Counter()
        self.overlay = build_overlay({"hands_free": self.hands_free})
        self.addCleanup(destroy_overlay, self.overlay)
        # A fixed 500 ms (the Windows default), so the gaps below mean the
        # same thing on every machine.
        self.double_click = mock.patch.object(self.overlay, "_double_click_seconds", return_value=0.5, create=True)
        self.double_click.start()
        self.addCleanup(self.double_click.stop)
        self.clock = _FakeClock()
        self.time_patch = mock.patch("knight_flow.overlay.time.monotonic", self.clock)
        self.time_patch.start()
        self.addCleanup(self.time_patch.stop)

    def click_twice(self, gap: float) -> None:
        click(self.overlay, *body_point(self.overlay))
        self.clock.advance(gap)
        pump(self.overlay.root, 0.02)
        click(self.overlay, *body_point(self.overlay))
        pump(self.overlay.root, 0.02)

    def test_two_clicks_350_ms_apart_are_one_toggle_and_one_ack(self) -> None:
        self.click_twice(0.35)
        self.assertEqual(self.hands_free.calls, 1, "the double-click started and stopped a take")
        self.assertEqual(self.overlay._ack_counts.get("pill"), 1)

    def test_a_triple_click_is_one_toggle(self) -> None:
        self.click_twice(0.3)
        self.clock.advance(0.3)
        pump(self.overlay.root, 0.02)
        click(self.overlay, *body_point(self.overlay))
        self.assertEqual(self.hands_free.calls, 1)

    def test_two_clicks_700_ms_apart_are_two_decisions(self) -> None:
        self.click_twice(0.7)
        self.assertEqual(self.hands_free.calls, 2)
        self.assertIsNone(self.overlay._ack_counts.get("pill"))

    def test_the_double_click_time_is_read_from_the_system(self) -> None:
        from knight_flow.overlay import Overlay

        seconds = Overlay._double_click_seconds(self.overlay)
        self.assertTrue(0.1 <= seconds <= 5.0, seconds)


if __name__ == "__main__":
    unittest.main()
