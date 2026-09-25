"""Find-more P0-4 (commandment 85): know when the target has read a borrowed clipboard.

A clipboard paste puts the dictation on the clipboard, sends Ctrl+V, and then
puts back what the person had copied. The restore ran after a fixed 0.2 s, so
any app that handles the keystroke later (Word or Teams under load, an
Electron app, a VM) read the clipboard after the restore and pasted the
person's OLD clipboard, which can be anything they copied, a password
included.

Windows can tell us the moment an app reads: delayed rendering. The borrowed
clipboard is offered with CF_UNICODETEXT and no data, owned by a hidden
message-only window; the first app that asks for the text makes Windows send
that window WM_RENDERFORMAT, and the text is handed over right then. The
paste layer waits for that read (the reader's process must be the target the
chord went to), restores only after it, and past a ceiling leaves the
dictation on the clipboard instead of guessing.

The window lives on its own thread with its own message pump, so a reader is
never kept waiting on anything else Talk DAT! is doing. The window procedure
does the least it can: copy the text into global memory, record who asked,
set an event. It never takes the paste layer's lock (the paste thread holds
it while waiting here). Every Win32 call goes through private, typed DLL
handles (X-434, X-604), and the callback is pinned for the process lifetime.
"""
from __future__ import annotations

import ctypes
import logging
import os
import threading
import time
from typing import Any

log = logging.getLogger(__name__)

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
WM_RENDERFORMAT = 0x0305
WM_RENDERALLFORMATS = 0x0306
WM_DESTROYCLIPBOARD = 0x0307
HWND_MESSAGE = -3
ERROR_CLASS_ALREADY_EXISTS = 1410
CLASS_NAME = "TalkDatBorrowedClipboard"

#: How long the paste waits for the target to read. Past this, the dictation
#: stays on the clipboard: a missed restore costs the person their old
#: clipboard, a restore before the read pastes it into their document.
READ_CEILING_S = 2.0
#: After the read, before the restore. An app reading through OLE asks for one
#: format per call and may come back for another; the old fixed delay was
#: 0.2 s after the chord, so waiting 0.2 s after the read is never sooner.
READ_GRACE_S = 0.2

_KEEPALIVE: list[Any] = []


