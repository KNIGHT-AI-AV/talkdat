"""Where the Pill's menu belongs: the Pill's own rectangle and its own monitor.

The owner, 2026-10-09: right-clicking the Pill on his second screen opened the
menu "off God knows where". That screen is ABOVE his primary (origin 704,-1440)
at 100% while the primary runs at 150%, so every rule here is about which
monitor and which pixel space:

* physical=True reads in per-monitor-aware (physical) pixels, the space the web
  menu's host window is placed in;
* physical=False reads in this process's own system-DPI space, the space Tk's
  event coordinates and geometry strings use.

Monitors come from the click point or the Pill's window, never from the
foreground application and never from the primary display alone. Every call
uses a PRIVATE user32 handle: setting argtypes on the shared ctypes.windll.user32
changed GetMonitorInfoW for the whole app once (X-605).
"""
from __future__ import annotations

import contextlib
import ctypes
import sys
from dataclasses import dataclass
from typing import Any

PER_MONITOR_AWARE_V2 = -4
MONITOR_DEFAULTTONEAREST = 2
MDT_EFFECTIVE_DPI = 0
GA_ROOT = 2

Rect = tuple[int, int, int, int]


@dataclass(frozen=True)
class PillWindow:
    """The Pill's window as Windows reports it, in physical pixels."""

    rect: Rect  # left, top, right, bottom
    work: Rect  # the work area of the monitor the window is on
    scale: float  # that monitor's own scale (1.0 = 100%)


def _user32() -> Any:
    return ctypes.WinDLL("user32", use_last_error=True)


@contextlib.contextmanager
def _pixel_space(user32: Any, physical: bool):
    """Read in physical pixels for the duration, restoring the thread after."""
    if not physical:
        yield
        return
    from ctypes import wintypes

    switch = user32.SetThreadDpiAwarenessContext
    switch.argtypes = (wintypes.HANDLE,)
    switch.restype = wintypes.HANDLE
    previous = switch(wintypes.HANDLE(PER_MONITOR_AWARE_V2))
    try:
        yield
    finally:
        if previous:
            switch(previous)


def _monitor_work_and_scale(user32: Any, monitor: Any) -> tuple[Rect, float] | None:
    from ctypes import wintypes

    class MonitorInfo(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("monitor", wintypes.RECT),
                    ("work", wintypes.RECT), ("flags", wintypes.DWORD)]

    info = MonitorInfo()
    info.size = ctypes.sizeof(info)
    user32.GetMonitorInfoW.argtypes = (wintypes.HANDLE, ctypes.POINTER(MonitorInfo))
    user32.GetMonitorInfoW.restype = wintypes.BOOL
    if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        return None
    work = (info.work.left, info.work.top, info.work.right, info.work.bottom)
    if work[2] <= work[0] or work[3] <= work[1]:
        return None
    with contextlib.suppress(AttributeError, OSError):
        # Review B12 (2026-10-10): the monitor's effective DPI is exact at any scale.
        # GetScaleFactorForMonitor answers from a fixed list (100, 120, 125, 140, 150,
        # ...), so a custom scale between two steps read as one of them, and read low
        # the menu's window came out shorter than its content. Like every DPI read it
        # answers in the thread's space: a per-monitor-aware thread gets the monitor's.
        dpi_x, dpi_y = ctypes.c_uint(), ctypes.c_uint()
        get_dpi = ctypes.WinDLL("shcore").GetDpiForMonitor
        get_dpi.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_uint))
        if get_dpi(monitor, MDT_EFFECTIVE_DPI, ctypes.byref(dpi_x), ctypes.byref(dpi_y)) == 0 and 96 <= dpi_x.value <= 480:
            return work, dpi_x.value / 96
    scale = 1.0
    with contextlib.suppress(AttributeError, OSError):
        factor = ctypes.c_int()
        get_factor = ctypes.WinDLL("shcore").GetScaleFactorForMonitor
        get_factor.argtypes = (wintypes.HANDLE, ctypes.POINTER(ctypes.c_int))
        if get_factor(monitor, ctypes.byref(factor)) == 0 and 100 <= factor.value <= 500:
            scale = factor.value / 100
    return work, scale


