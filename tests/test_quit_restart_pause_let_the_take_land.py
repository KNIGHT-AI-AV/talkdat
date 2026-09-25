"""X-630 (interaction grid D10, safety net 5): Quit, Restart, Pause and the install let the take land.

Quit cancelled a live or processing take (the audio was kept in History as
app_closed, but nothing pasted and nothing said so at the moment); the update
install quits 2.2 s after the installer starts, through the same quit; Pause
cancelled; Restart likewise. None of them waited for the paste.

Now a take in flight finishes first: a live one is stopped so it delivers,
then the action waits for the result to land, up to 10 s, and goes ahead
either way. The tray also gets a separator between Panic stop and Quit.
"""
from __future__ import annotations

import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import knight_flow.app as app_module
from knight_flow.app import TalkDatApp


class _Root:
    def __init__(self) -> None:
        self.queued: list = []

    def after(self, _delay, callback):
        self.queued.append(callback)
        return f"after#{len(self.queued)}"

    def run_queued(self) -> None:
        queued, self.queued = self.queued, []
        for callback in queued:
            callback()


def landing_app(*, mic_open: bool = False):
    app = TalkDatApp.__new__(TalkDatApp)
    app.lock = threading.RLock()
    app.session = mock.Mock() if mic_open else None
    app.session_token = object()
    app._released_processing = not mic_open
    app.overlay = SimpleNamespace(root=_Root(), flag=mock.Mock(), set_state=mock.Mock(),
                                  _ui_thread_id=threading.get_ident())
    app.stop_session = mock.Mock()
    return app


def land(app) -> None:
    with app.lock:
        app.session = None
        app.session_token = None


class LetTheTakeLandTests(unittest.TestCase):
    def test_an_action_waits_until_the_result_lands(self) -> None:
        app = landing_app()
        action = mock.Mock()
        self.assertTrue(app._finish_take_then(action, "quit"))
        app.overlay.root.run_queued()
        action.assert_not_called()
        land(app)
        app.overlay.root.run_queued()
        action.assert_called_once()

    def test_it_goes_ahead_after_ten_seconds(self) -> None:
        self.assertEqual(getattr(app_module, "LANDING_WAIT_SECONDS", None), 10.0)
        app = landing_app()
        action = mock.Mock()
        app._finish_take_then(action, "quit")
        app._landing_deadline = time.monotonic() - 0.1
        app.overlay.root.run_queued()
        action.assert_called_once()

    def test_a_live_take_is_stopped_so_it_delivers(self) -> None:
        app = landing_app(mic_open=True)
        app._finish_take_then(mock.Mock(), "pause")
        app.stop_session.assert_called_once()

    def test_nothing_in_flight_means_no_wait(self) -> None:
        app = landing_app()
        land(app)
        self.assertFalse(app._finish_take_then(mock.Mock(), "quit"))

    def test_a_second_pause_while_waiting_pauses_once_and_quit_still_runs(self) -> None:
        app = landing_app()
        order: list[str] = []
        app._finish_take_then(lambda: order.append("pause"), "pause")
        app._finish_take_then(lambda: order.append("pause again"), "pause")
        app._finish_take_then(lambda: order.append("quit"), "quit")
        land(app)
        app.overlay.root.run_queued()
        self.assertEqual(order, ["pause again", "quit"])

    def test_quit_does_not_touch_a_landing_take(self) -> None:
        app = landing_app()
        token = app.session_token
        app.finalize_safety_capture = mock.Mock()
        app.quit()
        self.assertIs(app.session_token, token, "Quit cancelled the take that was landing")
        app.finalize_safety_capture.assert_not_called()
        self.assertTrue(app._after_landing)

    def test_restart_and_pause_wait_too(self) -> None:
        app = landing_app()
        app.paused = False
        app.restart()
        app.toggle_pause()
        self.assertFalse(app.paused, "Pause went ahead with the take in flight")
        self.assertEqual(sorted(app._after_landing), ["pause", "restart"])

    def test_the_install_quits_through_the_same_quit(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "knight_flow" / "app.py").read_text(encoding="utf-8")
        self.assertIn("self.overlay.root.after(2200, self.quit)", source)

    def test_the_tray_fences_quit_off_from_panic_stop(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "knight_flow" / "tray.py").read_text(encoding="utf-8")
        panic = source.index('pystray.MenuItem("Panic stop"')
        quit_item = source.index('pystray.MenuItem("Quit Talk DAT!"')
        self.assertIn("pystray.Menu.SEPARATOR", source[panic:quit_item])


if __name__ == "__main__":
    unittest.main()
