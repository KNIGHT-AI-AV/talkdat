"""Live meeting transcripts backed by the same owned, durable Scribe capture."""
from __future__ import annotations
import copy,threading,time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from .config import app_dir
from .stt_sessions import transcribe_pcm

StatusCallback = Callable[[str], None]
LineCallback = Callable[[str], None]


def meetings_dir() -> Path:
    path = app_dir() / 'meetings'
    path.mkdir(parents=True, exist_ok=True)
    return path


class MeetingRecorder:
    def __init__(self, config: dict[str, Any], *, on_status: StatusCallback, on_line: LineCallback):
        self.config = copy.deepcopy(config)
        self.on_status, self.on_line = on_status, on_line
        seconds = config.get('meeting', {}).get('chunk_seconds', 25)
        self.chunk_seconds = seconds if type(seconds) is int and 8 <= seconds <= 60 else 25
        self.sample_rate, self.channels = 16000, 1
        self._stop_event = threading.Event()
        self._thread = None
        self._recorder = None
        self._pending = bytearray()
        self._lock = threading.Lock()
        self.path = None
        self.using_loopback = False
        self.unsaved_lines = []
        self.failed_chunks = []
        self._write_failed = False
        self._position = 0

    @property
    def running(self):
        return bool(self._thread and self._thread.is_alive())

    def start(self):
        from .export_files import save_new_export
        if self.running:
            return
        source = self.config.get('meeting', {}).get('source', 'system')
        if source not in {'microphone', 'system'}:
            raise ValueError('Choose microphone or system audio for live notes.')
        self._stop_event.clear()
        self._write_failed = False
        self.unsaved_lines = []
        self.failed_chunks = []
        self._position = 0
        self._pending.clear()
        header = f"# Meeting transcript - {time.strftime('%Y-%m-%d %H:%M')}\n\nSource: {source}. Times mark audio sections, not individual words.\n\n"
        self.path = save_new_export(meetings_dir(), time.strftime('meeting-%Y%m%d-%H%M.md'), header.encode('utf-8'))
        self._thread = threading.Thread(target=self._run, name='TalkDatMeeting', daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        recorder = self._recorder
        if recorder is not None:
            recorder.request_stop()

    def _open_stream(self, callback):
        # Kept for native callers that explicitly open one source. The live
        # worker itself uses ScribeRecorder for registration and disk spooling.
        source = self.config.get('meeting', {}).get('source', 'system')
        if source == 'system':
            from .system_audio import open_loopback_stream
            stream = open_loopback_stream(callback)
            self.using_loopback = True
            self.sample_rate, self.channels = int(stream.samplerate), int(stream.channels)
            return stream
        if source != 'microphone':
            raise ValueError('Choose a recording source.')
        from .audio_input import open_raw_input_stream, resolve_input_device
        chosen = str(self.config.get('audio', {}).get('input_device', '') or '')
        device = resolve_input_device(chosen)
        if chosen and device is None:
            raise RuntimeError('The selected microphone is unavailable.')
        stream, rate, channels, _ = open_raw_input_stream(samplerate=16000, channels=1,
            device=device, callback=callback, allow_device_fallback=False)
        self.using_loopback = False
        self.sample_rate, self.channels = int(rate), int(channels)
        return stream

    def _run(self):
        from .scribe import ScribeRecorder
        source = self.config.get('meeting', {}).get('source', 'system')
        config = copy.deepcopy(self.config)
        config['scribe'] = {'source': source}
        recorder = None
        try:
            recorder = ScribeRecorder(config)
            self._recorder = recorder
            if self._stop_event.is_set():
                return
            recorder.start()
            name = 'you' if source == 'microphone' else 'them'
            self.using_loopback = source == 'system'
            self.sample_rate, self.channels = recorder.rates[name], recorder.channels[name]
            self.on_status(f'Meeting recording from {"system audio" if self.using_loopback else "your selected microphone"}. Originals are kept for recovery.')
            path = recorder.folder / (name + '.wav')
            while not self._stop_event.wait(0.2) and not recorder.closed.is_set():
                self._read_next(path, final=False)
                if recorder.errors:
                    break
            recorder.stop()
            while not self._write_failed and self._read_next(path, final=True):
                pass
            for problem in recorder.errors:
                self._append(f'**Recording warning:** {problem}')
            if self._write_failed:
                self.on_status('Meeting stopped after a save failed. Unsaved words and original audio are kept for recovery.')
            elif self.failed_chunks or recorder.errors:
                self.on_status(f'Meeting stopped with gaps marked in the transcript. Originals: {recorder.folder}')
            else:
                self.on_status(f'Meeting stopped. Transcript: {self.path}')
        except Exception:
            self.on_status('Meeting could not finish. Saved words and any original audio are kept for recovery.')
        finally:
            try:
                if recorder is not None:
                    recorder.stop()
            except Exception:
                self.on_status('An audio device has not closed. Use Panic Stop to retry.')

    def _read_next(self, path, *, final):
        size = self.sample_rate * self.channels * 2 * self.chunk_seconds
        with path.open('rb') as file:
            # These are our canonical PCM16 WAV files; reads remain bounded
            # while the writer owns and updates the header independently.
            file.seek(44 + self._position)
            raw = file.read(size)
        if not raw or (len(raw) < size and not final):
            return False
        raw = raw[:len(raw) // (self.channels * 2) * (self.channels * 2)]
        if not raw:
            return False
        self._pending.extend(raw)
        self._flush_chunk()
        self._position += len(raw)
        return True

    def _append(self, line):
        try:
            if self.path is None:
                raise OSError('No transcript path')
            with self.path.open('a', encoding='utf-8') as file:
                file.write(line + '\n\n')
                file.flush()
                import os
                os.fsync(file.fileno())
        except OSError:
            self.unsaved_lines.append(line)
            self._write_failed = True
            self.stop()
            self.on_status('Meeting text could not be saved. The unsaved words are kept for recovery.')
            return False
        return True

    def _flush_chunk(self):
        with self._lock:
            chunk = bytes(self._pending)
            self._pending.clear()
        if not chunk:
            return
        start = self._position / (self.sample_rate * self.channels * 2)
        stamp = f'{int(start)//60:02d}:{int(start)%60:02d}'
        try:
            from .stt_registry import resolve_route
            text = str(transcribe_pcm(self.config, chunk, self.sample_rate, self.channels, provider_id=resolve_route(self.config)) or '')
        except Exception:
            self.failed_chunks.append(start)
            self._append(f'**[{stamp}] Transcription unavailable for this section. Original audio is retained.**')
            self.on_status('A meeting section could not be transcribed. Its original audio is kept for retry.')
            return
        if text and self._append(f'**[{stamp}]** {text}'):
            self.on_line(text)
