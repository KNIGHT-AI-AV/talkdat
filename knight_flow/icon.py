from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from .config import app_dir


ICON_VERSION = "talk-stone-2026-06-10-v1"


def _asset_path(filename: str) -> Path:
    local_path = Path(__file__).resolve().parent / "assets" / filename
    if local_path.exists():
        return local_path
    bundle_root = getattr(sys, "_MEIPASS", "")
    if bundle_root:
        bundled_path = Path(bundle_root) / "knight_flow" / "assets" / filename
        if bundled_path.exists():
            return bundled_path
    return local_path


def _mix(left: tuple[int, int, int], right: tuple[int, int, int], amount: float) -> tuple[int, int, int]:
    amount = max(0.0, min(1.0, amount))
    return (
        int(left[0] + (right[0] - left[0]) * amount),
        int(left[1] + (right[1] - left[1]) * amount),
        int(left[2] + (right[2] - left[2]) * amount),
    )


def _resample() -> Any:
    from PIL import Image

    return getattr(Image.Resampling, "LANCZOS", Image.LANCZOS)


def _odd(value: int) -> int:
    value = max(3, int(value))
    return value if value % 2 else value + 1


def _scale_box(box: tuple[float, float, float, float], scale: float) -> tuple[int, int, int, int]:
    return tuple(int(round(value * scale)) for value in box)  # type: ignore[return-value]


def _texture(size: int) -> Any:
    from PIL import Image, ImageDraw, ImageFilter

    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    for x in range(size):
        t = x / max(1, size - 1)
        if t < 0.20:
            color = _mix((255, 23, 57), (255, 84, 49), t / 0.20)
        elif t < 0.50:
            color = _mix((255, 84, 49), (255, 180, 96), (t - 0.20) / 0.30)
        elif t < 0.70:
            color = _mix((255, 180, 96), (9, 116, 112), (t - 0.50) / 0.20)
        else:
            color = _mix((9, 116, 112), (5, 31, 43), (t - 0.70) / 0.30)
        draw.line((x, 0, x, size), fill=(*color, 255))

    wash = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    wash_draw = ImageDraw.Draw(wash)
    scale = size / 1024
    wash_draw.ellipse(_scale_box((-110, 430, 610, 1120), scale), fill=(255, 0, 54, 176))
    wash_draw.ellipse(_scale_box((175, 235, 790, 820), scale), fill=(255, 136, 68, 120))
    wash_draw.ellipse(_scale_box((520, 80, 1160, 675), scale), fill=(0, 126, 130, 122))
    wash_draw.ellipse(_scale_box((640, 500, 1190, 1120), scale), fill=(255, 68, 28, 94))
    image = Image.alpha_composite(image, wash.filter(ImageFilter.GaussianBlur(radius=max(1, int(38 * scale)))))

    ribs = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    rib_draw = ImageDraw.Draw(ribs)
    pitch = max(8, int(33 * scale))
    for x in range(-pitch, size + pitch, pitch):
        rib_draw.rectangle((x - int(8 * scale), 0, x - int(2 * scale), size), fill=(0, 10, 16, 116))
        rib_draw.rectangle((x - int(2 * scale), 0, x + int(3 * scale), size), fill=(255, 186, 98, 120))
        rib_draw.line((x, 0, x, size), fill=(255, 238, 158, 222), width=max(1, int(2 * scale)))
        rib_draw.line((x + int(5 * scale), 0, x + int(5 * scale), size), fill=(14, 226, 211, 68), width=max(1, int(1 * scale)))
    image = Image.alpha_composite(image, ribs.filter(ImageFilter.GaussianBlur(radius=max(0.4, 0.8 * scale))))

    glass = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    glass_draw = ImageDraw.Draw(glass)
    glass_draw.rectangle((0, 0, size, int(size * 0.31)), fill=(255, 246, 198, 34))
    glass_draw.rectangle((0, int(size * 0.72), size, size), fill=(255, 50, 40, 28))
    return Image.alpha_composite(image, glass.filter(ImageFilter.GaussianBlur(radius=max(1, int(13 * scale)))))


def _dilate(mask: Any, pixels: int) -> Any:
    from PIL import ImageFilter

    return mask.filter(ImageFilter.MaxFilter(_odd(pixels * 2 + 1)))


def _stroke(mask: Any, outer: int, inner: int = 0) -> Any:
    from PIL import ImageChops, ImageFilter

    outside = _dilate(mask, outer)
    inside = mask.filter(ImageFilter.MinFilter(_odd(inner * 2 + 1))) if inner > 0 else mask
    return ImageChops.subtract(outside, inside)


def _paste_fill(base: Any, color_or_image: Any, mask: Any) -> None:
    from PIL import Image

    if isinstance(color_or_image, tuple):
        layer = Image.new("RGBA", base.size, color_or_image)
    else:
        layer = color_or_image
    base.alpha_composite(Image.composite(layer, Image.new("RGBA", base.size, (0, 0, 0, 0)), mask))


def _speaker_mask(size: int) -> Any:
    from PIL import Image, ImageDraw, ImageFilter

    scale = size / 1024
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle(_scale_box((84, 382, 356, 662), scale), radius=int(82 * scale), fill=255)
    horn = [
        (292, 390),
        (622, 180),
        (703, 176),
        (760, 222),
        (790, 304),
        (790, 726),
        (758, 812),
        (704, 856),
        (622, 842),
        (292, 650),
    ]
    draw.polygon([(int(x * scale), int(y * scale)) for x, y in horn], fill=255)
    draw.rounded_rectangle(_scale_box((628, 174, 794, 856), scale), radius=int(86 * scale), fill=255)
    draw.rectangle(_scale_box((292, 390, 684, 650), scale), fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(radius=max(0.5, 1.0 * scale)))
    return mask.point(lambda value: 255 if value > 92 else 0)


