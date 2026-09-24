"""Shared microphone input helpers: device selection and gain staging."""

from __future__ import annotations

import math
import logging
import threading
import os
import sys
import time
from array import array
from collections.abc import Callable
from typing import Any

log = logging.getLogger(__name__)


LOW_CONFIDENCE_INPUT_NAME_PARTS = (
    "dualsense",
    "controller",
    "oculus",
    "virtual",
    "webcam",
    "ndi webcam",
    "ivcam",
    "loop-back",
    "loopback",
    "stereo mix",
    "sound mapper",
    "primary sound capture",
)


def warm_audio_input_backend() -> float:
    """Initialize PortAudio before hotkeys can begin a recording.

    Importing sounddevice is expensive on some Windows systems. Doing that work
    on the first key press loses the beginning of the first dictation.
    """
    started = time.perf_counter()
    import sounddevice as sd

    list(sd.query_devices())
    return max(0.0, (time.perf_counter() - started) * 1000.0)


def low_confidence_input_name(name: str) -> bool:
    lower = str(name or "").lower()
    return any(part in lower for part in LOW_CONFIDENCE_INPUT_NAME_PARTS)


def _input_device_index(devices: list[Any], index: int) -> int | None:
    if index < 0 or index >= len(devices):
        return None
    try:
        return index if int(devices[index].get("max_input_channels", 0)) > 0 else None
    except (AttributeError, TypeError, ValueError):
        return None


def _device_name(device: Any) -> str:
    try:
        return str(device.get("name", "")).strip()
    except AttributeError:
        return ""


def resolve_input_device(setting: Any) -> int | None:
    """Map the audio.input_device config value to a sounddevice device index.

    Accepts an empty value (system default), a numeric index, or a case-insensitive
    name substring. Returns None for the default device or when no valid match exists.
    """
    raw = str(setting or "").strip()
    if not raw:
        return None
    preferred_index: int | None = None
    preferred_name = ""
    if ":" in raw:
        prefix, _separator, suffix = raw.partition(":")
        if prefix.strip().lstrip("-").isdigit():
            preferred_index = int(prefix.strip())
            preferred_name = suffix.strip().lower()
    try:
        import sounddevice as sd

        devices = list(sd.query_devices())
        if preferred_index is not None:
            matched_index = _input_device_index(devices, preferred_index)
            if matched_index is not None:
                current_name = _device_name(devices[matched_index]).lower()
                if not preferred_name or preferred_name in current_name or current_name in preferred_name:
                    return matched_index
            if preferred_name:
                for index, device in enumerate(devices):
                    if device.get("max_input_channels", 0) <= 0:
                        continue
                    current_name = _device_name(device).lower()
                    if preferred_name in current_name or current_name in preferred_name:
                        return index
            return None
        if raw.lstrip("-").isdigit():
            return _input_device_index(devices, int(raw))
        for index, device in enumerate(devices):
            if device.get("max_input_channels", 0) > 0 and raw.lower() in _device_name(device).lower():
                return index
    except Exception:
        if raw.lstrip("-").isdigit():
            return int(raw)
        return None
    return None


def list_input_devices() -> list[str]:
    try:
        import sounddevice as sd

        return [
            f"{index}: {device.get('name', '?')}"
            for index, device in enumerate(sd.query_devices())
            if device.get("max_input_channels", 0) > 0
        ]
    except Exception:
        return []


def _sounddevice_default_input(sd: Any) -> int | None:
    try:
        default = sd.default.device
        if isinstance(default, (list, tuple)) and default:
            value = default[0]
        else:
            value = getattr(default, "input", None)
        if value is None:
            return None
        return int(value)
    except Exception:
        return None


def _device_info(sd: Any, device: int | None) -> Any:
    if device is None:
        try:
            return sd.query_devices(kind="input")
        except Exception:
            default = _sounddevice_default_input(sd)
            if default is not None:
                return sd.query_devices(default)
            raise
    return sd.query_devices(device)


def _device_default_sample_rate(sd: Any, device: int | None, requested: int) -> int:
    try:
        info = _device_info(sd, device)
        rate = int(float(info.get("default_samplerate", 0) or 0))
        if rate > 0:
            return rate
    except Exception:
        pass
    return requested


def _candidate_rates(sd: Any, device: int | None, requested: int) -> list[int]:
    rates: list[int] = []
    for rate in (requested, _device_default_sample_rate(sd, device, requested), 48000, 44100, 32000, 16000):
        try:
            clean = int(rate)
        except (TypeError, ValueError):
            continue
        if clean > 0 and clean not in rates:
            rates.append(clean)
    return rates


