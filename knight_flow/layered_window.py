from __future__ import annotations

"""Per-pixel alpha for the Pill on Windows (X-641).

The Pill used to reach the screen through a colour key: Tk blended every soft
pixel PIL drew over ``#010203``, Windows removed only the pixels that were
exactly ``#010203``, and a one-bit GDI region cut the rest to a capsule. So the
anti-aliased edge, the rim and the contact shadow all arrived as opaque
near-black pixels: a jagged black ring on any light desktop (polish audit
P0-1, 1,380 fringe pixels on the idle Pill).

``UpdateLayeredWindow`` with ``ULW_ALPHA`` takes a 32-bit premultiplied BGRA
bitmap and composites it per pixel, so a pixel at alpha 90 is 35 % of the Pill
over whatever is behind it. That is the whole fix; nothing about how PIL
composes the frame changes.

How a Tk toplevel behaves under it, measured on Tk 8.6.15 (the research probe
is summarised in docs/CODEX_LOG.md, X-641):

* Tk's ``-alpha`` and ``-transparentcolor`` use ``SetLayeredWindowAttributes``.
  After that call ``UpdateLayeredWindow`` fails with ERROR_INVALID_PARAMETER
  (87) until ``WS_EX_LAYERED`` is cleared and set again. Arming does exactly
  that, and one failed push re-arms once before giving up, so a later Tk
  attribute call costs one frame, not the Pill.
* ``-topmost``, ``lift``, geometry moves and resizes, ``minsize``,
  withdraw/deiconify and canvas changes keep the same outer HWND and keep the
  layered bitmap working. The outer HWND is still re-read on every push, so a
  recreated Tk wrapper is simply re-armed.
* Once pushed, the window shows only the bitmap: Tk's own canvas painting into
  it is not presented. The canvas stays as the event surface: its items and
  bindings still hit-test, which is how the update dot keeps its click.
* Hit testing follows alpha: a pixel at alpha 0 passes the click to whatever is
  underneath (``WindowFromPoint`` returns the window below), and any pixel
  above 0, even 1, catches it. ``WM_NCHITTEST`` returning ``HTTRANSPARENT``
  only passes a click to windows of the SAME thread, so it cannot make a soft
  shadow outside the Pill click-through for other apps. The Pill therefore
  keeps today's footprint exactly: its frame is clipped to an anti-aliased
  capsule of the window's size, the same shape the old region cut, with a
  smooth edge instead of a stepped one.

When a push fails for good (both tries), the Overlay hands the window back to
the colour key in the same frame (X-642); ``overlay.pill_per_pixel_alpha``
false in config.json keeps the colour key from the start.
"""

import ctypes
import functools
import sys
import weakref
from ctypes import wintypes
from typing import Any, Protocol

from PIL import Image, ImageDraw


GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
ULW_ALPHA = 0x00000002
AC_SRC_OVER = 0x00
AC_SRC_ALPHA = 0x01
DIB_RGB_COLORS = 0
BI_RGB = 0
RDW_INVALIDATE = 0x0001
RDW_ERASE = 0x0004
RDW_ALLCHILDREN = 0x0080
RDW_FRAME = 0x0400
#: present() could not run yet (Tk has not mapped the window): not a failure.
NOT_MAPPED = "no mapped outer window"


class LayeredApi(Protocol):
    """The Win32 calls the presenter needs; injectable so tests can fail them."""

    def root_handle(self, client: int) -> int: ...

    def get_extended_style(self, hwnd: int) -> int: ...

    def set_extended_style(self, hwnd: int, style: int) -> bool: ...

    def clear_region(self, hwnd: int) -> bool: ...

    def update_layered(self, hwnd: int, width: int, height: int, bgra: bytes, alpha: int) -> bool: ...

    def update_alpha(self, hwnd: int, alpha: int) -> bool: ...

    def invalidate(self, hwnd: int) -> bool: ...

    def close(self) -> None: ...


