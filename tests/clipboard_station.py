"""Run a clipboard paste against a real Windows clipboard nobody else uses.

Find-more P0-4 (commandment 85) is about timing on the real clipboard, which
a fake DLL cannot show. The person's clipboard is off limits (a test must not
change the machine it runs on), and a hidden DESKTOP does not help: the
clipboard belongs to the window STATION, and every desktop in WinSta0 shares
his. So this creates a window station of its own, starts a copy of itself in
it, and that copy has a clipboard no other program on the machine can see.

Inside, a separate target process plays the app being pasted into: it waits
for the "chord" (the paste layer's Ctrl+V, replaced by a signal file, so no
key is ever sent anywhere), sleeps the scenario's delay, then reads the
clipboard the way an app handling Ctrl+V does.

    python tests/clipboard_station.py <read_after_ms> [early]    # prints one JSON report
    (read_after_ms < 0: the target never reads; "early": a clipboard manager
    in a third process reads the moment the clipboard changes)
"""
from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import tempfile
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CF_UNICODETEXT = 13


def _user32():
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.OpenClipboard.argtypes = (wintypes.HWND,)
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.CloseClipboard.restype = wintypes.BOOL
    user32.EmptyClipboard.restype = wintypes.BOOL
    user32.GetClipboardData.argtypes = (wintypes.UINT,)
    user32.GetClipboardData.restype = wintypes.HANDLE
    user32.SetClipboardData.argtypes = (wintypes.UINT, wintypes.HANDLE)
    user32.SetClipboardData.restype = wintypes.HANDLE
    user32.GetClipboardSequenceNumber.restype = wintypes.DWORD
    user32.CreateWindowExW.argtypes = (
        wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int, ctypes.c_int,
        ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID)
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.CreateWindowStationW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID)
    user32.CreateWindowStationW.restype = wintypes.HANDLE
    user32.GetProcessWindowStation.restype = wintypes.HANDLE
    user32.SetProcessWindowStation.argtypes = (wintypes.HANDLE,)
    user32.SetProcessWindowStation.restype = wintypes.BOOL
    user32.CreateDesktopW.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPVOID, wintypes.DWORD,
                                      wintypes.DWORD, wintypes.LPVOID)
    user32.CreateDesktopW.restype = wintypes.HANDLE
    user32.CloseDesktop.argtypes = (wintypes.HANDLE,)
    user32.CloseWindowStation.argtypes = (wintypes.HANDLE,)
    return user32


def _kernel32():
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GlobalAlloc.argtypes = (wintypes.UINT, ctypes.c_size_t)
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = (wintypes.HGLOBAL,)
    kernel32.GlobalLock.restype = wintypes.LPVOID
    kernel32.GlobalUnlock.argtypes = (wintypes.HGLOBAL,)
    return kernel32


def read_clipboard(user32, hwnd=None) -> str | None:
    kernel32 = _kernel32()
    for _attempt in range(50):
        if user32.OpenClipboard(hwnd):
            break
        time.sleep(0.02)
    else:
        return None
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return ""
        pointer = kernel32.GlobalLock(handle)
        try:
            return ctypes.wstring_at(pointer)
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def write_clipboard(user32, text: str) -> None:
    kernel32 = _kernel32()
    data = (text + "\0").encode("utf-16-le")
    handle = kernel32.GlobalAlloc(0x0002, len(data))
    pointer = kernel32.GlobalLock(handle)
    ctypes.memmove(pointer, data, len(data))
    kernel32.GlobalUnlock(handle)
    while not user32.OpenClipboard(None):
        time.sleep(0.02)
    try:
        user32.EmptyClipboard()
        user32.SetClipboardData(CF_UNICODETEXT, handle)
    finally:
        user32.CloseClipboard()


# -- the app being pasted into ---------------------------------------------------
def monitor(ready: Path) -> None:
    """A clipboard manager: reads the moment the clipboard changes, in its own process."""
    user32 = _user32()
    hwnd = user32.CreateWindowExW(0, "STATIC", "monitor", 0, 0, 0, 0, 0, wintypes.HWND(-3), None, None, None)
    seen = user32.GetClipboardSequenceNumber()
    ready.write_text("ready", encoding="utf-8")
    deadline = time.monotonic() + 20
    while user32.GetClipboardSequenceNumber() == seen and time.monotonic() < deadline:
        time.sleep(0.001)
    read_clipboard(user32, hwnd)


def target(delay_ms: int, ready: Path, signal: Path, result: Path) -> None:
    user32 = _user32()
    hwnd = user32.CreateWindowExW(0, "STATIC", "target", 0, 0, 0, 0, 0, wintypes.HWND(-3), None, None, None)
    ready.write_text(str(int(hwnd or 0)), encoding="utf-8")
    deadline = time.monotonic() + 20
    while not signal.exists() and time.monotonic() < deadline:
        time.sleep(0.005)
    if delay_ms < 0:
        result.write_text(json.dumps({"read": None}), encoding="utf-8")
        return
    time.sleep(delay_ms / 1000)
    result.write_text(json.dumps({"read": read_clipboard(user32, hwnd)}), encoding="utf-8")


