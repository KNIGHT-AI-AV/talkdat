"""X-635 (interaction grid D5, build 9): press-and-hold on the Pill is hold-to-talk.

A walkie-talkie press on the Pill did nothing while held and started a
hands-free take on release, so it recorded after the person had spoken.

Now a press held 450 ms on an idle Pill starts a hold take (push_to_talk);
the release ends it: with words heard it stops and delivers, with nothing
heard it stays open as a hands-free take (a slow click). A release before
450 ms is a click, as before; a press that moves past the slop before 450 ms
is a drag and starts nothing; sliding 40 px off during the hold cancels that
take (its audio is kept in History).

The GUI half runs through scripts/run_tests_offscreen.py.
"""
from __future__ import annotations

import threading
import types
import unittest
from unittest import mock

from tests.pill_harness import Counter, body_point, build_overlay, canvas_point, destroy_overlay, pump


class ThePillTests(unittest.TestCase):
    def setUp(self) -> None:
        self.counters = {name: Counter() for name in ("push_to_talk", "pill_hold_release", "pill_hold_cancel",
                                                       "hands_free")}
        self.overlay = build_overlay(dict(self.counters))
        self.addCleanup(destroy_overlay, self.overlay)
        self.point = body_point(self.overlay)

    def calls(self) -> tuple[int, ...]:
        return tuple(self.counters[name].calls for name in ("push_to_talk", "pill_hold_release",
                                                            "pill_hold_cancel", "hands_free"))

    def event(self, sequence: str, dx: int = 0, *, state: int = 0) -> None:
        x, y, rx, ry = canvas_point(self.overlay, self.point[0] + dx, self.point[1])
        self.overlay.canvas.event_generate(sequence, x=x, y=y, rootx=rx, rooty=ry, state=state)

    def test_a_held_press_is_hold_to_talk(self) -> None:
        self.event("<ButtonPress-1>")
        pump(self.overlay.root, 0.6)
        self.assertEqual(self.calls(), (1, 0, 0, 0), "a held press did not start talking")
        self.event("<ButtonRelease-1>")
        self.assertEqual(self.calls(), (1, 1, 0, 0), "the release did not end the hold, or also toggled")

    def test_a_quick_press_is_still_a_click(self) -> None:
        self.event("<ButtonPress-1>")
        pump(self.overlay.root, 0.15)
        self.event("<ButtonRelease-1>")
        pump(self.overlay.root, 0.5)
        self.assertEqual(self.calls(), (0, 0, 0, 1))

    def test_a_drag_before_the_hold_starts_nothing(self) -> None:
        self.event("<ButtonPress-1>")
        pump(self.overlay.root, 0.2)
        self.event("<B1-Motion>", 30, state=0x100)
        pump(self.overlay.root, 0.5)
        self.event("<ButtonRelease-1>", 30)
        self.assertEqual(self.calls(), (0, 0, 0, 0))

    def test_sliding_off_during_the_hold_cancels_that_take(self) -> None:
        self.event("<ButtonPress-1>")
        pump(self.overlay.root, 0.6)
        self.event("<B1-Motion>", 90, state=0x100)
        self.event("<ButtonRelease-1>", 90)
        self.assertEqual(self.calls(), (1, 0, 1, 0))
        self.assertIsNone(self.overlay._ack_counts.get("pill"), "an ACK played after a cancel")

    def test_no_hold_on_a_live_or_processing_pill(self) -> None:
        for state in ("listening", "processing"):
            with self.subTest(state=state):
                self.overlay.set_state(state, "")
                pump(self.overlay.root, 0.3)
                self.event("<ButtonPress-1>")
                pump(self.overlay.root, 0.6)
                self.event("<ButtonRelease-1>")
                self.assertEqual(self.counters["push_to_talk"].calls, 0)
                self.overlay._last_pill_click_at = None


class TheAppReleaseTests(unittest.TestCase):
    def app(self, *, heard: bool):
        import knight_flow.app as app_module

        app = types.SimpleNamespace(lock=threading.Lock(), session=object(), session_token=object(),
                                    session_control="hold", _released_processing=False,
                                    _last_hands_free_toggle_at=0.0, stop_session=mock.Mock(),
                                    overlay=mock.Mock(), _session_heard_voice=lambda _session: heard)
        app.overlay._ui_thread_id = threading.get_ident()
        app_module.TalkDatApp.pill_hold_release(app)
        return app

    def test_with_words_heard_the_release_delivers(self) -> None:
        app = self.app(heard=True)
        app.stop_session.assert_called_once()
        self.assertEqual(app.session_control, "hold")

    def test_with_nothing_heard_it_becomes_a_hands_free_take(self) -> None:
        app = self.app(heard=False)
        app.stop_session.assert_not_called()
        self.assertEqual(app.session_control, "hands_free")
        app.overlay.set_state.assert_called_with("listening", "Hands-free: toggle to stop.")

    def test_the_voice_check_treats_doubt_as_speech(self) -> None:
        from knight_flow.app import TalkDatApp

        app = TalkDatApp.__new__(TalkDatApp)
        quiet = types.SimpleNamespace(current_text=lambda: "", captured_audio=lambda: (b"\x00\x00" * 1600, 16000, 1, False))
        spoken = types.SimpleNamespace(current_text=lambda: "hello", captured_audio=quiet.captured_audio)
        broken = types.SimpleNamespace(current_text=lambda: (_ for _ in ()).throw(RuntimeError("gone")))
        self.assertFalse(app._session_heard_voice(quiet))
        self.assertTrue(app._session_heard_voice(spoken))
        self.assertTrue(app._session_heard_voice(broken))


if __name__ == "__main__":
    unittest.main()
