import contextlib, sys, threading, time, types, unittest
import numpy as np
from unittest.mock import Mock, patch
from knight_flow.wake import WakeWordListener
from knight_flow.mic_registry import MicrophoneRegistry


@contextlib.contextmanager
def modules(values):
    absent = object()
    previous = {name: sys.modules.get(name, absent) for name in values}
    sys.modules.update(values)
    try:
        yield
    finally:
        for name, value in previous.items():
            if value is absent:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = value


class WakeSafetyTests(unittest.TestCase):
    def setUp(self):
        self.streams = []
        self.status = []
        self.fired = []
        self.opened = threading.Event()
        self.closed = threading.Event()
        self.registry = MicrophoneRegistry()
        self.model = Mock()
        self.model.predict.return_value = {"hey_jarvis": 0}
        self.factory = Mock(return_value=self.model)
        self.download = Mock()
        self.fail_close = False
        self.release = threading.Event()
        self.release.set()
        test = self

        class Stream:
            def __init__(self, **kwargs):
                self.kwargs = kwargs
                self.active = False
                test.streams.append(self)

            def start(self):
                self.active = True
                test.opened.set()

            def stop(self):
                self.active = False

            def close(self):
                if test.fail_close:
                    raise OSError("device closing")
                test.closed.set()

            def __enter__(self):
                self.start()
                return self

            def __exit__(self, *args):
                self.stop()
                self.close()

        sd = types.ModuleType("sounddevice")
        sd.RawInputStream = Stream
        sd.CallbackStop = type("CallbackStop", (Exception,), {})
        sd.CallbackAbort = type("CallbackAbort", (Exception,), {})
        oww = types.ModuleType("openwakeword")
        oww.__path__ = []
        model = types.ModuleType("openwakeword.model")
        model.Model = self.factory
        utils = types.ModuleType("openwakeword.utils")
        utils.download_models = self.download
        oww.utils = utils
        oww.model = model
        self.stack = contextlib.ExitStack()
        self.stack.enter_context(
            modules(
                {
                    "sounddevice": sd,
                    "openwakeword": oww,
                    "openwakeword.model": model,
                    "openwakeword.utils": utils,
                }
            )
        )
        self.stack.enter_context(
            patch(
                "knight_flow.mic_registry.microphone_registry",
                return_value=self.registry,
            )
        )
        self.stack.enter_context(
            patch("knight_flow.audio_input.resolve_input_device", return_value=7)
        )
        self.listener = WakeWordListener(
            {
                "audio": {"input_device": "USB Studio"},
                "wake_word": {
                    "enabled": True,
                    "model": "hey_jarvis",
                    "threshold": 0.55,
                },
            },
            on_wake=self.wake,
            on_status=self.status.append,
        )
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.release.set()
        self.fail_close = False
        self.listener.stop()
        if self.listener._thread:
            self.listener._thread.join(2)
        self.stack.close()

    def wake(self):
        self.fired.append(self.closed.is_set())
        self.listener.stop()

    def start(self):
        self.listener.start()
        self.assertTrue(self.opened.wait(1), "Wake input did not open")

    def block(self):
        self.release.clear()

        def predict(audio):
            self.release.wait(2)
            return {"hey_jarvis": 0}

        self.model.predict.side_effect = predict

    def test_callback_never_waits_for_model_inference(self):
        self.block()
        self.start()
        done = threading.Event()

        def capture():
            try:
                self.streams[0].kwargs["callback"](b"\0\1" * 1280, 1280, None, None)
            finally:
                done.set()

        worker = threading.Thread(target=capture)
        worker.start()
        try:
            self.assertTrue(
                done.wait(0.2), "Audio callback blocked inside wake recognition"
            )
        finally:
            self.release.set()
            worker.join(2)

    def test_selected_microphone_is_explicit(self):
        self.start()
        self.assertEqual(self.streams[0].kwargs.get("device"), 7)

    def test_listener_is_registered_until_actual_close(self):
        self.start()
        self.assertIn("wake-word", self.registry.names())
        self.listener.stop()
        self.assertTrue(self.closed.wait(1))
        self.listener._thread.join(1)
        self.assertNotIn("wake-word", self.registry.names())

    def test_stop_during_model_preparation_never_opens_microphone(self):
        entered = threading.Event()
        self.release.clear()

        def model(**kwargs):
            entered.set()
            self.release.wait(2)
            return self.model

        self.factory.side_effect = model
        self.listener.start()
        self.assertTrue(entered.wait(1))
        self.listener.stop()
        self.release.set()
        self.listener._thread.join(2)
        self.assertFalse(
            self.streams, "Stopped preparation opened a microphone afterwards"
        )

    def test_model_failure_never_downloads_implicitly(self):
        self.factory.side_effect = OSError("missing model")
        self.listener.start()
        self.listener._thread.join(2)
        self.download.assert_not_called()
        self.assertFalse(self.streams)

    def test_invalid_threshold_fails_before_audio(self):
        self.listener.config["wake_word"]["threshold"] = float("nan")
        self.listener.start()
        self.opened.wait(0.3)
        self.listener.stop()
        self.listener._thread.join(1)
        self.assertFalse(
            self.streams, "An invalid threshold still opened the microphone"
        )

    def test_wake_handoff_waits_for_input_close(self):
        self.model.predict.return_value = {"hey_jarvis": 0.9}
        self.start()
        self.streams[0].kwargs["callback"](b"\0\1" * 1280, 1280, None, None)
        until = time.monotonic() + 1
        while not self.fired and time.monotonic() < until:
            time.sleep(0.01)
        self.assertEqual(
            self.fired, [True], "Wake fired before its microphone was closed"
        )

    def test_panic_retains_failed_close_owner_for_retry(self):
        self.start()
        self.fail_close = True
        self.registry.stop_all()
        self.listener.stop()
        self.listener._thread.join(1)
        self.assertIn(
            "wake-word",
            self.registry.names(),
            "Failed close disappeared from microphone ownership",
        )

    def test_audio_driver_status_stops_instead_of_recognizing_corrupt_frames(self):
        self.start()
        try:
            self.streams[0].kwargs["callback"](b"\0\1" * 1280, 1280, None, object())
        except Exception:
            pass
        self.assertTrue(self.closed.wait(0.4), "Driver overflow was silently ignored")
        self.model.predict.assert_not_called()

    def test_panic_closes_audio_while_prediction_is_blocked(self):
        entered = threading.Event()
        self.release.clear()

        def predict(audio):
            entered.set()
            self.release.wait(2)
            return {"hey_jarvis": 0.9}

        self.model.predict.side_effect = predict
        self.start()
        self.streams[0].kwargs["callback"](b"\0\1" * 1280, 1280, None, None)
        self.assertTrue(entered.wait(1))
        self.registry.stop_all()
        self.assertTrue(self.closed.wait(0.3))
        self.assertEqual(self.fired, [])

    def test_queue_overflow_stops_capture_without_unbounded_audio(self):
        entered = threading.Event()
        self.release.clear()

        def predict(audio):
            entered.set()
            self.release.wait(2)
            return {"hey_jarvis": 0}

        self.model.predict.side_effect = predict
        self.start()
        callback = self.streams[0].kwargs["callback"]
        callback(b"\0\1" * 1280, 1280, None, None)
        self.assertTrue(entered.wait(1))
        for _ in range(100):
            callback(b"\0\1" * 1280, 1280, None, None)
        self.assertTrue(self.closed.wait(0.4))
        self.assertLessEqual(self.listener._pending.qsize(), 8)
        self.assertTrue(self.listener.failed)

    def test_unavailable_selected_device_never_falls_back_to_default(self):
        with patch("knight_flow.audio_input.resolve_input_device", return_value=None):
            self.listener.start()
            self.listener._thread.join(1)
        self.assertFalse(self.streams)
        self.assertIn("selected microphone", self.listener.message)

    def test_failed_close_can_be_retried_without_reopening_input(self):
        self.start()
        self.fail_close = True
        self.listener.stop()
        self.listener._thread.join(1)
        self.assertIn("wake-word", self.registry.names())
        self.fail_close = False
        self.registry.stop_all()
        self.assertTrue(self.closed.wait(1))
        until = time.monotonic() + 1
        while self.registry.is_active() and time.monotonic() < until:
            time.sleep(0.01)
        self.assertFalse(self.registry.is_active())
        self.assertEqual(len(self.streams), 1)

    def test_malformed_large_callback_block_is_refused(self):
        self.start()
        self.streams[0].kwargs["callback"](bytes(65538), 32769, None, None)
        self.assertTrue(self.closed.wait(0.3))
        self.model.predict.assert_not_called()

    def test_selected_device_rate_fallback_is_resampled_into_80ms_frames(self):
        import sounddevice as sd

        original = sd.RawInputStream

        def create(**kwargs):
            if kwargs["samplerate"] == 16000:
                raise ValueError("Unsupported rate")
            return original(**kwargs)

        with patch.object(sd, "RawInputStream", create):
            self.start()
        self.assertEqual(self.listener.sample_rate, 48000)
        callback = self.streams[0].kwargs["callback"]
        for _ in range(4):
            callback(b"\0\1" * 1280, 1280, None, None)
        until = time.monotonic() + 1
        while not self.model.predict.called and time.monotonic() < until:
            time.sleep(0.01)
        self.assertTrue(self.model.predict.called)
        self.assertTrue(
            all(len(call.args[0]) == 1280 for call in self.model.predict.call_args_list)
        )


if __name__ == "__main__":
    unittest.main()
