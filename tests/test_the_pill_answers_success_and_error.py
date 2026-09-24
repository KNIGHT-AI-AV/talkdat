"""A finished take and a failed one no longer look like nothing happened.

Owner's audit, 2026-09-23 (shots tk-pill__6-captured-pasted and tk-pill__7-error
against tk-pill__1-idle-compact): the Pill's "captured/pasted" and "error"
states drew exactly the idle artwork, and the Pill never shows text, so an
error reached nobody but the Status window's "Last message" line.

What is pinned here:

* success is a short teal settle over the Pill's own artwork (about half a
  second, in fast and out slow), then idle;
* error is an ember glow with two soft beats, held until the next take or
  about three seconds, and it brings a message above the Pill that says what
  happened and what to do;
* reduced motion keeps the colour and drops the motion: a static tint for the
  same span;
* idle, listening and processing are untouched;
* the toast takes the theme palette like every other Tk popup (it was fixed
  #16181d / #f2f4f8, a black slab above the Pill in a light theme).

The GUI half builds a real Overlay and runs through
scripts/run_tests_offscreen.py, so nothing appears on anyone's screen.
"""
from __future__ import annotations

import copy
import time
import unittest
from unittest import mock

import numpy as np
from PIL import Image

from knight_flow.config import DEFAULT_CONFIG
from tests import gui_offscreen  # noqa: F401  (X-164: never on a human's screen)


def forget_default_root() -> None:
    """Tk binds every image made without a master to tkinter's default root.
    A root left behind by an earlier module would own this module's images
    ("image pyimageNN doesn't exist"), so each test starts and ends without
    one, as test_usage_counts_tk does."""
    import tkinter

    existing = getattr(tkinter, "_default_root", None)
    try:
        alive = existing is not None and bool(existing.winfo_exists())
    except Exception:
        alive = False
    if not alive:
        tkinter._default_root = None  # type: ignore[attr-defined]


def pump(root, seconds: float) -> None:
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        root.update()
        time.sleep(0.01)


def body_colour(image: Image.Image) -> tuple[float, float, float]:
    """Mean RGB over the Pill's opaque body (the colour key and the soft lift
    around it are left out)."""
    pixels = np.asarray(image.convert("RGBA"), dtype=np.float32)
    body = pixels[pixels[..., 3] >= 250]
    if not len(body):
        raise AssertionError("the frame has no opaque Pill body in it")
    red, green, blue = (float(body[:, index].mean()) for index in range(3))
    return red, green, blue


def is_teal(colour: tuple[float, float, float]) -> bool:
    red, green, _blue = colour
    return green - red > 45


def is_ember(colour: tuple[float, float, float]) -> bool:
    red, green, blue = colour
    return red - (green + blue) / 2 > 85 and green < 50


class TheEnvelopesTests(unittest.TestCase):
    """The timing, without a display."""

    def level(self, state: str, ms: float, reduced: bool = False) -> float:
        from knight_flow.pill_motion import state_feedback_level

        return state_feedback_level(state, ms, reduced_motion=reduced)

    def test_the_other_states_never_get_a_look(self) -> None:
        for state in ("idle", "starting", "connected", "listening", "command", "processing"):
            for ms in (0, 50, 400, 1500, 2999):
                with self.subTest(state=state, ms=ms):
                    self.assertEqual(self.level(state, ms), 0.0)

    def test_success_is_a_half_second_settle(self) -> None:
        from knight_flow.pill_motion import SUCCESS_FEEDBACK_MS

        self.assertLessEqual(SUCCESS_FEEDBACK_MS, 600, "a success receipt must be brief")
        self.assertGreater(self.level("captured", 60), 0.3, "it must arrive fast")
        peak = max(self.level("captured", ms) for ms in range(0, SUCCESS_FEEDBACK_MS, 5))
        self.assertGreaterEqual(peak, 0.8)
        self.assertLessEqual(peak, 1.0)
        # After the peak it only ever settles; no bounce back up.
        start = next(ms for ms in range(0, SUCCESS_FEEDBACK_MS) if self.level("captured", ms) >= peak - 1e-9)
        previous = peak
        for ms in range(start, SUCCESS_FEEDBACK_MS + 1, 5):
            current = self.level("captured", ms)
            self.assertLessEqual(current, previous + 1e-9, f"the settle rose again at {ms} ms")
            previous = current
        self.assertEqual(self.level("captured", SUCCESS_FEEDBACK_MS), 0.0)
        self.assertEqual(self.level("captured", 5000), 0.0)

    def test_error_holds_for_about_three_seconds_with_two_beats(self) -> None:
        from knight_flow.pill_motion import ERROR_FEEDBACK_MS

        self.assertTrue(2500 <= ERROR_FEEDBACK_MS <= 3500)
        held = [self.level("error", ms) for ms in range(200, 2500, 10)]
        self.assertGreaterEqual(min(held), 0.7, "the ember must stay unmistakable while held")
        early = [self.level("error", ms) for ms in range(140, 900, 5)]
        dips = sum(
            1
            for index in range(1, len(early) - 1)
            if early[index] < early[index - 1] and early[index] <= early[index + 1]
        )
        self.assertEqual(dips, 2, "the error look should beat twice, gently, then hold")
        self.assertGreater(max(early) - min(early), 0.15, "a pulse too faint to see is not a pulse")
        self.assertEqual(self.level("error", ERROR_FEEDBACK_MS), 0.0)

    def test_reduced_motion_is_a_static_tint_for_the_same_span(self) -> None:
        from knight_flow.pill_motion import ERROR_FEEDBACK_MS, SUCCESS_FEEDBACK_MS

        for state, span in (("captured", SUCCESS_FEEDBACK_MS), ("error", ERROR_FEEDBACK_MS)):
            with self.subTest(state=state):
                values = {round(self.level(state, ms, reduced=True), 6) for ms in range(0, span, 7)}
                self.assertEqual(len(values), 1, f"{state} moved under reduced motion: {sorted(values)}")
                self.assertGreater(values.pop(), 0.5, "reduced motion must keep the colour")
                self.assertEqual(self.level(state, span, reduced=True), 0.0)

    def test_the_message_stays_up_long_enough_to_read(self) -> None:
        from knight_flow.pill_motion import error_toast_hold_ms

        self.assertGreaterEqual(error_toast_hold_ms("No speech was heard."), 4000)
        long = error_toast_hold_ms(
            "The microphone did not start.",
            "Check that it is plugged in, or open Mic Doctor in Settings, Dictation.",
        )
        self.assertGreater(long, error_toast_hold_ms("No speech was heard."))
        self.assertLessEqual(error_toast_hold_ms("word " * 400), 8000)


