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
* the pip is a 6 px light in a dark well inside the Pill's right cap: it never
  changes the Pill's alpha, its lens reads at 3:1 on its well on every frame of
  the art, it rises out once and sinks back once, and only fades under reduced
  motion;
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


class TheWordsWrapEvenlyTests(unittest.TestCase):
    """2026-10-09, the owner: the Pill's message bubbles are "ugly". One measured reason:
    greedy wrapping left a word alone on the last line ("...by the built-in rules, not the /
    model."). A wrapped title or detail is now balanced, as CSS text-wrap: balance does:
    the same number of lines, as even as they can be, so never one word alone."""

    LONG = island.message_from("Your speech provider did not answer in time, so this one was transcribed here.",
                               detail="Talk DAT! keeps trying your provider and says so when it answers again.")

    @staticmethod
    def blocks(message: island.Message) -> tuple[list[str], list[str]]:
        lay = pill_message.layout(message, scale=1.0, work_width=1920, pill_w=96)
        return ([text for text, title, _x, _y in lay.lines if title], [text for text, title, _x, _y in lay.lines if not title])

    def test_no_wrapped_line_is_one_word_alone(self) -> None:
        # Whether a title wraps at all depends on the platform's font: in the Mac's SF the formatting notice
        # fits on one line (364 px), where Segoe UI wraps it (Mac native suite, 2026-10-11). So the rule is
        # checked wherever the layout wraps a title, and at a width that makes every platform wrap it.
        texts = ("Your text was formatted by the built-in rules, not the model.", self.LONG.title)
        for text in texts:
            titles, _details = self.blocks(island.message_from(text))
            with self.subTest(text=text, width="layout"):
                if len(titles) > 1:
                    self.assertGreater(len(titles[-1].split()), 1, f"a word alone: {titles}")
        face = pill_message.font(True, pill_message.TITLE_PX)
        for text in texts:
            lines = pill_message.wrap(text, face, pill_message.text_width(text, face) * 0.6, 3)
            with self.subTest(text=text, width="60%"):
                self.assertGreater(len(lines), 1)
                self.assertGreater(len(lines[-1].split()), 1, f"a word alone: {lines}")

    def test_wrapped_lines_are_even(self) -> None:
        titles, details = self.blocks(self.LONG)
        for block, bold, size in ((titles, True, pill_message.TITLE_PX), (details, False, pill_message.DETAIL_PX)):
            widths = [pill_message.text_width(line, pill_message.font(bold, size)) for line in block]
            with self.subTest(block=block):
                if len(widths) > 1:
                    self.assertGreaterEqual(min(widths) / max(widths), 0.6, block)

    def test_balancing_never_adds_a_line_or_drops_a_word(self) -> None:
        face = pill_message.font(True, pill_message.TITLE_PX)
        for text in ("Your text was formatted by the built-in rules, not the model.", self.LONG.title, "Short title",
                     " ".join(["word"] * 60)):
            greedy = pill_message.wrap(text, face, 400, 2, balance=False)
            balanced = pill_message.wrap(text, face, 400, 2)
            with self.subTest(text=text[:30]):
                self.assertEqual(len(balanced), len(greedy))
                if not greedy[-1].endswith("..."):
                    self.assertEqual(" ".join(balanced).split(), text.split())


