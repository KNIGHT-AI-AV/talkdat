"""T8 wiring: a long hold leaves checkpoints beside its audio, and Recovery
resumes from them. Synthetic audio, fake streams, a fake engine; no device.
"""
from __future__ import annotations

import math
import os
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from knight_flow import stt_sessions
from knight_flow.app import TalkDatApp
from knight_flow.audio_spool import read_safety_audio, safety_session, start_safety_capture
from knight_flow.stt_sessions import BatchSTTSession
from tests.test_app_session_lifecycle import _app
from tests.test_local_live import FakeStream, make_session

RATE = 16000


def tone(seconds: float, chunk_ms: int = 100) -> list[bytes]:
    per = RATE * chunk_ms // 1000
    samples = bytearray()
    for index in range(int(seconds * RATE)):
        samples += int(9000 * math.sin(2 * math.pi * 220 * index / RATE)).to_bytes(2, "little", signed=True)
    return [bytes(samples[i:i + 2 * per]) for i in range(0, len(samples), 2 * per)]


def quiet(seconds: float, chunk_ms: int = 100) -> list[bytes]:
    per = RATE * chunk_ms // 1000
    return [b"\x00\x00" * per for _ in range(int(seconds * 1000 / chunk_ms))]


class _Home(unittest.TestCase):
    def setUp(self) -> None:
        self._old = os.environ.get("TALK_DAT_HOME")
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["TALK_DAT_HOME"] = self._tmp.name

    def tearDown(self) -> None:
        if self._old is None:
            os.environ.pop("TALK_DAT_HOME", None)
        else:
            os.environ["TALK_DAT_HOME"] = self._old
        self._tmp.cleanup()


class TheCaptureKeepsCheckpoints(_Home):
    def test_checkpoints_are_written_beside_the_audio(self) -> None:
        capture = start_safety_capture(mode="dictation", control="hold", provider="local", model="")
        capture.append(b"\x10\x27" * 3200, RATE, 1, heard_voice=True)
        capture.add_checkpoint(0, 0, 6400, "the first part")
        capture.add_checkpoint(1, 6400, 9600, "secret words", keep_words=False)
        self.assertTrue(capture.flush())
        metadata = safety_session(capture.session_id)
        self.assertEqual([(c["index"], c["start"], c["end"], c["text"]) for c in metadata["checkpoints"]],
                         [(0, 0, 6400, "the first part"), (1, 6400, 9600, None)])
        capture.discard()

    def test_a_discarded_take_keeps_no_checkpoint(self) -> None:
        capture = start_safety_capture(mode="dictation", control="hold", provider="local", model="")
        capture.discard()
        capture.add_checkpoint(0, 0, 6400, "anything")
        self.assertIsNone(safety_session(capture.session_id))