# -- inside the private window station ---------------------------------------------
def inside(delay_ms: int, report: Path, early: bool = False) -> None:
    os.environ["TALK_DAT_PLAIN_CLIPBOARD"] = ""
    sys.path.insert(0, str(ROOT))
    from types import SimpleNamespace
    from unittest.mock import patch

    from knight_flow import paste

    user32 = _user32()
    work = Path(tempfile.mkdtemp(prefix="talkdat-clip-"))
    ready, signal, result = work / "ready", work / "signal", work / "result"
    write_clipboard(user32, "ABC-123")
    process = subprocess.Popen([sys.executable, __file__, "--target", str(delay_ms), str(ready), str(signal), str(result)],
                               cwd=str(ROOT))
    watcher = None
    if early:
        watching = work / "monitor-ready"
        watcher = subprocess.Popen([sys.executable, __file__, "--monitor", str(watching)], cwd=str(ROOT))
        deadline = time.monotonic() + 20
        while not watching.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
    deadline = time.monotonic() + 20
    while not ready.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    target_hwnd = int(ready.read_text(encoding="utf-8") or 0)
    keys = SimpleNamespace(hotkey=lambda *_keys: signal.write_text("chord", encoding="utf-8"), press=lambda *_a: None)
    started = time.perf_counter()
    with patch.object(paste, "pyautogui", keys), \
         patch.object(paste, "settle_modifiers", return_value=True), \
         patch.object(paste, "foreground_window_id", return_value=target_hwnd), \
         patch.object(paste, "foreground_is_remote_client", return_value=False):
        receipt = paste.paste_text_with_receipt("Hello there", restore_clipboard=True, paste_mode="clipboard")
    elapsed = time.perf_counter() - started
    process.wait(20)
    if watcher is not None:
        watcher.wait(20)
    read = json.loads(result.read_text(encoding="utf-8"))["read"] if result.exists() else "no result"
    report.write_text(json.dumps({
        "target_read": read,
        "clipboard_after": read_clipboard(user32),
        "success": receipt.success,
        "method": receipt.method,
        "elapsed_s": round(elapsed, 3),
    }), encoding="utf-8")


# -- the parent: make the station and run the copy in it ------------------------------
class STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR), ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR), ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD), ("dwXCountChars", wintypes.DWORD),
        ("dwYCountChars", wintypes.DWORD), ("dwFillAttribute", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD), ("lpReserved2", ctypes.POINTER(ctypes.c_byte)),
        ("hStdInput", wintypes.HANDLE), ("hStdOutput", wintypes.HANDLE), ("hStdError", wintypes.HANDLE),
    ]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE),
                ("dwProcessId", wintypes.DWORD), ("dwThreadId", wintypes.DWORD)]


def run(delay_ms: int, early: bool = False) -> dict:
    user32 = _user32()
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateProcessW.argtypes = (
        wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.LPVOID, wintypes.LPVOID, wintypes.BOOL, wintypes.DWORD,
        wintypes.LPVOID, wintypes.LPCWSTR, ctypes.POINTER(STARTUPINFOW), ctypes.POINTER(PROCESS_INFORMATION))
    kernel32.CreateProcessW.restype = wintypes.BOOL
    kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    # A named station is refused to an ordinary user here (error 5); an
    # unnamed one is allowed, and Windows gives it a name we read back.
    station = user32.CreateWindowStationW(None, 0, 0x37F, None)  # WINSTA_ALL_ACCESS
    if not station:
        raise OSError(ctypes.get_last_error(), "CreateWindowStationW failed")
    user32.GetUserObjectInformationW.argtypes = (wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD,
                                                 ctypes.POINTER(wintypes.DWORD))
    user32.GetUserObjectInformationW.restype = wintypes.BOOL
    buffer = ctypes.create_unicode_buffer(256)
    needed = wintypes.DWORD(0)
    if not user32.GetUserObjectInformationW(station, 2, buffer, ctypes.sizeof(buffer), ctypes.byref(needed)):  # UOI_NAME
        user32.CloseWindowStation(station)
        raise OSError(ctypes.get_last_error(), "the window station has no readable name")
    name = buffer.value
    desktop = None
    previous = user32.GetProcessWindowStation()
    try:
        if not user32.SetProcessWindowStation(station):
            raise OSError(ctypes.get_last_error(), "SetProcessWindowStation failed")
        try:
            desktop = user32.CreateDesktopW("Default", None, None, 0, 0x10000000, None)  # GENERIC_ALL
        finally:
            user32.SetProcessWindowStation(previous)
        if not desktop:
            raise OSError(ctypes.get_last_error(), "CreateDesktopW failed")
        report = Path(tempfile.mkdtemp(prefix="talkdat-clip-report-")) / "report.json"
        startup = STARTUPINFOW()
        startup.cb = ctypes.sizeof(STARTUPINFOW)
        startup.lpDesktop = f"{name}\\Default"
        info = PROCESS_INFORMATION()
        command = ctypes.create_unicode_buffer(
            subprocess.list2cmdline([sys.executable, str(Path(__file__).resolve()), "--inside", str(delay_ms), str(report)] + (["early"] if early else [])))
        if not kernel32.CreateProcessW(None, command, None, None, False, 0x08000000, None, str(ROOT),
                                       ctypes.byref(startup), ctypes.byref(info)):
            raise OSError(ctypes.get_last_error(), "CreateProcessW failed")
        try:
            kernel32.WaitForSingleObject(info.hProcess, 60000)
        finally:
            kernel32.CloseHandle(info.hThread)
            kernel32.CloseHandle(info.hProcess)
        if not report.exists():
            return {"error": "the paste inside the private window station wrote no report"}
        return json.loads(report.read_text(encoding="utf-8"))
    finally:
        if desktop:
            user32.CloseDesktop(desktop)
        user32.CloseWindowStation(station)


if __name__ == "__main__":
    if sys.argv[1] == "--target":
        target(int(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]), Path(sys.argv[5]))
    elif sys.argv[1] == "--monitor":
        monitor(Path(sys.argv[2]))
    elif sys.argv[1] == "--inside":
        inside(int(sys.argv[2]), Path(sys.argv[3]), "early" in sys.argv[4:])
    else:
        print(json.dumps(run(int(sys.argv[1]), "early" in sys.argv[2:])))
