"""Render at the monitor's real DPI instead of letting Windows stretch us.

The report that produced this module: "low-resolution ugliness" on another PC.
That machine runs display scaling above 100%, and this process never declared
DPI awareness -- so Windows rendered every window at 96 DPI and bitmap-stretched
the result. Blurry text, soft edges, the early-2000s look. Nothing about the
design was low resolution; the *pixels* were.

Two halves, and both are needed:

1. `enable_dpi_awareness()` -- tell Windows not to stretch us. Must run before
   the first window exists; awareness is process-wide and locked at first use.
2. `scale()` / `px()` / `apply_tk_scaling()` -- now that a pixel is a real
   pixel, everything sized in pixels is suddenly too small on a scaled
   display. Fonts fix themselves (`tk scaling` maps points to real pixels),
   but Canvas art, window geometry and PNG assets are pixel-sized by hand and
   must be multiplied.

**System-aware, deliberately not per-monitor-v2.** Tk 8.6 does not handle
WM_DPICHANGED, so under per-monitor awareness a window dragged to a monitor
with a different scale keeps its old pixel size -- wrong size, no notification,
no redraw. System-aware means: crisp at the primary monitor's scale, and on a
mismatched secondary monitor Windows falls back to stretching -- exactly the
behaviour every other Tk application ships with, and strictly better than
today on the machines that matter.
"""
from __future__ import annotations

from . import font_families

# Rebound at runtime by brand_font.apply_app_family; the literal keeps
# import free of GDI calls (they hang detached processes).
BRAND_UI_FAMILY = font_families.UI_FAMILY
BRAND_DISPLAY_FAMILY = font_families.UI_FAMILY

import logging
import sys
from typing import Any, TypeAlias

log = logging.getLogger(__name__)

_BASELINE_DPI = 96.0
_awareness_applied = False
_cached_scale: float | None = None

SpacingValue: TypeAlias = int | float | tuple[int | float, ...]
_LOGICAL_WINDOW_SIZE_UNITS = "logical-px-v1"


def _config_scale(config: dict[str, Any] | None = None) -> float | None:
    """Return a valid explicit scale without falling back to display DPI."""

    if config is None:
        return None
    try:
        candidate = config.get("ui", {}).get("scale")
        if candidate is None:
            return None
        override = float(candidate)
    except (AttributeError, TypeError, ValueError):
        return None
    if not override:
        return None
    return max(1.0, min(3.0, override))


def enable_dpi_awareness() -> bool:
    """Declare system-DPI awareness. Call before creating any window.

    Returns whether awareness is in effect. Never raises: a machine where the
    call fails simply keeps today's stretched-but-working rendering, which is
    the correct failure mode for something purely cosmetic.
    """
    global _awareness_applied, _cached_scale
    if _awareness_applied:
        return True
    if not sys.platform.startswith("win"):
        return False
    try:
        import ctypes

        try:
            # PROCESS_SYSTEM_DPI_AWARE = 1. See the module docstring for why
            # not 2 (per-monitor): Tk cannot follow WM_DPICHANGED.
            result = ctypes.windll.shcore.SetProcessDpiAwareness(1)
            if result == 0:
                _awareness_applied = True
            elif result in (-2147024891, 2147942405):
                # E_ACCESSDENIED only says some earlier source selected a mode.
                # A manifest can select PROCESS_DPI_UNAWARE too, so query the
                # process instead of treating every refusal as proof of DPI
                # awareness.
                current = ctypes.c_int(0)
                get_current_process = ctypes.windll.kernel32.GetCurrentProcess
                get_current_process.argtypes = []
                get_current_process.restype = ctypes.c_void_p
                get_process_awareness = ctypes.windll.shcore.GetProcessDpiAwareness
                get_process_awareness.argtypes = [
                    ctypes.c_void_p,
                    ctypes.POINTER(ctypes.c_int),
                ]
                # HRESULT is a 32-bit signed LONG even in a 64-bit process.
                get_process_awareness.restype = ctypes.c_long
                handle = get_current_process()
                query = get_process_awareness(
                    handle,
                    ctypes.byref(current),
                )
                _awareness_applied = query == 0 and current.value != 0
            else:
                _awareness_applied = False
        except (AttributeError, OSError):
            # Pre-8.1 fallback; same effect at system scope.
            _awareness_applied = bool(ctypes.windll.user32.SetProcessDPIAware())
    except Exception:
        log.debug("DPI awareness could not be applied", exc_info=True)
        return False
    if _awareness_applied:
        # scale() may have been queried during import before process awareness
        # was applied. Never preserve that provisional 1.0 result.
        _cached_scale = None
    return _awareness_applied


