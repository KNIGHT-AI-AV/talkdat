"""X-640: the gray standby Pill keeps its own soft edge, and drains in 90 ms.

Polish audit P0-2 (2026-09-24), found by reading rather than on screen: every
press paints the X-137 receipt, the compact Pill drained to gray, through
`_standby_gray_frame`. That function did `image.convert("RGB")`, which throws
the alpha away. The frame's clear surround is (0, 0, 0, 0), NOT the colour key,
so it became opaque black; the "repaint the key" step compared against
#010203 and matched nothing; and the capsule region clipped the result into a
near-black ring 2 to 3 px wide around the gray Pill, for the whole standby
moment, on every press.

What is pinned here:

* the gray frame carries the input's alpha exactly (so a transparent pixel of
  the colour Pill is a transparent pixel of the gray one);
* at full level the body is neutral gray, and the blend at half level sits
  between colour and gray without touching alpha;
* the drain is a colour change, not motion (X-137 forbids motion): it starts
  at 0.5 on the first frame so the receipt is still instant, reaches 1.0 by
  90 ms, is 1.0 at once under reduced motion, and starts again from colour on
  the next press.

The GUI half builds a real Overlay and runs through
scripts/run_tests_offscreen.py, so nothing appears on anyone's screen.
"""
from __future__ import annotations

import copy
import time
import unittest

import numpy as np
from PIL import Image, ImageDraw

from knight_flow.config import DEFAULT_CONFIG
from knight_flow.pill_motion import STANDBY_FADE_MS, standby_gray_level
from tests import gui_offscreen  # noqa: F401  (X-164: never on a human's screen)


def soft_pill(width: int = 96, height: int = 28) -> Image.Image:
    """A colourful capsule with a supersampled (partly transparent) edge."""
    scale = 4
    mask = Image.new("L", (width * scale, height * scale), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (2 * scale, 2 * scale, (width - 2) * scale - 1, (height - 2) * scale - 1),
        radius=(height - 4) * scale // 2,
        fill=255,
    )
    mask = mask.resize((width, height), Image.Resampling.LANCZOS)
    colour = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    ramp = np.zeros((height, width, 4), np.uint8)
    ramp[..., 0] = np.linspace(255, 40, width, dtype=np.uint8)[None, :]
    ramp[..., 1] = 90
    ramp[..., 2] = np.linspace(40, 230, width, dtype=np.uint8)[None, :]
    ramp[..., 3] = np.asarray(mask)
    colour = Image.fromarray(ramp, "RGBA")
    return colour


def gray_frame(image: Image.Image, level: float = 1.0) -> Image.Image:
    from knight_flow.overlay import Overlay

    # The method uses nothing on self but the module logger.
    return Overlay._standby_gray_frame(object(), image, level)


class TheDrainIsAColourChangeNotMotionTests(unittest.TestCase):
    def test_the_first_frame_is_already_half_way(self) -> None:
        self.assertAlmostEqual(standby_gray_level(0.0), 0.5)

    def test_it_is_fully_gray_by_ninety_ms(self) -> None:
        self.assertEqual(STANDBY_FADE_MS, 90)
        self.assertEqual(standby_gray_level(90.0), 1.0)
        self.assertEqual(standby_gray_level(5_000.0), 1.0)

    def test_it_only_ever_moves_toward_gray(self) -> None:
        levels = [standby_gray_level(float(ms)) for ms in range(0, 100, 5)]
        self.assertEqual(levels, sorted(levels))
        self.assertTrue(all(0.5 <= level <= 1.0 for level in levels))

    def test_reduced_motion_is_gray_at_once(self) -> None:
        self.assertEqual(standby_gray_level(0.0, reduced_motion=True), 1.0)


