"""X-415: the rainbow waits for the release.

His words, testing 0.4.128 in Executive mode: "I don't want it to visibly
show a rainbow until the user lets go... Rainbow's just to let the user
know that hey, we're no longer listening, we're processing."

During a hold the progressive planner (X-405) transcribes closed segments in
the background, and the local engine reports "loading_model" or
"transcribing" through the session status callback while it does. The app
mapped those straight to the processing state, so the Pill went rainbow with
the trigger still down and the microphone still open. The background work
stays (it saves time); the Pill does not repaint until the stop is requested.
"""
from __future__ import annotations

import threading
import unittest

from knight_flow.app import ENGINE_WORK_STATUSES, TalkDatApp


class RecordingOverlay:
    def __init__(self) -> None:
        self.states: list[tuple[str, str | None]] = []

    def set_state(self, state: str, message: str | None = None, preview: str | None = None, **_kwargs) -> None:
        self.states.append((state, message))

    def set_level(self, level: float) -> None:
        pass

    @property
    def state(self) -> str:
        return self.states[-1][0] if self.states else "idle"


def app_mid_session(control: str) -> tuple[TalkDatApp, RecordingOverlay, object]:
    app = TalkDatApp.__new__(TalkDatApp)
    app.lock = threading.RLock()
    token = object()
    app.session_token = token
    app.session_chime_token = None
    app.session_control = control
    app._released_processing = False
    app.overlay = RecordingOverlay()
    app.play_sound = lambda *_args, **_kwargs: None
    return app, app.overlay, token


class ThePillStaysLiveWhileHeldTests(unittest.TestCase):
    def test_engine_work_during_a_hold_never_paints_processing(self) -> None:
        app, overlay, token = app_mid_session("hold")
        app.on_session_status(token, "dictation", "listening", "hold")
        self.assertEqual(overlay.state, "listening")
        for status in sorted(ENGINE_WORK_STATUSES):
            with self.subTest(status=status):
                app.on_session_status(token, "dictation", status, "hold")
                self.assertEqual(overlay.state, "listening", f"{status} repainted the Pill mid-hold")

    def test_the_same_statuses_paint_processing_once_the_stop_is_requested(self) -> None:
        app, overlay, token = app_mid_session("hold")
        app.on_session_status(token, "dictation", "listening", "hold")
        app._released_processing = True  # what stop_session sets at the release
        app.on_session_status(token, "dictation", "transcribing", "hold")
        self.assertEqual(overlay.state, "processing")

    def test_hands_free_is_held_to_the_same_rule(self) -> None:
        app, overlay, token = app_mid_session("hands_free")
        app.on_session_status(token, "dictation", "listening", "hands_free")
        app.on_session_status(token, "dictation", "loading_model", "hands_free")
        self.assertEqual(overlay.state, "listening")

    def test_a_credit_guard_that_closes_the_mic_still_shows(self) -> None:
        # time_limit, silence and no-speech close the microphone on their
        # own; the person must see that, so they are not engine work.
        app, overlay, token = app_mid_session("hold")
        app.on_session_status(token, "dictation", "listening", "hold")
        app.on_session_status(token, "dictation", "silence_timeout", "hold")
        self.assertEqual(overlay.state, "processing")

    def test_a_stale_token_changes_nothing(self) -> None:
        app, overlay, token = app_mid_session("hold")
        app.on_session_status(object(), "dictation", "transcribing", "hold")
        self.assertEqual(overlay.states, [])


if __name__ == "__main__":
    unittest.main()
