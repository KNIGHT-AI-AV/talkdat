from __future__ import annotations

"""Native outer-window chrome for Talk DAT!'s Tk surfaces.

Tk exposes the client ``TkChild`` handle through ``winfo_id()`` on Windows,
while DWM and window-region APIs operate on the visible outer ``TkTopLevel``
handle.  Keeping that translation and the pointer-sized ctypes declarations in
one module prevents individual menus from growing their own subtly different
window-shaping code.

Windows 11 can render antialiased corners in the compositor.  Windows 10
cannot: ``CreateRoundRectRgn`` is a one-bit clip and therefore always aliases.
Ordinary windows deliberately stay square there.  A legacy region remains
available only for genuinely shaped surfaces such as the microphone Pill.
"""

import ctypes
import functools
import sys
from dataclasses import dataclass
from ctypes import wintypes
from typing import Any, Protocol


UTILITY_CHROME = "utility"
AUXILIARY_CHROME = "auxiliary"
SQUARE_CHROME = "square"

DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWCP_ROUND = 2
DWMWCP_ROUNDSMALL = 3
DWMWCP_DONOTROUND = 1
WINDOWS_11_BUILD = 22_000

GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_TRANSPARENT = 0x00000020
WS_EX_NOACTIVATE = 0x08000000
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
MONITOR_DEFAULTTONEAREST = 2


class _MonitorInfo(ctypes.Structure):
    _fields_ = (
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    )


@dataclass(frozen=True)
class ChromeReceipt:
    """Exact native result cached on a mapped Tk Toplevel."""

    hwnd: int
    role: str
    mode: str
    preference: int


class ChromeApi(Protocol):
    """Small injectable boundary around the Win32 calls used by this policy."""

    def root_handle(self, client: int) -> int: ...

    def set_dwm_int(self, hwnd: int, attribute: int, value: int) -> bool: ...

    def get_dwm_int(self, hwnd: int, attribute: int) -> int | None: ...

    def create_round_region(self, width: int, height: int, diameter: int) -> int: ...

    def set_region(self, hwnd: int, region: int) -> bool: ...

    def delete_region(self, region: int) -> None: ...

    def get_extended_style(self, hwnd: int) -> int: ...

    def set_extended_style(self, hwnd: int, style: int) -> bool: ...

    def set_window_pos(
        self,
        hwnd: int,
        insert_after: int,
        x: int,
        y: int,
        width: int,
        height: int,
        flags: int,
    ) -> bool: ...

    def monitor_work_area(self, hwnd: int) -> tuple[int, int, int, int] | None: ...