class TheGrayFrameKeepsItsAlphaTests(unittest.TestCase):
    def test_alpha_is_carried_through_exactly(self) -> None:
        source = soft_pill()
        for level in (0.5, 0.75, 1.0):
            with self.subTest(level=level):
                gray = gray_frame(source, level)
                self.assertEqual(gray.mode, "RGBA")
                np.testing.assert_array_equal(
                    np.asarray(gray.getchannel("A")), np.asarray(source.getchannel("A"))
                )

    def test_the_old_ring_is_gone(self) -> None:
        """Every pixel that was clear in the colour Pill is clear in the gray one.

        Before X-640 these came back as opaque (0, 0, 0): the ring."""
        source = soft_pill()
        gray = np.asarray(gray_frame(source, 1.0))
        clear = np.asarray(source.getchannel("A")) == 0
        self.assertGreater(int(clear.sum()), 100, "the fixture has no clear surround")
        self.assertEqual(int((gray[..., 3][clear] > 0).sum()), 0)

    def test_the_edge_stays_soft(self) -> None:
        source = soft_pill()
        alpha = np.asarray(gray_frame(source, 1.0).getchannel("A"))
        partial = (alpha > 0) & (alpha < 255)
        self.assertGreater(int(partial.sum()), 40, "the gray Pill lost its anti-aliased edge")

    def test_full_level_is_neutral_gray_and_half_level_sits_between(self) -> None:
        source = soft_pill()
        full = np.asarray(gray_frame(source, 1.0)).astype(int)
        half = np.asarray(gray_frame(source, 0.5)).astype(int)
        colour = np.asarray(source).astype(int)
        body = colour[..., 3] == 255
        self.assertTrue(np.all(full[..., 0][body] == full[..., 1][body]))
        self.assertTrue(np.all(full[..., 1][body] == full[..., 2][body]))
        # Red: colour is high on the left, gray lower; half level between them.
        left = body.copy()
        left[:, colour.shape[1] // 3:] = False
        self.assertTrue(np.all(half[..., 0][left] <= colour[..., 0][left]))
        self.assertTrue(np.all(half[..., 0][left] >= full[..., 0][left] - 1))

    def test_a_frame_without_alpha_is_still_accepted(self) -> None:
        gray = gray_frame(Image.new("RGB", (20, 10), (200, 30, 30)), 1.0)
        self.assertEqual(gray.mode, "RGBA")
        self.assertEqual(gray.getpixel((5, 5))[3], 255)


def forget_default_root() -> None:
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


class TheRealPillDrainsOnEveryPressTests(unittest.TestCase):
    """The real Overlay's draw path: what level it asks for, what it gets back."""

    def setUp(self) -> None:
        from knight_flow.overlay import Overlay
        from tests.tk_support import acquire_root

        forget_default_root()
        config = copy.deepcopy(DEFAULT_CONFIG)
        config.setdefault("ui", {})["reduce_motion"] = False
        # macOS: one Tk root per process, ever (tests/tk_support). A fresh
        # tk.Tk() here landed this Overlay's images in a dead interpreter
        # left by an earlier test ("image pyimageNN does not exist").
        self.overlay = Overlay(config, callbacks={}, root=acquire_root())
        pump(self.overlay.root, 0.4)
        self.calls: list[tuple[float, Image.Image, Image.Image]] = []
        real = self.overlay._standby_gray_frame

        def spy(image, level=1.0):
            result = real(image, level)
            self.calls.append((float(level), image, result))
            return result

        self.overlay._standby_gray_frame = spy  # type: ignore[method-assign]

    def tearDown(self) -> None:
        from tests.tk_support import release_root

        release_root(self.overlay._tk_root)
        forget_default_root()

    def press(self) -> None:
        # calls[0] is then the very first standby frame, whether the live
        # animation tick or the explicit draw below painted it.
        self.calls.clear()
        self.overlay.set_state("starting", "Starting microphone.", "")
        pump(self.overlay.root, 0.02)
        self.overlay._draw_visual()

    def test_the_first_standby_frame_is_half_gray_and_keeps_alpha(self) -> None:
        self.press()
        self.assertTrue(self.calls, "standby drew no gray frame")
        level, source, result = self.calls[0]
        self.assertAlmostEqual(level, 0.5, places=1)
        np.testing.assert_array_equal(
            np.asarray(result.getchannel("A")), np.asarray(source.convert("RGBA").getchannel("A"))
        )
        corner = np.asarray(result.getchannel("A"))[0, 0]
        self.assertEqual(int(corner), 0, "the gray Pill's corner is painted")

    def test_it_settles_to_full_gray_and_starts_over_on_the_next_press(self) -> None:
        self.press()
        time.sleep(0.12)
        self.overlay._draw_visual()
        self.assertEqual(self.calls[-1][0], 1.0)
        self.overlay.set_state("idle", "", "")
        pump(self.overlay.root, 0.1)
        self.overlay._draw_visual()
        self.assertIsNone(getattr(self.overlay, "_standby_started_at", None))
        self.press()
        self.assertTrue(self.calls)
        self.assertAlmostEqual(
            self.calls[0][0], 0.5, places=1, msg="the second press did not drain from colour again"
        )


if __name__ == "__main__":
    unittest.main()