class TheSessionReportsEachClosedSegment(unittest.TestCase):
    def test_checkpoints_are_contiguous_and_carry_the_segment_text(self) -> None:
        # The quiet lead-in is the room before the first word: the voice gate
        # learns its floor from the first chunks, so a take that opens on a
        # tone would hear that tone as the floor, not as speech.
        chunks = quiet(0.5) + tone(6.0) + quiet(1.2) + tone(6.0) + quiet(1.2) + tone(2.0)
        updates, done, checkpoints = [], [], []
        session = make_session({"stt": {"provider": "local", "local_live_captions": False}}, updates, done)
        session.on_checkpoint = lambda index, start, end, text: checkpoints.append((index, start, end, text))

        def open_stream(**kwargs):
            return FakeStream(kwargs["callback"], chunks, pace=0.005), RATE, 1, None

        def fake_local(self, wav_bytes: bytes, **_options) -> str:
            pcm = stt_sessions.pcm16_from_wav(wav_bytes)
            return f"words for {round(len(pcm) / (RATE * 2), 1)} seconds"

        with patch.object(stt_sessions, "open_raw_input_stream", open_stream), \
             patch.object(stt_sessions, "input_stream_active", lambda stream: True), \
             patch.object(BatchSTTSession, "_transcribe_local", fake_local), \
             patch("knight_flow.local_stt.gpu_available", lambda: False), \
             patch("knight_flow.local_stt.gpu_default", lambda extra: False):
            session.start()
            time.sleep(len(chunks) * 0.005 + 0.6)
            session.stop()
            session.join(timeout=8.0)
        self.assertGreaterEqual(len(checkpoints), 2, (checkpoints, done))
        checkpoints.sort()
        self.assertEqual(checkpoints[0][1], 0)
        for previous, current in zip(checkpoints, checkpoints[1:]):
            self.assertEqual(current[1], previous[2], "a gap or an overlap between checkpoints")
            self.assertEqual(current[0], previous[0] + 1)
        for _index, start, end, text in checkpoints:
            self.assertEqual(text, f"words for {round((end - start) / (RATE * 2), 1)} seconds")

    def test_a_failing_checkpoint_callback_never_breaks_the_take(self) -> None:
        chunks = quiet(0.5) + tone(6.0) + quiet(1.2) + tone(2.0)
        updates, done, called = [], [], []
        session = make_session({"stt": {"provider": "local", "local_live_captions": False}}, updates, done)

        def explode(*args):
            called.append(args)
            raise RuntimeError("disk full")

        session.on_checkpoint = explode

        def open_stream(**kwargs):
            return FakeStream(kwargs["callback"], chunks, pace=0.005), RATE, 1, None

        with patch.object(stt_sessions, "open_raw_input_stream", open_stream), \
             patch.object(stt_sessions, "input_stream_active", lambda stream: True), \
             patch.object(BatchSTTSession, "_transcribe_local", lambda self, wav, **_o: "some words"), \
             patch("knight_flow.local_stt.gpu_available", lambda: False), \
             patch("knight_flow.local_stt.gpu_default", lambda extra: False):
            session.start()
            time.sleep(len(chunks) * 0.005 + 0.6)
            session.stop()
            session.join(timeout=8.0)
        self.assertEqual(len(called), 1, "the callback must have run (and failed) for this to prove anything")
        self.assertTrue(done and not isinstance(done[0], tuple), done)


class _Probe:
    def __init__(self, secure: bool) -> None:
        self._secure = secure

    def secure_or_pending(self) -> bool:
        return self._secure


class _Capture:
    def __init__(self, probe) -> None:
        self.field_probe = probe
        self.calls: list = []

    def add_checkpoint(self, index, start, end, text, *, keep_words=True) -> None:
        self.calls.append((index, start, end, text, keep_words))


class TheAppKeepsWordsOnlyWhereItMay(unittest.TestCase):
    def app(self, *, save_history: bool, secure: bool):
        token = object()
        app = _app(token)
        app.config = {"privacy": {"save_history": save_history}}
        app.safety_capture = _Capture(_Probe(secure))
        app.safety_capture_token = token
        return app, token

    def test_words_are_kept_for_an_ordinary_field_with_history_on(self) -> None:
        app, token = self.app(save_history=True, secure=False)
        app.on_session_checkpoint(token, 0, 0, 100, "words")
        self.assertEqual(app.safety_capture.calls, [(0, 0, 100, "words", True)])

    def test_history_off_or_a_possible_password_keeps_the_range_only(self) -> None:
        for save_history, secure in ((False, False), (True, True), (False, True)):
            app, token = self.app(save_history=save_history, secure=secure)
            app.on_session_checkpoint(token, 0, 0, 100, "words")
            self.assertEqual(app.safety_capture.calls[0][4], False, (save_history, secure))

    def test_another_takes_checkpoint_is_ignored(self) -> None:
        app, _token = self.app(save_history=True, secure=False)
        app.on_session_checkpoint(object(), 0, 0, 100, "words")
        self.assertEqual(app.safety_capture.calls, [])


