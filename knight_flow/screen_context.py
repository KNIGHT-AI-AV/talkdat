"""X-34: the names on your screen spell right, without uploading anything.

Wispr does screen context by shipping the screen to their servers. This is
the privacy flex version: at the moment a dictation starts, read ONE string
-- the foreground window's title -- on-device, harvest the proper nouns out
of it, and let them bias the vocabulary pass for that dictation only.
Reply to "Adaeze Okafor - RE: Contract" and "adaeze" comes out spelled
right, and nothing about the window ever leaves the machine or outlives
the dictation.
"""

from __future__ import annotations

import ctypes
import re
import sys

from . import mac_support

# Junk that window titles carry which is never a person or product the user
# is dictating about.
_TITLE_NOISE = {
    "untitled", "document", "inbox", "sent", "drafts", "re", "fw", "fwd",
    "new", "tab", "window", "home", "page", "file", "edit", "view", "help",
    "microsoft", "google", "chrome", "edge", "firefox", "outlook", "mail",
    "word", "excel", "powerpoint", "notepad", "explorer", "settings",
    "visual", "studio", "code", "slack", "discord", "teams", "zoom",
    "mozilla", "profile", "meet", "calendar", "gmail", "youtube", "reddit",
    "the", "and", "for", "with", "from", "your", "talk", "dat",
}

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'’-]{1,23}")


def foreground_title() -> str:
    if sys.platform == "darwin":
        return mac_support.frontmost_window_title()
    if sys.platform != "win32":
        return ""
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return ""
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0 or length > 512:
            return ""
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        return buffer.value or ""
    except Exception:
        return ""


def names_from_title(title: str, *, limit: int = 8) -> list[str]:
    """Proper-noun-looking runs from a window title.

    Capitalized words that are not app chrome, kept in their original runs
    ("Adaeze Okafor" stays one name, because the pair is what the vocabulary
    pass needs to spell a reply correctly). Order preserved, first-seen wins,
    everything lowercase-noise filtered.
    """
    if not title:
        return []
    # Split on the separators titles use between document and application.
    segments = re.split(r"\s*[-–—|·:,;/&+]\s*", title)
    names: list[str] = []
    seen: set[str] = set()
    for segment in segments:
        run: list[str] = []
        for token in _WORD_RE.findall(segment):
            is_name = token[0].isupper() and token.lower() not in _TITLE_NOISE
            if is_name:
                run.append(token)
                continue
            if len(run) >= 1:
                _push_run(run, names, seen)
            run = []
        if run:
            _push_run(run, names, seen)
    return names[:limit]


def _push_run(run: list[str], names: list[str], seen: set[str]) -> None:
    # Single very short tokens ("A", "I") are noise; anything else useful.
    candidate = " ".join(run)
    if len(candidate) < 3:
        run.clear()
        return
    key = candidate.lower()
    if key not in seen:
        seen.add(key)
        names.append(candidate)
    run.clear()
