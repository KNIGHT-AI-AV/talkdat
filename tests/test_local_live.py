"""Local live captions: growing words while the trigger is held (X-416)."""
from __future__ import annotations

import ast
import pathlib
import socket
import threading
import time
import unittest

from knight_flow.config import DEFAULT_CONFIG
from knight_flow.local_live import (
    DECODE_CADENCE_SECONDS,
    TAIL_WINDOW_SECONDS,
    LivePartials,
    LiveTailDecoder,
    decode_due,
    live_captions_wanted,
    tail_window,
)


class LivePartialsTests(unittest.TestCase):
    def test_text_is_the_pieces_in_order_then_the_tail(self) -> None:
        partials = LivePartials()
        partials.set_tail("the launch")
        self.assertEqual(partials.text(), "the launch")
        partials.set_piece(0, "Okay so the launch moved to Friday.")
        partials.set_tail("and we need")
        self.assertEqual(partials.text(), "Okay so the launch moved to Friday. and we need")

    def test_pieces_arrive_out_of_order_and_still_read_in_order(self) -> None:
        partials = LivePartials()
        partials.set_piece(1, "Second sentence.")
        partials.set_piece(0, "First sentence.")
        self.assertEqual(partials.text(), "First sentence. Second sentence.")

    def test_a_closed_piece_replaces_the_tail_that_previewed_it(self) -> None:
        partials = LivePartials()
        partials.set_tail("the launch moved to")
        partials.set_piece(0, "The launch moved to Friday.")
        self.assertEqual(partials.text(), "The launch moved to Friday.")

    def test_clear_empties_everything(self) -> None:
        partials = LivePartials()
        partials.set_piece(0, "Words.")
        partials.set_tail("more")
        partials.clear()
        self.assertEqual(partials.text(), "")