class TheLooksTests(unittest.TestCase):
    """The pictures, without a window: a wash, never a sticker."""

    def artwork(self) -> Image.Image:
        """A stand-in with the real Pill's structure: a warm-to-cool striped
        body inside a transparent surround, with an antialiased edge."""
        width, height = 138, 39
        image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        pixels = image.load()
        for x in range(width):
            for y in range(height):
                inside = 2 <= x < width - 2 and 2 <= y < height - 2
                if not inside:
                    continue
                t = x / (width - 1)
                stripe = 0.55 + 0.45 * ((x + y * 2) % 7 < 3)
                red = int((255 * (1 - t) + 20 * t) * stripe)
                green = int((90 * (1 - t) + 110 * t) * stripe)
                blue = int((40 * (1 - t) + 120 * t) * stripe)
                pixels[x, y] = (red, green, blue, 255)
        return image

    def test_each_look_is_unmistakable_and_keeps_the_shape(self) -> None:
        from knight_flow.overlay import pill_feedback_frame

        source = self.artwork()
        self.assertFalse(is_teal(body_colour(source)))
        self.assertFalse(is_ember(body_colour(source)))
        teal = pill_feedback_frame(source, "captured", 0.85)
        ember = pill_feedback_frame(source, "error", 1.0)
        for name, frame in (("captured", teal), ("error", ember)):
            with self.subTest(look=name):
                self.assertEqual(frame.size, source.size)
                self.assertEqual(frame.getchannel("A").tobytes(), source.getchannel("A").tobytes(),
                                 "the look changed the Pill's silhouette")
        self.assertTrue(is_teal(body_colour(teal)), body_colour(teal))
        self.assertTrue(is_ember(body_colour(ember)), body_colour(ember))

    def test_the_hand_drawn_texture_survives(self) -> None:
        """A gradient map, not a flat fill: the stripes are still there."""
        from knight_flow.overlay import pill_feedback_frame

        source = self.artwork()
        for kind in ("captured", "error"):
            with self.subTest(look=kind):
                frame = np.asarray(pill_feedback_frame(source, kind, 1.0).convert("L"), dtype=np.float32)
                body = frame[5:-5, 10:-10]
                self.assertGreater(float(body.std()), 12.0, "the look flattened the artwork into a sticker")

    def test_nothing_changes_at_zero_or_for_other_states(self) -> None:
        from knight_flow.overlay import pill_feedback_frame

        source = self.artwork()
        self.assertIs(pill_feedback_frame(source, "captured", 0.0), source)
        self.assertIs(pill_feedback_frame(source, "listening", 1.0), source)


