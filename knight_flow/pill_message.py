from __future__ import annotations

"""The Pill's messages, drawn into the Pill's own bitmap (X-741).

The owner's rule: a message is the host part itself changing shape in its own
material, never "a separate piece" or "a weird overlay". On the desktop the
host is the Pill, so this module draws the Pill lengthened: one capsule, the
radius always half the height, the Pill's own art compressed into the cap at
the pinned end and stretched, blurred and veiled behind the words, and a
segment of the same capsule when the message has a button. It draws into the
bitmap the Pill already pushes with per-pixel alpha (layered_window.py): no
second window, no Tk widgets.

PIL only, no tkinter, so the shape and the contrast are tested without a
display. The Overlay supplies the art (the Pill's live picture, already in its
tone), the placement (island.pill_frame) and the moment (island.PillMotion).
"""

import functools
import math
import sys
from dataclasses import dataclass, field
from typing import Any

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

from . import island
from .layered_window import capsule_alpha_mask

#: (shadow, mid, highlight) gradient-map stops, then the rim glow. The success
#: teal and the error ember are the Pill's own looks (a finished take and a
#: failed one already flash them); the amber for a warning is new, from the
#: theme's accent2, in the same four stops.
PILL_FEEDBACK_LOOKS: dict[str, tuple[tuple[int, int, int], ...]] = {
    "captured": ((2, 36, 36), (22, 190, 160), (210, 255, 240), (80, 255, 216)),
    "error": ((40, 3, 5), (218, 40, 30), (255, 168, 100), (255, 92, 56)),
    "warn": ((40, 26, 2), (230, 160, 40), (255, 236, 190), (255, 202, 104)),
}

#: A message's tone as one of the Pill's looks (busy is the processing
#: spectrum, which the Overlay paints into the cap itself).
TONE_LOOKS = {"done": "captured", "error": "error", "warn": "warn"}
#: How strongly each look settles over the capsule. The teal peaks where the
#: Pill's own success look does (pill_motion.SUCCESS_FEEDBACK_PEAK).
TONE_LEVELS = {"done": 0.9, "error": 1.0, "warn": 0.85}


