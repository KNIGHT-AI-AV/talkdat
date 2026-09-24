"""Publish complete exports without replacing an earlier document."""

from __future__ import annotations

import os
import logging
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)


def _publish_new(staged: Path, target: Path) -> None:
    if os.name == "nt":
        # Windows rename refuses an existing destination. The file stays on
        # the same volume, so readers only see the finished document.
        os.rename(staged, target)
    else:
        # POSIX rename would replace an existing file. An exclusive hard link
        # publishes the complete inode and makes concurrent exports safe.
        os.link(staged, target)


def save_new_export(folder: Path, filename: str, data: bytes) -> Path:
    """Flush in the destination folder, then publish under an unused name.

    Publication failure leaves existing exports intact. A numbered suffix is
    selected atomically, including when several workers save simultaneously.
    """
    folder = Path(folder)
    if not filename or filename in {".", ".."} or Path(filename).name != filename:
        raise ValueError("An export needs a filename, without a folder path.")
    if any(char in filename for char in ('/', '\\', '\x00')):
        raise ValueError("An export filename contains an invalid character.")
    folder.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".talk-dat-export-", suffix=".tmp", dir=folder)
    staged = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        original = Path(filename)
        for number in range(1, 10001):
            name = filename if number == 1 else f"{original.stem} ({number}){original.suffix}"
            target = folder / name
            try:
                _publish_new(staged, target)
            except FileExistsError:
                continue
            return target
        raise FileExistsError("Too many exports share this name. Choose another folder or title.")
    finally:
        try:
            staged.unlink(missing_ok=True)
        except OSError:
            # Cleanup must not turn a successful publication into a failure,
            # or hide the original storage error from the recovery flow.
            log.warning("Could not remove a temporary export file", exc_info=True)