class _CtypesChromeApi:
    """64-bit-safe bindings for the handful of Win32 chrome operations."""

    def __init__(self) -> None:
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
        self.dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)

        self.user32.GetAncestor.argtypes = (wintypes.HWND, wintypes.UINT)
        self.user32.GetAncestor.restype = wintypes.HWND
        self.user32.SetWindowRgn.argtypes = (wintypes.HWND, wintypes.HRGN, wintypes.BOOL)
        self.user32.SetWindowRgn.restype = ctypes.c_int
        self._get_window_long_ptr = getattr(
            self.user32,
            "GetWindowLongPtrW",
            self.user32.GetWindowLongW,
        )
        self._get_window_long_ptr.argtypes = (wintypes.HWND, ctypes.c_int)
        self._get_window_long_ptr.restype = ctypes.c_ssize_t
        self._set_window_long_ptr = getattr(
            self.user32,
            "SetWindowLongPtrW",
            self.user32.SetWindowLongW,
        )
        self._set_window_long_ptr.argtypes = (
            wintypes.HWND,
            ctypes.c_int,
            ctypes.c_ssize_t,
        )
        self._set_window_long_ptr.restype = ctypes.c_ssize_t
        self.user32.SetWindowPos.argtypes = (
            wintypes.HWND,
            wintypes.HWND,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.UINT,
        )
        self.user32.SetWindowPos.restype = wintypes.BOOL
        monitor_handle = getattr(wintypes, "HMONITOR", wintypes.HANDLE)
        self.user32.MonitorFromWindow.argtypes = (wintypes.HWND, wintypes.DWORD)
        self.user32.MonitorFromWindow.restype = monitor_handle
        self.user32.GetMonitorInfoW.argtypes = (
            monitor_handle,
            ctypes.POINTER(_MonitorInfo),
        )
        self.user32.GetMonitorInfoW.restype = wintypes.BOOL

        self.gdi32.CreateRoundRectRgn.argtypes = (
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
        )
        self.gdi32.CreateRoundRectRgn.restype = wintypes.HRGN
        self.gdi32.DeleteObject.argtypes = (wintypes.HGDIOBJ,)
        self.gdi32.DeleteObject.restype = wintypes.BOOL

        self.dwmapi.DwmSetWindowAttribute.argtypes = (
            wintypes.HWND,
            wintypes.DWORD,
            wintypes.LPCVOID,
            wintypes.DWORD,
        )
        self.dwmapi.DwmSetWindowAttribute.restype = ctypes.HRESULT
        self.dwmapi.DwmGetWindowAttribute.argtypes = (
            wintypes.HWND,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
        )
        self.dwmapi.DwmGetWindowAttribute.restype = ctypes.HRESULT

    def root_handle(self, client: int) -> int:
        return int(self.user32.GetAncestor(wintypes.HWND(client), 2)) or int(client)

    def set_dwm_int(self, hwnd: int, attribute: int, value: int) -> bool:
        payload = ctypes.c_int(int(value))
        result = self.dwmapi.DwmSetWindowAttribute(
            wintypes.HWND(hwnd),
            int(attribute),
            ctypes.byref(payload),
            ctypes.sizeof(payload),
        )
        return int(result) == 0

    def get_dwm_int(self, hwnd: int, attribute: int) -> int | None:
        payload = ctypes.c_int()
        result = self.dwmapi.DwmGetWindowAttribute(
            wintypes.HWND(hwnd),
            int(attribute),
            ctypes.byref(payload),
            ctypes.sizeof(payload),
        )
        return int(payload.value) if int(result) == 0 else None

    def create_round_region(self, width: int, height: int, diameter: int) -> int:
        return int(
            self.gdi32.CreateRoundRectRgn(
                0,
                0,
                max(1, int(width)) + 1,
                max(1, int(height)) + 1,
                max(1, int(diameter)),
                max(1, int(diameter)),
            )
            or 0
        )

    def set_region(self, hwnd: int, region: int) -> bool:
        return bool(
            self.user32.SetWindowRgn(
                wintypes.HWND(hwnd),
                wintypes.HRGN(region),
                False,
            )
        )

    def delete_region(self, region: int) -> None:
        self.gdi32.DeleteObject(wintypes.HGDIOBJ(region))

    def get_extended_style(self, hwnd: int) -> int:
        return int(self._get_window_long_ptr(wintypes.HWND(hwnd), GWL_EXSTYLE))

    def set_extended_style(self, hwnd: int, style: int) -> bool:
        ctypes.set_last_error(0)
        previous = int(
            self._set_window_long_ptr(
                wintypes.HWND(hwnd),
                GWL_EXSTYLE,
                ctypes.c_ssize_t(int(style)),
            )
        )
        return previous != 0 or ctypes.get_last_error() == 0

    def set_window_pos(
        self,
        hwnd: int,
        insert_after: int,
        x: int,
        y: int,
        width: int,
        height: int,
        flags: int,
    ) -> bool:
        return bool(
            self.user32.SetWindowPos(
                wintypes.HWND(hwnd),
                wintypes.HWND(insert_after),
                int(x),
                int(y),
                int(width),
                int(height),
                int(flags),
            )
        )

    def monitor_work_area(self, hwnd: int) -> tuple[int, int, int, int] | None:
        monitor = self.user32.MonitorFromWindow(
            wintypes.HWND(hwnd),
            MONITOR_DEFAULTTONEAREST,
        )
        if not monitor:
            return None
        info = _MonitorInfo()
        info.cbSize = ctypes.sizeof(_MonitorInfo)
        if not self.user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            return None
        work = info.rcWork
        if work.right <= work.left or work.bottom <= work.top:
            return None
        return int(work.left), int(work.top), int(work.right), int(work.bottom)


