import queue, threading, unittest
from types import SimpleNamespace
from unittest.mock import Mock
from knight_flow.app import TalkDatApp
from knight_flow.wake_runtime import WakeRuntime


class WakeCaptureControlsTests(unittest.TestCase):
    def setUp(self):
        app = self.app = TalkDatApp.__new__(TalkDatApp)
        app.config = {"wake_word": {"enabled": True}}
        app.paused = False
        app.session = None
        app.session_token = None
        app.lock = threading.RLock()
        app._released_processing = False
        app._trigger_released_at = None
        app._cross_thread_calls = queue.Queue()
        main = threading.get_ident()
        self.tasks = []

        def after(delay, fn):
            self.assertEqual(threading.get_ident(), main)
            self.tasks.append((delay, fn))
            return "timer"

        app.overlay = SimpleNamespace(
            _ui_thread_id=main,
            set_state=Mock(),
            root=SimpleNamespace(after=after, after_cancel=Mock()),
        )
        app.wake_listener = SimpleNamespace(closed=threading.Event(), stop=Mock())
        app._wake_runtime = WakeRuntime(app)

    def test_press_then_release_cancels_pending_capture(self):
        self.app.start_session("dictation", "Hold", control="hold")
        self.assertIsNotNone(self.app._wake_runtime.capture_pending)
        self.app.stop_session()
        self.assertIsNone(self.app._wake_runtime.capture_pending)
        self.app.wake_listener.closed.set()
        for _, fn in self.tasks:
            fn()
        self.assertIsNone(self.app.session)

    def test_hotkey_worker_queues_press_and_release_in_order_without_entering_tk(self):
        errors = []

        def press_release():
            try:
                self.app.start_session("dictation", "Hold", control="hold")
                self.app.stop_session()
            except Exception as error:
                errors.append(str(error))

        worker = threading.Thread(target=press_release)
        worker.start()
        worker.join(1)
        self.assertEqual(errors, [])
        self.assertEqual(self.tasks, [])
        self.assertEqual(self.app._cross_thread_calls.qsize(), 2)
        while not self.app._cross_thread_calls.empty():
            self.app._cross_thread_calls.get_nowait()()
        self.assertIsNone(self.app._wake_runtime.capture_pending)
        self.assertIsNone(self.app.session)

    def test_second_hands_free_click_cancels_pending_start(self):
        self.app.start_session("dictation", "Hands free", control="hands_free")
        self.app.toggle_hands_free()
        self.assertIsNone(self.app._wake_runtime.capture_pending)
        self.assertIsNone(self.app.session)
