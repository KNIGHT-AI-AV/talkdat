"""X-631 (interaction grid D12, safety net 1): learned-word notices queue instead of replacing.

Talk DAT! has one undo window: the learned-word notice ("Added X", Undo, a few
seconds). The next notice (a receipt or an "Add X?" offer) destroyed it at
once, so the first word stayed learned and its undo was gone.

Now the next notice waits: the first keeps its full time and its undo, and the
second appears when the first has gone. X-742 made the notice a segment of
the Pill (one outline with the Pill, Undo inside it); the rule is the same.

Runs through scripts/run_tests_offscreen.py.
"""
from __future__ import annotations

import time
import unittest
from unittest import mock

from tests.pill_harness import build_overlay, destroy_overlay, pump


def until(overlay, predicate, seconds: float = 3.0) -> bool:
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        if predicate():
            return True
        pump(overlay.root, 0.02)
    return bool(predicate())


class WordNoticesQueueTests(unittest.TestCase):
    def setUp(self) -> None:
        self.overlay = build_overlay({}, reduce_motion=True)
        self.addCleanup(destroy_overlay, self.overlay)
        quiet = mock.patch("knight_flow.meeting_quiet.meeting_in_progress", return_value=False)
        quiet.start()
        self.addCleanup(quiet.stop)
        self.rejected: list[str] = []

    def showing(self) -> str:
        view = self.overlay._flag_view
        return "" if view is None else view.message.title

    def test_the_second_notice_waits_and_the_first_keeps_its_undo(self) -> None:
        overlay = self.overlay
        overlay.show_learned_word("Alpha", lambda: self.rejected.append("Alpha"))
        self.assertTrue(until(overlay, lambda: self.showing() == 'Added "Alpha"'))
        first = overlay._flag_view
        overlay.show_learned_word("Beta", lambda: self.rejected.append("Beta"))
        pump(overlay.root, 0.3)
        self.assertIs(overlay._flag_view, first, "the second notice replaced the first")
        self.assertEqual([action.label for action in first.message.actions], ["Undo"])

        overlay._flag_choose(0)   # the first word's undo still works
        self.assertTrue(until(overlay, lambda: self.rejected == ["Alpha"]))
        self.assertTrue(until(overlay, lambda: self.showing() == 'Added "Beta"'), "the waiting notice never appeared")
        self.assertIsNot(overlay._flag_view, first)

    def test_an_offer_waits_behind_a_receipt_too(self) -> None:
        overlay = self.overlay
        added: list[str] = []
        overlay.show_learned_word("Alpha", lambda: None)
        self.assertTrue(until(overlay, lambda: self.showing() == 'Added "Alpha"'))
        overlay.offer_learned_word("Gamma", added.append)
        pump(overlay.root, 0.2)
        self.assertEqual(self.showing(), 'Added "Alpha"')
        overlay._flag_contract()
        self.assertTrue(until(overlay, lambda: self.showing() == 'Add "Gamma" to your words?'))
        self.assertEqual([action.label for action in overlay._flag_view.message.actions], ["Add"])
        overlay._flag_choose(0)
        self.assertTrue(until(overlay, lambda: added == ["Gamma"]))


if __name__ == "__main__":
    unittest.main()