def pill_feedback_frame(frame: Image.Image, kind: str, strength: float) -> Image.Image:
    """Wash the Pill's own artwork in the success teal or the error ember.

    A gradient map over the artwork's luminance rather than a flat overlay, so
    every painted streak survives and the Pill still looks hand-drawn: only its
    colour speaks. The artwork's own colour is drained first, so the wash never
    passes through a muddy red-plus-teal midpoint on its way in or out, and a
    soft rim glows just inside the silhouette. Alpha is left exactly as it was,
    so the colour-keyed window keeps its shape.
    """
    look = PILL_FEEDBACK_LOOKS.get(str(kind))
    level = max(0.0, min(1.0, float(strength)))
    if look is None or level <= 0.0:
        return frame
    shadow, mid, highlight, rim_color = look
    rgba = frame.convert("RGBA")
    alpha = rgba.getchannel("A")
    rgb = rgba.convert("RGB")
    tinted = ImageOps.colorize(ImageOps.grayscale(rgb), black=shadow, white=highlight, mid=mid)
    drained = ImageEnhance.Color(rgb).enhance(max(0.0, 1.0 - 1.6 * level))
    washed = Image.blend(drained, tinted, min(1.0, level * 1.1)).convert("RGBA")
    washed.putalpha(alpha)
    body = alpha.point(lambda value: 255 if value >= 250 else 0)
    band = max(3, (min(rgba.size) // 12) | 1)
    rim = ImageChops.subtract(body, body.filter(ImageFilter.MinFilter(band)))
    rim = rim.filter(ImageFilter.GaussianBlur(radius=max(1.0, band / 2.5)))
    rim = ImageChops.multiply(rim, body).point(lambda value: int(value * 0.85 * level))
    glow = Image.new("RGBA", rgba.size, (*rim_color, 255))
    glow.putalpha(rim)
    return Image.alpha_composite(washed, glow)


def tone_wash(frame: Image.Image, tone: str, level: float) -> Image.Image:
    look = TONE_LOOKS.get(str(tone))
    if look is None or level <= 0.0:
        return frame
    return pill_feedback_frame(frame, look, TONE_LEVELS.get(str(tone), 1.0) * level)


# ---------------------------------------------------------------------------
# Material and words (message spec sections 5 to 7).
# ---------------------------------------------------------------------------

#: The veil over the frosted body: dark rgba(4,10,11,.64), light rgba(250,254,252,.80).
VEILS = {"dark": (4, 10, 11, 163), "light": (250, 254, 252, 204)}
#: Words are never coloured: these on the veil, details at 74% and 72%.
INK = {"dark": (243, 250, 247), "light": (16, 33, 29)}
DETAIL_ALPHA = {"dark": 0.74, "light": 0.72}
#: The Pill's rim: 1 px of black at 42% (24% in light), a 1 px top highlight.
RIM_ALPHA = {"dark": 0.42, "light": 0.24}
HIGHLIGHT_ALPHA = {"dark": 0.14, "light": 0.55}
#: Action colour. Flow light's accent is 4.0:1 on white, so light uses accent
#: 80% + text 20% (#047a6c, 5.2:1), the correction the spec carries over.
ACTION = {"dark": (94, 232, 204), "light": (4, 122, 108)}
ACTION_INK = {"dark": (0, 0, 0), "light": (255, 255, 255)}

TITLE_PX = 14.67
DETAIL_PX = 13.33
KEYCAP_PX = 11.0
BLUR_PX = 7.0
SATURATION = 1.2
TEXT_RISE_PX = 3.0
TEXT_BLUR_PX = 2.0
PROGRESS_ROOM_PX = 8


def _font_candidates(bold: bool) -> tuple[str, ...]:
    if sys.platform == "darwin":
        return ("/System/Library/Fonts/SFNS.ttf", "/System/Library/Fonts/Helvetica.ttc")
    return ("seguisb.ttf", "segoeuib.ttf", "segoeui.ttf") if bold else ("segoeui.ttf",)


@functools.lru_cache(maxsize=32)
def font(bold: bool, size_px: float) -> Any:
    """Segoe UI (Semibold for titles) from the real font files. Text on a
    per-pixel-alpha bitmap is drawn by PIL with grayscale anti-aliasing:
    ClearType cannot render onto one."""
    size = max(6, int(round(size_px)))
    for name in _font_candidates(bold):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # an older Pillow
        return ImageFont.load_default()


def text_width(text: str, face: Any) -> float:
    try:
        return float(face.getlength(text))
    except AttributeError:
        box = face.getbbox(text)
        return float(box[2] - box[0])


def wrap(text: str, face: Any, width: float, max_lines: int) -> list[str]:
    """Word wrap to ``width``; overflow past ``max_lines`` ends in "..."."""
    words = str(text or "").split()
    if not words:
        return []
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if not current or text_width(candidate, face) <= width:
            current = candidate
            continue
        lines.append(current)
        current = word
    lines.append(current)
    if len(lines) > max_lines:
        kept = lines[:max_lines]
        kept[-1] = ellipsize(" ".join([kept[-1], *lines[max_lines:]]), face, width)
        lines = kept
    return [ellipsize(line, face, width) for line in lines]


def ellipsize(line: str, face: Any, width: float) -> str:
    if text_width(line, face) <= width:
        return line
    words = line.split()
    while words and text_width(" ".join(words) + "...", face) > width:
        words.pop()
    if words:
        return " ".join(words) + "..."
    text = line
    while text and text_width(text + "...", face) > width:
        text = text[:-1]
    return (text + "...") if text else "..."


@dataclass(frozen=True)
class Button:
    label: str
    rect: tuple[int, int, int, int]  # x, y, w, h in the capsule's own pixels
    hit: tuple[int, int, int, int]  # the rectangle a press lands in (44 px tall)
    primary: bool
    index: int
    keycap: str = ""


@dataclass
class FlagLayout:
    """Where everything sits in the settled capsule (device pixels)."""

    mode: str  # "lengthen" | "segment"
    width: int
    height: int
    head: int  # the art's width at the pinned end when settled
    feather: int
    pin: str
    scale: float
    lines: list[tuple[str, bool, float, float]] = field(default_factory=list)  # text, is_title, x, centre y
    words_box: tuple[int, int, int, int] = (0, 0, 0, 0)
    buttons: list[Button] = field(default_factory=list)
    divider_x: int | None = None
    progress_box: tuple[int, int, int] | None = None  # x0, y, x1
    compact: bool = False
    pill_box: tuple[int, int, int, int] = (0, 0, 0, 0)  # the Pill end in a segment (x, y, w, h)

    @property
    def size(self) -> tuple[int, int]:
        return self.width, self.height


def _px(value: float, scale: float) -> int:
    return max(1, int(round(float(value) * float(scale))))


def _keycap_text(accelerator: str) -> str:
    """"<Alt-d>" -> "Alt+D", the way the render shows the accelerator."""
    inner = str(accelerator or "").strip("<>")
    if not inner:
        return ""
    parts = inner.split("-")
    return "+".join(part.capitalize() if len(part) > 1 else part.upper() for part in parts)


def measure(message: island.Message, *, scale: float, work_width: int, pill_w: int, compact: bool = False) -> tuple[int, int]:
    """The settled capsule's size for ``message`` (device pixels)."""
    return layout(message, scale=scale, work_width=work_width, pill_w=pill_w, pin="left", compact=compact).size


def layout(
    message: island.Message,
    *,
    scale: float,
    work_width: int,
    pill_w: int,
    pin: str = "left",
    compact: bool = False,
) -> FlagLayout:
    if message.is_segment:
        return _segment_layout(message, scale=scale, work_width=work_width, pill_w=pill_w, pin=pin)
    return _lengthened_layout(message, scale=scale, work_width=work_width, pin=pin, compact=compact)


def _lengthened_layout(message: island.Message, *, scale: float, work_width: int, pin: str, compact: bool) -> FlagLayout:
    s = float(scale)
    title_face = font(True, TITLE_PX * s)
    detail_face = font(False, DETAIL_PX * s)
    limit_design = min(island.COMPACT_MAX_WIDTH if compact else island.MAX_WIDTH,
                       max(1.0, work_width / s - 2 * 12))
    words_limit = max(40.0, (limit_design - island.CAP - island.TEXT_GAP - island.TRAIL) * s)
    title_lines = wrap(message.title, title_face, words_limit, 1 if compact else island.MAX_TITLE_LINES)
    detail_lines = [] if compact else wrap(message.detail, detail_face, words_limit, island.MAX_DETAIL_LINES)
    if not title_lines and not detail_lines:
        title_lines = [""]
    widths = [text_width(line, title_face) for line in title_lines] + [text_width(line, detail_face) for line in detail_lines]
    words_w = max(widths) if widths else 0.0
    if message.progress is not None:
        words_w = max(words_w, 120 * s)
    line_count = len(title_lines) + len(detail_lines)
    # A live message's progress line sits under its title and gets its own
    # room: drawn into the title's line it cut through the descenders.
    progress_room = PROGRESS_ROOM_PX * s if message.progress is not None else 0.0
    height = _px(island.capsule_height(line_count) + (PROGRESS_ROOM_PX if message.progress is not None else 0), s)
    cap, gap, trail = _px(island.CAP, s), _px(island.TEXT_GAP, s), _px(island.TRAIL, s)
    width = int(min(limit_design * s, math.ceil(cap + gap + words_w + trail)))
    words_x = cap + gap if pin == "left" else trail
    line_h = island.LINE * s
    top = (height - line_h * line_count - progress_room) / 2.0
    lines: list[tuple[str, bool, float, float]] = []
    for index, text in enumerate(title_lines + detail_lines):
        shift = progress_room if index >= len(title_lines) else 0.0
        lines.append((text, index < len(title_lines), float(words_x), top + shift + line_h * (index + 0.5)))
    words_box = (int(words_x), int(top), int(math.ceil(words_w)), int(math.ceil(line_h * line_count + progress_room)))
    progress = None
    if message.progress is not None:
        # 3 px under the title, the words' own width.
        y = int(round(top + line_h * len(title_lines) + 1.0 * s))
        progress = (int(words_x), y, int(words_x + words_w))
    return FlagLayout(
        mode="lengthen", width=width, height=height, head=cap, feather=_px(island.FEATHER, s), pin=pin, scale=s,
        lines=lines, words_box=words_box, progress_box=progress, compact=compact,
    )


def _segment_layout(message: island.Message, *, scale: float, work_width: int, pill_w: int, pin: str) -> FlagLayout:
    s = float(scale)
    height = _px(island.SEGMENT_HEIGHT, s)
    title_face = font(True, TITLE_PX * s)
    action_face = font(True, DETAIL_PX * s)
    keycap_face = font(False, KEYCAP_PX * s)
    pad_in, gap, pad_end = _px(island.SEGMENT_TEXT_GAP, s), _px(island.SEGMENT_ACTION_GAP, s), _px(island.SEGMENT_TRAIL, s)
    action_h = _px(island.ACTION_HEIGHT, s)
    hit_h = _px(island.ACTION_HIT, s)
    pieces = []
    actions_w = 0.0
    for index, action in enumerate(message.actions):
        label_w = text_width(action.label, action_face)
        pad = _px(12, s)
        body_w = label_w + 2 * pad
        keycap = _keycap_text(action.accelerator)
        keycap_w = text_width(keycap, keycap_face) + _px(10, s) if keycap else 0.0
        pieces.append((action, body_w, keycap, keycap_w))
        actions_w += body_w + (keycap_w + _px(4, s) if keycap else 0.0) + (gap if index else 0.0)
    limit = min(island.MAX_WIDTH * s, max(1.0, work_width - 2 * 12 * s))
    words_limit = max(40.0, limit - pill_w - 1 - pad_in - gap - actions_w - pad_end)
    title = ellipsize(message.title, title_face, words_limit)
    words_w = text_width(title, title_face)
    inner_w = pad_in + words_w + gap + actions_w + pad_end
    width = int(math.ceil(pill_w + 1 + inner_w))
    if pin == "left":
        divider = pill_w
        words_x = pill_w + 1 + pad_in
        pill_box = (0, 0, pill_w, height)
    else:
        divider = width - pill_w - 1
        words_x = pad_in
        pill_box = (width - pill_w, 0, pill_w, height)
    cy = height / 2.0
    lines = [(title, True, float(words_x), cy)]
    buttons: list[Button] = []
    x = words_x + words_w + gap
    for index, (action, body_w, keycap, keycap_w) in enumerate(pieces):
        if index:
            x += gap
        y = int(round((height - action_h) / 2.0))
        rect = (int(round(x)), y, int(math.ceil(body_w)), action_h)
        extra = keycap_w + _px(4, s) if keycap else 0.0
        hit = (int(round(x)), int(round((height - hit_h) / 2.0)), int(math.ceil(body_w + extra)), hit_h)
        buttons.append(Button(action.label, rect, hit, bool(action.primary), index, keycap))
        x += body_w + extra
    return FlagLayout(
        mode="segment", width=width, height=height, head=pill_w, feather=0, pin=pin, scale=s, lines=lines,
        words_box=(int(words_x), 0, int(math.ceil(words_w)), height), buttons=buttons, divider_x=divider,
        pill_box=pill_box,
    )


# ---------------------------------------------------------------------------
# Layers built once per message (the body is blurred once, then only cropped).
# ---------------------------------------------------------------------------


def frosted_body(
    art: Image.Image,
    size: tuple[int, int],
    *,
    theme: str,
    scale: float,
    tone: str = "info",
    tone_level: float = 0.0,
    high_contrast: tuple[tuple[int, int, int], tuple[int, int, int]] | None = None,
) -> Image.Image:
    """The Pill's art stretched to the capsule, blurred, saturated and veiled.

    Opaque everywhere: the words are read against it, and the capsule it
    fills must be one solid piece.
    """
    width, height = max(1, int(size[0])), max(1, int(size[1]))
    if high_contrast is not None:
        return Image.new("RGBA", (width, height), (*high_contrast[0], 255))
    veil = VEILS.get(theme, VEILS["dark"])
    source = tone_wash(art.convert("RGBA"), tone, tone_level)
    ground = Image.new("RGBA", source.size, (*veil[:3], 255))
    ground.alpha_composite(source)
    stretched = ground.convert("RGB").resize((width, height), Image.Resampling.BILINEAR)
    radius = max(1.0, BLUR_PX * float(scale))
    # Blur with the edge replicated, so the capsule's own ends do not darken.
    pad = int(math.ceil(radius * 2))
    padded = _edge_pad(stretched, pad)
    blurred = padded.filter(ImageFilter.GaussianBlur(radius)).crop((pad, pad, pad + width, pad + height))
    blurred = ImageEnhance.Color(blurred).enhance(SATURATION)
    body = blurred.convert("RGBA")
    body.alpha_composite(Image.new("RGBA", (width, height), veil))
    body.putalpha(255)
    return body


def _edge_pad(image: Image.Image, pad: int) -> Image.Image:
    width, height = image.size
    out = image.resize((width + 2 * pad, height + 2 * pad), Image.Resampling.NEAREST)
    out.paste(image, (pad, pad))
    return out


def words_layer(
    lay: FlagLayout,
    size: tuple[int, int],
    *,
    theme: str,
    progress: float | None = None,
    high_contrast: tuple[tuple[int, int, int], tuple[int, int, int]] | None = None,
    pressed: int | None = None,
) -> Image.Image:
    """The words (and a segment's actions), laid out where they will rest."""
    layer = Image.new("RGBA", (max(1, int(size[0])), max(1, int(size[1]))), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    s = lay.scale
    ink = high_contrast[1] if high_contrast is not None else INK.get(theme, INK["dark"])
    detail_alpha = 1.0 if high_contrast is not None else DETAIL_ALPHA.get(theme, 0.74)
    title_face, detail_face = font(True, TITLE_PX * s), font(False, DETAIL_PX * s)
    for text, is_title, x, cy in lay.lines:
        alpha = 255 if is_title else int(round(255 * detail_alpha))
        draw.text((x, cy), text, font=title_face if is_title else detail_face, fill=(*ink, alpha), anchor="lm")
    if lay.progress_box is not None:
        x0, y, x1 = lay.progress_box
        thick = max(2, int(round(3 * s)))
        radius = max(1, int(round(2 * s)))
        draw.rounded_rectangle((x0, y, x1, y + thick), radius=radius, fill=(*ink, 56))
        if progress is not None and progress > 0:
            end = x0 + (x1 - x0) * max(0.0, min(1.0, progress))
            if end - x0 >= thick:
                draw.rounded_rectangle((x0, y, end, y + thick), radius=radius, fill=(*ink, 235))
    action = high_contrast[1] if high_contrast is not None else ACTION.get(theme, ACTION["dark"])
    action_ink = high_contrast[0] if high_contrast is not None else ACTION_INK.get(theme, ACTION_INK["dark"])
    action_face, keycap_face = font(True, DETAIL_PX * s), font(False, KEYCAP_PX * s)
    for button in lay.buttons:
        x, y, w, h = button.rect
        radius = h // 2
        if button.primary:
            draw.rounded_rectangle((x, y, x + w - 1, y + h - 1), radius=radius, fill=(*action, 255))
            if pressed == button.index:
                draw.rounded_rectangle((x, y, x + w - 1, y + h - 1), radius=radius, fill=(0, 0, 0, 60))
            draw.text((x + w / 2.0, y + h / 2.0), button.label, font=action_face, fill=(*action_ink, 255), anchor="mm")
        else:
            if pressed == button.index:
                draw.rounded_rectangle((x, y, x + w - 1, y + h - 1), radius=radius, fill=(*ink, 40))
            draw.text((x + w / 2.0, y + h / 2.0), button.label, font=action_face, fill=(*action, 255), anchor="mm")
        if button.keycap:
            kx = x + w + max(2, int(round(4 * s)))
            kw = text_width(button.keycap, keycap_face) + max(6, int(round(10 * s)))
            kh = max(8, int(round(18 * s)))
            ky = int(round(y + (h - kh) / 2.0))
            draw.rounded_rectangle((kx, ky, kx + kw, ky + kh), radius=max(2, int(round(4 * s))),
                                   outline=(*ink, 110), width=max(1, int(round(s))))
            draw.text((kx + kw / 2.0, ky + kh / 2.0), button.keycap, font=keycap_face, fill=(*ink, 190), anchor="mm")
    return layer


# ---------------------------------------------------------------------------
# One frame.
# ---------------------------------------------------------------------------


@functools.lru_cache(maxsize=64)
def _feather_ramp(width: int, feather: int, pin: str) -> Image.Image:
    """Alpha across the cap: solid, then fading into the body over ``feather``."""
    width = max(1, int(width))
    feather = max(0, min(width, int(feather)))
    row = []
    for x in range(width):
        inner = (width - 1 - x) if pin == "left" else x  # distance from the cap's inner edge
        if feather <= 0 or inner >= feather:
            row.append(255)
        else:
            t = (inner + 0.5) / feather
            row.append(int(round(255 * t * t * (3 - 2 * t))))
    ramp = Image.new("L", (width, 1))
    ramp.putdata(row)
    return ramp


@functools.lru_cache(maxsize=64)
def _rim_masks(width: int, height: int) -> tuple[Image.Image, Image.Image]:
    """The capsule's 1 px inside edge, and its top highlight."""
    outer = capsule_alpha_mask(width, height)
    inner = Image.new("L", (width, height), 0)
    if width > 2 and height > 2:
        inner.paste(capsule_alpha_mask(width - 2, height - 2), (1, 1))
    ring = ImageChops.subtract(outer, inner)
    lowered = Image.new("L", (width, height), 0)
    if height > 3:
        lowered.paste(inner.crop((0, 0, width, height - 1)), (0, 1))
    top = ImageChops.subtract(inner, lowered)
    # Only the upper half: a highlight is where the light falls.
    top.paste(0, (0, height // 2, width, height))
    return ring, top


def compose(
    *,
    size: tuple[int, int],
    capsule: tuple[float, float, float, float],
    pin: str,
    head: float,
    feather: float,
    cap: Image.Image,
    body: Image.Image | None,
    body_origin: tuple[int, int],
    body_alpha: float,
    words: Image.Image | None = None,
    words_alpha: float = 0.0,
    words_blur: Image.Image | None = None,
    old_words: Image.Image | None = None,
    old_words_alpha: float = 0.0,
    rim: float = 0.0,
    theme: str = "dark",
    divider_x: float | None = None,
    scale: float = 1.0,
) -> Image.Image:
    """One frame of the lengthened Pill, the size of the window that holds it.

    ``capsule`` is (x, y, w, h) inside that window. Everything is clipped to
    one anti-aliased capsule of radius h/2, so the frame is one piece: the cap
    is the Pill's art compressed to ``head`` at the pinned end, the body behind
    it is the same art frosted (``body``, placed at ``body_origin`` and only
    cropped), the words sit on the body. At frame 0 (capsule = the Pill,
    head = its width, no feather, body and words at 0) the result is exactly
    the Pill's own frame.
    """
    frame = Image.new("RGBA", (max(1, int(size[0])), max(1, int(size[1]))), (0, 0, 0, 0))
    x0 = int(round(capsule[0]))
    y0 = int(round(capsule[1]))
    w = max(1, int(round(capsule[2])))
    h = max(1, int(round(capsule[3])))
    piece = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    if body is not None and body_alpha > 0.0:
        bx, by = x0 - int(body_origin[0]), y0 - int(body_origin[1])
        region = body.crop((bx, by, bx + w, by + h))
        if body_alpha < 1.0:
            region.putalpha(region.getchannel("A").point(lambda value: int(value * body_alpha)))
        piece.alpha_composite(region)
    for layer, alpha, blurred in ((old_words, old_words_alpha, None), (words, words_alpha, words_blur)):
        if layer is None or alpha <= 0.0:
            continue
        rise = int(round(TEXT_RISE_PX * scale * (1.0 - alpha)))
        bx, by = x0 - int(body_origin[0]), y0 - int(body_origin[1]) - rise
        region = layer.crop((bx, by, bx + w, by + h))
        if blurred is not None and alpha < 1.0:
            soft = blurred.crop((bx, by, bx + w, by + h))
            region = Image.blend(soft, region, alpha)
        region.putalpha(region.getchannel("A").point(lambda value, a=alpha: int(value * a)))
        piece.alpha_composite(region)
    head_w = max(1, min(w, int(round(head))))
    art = cap if cap.size == (head_w, h) else cap.convert("RGBA").resize((head_w, h), Image.Resampling.BILINEAR)
    art = art.convert("RGBA")
    fe = int(round(feather))
    if fe > 0:
        ramp = _feather_ramp(head_w, fe, pin).resize((head_w, h), Image.Resampling.NEAREST)
        art = art.copy()
        art.putalpha(ImageChops.multiply(art.getchannel("A"), ramp))
    art_x = 0 if pin == "left" else w - head_w
    if piece.getbbox() is None:
        # Nothing under the cap yet (frame 0): place the Pill's own pixels
        # exactly. Compositing onto transparency re-rounds the colour of every
        # soft edge pixel, and frame 0 must be the Pill's frame.
        piece.paste(art, (art_x, 0))
    else:
        piece.alpha_composite(art, (art_x, 0))
    if divider_x is not None and body is not None and body_alpha > 0.0:
        dx = int(round(divider_x)) - x0
        if 0 <= dx < w:
            # Drawn on its own layer and composited: ImageDraw REPLACES the
            # pixels it touches, which cut a half-transparent seam through the
            # capsule (one outline must stay one solid piece).
            strength = max(0.0, min(1.0, body_alpha))
            line = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            draw = ImageDraw.Draw(line)
            draw.line((dx, 0, dx, h), fill=(0, 0, 0, int(128 * strength)))
            light = dx + 1 if pin == "left" else dx - 1
            draw.line((light, 0, light, h), fill=(255, 255, 255, int(30 * strength)))
            piece.alpha_composite(line)
    if rim > 0.0 and w > 4 and h > 4:
        ring, top = _rim_masks(w, h)
        shade = Image.new("RGBA", (w, h), (0, 0, 0, 255))
        shade.putalpha(ring.point(lambda value: int(value * RIM_ALPHA.get(theme, 0.42) * rim)))
        piece.alpha_composite(shade)
        light = Image.new("RGBA", (w, h), (255, 255, 255, 255))
        light.putalpha(top.point(lambda value: int(value * HIGHLIGHT_ALPHA.get(theme, 0.14) * rim)))
        piece.alpha_composite(light)
    piece.putalpha(ImageChops.multiply(piece.getchannel("A"), capsule_alpha_mask(w, h)))
    frame.paste(piece, (x0, y0))
    return frame


# ---------------------------------------------------------------------------
# The pip: a 6 px light set into the Pill's rim (message spec 5.3).
# ---------------------------------------------------------------------------

PIP_COLOURS = {"green": (80, 255, 216), "red": (255, 92, 56)}
PIP_BREATHE_MS = 900.0


def pip_centre(width: float, height: float, scale: float) -> tuple[float, float]:
    """5 px inside the right cap, vertically centred."""
    radius = 3.0 * scale
    return float(width) - 5.0 * scale - radius, float(height) / 2.0


def pip_scale(age_ms: float | None) -> float:
    """It breathes once when it arrives: 1 to 1.35 to 1 over 900 ms."""
    if age_ms is None or age_ms < 0 or age_ms >= PIP_BREATHE_MS:
        return 1.0
    return 1.0 + 0.35 * math.sin(math.pi * age_ms / PIP_BREATHE_MS)


def paint_pip(frame: Image.Image, centre: tuple[float, float], *, severity: str, scale: float, grow: float = 1.0) -> None:
    """Teal: an update is waiting. Ember: it installs itself. Ringed 1.5 px in
    black 55% so it reads on any art, with a 6 px glow in its own colour."""
    colour = PIP_COLOURS.get(severity, PIP_COLOURS["green"])
    radius = 3.0 * scale * grow
    ring = 1.5 * scale
    glow = 6.0 * scale
    supersample = 4
    span = int(math.ceil(radius + ring + glow)) + 2
    side = span * 2
    sprite = Image.new("RGBA", (side * supersample, side * supersample), (0, 0, 0, 0))
    halo = Image.new("L", sprite.size, 0)
    c = side * supersample / 2.0
    ImageDraw.Draw(halo).ellipse(
        (c - (radius + glow * 0.5) * supersample, c - (radius + glow * 0.5) * supersample,
         c + (radius + glow * 0.5) * supersample, c + (radius + glow * 0.5) * supersample), fill=110)
    halo = halo.filter(ImageFilter.GaussianBlur(glow * supersample / 2.5))
    glow_layer = Image.new("RGBA", sprite.size, (*colour, 255))
    glow_layer.putalpha(halo)
    sprite.alpha_composite(glow_layer)
    draw = ImageDraw.Draw(sprite)
    outer = (radius + ring) * supersample
    draw.ellipse((c - outer, c - outer, c + outer, c + outer), fill=(0, 0, 0, 140))
    inner = radius * supersample
    draw.ellipse((c - inner, c - inner, c + inner, c + inner), fill=(*colour, 255))
    sprite = sprite.resize((side, side), Image.Resampling.BOX)
    left = int(round(centre[0] - side / 2.0))
    top = int(round(centre[1] - side / 2.0))
    layer = Image.new("RGBA", frame.size, (0, 0, 0, 0))
    layer.paste(sprite, (left, top))
    # The glow stays inside the Pill: the frame's own alpha bounds it, so the
    # pip never adds clickable pixels outside the capsule.
    bound = frame.getchannel("A")
    layer.putalpha(ImageChops.multiply(layer.getchannel("A"), bound))
    frame.alpha_composite(layer)


__all__ = [
    "PILL_FEEDBACK_LOOKS",
    "FlagLayout",
    "compose",
    "frosted_body",
    "layout",
    "measure",
    "paint_pip",
    "pill_feedback_frame",
    "pip_centre",
    "pip_scale",
    "tone_wash",
    "words_layer",
]
