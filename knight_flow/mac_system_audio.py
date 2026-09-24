"""Bounded pipe adapter for the packaged audio-only ScreenCaptureKit helper."""
from __future__ import annotations
import struct, subprocess, threading
from pathlib import Path

ERRORS = {
    'permission': 'Allow Screen and System Audio Recording for Talk DAT in Mac System Settings, then try again.',
    'display': 'Mac system audio needs an available display session.',
    'version': 'System audio needs macOS 13 or later.',
    'overflow': 'System audio arrived faster than it could be kept. Recording stopped.',
    'format': 'Mac system audio returned an unsupported format.',
    'buffer': 'Mac system audio returned an incomplete audio block.',
    'device': 'Mac system audio was interrupted. The saved portion is kept.',
    'start': 'Mac system audio could not start. Check its permission in System Settings.',
    'stop': 'Mac system audio could not stop normally. Its capture helper was closed.',
}


def _read_exact(stream, count):
    value = bytearray()
    while len(value) < count:
        part = stream.read(count - len(value))
        if not part:
            if not value:
                return None
            raise ValueError('Incomplete system-audio packet.')
        value.extend(part)
    return bytes(value)


def packets(stream):
    while (header := _read_exact(stream, 4)) is not None:
        size = struct.unpack('<I', header)[0]
        if not 1 <= size <= 65537:
            raise ValueError('Invalid system-audio packet size.')
        value = _read_exact(stream, size)
        if value is None:
            raise ValueError('Incomplete system-audio packet.')
        kind, body = value[0], value[1:]
        if kind not in (1, 2, 3, 4) or (kind in (1, 4) and body) or (kind == 2 and (not body or len(body) % 4)):
            raise ValueError('Invalid system-audio packet.')
        if kind == 3 and len(body) > 64:
            raise ValueError('Invalid system-audio error packet.')
        yield kind, body


class MacLoopbackStream:
    samplerate = 48000
    channels = 2
    device = 'Mac system audio'

    def __init__(self, callback):
        self.callback = callback
        self.helper = Path(__file__).resolve().parent / 'native' / 'TalkDATSystemAudio'
        self.process = None
        self._reader = None
        self._ready = threading.Event()
        self._stopping = threading.Event()
        self._closed = False
        self._active = False
        self._lock = threading.RLock()
        self.error = ''

    @property
    def active(self):
        return self._active and not self._closed

    def start(self):
        with self._lock:
            if self.process is not None or self._closed:
                raise RuntimeError('This audio capture cannot be started again.')
            if not self.helper.is_file():
                raise RuntimeError('The Mac system-audio component is missing. Repair or update Talk DAT.')
            self.process = subprocess.Popen([str(self.helper)], stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
            self._active = True
            self._reader = threading.Thread(target=self._receive, name='TalkDatSystemAudio', daemon=True)
            try:
                self._reader.start()
            except Exception:
                self.close()
                raise
        if not self._ready.wait(10):
            self.error = 'Mac system audio did not start in time. Check its permission in System Settings.'
        if self.error or not self._active:
            self.close()
            raise RuntimeError(self.error or 'Mac system audio stopped before recording began.')
        return self

    def _receive(self):
        try:
            for kind, body in packets(self.process.stdout):
                if kind == 1:
                    self._ready.set()
                elif kind == 2:
                    # A first audio block may precede the asynchronous ready
                    # receipt. The caller has already opened its track file.
                    self.callback(body, len(body) // 4, {}, 0)
                elif kind == 3:
                    self.error = ERRORS.get(body.decode('ascii', errors='replace'), 'Mac system audio failed. The saved portion is kept.')
                    break
                elif kind == 4:
                    break
            if not self._stopping.is_set() and not self.error:
                self.error = 'Mac system audio stopped unexpectedly. The saved portion is kept.'
        except Exception:
            self.error = 'Mac system audio could not be kept completely. Recording stopped.'
        finally:
            self._active = False
            self._ready.set()
            if self.error:
                try:
                    self.process.stdin.close()
                except Exception:
                    pass

    def stop(self):
        self._stopping.set()
        process = self.process
        if process is None or process.poll() is not None:
            return
        try:
            process.stdin.write(b'S')
            process.stdin.flush()
        except (OSError, ValueError):
            pass
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)

    def close(self):
        with self._lock:
            if self._closed:
                return
            self.stop()
            if self._reader is not None and self._reader is not threading.current_thread() and self._reader.ident is not None:
                self._reader.join(1)
                if self._reader.is_alive():
                    raise RuntimeError('Mac system audio is still closing. Use Panic Stop to retry.')
            if self.process is not None:
                for stream in (self.process.stdin, self.process.stdout):
                    stream.close()
            self._active = False
            self._closed = True

    def __enter__(self):
        return self.start()

    def __exit__(self, *_):
        self.close()
