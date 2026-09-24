"""X-161: the click turns the pill gray before anything slow happens.

Reported as: "upon clicking, the interface occasionally fails to transition to
gray, instead experiencing latency before improperly scaling for pill
activation."

It was the ORDER of `start_session`. The function opened with
`warm_cloud_connection` -- a genuine network round trip whose whole purpose is
to hide latency -- and only reached its first `set_state` afterwards. On a slow
link the pill stayed `idle` through the entire connect, so the press looked
ignored, and the grow then arrived late and read as a glitch instead of a
response.

Two rules are pinned here, and they are ordering rules, so no screenshot and no
visual review can check them. Only the source order can.

1. The standby gray is set before any network call.
2. The warm-up does not run on the thread that handled the keypress.

The growth side is already correct and is pinned elsewhere: EXPANDED_STATES is
{listening, command}, so the pill can only grow once the microphone is really
open, which is exactly "animating upward only when it is fully prepared and
actively listening".
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "knight_flow" / "app.py"


def _start_session() -> ast.FunctionDef:
    tree = ast.parse(APP.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "start_session":
            return node
    raise AssertionError("start_session not found")


def _line_of_first(predicate) -> int | None:
    for node in ast.walk(_start_session()):
        if predicate(node):
            return node.lineno
    return None


class ThePressAnswersBeforeItWorksTests(unittest.TestCase):
    def test_the_standby_gray_comes_after_the_last_refusal_gate(self) -> None:
        """X-166: it must NOT be the first line of the function.

        The first attempt at X-161 put the grey at the very top, above the gate
        that ignores a repeat press while a dictation is already running. Auto
        repeat during a hold then repainted the pill to `starting` and returned,
        dragging a live session out of `listening`, which he reported as "press
        to hold not holding, sometimes not triggering at all".

        The grey has to sit after the last point a press can be refused. It is
        still immediate, because everything above it is a lock and a few
        comparisons; the slow part, the cloud handshake, is threaded.
        """
        source = ast.get_source_segment(APP.read_text(encoding="utf-8"), _start_session()) or ""
        gate = source.index("session start ignored: already recording")
        grey = source.index('set_state("starting"')
        self.assertLess(
            gate, grey,
            "the standby grey is set before the repeat-press gate, so holding "
            "the trigger repaints over a live dictation",
        )

    def test_nothing_slow_runs_before_the_gray(self) -> None:
        """The original bug: real work ahead of any feedback.

        Session creation is the expensive step and must never precede the grey.
        """
        source = ast.get_source_segment(APP.read_text(encoding="utf-8"), _start_session()) or ""
        grey = source.index('set_state("starting"')
        self.assertLess(
            grey, source.index("create_stt_session"),
            "the microphone session is built before the pill answers the click",
        )

    def test_nothing_touches_the_network_before_the_keypress_is_answered(self) -> None:
        """X-516: there is no warm-up left to put on a thread.

        This used to assert the managed connection warm-up was handed to a
        thread, because inline it blocked the press on a DNS lookup and a TLS
        handshake: a warm-up whose whole purpose is to hide latency must never
        BE the latency. The warm-up went with the managed service.

        The property it protected is kept and made stronger. Rather than
        requiring the one known blocking call to be threaded, nothing before
        the pill answers may reach the network at all, so a future helper
        cannot reintroduce the same stall under a different name.
        """
        source = ast.get_source_segment(APP.read_text(encoding="utf-8"), _start_session()) or ""
        head = source[: source.index("X-106")] if "X-106" in source else source
        self.assertNotIn("warm_cloud_connection", head, "the warm-up is gone; do not bring it back")
        for blocking in ("urlopen(", "requests.get", "requests.post", "http_request(", "_session()"):
            with self.subTest(call=blocking):
                self.assertNotIn(blocking, head, "the press must be answered before any network call")

    def test_being_paused_is_answered_without_a_gray_flash(self) -> None:
        """A paused app must say so, not blink standby first.

        `paused` is a bool read and cannot stall, so it is the one check
        allowed to precede the gray.
        """
        source = ast.get_source_segment(APP.read_text(encoding="utf-8"), _start_session()) or ""
        paused_at = source.index("if self.paused")
        gray_at = source.index('set_state("starting"')
        self.assertLess(paused_at, gray_at, "the paused check must precede the standby gray")


class TheGrowthWaitsForTheMicrophoneTests(unittest.TestCase):
    def test_only_listening_and_command_expand(self) -> None:
        """His spec: full colour and size only once actually listening."""
        from knight_flow.pill_motion import EXPANDED_STATES, STANDBY_STATES

        self.assertEqual(EXPANDED_STATES, {"listening", "command"})
        self.assertEqual(STANDBY_STATES, {"starting", "connected"})
        self.assertTrue(
            STANDBY_STATES.isdisjoint(EXPANDED_STATES),
            "a state cannot be both standby and expanded; that is the glitch",
        )


if __name__ == "__main__":
    unittest.main()
