from __future__ import annotations

import base64
import contextlib
import io
import json
import logging
import os
import threading
import time
import wave
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .audio_input import (
    apply_gain,
    effective_gain,
    input_callback_problem,
    input_stream_active,
    open_raw_input_stream,
    resolve_input_device,
)
from .capture_timing import should_extend_min_capture
from .config import deepgram_params
from .deepgram_live import DeepgramLiveSession, raw_rms_level, rms_level
from .local_live import LivePartials, LiveTailDecoder, live_captions_wanted
from .stt_registry import PROVIDER_BY_ID, provider_settings, selected_model_id, selected_provider_id, selected_variant


log = logging.getLogger(__name__)

UpdateCallback = Callable[[str, bool], None]
StatusCallback = Callable[[str], None]
LevelCallback = Callable[[float], None]
AudioCallback = Callable[[bytes, int, int, bool], None]
DoneCallback = Callable[[str], None]
ErrorCallback = Callable[[str], None]


def pcm16_from_wav(wav_bytes: bytes) -> bytes:
    """The PCM frames inside a WAV container, or b"" when it is not one."""
    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as handle:
            if handle.getsampwidth() != 2:
                return b""
            return handle.readframes(handle.getnframes())
    except Exception:
        return b""


class BatchSTTSession:
    def __init__(
        self,
        *,
        provider_id: str,
        api_key: str,
        api_base: str,
        model: str,
        variant: str,
        language: str,
        sample_rate: int,
        channels: int,
        max_seconds: int,
        no_speech_timeout_seconds: int,
        silence_timeout_seconds: int,
        tail_capture_ms: int,
        min_capture_ms: int,
        extra: dict[str, Any],
        input_device: Any = None,
        gain: float = 1.0,
        on_update: UpdateCallback,
        on_status: StatusCallback,
        on_level: LevelCallback,
        on_done: DoneCallback,
        on_error: ErrorCallback,
        on_audio: AudioCallback | None = None,
    ) -> None:
        self.provider_id = provider_id
        self.api_key = api_key.strip()
        self.api_base = api_base.strip().rstrip("/")
        self.model = model.strip()
        self.variant = variant.strip()
        self.language = language.strip()
        self.sample_rate = int(sample_rate)
        self.channels = int(channels)
        self.max_seconds = max_seconds
        self.no_speech_timeout_seconds = no_speech_timeout_seconds
        self.silence_timeout_seconds = silence_timeout_seconds
        self.tail_capture_ms = tail_capture_ms
        self.min_capture_ms = int(min_capture_ms)
        self.extra = extra
        from .recognition_bias import recognition_terms
        self.recognition_vocabulary = recognition_terms(extra.get("config", {}))
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
        self.on_stable_update: Callable[[str], None] | None = None

        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._cancel_event = threading.Event()
        self._done_called = False
        self._heard_voice = False
        self._last_voice_at = 0.0
        self._current_text = ""
        self._audio = bytearray()
        self._transport_lock = threading.Lock()
        self._transport_reasons: list[str] = []
        # X-608: how sure the local recognizer was of each word of this take
        # (lowest score wins across segments). Read once the take is done.
        self.word_confidence: dict[str, float] = {}
        self._confidence_lock = threading.Lock()

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive() and not self._stop_event.is_set())

    def start(self) -> None:
        provider = PROVIDER_BY_ID.get(self.provider_id)
        if not self.api_key and not (provider and provider.key_optional):
            raise ValueError(f"{self.provider_id}_api_key_missing")
        if not self.model:
            raise ValueError(f"{self.provider_id}_model_missing")
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._thread_main, name=f"TalkDatSTT-{self.provider_id}", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def cancel(self) -> None:
        self._cancel_event.set()
        self.stop()

    def join(self, timeout: float | None = None) -> None:
        if self._thread:
            self._thread.join(timeout)

    def current_text(self) -> str:
        return self._current_text.strip()

    def captured_audio(self) -> tuple[bytes, int, int, bool]:
        return bytes(self._audio), self.sample_rate, self.channels, bool(self._heard_voice)

    @property
    def transport_degraded(self) -> bool:
        with self._transport_lock:
            return bool(self._transport_reasons)

    @property
    def transport_degradation_reasons(self) -> tuple[str, ...]:
        with self._transport_lock:
            return tuple(self._transport_reasons)

    def _record_transport_degradation(self, reason: str) -> bool:
        with self._transport_lock:
            if reason in self._transport_reasons:
                return False
            self._transport_reasons.append(reason)
            return True

    def _thread_main(self) -> None:
        try:
            self._record_then_transcribe()
        except Exception as exc:
            self._safe_error(str(exc) or exc.__class__.__name__)
            self._finish("")

    def _record_then_transcribe(self) -> None:
        self._safe_status("warming")
        self._last_voice_at = time.monotonic()

        # X-31: on long sessions, closed speech segments transcribe WHILE
        # the person is still talking; the release only pays for the tail,
        # and the reconcile pass downstream sees the full joined text. Armed
        # only past two minutes of allowance -- short dictations gain
        # nothing and the extra machinery must never touch them.
        progressive = None
        live: LiveTailDecoder | None = None
        live_wanted = False
        if self.provider_id == "local":
            try:
                from . import local_stt

                live_wanted = live_captions_wanted(
                    self.extra.get("config") if isinstance(self.extra, dict) else None,
                    provider_id=self.provider_id,
                    gpu=local_stt.gpu_default(self.extra) and local_stt.gpu_available(),
                )
            except Exception:
                live_wanted = False
        # X-416: live captions need the planner even on a short allowance.
        if self.max_seconds >= 120 or live_wanted:
            try:
                from concurrent.futures import ThreadPoolExecutor

                from .progressive import SegmentPlanner, VoiceGate

                progressive = {
                    "planner": SegmentPlanner(self.sample_rate, self.channels),
                    "gate": VoiceGate(),
                    "pool": ThreadPoolExecutor(max_workers=1, thread_name_prefix="TalkDatSegment"),
                    "futures": [],
                }
            except Exception:
                progressive = None
        if live_wanted and progressive is not None:
            # X-416: the words so far, while the trigger is held. The pieces are
            # the same futures the release joins; the tail is a rolling decode
            # of the open segment. Neither ever feeds the final text below.
            live = LiveTailDecoder(
                partials=LivePartials(),
                tail_span=progressive["planner"].tail_span,
                audio_slice=lambda start, end: bytes(self._audio[start:end]),
                decode=lambda pcm: self._transcribe_local(self._wav_bytes(pcm), record=False).strip(),
                on_text=lambda text: self._safe_update(text, False),
                sample_rate=self.sample_rate,
                channels=self.channels,
            )

        def callback(indata: Any, frames: int, time_info: Any, status: Any) -> None:
            if self._cancel_event.is_set():
                return
            if input_callback_problem(status):
                self._record_transport_degradation("audio_callback")
            raw_data = bytes(indata)
            data = self.front_end.process(raw_data)
            self._audio.extend(data)
            level = rms_level(data)
            if progressive is not None:
                try:
                    # X-405: judged on the RAW mic level against this recording's own
                    # floor and speech level. `level` is post-front-end audio, and the
                    # adaptive gain lifts every pause toward the speech target, so the
                    # fixed threshold never saw a pause and no segment ever closed.
                    span = progressive["planner"].observe(len(data), level, voiced=progressive["gate"].voiced(rms_level(raw_data)))
                    if span is not None:
                        start, end = span
                        segment = bytes(self._audio[start:end])
                        future = progressive["pool"].submit(
                            lambda seg=segment: self._transcribe(self._wav_bytes(seg)).strip()
                        )
                        progressive["futures"].append(future)
                        future.add_done_callback(
                            lambda done: self._publish_stable_pieces(progressive["futures"])
                        )
                        if live is not None:
                            index = len(progressive["futures"]) - 1

                            def piece_landed(done, index=index, live=live) -> None:
                                if done.exception() is None:
                                    live.publish_piece(index, done.result())

                            future.add_done_callback(piece_landed)
                except Exception:
                    pass
            if level >= 0.025:
                self._heard_voice = True
                self._last_voice_at = time.monotonic()
            self._safe_audio(data, self.sample_rate, self.channels, self._heard_voice)
            # Raw dynamics scaled by the live gain: a quiet mic's wave stays
            # visible and a hot mic's syllables are not limiter-flattened.
            self._safe_level(self.front_end.visual_level(raw_rms_level(raw_data)))

        stream, actual_rate, actual_channels, actual_device = open_raw_input_stream(
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype="int16",
            blocksize=0,
            device=self.input_device,
            callback=callback,
        )
        self.sample_rate = actual_rate
        self.channels = actual_channels
        self.input_device = actual_device

        started = time.monotonic()
        with stream:
            self._safe_status("listening")
            if live is not None:
                live.start()
            while not self._cancel_event.is_set():
                now = time.monotonic()
                if self._stop_event.is_set():
                    if should_extend_min_capture(
                        len(self._audio),
                        self.sample_rate,
                        self.channels,
                        heard_voice=self._heard_voice,
                        min_capture_ms=self.min_capture_ms,
                    ):
                        time.sleep(0.025)
                        continue
                    break
                if not input_stream_active(stream):
                    self._record_transport_degradation("input_lost")
                    self._safe_error("Microphone input stopped unexpectedly. Recovering captured audio.")
                    self.stop()
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
                time.sleep(0.025)
            if not self._cancel_event.is_set():
                self._drain_tail()

        if live is not None:
            # The release path below is the same bytes as with the toggle off.
            live.stop(timeout=0.5)
        self._safe_level(0)
        if self._cancel_event.is_set():
            return
        if len(self._audio) < max(512, self.sample_rate * self.channels):
            self._finish("")
            return

        self._safe_status("transcribing")
        text = ""
        if progressive is not None and progressive["futures"]:
            try:
                start, end = progressive["planner"].tail_span()
                tail = bytes(self._audio[start:end])
                tail_text = self._transcribe(self._wav_bytes(tail)).strip() if len(tail) > 512 else ""
                pieces = [future.result(timeout=self.max_seconds) for future in progressive["futures"]]
                log.info("progressive: %d segments closed during the hold, tail %.1fs of %.1fs", len(pieces), (end - start) / (2 * max(1, self.channels) * self.sample_rate), len(self._audio) / (2 * max(1, self.channels) * self.sample_rate))
                # X-609: the seams are pauses, not sentence ends; repair them.
                from .progressive import join_segment_texts

                text = join_segment_texts([*pieces, tail_text])
            except Exception:
                text = ""
            finally:
                progressive["pool"].shutdown(wait=False)
        if not text:
            wav_bytes = self._wav_bytes(bytes(self._audio))
            text = self._transcribe(wav_bytes).strip()
        elif progressive is not None:
            pass
        self._current_text = text
        if text:
            self._safe_update(text, True)
        self._finish(text)

    def _publish_stable_pieces(self, futures: list) -> None:
        """Only completed contiguous segments, independently from captions."""
        callback = getattr(self, "on_stable_update", None)
        if not callable(callback) or self._cancel_event.is_set():
            return
        pieces = []
        for future in tuple(futures):
            if not future.done() or future.cancelled() or future.exception() is not None:
                break
            pieces.append(str(future.result()).strip())
        text = " ".join(piece for piece in pieces if piece)
        if text and not self._cancel_event.is_set():
            try:
                callback(text)
            except Exception:
                log.debug("stable text preparation skipped", exc_info=True)

    # How long the tail must be silent before we accept that speech has ended.
    # Short enough to save most of the wait, long enough to survive the gap
    # between two words rather than cutting between them.
    TAIL_QUIET_SECONDS = 0.14

    def _drain_tail(self) -> None:
        """Hold the microphone open after the stop signal, but only while
        speech is still arriving.

        This used to be a flat sleep of tail_capture_ms -- 520ms by default --
        paid in full on every dictation. That budget exists for the case where
        someone releases the key a moment before they stop talking, which is
        real but uncommon; charging every dictation the worst case made it a
        quarter of the total time from key release to text on screen.

        The capture stream is still running here, so _last_voice_at keeps
        updating while there is anything to hear. Waiting for a short silence
        instead of a fixed duration keeps the whole budget available when it is
        actually needed and returns almost immediately when it is not.
        """
        budget = max(0.0, self.tail_capture_ms / 1000.0)
        if budget <= 0:
            return
        deadline = time.monotonic() + budget
        while True:
            now = time.monotonic()
            if now >= deadline or self._cancel_event.is_set():
                return
            # Only trust the silence test once we have heard the speaker at
            # all; otherwise a session that never picked up voice would exit
            # instantly and clip audio the meter simply never registered.
            if self._heard_voice and (now - self._last_voice_at) >= self.TAIL_QUIET_SECONDS:
                return
            time.sleep(0.02)

    def _wav_bytes(self, raw_pcm: bytes) -> bytes:
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav:
            wav.setnchannels(self.channels)
            wav.setsampwidth(2)
            wav.setframerate(self.sample_rate)
            wav.writeframes(raw_pcm)
        return buffer.getvalue()

    # api_kind -> the method that actually talks to that API. Held as data rather
    # than built inline so a test can assert every provider in the registry has a
    # live adapter. A provider whose api_kind is missing here is fully selectable
    # in the settings UI and only fails on the user's first dictation.
    TRANSCRIBE_HANDLERS: dict[str, str] = {
        "openai_batch": "_transcribe_openai_compatible",
        "elevenlabs_batch": "_transcribe_elevenlabs",
        "assemblyai_batch": "_transcribe_assemblyai",
        "gemini_batch": "_transcribe_gemini",
        "xai_batch": "_transcribe_xai",
        "smallest_batch": "_transcribe_smallest",
        "soniox_batch": "_transcribe_soniox",
        "local_batch": "_transcribe_local",
        "deepgram_stream": "_transcribe_deepgram_batch",
    }

    def _transcribe(self, wav_bytes: bytes) -> str:
        provider = PROVIDER_BY_ID.get(self.provider_id)
        api_kind = provider.api_kind if provider else "openai_batch"
        handler_name = self.TRANSCRIBE_HANDLERS.get(api_kind)
        if handler_name is None:
            raise NotImplementedError("This speech provider is not available in this build.")
        handler: Callable[[bytes], str] = getattr(self, handler_name)
        return handler(wav_bytes)

    def _transcribe_openai_compatible(self, wav_bytes: bytes) -> str:
        base = self.api_base or "https://api.openai.com"
        url = base + "/v1/audio/transcriptions"
        response_format = self.variant if self.variant in {"json", "text", "verbose_json", "diarized_json"} else "json"
        fields: dict[str, str] = {"model": self.model, "response_format": response_format}
        if "diarize" in self.model:
            # OpenAI's diarize transcription model rejects audio over 30s unless auto chunking is on.
            fields.setdefault("chunking_strategy", "auto")
        if self.language:
            fields["language"] = self.language.split("-")[0]
        for key, value in self.extra.items():
            if isinstance(value, (str, int, float, bool)) and str(key).strip():
                fields[str(key)] = str(value).lower() if isinstance(value, bool) else str(value)
        headers = {"Authorization": f"Bearer {self.api_key}"}
        payload, content_type = multipart_form(fields, {"file": ("talk-dat.wav", wav_bytes, "audio/wav")})
        raw = http_request(url, method="POST", body=payload, headers={**headers, "Content-Type": content_type})
        if response_format == "text":
            return raw.decode("utf-8", errors="replace").strip()
        data = json.loads(raw.decode("utf-8", errors="replace"))
        return extract_text(data)

    def _transcribe_elevenlabs(self, wav_bytes: bytes) -> str:
        base = self.api_base or "https://api.elevenlabs.io"
        fields: dict[str, str] = {"model_id": self.model}
        if self.language:
            fields["language_code"] = self.language.split("-")[0]
        if self.variant == "diarize":
            fields["diarize"] = "true"
        if self.variant == "tag-audio-events":
            fields["tag_audio_events"] = "true"
        for key, value in self.extra.items():
            if isinstance(value, (str, int, float, bool)) and str(key).strip():
                fields[str(key)] = str(value).lower() if isinstance(value, bool) else str(value)
        payload, content_type = multipart_form(fields, {"file": ("talk-dat.wav", wav_bytes, "audio/wav")})
        raw = http_request(
            base + "/v1/speech-to-text",
            method="POST",
            body=payload,
            headers={"xi-api-key": self.api_key, "Content-Type": content_type},
        )
        data = json.loads(raw.decode("utf-8", errors="replace"))
        return extract_text(data)

    def _transcribe_xai(self, wav_bytes: bytes) -> str:
        base = self.api_base or "https://api.x.ai"
        fields: dict[str, str] = {
            "format": "true",
            "filler_words": "false",
        }
        if self.language:
            fields["language"] = self.language.split("-")[0]
        if self.variant == "diarize":
            fields["diarize"] = "true"
        for key, value in self.extra.items():
            if isinstance(value, (str, int, float, bool)) and str(key).strip():
                fields[str(key)] = str(value).lower() if isinstance(value, bool) else str(value)
        payload, content_type = multipart_form(fields, {"file": ("talk-dat.wav", wav_bytes, "audio/wav")})
        raw = http_request(
            base + "/v1/stt",
            method="POST",
            body=payload,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": content_type},
        )
        return extract_text(json.loads(raw.decode("utf-8", errors="replace")))

    def _transcribe_smallest(self, wav_bytes: bytes) -> str:
        base = self.api_base or "https://api.smallest.ai"
        language = "en" if self.model == "pulse-pro" else (self.language.split("-")[0] if self.language else "en")
        params: dict[str, str] = {"model": self.model or "pulse-pro", "language": language}
        if self.variant == "diarize":
            params["diarize"] = "true"
        for key, value in self.extra.items():
            if isinstance(value, (str, int, float, bool)) and str(key).strip():
                params[str(key)] = str(value).lower() if isinstance(value, bool) else str(value)
        raw = http_request(
            base + "/waves/v1/stt/?" + urlencode(params),
            method="POST",
            body=wav_bytes,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/octet-stream"},
        )
        return extract_text(json.loads(raw.decode("utf-8", errors="replace")))

    def _transcribe_soniox(self, wav_bytes: bytes) -> str:
        base = self.api_base or "https://api.soniox.com"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        upload_payload, upload_type = multipart_form({}, {"file": ("talk-dat.wav", wav_bytes, "audio/wav")})
        upload_raw = http_request(
            base + "/v1/files",
            method="POST",
            body=upload_payload,
            headers={**headers, "Content-Type": upload_type},
        )
        file_id = str(json.loads(upload_raw.decode("utf-8", errors="replace")).get("id") or "")
        if not file_id:
            raise RuntimeError("Soniox upload did not return a file id")
        transcription_id = ""
        try:
            body: dict[str, Any] = {
                "model": self.model or "stt-async-v5",
                "file_id": file_id,
                "enable_speaker_diarization": self.variant == "diarize",
            }
            if self.language:
                body["language_hints"] = [self.language.split("-")[0]]
            body.update(self.extra if isinstance(self.extra, dict) else {})
            create_raw = http_request(
                base + "/v1/transcriptions",
                method="POST",
                body=json.dumps(body).encode("utf-8"),
                headers={**headers, "Content-Type": "application/json"},
            )
            transcription_id = str(json.loads(create_raw.decode("utf-8", errors="replace")).get("id") or "")
            if not transcription_id:
                raise RuntimeError("Soniox transcription did not return an id")
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline and not self._cancel_event.is_set():
                time.sleep(0.8)
                poll_raw = http_request(base + f"/v1/transcriptions/{transcription_id}", headers=headers)
                data = json.loads(poll_raw.decode("utf-8", errors="replace"))
                status = str(data.get("status", "")).lower()
                if status == "completed":
                    transcript_raw = http_request(
                        base + f"/v1/transcriptions/{transcription_id}/transcript",
                        headers=headers,
                    )
                    return extract_text(json.loads(transcript_raw.decode("utf-8", errors="replace")))
                if status in {"error", "failed"}:
                    raise RuntimeError(str(data.get("error_message") or data.get("message") or "Soniox transcription failed"))
            raise TimeoutError("Soniox transcription timed out")
        finally:
            if transcription_id:
                with contextlib.suppress(Exception):
                    http_request(
                        base + f"/v1/transcriptions/{transcription_id}",
                        method="DELETE",
                        headers=headers,
                        retries=0,
                    )
            with contextlib.suppress(Exception):
                http_request(base + f"/v1/files/{file_id}", method="DELETE", headers=headers, retries=0)

    def _transcribe_assemblyai(self, wav_bytes: bytes) -> str:
        base = self.api_base or "https://api.assemblyai.com"
        headers = {"Authorization": self.api_key}
        upload_raw = http_request(
            base + "/v2/upload",
            method="POST",
            body=wav_bytes,
            headers={**headers, "Content-Type": "audio/wav"},
        )
        upload_url = json.loads(upload_raw.decode("utf-8", errors="replace")).get("upload_url")
        if not upload_url:
            raise RuntimeError("AssemblyAI upload did not return upload_url")
        body: dict[str, Any] = {"audio_url": upload_url, "speech_models": [self.model]}
        if self.language:
            body["language_code"] = self.language.split("-")[0]
        if self.variant == "speaker-labels":
            body["speaker_labels"] = True
        body.update(self.extra if isinstance(self.extra, dict) else {})
        transcript_raw = http_request(
            base + "/v2/transcript",
            method="POST",
            body=json.dumps(body).encode("utf-8"),
            headers={**headers, "Content-Type": "application/json"},
        )
        transcript_id = json.loads(transcript_raw.decode("utf-8", errors="replace")).get("id")
        if not transcript_id:
            raise RuntimeError("AssemblyAI transcript did not return id")
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline and not self._cancel_event.is_set():
            time.sleep(1.25)
            poll_raw = http_request(base + f"/v2/transcript/{transcript_id}", headers=headers)
            data = json.loads(poll_raw.decode("utf-8", errors="replace"))
            status = str(data.get("status", "")).lower()
            if status == "completed":
                return extract_text(data)
            if status == "error":
                raise RuntimeError(str(data.get("error") or "AssemblyAI transcription failed"))
        raise TimeoutError("AssemblyAI transcription timed out")

    def _transcribe_deepgram_batch(self, wav_bytes: bytes) -> str:
        # Pre-recorded lane for Deepgram, used by meeting mode and transcribe_pcm.
        base = self.api_base or "https://api.deepgram.com"
        params: dict[str, str] = {"model": self.model or "nova-3", "smart_format": "true", "punctuate": "true"}
        if self.language:
            params["language"] = self.language
        raw = http_request(
            base + "/v1/listen?" + urlencode(params),
            method="POST",
            body=wav_bytes,
            headers={"Authorization": f"Token {self.api_key}", "Content-Type": "audio/wav"},
        )
        data = json.loads(raw.decode("utf-8", errors="replace"))
        return extract_text(data)

    def _transcribe_local(self, wav_bytes: bytes, *, record: bool = True) -> str:
        """`record=False` for the live caption tail: a rolling guess at a
        half-said word is not evidence about the words that land."""
        from . import local_stt
        # X-405: transcribe the bytes this call was handed. This used to read
        # the whole buffer whatever it was given, so every progressive
        # segment carried the entire take so far and the release joined the
        # same sentences several times over.
        pcm16 = pcm16_from_wav(wav_bytes) if wav_bytes else b""
        if not pcm16:
            pcm16 = bytes(self._audio)

        heard: dict[str, float] | None = {} if record else None
        text = local_stt.transcribe(
            model_id=self.model,
            pcm16=pcm16,
            sample_rate=self.sample_rate,
            channels=self.channels,
            language=self.language,
            gpu=local_stt.gpu_default(self.extra),
            task="translate" if self.extra.get("translate") else "",
            status_cb=self._safe_status,
            vocabulary=self.recognition_vocabulary,
            word_confidence=heard,
        )
        if heard:
            with self._confidence_lock:
                for word, value in heard.items():
                    self.word_confidence[word] = min(value, self.word_confidence.get(word, value))
        return text

    def _transcribe_gemini(self, wav_bytes: bytes) -> str:
        base = self.api_base or "https://generativelanguage.googleapis.com"
        query = urlencode({"key": self.api_key})
        url = f"{base}/v1beta/models/{self.model}:generateContent?{query}"
        prompt = str(
            self.extra.get(
                "prompt",
                "Transcribe this audio exactly. Return only the spoken text, with punctuation and clean formatting.",
            )
        )
        body = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": prompt},
                        {"inline_data": {"mime_type": "audio/wav", "data": base64.b64encode(wav_bytes).decode("ascii")}},
                    ],
                }
            ]
        }
        raw = http_request(
            url,
            method="POST",
            body=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        data = json.loads(raw.decode("utf-8", errors="replace"))
        return extract_text(data)

    def _finish(self, text: str) -> None:
        if self._done_called or self._cancel_event.is_set():
            return
        self._done_called = True
        with contextlib.suppress(Exception):
            self.on_done(text.strip())

    def _safe_update(self, text: str, is_final: bool) -> None:
        with contextlib.suppress(Exception):
            self.on_update(text, is_final)

    def _safe_status(self, status: str) -> None:
        with contextlib.suppress(Exception):
            self.on_status(status)

    def _safe_level(self, level: float) -> None:
        with contextlib.suppress(Exception):
            self.on_level(level)

    def _safe_error(self, error: str) -> None:
        with contextlib.suppress(Exception):
            self.on_error(error)

    def _safe_audio(
        self,
        data: bytes,
        sample_rate: int,
        channels: int,
        heard_voice: bool,
    ) -> None:
        if self.on_audio is None:
            return
        with contextlib.suppress(Exception):
            self.on_audio(data, sample_rate, channels, heard_voice)


def selected_stt_api_key(config: dict[str, Any], provider_id: str) -> str:
    settings = provider_settings(config, provider_id)
    provider = PROVIDER_BY_ID[provider_id]
    value = str(settings.get("api_key", "")).strip()
    if value:
        return value
    if provider_id == "deepgram":
        value = str(config.get("deepgram", {}).get("api_key", "")).strip()
        if value:
            return value
    return os.environ.get(provider.env_key, "").strip() if provider.env_key else ""


def create_stt_session(
    *,
    config: dict[str, Any],
    max_seconds: int,
    no_speech_timeout_seconds: int,
    silence_timeout_seconds: int,
    tail_capture_ms: int,
    min_capture_ms: int,
    on_update: UpdateCallback,
    on_status: StatusCallback,
    on_level: LevelCallback,
    on_done: DoneCallback,
    on_error: ErrorCallback,
    on_audio: AudioCallback | None = None,
) -> Any:
    provider_id = selected_provider_id(config)
    provider = PROVIDER_BY_ID[provider_id]
    settings = provider_settings(config, provider_id)
    api_key = selected_stt_api_key(config, provider_id)
    model = selected_model_id(config, provider_id)
    variant = selected_variant(config, provider_id)

    input_device = resolve_input_device(config.get("audio", {}).get("input_device", ""))
    gain = effective_gain(config)

    if provider.api_kind == "deepgram_stream":
        params = deepgram_params(config)
        params["model"] = model
        return DeepgramLiveSession(
            api_key=api_key,
            params=params,
            max_seconds=max_seconds,
            no_speech_timeout_seconds=no_speech_timeout_seconds,
            silence_timeout_seconds=silence_timeout_seconds,
            tail_capture_ms=tail_capture_ms,
            min_capture_ms=min_capture_ms,
            input_device=input_device,
            gain=gain,
            on_update=on_update,
            on_status=on_status,
            on_level=on_level,
            on_done=on_done,
            on_error=on_error,
            on_audio=on_audio,
        )

    if provider.api_kind == "external":
        details = provider.notes or "This provider needs a dedicated adapter before it can run inside Talk DAT!."
        raise NotImplementedError(f"{provider.label}: {details}")

    dg = config.get("deepgram", {})
    extra = settings.get("extra", {})
    if not isinstance(extra, dict):
        extra = {}
    extra = dict(extra)
    # X-435: every session carries the config, not only the cloud one. The
    # local live-captions gate (X-416, live_captions_wanted) reads
    # extra["config"]["stt"]["local_live_captions"], and with the config
    # handed to the cloud session alone the local route always saw None:
    # the toggle in Settings > Voice never did anything in the real app,
    # while the unit tests, which pass the config straight to the session,
    # stayed green. Seen in the film trace on 2026-09-04.
    extra["config"] = config
    return BatchSTTSession(
        provider_id=provider_id,
        api_key=api_key,
        api_base=str(settings.get("api_base") or provider.api_base),
        model=model,
        variant=variant,
        language=str(settings.get("language") or dg.get("language", "en-US")),
        sample_rate=int(settings.get("sample_rate") or dg.get("sample_rate", 16000)),
        channels=int(settings.get("channels") or dg.get("channels", 1)),
        max_seconds=max_seconds,
        no_speech_timeout_seconds=no_speech_timeout_seconds,
        silence_timeout_seconds=silence_timeout_seconds,
        tail_capture_ms=tail_capture_ms,
        min_capture_ms=min_capture_ms,
        extra=extra,
        input_device=input_device,
        gain=gain,
        on_update=on_update,
        on_status=on_status,
        on_level=on_level,
        on_done=on_done,
        on_error=on_error,
        on_audio=on_audio,
    )


def transcribe_pcm(
    config: dict[str, Any],
    pcm16: bytes,
    sample_rate: int,
    channels: int,
    *,
    provider_id: str = "",
) -> str:
    """One-shot transcription of already-captured PCM16 audio (meeting mode, tests).

    `provider_id` overrides what the config selects. That exists for the local
    rescue path: when a cloud provider has just failed, retrying it is the one
    thing guaranteed not to work, and the caller already knows which provider to
    use instead.
    """
    provider_id = str(provider_id).strip() or selected_provider_id(config)
    provider = PROVIDER_BY_ID[provider_id]
    if provider.api_kind == "external":
        raise NotImplementedError(f"{provider.label} has no wired adapter yet.")
    settings = provider_settings(config, provider_id)
    extra = settings.get("extra", {})
    if not isinstance(extra, dict):
        extra = {}
    extra = dict(extra)
    # X-435: every session carries the config, not only the cloud one. The
    # local live-captions gate (X-416, live_captions_wanted) reads
    # extra["config"]["stt"]["local_live_captions"], and with the config
    # handed to the cloud session alone the local route always saw None:
    # the toggle in Settings > Voice never did anything in the real app,
    # while the unit tests, which pass the config straight to the session,
    # stayed green. Seen in the film trace on 2026-09-04.
    extra["config"] = config
    noop = lambda *args, **kwargs: None  # noqa: E731
    session = BatchSTTSession(
        provider_id=provider_id,
        api_key=selected_stt_api_key(config, provider_id),
        api_base=str(settings.get("api_base") or provider.api_base),
        model=selected_model_id(config, provider_id),
        variant=selected_variant(config, provider_id),
        language=str(settings.get("language") or config.get("deepgram", {}).get("language", "en-US")),
        sample_rate=sample_rate,
        channels=channels,
        max_seconds=0,
        no_speech_timeout_seconds=0,
        silence_timeout_seconds=0,
        tail_capture_ms=0,
        min_capture_ms=0,
        extra=extra if isinstance(extra, dict) else {},
        on_update=noop,
        on_status=noop,
        on_level=noop,
        on_done=noop,
        on_error=noop,
    )
    session._audio = bytearray(pcm16)
    return session._transcribe(session._wav_bytes(pcm16)).strip()


def multipart_form(fields: dict[str, str], files: dict[str, tuple[str, bytes, str]]) -> tuple[bytes, str]:
    boundary = f"talkdat-{int(time.time() * 1000)}"
    parts: list[bytes] = []
    for key, value in fields.items():
        parts.append(f"--{boundary}\r\n".encode("ascii"))
        parts.append(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8"))
        parts.append(str(value).encode("utf-8"))
        parts.append(b"\r\n")
    for key, (filename, content, content_type) in files.items():
        parts.append(f"--{boundary}\r\n".encode("ascii"))
        parts.append(
            f'Content-Disposition: form-data; name="{key}"; filename="{filename}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n".encode("utf-8")
        )
        parts.append(content)
        parts.append(b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode("ascii"))
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


RETRYABLE_HTTP_CODES = {408, 429, 500, 502, 503, 504}


def http_request(
    url: str,
    *,
    method: str = "GET",
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 90.0,
    retries: int = 2,
) -> bytes:
    last_error: Exception | None = None
    for attempt in range(max(1, retries + 1)):
        if attempt:
            time.sleep(min(8.0, 0.8 * (2 ** (attempt - 1))))
        request = Request(url, data=body, headers=headers or {}, method=method)
        try:
            with urlopen(request, timeout=timeout) as response:
                return response.read()
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:800]
            last_error = RuntimeError(f"HTTP {exc.code}: {detail}")
            last_error.__cause__ = exc
            if exc.code not in RETRYABLE_HTTP_CODES:
                raise last_error
        except URLError as exc:
            last_error = RuntimeError(str(exc.reason))
            last_error.__cause__ = exc
    raise last_error if last_error else RuntimeError("request failed")


def extract_text(data: Any) -> str:
    if isinstance(data, str):
        return data
    if not isinstance(data, dict):
        return ""
    if isinstance(data.get("text"), str):
        return str(data["text"])
    if isinstance(data.get("transcript"), str):
        return str(data["transcript"])
    if isinstance(data.get("transcription"), str):
        return str(data["transcription"])
    segments = data.get("segments")
    if isinstance(segments, list):
        texts = [
            str(segment["text"]).strip()
            for segment in segments
            if isinstance(segment, dict) and isinstance(segment.get("text"), str)
        ]
        if texts:
            return " ".join(text for text in texts if text)
    channel = data.get("channel")
    if isinstance(channel, dict):
        alternatives = channel.get("alternatives")
        if isinstance(alternatives, list) and alternatives:
            transcript = alternatives[0].get("transcript") if isinstance(alternatives[0], dict) else None
            if isinstance(transcript, str):
                return transcript
    results = data.get("results")
    if isinstance(results, dict):
        channels = results.get("channels")
        if isinstance(channels, list) and channels and isinstance(channels[0], dict):
            alternatives = channels[0].get("alternatives")
            if isinstance(alternatives, list) and alternatives and isinstance(alternatives[0], dict):
                transcript = alternatives[0].get("transcript")
                if isinstance(transcript, str):
                    return transcript
    candidates = data.get("candidates")
    if isinstance(candidates, list):
        texts: list[str] = []
        for candidate in candidates:
            content = candidate.get("content") if isinstance(candidate, dict) else None
            parts = content.get("parts") if isinstance(content, dict) else None
            if isinstance(parts, list):
                for part in parts:
                    text = part.get("text") if isinstance(part, dict) else None
                    if isinstance(text, str):
                        texts.append(text)
        if texts:
            return "\n".join(texts)
    return ""