class _BlendFunction(ctypes.Structure):
    _fields_ = (
        ("BlendOp", ctypes.c_ubyte),
        ("BlendFlags", ctypes.c_ubyte),
        ("SourceConstantAlpha", ctypes.c_ubyte),
        ("AlphaFormat", ctypes.c_ubyte),
    )


class _BitmapInfoHeader(ctypes.Structure):
    _fields_ = (
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    )


class _CtypesLayeredApi:
    """64-bit-safe bindings, with one reusable DIB section per frame size.

    A frame is a memmove into bits the DIB section already owns plus one
    ``UpdateLayeredWindow``; the bitmap is only reallocated when the Pill's
    size changes (compact, active, a settings change), not per frame.
    """

    def __init__(self) -> None:
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
        user32, gdi32 = self.user32, self.gdi32

        user32.GetAncestor.argtypes = (wintypes.HWND, wintypes.UINT)
        user32.GetAncestor.restype = wintypes.HWND
        self._get_window_long_ptr = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
        self._get_window_long_ptr.argtypes = (wintypes.HWND, ctypes.c_int)
        self._get_window_long_ptr.restype = ctypes.c_ssize_t
        self._set_window_long_ptr = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
        self._set_window_long_ptr.argtypes = (wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t)
        self._set_window_long_ptr.restype = ctypes.c_ssize_t
        user32.SetWindowRgn.argtypes = (wintypes.HWND, wintypes.HRGN, wintypes.BOOL)
        user32.SetWindowRgn.restype = ctypes.c_int
        user32.RedrawWindow.argtypes = (wintypes.HWND, ctypes.c_void_p, wintypes.HRGN, wintypes.UINT)
        user32.RedrawWindow.restype = wintypes.BOOL
        user32.GetDC.argtypes = (wintypes.HWND,)
        user32.GetDC.restype = wintypes.HDC
        user32.ReleaseDC.argtypes = (wintypes.HWND, wintypes.HDC)
        user32.ReleaseDC.restype = ctypes.c_int
        user32.UpdateLayeredWindow.argtypes = (
            wintypes.HWND,
            wintypes.HDC,
            ctypes.POINTER(wintypes.POINT),
            ctypes.POINTER(wintypes.SIZE),
            wintypes.HDC,
            ctypes.POINTER(wintypes.POINT),
            wintypes.COLORREF,
            ctypes.POINTER(_BlendFunction),
            wintypes.DWORD,
        )
        user32.UpdateLayeredWindow.restype = wintypes.BOOL
        gdi32.CreateCompatibleDC.argtypes = (wintypes.HDC,)
        gdi32.CreateCompatibleDC.restype = wintypes.HDC
        gdi32.DeleteDC.argtypes = (wintypes.HDC,)
        gdi32.DeleteDC.restype = wintypes.BOOL
        gdi32.CreateDIBSection.argtypes = (
            wintypes.HDC,
            ctypes.c_void_p,
            wintypes.UINT,
            ctypes.POINTER(ctypes.c_void_p),
            wintypes.HANDLE,
            wintypes.DWORD,
        )
        gdi32.CreateDIBSection.restype = wintypes.HBITMAP
        gdi32.SelectObject.argtypes = (wintypes.HDC, wintypes.HGDIOBJ)
        gdi32.SelectObject.restype = wintypes.HGDIOBJ
        gdi32.DeleteObject.argtypes = (wintypes.HGDIOBJ,)
        gdi32.DeleteObject.restype = wintypes.BOOL

        self._dc = 0
        self._bitmap = 0
        self._previous = 0
        self._bits = ctypes.c_void_p()
        self._size = (0, 0)

    def root_handle(self, client: int) -> int:
        return int(self.user32.GetAncestor(wintypes.HWND(client), 2) or 0) or int(client)

    def get_extended_style(self, hwnd: int) -> int:
        return int(self._get_window_long_ptr(wintypes.HWND(hwnd), GWL_EXSTYLE))

    def set_extended_style(self, hwnd: int, style: int) -> bool:
        ctypes.set_last_error(0)
        previous = int(
            self._set_window_long_ptr(wintypes.HWND(hwnd), GWL_EXSTYLE, ctypes.c_ssize_t(int(style)))
        )
        return previous != 0 or ctypes.get_last_error() == 0

    def clear_region(self, hwnd: int) -> bool:
        # A NULL region removes the one-bit capsule the colour-key path set.
        return bool(self.user32.SetWindowRgn(wintypes.HWND(hwnd), None, False))

    def _surface(self, width: int, height: int) -> bool:
        if self._dc and self._bitmap and self._size == (width, height):
            return True
        self._release_bitmap()
        if not self._dc:
            self._dc = int(self.gdi32.CreateCompatibleDC(None) or 0)
            if not self._dc:
                return False
        header = _BitmapInfoHeader()
        header.biSize = ctypes.sizeof(_BitmapInfoHeader)
        header.biWidth = int(width)
        header.biHeight = -int(height)  # top-down, the row order PIL writes
        header.biPlanes = 1
        header.biBitCount = 32
        header.biCompression = BI_RGB
        bits = ctypes.c_void_p()
        bitmap = int(
            self.gdi32.CreateDIBSection(
                self._dc, ctypes.byref(header), DIB_RGB_COLORS, ctypes.byref(bits), None, 0
            )
            or 0
        )
        if not bitmap or not bits.value:
            if bitmap:
                self.gdi32.DeleteObject(bitmap)
            return False
        self._previous = int(self.gdi32.SelectObject(self._dc, bitmap) or 0)
        self._bitmap = bitmap
        self._bits = bits
        self._size = (int(width), int(height))
        return True

    def update_layered(self, hwnd: int, width: int, height: int, bgra: bytes, alpha: int) -> bool:
        width, height = int(width), int(height)
        if width <= 0 or height <= 0 or len(bgra) != width * height * 4:
            return False
        if not self._surface(width, height):
            return False
        ctypes.memmove(self._bits, bgra, len(bgra))
        blend = _BlendFunction(AC_SRC_OVER, 0, max(0, min(255, int(alpha))), AC_SRC_ALPHA)
        size = wintypes.SIZE(width, height)
        source = wintypes.POINT(0, 0)
        # pptDst NULL: Tk owns the position (DPI- and monitor-aware geometry);
        # this call only replaces what the window shows.
        return bool(
            self.user32.UpdateLayeredWindow(
                wintypes.HWND(hwnd),
                None,
                None,
                ctypes.byref(size),
                self._dc,
                ctypes.byref(source),
                0,
                ctypes.byref(blend),
                ULW_ALPHA,
            )
        )

    def update_layered_at(
        self, hwnd: int, x: int, y: int, width: int, height: int, bgra: bytes, alpha: int
    ) -> bool:
        """Move, resize and repaint in ONE call (X-742, the Pill lengthening).

        A Tk geometry change then a separate push leaves a moment where the
        window has its new rectangle and its old bitmap: one frame of the Pill
        drawn in the wrong place. UpdateLayeredWindow with pptDst and psize
        applies the rectangle and the pixels together.
        """
        width, height = int(width), int(height)
        if width <= 0 or height <= 0 or len(bgra) != width * height * 4:
            return False
        if not self._surface(width, height):
            return False
        ctypes.memmove(self._bits, bgra, len(bgra))
        blend = _BlendFunction(AC_SRC_OVER, 0, max(0, min(255, int(alpha))), AC_SRC_ALPHA)
        size = wintypes.SIZE(width, height)
        destination = wintypes.POINT(int(x), int(y))
        source = wintypes.POINT(0, 0)
        return bool(
            self.user32.UpdateLayeredWindow(
                wintypes.HWND(hwnd),
                None,
                ctypes.byref(destination),
                ctypes.byref(size),
                self._dc,
                ctypes.byref(source),
                0,
                ctypes.byref(blend),
                ULW_ALPHA,
            )
        )

    def update_alpha(self, hwnd: int, alpha: int) -> bool:
        # The hover fade: only the constant alpha changes, the bitmap is kept.
        blend = _BlendFunction(AC_SRC_OVER, 0, max(0, min(255, int(alpha))), AC_SRC_ALPHA)
        return bool(
            self.user32.UpdateLayeredWindow(
                wintypes.HWND(hwnd), None, None, None, None, None, 0, ctypes.byref(blend), ULW_ALPHA
            )
        )

    def invalidate(self, hwnd: int) -> bool:
        # Queued, not synchronous: Tk repaints the canvas from its own loop.
        flags = RDW_INVALIDATE | RDW_ERASE | RDW_FRAME | RDW_ALLCHILDREN
        return bool(self.user32.RedrawWindow(wintypes.HWND(hwnd), None, None, flags))

    def _release_bitmap(self) -> None:
        if self._bitmap:
            if self._dc and self._previous:
                self.gdi32.SelectObject(self._dc, self._previous)
            self.gdi32.DeleteObject(self._bitmap)
        self._bitmap = 0
        self._previous = 0
        self._bits = ctypes.c_void_p()
        self._size = (0, 0)

    def close(self) -> None:
        self._release_bitmap()
        if self._dc:
            self.gdi32.DeleteDC(self._dc)
        self._dc = 0


