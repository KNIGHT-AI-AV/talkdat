from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from typing import Any

_mutex_handle: Any = None
_lock_file: Any = None
ERROR_ALREADY_EXISTS = 183
MUTEX_NAME = "Local\\TalkDatSingleInstance"
LOCK_FILE_NAME = "talk-dat.lock"


def _already_running_mac() -> bool:
    """Hold an exclusive flock for the life of the process.

    The lock is a file in the app directory rather than a named mutex, and the
    handle is kept in a module global on purpose: closing it, or letting it be
    garbage collected, releases the lock and lets a second copy start. The
    kernel drops the lock when the process exits, including on a crash, so a
    stale lock file never blocks the next launch.
    """
    global _lock_file
    import fcntl

    from .config import app_dir

    # flock is held per open file description, not per process, so a second
    # open() here would collide with our own lock and report a duplicate that
    # does not exist.
    if _lock_file is not None:
        return False
    try:
        path = app_dir() / LOCK_FILE_NAME
        handle = open(path, "w")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return True
        _lock_file = handle
        return False
    except Exception:
        # A machine that cannot take the lock at all should still be able to
        # run the app; a duplicate window is a smaller failure than no app.
        return False


def _raise_the_running_copy_mac() -> None:
    """Bring the copy that is already running to the front, then let this one exit.

    An NSAlert was tried first and is wrong twice over. The app is LSUIElement,
    so a second launch is not the active application and its modal alert appears
    with no focus -- in practice invisible -- and `runModal` blocks until an
    alert nobody can see is dismissed. The second process then never reaches the
    `return` that was supposed to end it, and sits there holding a copy of the
    model in memory.

    Activating the original is also what a Mac user expects from launching a
    running app: the thing they wanted comes forward.
    """
    try:
        import os

        from AppKit import NSRunningApplication, NSWorkspace

        bundle_id = "com.knightaiav.talkdat"
        me = os.getpid()
        for app in NSRunningApplication.runningApplicationsWithBundleIdentifier_(bundle_id):
            if int(app.processIdentifier()) != me:
                app.activateWithOptions_(1 << 1)  # NSApplicationActivateIgnoringOtherApps
                return
        # Launched from a checkout rather than the bundle, so there is no bundle
        # id to match on. Nothing to raise; exiting quietly is still correct.
        NSWorkspace.sharedWorkspace()
    except Exception:
        pass


def already_running() -> bool:
    global _mutex_handle
    if sys.platform == "darwin":
        return _already_running_mac()
    if sys.platform != "win32":
        return False
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL

    ctypes.set_last_error(0)
    handle = kernel32.CreateMutexW(None, True, MUTEX_NAME)
    last_error = ctypes.get_last_error()
    if not handle:
        return False
    if last_error == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return True
    _mutex_handle = handle
    return False


def show_already_running_message() -> None:
    if sys.platform == "darwin":
        _raise_the_running_copy_mac()
        return
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.user32.MessageBoxW(
            None,
            # 2026-09-23: the product's name is "Talk DAT!" everywhere else, and
            # "the bottom overlay" is not a thing anyone calls the Pill.
            "Talk DAT! is already running. Look for the Pill at the bottom of your screen, "
            "or the Talk DAT! icon in the system tray.",
            "Talk DAT!",
            0x40,
        )
    except Exception:
        pass