class RecoveryResumes(_Home):
    def test_only_the_audio_after_the_checkpoints_is_transcribed(self) -> None:
        capture = start_safety_capture(mode="dictation", control="hold", provider="local", model="")
        first, second = b"\x10\x27" * (RATE * 3), b"\x20\x27" * (RATE * 2)
        capture.append(first + second, RATE, 1, heard_voice=True)
        capture.add_checkpoint(0, 0, len(first), "the first three seconds")
        capture.finalize(status="interrupted")
        pcm16, rate, channels = read_safety_audio(capture.session_id)
        heard = []

        def transcribe(config, pcm, rate, channels):
            heard.append(len(pcm))
            return "and the last two"

        app = _app(object())
        with patch("knight_flow.app.transcribe_pcm", transcribe):
            text = TalkDatApp._recovered_transcript(app, capture.session_id, pcm16, rate, channels)
        self.assertEqual(heard, [len(second)])
        self.assertEqual(text, "the first three seconds and the last two")

    def recover(self, capture) -> list[tuple[str, str, str]]:
        """Recover a kept take through the app's own Recover action; the Pill's states, detail included."""
        states: list[tuple[str, str, str]] = []
        app = _app(object())
        app.config = {"privacy": {"save_history": False}}
        app.overlay = SimpleNamespace(
            set_state=lambda state, message="", detail="", **_kwargs: states.append((state, message, detail)),
            root=SimpleNamespace(after=lambda _delay, callback: callback()),
        )
        with (
            patch("knight_flow.app.transcribe_pcm", lambda *_args, **_kwargs: "and the last two"),
            patch("knight_flow.app.process_dictation", side_effect=lambda text, _config: SimpleNamespace(text=text)),
            patch("knight_flow.app.paste_text_with_receipt",
                  return_value=SimpleNamespace(success=True, method="copy_only")),
        ):
            app.recover_audio_session(capture.session_id)
            worker = next(t for t in threading.enumerate() if t.name == "TalkDatAudioRecovery")
            worker.join(5.0)
        self.assertFalse(worker.is_alive())
        return states

    def test_recover_says_how_much_the_checkpoints_kept(self) -> None:
        # B8, the owner's wording (cleaned 2026-10-22): the message names the kept part.
        capture = start_safety_capture(mode="dictation", control="hold", provider="local", model="")
        first, second = b"\x10\x27" * (RATE * 65), b"\x20\x27" * (RATE * 2)
        capture.append(first + second, RATE, 1, heard_voice=True)
        capture.add_checkpoint(0, 0, len(first), "the first minute")
        capture.finalize(status="interrupted")
        state, _message, detail = self.recover(capture)[-1]
        self.assertEqual(state, "captured")
        self.assertEqual(detail, "1:05 was kept from before it stopped; the rest was transcribed again.")

    def test_a_take_without_checkpoints_still_shows_its_words(self) -> None:
        capture = start_safety_capture(mode="dictation", control="hold", provider="local", model="")
        capture.append(b"\x10\x27" * (RATE * 2), RATE, 1, heard_voice=True)
        capture.finalize(status="interrupted")
        state, _message, detail = self.recover(capture)[-1]
        self.assertEqual((state, detail), ("captured", "and the last two"))

    def test_the_kept_time_reads_as_minutes_and_seconds(self) -> None:
        line = " was kept from before it stopped; the rest was transcribed again."
        self.assertEqual(TalkDatApp._kept_line(3.0), "0:03" + line)
        self.assertEqual(TalkDatApp._kept_line(125.4), "2:05" + line)
        self.assertEqual(TalkDatApp._kept_line(3600.0), "60:00" + line)

    def test_no_checkpoint_transcribes_the_whole_take(self) -> None:
        capture = start_safety_capture(mode="dictation", control="hold", provider="local", model="")
        capture.append(b"\x10\x27" * (RATE * 2), RATE, 1, heard_voice=True)
        capture.finalize(status="interrupted")
        pcm16, rate, channels = read_safety_audio(capture.session_id)
        heard = []
        app = _app(object())
        with patch("knight_flow.app.transcribe_pcm", lambda c, p, r, ch: heard.append(len(p)) or "all of it"):
            self.assertEqual(TalkDatApp._recovered_transcript(app, capture.session_id, pcm16, rate, channels),
                             "all of it")
        self.assertEqual(heard, [len(pcm16)])


if __name__ == "__main__":
    unittest.main()
