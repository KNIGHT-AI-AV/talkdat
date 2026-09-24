"""Bounded local diagnostics. Transcripts and journals have separate retention."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import stat
import tempfile
import threading

from .config import app_dir

MAX_LOG_BYTES = 2 * 1024 * 1024
MAX_LOG_BACKUPS = 3
MAX_RECORD_BYTES = 64 * 1024
_CONFIGURE_LOCK = threading.RLock()
_FORMAT = '%(asctime)s %(levelname)s %(name)s: %(message)s'


def _bounded_text(text: str, limit: int, marker: str = '') -> str:
    raw = text.encode('utf-8', errors='backslashreplace')
    if len(raw) <= limit:
        return raw.decode('utf-8')
    suffix = marker.encode('utf-8')
    return raw[:max(0, limit - len(suffix))].decode('utf-8', errors='ignore') + marker


def _regular_or_missing(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink > 1
            or getattr(info, 'st_file_attributes', 0) & 0x400):
        raise OSError('Diagnostic path is not an ordinary file.')
    return True


def _prepare_existing(path: Path) -> None:
    """Keep recent tails of legacy oversized logs, replacing each atomically."""
    for index in range(MAX_LOG_BACKUPS + 1):
        item = path if not index else path.with_name(path.name + '.' + str(index))
        if not _regular_or_missing(item) or item.stat().st_size <= MAX_LOG_BYTES:
            continue
        with item.open('rb') as stream:
            stream.seek(-MAX_LOG_BYTES, os.SEEK_END)
            tail = stream.read(MAX_LOG_BYTES)
        if b'\n' in tail:
            tail = tail.split(b'\n', 1)[1]
        text = _bounded_text(tail.decode('utf-8', errors='replace'), MAX_LOG_BYTES)
        fd, name = tempfile.mkstemp(prefix='.talkdat-log-', dir=path.parent)
        temporary = Path(name)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(text.encode('utf-8'))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, item)
        finally:
            temporary.unlink(missing_ok=True)


class BoundedLogHandler(RotatingFileHandler):
    """Use encoded byte sizes and bound an individual formatted exception."""

    def _open(self):
        return open(self.baseFilename, self.mode, encoding='utf-8',
                    errors='backslashreplace', newline='\n')

    def format(self, record):
        return _bounded_text(super().format(record),
                             min(MAX_RECORD_BYTES, self.maxBytes - 1),
                             '\n[log entry truncated]')

    def shouldRollover(self, record):
        if self.stream is None:
            self.stream = self._open()
        self.stream.seek(0, os.SEEK_END)
        size = self.stream.tell()
        length = len((self.format(record) + self.terminator).encode('utf-8'))
        return size > 0 and size + length > self.maxBytes

    def doRollover(self):
        for index in range(self.backupCount + 1):
            _regular_or_missing(Path(self.baseFilename + ('.' + str(index) if index else '')))
        super().doRollover()

    def handleError(self, record):
        # Logging failure must not interrupt dictation or dump private record
        # content to a console when a full/locked disk refuses the write.
        self.write_failed = True


def configure_logging() -> bool:
    """Install one owned file handler without replacing another component's."""
    with _CONFIGURE_LOCK:
        root = logging.getLogger()
        try:
            path = (app_dir() / 'talk-dat.log').absolute()
            owned = [handler for handler in root.handlers if isinstance(handler, BoundedLogHandler)]
            if any(Path(handler.baseFilename) == path for handler in owned):
                return True
            _prepare_existing(path)
            handler = BoundedLogHandler(path, maxBytes=MAX_LOG_BYTES,
                                        backupCount=MAX_LOG_BACKUPS, encoding='utf-8',
                                        errors='backslashreplace')
            handler.setFormatter(logging.Formatter(_FORMAT))
        except OSError:
            # An unreadable diagnostic folder is not a reason to lose dictation.
            if not root.handlers:
                root.addHandler(logging.NullHandler())
            return False
        root.addHandler(handler)
        root.setLevel(logging.INFO)
        for previous in owned:
            root.removeHandler(previous)
            previous.close()
        return True
