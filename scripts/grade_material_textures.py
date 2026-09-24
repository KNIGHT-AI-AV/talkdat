#!/usr/bin/env python3
"""X-352: grade the generated material textures into gallery row strips.

The founder's rule: visual assets are IMAGE-GENERATED, then fitted with
real image-editing moves -- never hand-coded. The 25 family textures come
from the Codex seat (one per family); this script is the "editing to fit"
half: center-crop each into a wide strip, tint it toward the theme's
Dark/Light material colour, and normalize its mean luminance to the FLAT
material's -- that last step is what carries the WCAG ink law
(test_the_theme_gallery_is_material) onto photographic backgrounds.

Usage: python scripts/grade_material_textures.py <raw_dir>
Writes knight_flow/assets/materials/<slug>-<dark|light>.png (1280x176).
Idempotent and deterministic: same inputs, same bytes.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageEnhance

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from knight_flow.themes import (  # noqa: E402
    SETTINGS_THEME_PALETTES,
    relative_luminance,
    theme_material,
)

OUT = ROOT / "knight_flow" / "assets" / "materials"
STRIP = (1280, 176)  # 2x the 640x88 a 200%-scaled 44pt row needs
TINT = 0.42          # how far the texture leans into the theme's material


def _hex_rgb(colour: str) -> tuple[int, int, int]:
    value = colour.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _mean_luminance(image: Image.Image) -> float:
    small = image.resize((64, 16)).convert("RGB")
    pixels = list(small.getdata())
    return sum(relative_luminance("#%02x%02x%02x" % pixel) for pixel in pixels) / len(pixels)


def grade(raw: Image.Image, material: str) -> Image.Image:
    width, height = raw.size
    band_height = max(1, int(width * STRIP[1] / STRIP[0]))
    top = max(0, (height - band_height) // 2)
    strip = raw.crop((0, top, width, top + band_height)).resize(STRIP, Image.LANCZOS).convert("RGB")
    tint_layer = Image.new("RGB", STRIP, _hex_rgb(material))
    graded = Image.blend(strip, tint_layer, TINT)
    target = relative_luminance(material)
    for _ in range(6):
        current = _mean_luminance(graded)
        if abs(current - target) < 0.015:
            break
        # Luminance is non-linear in brightness; small proportional steps
        # converge quickly and deterministically.
        factor = ((target + 0.05) / (current + 0.05)) ** 0.6
        graded = ImageEnhance.Brightness(graded).enhance(max(0.4, min(2.2, factor)))
    return graded


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: grade_material_textures.py <raw_dir>")
        return 2
    raw_dir = Path(sys.argv[1])
    OUT.mkdir(parents=True, exist_ok=True)
    missing = []
    for family, modes in SETTINGS_THEME_PALETTES.items():
        slug = family.lower().replace(" ", "-")
        source = raw_dir / f"{slug}.png"
        if not source.is_file():
            missing.append(slug)
            continue
        raw = Image.open(source)
        for mode in ("Dark", "Light"):
            material = theme_material(modes[mode], mode)
            graded = grade(raw, material)
            target = OUT / f"{slug}-{mode.lower()}.png"
            graded.save(target, optimize=True)
            print(f"{target.name}: mean L {_mean_luminance(graded):.3f} vs flat {relative_luminance(material):.3f}")
    if missing:
        print(f"MISSING RAW TEXTURES: {missing}")
        return 1
    print(f"graded {len(SETTINGS_THEME_PALETTES) * 2} strips -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
