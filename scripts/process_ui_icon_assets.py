"""Build deployment-sized UI icons from the archived Image 2 masters.

The generated originals are intentionally retained under ``masters``.  This
script performs only deterministic production work: it crops to the alpha
silhouette, neutralises residual colour, resamples with premultiplied alpha,
and gives every icon the same optical padding on a square canvas.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageColor, ImageDraw, ImageEnhance, ImageFont, ImageOps


ROOT = Path(__file__).resolve().parents[1]
ICON_ROOT = ROOT / "knight_flow" / "assets" / "ui" / "icons" / "imagegen-v1"
MASTER_ROOT = ICON_ROOT / "masters"
RUNTIME_ROOT = ICON_ROOT / "runtime"
OUTPUT_SIZE = 384
OPTICAL_FILL = 0.80
CONTACT_SHEET = ICON_ROOT / "contact-sheet.png"


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = (
        Path("C:/Windows/Fonts/segoeui.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    )
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


def _luminance(color: str) -> float:
    values: list[float] = []
    for channel in ImageColor.getrgb(color):
        value = channel / 255.0
        values.append(
            value / 12.92
            if value <= 0.04045
            else ((value + 0.055) / 1.055) ** 2.4
        )
    return 0.2126 * values[0] + 0.7152 * values[1] + 0.0722 * values[2]


def _review_icon(path: Path, size: int, primary: str, detail: str) -> Image.Image:
    with Image.open(path) as source:
        source = source.convert("RGBA")
    dark, light = sorted((primary, detail), key=_luminance)
    tinted = ImageOps.colorize(source.convert("L"), black=dark, white=light).convert(
        "RGBA"
    )
    tinted.putalpha(source.getchannel("A"))
    return tinted.resize((size, size), Image.Resampling.LANCZOS)


def build_contact_sheet(icon_paths: list[Path]) -> None:
    """Write a dark/light proof at the actual UI sizes used by Talk DAT!."""

    columns = 5
    cell_width = 210
    cell_height = 132
    rows = (len(icon_paths) + columns - 1) // columns
    section_height = rows * cell_height
    sheet = Image.new("RGB", (columns * cell_width, section_height * 2))
    draw = ImageDraw.Draw(sheet)
    label_font = _font(14)
    size_font = _font(14)
    themes = (
        ("#071011", "#edf0e9", "#37d8cc", "#d9ddd8", "#30d7cd"),
        ("#f4ecdf", "#202426", "#9a4d13", "#202426", "#b95f1d"),
    )
    for theme_index, (background, primary, detail, label, size_color) in enumerate(
        themes
    ):
        top = theme_index * section_height
        draw.rectangle(
            (0, top, sheet.width, top + section_height), fill=background
        )
        for index, icon_path in enumerate(icon_paths):
            row, column = divmod(index, columns)
            left = column * cell_width
            cell_top = top + row * cell_height
            draw.text((left + 12, cell_top + 12), icon_path.stem, fill=label, font=label_font)
            for offset, size in zip((30, 88, 146), (20, 24, 32)):
                icon = _review_icon(icon_path, size, primary, detail)
                icon_left = left + offset
                icon_top = cell_top + 48 + (32 - size) // 2
                sheet.paste(icon, (icon_left, icon_top), icon)
                draw.text(
                    (icon_left - 7, cell_top + 94),
                    str(size),
                    fill=size_color,
                    font=size_font,
                )
    sheet.save(CONTACT_SHEET, format="PNG", optimize=True)


def _premultiplied_resize(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Resize RGBA without leaking hidden matte colours into edge pixels."""

    source = np.asarray(image.convert("RGBA"), dtype=np.float32) / 255.0
    alpha = source[..., 3:4]
    premultiplied = source[..., :3] * alpha

    channels: list[np.ndarray] = []
    for index in range(3):
        plane = Image.fromarray(premultiplied[..., index])
        channels.append(
            np.asarray(plane.resize(size, Image.Resampling.LANCZOS), dtype=np.float32)
        )
    alpha_plane = Image.fromarray(alpha[..., 0])
    resized_alpha = np.asarray(
        alpha_plane.resize(size, Image.Resampling.LANCZOS), dtype=np.float32
    )
    resized_alpha = np.clip(resized_alpha, 0.0, 1.0)

    resized_rgb = np.stack(channels, axis=-1)
    visible = resized_alpha > (1.0 / 255.0)
    resized_rgb[visible] /= resized_alpha[visible, None]
    resized_rgb[~visible] = 0.0
    result = np.dstack((np.clip(resized_rgb, 0.0, 1.0), resized_alpha))
    return Image.fromarray(np.round(result * 255.0).astype(np.uint8))


def normalize_master(source_path: Path, target_path: Path) -> None:
    source = Image.open(source_path).convert("RGBA")
    alpha = source.getchannel("A")
    # Very low alpha values are generator residue rather than visible art.
    hard_alpha = alpha.point(lambda value: 0 if value < 5 else value)
    bounds = hard_alpha.getbbox()
    if bounds is None:
        raise ValueError(f"{source_path.name} has no visible alpha silhouette")

    source.putalpha(hard_alpha)
    cropped = source.crop(bounds)
    edge = max(cropped.width, cropped.height)
    target_edge = max(1, int(round(OUTPUT_SIZE * OPTICAL_FILL)))
    scale = target_edge / float(edge)
    fitted = _premultiplied_resize(
        cropped,
        (
            max(1, int(round(cropped.width * scale))),
            max(1, int(round(cropped.height * scale))),
        ),
    )

    # The runtime renderer supplies theme colour.  Keep only material
    # luminance and alpha so no warm/cool fringe can contaminate a theme.
    neutral_luma = ImageEnhance.Contrast(fitted.convert("L")).enhance(1.08)
    neutral = Image.merge(
        "RGBA",
        (
            neutral_luma,
            neutral_luma,
            neutral_luma,
            fitted.getchannel("A"),
        ),
    )
    canvas = Image.new("RGBA", (OUTPUT_SIZE, OUTPUT_SIZE), (0, 0, 0, 0))
    offset = (
        (OUTPUT_SIZE - neutral.width) // 2,
        (OUTPUT_SIZE - neutral.height) // 2,
    )
    canvas.alpha_composite(neutral, offset)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(target_path, format="PNG", optimize=True)


def main() -> int:
    masters = sorted(MASTER_ROOT.glob("*.png"))
    if not masters:
        raise SystemExit(f"No generated masters found in {MASTER_ROOT}")
    for source_path in masters:
        normalize_master(source_path, RUNTIME_ROOT / source_path.name)
        print(f"processed {source_path.name}")
    runtime_icons = sorted(RUNTIME_ROOT.glob("*.png"))
    build_contact_sheet(runtime_icons)
    print(f"Built {len(masters)} alpha-safe runtime icons in {RUNTIME_ROOT}")
    print(f"Wrote dark/light scale proof to {CONTACT_SHEET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
