"""X-621 (interaction grid D2): a Pill click while processing is an ACK, never a redo.

Once the finisher had released the session, a click on the Pill reached
start_session as a trigger press, press_intent read it as "no, redo", and the
take that was landing was cancelled while a new hands-free take opened. An
impatient click on the rainbow, or a slow double-click to stop, threw the
words away.

On the Pill a press while processing means "is it working?". It gets the ACK
and the result lands. The redo stays on the hotkeys, where a second press
after a beat is a deliberate decision (X-106).

The GUI half runs through scripts/run_tests_offscreen.py.
"""
from __future__ import annotations

import threading
import time
import types
import unittest
from unittest import mock

from tests.pill_harness import Counter, body_point, build_overlay, click, destroy_overlay, pump


def processing_app(*, session: object | None = None, released: bool = True):
    import knight_flow.app as app_module

    app = types.SimpleNamespace()
    app.lock = threading.Lock()
    app._wake_runtime = None
    app.session = session
    token = object()
    app.session_token = token
    app._released_processing = released
    app._trigger_released_at = time.perf_counter() - 1.0   # well past the bounce window
    app._last_hands_free_toggle_at = 0.0
    app.paused = False
    app.overlay = mock.Mock()
    app.overlay._ui_thread_id = threading.get_ident()
    app.cancel = mock.Mock()
    app.stop_session = mock.Mock()
    app._scribe_busy = lambda: False
    app.config = {"stt": {"provider": "local", "providers": {}}, "dictation": {}}

    class Past(Exception):
        pass

    def reached_the_gate(*_args, **_kwargs):
        raise Past()

    app._maybe_return_to_cloud = reached_the_gate
    app.start_session = lambda *a, **k: app_module.TalkDatApp.start_session(app, *a, **k)
    return app_module, app, token, Past


class TheAppSideTests(unittest.TestCase):
    def test_a_pill_click_on_a_landing_result_is_acknowledged(self) -> None:
        app_module, app, token, _past = processing_app()
        app_module.TalkDatApp.toggle_hands_free(app, source="pill")
        app.cancel.assert_not_called()
        self.assertIs(app.session_token, token, "the landing result was replaced")
        app.overlay.acknowledge.assert_called_once_with("pill")

    def test_the_same_while_the_mic_is_closing(self) -> None:
        app_module, app, token, _past = processing_app(session=mock.Mock(), released=True)
        app_module.TalkDatApp.toggle_hands_free(app, source="pill")
        app.stop_session.assert_not_called()
        app.cancel.assert_not_called()
        app.overlay.acknowledge.assert_called_once_with("pill")

    def test_the_hotkey_keeps_its_redo(self) -> None:
        app_module, app, _token, past = processing_app()
        with self.assertRaises(past):
            app_module.TalkDatApp.toggle_hands_free(app)
        app.cancel.assert_called_once()
        app.overlay.acknowledge.assert_not_called()

    def test_a_pill_click_still_stops_an_open_microphone(self) -> None:
        app_module, app, _token, _past = processing_app(session=mock.Mock(), released=False)
        app_module.TalkDatApp.toggle_hands_free(app, source="pill")
        app.stop_session.assert_called_once()
        app.overlay.acknowledge.assert_not_called()


class ThePillSideTests(unittest.TestCase):
    def setUp(self) -> None:
        self.hands_free = Counter()
        self.overlay = build_overlay({"hands_free": self.hands_free})

    def tearDown(self) -> None:
        destroy_overlay(self.overlay)

    def test_a_click_on_the_rainbow_toggles_nothing_and_acks(self) -> None:
        self.overlay.set_state("processing", "Formatting transcript.")
        pump(self.overlay.root, 0.3)
        click(self.overlay, *body_point(self.overlay))
        pump(self.overlay.root, 0.05)
        self.assertEqual(self.hands_free.calls, 0, "a click on the rainbow started a redo")
        self.assertEqual(self.overlay._ack_counts.get("pill"), 1)

    def test_an_idle_click_still_toggles(self) -> None:
        click(self.overlay, *body_point(self.overlay))
        self.assertEqual(self.hands_free.calls, 1)
        self.assertIsNone(self.overlay._ack_counts.get("pill"))


if __name__ == "__main__":
    unittest.main()