class TailWindowTests(unittest.TestCase):
    RATE, CHANNELS = 16000, 1
    BYTES_PER_SECOND = 2 * 16000

    def test_a_short_open_segment_is_decoded_whole(self) -> None:
        start, end = 0, 3 * self.BYTES_PER_SECOND
        self.assertEqual(tail_window(start, end, self.RATE, self.CHANNELS), (0, end))

    def test_a_long_open_segment_keeps_only_the_last_window(self) -> None:
        start, end = 0, 30 * self.BYTES_PER_SECOND
        window_start, window_end = tail_window(start, end, self.RATE, self.CHANNELS)
        self.assertEqual(window_end, end)
        self.assertEqual((window_end - window_start) / self.BYTES_PER_SECOND, TAIL_WINDOW_SECONDS)

    def test_the_window_starts_on_a_frame_boundary(self) -> None:
        start, end = 7, 30 * self.BYTES_PER_SECOND + 3
        window_start, window_end = tail_window(start, end, self.RATE, 2)
        self.assertEqual(window_start % 4, 0)
        self.assertEqual(window_end % 4, 0)

    def test_less_than_a_second_is_not_worth_a_decode(self) -> None:
        self.assertIsNone(tail_window(0, self.BYTES_PER_SECOND // 2, self.RATE, self.CHANNELS))


class CadenceTests(unittest.TestCase):
    def test_the_first_decode_is_due_at_once(self) -> None:
        self.assertTrue(decode_due(now=10.0, last=None))

    def test_a_decode_is_due_after_the_cadence(self) -> None:
        self.assertFalse(decode_due(now=10.5, last=10.0))
        self.assertTrue(decode_due(now=10.0 + DECODE_CADENCE_SECONDS, last=10.0))


class TheGateTests(unittest.TestCase):
    def config(self, toggle: bool) -> dict:
        return {"stt": {"provider": "local", "local_live_captions": toggle}}

    def test_the_default_is_off(self) -> None:
        self.assertIs(DEFAULT_CONFIG["stt"]["local_live_captions"], False)
        self.assertFalse(live_captions_wanted(DEFAULT_CONFIG, provider_id="local", gpu=True))

    def test_on_needs_the_local_route_on_any_machine(self) -> None:
        self.assertTrue(live_captions_wanted(self.config(True), provider_id="local", gpu=True))
        self.assertTrue(live_captions_wanted(self.config(True), provider_id="local", gpu=False), "the CPU measured 0.38 s per window")
        self.assertFalse(live_captions_wanted(self.config(True), provider_id="deepgram", gpu=True))
        self.assertFalse(live_captions_wanted(self.config(True), provider_id="talk_dat_cloud", gpu=True))

    def test_a_slow_decode_stretches_the_cadence(self) -> None:
        audio = bytearray(2 * 16000 * 3)
        texts: list[str] = []

        def slow(pcm: bytes) -> str:
            time.sleep(0.12)
            return "slow words"

        decoder = LiveTailDecoder(
            partials=LivePartials(), tail_span=lambda: (0, len(audio)),
            audio_slice=lambda s, e: bytes(audio[s:e]), decode=slow, on_text=texts.append,
            sample_rate=16000, channels=1, cadence_seconds=0.05,
        )
        decoder.start()
        time.sleep(0.9)
        decoder.stop(timeout=1.0)
        self.assertLessEqual(len(texts), 5, "a 0.12 s decode must not run every 0.05 s")
        self.assertGreaterEqual(len(texts), 2)

    def test_off_is_off_whatever_the_machine(self) -> None:
        self.assertFalse(live_captions_wanted(self.config(False), provider_id="local", gpu=True))


class LiveTailDecoderTests(unittest.TestCase):
    RATE, CHANNELS = 16000, 1

    def make(self, audio: bytearray, decoded: list[str], *, cadence: float = 0.05):
        partials = LivePartials()
        texts: list[str] = []
        calls: list[int] = []

        def decode(pcm: bytes) -> str:
            calls.append(len(pcm))
            return decoded[min(len(calls), len(decoded)) - 1]

        decoder = LiveTailDecoder(
            partials=partials,
            tail_span=lambda: (0, len(audio)),
            audio_slice=lambda start, end: bytes(audio[start:end]),
            decode=decode,
            on_text=texts.append,
            sample_rate=self.RATE,
            channels=self.CHANNELS,
            cadence_seconds=cadence,
        )
        return decoder, partials, texts, calls

    def test_the_partial_grows_while_audio_arrives(self) -> None:
        audio = bytearray(2 * self.RATE * 2)  # two seconds
        decoder, partials, texts, _ = self.make(audio, ["the launch", "the launch moved", "the launch moved to friday"])
        decoder.start()
        deadline = time.monotonic() + 3.0
        while len(texts) < 3 and time.monotonic() < deadline:
            audio.extend(bytes(2 * self.RATE // 2))
            time.sleep(0.06)
        decoder.stop(timeout=1.0)
        self.assertGreaterEqual(len(texts), 3)
        self.assertEqual(texts[:3], ["the launch", "the launch moved", "the launch moved to friday"])
        self.assertEqual(partials.text(), "the launch moved to friday")

    def test_stop_ends_the_thread_and_cancel_clears_the_text(self) -> None:
        audio = bytearray(2 * self.RATE * 3)
        decoder, partials, _, _ = self.make(audio, ["words"])
        decoder.start()
        time.sleep(0.15)
        decoder.stop(timeout=1.0)
        self.assertFalse(decoder.running)
        decoder.cancel()
        self.assertEqual(partials.text(), "")

    def test_a_decode_that_raises_never_kills_the_loop(self) -> None:
        audio = bytearray(2 * self.RATE * 3)
        seen: list[str] = []

        def flaky(pcm: bytes) -> str:
            if not seen:
                seen.append("boom")
                raise RuntimeError("engine hiccup")
            seen.append("ok")
            return "still going"

        texts: list[str] = []
        decoder = LiveTailDecoder(
            partials=LivePartials(), tail_span=lambda: (0, len(audio)),
            audio_slice=lambda s, e: bytes(audio[s:e]), decode=flaky, on_text=texts.append,
            sample_rate=self.RATE, channels=self.CHANNELS, cadence_seconds=0.05,
        )
        decoder.start()
        deadline = time.monotonic() + 1.5
        while not texts and time.monotonic() < deadline:
            time.sleep(0.05)
        decoder.stop(timeout=1.0)
        self.assertEqual(texts[:1], ["still going"])

    def test_nothing_is_decoded_before_a_second_of_tail_exists(self) -> None:
        audio = bytearray(2 * self.RATE // 4)  # a quarter second
        decoder, _, texts, calls = self.make(audio, ["never"])
        decoder.start()
        time.sleep(0.2)
        decoder.stop(timeout=1.0)
        self.assertEqual(calls, [])
        self.assertEqual(texts, [])


class NothingLeavesTheMachineTests(unittest.TestCase):
    def test_the_module_imports_no_network_code(self) -> None:
        source = (pathlib.Path(__file__).resolve().parents[1] / "knight_flow" / "local_live.py").read_text(encoding="utf-8")
        names = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                names.add(node.module or "")
        for forbidden in ("socket", "urllib", "http", "requests", "websockets", "ssl", "asyncio"):
            self.assertFalse(any(name == forbidden or name.startswith(forbidden + ".") for name in names), forbidden)

    def test_a_decode_loop_opens_no_socket(self) -> None:
        opened: list[object] = []
        original = socket.socket

        class Trap(original):  # type: ignore[misc]
            def __init__(self, *args, **kwargs):
                opened.append(self)
                super().__init__(*args, **kwargs)

        socket.socket = Trap  # type: ignore[assignment]
        try:
            audio = bytearray(2 * 16000 * 3)
            texts: list[str] = []
            decoder = LiveTailDecoder(
                partials=LivePartials(), tail_span=lambda: (0, len(audio)),
                audio_slice=lambda s, e: bytes(audio[s:e]), decode=lambda pcm: "local words",
                on_text=texts.append, sample_rate=16000, channels=1, cadence_seconds=0.05,
            )
            decoder.start()
            time.sleep(0.2)
            decoder.stop(timeout=1.0)
        finally:
            socket.socket = original  # type: ignore[assignment]
        self.assertEqual(opened, [])
        self.assertTrue(texts)


import math
from unittest.mock import patch

from knight_flow import stt_sessions
from knight_flow.stt_sessions import BatchSTTSession


class FakeStream:
    """Feeds `chunks` to the session callback at `pace` seconds each, on a thread."""

    def __init__(self, callback, chunks: list[bytes], pace: float = 0.02) -> None:
        self._callback, self._chunks, self._pace = callback, chunks, pace
        self._done = threading.Event()

    def __enter__(self):
        def feed() -> None:
            for chunk in self._chunks:
                if self._done.is_set():
                    return
                self._callback(chunk, len(chunk) // 2, None, None)
                time.sleep(self._pace)
        threading.Thread(target=feed, daemon=True).start()
        return self

    def __exit__(self, *exc) -> None:
        self._done.set()


def speech_chunks(seconds: float, rate: int = 16000, chunk_ms: int = 100) -> list[bytes]:
    per_chunk = rate * chunk_ms // 1000
    total = int(seconds * rate)
    samples = bytearray()
    for i in range(total):
        value = int(9000 * math.sin(2 * math.pi * 220 * i / rate))
        samples += int(value).to_bytes(2, "little", signed=True)
    return [bytes(samples[i:i + 2 * per_chunk]) for i in range(0, len(samples), 2 * per_chunk)]


def make_session(config: dict, updates: list, done: list, *, max_seconds: int = 300) -> BatchSTTSession:
    return BatchSTTSession(
        provider_id="local", api_key="", api_base="", model="parakeet-tdt-0.6b-v3", variant="",
        language="en-US", sample_rate=16000, channels=1, max_seconds=max_seconds,
        no_speech_timeout_seconds=120, silence_timeout_seconds=300, tail_capture_ms=0, min_capture_ms=0,
        extra={"config": config},
        on_update=lambda text, is_final: updates.append((text, is_final)),
        on_status=lambda status: None, on_level=lambda level: None,
        on_done=done.append, on_error=lambda error: done.append(("error", error)),
    )


def run_hold(config: dict, hold_seconds: float = 3.0, *, cancel: bool = False) -> tuple[list, list]:
    """A hold of `hold_seconds` of tone, then a release (or a cancel). Returns (updates, done)."""
    updates: list = []
    done: list = []
    session = make_session(config, updates, done)
    chunks = speech_chunks(hold_seconds)

    def open_stream(**kwargs):
        return FakeStream(kwargs["callback"], chunks), 16000, 1, None

    def fake_local(self, wav_bytes: bytes) -> str:
        pcm = stt_sessions.pcm16_from_wav(wav_bytes)
        return f"words for {len(pcm) // 32000} seconds"

    with patch.object(stt_sessions, "open_raw_input_stream", open_stream), \
         patch.object(stt_sessions, "input_stream_active", lambda stream: True), \
         patch.object(BatchSTTSession, "_transcribe_local", fake_local), \
         patch("knight_flow.local_stt.gpu_available", lambda: True), \
         patch("knight_flow.local_stt.gpu_default", lambda extra: True):
        session.start()
        time.sleep(hold_seconds + 0.3)
        if cancel:
            session.cancel()
        else:
            session.stop()
        session.join(timeout=8.0)
    return updates, done


class TheSessionShowsWordsWhileHeldTests(unittest.TestCase):
    ON = {"stt": {"provider": "local", "local_live_captions": True}}
    OFF = {"stt": {"provider": "local", "local_live_captions": False}}

    def test_partials_grow_during_the_hold_and_the_final_is_final(self) -> None:
        updates, done = run_hold(self.ON)
        partials = [text for text, is_final in updates if not is_final]
        self.assertGreaterEqual(len(partials), 2, updates)
        self.assertEqual(updates[-1][1], True, updates[-3:])
        self.assertEqual(done, [updates[-1][0]])

    def test_the_release_text_is_byte_equal_with_the_toggle_off(self) -> None:
        on_updates, on_done = run_hold(self.ON)
        off_updates, off_done = run_hold(self.OFF)
        self.assertEqual(on_done, off_done)
        self.assertEqual([u for u in off_updates if not u[1]], [], "toggle off: no partials, exactly today")

    def test_cancel_during_the_hold_publishes_nothing_final(self) -> None:
        updates, done = run_hold(self.ON, hold_seconds=2.0, cancel=True)
        self.assertEqual([u for u in updates if u[1]], [])
        self.assertEqual(done, [])


class ProviderRoutingTests(unittest.TestCase):
    def test_cloud_providers_still_get_the_live_socket_session(self) -> None:
        source = pathlib.Path(__file__).resolve().parents[1].joinpath("knight_flow", "stt_sessions.py").read_text(encoding="utf-8")
        self.assertIn("return DeepgramLiveSession(", source)
        self.assertIn("live_captions_wanted(", source)


class TheToggleTests(unittest.TestCase):
    SOURCE = pathlib.Path(__file__).resolve().parents[1].joinpath("knight_flow", "overlay.py").read_text(encoding="utf-8")

    def test_the_row_saves_the_stt_key_through_save_settings(self) -> None:
        block = self.SOURCE[self.SOURCE.index("local_live_captions_var"):][:2500]
        self.assertIn('"local_live_captions"', block)
        self.assertIn('self.callbacks.get("save_settings")', block)

    def test_the_label_is_in_the_products_voice(self) -> None:
        self.assertIn("Show words while I speak (local models)", self.SOURCE)

    def test_it_sits_in_the_local_models_section_not_a_fifth_destination(self) -> None:
        start = self.SOURCE.index("local_auto_download_var = tk.BooleanVar(")
        end = self.SOURCE.index("Compare ready and upcoming models", start)
        self.assertIn("local_live_captions_var", self.SOURCE[start:end + 4000])


if __name__ == "__main__":
    unittest.main()