def work_area_at_point(x: int, y: int, *, physical: bool) -> tuple[Rect, float] | None:
    """(work area, scale) of the monitor holding (x, y), or the nearest one.

    A point left behind by an unplugged monitor resolves to the nearest monitor
    that still exists. None off Windows or when Windows cannot answer.
    """
    if sys.platform != "win32":
        return None
    try:
        from ctypes import wintypes

        user32 = _user32()
        with _pixel_space(user32, physical):
            user32.MonitorFromPoint.argtypes = (wintypes.POINT, wintypes.DWORD)
            user32.MonitorFromPoint.restype = wintypes.HANDLE
            monitor = user32.MonitorFromPoint(wintypes.POINT(int(x), int(y)), MONITOR_DEFAULTTONEAREST)
            if not monitor:
                return None
            return _monitor_work_and_scale(user32, monitor)
    except (AttributeError, OSError, TypeError, ValueError):
        return None


def cursor_position(*, physical: bool) -> tuple[int, int] | None:
    """Where the pointer is, in the requested pixel space, or None."""
    if sys.platform != "win32":
        return None
    try:
        from ctypes import wintypes

        user32 = _user32()
        with _pixel_space(user32, physical):
            point = wintypes.POINT()
            user32.GetCursorPos.argtypes = (ctypes.POINTER(wintypes.POINT),)
            user32.GetCursorPos.restype = wintypes.BOOL
            if not user32.GetCursorPos(ctypes.byref(point)):
                return None
            return int(point.x), int(point.y)
    except (AttributeError, OSError, TypeError, ValueError):
        return None


def read_pill_window(root: Any) -> PillWindow:
    """The Pill's top-level window in physical pixels, with its monitor.

    Raises OSError (or the ctypes errors) when Windows cannot answer; the caller
    falls back to the click point's monitor.
    """
    from ctypes import wintypes

    user32 = _user32()
    with _pixel_space(user32, True):
        user32.GetAncestor.argtypes = (wintypes.HWND, wintypes.UINT)
        user32.GetAncestor.restype = wintypes.HWND
        hwnd = user32.GetAncestor(root.winfo_id(), GA_ROOT)
        rect = wintypes.RECT()
        user32.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
        user32.GetWindowRect.restype = wintypes.BOOL
        if not hwnd or not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            raise OSError("the Pill window is unavailable")
        user32.MonitorFromWindow.argtypes = (wintypes.HWND, wintypes.DWORD)
        user32.MonitorFromWindow.restype = wintypes.HANDLE
        monitor = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
        found = _monitor_work_and_scale(user32, monitor) if monitor else None
        if found is None:
            raise OSError("the Pill's monitor is unavailable")
        return PillWindow(rect=(rect.left, rect.top, rect.right, rect.bottom), work=found[0], scale=found[1])


def pill_body_in_window(window_rect: Rect, envelope: Any, pill: Any) -> Rect:
    """The Pill's own (x, y, w, h) inside its window, in the window's pixels.

    While a message shows, the Pill's window is the message's envelope (X-742),
    which is wider than the Pill and can be offset from it. `envelope` and
    `pill` are that envelope and the Pill in Tk geometry; `window_rect` is the
    same window as Windows reports it. With no message, the window is the Pill.
    """
    left, top, right, bottom = (int(value) for value in window_rect)
    width, height = right - left, bottom - top
    env_w = getattr(envelope, "w", 0) or 0
    env_h = getattr(envelope, "h", 0) or 0
    if pill is None or env_w <= 0 or env_h <= 0:
        return left, top, width, height
    kx, ky = width / env_w, height / env_h
    return (round(left + (pill.x - envelope.x) * kx), round(top + (pill.y - envelope.y) * ky),
            round(pill.w * kx), round(pill.h * ky))