class BorrowedClipboard:
    """One hidden owner window; one borrowed clipboard at a time."""

    def __init__(self) -> None:
        from ctypes import wintypes

        self._wintypes = wintypes
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self._rendered = threading.Event()
        self._lost = threading.Event()
        self._text: str | None = None
        self._generation = 0
        self._reads: list[tuple[float, int]] = []
        self.rendered_sequence = 0
        self.hwnd = 0
        self._user32, self._kernel32 = self._dlls()
        self._thread = threading.Thread(target=self._run, name="TalkDatClipboardOwner", daemon=True)
        self._thread.start()
        self._ready.wait(2.0)

    # -- Win32 ---------------------------------------------------------------
    def _dlls(self) -> tuple[Any, Any]:
        wintypes = self._wintypes
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        lresult = ctypes.c_ssize_t
        self._WNDPROC = ctypes.WINFUNCTYPE(lresult, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

        class WNDCLASSW(ctypes.Structure):
            _fields_ = [
                ("style", wintypes.UINT),
                ("lpfnWndProc", self._WNDPROC),
                ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE),
                ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR),
            ]

        self._WNDCLASSW = WNDCLASSW
        user32.RegisterClassW.argtypes = (ctypes.POINTER(WNDCLASSW),)
        user32.RegisterClassW.restype = wintypes.ATOM
        user32.CreateWindowExW.argtypes = (
            wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int, ctypes.c_int,
            ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
        )
        user32.CreateWindowExW.restype = wintypes.HWND
        user32.DefWindowProcW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
        user32.DefWindowProcW.restype = lresult
        user32.GetMessageW.argtypes = (ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT)
        user32.GetMessageW.restype = wintypes.BOOL
        user32.TranslateMessage.argtypes = (ctypes.POINTER(wintypes.MSG),)
        user32.TranslateMessage.restype = wintypes.BOOL
        user32.DispatchMessageW.argtypes = (ctypes.POINTER(wintypes.MSG),)
        user32.DispatchMessageW.restype = lresult
        user32.OpenClipboard.argtypes = (wintypes.HWND,)
        user32.OpenClipboard.restype = wintypes.BOOL
        user32.CloseClipboard.argtypes = ()
        user32.CloseClipboard.restype = wintypes.BOOL
        user32.EmptyClipboard.argtypes = ()
        user32.EmptyClipboard.restype = wintypes.BOOL
        user32.SetClipboardData.argtypes = (wintypes.UINT, wintypes.HANDLE)
        user32.SetClipboardData.restype = wintypes.HANDLE
        user32.GetClipboardOwner.argtypes = ()
        user32.GetClipboardOwner.restype = wintypes.HWND
        user32.GetOpenClipboardWindow.argtypes = ()
        user32.GetOpenClipboardWindow.restype = wintypes.HWND
        user32.IsClipboardFormatAvailable.argtypes = (wintypes.UINT,)
        user32.IsClipboardFormatAvailable.restype = wintypes.BOOL
        user32.GetClipboardSequenceNumber.argtypes = ()
        user32.GetClipboardSequenceNumber.restype = wintypes.DWORD
        user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        kernel32.GetModuleHandleW.argtypes = (wintypes.LPCWSTR,)
        kernel32.GetModuleHandleW.restype = wintypes.HMODULE
        kernel32.GlobalAlloc.argtypes = (wintypes.UINT, ctypes.c_size_t)
        kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
        kernel32.GlobalLock.argtypes = (wintypes.HGLOBAL,)
        kernel32.GlobalLock.restype = wintypes.LPVOID
        kernel32.GlobalUnlock.argtypes = (wintypes.HGLOBAL,)
        kernel32.GlobalUnlock.restype = wintypes.BOOL
        kernel32.GlobalFree.argtypes = (wintypes.HGLOBAL,)
        kernel32.GlobalFree.restype = wintypes.HGLOBAL
        return user32, kernel32

    def _run(self) -> None:
        wintypes = self._wintypes
        try:
            proc = self._WNDPROC(self._window_proc)
            _KEEPALIVE.append(proc)  # Windows calls it for as long as the window lives
            hinstance = self._kernel32.GetModuleHandleW(None)
            # One class per owner: a class keeps the first window procedure it
            # was registered with, which would belong to another instance.
            class_name = f"{CLASS_NAME}-{id(self):x}"
            wndclass = self._WNDCLASSW()
            wndclass.lpfnWndProc = proc
            wndclass.hInstance = hinstance
            wndclass.lpszClassName = class_name
            _KEEPALIVE.append(wndclass)
            if not self._user32.RegisterClassW(ctypes.byref(wndclass)):
                if ctypes.get_last_error() != ERROR_CLASS_ALREADY_EXISTS:
                    raise OSError(ctypes.get_last_error(), "RegisterClassW failed")
            hwnd = self._user32.CreateWindowExW(
                0, class_name, "", 0, 0, 0, 0, 0, wintypes.HWND(HWND_MESSAGE), None, hinstance, None)
            if not hwnd:
                raise OSError(ctypes.get_last_error(), "CreateWindowExW failed")
            self.hwnd = int(hwnd)
        except Exception:
            log.warning("clipboard owner window unavailable; paste restores use the fixed delay", exc_info=True)
            self._ready.set()
            return
        self._ready.set()
        message = wintypes.MSG()
        while self._user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            self._user32.TranslateMessage(ctypes.byref(message))
            self._user32.DispatchMessageW(ctypes.byref(message))

    def _window_proc(self, hwnd: int, message: int, wparam: int, lparam: int) -> int:
        try:
            if message == WM_RENDERFORMAT:
                if int(wparam) == CF_UNICODETEXT:
                    self._render(requested=True)
                return 0
            if message == WM_RENDERALLFORMATS:
                # The window is going away while it still owns the clipboard:
                # put the text there for good so the next paste still works.
                if self._user32.OpenClipboard(hwnd):
                    try:
                        if self._user32.GetClipboardOwner() == hwnd:
                            self._render(requested=False)
                    finally:
                        self._user32.CloseClipboard()
                return 0
            if message == WM_DESTROYCLIPBOARD:
                with self._lock:
                    self._text = None
                self._lost.set()
                return 0
        except Exception:
            log.debug("clipboard owner message failed", exc_info=True)
        return self._user32.DefWindowProcW(hwnd, message, wparam, lparam)

    def _global_text(self, text: str) -> int:
        data = (text + "\0").encode("utf-16-le")
        handle = self._kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not handle:
            return 0
        pointer = self._kernel32.GlobalLock(handle)
        if not pointer:
            self._kernel32.GlobalFree(handle)
            return 0
        ctypes.memmove(pointer, data, len(data))
        self._kernel32.GlobalUnlock(handle)
        return int(handle)

    def _render(self, *, requested: bool) -> bool:
        """Hand the text over; the clipboard is open (by the reader, or by us)."""
        with self._lock:
            text, generation = self._text, self._generation
        if text is None:
            return False
        handle = self._global_text(text)
        if not handle:
            return False
        if not self._user32.SetClipboardData(CF_UNICODETEXT, handle):
            self._kernel32.GlobalFree(handle)
            return False
        reader_pid = 0
        if requested:
            reader = self._user32.GetOpenClipboardWindow()
            if reader:
                pid = self._wintypes.DWORD(0)
                self._user32.GetWindowThreadProcessId(reader, ctypes.byref(pid))
                reader_pid = int(pid.value)
        sequence = int(self._user32.GetClipboardSequenceNumber() or 0)
        with self._lock:
            if generation == self._generation:
                self._text = None  # rendered once; the data is the system's now
                self.rendered_sequence = sequence
                if requested:
                    self._reads.append((time.perf_counter(), reader_pid))
        if requested:
            self._rendered.set()
        return True

    # -- used by the paste layer ---------------------------------------------
    @property
    def available(self) -> bool:
        return bool(self.hwnd)

    def offer(self, text: str, mark_private: Any) -> int:
        """Put `text` on the clipboard as a promise. Returns the sequence number, or 0.

        `mark_private` adds X-604's local-only formats while the clipboard is
        open (they carry real data; only the text waits for a reader).
        """
        if not self.hwnd:
            return 0
        for _attempt in range(5):
            if self._user32.OpenClipboard(self.hwnd):
                break
            time.sleep(0.02)
        else:
            return 0
        try:
            if not self._user32.EmptyClipboard():
                return 0
            # EmptyClipboard sent WM_DESTROYCLIPBOARD for any earlier offer;
            # this one starts clean after it.
            with self._lock:
                self._generation += 1
                self._text = text
                self._reads = []
                self.rendered_sequence = 0
            self._rendered.clear()
            self._lost.clear()
            ctypes.set_last_error(0)
            self._user32.SetClipboardData(CF_UNICODETEXT, None)
            if ctypes.get_last_error():
                with self._lock:
                    self._text = None
                return 0
            mark_private()
        finally:
            self._user32.CloseClipboard()
        if self._user32.GetClipboardOwner() != self.hwnd or not self._user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
            return 0
        return int(self._user32.GetClipboardSequenceNumber() or 0)

    def wait_for_read(self, chord_at: float, target_pid: int, ceiling: float = READ_CEILING_S) -> str:
        """"read" (the target took it), "early" (someone else read first, so the
        target's read will be silent), "lost" (someone replaced the clipboard)
        or "none" (nobody read it before the ceiling)."""
        deadline = time.perf_counter() + max(0.0, ceiling)
        own_pid = os.getpid()
        while True:
            with self._lock:
                first = self._reads[0] if self._reads else None
            if first is not None:
                read_at, reader_pid = first
                if read_at < chord_at or reader_pid == own_pid:
                    return "early"
                if reader_pid and target_pid and reader_pid != target_pid:
                    return "early"
                return "read"
            if self._lost.is_set():
                return "lost"
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                return "none"
            self._rendered.wait(min(remaining, 0.05))

    def keep(self) -> bool:
        """Past the ceiling: turn the promise into real data and leave it there."""
        with self._lock:
            pending = self._text is not None
        if not pending or not self.hwnd:
            return True
        for _attempt in range(10):
            if self._user32.OpenClipboard(self.hwnd):
                break
            time.sleep(0.02)
        else:
            return False
        try:
            if self._user32.GetClipboardOwner() != self.hwnd:
                return False
            return self._render(requested=False)
        finally:
            self._user32.CloseClipboard()


_OWNER: BorrowedClipboard | None = None
_OWNER_LOCK = threading.Lock()


def borrowed_clipboard() -> BorrowedClipboard | None:
    """The process's owner window, started on first use; None where unavailable."""
    global _OWNER
    if os.name != "nt" or os.environ.get("TALK_DAT_PLAIN_CLIPBOARD") == "1":
        return None
    with _OWNER_LOCK:
        if _OWNER is None:
            try:
                _OWNER = BorrowedClipboard()
            except Exception:
                log.warning("clipboard owner unavailable", exc_info=True)
                return None
        return _OWNER if _OWNER.available else None


def process_of_window(hwnd: int) -> int:
    """The process id behind a window, or 0."""
    if os.name != "nt" or not hwnd:
        return 0
    try:
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        pid = wintypes.DWORD(0)
        user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))
        return int(pid.value)
    except Exception:
        return 0
