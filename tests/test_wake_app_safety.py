import queue, threading, unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from knight_flow.app import TalkDatApp
from knight_flow.mic_registry import MicrophoneRegistry


class WakeAppSafetyTests(unittest.TestCase):
    def setUp(self):
        self.app = TalkDatApp.__new__(TalkDatApp)
        self.app.config = {"wake_word": {"enabled": True}}
        self.app.session = None
        self.app.session_token = None
        self.app.paused = False
        self.app.wake_listener = None
        self.app.lock = threading.RLock()
        self.app._cross_thread_calls = queue.Queue()
        self.app.cancel = Mock()
        self.app.toggle_hands_free = Mock()
        self.app.tray = Mock()
        self.app.stop_captions_stream = Mock()
        self.app.stop_microphone_check = Mock()
        self.tasks = []
        main = threading.get_ident()

        def after(ms, fn):
            if threading.get_ident() != main:
                raise AssertionError("Worker entered Tk")
            self.tasks.append((ms, fn))
            return "timer"

        self.app.overlay = SimpleNamespace(
            _ui_thread_id=main,
            set_state=Mock(),
            root=SimpleNamespace(after=after, after_cancel=Mock()),
        )
        self.listener = SimpleNamespace(
            running=False,
            closed=threading.Event(),
            failed=False,
            phase="idle",
            message="",
            generation=1,
            stop=Mock(),
            start=Mock(),
            _decoder=None,
        )
        self.listener.closed.set()

        def factory(config, **callbacks):
            self.callbacks = callbacks
            return self.listener

        self.factory = Mock(side_effect=factory)
        self.patch = patch("knight_flow.app.WakeWordListener", self.factory)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        try:
            import knight_flow.wake_runtime

            p = patch("knight_flow.wake_runtime.WakeWordListener", self.factory)
            p.start()
            self.addCleanup(p.stop)
        except ImportError:
            pass
        p = patch(
            "knight_flow.app.microphone_registry", return_value=MicrophoneRegistry()
        )
        p.start()
        self.addCleanup(p.stop)
        p = patch(
            "knight_flow.mic_registry.microphone_registry",
            return_value=MicrophoneRegistry(),
        )
        p.start()
        self.addCleanup(p.stop)

    def test_panic_stops_even_a_listener_preparing_its_model(self):
        self.app.wake_listener = self.listener
        self.app.panic_stop()
        self.listener.stop.assert_called()

    def test_pause_stops_wake_listening(self):
        self.app.wake_listener = self.listener
        self.app.toggle_pause()
        self.listener.stop.assert_called()

    def test_quitting_cannot_start_another_listener(self):
        self.app._quitting = True
        self.app.refresh_wake_word()
        self.factory.assert_not_called()

    def test_wake_status_never_calls_tk_from_worker(self):
        self.app.refresh_wake_word()
        errors = []
        self.listener.phase = "listening"
        self.listener.message = "Listening"

        def status():
            try:
                self.callbacks["on_status"]("Listening")
            except Exception as error:
                errors.append(str(error))

        worker = threading.Thread(target=status)
        worker.start()
        worker.join(1)
        self.assertEqual(errors, [])
        self.assertFalse(self.app._cross_thread_calls.empty())

    def test_wake_cannot_toggle_an_existing_dictation(self):
        self.app.refresh_wake_word()
        self.app.session = object()
        self.listener.phase = "detected"
        self.callbacks["on_wake"]()
        while not self.app._cross_thread_calls.empty():
            self.app._cross_thread_calls.get_nowait()()
        self.app.toggle_hands_free.assert_not_called()

    def test_old_status_cannot_repaint_replacement_listener(self):
        self.app.refresh_wake_word()
        self.app.wake_listener = object()
        self.listener.message = "Old status"
        self.callbacks["on_status"]("Old status")
        while not self.app._cross_thread_calls.empty():
            self.app._cross_thread_calls.get_nowait()()
        for delay, task in self.tasks:
            if delay == 0:
                task()
        self.app.overlay.set_state.assert_not_called()
