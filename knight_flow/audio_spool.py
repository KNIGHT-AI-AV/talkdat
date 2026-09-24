from __future__ import annotations

import contextlib
import json
import os
import queue
import struct
import threading
import time
import uuid
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import app_dir


MINIMUM_SAFETY_SESSIONS = 5
_ACTIVE_STATUSES = {"arming", "recording", "finalizing", "processing"}


def audio_spool_dir() -> Path:
    path = app_dir() / "audio-spool"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _session_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    return f"{stamp}-{uuid.uuid4().hex[:8]}"


def _wav_header(data_size: int, sample_rate: int, channels: int) -> bytes:
    channels = max(1, int(channels))
    sample_rate = max(1, int(sample_rate))
    data_size = max(0, int(data_size))
    block_align = channels * 2
    byte_rate = sample_rate * block_align
    return struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + data_size,
        b"WAVE",
        b"fmt ",
        16,
        1,
        channels,
        sample_rate,
        byte_rate,
        block_align,
        16,
        b"data",
        data_size,
    )


def wav_bytes(pcm16: bytes, sample_rate: int, channels: int) -> bytes:
    import io

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(int(channels))
        wav.setsampwidth(2)
        wav.setframerate(int(sample_rate))
        wav.writeframes(pcm16)
    return buffer.getvalue()


def _atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as file:
            json.dump(value, file, ensure_ascii=True, indent=2, sort_keys=True)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        with contextlib.suppress(OSError):
            temporary.unlink()


def _created_timestamp(value: dict[str, Any], fallback: float) -> float:
    try:
        return float(value.get("created_at") or fallback)
    except (TypeError, ValueError):
        return fallback


def repair_wav(path: Path, sample_rate: int = 16000, channels: int = 1) -> int:
    """Repair our PCM16 length fields without replacing the recorded format.

    Metadata can lag the first audio write, and orphan recordings have none.
    The file's format is authoritative. Other valid WAV layouts are left intact;
    their extra chunks must never become samples in a replacement 44-byte header.
    The optional metadata arguments remain accepted for older callers.
    """
    try:
        size = path.stat().st_size
        with path.open("rb") as file:
            header = file.read(44)
    except OSError:
        return 0
    if len(header) < 44:
        return 0
    fields = struct.unpack("<4sI4s4sIHHIIHH4sI", header)
    (
        riff, riff_size, wave_id, fmt, fmt_size, encoding, channels, sample_rate,
        byte_rate, alignment, bits, data, stored_size,
    ) = fields
    canonical = (
        riff == b"RIFF" and wave_id == b"WAVE" and fmt == b"fmt "
        and fmt_size == 16 and encoding == 1 and data == b"data" and bits == 16
        and 1 <= channels <= 32 and 1 <= sample_rate <= 384000
        and alignment == channels * 2 and byte_rate == sample_rate * alignment
    )
    if not canonical:
        try:
            with wave.open(str(path), "rb") as wav:
                return wav.getnframes() * wav.getnchannels() * wav.getsampwidth()
        except (OSError, EOFError, wave.Error):
            return 0
    # A complete file can contain trailing non-audio chunks. It already has a
    # coherent length and needs no rewrite. Incomplete captures instead use the
    # bytes actually written, rounded down to whole sample frames.
    if riff_size == size - 8 and stored_size <= size - 44:
        return stored_size
    data_size = (size - 44) // alignment * alignment
    try:
        with path.open("r+b", buffering=0) as file:
            file.seek(0)
            file.write(_wav_header(data_size, sample_rate, channels))
            file.flush()
            os.fsync(file.fileno())
    except OSError:
        return 0
    return data_size


