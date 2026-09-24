"""X-351: the right-click door -- highlight text in ANY app, right-click,
and Talk DAT! offers Rewrite and prompted rewrites.

The founder's order, verbatim intent: "highlight any text anywhere, right
click, and it appears on whatever that context menu is as an option."
Windows has no extension point that injects items into other apps' text
selection menus (Explorer file menus are a different system), so the
honest implementation is a low-level mouse hook: on a right-click inside
someone else's window, a small Talk DAT! chip appears beside the native
menu. Clicking the chip opens the options; choosing one refocuses the
original window (the paste_last pattern), captures the selection through
the existing Fix That machinery, and rewrites it in place.

Nothing here touches the native menu, steals the click, or copies the
clipboard on its own -- the hook only OBSERVES button-ups and posts a
chip. Everything destructive rides Fix That's caret-proof pipeline.

Windows-only by design; macOS gets the same feature natively through the
Services menu (knight_flow/mac_services.py).
"""

from __future__ import annotations

import logging
import sys
import threading
from typing import Any, Callable

log = logging.getLogger("knight_flow.selection_menu")

WM_RBUTTONUP = 0x0205

#: The fixed offers. The instruction strings go verbatim into Fix That's
#: rewrite call, so they read as instructions, not labels.
QUICK_FIXES: tuple[tuple[str, str], ...] = (
    ("Rewrite", "Rewrite this cleanly. Keep the meaning and the language."),
    ("Make it shorter", "Make this shorter."),
    ("Make it friendlier", "Make this friendlier."),
)

_state: dict[str, Any] = {"thread": None, "stop": None}


def enabled(config: dict[str, Any]) -> bool:
    """The kill switch. Default OFF since X-436 (2026-09-04).

    0.4.131 was the first build whose hook actually installed (X-434), and
    the founder's PC lagged system-wide the moment the app came up: a
    low-level mouse hook runs its callback inside this process, so every
    mouse event on the machine waits for our interpreter whenever the app is
    busy (model load, a decode, a Tk redraw). No Python process should hold a
    WH_MOUSE_LL hook by default. The chip beside the native menu is also the
    thing he rejected: "it needs to be in the normal context menu, not a
    second menu". Windows offers no such extension point for other apps'
    text menus, so the honest state is off, with the reason in Settings.
    """
    return bool(config.get("dictation", {}).get("right_click_rewrite", False))