def _available_input_devices(sd: Any) -> list[tuple[int, Any]]:
    try:
        devices = sd.query_devices()
    except Exception:
        return []
    if isinstance(devices, dict):
        return []
    available: list[tuple[int, Any]] = []
    for index, device in enumerate(devices):
        try:
            if int(device.get("max_input_channels", 0)) > 0:
                available.append((index, device))
        except (AttributeError, TypeError, ValueError):
            continue
    return available


def _ranked_device_candidates(sd: Any, preferred: int | None) -> list[int | None]:
    """Prefer physical microphones while retaining the Windows default fallback."""
    inputs = _available_input_devices(sd)
    default_index = _sounddevice_default_input(sd)
    default_name = ""
    for index, device in inputs:
        if index == default_index:
            default_name = _device_name(device)
            break
    default_is_low_confidence = bool(default_name and low_confidence_input_name(default_name))
    high_confidence = [
        index
        for index, device in inputs
        if index != preferred and index != default_index and not low_confidence_input_name(_device_name(device))
    ]
    low_confidence = [
        index
        for index, device in inputs
        if index != preferred and index != default_index and low_confidence_input_name(_device_name(device))
    ]

    candidates: list[int | None] = []

    def add(candidate: int | None) -> None:
        if candidate not in candidates:
            candidates.append(candidate)

    if preferred is not None:
        add(preferred)
    if not default_is_low_confidence:
        add(None)
    for candidate in high_confidence:
        add(candidate)
    if default_is_low_confidence:
        add(None)
    for candidate in low_confidence:
        add(candidate)
    if not candidates:
        add(None)
    return candidates


def input_callback_problem(status: Any) -> str:
    """Return a stable warning when PortAudio reports dropped or failed input."""
    try:
        if not status:
            return ""
    except Exception:
        pass
    message = str(status or "").strip()
    return message or status.__class__.__name__


def input_stream_active(stream: Any) -> bool:
    """Treat an unavailable `active` property as healthy for backend compatibility."""
    try:
        return bool(stream.active)
    except Exception:
        return True