class TheBubbleIsOneCalmMaterialTests(unittest.TestCase):
    """2026-10-09, the owner on the Pill's message bubbles: "ugly". Two measured causes.
    The Pill's art met the frosted body at a hard edge: a 44 px cap feathered over only
    its last 18 px, a sticker edge in the light theme above all. And an error washed the
    whole body in the ember at full strength (the dark body's saturation was 0.81),
    shouting where the red cap already says it. The cap now melts into the body over most
    of its width, and the body takes a calmer share of an error's or a warning's tone."""

    @staticmethod
    def saturation(theme: str, tone: str) -> float:
        message = island.message_from("The microphone did not start.", detail="Check your microphone.", tone=tone)
        lay = pill_message.layout(message, scale=SCALE, work_width=1920, pill_w=PILL_W)
        body = pill_message.frosted_body(ART, lay.size, theme=theme, scale=SCALE, tone=tone, tone_level=1.0)
        rgb = np.asarray(body.convert("RGB"), dtype=float) / 255.0
        x, y, w, h = lay.words_box
        region = rgb[y:y + h, x:x + max(w, 40)].reshape(-1, 3)
        top, low = region.max(axis=1), region.min(axis=1)
        return float(((top - low) / np.maximum(top, 1e-6)).mean())

    def test_the_cap_melts_into_the_body_over_most_of_its_width(self) -> None:
        self.assertGreaterEqual(island.FEATHER, 0.7 * island.CAP, "the Pill's art ends at a hard edge")
        lay = pill_message.layout(MESSAGES["info"], scale=SCALE, work_width=1920, pill_w=PILL_W)
        self.assertGreaterEqual(lay.feather, 0.7 * lay.head)

    def test_an_error_is_said_calmly(self) -> None:
        # Measured at full strength: dark 0.81, light 0.125. At 55% of the wash: 0.59 and 0.078.
        self.assertLessEqual(self.saturation("dark", "error"), 0.7)
        self.assertLessEqual(self.saturation("light", "error"), 0.1)

    def test_the_cap_keeps_the_full_tone(self) -> None:
        washed = pill_message.tone_wash(ART, "error", 1.0)
        self.assertNotEqual(np.asarray(washed).tobytes(), np.asarray(ART).tobytes())
        self.assertEqual(pill_message.BODY_TONE.get("done", 1.0), 1.0, "success keeps its full teal body")


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
    """2026-10-09, the owner: the dots "look cut and paste"; they must be "nicely designed
    lights that look like they're almost like animating out of" the Pill. The light is a
    dark well, a 6 px lens with a hot spot, rim and glint, and a glow on the glass; it
    rises out once (320 ms) and sinks back once (180 ms), and fades under reduced motion."""

    REST = (1.0, 1.0, 1.0, 1.0, 0.0, 1.0)

    def painted(self, severity: str, look=None, art=None) -> Image.Image:
        frame = (art or ART).copy()
        pill_message.paint_pip(frame, pill_message.pip_centre(frame.width, frame.height, SCALE), severity=severity,
                               scale=SCALE, look=self.REST if look is None else look)
        return frame

    def test_the_light_sits_in_the_right_cap_and_never_changes_the_alpha(self) -> None:
        cx, cy = pill_message.pip_centre(PILL_W, PILL_H, SCALE)
        self.assertAlmostEqual(cx, PILL_W - 8 * SCALE)
        self.assertAlmostEqual(cy, PILL_H / 2)
        before = np.asarray(ART.getchannel("A"))
        for moment in (0.0, 60.0, 120.0, 160.0, 220.0, 320.0):
            for severity in ("green", "red"):
                frame = self.painted(severity, pill_message.pip_look(moment))
                with self.subTest(moment=moment, severity=severity):
                    self.assertTrue(np.array_equal(np.asarray(frame.getchannel("A")), before),
                                    "the light changed the Pill's alpha (a click target)")

    def test_the_lens_is_its_colour_at_the_centre(self) -> None:
        cx, cy = pill_message.pip_centre(PILL_W, PILL_H, SCALE)
        red, green, blue = self.painted("red").convert("RGB").getpixel((int(cx), int(cy)))
        self.assertGreater(red, 200)
        self.assertLess(green, 120)
        red, green, blue = self.painted("green").convert("RGB").getpixel((int(cx), int(cy)))
        self.assertGreater(green, 200)
        self.assertLess(red, 140)

    def test_the_lens_reads_on_its_well_on_every_frame_of_the_art(self) -> None:
        strip = Image.open(ASSETS / "flow_pill_240.png").convert("RGBA")
        meta = json.loads((ASSETS / "flow_pill_240.json").read_text(encoding="utf-8-sig"))
        fw, fh, cols = meta["frame_width"], meta["frame_height"], meta["columns"]
        w, h = int(92 * SCALE), int(26 * SCALE)
        cx, cy = pill_message.pip_centre(w, h, SCALE)
        yy, xx = np.mgrid[0:h, 0:w]
        dist = np.hypot(xx + 0.5 - cx, yy + 0.5 - cy)
        lens = dist <= pill_message.PIP_LENS_R * SCALE * 0.7
        well = (dist >= pill_message.PIP_LENS_R * SCALE + 0.9) & (dist <= pill_message.PIP_WELL_R * SCALE - 0.6)
        worst = []
        for index in range(0, 240, 4):
            x, y = (index % cols) * fw, (index // cols) * fh
            art = strip.crop((x, y, x + fw, y + fh)).resize((w, h), Image.Resampling.LANCZOS)
            art.putalpha(capsule_alpha_mask(w, h))
            for severity in ("green", "red"):
                rgb = np.asarray(self.painted(severity, art=art).convert("RGB"), np.float64)
                ratio = contrast_of(rgb[lens].mean(axis=0), rgb[well].mean(axis=0))
                worst.append((round(ratio, 2), index, severity))
        self.assertGreaterEqual(min(worst)[0], 3.0, f"the lens does not stand off its well: {min(worst)}")

    def test_it_rises_out_once_then_holds_still(self) -> None:
        look = pill_message.pip_look
        well_scale, well_alpha, lens_scale, lens_alpha, rise, glow = look(0.0)
        self.assertEqual((well_alpha, lens_alpha, glow), (0.0, 0.0, 0.0), "it is there before it arrives")
        peak = look(160.0)
        self.assertGreater(peak[2], 1.05, "the lens does not overshoot as it rises")
        self.assertGreater(peak[5], 1.5, "the glow does not flare")
        self.assertGreater(look(60.0)[4], 0.0, "the lens does not rise out of the well")
        self.assertEqual(look(pill_message.PIP_ENTRANCE_MS), self.REST)
        self.assertEqual(look(60_000.0), self.REST, "it moves at rest")
        self.assertTrue(pill_message.pip_moving(pill_message.PIP_ENTRANCE_MS - 1))
        self.assertFalse(pill_message.pip_moving(pill_message.PIP_ENTRANCE_MS + 1))

    def test_it_sinks_back_from_where_it_was(self) -> None:
        start = pill_message.pip_look(100.0)  # cleared mid-entrance
        self.assertEqual(pill_message.pip_look(0.0, leaving=True, start=start), start, "the exit jumps")
        gone = pill_message.pip_look(pill_message.PIP_EXIT_MS, leaving=True, start=self.REST)
        self.assertEqual((gone[1], gone[3], gone[5]), (0.0, 0.0, 0.0))
        self.assertFalse(pill_message.pip_moving(pill_message.PIP_EXIT_MS + 1, leaving=True))

    def test_reduced_motion_only_fades(self) -> None:
        for moment in (0.0, 30.0, 60.0, 90.0, 120.0, 500.0):
            well_scale, well_alpha, lens_scale, lens_alpha, rise, glow = pill_message.pip_look(moment, reduced=True)
            with self.subTest(moment=moment):
                self.assertEqual((well_scale, lens_scale, rise), (1.0, 1.0, 0.0), "it moves under reduced motion")
                self.assertLessEqual(glow, 1.0)
        self.assertEqual(pill_message.pip_look(pill_message.PIP_FADE_IN_MS, reduced=True), self.REST)
        self.assertLess(pill_message.PIP_FADE_IN_MS, pill_message.PIP_ENTRANCE_MS)

    def test_the_lights_cache_stays_small(self) -> None:
        # Review B13 (2026-10-10): one cached frame of the light holds five float32
        # squares, 149 KB at 200%, so 384 of them could keep 57 MB for good. A rise and a
        # fall of each colour at the Pill's 16 ms frame use 58 entries (measured).
        self.assertLessEqual(pill_message._pip_layers.cache_parameters()["maxsize"], 64)
        # Review N6: and no smaller than that measured need, or every rise re-renders.
        self.assertGreaterEqual(pill_message._pip_layers.cache_parameters()["maxsize"], 58)

    def test_painting_touches_only_the_lights_own_square(self) -> None:
        wide = pill_art(int(240 * SCALE), PILL_H)
        frame = wide.copy()
        cx, cy = 60.0 * SCALE, PILL_H / 2
        pill_message.paint_pip(frame, (cx, cy), severity="green", scale=SCALE, look=pill_message.pip_look(160.0))
        changed = np.argwhere(np.any(np.asarray(frame) != np.asarray(wide), axis=2))
        self.assertGreater(len(changed), 0)
        reach = pill_message.pip_reach(SCALE)
        self.assertLessEqual(int(np.abs(changed[:, 1] - cx).max()), reach + 1)


def contrast_of(first, second) -> float:
    def lum(rgb):
        v = np.asarray(rgb, np.float64) / 255.0
        v = np.where(v <= 0.04045, v / 12.92, ((v + 0.055) / 1.055) ** 2.4)
        return float(0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2])
    light, dark = sorted((lum(first), lum(second)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


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