def typed_user32(hookproc: type) -> object:
    """A user32 of our own with every call this module makes typed.

    Private (X-434) so pynput's argtypes on the shared singleton never apply
    to us; typed, so 64-bit handles and lparams never overflow a default
    c_int conversion. `hookproc` is the WINFUNCTYPE class the hook is built
    from, which is what SetWindowsHookExW must be told to accept.
    """
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    LRESULT = getattr(wintypes, "LRESULT", ctypes.c_ssize_t)
    user32.SetWindowsHookExW.argtypes = (ctypes.c_int, hookproc, wintypes.HINSTANCE, wintypes.DWORD)
    user32.SetWindowsHookExW.restype = wintypes.HHOOK
    user32.UnhookWindowsHookEx.argtypes = (wintypes.HHOOK,)
    user32.UnhookWindowsHookEx.restype = wintypes.BOOL
    user32.CallNextHookEx.argtypes = (wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
    user32.CallNextHookEx.restype = LRESULT
    user32.WindowFromPoint.argtypes = (wintypes.POINT,)
    user32.WindowFromPoint.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.GetAncestor.argtypes = (wintypes.HWND, wintypes.UINT)
    user32.GetAncestor.restype = wintypes.HWND
    user32.PeekMessageW.argtypes = (ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT)
    user32.PeekMessageW.restype = wintypes.BOOL
    user32.TranslateMessage.argtypes = (ctypes.POINTER(wintypes.MSG),)
    user32.TranslateMessage.restype = wintypes.BOOL
    user32.DispatchMessageW.argtypes = (ctypes.POINTER(wintypes.MSG),)
    user32.DispatchMessageW.restype = LRESULT
    return user32


def start(
    *,
    config: dict[str, Any],
    on_right_click: Callable[[int, int, int], None],
) -> bool:
    """Install the observer hook. Returns whether it is running.

    ``on_right_click(x, y, hwnd)`` is called (from the hook thread) for
    every right-button-up that lands in ANOTHER process's window; the
    caller marshals to the UI thread and shows the chip.
    """
    if sys.platform != "win32":
        return False
    if not enabled(config):
        log.info("right-click rewrite disabled by config")
        return False
    if _state["thread"] is not None:
        return True

    import ctypes
    from ctypes import wintypes

    # X-434: a private, typed user32 (see typed_user32), never the shared
    # ctypes singleton. pynput (hotkeys.py) sets SetWindowsHookExW.argtypes on
    # the shared user32 with ITS hook-proc class, WINFUNCTYPE(LPARAM, c_int32,
    # WPARAM, LPARAM). Ours is WINFUNCTYPE(c_ssize_t, c_int, WPARAM, c_void_p),
    # a different signature and so a different class, and the shared function
    # refused our instance ("expected WinFunctionType instance instead of
    # WinFunctionType"); the hook thread died before installing anything.
    kernel32 = ctypes.windll.kernel32

    ULONG_PTR = getattr(wintypes, "ULONG_PTR", ctypes.c_size_t)

    class MSLLHOOKSTRUCT(ctypes.Structure):
        _fields_ = [
            ("pt", wintypes.POINT),
            ("mouseData", wintypes.DWORD),
            ("flags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ULONG_PTR),
        ]

    HOOKPROC = ctypes.WINFUNCTYPE(
        ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, ctypes.c_void_p
    )

    our_pid = kernel32.GetCurrentProcessId()
    stop_event = threading.Event()
    _state["stop"] = stop_event

    def hook_proc(code: int, wparam: int, lparam: int) -> int:
        if code >= 0 and wparam == WM_RBUTTONUP:
            try:
                info = ctypes.cast(lparam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                x, y = info.pt.x, info.pt.y
                hwnd = user32.WindowFromPoint(info.pt)
                target_pid = wintypes.DWORD(0)
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(target_pid))
                # Our own windows already carry the feature; a chip over the
                # pill menu would be noise.
                if hwnd and target_pid.value and target_pid.value != our_pid:
                    root = user32.GetAncestor(hwnd, 2)  # GA_ROOT
                    on_right_click(int(x), int(y), int(root or hwnd))
            except Exception:
                log.debug("right-click observation failed", exc_info=True)
        return user32.CallNextHookEx(None, code, wparam, lparam)

    # Typed, because a private WinDLL starts with NO argtypes: the first cut
    # of X-434 let a 64-bit lparam overflow c_int inside CallNextHookEx, so
    # the hook raised on every mouse event and never chained to the next hook.
    user32 = typed_user32(HOOKPROC)
    keep_alive = HOOKPROC(hook_proc)
    _state["proc"] = keep_alive  # the GC must never collect an active hook proc

    def pump() -> None:
        hook = user32.SetWindowsHookExW(14, keep_alive, None, 0)  # WH_MOUSE_LL
        if not hook:
            log.warning("right-click rewrite hook did not install")
            return
        log.info("right-click rewrite hook installed")
        try:
            msg = wintypes.MSG()
            while not stop_event.is_set():
                # PeekMessage keeps the loop responsive to the stop event; a
                # blocking GetMessage would pin this thread forever.
                if user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
                    user32.TranslateMessage(ctypes.byref(msg))
                    user32.DispatchMessageW(ctypes.byref(msg))
                else:
                    kernel32.Sleep(24)
        finally:
            user32.UnhookWindowsHookEx(hook)
            log.info("right-click rewrite hook removed")

    thread = threading.Thread(target=pump, name="TalkDatRightClick", daemon=True)
    _state["thread"] = thread
    thread.start()
    return True


def stop() -> None:
    event = _state.get("stop")
    if event is not None:
        event.set()
    _state["thread"] = None
