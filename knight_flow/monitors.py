"""Which screen a pop-up should appear on.

Tk only ever describes the primary display: winfo_screenwidth reports the
primary's size, and centring against it puts every settings, update and history
window directly over whatever the person is working on. For a dictation tool
that is the wrong monitor by definition -- you are dictating *into* something on
the main screen, and a window that lands on top of it interrupts the task it is
supposed to support.

Windows knows about the others, so ask it. EnumDisplayMonitors reports every
monitor with both its full bounds and its work area (bounds minus taskbar and
docked bars), and a flag saying which one is primary.

Coordinates can be negative. A monitor placed above or to the left of the
primary has a negative origin -- on this machine the second screen sits at
y=-1440 -- so anything that assumes 0,0 is the top-left of the desktop will
compute an off-screen position and the window will simply not appear.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from dataclasses import dataclass

from . import mac_support

MONITORINFOF_PRIMARY = 0x00000001


@dataclass(frozen=True)
class Monitor:
    """One physical display.

    `work` excludes the taskbar; `bounds` does not. Placement uses `work` so a
    window is never positioned underneath a docked bar.
    """

    left: int
    top: int
    right: int
    bottom: int
    work_left: int
    work_top: int
    work_right: int
    work_bottom: int
    primary: bool

    @property
    def work_width(self) -> int:
        return max(1, self.work_right - self.work_left)

    @property
    def work_height(self) -> int:
        return max(1, self.work_bottom - self.work_top)


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class _MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_ulong),
        ("rcMonitor", _RECT),
        ("rcWork", _RECT),
        ("dwFlags", ctypes.c_ulong),
    ]


def list_monitors() -> list[Monitor]:
    """Every attached display, or an empty list off Windows or on failure.

    Callers must cope with an empty result rather than assuming at least one:
    this runs inside window placement, and a display-enumeration failure must
    degrade to Tk's own centring, never prevent a window from opening.
    """
    if sys.platform == "darwin":
        # NSScreen's visibleFrame already excludes the menu bar and the Dock,
        # which is exactly what `work` means to every caller here.
        return [
            Monitor(
                left=screen["x"],
                top=screen["y"],
                right=screen["x"] + screen["width"],
                bottom=screen["y"] + screen["height"],
                work_left=screen["work_x"],
                work_top=screen["work_y"],
                work_right=screen["work_x"] + screen["work_width"],
                work_bottom=screen["work_y"] + screen["work_height"],
                primary=screen["primary"],
            )
            for screen in mac_support.list_screens()
        ]
    if not sys.platform.startswith("win"):
        return []

    monitors: list[Monitor] = []
    callback_type = ctypes.WINFUNCTYPE(
        ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(_RECT), ctypes.c_double
    )

    def callback(handle, _hdc, _rect, _data):  # pragma: no cover - exercised via list_monitors
        info = _MONITORINFO()
        info.cbSize = ctypes.sizeof(_MONITORINFO)
        if ctypes.windll.user32.GetMonitorInfoW(handle, ctypes.byref(info)):
            monitors.append(
                Monitor(
                    left=info.rcMonitor.left,
                    top=info.rcMonitor.top,
                    right=info.rcMonitor.right,
                    bottom=info.rcMonitor.bottom,
                    work_left=info.rcWork.left,
                    work_top=info.rcWork.top,
                    work_right=info.rcWork.right,
                    work_bottom=info.rcWork.bottom,
                    primary=bool(info.dwFlags & MONITORINFOF_PRIMARY),
                )
            )
        return 1

    try:
        ctypes.windll.user32.EnumDisplayMonitors(None, None, callback_type(callback), 0)
    except Exception:
        return []
    return monitors


def preferred_monitor(monitors: list[Monitor], preference: str = "secondary") -> Monitor | None:
    """The display a pop-up should open on.

    "secondary" is the default because a window that covers the thing you are
    dictating into defeats the point. It falls back to the primary rather than
    refusing, so a single-monitor machine still gets a window.
    """
    if not monitors:
        return None
    choice = (preference or "secondary").strip().lower()
    if choice == "primary":
        return next((m for m in monitors if m.primary), monitors[0])
    if choice == "secondary":
        return next((m for m in monitors if not m.primary), None) or next(
            (m for m in monitors if m.primary), monitors[0]
        )
    return next((m for m in monitors if m.primary), monitors[0])


def centre_on(monitor: Monitor, width: int, height: int) -> tuple[int, int, int, int]:
    """Centre a window of this size on that display, clamped to its work area.

    Returns (width, height, x, y) because the size may need reducing to fit a
    smaller screen -- the second monitor is not always the larger one.
    """
    width = max(320, min(int(width), monitor.work_width - 32))
    height = max(220, min(int(height), monitor.work_height - 32))
    x = monitor.work_left + (monitor.work_width - width) // 2
    y = monitor.work_top + (monitor.work_height - height) // 2
    return width, height, x, y
