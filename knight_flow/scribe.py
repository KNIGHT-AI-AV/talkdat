"""Scribe audio tracks, bounded conversion and preserved meeting notes."""
from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass
from pathlib import Path

CHUNK_SECONDS = 30


@dataclass(frozen=True)
class Chunk:
    speaker: str      # "You" | "Them"
    start: float      # seconds from session start
    text: str


def merge_turns(chunks: list[Chunk], *, gap: float = 1.0) -> list[tuple[str, str]]:
    """Interleave both tracks by time into readable turns.

    Consecutive same-speaker chunks fuse into one turn; empty chunks vanish;
    ordering is by start time so cross-talk lands where it happened. The
    result is what a person would have typed: You: ... / Them: ...
    """
    ordered = sorted(
        (chunk for chunk in chunks if chunk.text.strip()),
        key=lambda chunk: (chunk.start, 0 if chunk.speaker == "You" else 1),
    )
    turns: list[tuple[str, str]] = []
    for chunk in ordered:
        text = " ".join(chunk.text.split())
        if turns and turns[-1][0] == chunk.speaker:
            turns[-1] = (chunk.speaker, f"{turns[-1][1]} {text}")
        else:
            turns.append((chunk.speaker, text))
    return turns


def heuristic_summary(turns: list[tuple[str, str]], *, max_points: int = 6) -> list[str]:
    """The offline summary: decision-shaped sentences first, then openers.

    Extractive selected lines preserve the original wording. They are not
    an AI-generated summary or an identification of individual speakers.
    """
    if max_points <= 0:
        return []
    sentences: list[tuple[int, str]] = []
    decision_words = re.compile(
        r"\b(?:will|agreed|decide|decided|deadline|due|next step|action|send|ship|schedule|by (?:monday|tuesday|wednesday|thursday|friday|tomorrow))\b",
        re.IGNORECASE,
    )
    for _speaker, text in turns:
        for sentence in re.split(r"(?<=[.!?])\s+", text):
            sentence = sentence.strip()
            words = len(sentence.split())
            if words < 4 or words > 40:
                continue
            score = 2 if decision_words.search(sentence) else 0
            sentences.append((score, sentence))
    sentences.sort(key=lambda item: -item[0])
    seen: set[str] = set()
    points: list[str] = []
    for score, sentence in sentences:
        key = sentence.casefold()
        if key in seen:
            continue
        seen.add(key)
        points.append(sentence)
        if len(points) >= max_points:
            break
    return points


