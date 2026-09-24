"""Theme-aware renderer for Talk DAT!'s generated desktop icon family."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import sys

from PIL import Image, ImageColor, ImageOps


ICON_NAMES = frozenset(
    {
        "account",
        "captions",
        "chevron",
        "checkbox_off",
        "checkbox_on",
        "chill",
        "clarity",
        "close",
        "executive",
        "features",
        "drag_handle",
        "history",
        "mic_doctor",
        "microphone",
        "minimize",
        "offline",
        "pager",
        "paste",
        "power",
        "ramble",
        "resize_handle",
        "restart",
        "scratchpad",
        "scribe",
        "settings",
        "stats",
        "success",
        "theme",
        "translation",
        "update",
        "vocabulary",
        "warning",
    }
)


def _icon_root() -> Path:
    relative = Path("knight_flow") / "assets" / "ui" / "icons" / "imagegen-v1" / "runtime"
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        bundled = Path(bundle_root) / relative
        if bundled.exists():
            return bundled
    return Path(__file__).resolve().parents[1] / "assets" / "ui" / "icons" / "imagegen-v1" / "runtime"


def icon_asset_path(name: str) -> Path:
    key = str(name).strip().lower()
    if key not in ICON_NAMES:
        raise KeyError(f"Unknown Talk DAT! UI icon: {name!r}")
    return _icon_root() / f"{key}.png"


@lru_cache(maxsize=len(ICON_NAMES))
def _master(name: str) -> Image.Image:
    path = icon_asset_path(name)
    with Image.open(path) as source:
        return source.convert("RGBA")


def _luminance(color: str) -> float:
    channels = []
    for value in ImageColor.getrgb(color):
        value = value / 255.0
        channels.append(value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


@lru_cache(maxsize=2048)
def render_icon(
    name: str,
    size: int,
    primary: str,
    detail: str,
    *,
    rotate: int = 0,
    mirror: bool = False,
    opacity: int = 255,
) -> Image.Image:
    """Return a duotone RGBA icon that retains the master's material lift."""

    size = max(8, int(size))
    source = _master(name)
    if mirror:
        source = ImageOps.mirror(source)
    if rotate:
        source = source.rotate(int(rotate), resample=Image.Resampling.BICUBIC)

    primary = str(primary)
    detail = str(detail)
    dark, light = sorted((primary, detail), key=_luminance)
    grayscale = source.convert("L")
    tinted = ImageOps.colorize(grayscale, black=dark, white=light).convert("RGBA")
    alpha = source.getchannel("A")
    if int(opacity) != 255:
        alpha = alpha.point(lambda value: value * max(0, min(255, int(opacity))) // 255)
    tinted.putalpha(alpha)
    return tinted.resize((size, size), Image.Resampling.LANCZOS)


def clear_icon_caches() -> None:
    """Release decoded/rendered icon images after a palette or asset reload."""

    _master.cache_clear()
    render_icon.cache_clear()