def _default_api() -> LayeredApi | None:
    if sys.platform != "win32":
        return None
    try:
        return _CtypesLayeredApi()
    except (AttributeError, OSError):
        return None


def premultiplied_bgra(image: Image.Image) -> bytes:
    """The frame as ULW wants it: top-down BGRA, colour premultiplied by alpha."""
    rgba = image if image.mode == "RGBA" else image.convert("RGBA")
    try:
        # Pillow's "BGRa" packer premultiplies and swaps in C: 0.17 ms for a
        # 288 x 53 Pill here, against ~1 ms for the same work in numpy.
        return rgba.tobytes("raw", "BGRa")
    except (ValueError, KeyError):
        import numpy as np

        pixels = np.asarray(rgba, dtype=np.uint16)
        alpha = pixels[..., 3:4]
        premultiplied = (pixels[..., :3] * alpha + 127) // 255
        out = np.empty(pixels.shape, dtype=np.uint8)
        out[..., 0] = premultiplied[..., 2]
        out[..., 1] = premultiplied[..., 1]
        out[..., 2] = premultiplied[..., 0]
        out[..., 3] = pixels[..., 3]
        return out.tobytes()


@functools.lru_cache(maxsize=16)
def capsule_alpha_mask(width: int, height: int) -> Image.Image:
    """An anti-aliased capsule the size of the window: the old region, smooth.

    The colour-key path cut the window to ``CreateRoundRectRgn`` over its full
    size. Keeping that footprint means a click lands on exactly the pixels it
    always did, and a glow that reaches the window's edge fades along the
    Pill's curve instead of stopping at a straight rectangle side.
    """
    width, height = max(1, int(width)), max(1, int(height))
    scale = 4
    mask = Image.new("L", (width * scale, height * scale), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, width * scale - 1, height * scale - 1),
        radius=max(1, (height * scale) // 2),
        fill=255,
    )
    # BOX is an exact area average: each pixel's alpha is its coverage.
    return mask.resize((width, height), Image.Resampling.BOX)


