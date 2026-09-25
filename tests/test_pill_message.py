"""X-741: the lengthened Pill, drawn with no window (knight_flow/pill_message.py).

The owner's rule: a message is the Pill itself changing shape in its own
material, one outline, never a separate piece. These tests draw it from the
Pill's real art (flow_pill_240.png) and check what a person would see:

* one continuous capsule at every tone, theme and pinned end: nothing outside
  it, no gap along its midline, an outline that is exactly the Pill's own
  anti-aliased capsule (radius half the height);
* frame 0 is the Pill's own frame, pixel for pixel;
* the words read: measured pixel by pixel over every tone's frosted body,
  titles at 7:1 or better and details at 4.5:1 or better, in dark and light;
* a segment is the same outline with a 1 px divider, its actions inside it and
  their press areas 44 px tall; long words wrap to two title lines and three
  detail lines and end in "...";
* the pip is a 6 px light inside the Pill's right cap that adds no pixel
  outside the Pill;
* the presenter moves, resizes and repaints in one UpdateLayeredWindow call.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from knight_flow import island, pill_message
from knight_flow.layered_window import LayeredPresenter, capsule_alpha_mask

ASSETS = Path(__file__).resolve().parents[1] / "knight_flow" / "assets"
SCALE = 1.5


def pill_art(width: int, height: int) -> Image.Image:
    strip = Image.open(ASSETS / "flow_pill_240.png").convert("RGBA")
    meta = json.loads((ASSETS / "flow_pill_240.json").read_text(encoding="utf-8-sig"))
    frame = strip.crop((0, 0, meta["frame_width"], meta["frame_height"])).resize((width, height), Image.Resampling.LANCZOS)
    frame.putalpha(capsule_alpha_mask(width, height))
    return frame


PILL_W, PILL_H = int(96 * SCALE), int(18 * SCALE)
ART = pill_art(PILL_W, PILL_H)


def settled(message: island.Message, *, theme: str = "dark", pin: str = "left"):
    lay = pill_message.layout(message, scale=SCALE, work_width=1920, pill_w=PILL_W, pin=pin)
    size = (lay.width + 12, lay.height)
    x = 0 if pin == "left" else 12
    body = pill_message.frosted_body(ART, size, theme=theme, scale=SCALE, tone=message.tone, tone_level=1.0)
    words = Image.new("RGBA", size, (0, 0, 0, 0))
    words.alpha_composite(pill_message.words_layer(lay, lay.size, theme=theme, progress=message.progress), (x, 0))
    cap = pill_message.tone_wash(ART, message.tone, 1.0)
    divider = None
    if lay.divider_x is not None:
        divider = x + lay.head if pin == "left" else x + lay.width - lay.head - 1
    frame = pill_message.compose(
        size=size, capsule=(x, 0, lay.width, lay.height), pin=pin, head=lay.head, feather=lay.feather, cap=cap,
        body=body, body_origin=(0, 0), body_alpha=1.0, words=words, words_alpha=1.0, rim=1.0, theme=theme,
        divider_x=divider, scale=SCALE,
    )
    return lay, frame, body, (x, 0, lay.width, lay.height)


def pieces(mask: np.ndarray) -> int:
    seen = np.zeros_like(mask, dtype=bool)
    count = 0
    for y0, x0 in zip(*np.nonzero(mask)):
        if seen[y0, x0]:
            continue
        count += 1
        stack = [(y0, x0)]
        seen[y0, x0] = True
        while stack:
            y, x = stack.pop()
            for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                if 0 <= ny < mask.shape[0] and 0 <= nx < mask.shape[1] and mask[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    stack.append((ny, nx))
    return count


MESSAGES = {
    "info": island.message_from("Your speech provider did not answer", detail="This one was transcribed on this PC."),
    "done": island.message_from("Copied your last dictation", tone="done"),
    "warn": island.message_from("Using this PC for now", detail="Your speech provider keeps failing.", tone="warn"),
    "error": island.message_from("The microphone did not start.", detail="Check your microphone.", tone="error"),
    "busy": island.message_from("Installing 1.2.4", tone="busy", progress=0.4),
    "segment": island.message_from('Added "Kubernetes"', tone="done",
                                   actions=(island.FlagAction("Undo", lambda: None, "<Alt-d>"),)),
}


class OneContinuousCapsuleTests(unittest.TestCase):
    def test_every_tone_theme_and_end_is_one_capsule(self) -> None:
        for name, message in MESSAGES.items():
            for theme in ("dark", "light"):
                for pin in ("left", "right"):
                    with self.subTest(message=name, theme=theme, pin=pin):
                        lay, frame, _body, (x, y, w, h) = settled(message, theme=theme, pin=pin)
                        alpha = np.asarray(frame.getchannel("A")).astype(int)
                        self.assertEqual(pieces(alpha > 0), 1)
                        outside = alpha.copy()
                        outside[y:y + h, x:x + w] = 0
                        self.assertEqual(int(outside.max()), 0, "drawn outside the capsule")
                        self.assertTrue(np.all(alpha[y + h // 2, x + 1:x + w - 1] > 0), "a gap on the midline")
                        mask = np.asarray(capsule_alpha_mask(w, h)).astype(int)
                        self.assertLessEqual(int(np.abs(alpha[y:y + h, x:x + w] - mask).max()), 1,
                                             "the outline is not the Pill's capsule of radius h/2")

    def test_the_height_is_36_54_and_18_more_per_line(self) -> None:
        one = pill_message.layout(MESSAGES["done"], scale=1.0, work_width=1920, pill_w=96)
        two = pill_message.layout(MESSAGES["info"], scale=1.0, work_width=1920, pill_w=96)
        self.assertEqual((one.height, two.height), (36, 54))
        long = island.message_from("A title", detail=" ".join(["detail"] * 80))
        three = pill_message.layout(long, scale=1.0, work_width=1920, pill_w=96)
        self.assertEqual(three.height, 36 + 18 * 3, "detail stops at three lines")
        self.assertTrue(three.lines[-1][0].endswith("..."))
        self.assertLessEqual(three.width, 480)

    def test_frame_zero_is_the_pills_own_frame(self) -> None:
        frame = pill_message.compose(
            size=(PILL_W, PILL_H), capsule=(0, 0, PILL_W, PILL_H), pin="left", head=PILL_W, feather=0.0, cap=ART,
            body=None, body_origin=(0, 0), body_alpha=0.0,
        )
        own = ART.copy()
        own.putalpha(Image.fromarray(
            (np.asarray(ART.getchannel("A")).astype(int) * np.asarray(capsule_alpha_mask(PILL_W, PILL_H)).astype(int)
             // 255).astype(np.uint8)))
        difference = np.abs(np.asarray(frame).astype(int) - np.asarray(own).astype(int))
        self.assertLessEqual(int(difference.max()), 1)


def luminance(rgb: np.ndarray) -> np.ndarray:
    channel = rgb / 255.0
    linear = np.where(channel <= 0.04045, channel / 12.92, ((channel + 0.055) / 1.055) ** 2.4)
    return linear @ np.array([0.2126, 0.7152, 0.0722])


def worst_contrast(ink: np.ndarray, ground: np.ndarray) -> float:
    first, second = luminance(ink), luminance(ground)
    light, dark = np.maximum(first, second), np.minimum(first, second)
    return float(((light + 0.05) / (dark + 0.05)).min())


class TheWordsReadTests(unittest.TestCase):
    """Measured over the body behind the words, every tone, both themes."""

    def test_titles_7_to_1_and_details_4_5_to_1_over_every_tone(self) -> None:
        for tone in ("info", "done", "warn", "error"):
            for theme in ("dark", "light"):
                with self.subTest(tone=tone, theme=theme):
                    message = island.message_from("Title", detail="Detail", tone=tone)
                    lay = pill_message.layout(message, scale=SCALE, work_width=1920, pill_w=PILL_W)
                    body = pill_message.frosted_body(ART, lay.size, theme=theme, scale=SCALE, tone=tone, tone_level=1.0)
                    x, y, w, h = lay.words_box
                    ground = np.asarray(body.convert("RGB"), dtype=float)[y:y + h, x:x + max(w, 40)].reshape(-1, 3)
                    ink = np.array(pill_message.INK[theme], dtype=float)
                    detail = ink * pill_message.DETAIL_ALPHA[theme] + ground * (1 - pill_message.DETAIL_ALPHA[theme])
                    title_ratio = worst_contrast(np.broadcast_to(ink, ground.shape), ground)
                    detail_ratio = worst_contrast(detail, ground)
                    self.assertGreaterEqual(title_ratio, 7.0, f"title {title_ratio:.2f}:1")
                    self.assertGreaterEqual(detail_ratio, 4.5, f"detail {detail_ratio:.2f}:1")


class SegmentTests(unittest.TestCase):
    def test_a_segment_keeps_the_pill_end_and_its_actions_inside_one_outline(self) -> None:
        for pin in ("left", "right"):
            with self.subTest(pin=pin):
                lay, frame, _body, (x, y, w, h) = settled(MESSAGES["segment"], pin=pin)
                self.assertEqual(lay.mode, "segment")
                self.assertEqual(lay.head, PILL_W, "the Pill end lost its full width")
                self.assertEqual(h, round(36 * SCALE))
                for button in lay.buttons:
                    bx, by, bw, bh = button.rect
                    self.assertTrue(0 <= bx and bx + bw <= w and 0 <= by and by + bh <= h, "an action outside the Pill")
                    self.assertEqual(button.hit[3], round(44 * SCALE), "the press area is not 44 px")
                    pill_left = 0 if pin == "left" else w - PILL_W
                    self.assertFalse(pill_left <= bx < pill_left + PILL_W, "an action on the Pill end")
                divider = lay.divider_x
                self.assertIsNotNone(divider)
                column = np.asarray(frame.convert("RGB"))[h // 2, x + (lay.head if pin == "left" else w - lay.head - 1)]
                neighbour = np.asarray(frame.convert("RGB"))[h // 2, x + (lay.head + 3 if pin == "left" else w - lay.head - 4)]
                self.assertLess(int(column.sum()), int(neighbour.sum()) + 1, "no divider in the Pill's own material")

    def test_the_accelerator_is_named_on_its_keycap(self) -> None:
        lay = pill_message.layout(MESSAGES["segment"], scale=1.0, work_width=1920, pill_w=96)
        self.assertEqual(lay.buttons[0].keycap, "Alt+D")


class PipTests(unittest.TestCase):
    def test_the_pip_sits_inside_the_right_cap_and_adds_nothing_outside(self) -> None:
        frame = ART.copy()
        before = np.asarray(frame.getchannel("A")).copy()
        cx, cy = pill_message.pip_centre(PILL_W, PILL_H, SCALE)
        self.assertAlmostEqual(cx, PILL_W - 8 * SCALE)
        self.assertAlmostEqual(cy, PILL_H / 2)
        pill_message.paint_pip(frame, (cx, cy), severity="red", scale=SCALE, grow=1.35)
        after = np.asarray(frame.getchannel("A"))
        self.assertTrue(np.all(after[before == 0] == 0), "the pip's glow made clickable pixels outside the Pill")
        red, green, blue = frame.convert("RGB").getpixel((int(cx), int(cy)))
        self.assertEqual((red, green, blue), pill_message.PIP_COLOURS["red"])

    def test_it_breathes_once(self) -> None:
        self.assertEqual(pill_message.pip_scale(0.0), 1.0)
        self.assertAlmostEqual(pill_message.pip_scale(450.0), 1.35)
        self.assertEqual(pill_message.pip_scale(900.0), 1.0)


class OneCallMovesAndPaintsTests(unittest.TestCase):
    def test_present_with_a_position_uses_update_layered_at(self) -> None:
        calls = []

        class Api:
            def root_handle(self, client):
                return 7

            def get_extended_style(self, hwnd):
                return 0x00080000

            def set_extended_style(self, hwnd, style):
                return True

            def clear_region(self, hwnd):
                return True

            def update_layered(self, hwnd, width, height, bgra, alpha):
                calls.append(("in place", width, height))
                return True

            def update_layered_at(self, hwnd, x, y, width, height, bgra, alpha):
                calls.append(("moved", x, y, width, height))
                return True

            def close(self):
                pass

        class Window:
            def winfo_ismapped(self):
                return 1

            def winfo_id(self):
                return 3

        presenter = LayeredPresenter(Window(), api=Api())
        image = Image.new("RGBA", (40, 12), (1, 2, 3, 255))
        self.assertTrue(presenter.present(image, position=(100, 200)))
        self.assertTrue(presenter.present(image))
        self.assertEqual(calls, [("moved", 100, 200, 40, 12), ("in place", 40, 12)])


if __name__ == "__main__":
    unittest.main()