class AudioSafetyCapture:
    """Durably records one trigger hold independently of STT and text delivery."""

    def __init__(
        self,
        *,
        mode: str,
        control: str,
        provider: str,
        model: str,
        limit: int = MINIMUM_SAFETY_SESSIONS,
    ) -> None:
        self.session_id = _session_id()
        self.root = audio_spool_dir()
        self.audio_path = self.root / f"{self.session_id}.wav"
        self.metadata_path = self.root / f"{self.session_id}.json"
        self.limit = max(MINIMUM_SAFETY_SESSIONS, int(limit or MINIMUM_SAFETY_SESSIONS))
        self._queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._metadata_lock = threading.RLock()
        self._closed = threading.Event()
        self._bytes_written = 0
        self._sample_rate = 16000
        self._channels = 1
        self._heard_voice = False
        now = time.time()
        self._metadata: dict[str, Any] = {
            "schema": 1,
            "session_id": self.session_id,
            "created_at": now,
            "updated_at": now,
            "mode": str(mode or "dictation"),
            "control": str(control or "hold"),
            "provider": str(provider or ""),
            "model": str(model or ""),
            "status": "arming",
            "audio_file": self.audio_path.name,
            "audio_bytes": 0,
            "duration_ms": 0,
            "sample_rate": self._sample_rate,
            "channels": self._channels,
            "heard_voice": False,
            "raw_transcript": "",
            "final_text": "",
            "error": "",
        }
        self._write_metadata()
        self._thread = threading.Thread(
            target=self._writer_main,
            name=f"TalkDatAudioSafety-{self.session_id[-8:]}",
            daemon=True,
        )
        self._thread.start()

    @property
    def audio_bytes(self) -> int:
        return self._bytes_written

    def append(self, pcm16: bytes, sample_rate: int, channels: int, *, heard_voice: bool = False) -> bool:
        if self._closed.is_set() or not pcm16:
            return False
        self._queue.put(
            (
                "audio",
                (bytes(pcm16), max(1, int(sample_rate)), max(1, int(channels)), bool(heard_voice)),
            )
        )
        return True

    def update(self, **changes: Any) -> None:
        with self._metadata_lock:
            self._metadata.update({key: value for key, value in changes.items() if value is not None})
            self._metadata["updated_at"] = time.time()
            self._write_metadata_locked()

    def flush(self, timeout: float = 3.0) -> bool:
        if self._closed.is_set():
            return True
        completed = threading.Event()
        self._queue.put(("flush", completed))
        return completed.wait(max(0.05, timeout))

    def finalize(
        self,
        *,
        status: str,
        raw_transcript: str = "",
        final_text: str = "",
        error: str = "",
        delivery: dict[str, Any] | None = None,
        heard_voice: bool | None = None,
    ) -> dict[str, Any]:
        if not self._closed.is_set():
            self.update(
                status="finalizing",
                raw_transcript=str(raw_transcript or ""),
                final_text=str(final_text or ""),
                error=str(error or ""),
                delivery=delivery,
                heard_voice=heard_voice,
            )
            completed = threading.Event()
            self._queue.put(("close", completed))
            completed.wait(5.0)
            self._closed.set()
        self.update(
            status=str(status or "complete"),
            raw_transcript=str(raw_transcript or ""),
            final_text=str(final_text or ""),
            error=str(error or ""),
            delivery=delivery,
            heard_voice=heard_voice,
        )
        rotate_safety_recordings(limit=self.limit)
        return self.snapshot()

    def snapshot(self) -> dict[str, Any]:
        with self._metadata_lock:
            return dict(self._metadata)

    def _writer_main(self) -> None:
        file = None
        last_sync = time.monotonic()
        try:
            while True:
                action, payload = self._queue.get()
                if action == "audio":
                    pcm16, sample_rate, channels, heard_voice = payload
                    first_chunk = file is None
                    if file is None:
                        self._sample_rate = sample_rate
                        self._channels = channels
                        file = self.audio_path.open("w+b", buffering=0)
                        file.write(_wav_header(0, sample_rate, channels))
                    file.seek(0, os.SEEK_END)
                    file.write(pcm16)
                    self._bytes_written += len(pcm16)
                    self._heard_voice = self._heard_voice or bool(heard_voice)
                    self._patch_header(file)
                    should_sync = time.monotonic() - last_sync >= 0.5
                    if first_chunk or should_sync:
                        file.flush()
                        os.fsync(file.fileno())
                        last_sync = time.monotonic()
                        self._checkpoint_metadata()
                    continue
                if action == "flush":
                    if file is not None:
                        self._patch_header(file)
                        file.flush()
                        os.fsync(file.fileno())
                    self._checkpoint_metadata()
                    payload.set()
                    continue
                if action == "close":
                    if file is not None:
                        self._patch_header(file)
                        file.flush()
                        os.fsync(file.fileno())
                    self._checkpoint_metadata()
                    payload.set()
                    break
        except Exception as exc:
            self.update(status="recording_error", error=f"Local safety writer failed: {exc}")
        finally:
            if file is not None:
                with contextlib.suppress(OSError):
                    file.close()
            self._closed.set()

    def _patch_header(self, file: Any) -> None:
        file.seek(0)
        file.write(_wav_header(self._bytes_written, self._sample_rate, self._channels))
        file.seek(0, os.SEEK_END)

    def _checkpoint_metadata(self) -> None:
        duration_ms = int(
            round(self._bytes_written / max(1, self._sample_rate * self._channels * 2) * 1000)
        )
        with self._metadata_lock:
            self._metadata.update(
                {
                    "status": "recording",
                    "updated_at": time.time(),
                    "audio_bytes": self._bytes_written,
                    "duration_ms": duration_ms,
                    "sample_rate": self._sample_rate,
                    "channels": self._channels,
                    "heard_voice": bool(self._metadata.get("heard_voice")) or self._heard_voice,
                }
            )
            self._write_metadata_locked()

    def _write_metadata(self) -> None:
        with self._metadata_lock:
            self._write_metadata_locked()

    def _write_metadata_locked(self) -> None:
        _atomic_write_json(self.metadata_path, self._metadata)


