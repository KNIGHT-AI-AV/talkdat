"""Things that went wrong before the person could see anything, said once.

Find-more sweep, P0-3 and P0-7: a crash that interrupted a dictation, and a
settings file that could not be read, were both handled at launch and only
written to the log. The person was never told that a take was waiting in
Recovery, or that the app had started with default settings. Anything added
here is shown on Home for the rest of this session and once on the Pill.

A notice lives in memory only. The next launch says it again only if the
problem is still there, which is what "once" means for a launch.
"""
from __future__ import annotations

import threading

_LOCK = threading.Lock()
_NOTICES: list[dict[str, str]] = []


def notice(key: str, text: str, page: str = "", message: str = "") -> None:
    """Record one notice: `text` for Home, `message` (short) for the Pill.

    The same key twice keeps the first. `page` names the shell page Home
    offers a button for ("recovery"), or nothing.
    """
    with _LOCK:
        if any(item["key"] == key for item in _NOTICES):
            return
        _NOTICES.append({"key": str(key), "text": str(text), "page": str(page or ""),
                         "message": str(message or text)})


def pending() -> list[dict[str, str]]:
    with _LOCK:
        return [dict(item) for item in _NOTICES]


def clear() -> None:
    """Tests only: a notice belongs to one launch."""
    with _LOCK:
        _NOTICES.clear()