def system_dpi() -> float:
    """The effective DPI of the primary display, 96.0 when unknowable."""
    if not sys.platform.startswith("win"):
        return _BASELINE_DPI
    try:
        import ctypes

        try:
            return float(ctypes.windll.user32.GetDpiForSystem())
        except (AttributeError, OSError):
            pass
        hdc = ctypes.windll.user32.GetDC(0)
        try:
            LOGPIXELSX = 88
            value = ctypes.windll.gdi32.GetDeviceCaps(hdc, LOGPIXELSX)
        finally:
            ctypes.windll.user32.ReleaseDC(0, hdc)
        return float(value or _BASELINE_DPI)
    except Exception:
        return _BASELINE_DPI


def scale(config: dict[str, Any] | None = None) -> float:
    """The multiplier for hand-sized pixels. Cached after first read.

    Quarter-step rounding, because 1.5 and 1.25 are what Windows actually
    ships and a scale of 1.437 turns every even margin odd. Clamped so a
    corrupt override cannot produce an invisible or monitor-filling pill.
    An explicit `ui.scale` in the config wins -- the escape hatch for a
    display Windows misreports.
    """
    global _cached_scale
    override = _config_scale(config)
    if override:
        return max(1.0, min(3.0, override))
    if _cached_scale is None:
        raw = system_dpi() / _BASELINE_DPI if _awareness_applied else 1.0
        _cached_scale = max(1.0, min(3.0, round(raw * 4) / 4))
    return _cached_scale


def px(value: float, config: dict[str, Any] | None = None) -> int:
    """A hand-tuned 96-DPI pixel count, at this display's real scale."""
    return max(1, round(value * scale(config)))


def spacing(value: SpacingValue, config: dict[str, Any] | None = None) -> int | tuple[int, ...]:
    """Scale Tk padding while preserving a deliberate zero inset.

    Tk's point-font scaling does not scale numeric ``padx``/``pady`` values.
    That made text grow inside boxes whose breathing room stayed frozen.  This
    helper is the single conversion point for layout spacing, including the
    asymmetric two-value form accepted by ``pack`` and ``grid``.
    """

    def one(item: int | float) -> int:
        return 0 if float(item) == 0.0 else px(float(item), config)

    if isinstance(value, tuple):
        return tuple(one(item) for item in value)
    return one(value)


def scale_geometry(geometry: str, config: dict[str, Any] | None = None) -> str:
    """Scale the WxH part of a Tk geometry string; offsets pass through."""
    size, _, offsets = geometry.partition("+")
    if "x" not in size:
        return geometry
    try:
        width, height = (int(part) for part in size.split("x", 1))
    except ValueError:
        return geometry
    scaled = f"{px(width, config)}x{px(height, config)}"
    return f"{scaled}+{offsets}" if offsets else scaled


def window_size_receipt(
    width: int,
    height: int,
    config: dict[str, Any] | None = None,
) -> dict[str, int | str]:
    """Persist a resizable window in design-space units, not monitor pixels."""

    factor = scale(config)
    return {
        "width": max(1, round(int(width) / factor)),
        "height": max(1, round(int(height) / factor)),
        "units": _LOGICAL_WINDOW_SIZE_UNITS,
    }


