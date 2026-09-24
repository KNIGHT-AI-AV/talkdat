import copy, queue, threading, unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from knight_flow.mic_registry import MicrophoneRegistry
from knight_flow.wake_runtime import WakeRuntime


class WakeRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.app = SimpleNamespace(
            config={
                "wake_word": {"enabled": True, "model": "hey_jarvis"},
                "audio": {"input_device": "USB"},
            },
            paused=False,
            session=None,
            session_token=None,
            wake_listener=None,
            _cross_thread_calls=queue.Queue(),
            toggle_hands_free=Mock(),
            overlay=SimpleNamespace(
                set_state=Mock(),
                root=SimpleNamespace(
                    after=Mock(return_value="timer"), after_cancel=Mock()
                ),
            ),
        )
        self.listeners = []
        test = self

        class Listener:
            def __init__(self, config, **callbacks):
                self.config = copy.deepcopy(config)
                self.callbacks = callbacks
                self.running = False
                self.failed = False
                self.closed = threading.Event()
                self.closed.set()
                self.generation = 0
                self.phase = "idle"
                self.message = ""
                self._token = None
                self._decoder = None
                self.starts = 0
                self.stops = 0
                test.listeners.append(self)

            def start(self):
                self.running = True
                self.generation += 1
                self.starts += 1
                self.closed.clear()
                self.phase = "listening"

            def stop(self):
                self.stops += 1
                self.running = False
                self.closed.set()
                self.phase = "stopped"

        self.registry = MicrophoneRegistry()
        for target, value in [
            ("knight_flow.wake_runtime.WakeWordListener", Listener),
            ("knight_flow.mic_registry.microphone_registry", lambda: self.registry),
        ]:
            item = patch(target, value)
            item.start()
            self.addCleanup(item.stop)
        self.runtime = WakeRuntime(self.app)

    def drain(self):
        while not self.app._cross_thread_calls.empty():
            self.app._cross_thread_calls.get_nowait()()

    def test_disabled_and_nonboolean_setting_never_start_listener(self):
        for value in (False, "true", 1):
            self.app.config["wake_word"]["enabled"] = value
            self.runtime.refresh()
        self.assertEqual(self.listeners, [])

    def test_panic_does_not_silently_restart_on_next_poll_or_unrelated_save(self):
        self.runtime.refresh()
        listener = self.listeners[0]
        self.runtime.suspend()
        self.runtime.refresh()
        self.runtime.refresh(retry=True)
        self.assertEqual(listener.starts, 1)
        self.assertTrue(listener.closed.is_set())
        self.app.config["wake_word"]["enabled"] = False
        self.runtime.refresh()
        self.app.config["wake_word"]["enabled"] = True
        self.runtime.refresh()
        self.assertEqual(listener.starts, 2)

    def test_active_dictation_prevents_listening_and_idle_resumes(self):
        self.app.session = object()
        self.runtime.refresh()
        self.assertEqual(self.listeners, [])
        self.app.session = None
        self.runtime.refresh()
        self.assertEqual(self.listeners[0].starts, 1)
        self.app.session = object()
        self.runtime.refresh()
        self.assertTrue(self.listeners[0].closed.is_set())

    def test_foreign_registered_input_stops_listener(self):
        self.runtime.refresh()
        token = self.registry.acquire("microphone-check")
        self.runtime.refresh()
        self.assertTrue(self.listeners[0].closed.is_set())
        self.registry.release(token)

    def test_own_microphone_does_not_suspend_itself(self):
        self.runtime.refresh()
        listener = self.listeners[0]
        listener._token = self.registry.acquire("wake-word")
        self.runtime.refresh()
        self.assertEqual(listener.stops, 0)

    def test_model_failure_is_not_retried_on_every_poll(self):
        self.runtime.refresh()
        listener = self.listeners[0]
        listener.running = False
        listener.closed.set()
        listener.failed = True
        for _ in range(5):
            self.runtime.refresh()
        self.assertEqual(listener.starts, 1)
        self.runtime.refresh(retry=True)
        self.assertEqual(listener.starts, 2)

    def test_changed_input_waits_for_the_old_handle(self):
        self.runtime.refresh()
        listener = self.listeners[0]
        listener.stop = lambda: None
        self.app.config["audio"]["input_device"] = "Second USB"
        self.runtime.refresh()
        self.assertEqual(len(self.listeners), 1)
        listener.running = False
        listener.closed.set()
        self.runtime.refresh()
        self.assertEqual(len(self.listeners), 2)
        self.assertEqual(
            self.listeners[1].config["audio"]["input_device"], "Second USB"
        )

    def test_late_status_from_previous_generation_is_ignored(self):
        self.runtime.refresh()
        listener = self.listeners[0]
        listener.phase = "listening"
        listener.message = "Listening"
        listener.callbacks["on_status"]("Listening")
        listener.generation += 1
        self.drain()
        self.app.overlay.set_state.assert_not_called()

    def test_one_detection_starts_at_most_one_dictation(self):
        self.runtime.refresh()
        listener = self.listeners[0]
        listener.running = False
        listener.closed.set()
        listener.phase = "detected"
        listener.callbacks["on_wake"]()
        listener.callbacks["on_wake"]()
        self.drain()
        self.app.toggle_hands_free.assert_called_once()

    def test_stop_cancels_poll_and_does_not_schedule_after_quit(self):
        self.runtime.refresh()
        self.runtime.stop()
        self.app.overlay.root.after_cancel.assert_called_once_with("timer")
        before = self.app.overlay.root.after.call_count
        self.app._quitting = True
        self.runtime.refresh()
        self.assertEqual(self.app.overlay.root.after.call_count, before)
