"""X-628 (interaction grid D8): an auto-stopped take pastes only where it started.

A hands-free take that nobody stops ends by itself: 15 s with no speech, 45 s
of silence, or the time limit. It then pasted into whatever app had the focus
at that moment, which after 45 seconds is often not the one the person was
dictating into.

Now the take remembers the window it started in. When the app ended the take
and another window has the focus at delivery, the words are copied and kept
in History instead of typed, with one line. A stop the person made pastes
where they are, as always.
"""
from __future__ import annotations

import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from knight_flow.app import TalkDatApp
from tests.test_esc_while_processing_keeps_the_words import deliver, processing_app


def started_in(app, token, window: int) -> None:
    app._flight_window = (token, window)


class AnAutoStoppedTakeTests(unittest.TestCase):
    def test_the_timeout_statuses_mark_the_take(self) -> None:
        for status in ("time_limit", "no_speech_timeout", "silence_timeout"):
            with self.subTest(status=status):
                app, token = processing_app()
                app.session_control = "hands_free"
                app.on_session_status(token, "dictation", status, "hands_free")
                self.assertIs(app._auto_stopped_token, token)

    def test_auto_stopped_in_another_window_is_kept_not_pasted(self) -> None:
        app, token = processing_app()
        started_in(app, token, 111)
        app._auto_stopped_token = token
        with patch("knight_flow.app.foreground_window_id", return_value=222):
            calls = deliver(app, token)
        self.assertEqual([call["paste_mode"] for call in calls], ["copy_only"], "it typed into another app")
        self.assertEqual(len(app.history), 1)
        self.assertEqual(app.overlay.states[-1], ("captured", "Kept, not pasted: you moved to another window."))

    def test_auto_stopped_in_the_same_window_pastes(self) -> None:
        app, token = processing_app()
        started_in(app, token, 111)
        app._auto_stopped_token = token
        with patch("knight_flow.app.foreground_window_id", return_value=111):
            calls = deliver(app, token)
        self.assertEqual([call["paste_mode"] for call in calls], ["clipboard"])

    def test_a_stop_you_made_pastes_where_you_are(self) -> None:
        app, token = processing_app()
        started_in(app, token, 111)
        with patch("knight_flow.app.foreground_window_id", return_value=222):
            calls = deliver(app, token)
        self.assertEqual([call["paste_mode"] for call in calls], ["clipboard"])

    def test_an_unknown_start_window_proves_nothing(self) -> None:
        app, token = processing_app()
        started_in(app, token, 0)
        app._auto_stopped_token = token
        with patch("knight_flow.app.foreground_window_id", return_value=222):
            calls = deliver(app, token)
        self.assertEqual([call["paste_mode"] for call in calls], ["clipboard"])

    def test_the_start_records_the_window(self) -> None:
        source = TalkDatApp.start_session.__code__
        self.assertIn("foreground_window_id", source.co_names)


if __name__ == "__main__":
    unittest.main()