def _arc_mask(size: int, box: tuple[float, float, float, float], width: float) -> Any:
    import math
    from PIL import Image, ImageDraw, ImageFilter

    scale = size / 1024
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    scaled_box = _scale_box(box, scale)
    stroke = max(2, int(width * scale))
    start = -62
    end = 62
    draw.arc(scaled_box, start=start, end=end, fill=255, width=stroke)

    left, top, right, bottom = scaled_box
    cx = (left + right) / 2
    cy = (top + bottom) / 2
    rx = (right - left) / 2
    ry = (bottom - top) / 2
    radius = stroke / 2
    for angle in (start, end):
        radians = math.radians(angle)
        x = cx + math.cos(radians) * rx
        y = cy + math.sin(radians) * ry
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=255)
    return mask.filter(ImageFilter.GaussianBlur(radius=max(0.4, 0.5 * scale))).point(
        lambda value: 255 if value > 70 else 0
    )


def _draw_icon(size: int) -> Any:
    from PIL import Image, ImageFilter

    render_size = max(256, min(512, size * 2))
    scale = render_size / 1024
    image = Image.new("RGBA", (render_size, render_size), (0, 0, 0, 0))
    texture = _texture(render_size)

    wave_specs = [
        ((585, 350, 835, 700), 52),
        ((555, 275, 935, 780), 62),
        ((520, 205, 1005, 850), 72),
    ]
    for box, width in wave_specs[::-1]:
        mask = _arc_mask(render_size, box, width)
        _paste_fill(image, (6, 23, 28, 136), _stroke(mask, int(34 * scale)))
        _paste_fill(image, (0, 226, 210, 52), _dilate(mask, int(22 * scale)).filter(ImageFilter.GaussianBlur(radius=int(14 * scale))))
        _paste_fill(image, texture, mask)
        _paste_fill(image, (235, 226, 195, 170), _stroke(mask, int(5 * scale), int(3 * scale)))
        _paste_fill(image, (19, 53, 52, 120), _stroke(mask, int(14 * scale), int(8 * scale)))

    speaker = _speaker_mask(render_size)
    _paste_fill(image, (255, 25, 0, 60), _dilate(speaker, int(44 * scale)).filter(ImageFilter.GaussianBlur(radius=int(24 * scale))))
    _paste_fill(image, (0, 215, 205, 52), _dilate(speaker, int(35 * scale)).filter(ImageFilter.GaussianBlur(radius=int(23 * scale))))
    _paste_fill(image, (4, 18, 23, 160), _stroke(speaker, int(34 * scale)))
    _paste_fill(image, texture, speaker)
    _paste_fill(image, (232, 224, 195, 188), _stroke(speaker, int(9 * scale), int(4 * scale)))
    _paste_fill(image, (255, 245, 202, 92), _stroke(speaker, int(5 * scale), int(2 * scale)))
    _paste_fill(image, (4, 24, 29, 130), _stroke(speaker, int(22 * scale), int(12 * scale)))

    highlight = Image.new("RGBA", (render_size, render_size), (0, 0, 0, 0))
    highlight_mask = speaker.filter(ImageFilter.GaussianBlur(radius=max(1, int(2 * scale))))
    shine = Image.new("RGBA", (render_size, render_size), (255, 243, 198, 34))
    top_mask = Image.new("L", (render_size, render_size), 0)
    from PIL import ImageDraw

    top_draw = ImageDraw.Draw(top_mask)
    top_draw.rectangle((0, 0, render_size, int(420 * scale)), fill=180)
    highlight.alpha_composite(Image.composite(shine, Image.new("RGBA", (render_size, render_size), (0, 0, 0, 0)), top_mask))
    image.alpha_composite(Image.composite(highlight, Image.new("RGBA", (render_size, render_size), (0, 0, 0, 0)), highlight_mask))

    if render_size != size:
        image = image.resize((size, size), _resample())
    return image


def ensure_icon_file() -> Path:
    path = app_dir() / "talk-dat.ico"
    version_path = app_dir() / "talk-dat-icon.version"
    if path.exists():
        try:
            if version_path.read_text(encoding="utf-8").strip() == ICON_VERSION:
                return path
        except OSError:
            pass
    asset = _asset_path("app_icon.ico")
    if asset.exists():
        path.write_bytes(asset.read_bytes())
    else:
        image = _draw_icon(256)
        sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
        image.save(path, sizes=sizes)
    version_path.write_text(ICON_VERSION, encoding="utf-8")
    return path


def ensure_tray_png_file() -> Path:
    path = app_dir() / "talk-dat-tray.png"
    version_path = app_dir() / "talk-dat-tray.version"
    if path.exists():
        try:
            if version_path.read_text(encoding="utf-8").strip() == ICON_VERSION:
                return path
        except OSError:
            pass
    asset = _asset_path("app_icon.png")
    if asset.exists():
        from PIL import Image

        image = Image.open(asset).convert("RGBA").resize((64, 64), _resample())
    else:
        image = _draw_icon(64)
    image.save(path)
    version_path.write_text(ICON_VERSION, encoding="utf-8")
    return path


def make_tray_image() -> Any:
    from PIL import Image

    return Image.open(ensure_tray_png_file()).convert("RGBA")