class LayeredPresenter:
    """Pushes composed Pill frames to one Tk toplevel with per-pixel alpha."""

    def __init__(self, window: Any, *, api: LayeredApi | None = None) -> None:
        self.window = window
        self.api = api if api is not None else _default_api()
        self.hwnd = 0
        self.alpha = 255
        self.frames = 0
        self.last_error = ""
        if self.api is not None:
            # The memory DC and DIB section are GDI objects; a test suite
            # builds hundreds of Pills, so they go back with the presenter.
            weakref.finalize(self, self.api.close)

    @property
    def armed(self) -> bool:
        return self.hwnd > 0

    def _outer_handle(self) -> int:
        if self.api is None:
            return 0
        try:
            if not self.armed and not bool(self.window.winfo_ismapped()):
                # Before Tk first maps the root there is no wrapper HWND to own
                # yet. Once armed, a withdrawn Pill (fullscreen media, hide())
                # keeps its wrapper and keeps receiving frames, so it is
                # current the instant it is shown again.
                return 0
            return max(0, int(self.api.root_handle(int(self.window.winfo_id()))))
        except Exception:
            return 0

    def _arm(self, hwnd: int) -> None:
        # Clear then set: Tk's -alpha/-transparentcolor went through
        # SetLayeredWindowAttributes, which blocks UpdateLayeredWindow (87)
        # until the layering bit is toggled.
        style = int(self.api.get_extended_style(hwnd))
        self.api.set_extended_style(hwnd, style & ~WS_EX_LAYERED)
        self.api.set_extended_style(hwnd, style | WS_EX_LAYERED)
        self.api.clear_region(hwnd)
        self.hwnd = hwnd

    def present(self, image: Image.Image, position: tuple[int, int] | None = None) -> bool:
        """Show `image` (window-sized RGBA). False when the frame did not land.

        With ``position`` the window takes the image's size at that screen
        point in the same call (the lengthened Pill, X-742); without it Tk owns
        the rectangle, as it always has.
        """
        hwnd = self._outer_handle()
        if hwnd <= 0:
            self.last_error = NOT_MAPPED
            return False
        width, height = image.size
        move = position is not None and hasattr(self.api, "update_layered_at")

        def push() -> bool:
            if move:
                return bool(self.api.update_layered_at(hwnd, int(position[0]), int(position[1]),
                                                       width, height, data, self.alpha))
            return bool(self.api.update_layered(hwnd, width, height, data, self.alpha))

        try:
            data = premultiplied_bgra(image)
            if hwnd != self.hwnd:
                self._arm(hwnd)
            if push():
                self.frames += 1
                return True
            # Something called SetLayeredWindowAttributes since the last frame
            # (a Tk -alpha, a test harness): re-arm once and retry.
            self._arm(hwnd)
            if push():
                self.frames += 1
                return True
            self.last_error = f"error {ctypes.get_last_error()}"
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
        return False

    def set_alpha(self, alpha: float) -> bool:
        """The window-wide opacity (the hover fade), applied without a new bitmap."""
        self.alpha = max(0, min(255, int(round(float(alpha) * 255.0))))
        if not self.armed:
            return True
        try:
            return bool(self.api.update_alpha(self.hwnd, self.alpha))
        except Exception:
            return False

    def release(self) -> None:
        """Hand the window back to Tk's own layering (the colour key, X-642).

        The layered bit is toggled, not removed. Tk remembers that it layered
        the window and never sets the bit again, so with the bit cleared its
        -transparentcolor and -alpha fail underneath (measured: error 87, no
        key, a window with no transparency at all). Clear-then-set drops the
        UpdateLayeredWindow bitmap and leaves a layered window that Tk's
        SetLayeredWindowAttributes can take over; the repaint request makes Tk
        draw the canvas into it again.
        """
        hwnd = self.hwnd
        self.hwnd = 0
        if self.api is None:
            return
        try:
            if hwnd > 0:
                style = int(self.api.get_extended_style(hwnd))
                self.api.set_extended_style(hwnd, style & ~WS_EX_LAYERED)
                self.api.set_extended_style(hwnd, style | WS_EX_LAYERED)
                self.api.invalidate(hwnd)
        except Exception:
            pass
        try:
            self.api.close()
        except Exception:
            pass


__all__ = [
    "LayeredApi",
    "LayeredPresenter",
    "NOT_MAPPED",
    "WS_EX_LAYERED",
    "capsule_alpha_mask",
    "premultiplied_bgra",
]