class _WavInputStream:
    """X-398: a microphone fed from a WAV file, for the product film.

    Only reachable when TALK_DAT_MIC_WAV names a 16-bit PCM WAV. It mimics the
    slice of sounddevice.RawInputStream the app touches (start/stop/close/
    abort, `active`, the four-argument callback with bytes) and feeds the
    file at real-time pace, then silence forever, so the app hears a person
    speak and then stop, with no audio hardware involved at all.
    """

    def __init__(self, path: str, channels: int, blocksize: int, callback: Callable[..., None]) -> None:
        import wave

        with wave.open(path, "rb") as source:
            if source.getsampwidth() != 2:
                raise RuntimeError("TALK_DAT_MIC_WAV must be 16-bit PCM.")
            self.samplerate = int(source.getframerate())
            self._source_channels = int(source.getnchannels())
            self._pcm = source.readframes(source.getnframes())
        self.channels = max(1, int(channels))
        self.blocksize = int(blocksize) or 1024
        self._callback = callback
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.active = False

    def _frames(self) -> bytes:
        frame_bytes = 2 * self._source_channels
        total = len(self._pcm) // frame_bytes
        for start in range(0, total, self.blocksize):
            chunk = self._pcm[start * frame_bytes : (start + self.blocksize) * frame_bytes]
            if self._source_channels == 1 and self.channels > 1:
                mono = [chunk[i : i + 2] for i in range(0, len(chunk), 2)]
                chunk = b"".join(sample * self.channels for sample in mono)
            yield chunk
        silence = bytes(self.blocksize * 2 * self.channels)
        while True:
            yield silence

    def _run(self) -> None:
        pace = self.blocksize / float(self.samplerate)
        next_at = time.perf_counter()
        for chunk in self._frames():
            if self._stop.is_set():
                return
            frames = len(chunk) // (2 * self.channels)
            try:
                self._callback(chunk, frames, None, None)
            except Exception:
                log.exception("film microphone callback failed")
                return
            next_at += pace
            delay = next_at - time.perf_counter()
            if delay > 0:
                time.sleep(delay)

    def start(self) -> None:
        if self.active:
            return
        self._stop.clear()
        self.active = True
        self._thread = threading.Thread(target=self._run, name="talk-dat-film-mic", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self.active = False

    def abort(self) -> None:
        self.stop()

    def close(self) -> None:
        self.stop()

    def __enter__(self) -> "_WavInputStream":
        self.start()
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()

def open_raw_input_stream(
    *,
    samplerate: int,
    channels: int,
    dtype: str = "int16",
    blocksize: int = 0,
    device: int | None = None,
    callback: Callable[..., None],
    allow_device_fallback: bool = True,
) -> tuple[Any, int, int, int | None]:
    """Open a Windows mic stream with practical fallbacks.

    Some Windows/driver stacks reject 16 kHz directly even though they record
    perfectly at their native 44.1/48/96 kHz rate. The rest of Talk Dat can
    transcribe any WAV rate, so retrying native rates prevents silent "mic is
    broken" failures on real user machines. Diagnostics can disable device
    fallback while retaining rate fallback, so they test only the chosen input.
    """
    requested_channels = max(1, int(channels))
    film_wav = os.environ.get("TALK_DAT_MIC_WAV", "").strip()
    if film_wav:
        stream = _WavInputStream(film_wav, requested_channels, blocksize, callback)
        log.info("film microphone: %s at %s Hz", film_wav, stream.samplerate)
        return stream, stream.samplerate, requested_channels, None

    import sounddevice as sd

    requested_rate = int(samplerate)
    attempts: list[tuple[int | None, int]] = []
    candidates = _ranked_device_candidates(sd, device) if allow_device_fallback else [device]
    for candidate_device in candidates:
        for rate in _candidate_rates(sd, candidate_device, requested_rate):
            attempt = (candidate_device, rate)
            if attempt not in attempts:
                attempts.append(attempt)

    last_error: Exception | None = None
    for candidate_device, rate in attempts:
        try:
            stream = sd.RawInputStream(
                samplerate=rate,
                channels=requested_channels,
                dtype=dtype,
                blocksize=blocksize,
                device=candidate_device,
                callback=callback,
            )
            if candidate_device != device or rate != requested_rate:
                log.info(
                    "mic stream fallback selected: requested_device=%s actual_device=%s requested_rate=%s actual_rate=%s",
                    device,
                    candidate_device,
                    requested_rate,
                    rate,
                )
            return stream, rate, requested_channels, candidate_device
        except Exception as exc:
            last_error = exc
            log.info(
                "mic stream open failed: device=%s rate=%s channels=%s error=%s",
                candidate_device,
                rate,
                requested_channels,
                exc,
            )
    if last_error is not None:
        raise last_error
    raise RuntimeError("No microphone input stream could be opened.")


def effective_gain(config: dict[str, Any]) -> float:
    audio = config.get("audio", {})
    gain = float(audio.get("gain_boost", 1.0) or 1.0)
    if bool(audio.get("quiet_mode", False)):
        gain *= float(audio.get("quiet_mode_boost", 3.0) or 3.0)
    return max(0.1, min(16.0, gain))


def pcm_rms_level(raw: bytes) -> float:
    """Return a normalized PCM16 RMS level for failure-recovery decisions."""
    if not raw:
        return 0.0
    sample_bytes = raw[: min(len(raw), 16000)]
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


def likely_has_input_signal(raw: bytes, *, threshold: float = 0.0018) -> bool:
    """Detect low but real mic input without treating pure digital silence as speech."""
    return pcm_rms_level(raw) >= threshold


def apply_gain(pcm16: bytes, gain: float) -> bytes:
    if abs(gain - 1.0) < 1e-3 or not pcm16:
        return pcm16
    try:
        import numpy as np

        audio = np.frombuffer(pcm16, dtype=np.int16).astype(np.float32) * gain
        return np.clip(audio, -32768, 32767).astype(np.int16).tobytes()
    except Exception:
        return pcm16


def is_digitally_silent(pcm16: bytes) -> bool:
    """Every sample is exactly zero -- which a working microphone never produces.

    A real input device in a silent room still delivers a noise floor. Samples
    that are all exactly zero mean nothing is being captured at all, and on
    macOS that has one overwhelmingly likely cause: microphone access was
    refused. macOS does not fail the call or raise anything when it refuses --
    it hands over silence, so the recording succeeds, the transcript comes back
    empty, and the app blames the user for not speaking.

    Verified during the macOS port: ten seconds of capture with speech playing
    aloud the whole time returned a peak amplitude of exactly 0.

    Empty input is not silence, it is no input, so it returns False and leaves
    that case to the callers that already handle it.
    """
    if not pcm16:
        return False
    try:
        import numpy as np

        return not np.frombuffer(pcm16, dtype=np.int16).any()
    except Exception:
        return not any(pcm16)
