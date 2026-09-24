from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageChops, ImageEnhance, ImageFilter, ImageOps


ROOT = Path(__file__).resolve().parents[1]
ASSET_DIR = ROOT / "knight_flow" / "assets"
BRAND_DIR = ROOT / "branding" / "the-pill"
SOURCE = BRAND_DIR / "loading-spectrum-source.png"
MASTER = BRAND_DIR / "loading-spectrum-master-4k.png"
BASE_SHEET = ASSET_DIR / "flow_pill_240.png"
BASE_META = ASSET_DIR / "flow_pill_240.json"
OUTPUT_SHEET = ASSET_DIR / "loading_pill_240.png"
OUTPUT_META = ASSET_DIR / "loading_pill_240.json"


def _shift_hue(image: Image.Image, amount: int) -> Image.Image:
    hue, saturation, value = image.convert("HSV").split()
    hue = hue.point([(index + amount) % 256 for index in range(256)])
    return Image.merge("HSV", (hue, saturation, value)).convert("RGB")


def _frame(sheet: Image.Image, index: int, width: int, height: int, columns: int) -> Image.Image:
    x = (index % columns) * width
    y = (index // columns) * height
    return sheet.crop((x, y, x + width, y + height)).convert("RGBA")


def main() -> None:
    metadata = json.loads(BASE_META.read_text(encoding="utf-8"))
    columns = int(metadata["columns"])
    frame_count = int(metadata["frame_count"])
    frame_width = int(metadata["frame_width"])
    frame_height = int(metadata["frame_height"])
    rows = (frame_count + columns - 1) // columns

    source = Image.open(SOURCE).convert("RGB")
    master = ImageOps.fit(source, (3840, 1632), method=Image.Resampling.LANCZOS)
    master = master.filter(ImageFilter.UnsharpMask(radius=1.2, percent=42, threshold=3))
    master.save(MASTER, optimize=True, compress_level=9)

    texture = ImageOps.fit(master, (frame_width, frame_height), method=Image.Resampling.LANCZOS)
    texture = ImageEnhance.Color(texture).enhance(1.32)
    texture = ImageEnhance.Contrast(texture).enhance(1.08)
    periodic = Image.new("RGB", (frame_width * 3, frame_height))
    periodic.paste(texture, (0, 0))
    periodic.paste(ImageOps.mirror(texture), (frame_width, 0))
    periodic.paste(texture, (frame_width * 2, 0))

    base_sheet = Image.open(BASE_SHEET).convert("RGBA")
    output = Image.new("RGBA", (columns * frame_width, rows * frame_height), (0, 0, 0, 0))

    for index in range(frame_count):
        progress = index / frame_count
        base = _frame(base_sheet, index, frame_width, frame_height, columns)
        offset = int(round(progress * frame_width * 2))
        spectral = periodic.crop((offset, 0, offset + frame_width, frame_height))
        spectral = _shift_hue(spectral, int(round(progress * 256)) % 256)

        luminance = ImageEnhance.Contrast(base.convert("RGB").convert("L")).enhance(1.18)
        lighting = luminance.point(lambda value: min(255, 58 + int(value * 0.82)))
        lighting_rgb = Image.merge("RGB", (lighting, lighting, lighting))
        colored = ImageChops.multiply(spectral, lighting_rgb)
        colored = ImageEnhance.Color(colored).enhance(1.45)
        colored = ImageEnhance.Contrast(colored).enhance(1.12)
        colored = ImageEnhance.Brightness(colored).enhance(1.24)

        ribs = ImageChops.difference(luminance, luminance.filter(ImageFilter.GaussianBlur(1.15)))
        ribs = ImageEnhance.Contrast(ribs).enhance(2.4)
        rib_light = Image.merge("RGB", (ribs, ribs, ribs))
        colored = ImageChops.screen(colored, rib_light)

        alpha = base.getchannel("A").point(lambda value: min(255, int(value * 1.08)))
        frame = colored.convert("RGBA")
        frame.putalpha(alpha)
        x = (index % columns) * frame_width
        y = (index // columns) * frame_height
        output.paste(frame, (x, y), frame)

    output.save(OUTPUT_SHEET, optimize=True, compress_level=9)
    OUTPUT_META.write_text(
        json.dumps(
            {
                "columns": columns,
                "frame_count": frame_count,
                "frame_width": frame_width,
                "frame_height": frame_height,
                "fps": 240,
                "loop_seconds": 1.6,
                "direction": "left-to-right",
                "source": "Talk Dat generated full-spectrum optical texture mapped through The Pill",
                "transparent_background": True,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
