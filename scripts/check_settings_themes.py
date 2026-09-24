from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Read the palettes from the data module rather than overlay, so this gate needs no
# tkinter, no PIL, and no display, and can run on any CI runner.
from knight_flow.themes import SETTINGS_THEME_FAMILIES, SETTINGS_THEME_PALETTE_KEYS, SETTINGS_THEME_PALETTES


HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _rgb(color: str) -> tuple[float, float, float]:
    raw = color.lstrip("#")
    return tuple(int(raw[index : index + 2], 16) / 255 for index in (0, 2, 4))


def _channel(value: float) -> float:
    if value <= 0.03928:
        return value / 12.92
    return ((value + 0.055) / 1.055) ** 2.4


def _luminance(color: str) -> float:
    red, green, blue = (_channel(value) for value in _rgb(color))
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _contrast(foreground: str, background: str) -> float:
    first = _luminance(foreground)
    second = _luminance(background)
    light = max(first, second)
    dark = min(first, second)
    return (light + 0.05) / (dark + 0.05)


def main() -> int:
    failures: list[str] = []
    expected = {family for family in SETTINGS_THEME_FAMILIES}
    actual = set(SETTINGS_THEME_PALETTES)
    missing = expected - actual
    extra = actual - expected
    if missing:
        failures.append(f"missing theme families: {', '.join(sorted(missing))}")
    if extra:
        failures.append(f"unexpected theme families: {', '.join(sorted(extra))}")

    for family in SETTINGS_THEME_FAMILIES:
        modes = SETTINGS_THEME_PALETTES.get(family, {})
        for mode in ("Dark", "Light"):
            palette = modes.get(mode)
            label = f"{family} {mode}"
            if not palette:
                failures.append(f"{label}: missing palette")
                continue
            missing_keys = [key for key in SETTINGS_THEME_PALETTE_KEYS if key not in palette]
            if missing_keys:
                failures.append(f"{label}: missing keys {', '.join(missing_keys)}")
            for key in SETTINGS_THEME_PALETTE_KEYS:
                value = palette.get(key, "")
                if not HEX_RE.match(value):
                    failures.append(f"{label}: {key} is not #RRGGBB")
            if missing_keys:
                continue
            if _contrast(palette["text"], palette["panel"]) < 4.5:
                failures.append(f"{label}: text/panel contrast below 4.5")
            if _contrast(palette["text"], palette["field"]) < 4.5:
                failures.append(f"{label}: text/field contrast below 4.5")
            if _contrast(palette["text"], palette["button"]) < 4.5:
                failures.append(f"{label}: text/button contrast below 4.5")
            if _contrast(palette["muted"], palette["panel"]) < 3.0:
                failures.append(f"{label}: muted/panel contrast below 3.0")

    if failures:
        print("Settings theme check failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print(f"Settings theme check passed for {len(SETTINGS_THEME_FAMILIES) * 2} themes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