def restore_window_size(
    saved: Any,
    config: dict[str, Any] | None = None,
) -> tuple[int, int] | None:
    """Restore new logical receipts and accept one-generation legacy strings."""

    if isinstance(saved, dict) and saved.get("units") == _LOGICAL_WINDOW_SIZE_UNITS:
        try:
            return px(int(saved["width"]), config), px(int(saved["height"]), config)
        except (KeyError, TypeError, ValueError):
            return None
    if isinstance(saved, str) and "x" in saved:
        try:
            width, height = (int(part) for part in saved.split("x", 1))
            return width, height
        except ValueError:
            return None
    return None


#: A window opens at no more than this share of the monitor's work area. A
#: person can still drag it larger; nothing may ARRIVE larger. 0.8 leaves the
#: desktop legible behind a setup wizard on a 4K panel and still gives a
#: settings window room on a laptop.
OPENING_SHARE_OF_WORK_AREA = 0.8


def clamp_to_work_area(
    width: int,
    height: int,
    work_area: tuple[int, int, int, int] | None,
    *,
    inset: int = 24,
    share: float = OPENING_SHARE_OF_WORK_AREA,
    config: dict[str, Any] | None = None,
) -> tuple[int, int]:
    """A window size that fits the monitor it is about to open on.

    Every size reaching a window has one of three origins, and all three can
    exceed the screen:

      * a hardcoded default tuned on somebody else's monitor;
      * a SAVED size, which was measured on whatever monitor and scale the
        person had last time -- they may since have changed either;
      * a size the app grew by itself to fit content.

    Nothing checked any of them. On a 4K panel at 150% this restored a
    1908x2091 onboarding window onto a 2066px work area: taller than the
    screen, which is what "the window that pops up is gigantic" looks like
    from the inside.

    Clamping belongs here rather than at each call site because all three
    origins funnel through one place, and a rule enforced in one of three
    paths is not a rule.
    """
    if not work_area:
        return max(1, int(width)), max(1, int(height))
    left, top, right, bottom = work_area
    room_w = max(1, int(right) - int(left) - px(inset, config) * 2)
    room_h = max(1, int(bottom) - int(top) - px(inset, config) * 2)
    ceiling_w = min(room_w, int(room_w * share) if share < 1 else room_w)
    ceiling_h = min(room_h, int(room_h * share) if share < 1 else room_h)
    return max(1, min(int(width), ceiling_w)), max(1, min(int(height), ceiling_h))


def apply_tk_scaling(root: Any, config: dict[str, Any] | None = None) -> None:
    """Make point-sized fonts render at the display's real DPI.

    Tk's `scaling` is pixels-per-point. Left at its default under a
    DPI-aware process, every font in the app renders at 96-DPI size on a
    display that is not 96 DPI -- crisp, but tiny. This one call is why the
    hundreds of existing `(BRAND_UI_FAMILY, 10)` tuples all come out right without
    being touched.
    """
    try:
        override = _config_scale(config)
        if sys.platform.startswith("win"):
            # Geometry and fonts must share the same effective scale.  Using
            # system_dpi() here ignored ui.scale overrides, so text and boxes
            # could move in opposite directions.
            target = (_BASELINE_DPI / 72.0) * scale(config)
        elif override is None:
            # Aqua already establishes the correct native/Retina Tk scale.
            # Replacing it with 96/72 made Mac text smaller than the platform
            # controls around it. If a live preference change removed an
            # earlier explicit override, restore that native baseline.
            baseline = getattr(root, "_talkdat_native_tk_scaling", None)
            if baseline is None:
                return
            target = float(baseline)
        else:
            # Remember the platform baseline so a second application of the
            # same override is idempotent instead of multiplying it again.
            baseline = getattr(root, "_talkdat_native_tk_scaling", None)
            if baseline is None:
                baseline = float(root.tk.call("tk", "scaling"))
                setattr(root, "_talkdat_native_tk_scaling", baseline)
            target = float(baseline) * override
        root.tk.call("tk", "scaling", target)
    except Exception:
        log.debug("tk scaling could not be applied", exc_info=True)


def reset_for_tests() -> None:
    global _awareness_applied, _cached_scale
    _awareness_applied = False
    _cached_scale = None
