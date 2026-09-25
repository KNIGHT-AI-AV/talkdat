from __future__ import annotations

"""Say a Pill message to a screen reader (X-742).

The Pill's words are pixels in a per-pixel-alpha bitmap, so no accessibility
tree ever sees them: before this, Narrator and NVDA heard none of the Tk
messages (message inventory, point 8). Windows 10 1709 and later have a direct
way to speak for a window without a focusable element:
UiaRaiseNotificationEvent on the window's host provider. The tone decides the
urgency: a finished action is ActionCompleted, an error is ImportantAll (read
even over other speech), everything else is Other and only the latest is read.

Never raises and never blocks on a listener: with no screen reader running,
UiaClientsAreListening is false and nothing is built.
"""

import ctypes
import logging
import sys
from ctypes import wintypes

log = logging.getLogger("knight_flow.announce")

NOTIFICATION_KIND_ACTION_COMPLETED = 2
NOTIFICATION_KIND_OTHER = 4
PROCESSING_IMPORTANT_ALL = 0
PROCESSING_ALL = 2
PROCESSING_MOST_RECENT = 3

#: tone -> (NotificationKind, NotificationProcessing)
TONE_EVENTS = {
    "done": (NOTIFICATION_KIND_ACTION_COMPLETED, PROCESSING_ALL),
    "error": (NOTIFICATION_KIND_OTHER, PROCESSING_IMPORTANT_ALL),
    "warn": (NOTIFICATION_KIND_OTHER, PROCESSING_MOST_RECENT),
    "info": (NOTIFICATION_KIND_OTHER, PROCESSING_MOST_RECENT),
    "busy": (NOTIFICATION_KIND_OTHER, PROCESSING_MOST_RECENT),
}

_API = None


class _Uia:
    def __init__(self) -> None:
        core = ctypes.WinDLL("UIAutomationCore")
        oleaut = ctypes.WinDLL("oleaut32")
        self.listening = core.UiaClientsAreListening
        self.listening.restype = wintypes.BOOL
        self.host = core.UiaHostProviderFromHwnd
        self.host.argtypes = (wintypes.HWND, ctypes.POINTER(ctypes.c_void_p))
        self.host.restype = ctypes.c_long
        self.raise_ = core.UiaRaiseNotificationEvent
        self.raise_.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
        self.raise_.restype = ctypes.c_long
        self.alloc = oleaut.SysAllocString
        self.alloc.argtypes = (wintypes.LPCWSTR,)
        self.alloc.restype = ctypes.c_void_p
        self.free = oleaut.SysFreeString
        self.free.argtypes = (ctypes.c_void_p,)
        self.free.restype = None


def _api() -> _Uia | None:
    global _API
    if _API is None and sys.platform == "win32":
        try:
            _API = _Uia()
        except (AttributeError, OSError):
            log.debug("UI Automation notifications are unavailable", exc_info=True)
            _API = False  # type: ignore[assignment]
    return _API or None


def _release(pointer: int) -> None:
    # IUnknown::Release is the third slot of every COM vtable.
    vtable = ctypes.cast(ctypes.c_void_p(pointer), ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtable[2])
    release(pointer)


def spoken_text(title: str, detail: str = "", hints: tuple[str, ...] = ()) -> str:
    parts = [part.strip() for part in (title, detail, *hints) if part and part.strip()]
    text = ""
    for part in parts:
        if text and not text.endswith((".", "!", "?")):
            text += "."
        text = f"{text} {part}".strip()
    return text


def announce(hwnd: int, text: str, tone: str = "info", *, activity: str = "TalkDatPill") -> bool:
    """Raise one notification for ``hwnd``. True when a listener was told."""
    api = _api()
    if api is None or not hwnd or not text:
        return False
    try:
        if not api.listening():
            return False
        provider = ctypes.c_void_p()
        if api.host(wintypes.HWND(int(hwnd)), ctypes.byref(provider)) != 0 or not provider.value:
            return False
        kind, processing = TONE_EVENTS.get(str(tone), TONE_EVENTS["info"])
        display = api.alloc(str(text))
        activity_id = api.alloc(str(activity))
        try:
            return api.raise_(provider, kind, processing, display, activity_id) == 0
        finally:
            api.free(display)
            api.free(activity_id)
            _release(int(provider.value))
    except Exception:
        log.debug("screen reader notification failed", exc_info=True)
        return False


__all__ = ["TONE_EVENTS", "announce", "spoken_text"]
