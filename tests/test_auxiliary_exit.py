import queue, threading, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from knight_flow.app import TalkDatApp
from knight_flow.mic_registry import MicrophoneRegistry, DEFERRED_MICROPHONE_RELEASE


class AuxiliaryExitTests(unittest.TestCase):
    def setUp(self):
        app = self.app = TalkDatApp.__new__(TalkDatApp)
        app.config = {}
        app.lock = threading.RLock()
        app.session = None
        app.session_token = None
        app.safety_capture = None
        app.meeting = None
        app.control_server = None
        app.project_root = Path(".")
        app.stop_captions_stream = Mock()
        app.stop_microphone_check = Mock()
        app.release_activation_guards = Mock()
        app.remind_about_update = Mock()
        app.hotkeys = Mock()
        app.tray = Mock()
        app.overlay = SimpleNamespace(
            _ui_thread_id=threading.get_ident(),
            set_state=Mock(),
            root=SimpleNamespace(after=Mock(), destroy=Mock()),
            _tk_root=Mock(),
        )
        app.wake_listener = SimpleNamespace(closed=threading.Event(), stop=Mock())
        self.registry = MicrophoneRegistry()
        p = patch("knight_flow.app.microphone_registry", return_value=self.registry)
        p.start()
        self.addCleanup(p.stop)

    def test_quit_waits_for_wake_handle_close(self):
        with patch("knight_flow.app.save_config"):
            self.app.quit()
        self.app.wake_listener.stop.assert_called()
        self.assertTrue(self.app._quitting)
        self.assertEqual(self.app.overlay.root.after.call_args.args[0], 100)
        self.app.hotkeys.stop.assert_not_called()

    def test_restart_waits_for_wake_before_launching_replacement(self):
        with patch("subprocess.Popen") as launch, patch("os._exit") as leave:
            self.app.restart()
            launch.assert_not_called()
            leave.assert_not_called()
        self.app.wake_listener.stop.assert_called()
        self.assertEqual(self.app.overlay.root.after.call_args.args[0], 100)

    def test_registry_owner_blocks_exit_even_without_a_known_surface(self):
        self.app.wake_listener.closed.set()
        token = self.registry.acquire(
            "settings-meter", stop=lambda: DEFERRED_MICROPHONE_RELEASE
        )
        with patch("knight_flow.app.save_config"):
            self.app.quit()
        self.assertEqual(self.app.overlay.root.after.call_args.args[0], 100)
        self.app.hotkeys.stop.assert_not_called()
        self.registry.release(token)

    def test_close_timeout_keeps_app_available_for_panic_retry(self):
        self.app._meeting_quit_deadline = 0
        with patch("subprocess.Popen") as launch, patch("os._exit") as leave:
            self.app.restart()
            launch.assert_not_called()
            leave.assert_not_called()
        self.assertFalse(self.app._quitting)
        self.app.overlay.root.after.assert_not_called()
        self.assertIn("still closing", self.app.overlay.set_state.call_args.args[1])

    def test_closed_wake_allows_normal_shutdown(self):
        self.app.wake_listener.closed.set()
        with patch("knight_flow.app.save_config"):
            self.app.quit()
        self.app.hotkeys.stop.assert_called_once()
        self.assertEqual(self.app.overlay.root.after.call_args.args[0], 0)

    def test_failed_restart_launch_clears_quitting_flag(self):
        self.app.wake_listener.closed.set()
        with (
            patch("subprocess.Popen", side_effect=OSError("fixture unavailable")),
            patch("os._exit") as leave,
        ):
            self.app.restart()
            leave.assert_not_called()
        self.assertFalse(self.app._quitting)