def start_safety_capture(
    *,
    mode: str,
    control: str,
    provider: str,
    model: str,
    limit: int = MINIMUM_SAFETY_SESSIONS,
) -> AudioSafetyCapture:
    return AudioSafetyCapture(
        mode=mode,
        control=control,
        provider=provider,
        model=model,
        limit=max(MINIMUM_SAFETY_SESSIONS, int(limit or MINIMUM_SAFETY_SESSIONS)),
    )


def save_safety_recording(
    pcm16: bytes,
    *,
    sample_rate: int,
    channels: int,
    reason: str = "capture",
    limit: int = MINIMUM_SAFETY_SESSIONS,
) -> Path | None:
    if len(pcm16) < 1024:
        return None
    capture = start_safety_capture(
        mode=reason,
        control="legacy",
        provider="",
        model="",
        limit=limit,
    )
    capture.append(pcm16, sample_rate, channels, heard_voice=True)
    capture.finalize(status=reason, heard_voice=True)
    return capture.audio_path if capture.audio_path.exists() else None


def list_safety_sessions(limit: int = MINIMUM_SAFETY_SESSIONS) -> list[dict[str, Any]]:
    root = audio_spool_dir()
    sessions: list[dict[str, Any]] = []
    described_audio: set[str] = set()
    for metadata_path in root.glob("*.json"):
        try:
            value = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(value, dict):
            continue
        audio_name = str(value.get("audio_file") or f"{metadata_path.stem}.wav")
        audio_path = root / Path(audio_name).name
        value["metadata_path"] = str(metadata_path)
        value["audio_path"] = str(audio_path)
        value["has_audio"] = audio_path.exists() and audio_path.stat().st_size > 44
        value["_sort_at"] = _created_timestamp(value, metadata_path.stat().st_mtime)
        sessions.append(value)
        described_audio.add(audio_path.name.lower())

    for audio_path in root.glob("*.wav"):
        if audio_path.name.lower() in described_audio:
            continue
        sessions.append(
            {
                "schema": 0,
                "session_id": audio_path.stem,
                "created_at": audio_path.stat().st_mtime,
                "updated_at": audio_path.stat().st_mtime,
                "status": "legacy_recording",
                "audio_file": audio_path.name,
                "audio_path": str(audio_path),
                "has_audio": audio_path.stat().st_size > 44,
                "raw_transcript": "",
                "final_text": "",
                "_sort_at": audio_path.stat().st_mtime,
            }
        )
    sessions.sort(key=lambda item: float(item.get("_sort_at") or 0), reverse=True)
    for item in sessions:
        item.pop("_sort_at", None)
    return sessions[: max(1, int(limit))]


