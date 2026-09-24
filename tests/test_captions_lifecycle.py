"""Real app entrypoint, synthetic audio: no owner microphone or window."""
import queue
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from knight_flow.app import TalkDatApp
from knight_flow.mic_registry import MicrophoneRegistry, CAPTIONS


class CaptionsLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.ui = queue.Queue()
        self.registry = MicrophoneRegistry()
        self.opened = threading.Event()
        self.closed = threading.Event()
        self.closing = threading.Event()
        self.release_close = threading.Event()
        self.release_close.set()
        self.open_attempt = threading.Event()
        self.release_open = threading.Event()
        self.release_open.set()
        self.preparing = threading.Event()
        self.release_prepare = threading.Event()
        self.release_prepare.set()
        self.prepare_failure = False
        self.decoding = threading.Event()
        self.decoded = threading.Event()
        self.release_decode = threading.Event()
        self.release_decode.set()
        self.frames = []
        self.received = []
        self.states = []
        self.widget_threads = []
        self.open_count = 0
        self.enter_count = 0
        self.decode_failure = False
        self.close_failures = 0
        self.rate = 16000
        self.channels = 1
        self.open_failure = False
        self.app = TalkDatApp.__new__(TalkDatApp)
        self.app.config = {"audio": {"input_device": "fixture"}}
        self.app._cross_thread_calls = self.ui
        self.app.overlay = SimpleNamespace(
            root=SimpleNamespace(after=lambda _delay, fn: (self.widget_threads.append(threading.get_ident()), self.ui.put(fn))),
            captions_update=lambda text, final: self.received.append((text, final)),
            captions_stream_state=lambda phase, detail="": None,
            set_state=lambda *args: self.states.append(args),
            _ui_thread_id=threading.get_ident(),
        )
        test = self

        class Stream:
            def __enter__(self):
                test.enter_count += 1
                test.opened.set()
                return self

            def __exit__(self, *_args):
                self.close()

            def close(self):
                test.closing.set()
                test.release_close.wait(3)
                if test.close_failures:
                    test.close_failures -= 1
                    raise OSError("synthetic close failure")
                test.closed.set()

        def open_stream(**kw):
            self.open_count += 1
            self.open_attempt.set()
            self.release_open.wait(3)
            if self.open_failure:
                self.opened.set()
                raise OSError("synthetic input unavailable")
            self.audio = kw["callback"]
            return Stream(), self.rate, self.channels, 7

        def decode(_config, pcm, rate, channels, **kw):
            self.decoding.set()
            self.frames.append((len(pcm), rate, channels, kw.get("provider_id")))
            self.release_decode.wait(3)
            if self.decode_failure:
                raise RuntimeError("synthetic model failure")
            self.decoded.set()
            return "Caption fixture."

        def prepare(_config):
            self.preparing.set()
            self.release_prepare.wait(3)
            if self.prepare_failure:
                raise RuntimeError("synthetic preparation failure")

        for target, value in (
            ("knight_flow.caption_stream.prepare_local_captions", prepare),
            ("knight_flow.app.microphone_registry", lambda: self.registry),
            ("knight_flow.mic_registry.microphone_registry", lambda: self.registry),
            ("knight_flow.audio_input.resolve_input_device", lambda _setting: 7),
            ("knight_flow.audio_input.open_raw_input_stream", open_stream),
            ("knight_flow.stt_sessions.transcribe_pcm", decode),
        ):
            mock = patch(target, value)
            mock.start()
            self.addCleanup(mock.stop)

    def pump(self):
        while True:
            try:
                fn = self.ui.get_nowait()
            except queue.Empty:
                break
            fn()

    def until(self, predicate, timeout=2):
        end = time.monotonic() + timeout
        while not predicate() and time.monotonic() < end:
            self.pump()
            time.sleep(.005)
        self.pump()
        return predicate()

    def tearDown(self):
        self.release_prepare.set()
        self.release_open.set()
        self.release_close.set()
        self.close_failures = 0
        engine = getattr(self.app, "_captions_engine", None)
        if engine is not None:
            if isinstance(engine, dict):
                engine["stop"].set()
            else:
                engine.stop()
        self.release_decode.set()
        self.closed.wait(.3)
        self.until(lambda: getattr(self.app, "_captions_engine", None) is None, .2)

    def start(self):
        self.app.start_captions_stream()
        self.assertTrue(self.opened.wait(2))
        self.pump()

    def send_audio(self):
        pcm = b"\x00\x01" * int(self.rate * self.channels * 1.8)
        self.audio(pcm, len(pcm) // (2 * self.channels), None, None)
        self.assertTrue(self.decoding.wait(2))

    def test_live_capture_is_disclosed_to_panic_stop(self):
        self.start()
        self.assertIn(CAPTIONS, self.registry.names())
        self.registry.stop_all()
        self.assertTrue(self.closed.wait(2))
        self.assertTrue(self.until(lambda: not self.registry.is_active()))

    def test_decoder_receives_the_actual_negotiated_audio_format(self):
        self.rate, self.channels = 48000, 2
        self.start()
        self.send_audio()
        self.assertEqual(self.frames[0], (345600, 48000, 2, "local"))

    def test_a_caption_already_scheduled_on_the_ui_is_ignored_after_stop(self):
        self.start()
        self.send_audio()
        self.assertTrue(self.decoded.wait(2))
        end = time.monotonic() + 2
        while self.ui.empty() and time.monotonic() < end:
            time.sleep(.005)
        self.app.start_captions_stream()
        self.pump()
        self.assertEqual(self.received, [])

    def test_a_microphone_open_failure_resets_the_engine(self):
        self.open_failure = True
        self.start()
        self.assertTrue(self.until(lambda: getattr(self.app, "_captions_engine", None) is None))
        self.assertTrue(any(row[0] == "error" for row in self.states))

    def test_stop_rejects_an_inflight_result_and_discards_backlog(self):
        self.release_decode.clear()
        self.start()
        engine = self.app._captions_engine
        self.send_audio()
        self.send_audio()
        self.app.stop_captions_stream()
        self.release_decode.set()
        self.assertTrue(self.until(lambda: self.app._captions_engine is None))
        self.assertEqual(len(self.frames), 1)
        self.assertEqual(self.received, [])
        self.assertTrue(engine.chunks.empty())

    def test_a_slow_model_gets_a_visible_stop_instead_of_unbounded_audio(self):
        self.release_decode.clear()
        self.start()
        engine = self.app._captions_engine
        self.send_audio()
        for _ in range(4):
            self.send_audio()
        self.assertLessEqual(engine.chunks.qsize(), 2)
        self.assertTrue(self.closed.wait(2))
        self.release_decode.set()
        self.assertTrue(self.until(lambda: self.app._captions_engine is None))
        self.assertTrue(any("could not keep up" in str(row) for row in self.states))
        self.assertEqual(len(self.frames), 1)

    def test_owner_remains_visible_until_the_driver_actually_closes(self):
        self.release_close.clear()
        self.start()
        self.registry.stop_all()
        self.assertTrue(self.closing.wait(2))
        self.assertEqual(self.registry.names(), (CAPTIONS,))
        self.assertEqual(self.registry.owners()[0].phase, "closing")
        self.release_close.set()
        self.assertTrue(self.until(lambda: not self.registry.is_active()))

    def test_stop_during_open_does_not_start_the_returned_stream(self):
        self.release_open.clear()
        self.app.start_captions_stream()
        self.assertTrue(self.open_attempt.wait(2))
        self.app.stop_captions_stream()
        self.release_open.set()
        self.assertTrue(self.closed.wait(2))
        self.assertTrue(self.until(lambda: self.app._captions_engine is None))
        self.assertEqual(self.enter_count, 0)
        self.assertFalse(self.registry.is_active())

    def test_cold_model_preparation_keeps_the_microphone_closed_and_can_cancel(self):
        self.release_prepare.clear()
        self.app.start_captions_stream()
        self.assertTrue(self.preparing.wait(2))
        self.assertEqual(self.open_count, 0)
        self.assertFalse(self.registry.is_active())
        self.app.stop_captions_stream()
        self.release_prepare.set()
        self.assertTrue(self.until(lambda: self.app._captions_engine is None))
        self.assertEqual(self.open_count, 0)

    def test_model_preparation_failure_never_opens_the_microphone(self):
        self.prepare_failure = True
        self.app.start_captions_stream()
        self.assertTrue(self.until(lambda: self.app._captions_engine is None))
        self.assertEqual(self.open_count, 0)
        self.assertFalse(self.registry.is_active())
        self.assertTrue(any("could not prepare" in str(row) for row in self.states))

    def test_panic_during_cold_preparation_prevents_a_late_microphone_open(self):
        self.release_prepare.clear()
        self.app.cancel = lambda: None
        self.app.start_captions_stream()
        self.assertTrue(self.preparing.wait(2))
        self.app.panic_stop()
        self.release_prepare.set()
        self.assertTrue(self.until(lambda: self.app._captions_engine is None))
        self.assertEqual(self.open_count, 0)

    def test_no_second_model_worker_opens_until_the_previous_one_retires(self):
        self.release_decode.clear()
        self.start()
        engine = self.app._captions_engine
        self.send_audio()
        self.app.stop_captions_stream()
        self.app.start_captions_stream()
        self.assertIs(self.app._captions_engine, engine)
        self.assertEqual(self.open_count, 1)
        self.release_decode.set()
        self.assertTrue(self.until(lambda: self.app._captions_engine is None))
        self.app.start_captions_stream()
        self.assertTrue(self.until(lambda: self.open_count == 2))

    def test_explicit_stop_on_an_idle_window_does_not_start_capture(self):
        self.app.stop_captions_stream()
        self.assertEqual(self.open_count, 0)

    def test_model_failure_closes_capture_and_reports_the_error(self):
        self.decode_failure = True
        self.start()
        self.send_audio()
        self.assertTrue(self.closed.wait(2))
        self.assertTrue(self.until(lambda: self.app._captions_engine is None))
        self.assertTrue(any("could not transcribe" in str(row) for row in self.states))

    def test_workers_never_enter_tk_to_schedule_a_caption(self):
        self.start()
        self.send_audio()
        self.assertTrue(self.until(lambda: bool(self.received)))
        self.assertEqual(self.widget_threads, [])

    def test_caption_completion_preserves_an_active_dictation_pill(self):
        self.start()
        self.app.session_token = "new-dictation"
        self.states.clear()
        self.app.stop_captions_stream()
        self.assertTrue(self.until(lambda: self.app._captions_engine is None))
        self.assertEqual(self.states, [])

    def test_retired_engine_callbacks_do_not_change_a_new_caption_session(self):
        self.start()
        old = self.app._captions_engine
        self.app.stop_captions_stream()
        self.assertTrue(self.until(lambda: self.app._captions_engine is None))
        self.app.start_captions_stream()
        current = self.app._captions_engine
        self.app._on_caption_text(old, "old text")
        self.app._on_caption_state(old, "stopped", "")
        self.assertIs(self.app._captions_engine, current)
        self.assertEqual(self.received, [])

    def test_settings_changes_do_not_reconfigure_an_active_caption_stream(self):
        self.start()
        engine = self.app._captions_engine
        self.app.config["audio"]["input_device"] = "different microphone"
        self.assertEqual(engine.config["audio"]["input_device"], "fixture")

    def test_driver_close_failure_stays_disclosed_and_panic_can_retry(self):
        self.close_failures = 2
        self.start()
        engine = self.app._captions_engine
        self.app.stop_captions_stream()
        self.assertTrue(self.until(lambda: engine.capture_done.is_set()))
        self.assertEqual(self.registry.names(), (CAPTIONS,))
        self.assertEqual(self.registry.owners()[0].phase, "stop-failed")
        self.assertFalse(engine.finished.is_set())
        self.registry.stop_all()
        self.assertTrue(self.until(lambda: self.app._captions_engine is None))
        self.assertFalse(self.registry.is_active())

    def test_audio_callback_overflow_is_reported_instead_of_hiding_missing_words(self):
        self.start()
        self.audio(b"\x00\x01" * 128, 128, None, "input overflow")
        self.assertTrue(self.until(lambda: self.app._captions_engine is None))
        self.assertTrue(any("audio was interrupted" in str(row) for row in self.states))


class LocalCaptionPreparationTests(unittest.TestCase):
    def test_preparation_discards_silence_and_forces_the_local_route(self):
        from knight_flow.caption_stream import prepare_local_captions
        config = {"stt": {"provider": "deepgram"}}
        with patch("knight_flow.local_stt.is_downloaded", return_value=True), \
             patch("knight_flow.stt_sessions.transcribe_pcm", return_value="discard this") as decode:
            self.assertIsNone(prepare_local_captions(config))
        args, kwargs = decode.call_args
        self.assertIs(args[0], config)
        self.assertEqual(args[1], bytes(57600))
        self.assertEqual(args[2:], (16000, 1))
        self.assertEqual(kwargs, {"provider_id": "local"})
        self.assertEqual(config["stt"]["provider"], "deepgram")

    def test_missing_model_does_not_download_or_transcribe(self):
        from knight_flow.caption_stream import prepare_local_captions
        with patch("knight_flow.local_stt.is_downloaded", return_value=False), \
             patch("knight_flow.stt_sessions.transcribe_pcm") as decode:
            with self.assertRaisesRegex(RuntimeError, "Prepare a local speech model"):
                prepare_local_captions({})
        decode.assert_not_called()


if __name__ == "__main__":
    unittest.main()