def render_notes(
    turns: list[tuple[str, str]],
    summary: list[str],
    when: _dt.datetime,
    *,
    title: str = "",
) -> str:
    """The Markdown document: summary up top, raw two-sided transcript below."""
    heading = title.strip() or f"Notes, {when:%B %d, %Y}"
    lines = [f"# {heading}", "", f"*Taken by Talk DAT! Scribe, {when:%B %d, %Y at %H:%M}*", ""]
    if summary:
        lines.append("## Summary")
        lines.extend(f"- {point}" for point in summary)
        lines.append("")
    lines.append("## Transcript")
    for speaker, text in turns:
        lines.append(f"**{speaker}:** {text}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def notes_folder() -> Path:
    return Path.home() / "Documents" / "Talk DAT! Notes"


def save_notes(turns: list[tuple[str, str]], summary: list[str], when: _dt.datetime | None = None) -> Path:
    when = when or _dt.datetime.now()
    body = render_notes(turns, summary, when)
    folder = notes_folder()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{when:%Y-%m-%d %H.%M} notes.md"
    from .export_files import save_new_export
    return save_new_export(folder, path.name, body.encode("utf-8"))

class ScribeRecorder:
    """Own explicit input tracks until close; spool on one bounded worker."""

    QUEUE_BLOCKS = 128
    MAX_BLOCK_BYTES = 65536
    MAX_TRACK_BYTES = 4_000_000_000

    def __init__(self, config=None) -> None:
        import copy, queue, tempfile, threading
        from .config import app_dir

        self.config = copy.deepcopy(config or {})
        root = app_dir() / 'scribe-recordings'
        root.mkdir(parents=True, exist_ok=True)
        self.folder = Path(tempfile.mkdtemp(prefix='recording-', dir=root))
        self.streams = []
        self.wavs = {}
        self.rates = {}
        self.channels = {}
        self.offsets = {}
        self.written_bytes = {}
        self.errors = []
        self.started_at = 0.0
        self._token = None
        self._started = False
        self._worker = None
        self._worker_lock = threading.Lock()
        self._queue = queue.Queue(maxsize=self.QUEUE_BLOCKS)
        self._stop_event = threading.Event()
        self._ready = threading.Event()
        self.closed = threading.Event()

    def _problem(self, message):
        # Messages are a small fixed vocabulary, never device/provider details.
        if message not in self.errors:
            self.errors.append(message)
        self._stop_event.set()

    def _receiver(self, name):
        import queue, time

        def receive(data, frames, timing, status):
            if self._stop_event.is_set():
                return
            if status:
                self._problem('The audio device reported an interruption. Part of the recording may be missing.')
                return
            raw = bytes(data)
            if not raw:
                return
            alignment = self.channels[name] * 2
            if len(raw) > self.MAX_BLOCK_BYTES or len(raw) % alignment:
                self._problem('The audio device returned an unsupported block. Recording stopped.')
                return
            if name not in self.offsets:
                self.offsets[name] = max(0.0, time.monotonic() - self.started_at)
            try:
                self._queue.put_nowait((name, raw))
            except queue.Full:
                self._problem('Audio arrived faster than it could be saved. Recording stopped; the saved portion is kept.')
        return receive

    def _manifest(self):
        from .audio_spool import _atomic_write_json
        _atomic_write_json(self.folder / 'recording.json', {
            'version': 1, 'source': self.config.get('scribe', {}).get('source', 'both'),
            'rates': dict(self.rates), 'channels': dict(self.channels),
            'offsets': dict(self.offsets), 'written_bytes': dict(self.written_bytes),
            'errors': list(self.errors), 'closed': self.closed.is_set(),
        })

    def start(self) -> None:
        import threading, time, wave
        from .audio_input import open_raw_input_stream, resolve_input_device
        from .mic_registry import microphone_registry, MEETING
        from .system_audio import open_loopback_stream

        with self._worker_lock:
            if self._started or self.closed.is_set() or self._stop_event.is_set():
                raise RuntimeError('This recording already started. Finish it before starting another.')
            source = self.config.get('scribe', {}).get('source', 'both')
            if source not in {'microphone', 'system', 'both'}:
                raise ValueError('Choose microphone, system audio or both.')
            self._started = True
            self._token = microphone_registry().acquire(MEETING, device=source, phase='starting', stop=self.request_stop)

            def keep(name, stream, rate, channels):
                self.streams.append(stream)
                self.rates[name], self.channels[name] = int(rate), int(channels)
                handle = wave.open(str(self.folder / (name + '.wav')), 'wb')
                self.wavs[name] = handle
                handle.setnchannels(int(channels))
                handle.setsampwidth(2)
                handle.setframerate(int(rate))
                handle.writeframes(b'')
                self.written_bytes[name] = 0

            try:
                if source in {'microphone', 'both'}:
                    chosen = str(self.config.get('audio', {}).get('input_device', '') or '')
                    device = resolve_input_device(chosen)
                    if chosen and device is None:
                        raise RuntimeError('The selected microphone is unavailable. Reconnect it or choose another input.')
                    stream, rate, channels, _ = open_raw_input_stream(
                        samplerate=16000, channels=1, device=device,
                        callback=self._receiver('you'), allow_device_fallback=False)
                    keep('you', stream, rate, channels)
                if source in {'system', 'both'}:
                    stream = open_loopback_stream(self._receiver('them'))
                    keep('them', stream, stream.samplerate, stream.channels)
                self._manifest()
                self._worker = threading.Thread(target=self._spool, name='TalkDatScribeAudio', daemon=True)
                self._worker.start()
                self.started_at = time.monotonic()
                for stream in self.streams:
                    if self._stop_event.is_set():
                        raise RuntimeError('Recording stopped while the audio devices were starting.')
                    stream.start()
                if self._stop_event.is_set():
                    raise RuntimeError('Recording stopped while the audio devices were starting.')
                microphone_registry().set_phase(self._token, 'listening')
            except Exception:
                self._stop_event.set()
                self._ready.set()
                if self._worker is None or not self._worker.is_alive():
                    self._finish_capture()
                else:
                    self._worker.join(5)
                raise
            finally:
                self._ready.set()

    def _write_block(self, name, raw):
        if self.written_bytes[name] + len(raw) > self.MAX_TRACK_BYTES:
            self._problem('This recording reached its file size limit. The saved portion is kept.')
            return
        try:
            self.wavs[name].writeframes(raw)
            self.written_bytes[name] += len(raw)
        except Exception:
            self._problem('An original recording could not be saved completely. The saved portion is kept.')

    def _spool(self):
        import queue
        self._ready.wait()
        try:
            while not self._stop_event.is_set():
                try:
                    name, raw = self._queue.get(timeout=0.1)
                except queue.Empty:
                    if any(getattr(stream, 'active', None) is False for stream in self.streams):
                        self._problem('An audio device stopped unexpectedly. The saved portion is kept.')
                    continue
                self._write_block(name, raw)
        except Exception:
            self._problem('Audio processing stopped unexpectedly. The saved portion is kept.')
        finally:
            self._finish_capture()

    def _finish_capture(self):
        import queue
        from .mic_registry import microphone_registry

        if self._token is not None:
            microphone_registry().set_phase(self._token, 'closing')
        remaining = []
        for stream in self.streams:
            try:
                stream.stop()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                remaining.append(stream)
        self.streams = remaining
        # Callbacks refuse new blocks after Stop. Drain only bounded accepted
        # audio, including when a driver still needs a close retry.
        while True:
            try:
                name, raw = self._queue.get_nowait()
            except queue.Empty:
                break
            self._write_block(name, raw)
        if remaining:
            self._problem('An audio device has not closed. Use Panic Stop to retry.')
            if self._token is not None:
                microphone_registry().set_phase(self._token, 'stop-failed')
            return
        for handle in self.wavs.values():
            try:
                handle.close()
            except Exception:
                self._problem('An original recording could not finish saving.')
        microphone_registry().release(self._token)
        self._token = None
        self.closed.set()
        try:
            self._manifest()
        except Exception:
            self._problem('Recording details could not be saved. The original audio files are kept.')

    def request_stop(self):
        import threading
        from .mic_registry import microphone_registry, DEFERRED_MICROPHONE_RELEASE

        self._stop_event.set()
        if self._token is not None:
            microphone_registry().set_phase(self._token, 'closing')
        if self._started and not self._ready.is_set():
            return DEFERRED_MICROPHONE_RELEASE
        # Normally the already-running writer owns close. A failed close has
        # finished its worker and needs an explicit retry from Stop or Panic.
        if not self.closed.is_set() and (self._worker is None or not self._worker.is_alive()):
            with self._worker_lock:
                if not self.closed.is_set() and (self._worker is None or not self._worker.is_alive()):
                    self._ready.set()
                    self._worker = threading.Thread(target=self._finish_capture, name='TalkDatScribeClose', daemon=True)
                    try:
                        self._worker.start()
                    except Exception:
                        self._problem('Recording could not stop. Use Panic Stop to retry.')
                        if self._token is not None:
                            microphone_registry().set_phase(self._token, 'stop-failed')
        return DEFERRED_MICROPHONE_RELEASE

    def stop(self) -> dict[str, Path]:
        import threading
        # Also closes partially constructed recorders, before any worker exists.
        if not self._started and self._worker is None:
            self._stop_event.set()
            self._finish_capture()
        else:
            self.request_stop()
            if self._started and not self._ready.wait(10):
                raise RuntimeError('An audio device is still starting. Use Panic Stop to retry.')
            worker = self._worker
            if worker is not None and worker is not threading.current_thread():
                worker.join(5)
        if not self.closed.is_set():
            raise RuntimeError('An audio device has not closed. Use Panic Stop to retry.')
        return self.tracks()

    def tracks(self):
        return {name: self.folder / (name + '.wav') for name in ('you', 'them')
                if (self.folder / (name + '.wav')).exists() and (self.folder / (name + '.wav')).stat().st_size > 44}


def chunk_wav_for_transcription(path: Path, *, chunk_seconds: int = CHUNK_SECONDS):
    """Stream bounded PCM chunks using the bundled resampler, not removed audioop."""
    import wave
    if type(chunk_seconds) is not int or not 1<=chunk_seconds<=300:
        raise ValueError('Choose a chunk length between one and 300 seconds.')
    with wave.open(str(path),'rb') as source:
        rate,channels=source.getframerate(),source.getnchannels()
        if source.getsampwidth()!=2 or not 1<=channels<=8 or not 8000<=rate<=384000:
            raise ValueError('This recording needs 16-bit PCM audio at a supported rate.')
        if rate==16000 and channels==1:
            index=0
            while frames:=source.readframes(rate*chunk_seconds):
                yield index*chunk_seconds,frames
                index+=1
            return
        import av,numpy as np
        from fractions import Fraction
        resampler=av.AudioResampler(format='s16',layout='mono',rate=16000)
        pending=bytearray();target=16000*chunk_seconds*2;offset=0;index=0
        def outputs(frame):
            for converted in resampler.resample(frame):
                yield converted.to_ndarray().astype('<i2',copy=False).tobytes()
        while frames:=source.readframes(8192):
            samples=np.frombuffer(frames,dtype='<i2').reshape(-1,channels)
            # Equal-weight downmix preserves headroom for correlated stereo.
            mono=np.rint(samples.astype(np.float64).mean(axis=1)).astype(np.int16)
            frame=av.AudioFrame.from_ndarray(mono.reshape(1,-1),format='s16',layout='mono')
            frame.sample_rate=rate;frame.time_base=Fraction(1,rate);frame.pts=offset;offset+=len(mono)
            for raw in outputs(frame):pending.extend(raw)
            while len(pending)>=target:
                yield index*chunk_seconds,bytes(pending[:target]);del pending[:target];index+=1
        for raw in outputs(None):pending.extend(raw)
        while pending:
            yield index*chunk_seconds,bytes(pending[:target]);del pending[:target];index+=1
