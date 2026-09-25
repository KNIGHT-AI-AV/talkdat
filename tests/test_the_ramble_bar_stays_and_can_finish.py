"""X-632 (interaction grid D13, d14): the ramble bar keeps showing, and can finish the ramble.

The rainbow RAMBLE bar is the only loud marker of a hands-free take that can
run for an hour. A double-click hid it while the ramble kept recording, and
the bar itself had no way to end the ramble.

Now a click or double-click on the bar gets the ACK and the bar stays; a
Finish control on the bar ends the ramble (only a ramble that is still
recording). A press on Finish released off it does nothing.

The GUI half runs through scripts/run_tests_offscreen.py.
"""
from __future__ import annotations

import threading
import tkinter as tk
import types
import unittest
from unittest import mock

from tests.pill_harness import Counter, build_overlay, destroy_overlay, pump


class TheBarTests(unittest.TestCase):
    def setUp(self) -> None:
        self.finish = Counter()
        self.hands_free = Counter()
        self.overlay = build_overlay({"ramble_finish": self.finish, "hands_free": self.hands_free})
        self.addCleanup(destroy_overlay, self.overlay)
        self.overlay.show_ramble_indicator()
        pump(self.overlay.root, 0.3)
        self.bar = self.overlay._ramble_indicator
        self.canvas = next(child for child in self.bar.winfo_children() if isinstance(child, tk.Canvas))

    def at(self, x: int, y: int, sequence: str) -> None:
        self.canvas.event_generate(sequence, x=x, y=y, rootx=self.canvas.winfo_rootx() + x,
                                   rooty=self.canvas.winfo_rooty() + y)

    def click(self, x: int, y: int) -> None:
        self.at(x, y, "<ButtonPress-1>")
        self.at(x, y, "<ButtonRelease-1>")

    def finish_point(self) -> tuple[int, int]:
        return int(self.canvas.winfo_width()) - 12, int(self.canvas.winfo_height()) // 2

    def test_a_double_click_leaves_the_bar_up_and_acks(self) -> None:
        self.click(20, 10)
        self.click(20, 10)
        pump(self.overlay.root, 0.4)
        self.assertTrue(self.bar.winfo_exists(), "a double-click hid the bar of a live ramble")
        self.assertFalse(bool(getattr(self.bar, "_talkdat_popup_close_requested", False)),
                         "a double-click started closing the bar of a live ramble")
        self.assertIs(self.overlay._ramble_indicator, self.bar)
        self.assertEqual(self.overlay._ack_counts.get("ramble_bar"), 1)
        self.assertEqual((self.finish.calls, self.hands_free.calls), (0, 0))

    def test_finish_ends_the_ramble(self) -> None:
        self.click(*self.finish_point())
        self.assertEqual(self.finish.calls, 1)
        self.assertEqual(self.hands_free.calls, 0)

    def test_a_press_on_finish_released_elsewhere_is_never_mind(self) -> None:
        self.at(*self.finish_point(), "<ButtonPress-1>")
        self.at(20, 10, "<ButtonRelease-1>")
        self.assertEqual(self.finish.calls, 0)


class TheAppFinishesOnlyARambleTests(unittest.TestCase):
    def finish(self, *, mode: str, released: bool = False, session: object | None = object()):
        import knight_flow.app as app_module

        app = types.SimpleNamespace(lock=threading.Lock(), session=session, session_mode=mode,
                                    _released_processing=released, stop_session=mock.Mock(),
                                    overlay=types.SimpleNamespace(_ui_thread_id=threading.get_ident()))
        app_module.TalkDatApp.finish_ramble_take(app)
        return app.stop_session

    def test_a_recording_ramble_stops(self) -> None:
        self.finish(mode="ramble").assert_called_once()

    def test_anything_else_is_left_alone(self) -> None:
        self.finish(mode="dictation").assert_not_called()
        self.finish(mode="ramble", released=True).assert_not_called()
        self.finish(mode="ramble", session=None).assert_not_called()


if __name__ == "__main__":
    unittest.main()
