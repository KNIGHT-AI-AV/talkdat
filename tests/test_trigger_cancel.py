"""X-106: the trigger press means the right thing every time.

One key, three meanings, decided by timing: key-repeat while the mic is
open means nothing; a re-press within the bounce window is finger chatter
and must never throw away the in-flight result; a re-press after a beat is
"no, redo" -- cancel what is in flight and let the same press start the
new dictation.
"""
from __future__ import annotations

import threading
import time
import types
import unittest
from unittest import mock

from knight_flow.trigger_intent import (
    BOUNCE_MS,
    PRESS_BOUNCE,
    PRESS_CANCEL_AND_RESTART,
    PRESS_IGNORE,
    PRESS_START,
    press_intent,
)


class PressIntentTableTests(unittest.TestCase):
    def test_key_repeat_while_recording_is_ignored(self) -> None:
        self.assertEqual(
            press_intent(recording=True, processing=False, ms_since_release=None),
            PRESS_IGNORE,
        )

    def test_a_plain_press_starts(self) -> None:
        self.assertEqual(
            press_intent(recording=False, processing=False, ms_since_release=None),
            PRESS_START,
        )

    def test_a_chattering_repress_is_a_bounce_not_a_cancel(self) -> None:
        """Say one word, let go, key chatters 120ms later: the in-flight
        result is worth more than a twitch."""
        self.assertEqual(
            press_intent(recording=False, processing=True, ms_since_release=120.0),
            PRESS_BOUNCE,
        )

    def test_a_deliberate_repress_cancels_and_restarts(self) -> None:
        self.assertEqual(
            press_intent(recording=False, processing=True, ms_since_release=800.0),
            PRESS_CANCEL_AND_RESTART,
        )

    def test_the_boundary_is_exactly_the_bounce_window(self) -> None:
        self.assertEqual(
            press_intent(recording=False, processing=True, ms_since_release=BOUNCE_MS - 1),
            PRESS_BOUNCE,
        )
        self.assertEqual(
            press_intent(recording=False, processing=True, ms_since_release=float(BOUNCE_MS)),
            PRESS_CANCEL_AND_RESTART,
        )

    def test_an_unknown_release_time_still_allows_the_cancel(self) -> None:
        """No timestamp means we cannot prove a bounce; a deliberate press
        must still be able to cancel."""
        self.assertEqual(
            press_intent(recording=False, processing=True, ms_since_release=None),
            PRESS_CANCEL_AND_RESTART,
        )


class StartSessionHonoursTheIntentTests(unittest.TestCase):
    """Drive the REAL start_session gate with a stub app mid-processing."""

    def fake_app(self, *, released_ms_ago: float | None):
        import knight_flow.app as app_module

        app = types.SimpleNamespace()
        app.lock = threading.Lock()
        app.session = object()          # a dictation is in flight
        app.session_token = object()
        app._released_processing = released_ms_ago is not None
        app._trigger_released_at = (
            time.perf_counter() - released_ms_ago / 1000.0
            if released_ms_ago is not None
            else None
        )
        app.paused = False
        app._scribe_busy = lambda: app_module.TalkDatApp._scribe_busy(app)
        app.overlay = types.SimpleNamespace(
            set_state=lambda *a, **k: None,
            root=types.SimpleNamespace(after=lambda *a, **k: None),
        )
        app.config = {"stt": {"provider": "local", "providers": {}}, "dictation": {}}
        app.cancel = mock.Mock()
        app.canceled = app.cancel
        return app_module, app

    def run_gate(self, app_module, app):
        # Sentinel raised past the gate so the test stops at the decision.
        class Past(Exception):
            pass

        def boom():
            raise Past()

        app._maybe_return_to_cloud = boom
        try:
            app_module.TalkDatApp.start_session(app, "ptt", "Listening...")
        except Past:
            return "proceeded"
        return "returned"

    def test_bounce_leaves_the_flight_alone(self) -> None:
        app_module, app = self.fake_app(released_ms_ago=100.0)
        outcome = self.run_gate(app_module, app)
        self.assertEqual(outcome, "returned")
        app.cancel.assert_not_called()

    def test_deliberate_repress_cancels_then_proceeds(self) -> None:
        app_module, app = self.fake_app(released_ms_ago=900.0)
        outcome = self.run_gate(app_module, app)
        self.assertEqual(outcome, "proceeded", "the same press must start the redo")
        app.cancel.assert_called_once()

    def test_mid_recording_press_never_cancels(self) -> None:
        app_module, app = self.fake_app(released_ms_ago=None)
        outcome = self.run_gate(app_module, app)
        self.assertEqual(outcome, "returned")
        app.cancel.assert_not_called()


if __name__ == "__main__":
    unittest.main()



class PillToggleChatterTests(unittest.TestCase):
    """X-115: two pill toggles inside a quarter second are one decision plus
    chatter. An impatient double-click used to open a session and slam it
    shut milliseconds later -- "activates and deactivates and just breaks"."""

    def _app(self):
        import threading
        from knight_flow.app import TalkDatApp

        app = TalkDatApp.__new__(TalkDatApp)
        app.lock = threading.Lock()
        app.session = None
        app._last_hands_free_toggle_at = 0.0
        app.calls = []
        app.stop_session = lambda: app.calls.append("stop")
        app.start_session = lambda *a, **k: app.calls.append("start")
        return app

    def test_a_double_click_is_one_toggle(self) -> None:
        app = self._app()
        app.toggle_hands_free()
        app.toggle_hands_free()  # immediately after: chatter
        self.assertEqual(app.calls, ["start"])

    def test_a_deliberate_second_toggle_still_stops(self) -> None:
        import time as _time

        app = self._app()
        app.toggle_hands_free()
        app.session = object()  # the first toggle's session is now live
        app._last_hands_free_toggle_at -= 0.3  # a beat later
        app.toggle_hands_free()
        self.assertEqual(app.calls, ["start", "stop"])
