"""Derive the mobile icon set FROM THE REAL BRAND MASTER. Never draw one.

WHY THIS REPLACES `generate_app_icon.py`, which was a mistake.

That script RE-RENDERED the app icon: it sampled a few colours out of a 180px
web copy and drew fresh bars with them. It produced a flat, generic waveform —
nine plain rounded bars on a gradient — and shipped it as the brand. The real
mark was sitting in the repo the whole time at `knight_flow/assets/logo.png`:
1024x1024, 1.3 MB, a textured charcoal plate with five INSET bars, each with
its own vertical gradient, soft inner shadows and a rim highlight. The
generated file was 6 KB. Two hundred times smaller, because there was almost
nothing in it.

**Branding is not ours to regenerate.** The master is the master. If an icon
looks wrong, the answer is to find the real asset, never to approximate one
from sampled colours. This script therefore only ever RESIZES, CROPS, MASKS and
FLATTENS. It contains no drawing code at all, and that is the point.

MASTER: `knight_flow/assets/logo.png` — the icon the desktop app already ships.

## What each platform needs, and why the transforms differ

**iOS / the base `icon.png`** must be a full-bleed 1024x1024 square with NO
alpha; iOS applies its own superellipse mask. The master is a rounded plate
floating on transparency, so pasting it straight in gets DOUBLE-ROUNDED — the
plate's own corners sit inside Apple's mask and the icon reads as a small tile
with a border. So the plate is cropped to its own bounds and scaled to fill the
canvas, which lets Apple's mask cut the plate's corners instead. Residual
corner transparency is flattened onto the plate's own colour, sampled from the
plate, so nothing white ever shows through.

**Android adaptive foreground** is the opposite: Android masks aggressively and
only the central ~66% is guaranteed visible, so the mark is INSET rather than
full-bleed, on transparency, over the `backgroundColor` already in app.json.

**Monochrome** is a themed-icon silhouette: alpha only, no colour.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
MASTER = ROOT / "knight_flow" / "assets" / "logo.png"
ASSETS = ROOT / "mobile" / "assets"

SIZE = 1024
# Android guarantees only the central 66% of an adaptive icon is visible.
ANDROID_SAFE = 0.66
# The splash mark sits on a large empty screen, so it is smaller again.
SPLASH_SCALE = 0.58


def load_master() -> Image.Image:
    if not MASTER.exists():
        raise SystemExit("brand master missing: " + str(MASTER))
    return Image.open(MASTER).convert("RGBA")


def plate_only(master: Image.Image) -> Image.Image:
    """The mark cropped to its own bounds, with the transparent margin gone."""
    box = master.split()[-1].getbbox()
    if not box:
        raise SystemExit("master is fully transparent")
    return master.crop(box)


def plate_colour(plate: Image.Image) -> tuple[int, int, int]:
    """The plate's own ground, sampled from inside its edge.

    Sampled rather than hardcoded so a future master with a different ground
    still flattens correctly, and so nothing here encodes a brand colour of its
    own invention.
    """
    pixels = plate.convert("RGBA").load()
    width, height = plate.size
    samples = [
        pixels[width // 2, int(height * 0.06)],
        pixels[int(width * 0.06), height // 2],
        pixels[width // 2, int(height * 0.94)],
        pixels[int(width * 0.94), height // 2],
    ]
    opaque = [s for s in samples if s[3] > 200]
    if not opaque:
        raise SystemExit("could not sample the plate ground")
    return (
        sum(s[0] for s in opaque) // len(opaque),
        sum(s[1] for s in opaque) // len(opaque),
        sum(s[2] for s in opaque) // len(opaque),
    )


def write_ios_icon(plate: Image.Image) -> None:
    """Full-bleed, no alpha. Apple's mask does the rounding."""
    filled = plate.resize((SIZE, SIZE), Image.LANCZOS)
    ground = Image.new("RGBA", (SIZE, SIZE), plate_colour(plate) + (255,))
    ground.alpha_composite(filled)
    ground.convert("RGB").save(ASSETS / "icon.png")
    print("icon.png                    full-bleed plate, RGB, no alpha")


def write_inset(plate: Image.Image, name: str, scale: float) -> None:
    """The mark centred on transparency, inside the platform's safe zone."""
    edge = int(SIZE * scale)
    mark = plate.resize((edge, edge), Image.LANCZOS)
    canvas = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    offset = (SIZE - edge) // 2
    canvas.paste(mark, (offset, offset), mark)
    canvas.save(ASSETS / name)
    print("%-27s inset to %d%% of the canvas" % (name, round(scale * 100)))


def write_monochrome(plate: Image.Image) -> None:
    """A silhouette for Android themed icons: shape only, no colour."""
    edge = int(SIZE * ANDROID_SAFE)
    mark = plate.resize((edge, edge), Image.LANCZOS)
    silhouette = Image.new("RGBA", mark.size, (255, 255, 255, 0))
    silhouette.putalpha(mark.split()[-1])
    white = Image.new("RGBA", mark.size, (255, 255, 255, 255))
    white.putalpha(mark.split()[-1])
    canvas = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    offset = (SIZE - edge) // 2
    canvas.paste(white, (offset, offset), white)
    canvas.save(ASSETS / "android-icon-monochrome.png")
    print("android-icon-monochrome.png silhouette from the master's own alpha")


def write_favicon(plate: Image.Image) -> None:
    ground = Image.new("RGBA", plate.size, plate_colour(plate) + (255,))
    ground.alpha_composite(plate)
    ground.convert("RGB").resize((196, 196), Image.LANCZOS).save(ASSETS / "favicon.png")
    print("favicon.png                 196px, flattened")


def main() -> int:
    master = load_master()
    plate = plate_only(master)
    print("master: %s  %dx%d -> plate %dx%d"
          % (MASTER.relative_to(ROOT), *master.size, *plate.size))
    write_ios_icon(plate)
    write_inset(plate, "android-icon-foreground.png", ANDROID_SAFE)
    write_monochrome(plate)
    write_inset(plate, "splash-icon.png", SPLASH_SCALE)
    write_favicon(plate)
    return 0


if __name__ == "__main__":
    sys.exit(main())
