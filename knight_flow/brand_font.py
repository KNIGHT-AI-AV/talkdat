"""The Knight AI+AV display font, loaded process-private at startup.

The brand font ships as a bundled TTF (converted from the site's
`Knight AI+AV.woff2` -- the "Knight Display" face, deliberately NOT
"Knight Smoothie"). Windows makes it visible to this process only via
AddFontResourceExW(FR_PRIVATE), so nothing is installed system-wide and
uninstall leaves no trace.

Mac port notes: the equivalent is CTFontManagerRegisterFontsForURL with
kCTFontManagerScopeProcess; the family name inside the file is
"Knight AI+AV" on both platforms.
"""
from __future__ import annotations

import logging
import sys
from functools import lru_cache
from pathlib import Path

log = logging.getLogger(__name__)

FAMILY = "Knight AI+AV"
_FR_PRIVATE = 0x10


def _font_path() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    bundled = base / "knight_flow" / "assets" / "fonts" / "KnightDisplay.ttf"
    if bundled.exists():
        return bundled
    return Path(__file__).resolve().parent / "assets" / "fonts" / "KnightDisplay.ttf"


@lru_cache(maxsize=1)
def load_display_family() -> str | None:
    """Register the brand font for this process; return its family name.

    Returns None when the file is missing or the platform call fails --
    callers fall back to their existing system font, so a missing font can
    never break a window.
    """
    path = _font_path()
    if not path.exists():
        log.debug("brand font not bundled at %s", path)
        return None
    if sys.platform == "darwin":
        # The port this file's own header prescribes:
        # CTFontManagerRegisterFontsForURL with process scope -- nothing is
        # installed system-wide and nothing touches the user's font library,
        # the same contract AddFontResourceExW(FR_PRIVATE) gives Windows.
        try:
            from CoreText import (
                CTFontManagerRegisterFontsForURL,
                kCTFontManagerScopeProcess,
            )
            from CoreFoundation import CFURLCreateWithFileSystemPath, kCFURLPOSIXPathStyle

            url = CFURLCreateWithFileSystemPath(None, str(path), kCFURLPOSIXPathStyle, False)
            ok, error = CTFontManagerRegisterFontsForURL(url, kCTFontManagerScopeProcess, None)
            if ok or (error and "already registered" in repr(error).lower()):
                return FAMILY
            log.debug("CTFontManager refused %s: %r", path, error)
        except Exception:
            log.debug("brand font registration failed on macOS", exc_info=True)
        return None
    if not sys.platform.startswith("win"):
        return None
    try:
        import ctypes

        added = ctypes.windll.gdi32.AddFontResourceExW(str(path), _FR_PRIVATE, 0)
        if added > 0:
            return FAMILY
        log.debug("AddFontResourceExW returned 0 for %s", path)
    except Exception:
        log.debug("brand font registration failed", exc_info=True)
    return None


def ui_family() -> str:
    """The one family every widget uses: the brand face, or Segoe when the
    bundled font is missing. Module-callable so font literals across the UI
    resolve at widget-creation time without threading state."""
    if sys.platform == "darwin":
        from . import mac_support

        return load_display_family() or mac_support.FONT_UI
    return load_display_family() or "Segoe UI"


# No module-level registration: AddFontResourceExW at IMPORT time blocks
# in detached processes (unittest discovery in a background shell hung at
# exactly this call). Runtime resolution via apply_app_family is the path.


# X-83: display face vs TEXT face -- the pairing every real product uses.
# Measured: the Knight face sets 16% wider and 20% taller per line than the
# Segoe metrics every layout in this app was hand-tuned against, so using it
# for 9pt labels overflowed boxes and overlapped rows ("text does not scale
# to the boxes", "overlapping text"), and an unhinted display face at 9pt is
# thin and aliased on Windows. So the brand face now owns the sizes where it
# is actually seen -- titles, headers, big numbers -- and a text face carries
# the small copy. Choosing "knight" puts the brand face everywhere for anyone
# who wants it, layouts included.
APP_FONT_CHOICES = (
    ("system", "System sans (recommended)"),
    ("constantia", "Constantia (editorial serif)"),
    ("candara", "Candara (soft sans)"),
    ("knight", "Knight AI+AV everywhere"),
)
# Functional desktop UI follows the platform text face by default. Constantia
# remains available for people who deliberately want an editorial serif, but
# it no longer makes menus, keycaps, warnings and settings read like display
# copy on a fresh install. The layouts were originally tuned against Segoe UI,
# so this also returns the default to the metrics the controls were designed
# around.
DEFAULT_APP_FONT = "system"
# X-84's own Mac order: Constantia and Candara are not macOS stock faces.
# Palatino is the closest shipped serif to Constantia's metrics, Avenir Next
# to Candara's soft sans, and the system face is SF Pro.
_APP_FONT_FAMILIES = {
    "system": "Segoe UI",
    "constantia": "Constantia",
    "candara": "Candara",
} if sys.platform != "darwin" else {
    "system": "SF Pro Text",
    "constantia": "Palatino",
    "candara": "Avenir Next",
}
# Any label at or above this point size uses the brand display face.
DISPLAY_SIZE_FLOOR = 13


def resolve_app_family(config: dict | None) -> str:
    """The TEXT face: small copy, labels, buttons, table rows."""
    ui = (config or {}).get("ui") if isinstance(config, dict) else None
    choice = str((ui or {}).get("app_font", DEFAULT_APP_FONT)).lower()
    if choice == "knight":
        return load_display_family() or ui_family()
        return load_display_family() or "Segoe UI"
    return _APP_FONT_FAMILIES.get(choice, _APP_FONT_FAMILIES[DEFAULT_APP_FONT])


def resolve_display_family(config: dict | None) -> str:
    """The DISPLAY face: titles, section headers, hero numbers."""
    ui = (config or {}).get("ui") if isinstance(config, dict) else None
    choice = str((ui or {}).get("app_font", DEFAULT_APP_FONT)).lower()
    if choice in ("constantia", "candara"):
        # A chosen text face carries the whole app, headings included: one
        # voice reads as designed, two read as an accident.
        return _APP_FONT_FAMILIES[choice]
    return load_display_family() or "Segoe UI"


def apply_app_family(config: dict | None) -> str:
    """Re-point every module's font-family globals at the chosen faces.

    The UI builds font tuples from module globals at widget-creation time, so
    rebinding here + rebuilding a window is a complete, live font swap.
    """
    family = resolve_app_family(config)
    display = resolve_display_family(config)
    from . import overlay as overlay_module
    from . import ui_scale as ui_scale_module
    from .ui import flow_console as flow_console_module
    # Setup is a functional learning surface, not a branding canvas. It keeps
    # its platform UI face so a global editorial-font preference cannot turn
    # key labels, permission guidance and first-run controls into ornate copy.
    for module in (overlay_module, flow_console_module, ui_scale_module):
        module.BRAND_UI_FAMILY = family
        module.BRAND_DISPLAY_FAMILY = display
    return family
