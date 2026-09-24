from __future__ import annotations

import asyncio
import json
import math
import queue
import sys
import threading
import time
from array import array
from collections.abc import Callable
from typing import Any
from urllib.parse import urlencode

from .audio_input import apply_gain, input_callback_problem, input_stream_active, open_raw_input_stream
from .capture_timing import should_extend_min_capture


UpdateCallback = Callable[[str, bool], None]
StatusCallback = Callable[[str], None]
LevelCallback = Callable[[float], None]
AudioCallback = Callable[[bytes, int, int, bool], None]
DoneCallback = Callable[[str], None]
ErrorCallback = Callable[[str], None]


def bool_param(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def build_listen_url(params: dict[str, Any]) -> str:
    items: list[tuple[str, str]] = []
    for key, value in params.items():
        if value is None or value == "":
            continue
        if isinstance(value, list):
            for item in value:
                if str(item).strip():
                    items.append((key, str(item)))
        else:
            items.append((key, bool_param(value)))
    return "wss://api.deepgram.com/v1/listen?" + urlencode(items)


# Finalize-drain staging. STEP is one wait window; the loop keeps granting
# windows while progress continues (queue draining / messages arriving) and
# CAP is the hard ceiling. Progress-based because flat windows were the
# long-dictation killer: Deepgram flushes one final per unflushed segment
# after CloseStream, and a long talk needs more than any fixed small wait.
SENDER_DRAIN_STEP = 1.5
SENDER_DRAIN_CAP = 15.0
RECEIVER_DRAIN_STEP = 2.0
RECEIVER_DRAIN_CAP = 20.0


def raw_rms_level(raw: bytes) -> float:
    """Return unamplified PCM16 RMS for UI metering and diagnostics."""
    if not raw:
        return 0.0
    sample_bytes = raw[: min(len(raw), 4096)]
    if len(sample_bytes) % 2:
        sample_bytes = sample_bytes[:-1]
    if not sample_bytes:
        return 0.0
    samples = array("h")
    samples.frombytes(sample_bytes)
    if sys.byteorder == "big":
        samples.byteswap()
    if not samples:
        return 0.0
    mean_square = sum(sample * sample for sample in samples) / len(samples)
    return min(1.0, math.sqrt(mean_square) / 32768.0)


def rms_level(raw: bytes) -> float:
    """Return the legacy speech-detection level used by capture safety logic."""
    return min(1.0, raw_rms_level(raw) * 6.0)


class DeepgramLiveSession:
    def __init__(
        self,
        *,
        api_key: str,
        params: dict[str, Any],
        max_seconds: int,
        no_speech_timeout_seconds: int,
        silence_timeout_seconds: int,
        tail_capture_ms: int,
        min_capture_ms: int,
        input_device: Any = None,
        gain: float = 1.0,
        on_update: UpdateCallback,
        on_status: StatusCallback,
        on_level: LevelCallback,
        on_done: DoneCallback,
        on_error: ErrorCallback,
        on_audio: AudioCallback | None = None,
    ) -> None:
        self.api_key = api_key.strip()
        self.params = params
        self.max_seconds = max_seconds
        self.no_speech_timeout_seconds = no_speech_timeout_seconds
        self.silence_timeout_seconds = silence_timeout_seconds
        self.tail_capture_ms = tail_capture_ms
        self.min_capture_ms = int(min_capture_ms)
        self.input_device = input_device
        self.gain = float(gain or 1.0)
        # X-36: the adaptive front-end wraps the manual gain -- whispering
        # just works, on every engine, with no mode to find.
        from .audio_front_end import AdaptiveFrontEnd
        self.front_end = AdaptiveFrontEnd(pre_gain=self.gain)
        self.on_update = on_update
        self.on_status = on_status
        self.on_level = on_level
        self.on_done = on_done
        self.on_error = on_error
        self.on_audio = on_audio

        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._cancel_event = threading.Event()
        self._audio_queue: queue.Queue[bytes | None] = queue.Queue(maxsize=240)
        self._final_parts: list[str] = []
        self._interim_text = ""
        self._done_called = False
        self._heard_voice = False
        self._last_voice_at = 0.0
        # Any parsed server message stamps this; the finalize drain uses it
        # to tell "still flushing results" from "actually stalled" (see
        # SENDER/RECEIVER_DRAIN_* at module top).
        self._last_message_at = 0.0
        self._audio_closed = threading.Event()
        self._audio = bytearray()
        self._sample_rate = int(params.get("sample_rate", 16000))
        self._channels = int(params.get("channels", 1))
        self._transport_lock = threading.Lock()
        self._transport_reasons: list[str] = []
        self._audio_queue_drops = 0

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive() and not self._stop_event.is_set())

    def start(self) -> None:
        from .net_fence import assert_cloud_allowed
        assert_cloud_allowed("api.deepgram.com", "The cloud caption stream")
        if not self.api_key:
            raise ValueError("deepgram_api_key_missing")
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._thread_main, name="TalkDatDeepgram", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def cancel(self) -> None:
        self._cancel_event.set()
        self._audio_closed.set()
        self.stop()
        self._put_audio(None)

    def join(self, timeout: float | None = None) -> None:
        if self._thread:
            self._thread.join(timeout)

    def current_text(self) -> str:
        return " ".join([*self._final_parts, self._interim_text]).strip()

    def captured_audio(self) -> tuple[bytes, int, int, bool]:
        return bytes(self._audio), self._sample_rate, self._channels, bool(self._heard_voice)

    @property
    def transport_degraded(self) -> bool:
        with self._transport_lock:
            return bool(self._transport_reasons)

    @property
    def transport_degradation_reasons(self) -> tuple[str, ...]:
        with self._transport_lock:
            return tuple(self._transport_reasons)

    @property
    def audio_queue_drops(self) -> int:
        with self._transport_lock:
            return self._audio_queue_drops

    def _thread_main(self) -> None:
        try:
            asyncio.run(self._run())
        except Exception as exc:
            self._safe_error(str(exc) or exc.__class__.__name__)
            self._finish("")

    async def _run(self) -> None:
        import websockets

        headers = {"Authorization": f"Token {self.api_key}"}
        self._safe_status("starting")
        sample_rate = self._sample_rate
        channels = self._channels

        def callback(indata: Any, frames: int, time_info: Any, status: Any) -> None:
            if self._cancel_event.is_set() or self._audio_closed.is_set():
                return
            if input_callback_problem(status):
                self._record_transport_degradation("audio_callback")
            raw_data = bytes(indata)
            data = self.front_end.process(raw_data)
            self._audio.extend(data)
            self._put_audio(data)
            level = rms_level(data)
            if level >= 0.025:
                self._heard_voice = True
                self._last_voice_at = time.monotonic()
            self._safe_audio(data, sample_rate, channels, self._heard_voice)
            # Raw dynamics scaled by the live gain (limiter excluded): a hot
            # mic's syllables stay intact AND a quiet mic -- the field case
            # that made the voice wave vanish -- stays visible.
            self._safe_level(self.front_end.visual_level(raw_rms_level(raw_data)))

        stream, sample_rate, channels, actual_device = open_raw_input_stream(
            samplerate=sample_rate,
            channels=channels,
            dtype="int16",
            blocksize=0,
            device=self.input_device,
            callback=callback,
        )
        self._sample_rate = sample_rate
        self._channels = channels
        self.input_device = actual_device
        params = dict(self.params)
        params["sample_rate"] = sample_rate
        params["channels"] = channels
        url = build_listen_url(params)

        connect_kwargs = {"ping_interval": 20, "ping_timeout": 10, "close_timeout": 2}
        try:
            context = websockets.connect(url, additional_headers=headers, **connect_kwargs)
        except TypeError:
            context = websockets.connect(url, extra_headers=headers, **connect_kwargs)

        with stream:
            self._safe_status("warming")
            async with context as websocket:
                self._safe_status("connected")
                sender = asyncio.create_task(self._send_loop(websocket))
                receiver = asyncio.create_task(self._receive_loop(websocket))
                keepalive = asyncio.create_task(self._keepalive_loop(websocket))
                transport_tasks = {
                    "sender": sender,
                    "receiver": receiver,
                    "keepalive": keepalive,
                }
                transport_failed = False
                try:
                    self._safe_status("listening")
                    started = time.monotonic()
                    self._last_voice_at = started

                    while not self._cancel_event.is_set():
                        clean_completions = {"keepalive"} if self._stop_event.is_set() else None
                        if self._observe_transport_tasks(
                            transport_tasks,
                            clean_completions=clean_completions,
                        ):
                            transport_failed = True
                            break

                        now = time.monotonic()
                        if self._stop_event.is_set():
                            if should_extend_min_capture(
                                len(self._audio),
                                sample_rate,
                                channels,
                                heard_voice=self._heard_voice,
                                min_capture_ms=self.min_capture_ms,
                            ):
                                await self._wait_for_transport(transport_tasks)
                                continue
                            break
                        if not input_stream_active(stream):
                            self._report_transport_issue(
                                "input_lost",
                                "Microphone input stopped unexpectedly. Recovering captured audio.",
                            )
                            transport_failed = True
                            break
                        if now - started >= self.max_seconds:
                            self._safe_status("time_limit")
                            self.stop()
                            break
                        if not self._heard_voice and now - started >= self.no_speech_timeout_seconds:
                            self._safe_status("no_speech_timeout")
                            self.stop()
                            break
                        if self._heard_voice and now - self._last_voice_at >= self.silence_timeout_seconds:
                            self._safe_status("silence_timeout")
                            self.stop()
                            break
                        await self._wait_for_transport(transport_tasks)

                    await asyncio.sleep(max(0, self.tail_capture_ms) / 1000)
                    self._audio_closed.set()
                    self._put_audio(None)

                    if not transport_failed:
                        # Flat 1.5s here declared slow-uplink sessions dead
                        # while the tail audio was still uploading. Keep
                        # waiting as long as the queue is DRAINING; only a
                        # genuinely stuck sender (or the hard cap) fails.
                        sender_deadline = time.monotonic() + SENDER_DRAIN_CAP
                        while True:
                            backlog = self._audio_queue.qsize()
                            await asyncio.wait({sender}, timeout=SENDER_DRAIN_STEP)
                            if sender.done():
                                if self._observe_transport_tasks(
                                    transport_tasks,
                                    clean_completions={"sender", "keepalive"},
                                ):
                                    transport_failed = True
                                break
                            drained = self._audio_queue.qsize() < backlog
                            if not drained or time.monotonic() >= sender_deadline:
                                self._report_transport_issue(
                                    "sender_timeout",
                                    "Deepgram sender did not finish while finalizing.",
                                )
                                transport_failed = True
                                break

                    if not transport_failed:
                        try:
                            await websocket.send(json.dumps({"type": "CloseStream"}))
                        except Exception as exc:
                            self._report_transport_issue(
                                "close_failure",
                                f"Deepgram close failed: {str(exc) or exc.__class__.__name__}",
                            )
                            transport_failed = True

                    if not transport_failed:
                        # THE long-dictation killer (field: "45 seconds to
                        # transcribe"): after CloseStream, Deepgram flushes a
                        # final per unflushed segment -- seconds of tail on a
                        # long talk -- and a flat 2.0s window declared those
                        # sessions degraded, so minutes of audio were then
                        # re-transcribed on the local CPU. Drain until QUIET:
                        # keep waiting while messages still arrive; give up
                        # only when the stream stalls or the hard cap lands.
                        receiver_deadline = time.monotonic() + RECEIVER_DRAIN_CAP
                        while True:
                            seen = self._last_message_at
                            await asyncio.wait({receiver}, timeout=RECEIVER_DRAIN_STEP)
                            if receiver.done():
                                self._observe_transport_tasks(
                                    {"receiver": receiver},
                                    clean_completions={"receiver"},
                                )
                                break
                            flowing = self._last_message_at > seen
                            if not flowing or time.monotonic() >= receiver_deadline:
                                self._report_transport_issue(
                                    "receiver_timeout",
                                    "Deepgram receiver did not finish while finalizing.",
                                )
                                break
                finally:
                    self._audio_closed.set()
                    self._put_audio(None)
                    for task in transport_tasks.values():
                        task.cancel()
                    await asyncio.gather(*transport_tasks.values(), return_exceptions=True)

        self._finish(self.current_text())

    async def _send_loop(self, websocket: Any) -> None:
        while not self._cancel_event.is_set():
            chunk = await asyncio.to_thread(self._audio_queue.get)
            if chunk is None:
                break
            await websocket.send(chunk)

    async def _receive_loop(self, websocket: Any) -> None:
        async for raw in websocket:
            if isinstance(raw, bytes):
                continue
            self._handle_message(str(raw))

    async def _keepalive_loop(self, websocket: Any) -> None:
        while not self._stop_event.is_set() and not self._cancel_event.is_set():
            await asyncio.sleep(8)
            await websocket.send(json.dumps({"type": "KeepAlive"}))

    async def _wait_for_transport(self, tasks: dict[str, asyncio.Task[None]]) -> None:
        await asyncio.wait(set(tasks.values()), timeout=0.04, return_when=asyncio.FIRST_COMPLETED)

    def _observe_transport_tasks(
        self,
        tasks: dict[str, asyncio.Task[None]],
        *,
        clean_completions: set[str] | None = None,
    ) -> bool:
        clean_completions = clean_completions or set()
        issues: list[tuple[str, str]] = []
        for name, task in tasks.items():
            if not task.done():
                continue
            if task.cancelled():
                issues.append(
                    (
                        f"{name}_failure",
                        f"Deepgram {name} was cancelled unexpectedly.",
                    )
                )
                continue
            error = task.exception()
            if error is not None:
                detail = str(error) or error.__class__.__name__
                issues.append(
                    (
                        f"{name}_failure",
                        f"Deepgram {name} failed: {detail}",
                    )
                )
            elif name not in clean_completions:
                issues.append(
                    (
                        f"{name}_eof",
                        f"Deepgram {name} ended unexpectedly.",
                    )
                )

        if not issues:
            return False
        for reason, _message in issues:
            self._record_transport_degradation(reason)
        self._stop_event.set()
        self._safe_error(" ".join(message for _reason, message in issues))
        return True

    def _report_transport_issue(self, reason: str, message: str) -> None:
        self._record_transport_degradation(reason)
        self._stop_event.set()
        self._safe_error(message)

    def _record_transport_degradation(self, reason: str) -> None:
        with self._transport_lock:
            if reason not in self._transport_reasons:
                self._transport_reasons.append(reason)

    def _handle_message(self, raw: str) -> None:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return

        self._last_message_at = time.monotonic()
        msg_type = payload.get("type")
        if msg_type == "Results":
            transcript = str(
                payload.get("channel", {}).get("alternatives", [{}])[0].get("transcript", "")
            ).strip()
            if not transcript:
                return
            if payload.get("is_final"):
                if not self._final_parts or self._final_parts[-1] != transcript:
                    self._final_parts.append(transcript)
                self._interim_text = ""
            else:
                self._interim_text = transcript

            combined = self.current_text()
            is_final = bool(payload.get("speech_final") or payload.get("from_finalize"))
            self._safe_update(combined, is_final)
            return

        if msg_type == "UtteranceEnd":
            self._safe_update(self.current_text(), True)
            return

        if msg_type == "Warning":
            message = payload.get("message") or payload.get("description") or msg_type
            self._safe_status(f"warning:{message}")
            return

        if msg_type == "Error":
            message = payload.get("message") or payload.get("description") or msg_type
            self._safe_error(str(message))

    def _put_audio(self, chunk: bytes | None) -> None:
        try:
            self._audio_queue.put_nowait(chunk)
        except queue.Full:
            if chunk is not None:
                self._record_audio_queue_drop()
                return

            while True:
                try:
                    dropped = self._audio_queue.get_nowait()
                except queue.Empty:
                    pass
                else:
                    if dropped is not None:
                        self._record_audio_queue_drop()
                try:
                    self._audio_queue.put_nowait(None)
                    return
                except queue.Full:
                    continue

    def _record_audio_queue_drop(self) -> None:
        with self._transport_lock:
            self._audio_queue_drops += 1
            if "audio_queue_overflow" not in self._transport_reasons:
                self._transport_reasons.append("audio_queue_overflow")

    def _finish(self, text: str) -> None:
        if self._done_called or self._cancel_event.is_set():
            return
        self._done_called = True
        try:
            self.on_done(text.strip())
        except Exception:
            pass

    def _safe_update(self, text: str, is_final: bool) -> None:
        try:
            self.on_update(text, is_final)
        except Exception:
            pass

    def _safe_status(self, status: str) -> None:
        try:
            self.on_status(status)
        except Exception:
            pass

    def _safe_level(self, level: float) -> None:
        try:
            self.on_level(level)
        except Exception:
            pass

    def _safe_audio(
        self,
        data: bytes,
        sample_rate: int,
        channels: int,
        heard_voice: bool,
    ) -> None:
        if self.on_audio is None:
            return
        try:
            self.on_audio(data, sample_rate, channels, heard_voice)
        except Exception:
            pass

    def _safe_error(self, error: str) -> None:
        try:
            self.on_error(error)
        except Exception:
            pass
