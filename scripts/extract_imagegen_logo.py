from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageStat


def foreground_mask(image: Image.Image) -> Image.Image:
    rgba = image.convert("RGBA")
    pixels = rgba.load()
    mask = Image.new("L", rgba.size, 0)
    out = mask.load()
    width, height = rgba.size
    for y in range(height):
        for x in range(width):
            r, g, b, a = pixels[x, y]
            if a == 0:
                continue
            maximum = max(r, g, b)
            minimum = min(r, g, b)
            saturation = (maximum - minimum) / max(1, maximum)
            luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
            if luminance < 218 or (saturation > 0.24 and luminance < 248):
                out[x, y] = 255

    # Smooth the AI preview checkerboard cut while preserving the icon edge.
    mask = mask.filter(ImageFilter.MaxFilter(13))
    mask = mask.filter(ImageFilter.GaussianBlur(2.2))
    mask = mask.point(lambda p: 255 if p > 88 else 0)
    mask = mask.filter(ImageFilter.GaussianBlur(1.4))
    return mask


def trim_and_square(icon: Image.Image, mask: Image.Image, size: int, fill: float) -> Image.Image:
    bbox = mask.getbbox()
    if bbox is None:
        raise RuntimeError("Could not find a foreground logo in the source image.")
    left, top, right, bottom = bbox
    pad = max(24, int(max(right - left, bottom - top) * 0.08))
    left = max(0, left - pad)
    top = max(0, top - pad)
    right = min(icon.width, right + pad)
    bottom = min(icon.height, bottom + pad)

    cropped = icon.crop((left, top, right, bottom))
    cropped_mask = mask.crop((left, top, right, bottom))
    transparent = Image.new("RGBA", cropped.size, (0, 0, 0, 0))
    transparent.alpha_composite(cropped)
    transparent.putalpha(cropped_mask)

    fill = max(0.72, min(0.98, float(fill)))
    scale = min(size * fill / transparent.width, size * fill / transparent.height)
    target = (max(1, int(transparent.width * scale)), max(1, int(transparent.height * scale)))
    resized = transparent.resize(target, Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.alpha_composite(resized, ((size - target[0]) // 2, (size - target[1]) // 2))
    return clean_white_preview_fringe(canvas)


def clean_white_preview_fringe(image: Image.Image) -> Image.Image:
    rgba = image.convert("RGBA")
    pixels = rgba.load()
    width, height = rgba.size
    for y in range(height):
        for x in range(width):
            r, g, b, a = pixels[x, y]
            if a == 0:
                continue
            maximum = max(r, g, b)
            minimum = min(r, g, b)
            saturation = (maximum - minimum) / max(1, maximum)
            luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
            if saturation < 0.12 and luminance > 188:
                softened_alpha = min(a, 188)
                pixels[x, y] = (12, 14, 14, softened_alpha)
    return rgba


def checker(size: int, cell: int = 48) -> Image.Image:
    image = Image.new("RGBA", (size, size), (244, 247, 247, 255))
    draw = ImageDraw.Draw(image)
    for y in range(0, size, cell):
        for x in range(0, size, cell):
            if (x // cell + y // cell) % 2:
                draw.rectangle((x, y, x + cell, y + cell), fill=(217, 225, 223, 255))
    return image


def save_previews(icon: Image.Image, output_dir: Path) -> None:
    size = icon.width
    backgrounds = {
        "checker": checker(size),
        "light": Image.new("RGBA", (size, size), (245, 246, 244, 255)),
        "dark": Image.new("RGBA", (size, size), (6, 12, 14, 255)),
    }
    for name, background in backgrounds.items():
        preview = background.copy()
        preview.alpha_composite(icon)
        preview.convert("RGB").save(output_dir / f"talk-stone-preview-{name}.jpg", quality=94)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--out", type=Path, default=Path("branding/talk-stone"))
    parser.add_argument("--size", type=int, default=2048)
    parser.add_argument("--fill", type=float, default=0.94)
    args = parser.parse_args()

    source = args.source
    output_dir = args.out
    output_dir.mkdir(parents=True, exist_ok=True)

    image = Image.open(source).convert("RGBA")
    mask = foreground_mask(image)
    icon = trim_and_square(image, mask, args.size, args.fill)
    icon.save(output_dir / "talk-stone-transparent.png", compress_level=3)
    save_previews(icon, output_dir)
    (output_dir / "SOURCE.txt").write_text("Generated via Codex image generation, then alpha-cleaned locally.\n", encoding="utf-8")

    alpha = icon.getchannel("A")
    print("wrote", output_dir / "talk-stone-transparent.png")
    print("size", icon.size)
    print("alpha bbox", alpha.getbbox())
    print("alpha mean", round(ImageStat.Stat(alpha).mean[0], 2))


if __name__ == "__main__":
    main()