def _windows_build() -> int:
    try:
        return int(sys.getwindowsversion().build)
    except (AttributeError, OSError, ValueError):
        return 0


@functools.lru_cache(maxsize=1)
def _api() -> ChromeApi | None:
    if sys.platform != "win32":
        return None
    try:
        return _CtypesChromeApi()
    except (AttributeError, OSError):
        return None


def native_toplevel_handle(window: Any, *, api: ChromeApi | None = None) -> int:
    """Return the visible outer HWND, never Tk's inner client handle."""

    implementation = api or _api()
    if implementation is None:
        return 0
    try:
        client = int(window.winfo_id())
        return max(0, int(implementation.root_handle(client)))
    except Exception:
        return 0


def apply_window_chrome(
    window: Any,
    role: str,
    *,
    api: ChromeApi | None = None,
    platform_name: str | None = None,
    windows_build: int | None = None,
) -> ChromeReceipt:
    """Apply one stable outer-window policy and return the exact result.

    Non-shaped windows use DWM on Windows 11.  A failed or unavailable DWM
    request intentionally lands on a clean square window; it never falls back
    to an aliased GDI curve.  The receipt is keyed by the actual outer HWND so
    a Tk wrapper recreation is reapplied exactly once.
    """

    if role not in {UTILITY_CHROME, AUXILIARY_CHROME, SQUARE_CHROME}:
        raise ValueError(f"unknown window chrome role: {role}")
    platform_value = sys.platform if platform_name is None else str(platform_name)
    preference = {
        UTILITY_CHROME: DWMWCP_ROUND,
        AUXILIARY_CHROME: DWMWCP_ROUNDSMALL,
        SQUARE_CHROME: DWMWCP_DONOTROUND,
    }[role]
    implementation = api or (_api() if platform_value == "win32" else None)
    hwnd = native_toplevel_handle(window, api=implementation) if implementation else 0
    cached = getattr(window, "_talkdat_chrome_receipt", None)
    if (
        isinstance(cached, ChromeReceipt)
        and cached.hwnd == hwnd
        and cached.role == role
        and cached.mode != "retry"
    ):
        return cached

    if platform_value != "win32" or implementation is None or hwnd <= 0:
        receipt = ChromeReceipt(hwnd=hwnd, role=role, mode="square", preference=preference)
        window._talkdat_chrome_receipt = receipt
        return receipt

    build = _windows_build() if windows_build is None else int(windows_build)
    mode = "square"
    if build >= WINDOWS_11_BUILD:
        mode = "retry"
        try:
            applied = implementation.set_dwm_int(
                hwnd,
                DWMWA_WINDOW_CORNER_PREFERENCE,
                preference,
            )
            readback = implementation.get_dwm_int(
                hwnd,
                DWMWA_WINDOW_CORNER_PREFERENCE,
            )
            if applied and readback == preference:
                # This acknowledges the requested compositor preference; it is
                # not a claim that a physical capture is visibly rounded.
                mode = "square" if role == SQUARE_CHROME else "dwm_hint"
        except Exception:
            mode = "retry"

    receipt = ChromeReceipt(hwnd=hwnd, role=role, mode=mode, preference=preference)
    window._talkdat_chrome_receipt = receipt
    return receipt


def set_dwm_int_attribute(
    window: Any,
    attribute: int,
    value: int,
    *,
    api: ChromeApi | None = None,
) -> bool:
    """Set a DWM integer attribute on the exact visible outer HWND."""

    implementation = api or _api()
    hwnd = native_toplevel_handle(window, api=implementation) if implementation else 0
    if implementation is None or hwnd <= 0:
        return False
    try:
        return bool(implementation.set_dwm_int(hwnd, int(attribute), int(value)))
    except Exception:
        return False


