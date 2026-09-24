"""Bake temporal motion-blend into the mobile pill sprite sheets.

WHY: the pill material is a finely ribbed wave (branding/the-pill). On desktop
it plays at a rate where the ribs fuse into a shimmer. The phone plays the same
frames at ~15 fps idle (TalkDatPill.swift: 120 frames over 8 s), where each rib
is a crisp stripe for 66 ms -- the flow reads as strobing corduroy, and the
Reduce Motion / parked states freeze it outright. The owner's direction
(2026-08-29): keep the design, make it read as well on the phone as it does on
the desktop.

WHAT: each frame becomes what the eye would see of the desktop pill across one
phone-frame interval -- a weighted blend of the frame with its neighbours
(0.25 / 0.5 / 0.25, circular, so the loop stays seamless) plus a 1 px
horizontal gaussian to melt the rib edges at small sizes. Palette, silhouette,
frame count, grid and timing are untouched; no Swift changes.

Sheets processed (in place):
  mobile/targets/keyboard/flow-pill-120.webp  (120 frames, 12x10, 320x58)
  mobile/assets/flow-pill-240.webp            (240 frames, 16x15, 320x58)

Run from the repo root:  python scripts/soften_pill_sheets.py
A before/after strip is written next to each sheet for eyeballing.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parents[1]

SHEETS = [
    (ROOT / "mobile" / "targets" / "keyboard" / "flow-pill-120.webp", 12, 10),
    (ROOT / "mobile" / "assets" / "flow-pill-240.webp", 16, 15),
]

TEMPORAL = (0.25, 0.5, 0.25)  # previous, current, next
BLUR_RADIUS = 1.0             # px on the 320-wide frame; melts rib edges only


def frames_of(sheet: Image.Image, cols: int, rows: int) -> list[Image.Image]:
    fw, fh = sheet.width // cols, sheet.height // rows
    return [
        sheet.crop(((i % cols) * fw, (i // cols) * fh, (i % cols + 1) * fw, (i // cols + 1) * fh))
        for i in range(cols * rows)
    ]


def _canonical(frame: Image.Image) -> Image.Image:
    """Zero the RGB under fully transparent pixels before any blur.

    The PNG master keeps colored RGB in its alpha-0 halo; WebP zeroes it.
    Invisible RGB is undefined data, but a gaussian smears it into the visible
    edge -- so the same-looking input softens differently depending on which
    container it came from. Canonicalizing first makes the transform a pure
    function of what the eye can see, which is also what lets the guard verify
    the shipped sheet against the PNG master exactly.
    """
    r, g, b, a = frame.split()
    mask = a.point(lambda v: 255 if v > 0 else 0)
    zero = Image.new("L", frame.size, 0)
    return Image.merge("RGBA", (
        Image.composite(r, zero, mask),
        Image.composite(g, zero, mask),
        Image.composite(b, zero, mask),
        a,
    ))


def soften(frames: list[Image.Image]) -> list[Image.Image]:
    frames = [_canonical(f) for f in frames]
    n = len(frames)
    out = []
    for i in range(n):
        prev_w, cur_w, next_w = TEMPORAL
        blend = Image.blend(frames[(i - 1) % n], frames[i], cur_w / (prev_w + cur_w))
        blend = Image.blend(blend, frames[(i + 1) % n], next_w)
        out.append(blend.filter(ImageFilter.GaussianBlur(BLUR_RADIUS)))
    return out


def process(path: Path, cols: int, rows: int) -> None:
    sheet = Image.open(path).convert("RGBA")
    frames = frames_of(sheet, cols, rows)
    fw, fh = frames[0].size
    softened = soften(frames)
    rebuilt = Image.new("RGBA", sheet.size)
    for i, frame in enumerate(softened):
        rebuilt.paste(frame, ((i % cols) * fw, (i // cols) * fh))
    # Lossless, per the lesson recorded in test_the_pill_is_the_real_artwork:
    # lossy WebP plateaus near 3.7/255 on the saturated flute edges at ANY quality.
    rebuilt.save(path, format="WEBP", lossless=True, quality=100, method=6)

    strip = Image.new("RGBA", (fw * 2, fh * 2))
    strip.paste(frames[0].resize((fw * 2, fh)), (0, 0))
    strip.paste(softened[0].resize((fw * 2, fh)), (0, fh))
    strip.save(path.with_suffix(".before-after.png"))
    print(f"{path.name}: {len(frames)} frames softened; preview {path.with_suffix('.before-after.png').name}")


def main() -> int:
    for path, cols, rows in SHEETS:
        if not path.exists():
            print(f"missing sheet: {path}", file=sys.stderr)
            return 1
        process(path, cols, rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