class ThePillShowsItTests(unittest.TestCase):
    """The real Overlay: what it draws, and the message it raises."""

    def overlay(self, *, reduce_motion: bool = True, theme: str = "Flow Dark"):
        from knight_flow.overlay import Overlay

        previous = getattr(self, "_overlay", None)
        if previous is not None:
            previous.root.destroy()
        forget_default_root()
        config = copy.deepcopy(DEFAULT_CONFIG)
        config.setdefault("ui", {})["scale"] = 1.5
        config["ui"]["reduce_motion"] = reduce_motion
        config["ui"]["settings_theme"] = theme
        overlay = Overlay(config, callbacks={})
        self._overlay = overlay
        pump(overlay.root, 0.4)
        return overlay

    def tearDown(self) -> None:
        overlay = getattr(self, "_overlay", None)
        self._overlay = None
        if overlay is not None:
            try:
                overlay.root.destroy()
            except Exception:
                pass
        forget_default_root()

    def drawn(self, overlay) -> Image.Image:
        """The exact image the Pill hands to Tk for its next frame."""
        import knight_flow.overlay as module

        real = module.ImageTk.PhotoImage
        seen: list[Image.Image] = []

        def spy(image=None, *args, **kwargs):
            seen.append(image)
            return real(image, *args, **kwargs)

        overlay.idle_photo_cache.clear()
        overlay.idle_render_cache.clear()
        with mock.patch.object(module.ImageTk, "PhotoImage", side_effect=spy):
            overlay._draw_visual()
        self.assertTrue(seen, "the Pill drew nothing")
        return seen[-1]

    def test_idle_is_the_plain_artwork(self) -> None:
        overlay = self.overlay()
        colour = body_colour(self.drawn(overlay))
        self.assertFalse(is_teal(colour), colour)
        self.assertFalse(is_ember(colour), colour)

    def test_a_result_settles_in_teal_then_returns_to_idle(self) -> None:
        overlay = self.overlay()
        overlay.set_state("captured", "Pasted.", "")
        pump(overlay.root, 0.1)
        self.assertTrue(is_teal(body_colour(self.drawn(overlay))), "a finished take still looks idle")
        pump(overlay.root, 0.6)
        colour = body_colour(self.drawn(overlay))
        self.assertFalse(is_teal(colour), f"the teal did not settle back to idle: {colour}")

    def test_an_error_glows_ember_until_the_next_take(self) -> None:
        overlay = self.overlay()
        overlay.set_state("error", "No sound is reaching the microphone.", "Check the input device.")
        pump(overlay.root, 0.2)
        self.assertTrue(is_ember(body_colour(self.drawn(overlay))), "an error still looks idle")
        overlay.set_state("starting", "Starting microphone.", "")
        pump(overlay.root, 0.1)
        self.assertFalse(is_ember(body_colour(self.drawn(overlay))), "the ember outlived the next take")

    def test_the_error_look_ends_by_itself(self) -> None:
        overlay = self.overlay(reduce_motion=False)
        overlay.set_state("error", "No sound is reaching the microphone.", "Check the input device.")
        pump(overlay.root, 0.3)
        self.assertGreater(overlay._state_feedback_strength(), 0.5)
        overlay._feedback_started_at -= 3.2   # as if three seconds had passed
        self.assertEqual(overlay._state_feedback_strength(), 0.0)
        self.assertFalse(is_ember(body_colour(self.drawn(overlay))))

    def test_listening_and_processing_are_untouched(self) -> None:
        overlay = self.overlay()
        for state in ("listening", "processing", "idle"):
            with self.subTest(state=state):
                overlay.set_state(state, "", "")
                pump(overlay.root, 0.1)
                self.assertEqual(overlay._state_feedback_strength(), 0.0)

    def test_an_error_says_what_happened_and_what_to_do(self) -> None:
        overlay = self.overlay()
        overlay.set_state(
            "error",
            "No sound is reaching the microphone.",
            "Check the input device, or open Mic Doctor in Settings.",
        )
        pump(overlay.root, 0.2)
        toast = overlay._toast_window
        self.assertIsNotNone(toast, "an error raised no message at all")
        texts = [child.cget("text") for child in _walk(toast) if child.winfo_class() == "Label"]
        self.assertIn("No sound is reaching the microphone.", texts)
        self.assertIn("Check the input device, or open Mic Doctor in Settings.", texts)
        self.assertGreaterEqual(int(getattr(toast, "_talkdat_toast_hold_ms", 0)), 4000)

    def test_a_hidden_pill_raises_no_error_box(self) -> None:
        overlay = self.overlay()
        overlay.root.withdraw()
        pump(overlay.root, 0.1)
        overlay.set_state("error", "No sound is reaching the microphone.", "Check the input device.")
        pump(overlay.root, 0.2)
        self.assertIsNone(overlay._toast_window)

    def test_the_toast_follows_the_theme(self) -> None:
        for theme in ("Flow Light", "Flow Dark"):
            with self.subTest(theme=theme):
                overlay = self.overlay(theme=theme)
                palette = overlay._settings_palette(theme)
                overlay.show_toast("Talk DAT! is up to date")
                pump(overlay.root, 0.2)
                toast = overlay._toast_window
                self.assertIsNotNone(toast)
                labels = [child for child in _walk(toast) if child.winfo_class() == "Label"]
                self.assertTrue(labels)
                self.assertEqual(labels[0].cget("bg").lower(), palette["surface"].lower())
                self.assertEqual(labels[0].cget("fg").lower(), palette["text"].lower())


def _walk(widget):
    yield widget
    for child in widget.winfo_children():
        yield from _walk(child)


if __name__ == "__main__":
    unittest.main()