def apply_no_activate_style(
    window: Any,
    *,
    click_through: bool = False,
    api: ChromeApi | None = None,
) -> bool:
    """Apply NOACTIVATE and optional click-through to one pointer-safe HWND."""

    implementation = api or _api()
    hwnd = native_toplevel_handle(window, api=implementation) if implementation else 0
    if implementation is None or hwnd <= 0:
        return False
    required = WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
    if click_through:
        required |= WS_EX_TRANSPARENT
    try:
        style = int(implementation.get_extended_style(hwnd)) | required
        if not implementation.set_extended_style(hwnd, style):
            return False
        if not implementation.set_window_pos(
            hwnd,
            0,
            0,
            0,
            0,
            0,
            SWP_NOSIZE
            | SWP_NOMOVE
            | SWP_NOZORDER
            | SWP_NOACTIVATE
            | SWP_FRAMECHANGED,
        ):
            return False
        return (int(implementation.get_extended_style(hwnd)) & required) == required
    except Exception:
        return False


def move_window_no_activate(
    window: Any,
    x: int,
    y: int,
    *,
    api: ChromeApi | None = None,
) -> bool:
    """Move an existing outer HWND without resizing, ordering, or activating."""

    implementation = api or _api()
    hwnd = native_toplevel_handle(window, api=implementation) if implementation else 0
    if implementation is None or hwnd <= 0:
        return False
    try:
        return bool(
            implementation.set_window_pos(
                hwnd,
                0,
                int(x),
                int(y),
                0,
                0,
                SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE,
            )
        )
    except Exception:
        return False


def monitor_work_area_for_window(
    window: Any,
    *,
    api: ChromeApi | None = None,
) -> tuple[int, int, int, int] | None:
    """Return the nearest monitor's work area for a mapped Tk surface."""

    implementation = api or _api()
    hwnd = native_toplevel_handle(window, api=implementation) if implementation else 0
    if implementation is None or hwnd <= 0:
        return None
    try:
        return implementation.monitor_work_area(hwnd)
    except Exception:
        return None


def apply_shaped_window_region(
    window: Any,
    width: int,
    height: int,
    radius: int,
    *,
    api: ChromeApi | None = None,
    platform_name: str | None = None,
) -> bool:
    """Apply the Pill's explicit shape to only the visible outer HWND.

    ``SetWindowRgn`` takes ownership only on success.  A failed transfer is the
    one case where this module must delete the newly created region itself.
    """

    platform_value = sys.platform if platform_name is None else str(platform_name)
    implementation = api or (_api() if platform_value == "win32" else None)
    if platform_value != "win32" or implementation is None:
        return False
    hwnd = native_toplevel_handle(window, api=implementation)
    if hwnd <= 0:
        return False
    region = 0
    try:
        region = int(
            implementation.create_round_region(
                max(1, int(width)),
                max(1, int(height)),
                max(1, int(radius)) * 2,
            )
        )
        if region <= 0:
            return False
        if implementation.set_region(hwnd, region):
            return True
    except Exception:
        pass
    if region > 0:
        try:
            implementation.delete_region(region)
        except Exception:
            pass
    return False


__all__ = [
    "AUXILIARY_CHROME",
    "ChromeReceipt",
    "DWMWA_WINDOW_CORNER_PREFERENCE",
    "DWMWCP_DONOTROUND",
    "DWMWCP_ROUND",
    "DWMWCP_ROUNDSMALL",
    "WS_EX_NOACTIVATE",
    "WS_EX_TOOLWINDOW",
    "WS_EX_TRANSPARENT",
    "UTILITY_CHROME",
    "SQUARE_CHROME",
    "WINDOWS_11_BUILD",
    "apply_no_activate_style",
    "apply_shaped_window_region",
    "apply_window_chrome",
    "monitor_work_area_for_window",
    "move_window_no_activate",
    "native_toplevel_handle",
    "set_dwm_int_attribute",
]