def safety_session(session_id: str) -> dict[str, Any] | None:
    target = str(session_id or "").strip()
    if not target:
        return None
    return next((item for item in list_safety_sessions(1000) if item.get("session_id") == target), None)


def update_safety_session(session_id: str, **changes: Any) -> dict[str, Any] | None:
    item = safety_session(session_id)
    if item is None:
        return None
    metadata_path = Path(str(item.get("metadata_path") or ""))
    if not metadata_path.exists():
        return item
    persisted = {
        key: value
        for key, value in item.items()
        if key not in {"metadata_path", "audio_path", "has_audio"}
    }
    persisted.update({key: value for key, value in changes.items() if value is not None})
    persisted["updated_at"] = time.time()
    _atomic_write_json(metadata_path, persisted)
    return safety_session(session_id)


def read_safety_audio(session_id: str) -> tuple[bytes, int, int]:
    item = safety_session(session_id)
    if item is None:
        raise FileNotFoundError(f"Protected voice session not found: {session_id}")
    path = Path(str(item.get("audio_path") or ""))
    if not path.exists():
        raise FileNotFoundError(f"Protected audio is unavailable: {session_id}")
    repair_wav(path)
    with wave.open(str(path), "rb") as wav:
        channels = wav.getnchannels()
        sample_rate = wav.getframerate()
        pcm16 = wav.readframes(wav.getnframes())
    return pcm16, sample_rate, channels


def recover_interrupted_sessions(*, limit: int = MINIMUM_SAFETY_SESSIONS) -> int:
    recovered = 0
    for item in list_safety_sessions(1000):
        if str(item.get("status") or "") not in _ACTIVE_STATUSES:
            continue
        path = Path(str(item.get("audio_path") or ""))
        data_size = repair_wav(path)
        sample_rate, channels = 16000, 1
        with contextlib.suppress(OSError, EOFError, wave.Error):
            with wave.open(str(path), "rb") as wav:
                sample_rate = wav.getframerate()
                channels = wav.getnchannels()
        duration_ms = int(
            round(
                data_size
                / max(1, sample_rate * channels * 2)
                * 1000
            )
        )
        update_safety_session(
            str(item.get("session_id") or ""),
            status="interrupted",
            error=str(item.get("error") or "Talk DAT! closed before this voice session completed."),
            audio_bytes=data_size,
            duration_ms=duration_ms,
            sample_rate=sample_rate,
            channels=channels,
        )
        recovered += 1
    rotate_safety_recordings(limit=limit)
    return recovered


def rotate_safety_recordings(*, limit: int = MINIMUM_SAFETY_SESSIONS) -> None:
    keep = max(MINIMUM_SAFETY_SESSIONS, int(limit or MINIMUM_SAFETY_SESSIONS))
    root = audio_spool_dir()
    sessions = list_safety_sessions(1000)
    for item in sessions[keep:]:
        if str(item.get("status") or "") in _ACTIVE_STATUSES:
            continue
        for key in ("audio_path", "metadata_path"):
            value = str(item.get(key) or "")
            if value:
                with contextlib.suppress(OSError):
                    Path(value).unlink()
        if not item.get("metadata_path"):
            with contextlib.suppress(OSError):
                (root / str(item.get("audio_file") or "")).unlink()


def clear_safety_recordings() -> int:
    removed = 0
    root = audio_spool_dir()
    for pattern in ("*.wav", "*.json"):
        for path in root.glob(pattern):
            with contextlib.suppress(OSError):
                path.unlink()
                if pattern == "*.wav":
                    removed += 1
    return removed
