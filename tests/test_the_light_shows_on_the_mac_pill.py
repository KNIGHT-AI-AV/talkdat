"""The Pill's update light on macOS (2026-10-11, Mac 0.4.171 parity, option (i)).

The light is painted in _layered_frame, which is the Windows UpdateLayeredWindow
presenter. The Mac Pill is a NativePill (an NSWindow) that takes its frames through
set_image. The plain-Pill hand-offs, _draw_compact_reference_visual and
_blit_pill_image, never painted the light, so a Mac Pill never showed it (0.4.170 had
the same gap). The shared 0.4.171 notes say the light rises out of the Pill, so on the
Mac it must.

Message frames already carry the light: _flag_frame paints it at the lengthened Pill's
end, and _flag_paint_keyed hands that frame over. That hand-off must NOT paint it again.

The first class runs everywhere. The last one drives a real Pill and runs only in the
Mac native suite.
"""
from __future__ import annotations

import copy
from pathlib import Path
import re
import sys
import unittest

from PIL import Image

from knight_flow.config import DEFAULT_CONFIG
from knight_flow.overlay import Overlay

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "knight_flow" / "overlay.py").read_text(encoding="utf-8")


class FakeNativePill:
    available = True

    def __init__(self) -> None:
        self.images: list[Image.Image] = []

    def set_image(self, image: Image.Image) -> None:
        self.images.append(image)


def bare_overlay(flag: str = "green") -> Overlay:
    overlay = object.__new__(Overlay)
    overlay.config = copy.deepcopy(DEFAULT_CONFIG)
    overlay.config.setdefault("ui", {})["scale"] = 1.5
    overlay._update_flag = flag
    overlay._pip_since = None  # settled: the resting light
    overlay._pip_leaving = None
    overlay._motion_is_reduced = lambda: False
    return overlay


def method_body(name: str) -> str:
    match = re.search(rf"\n    def {name}\(.*?(?=\n    def |\nclass |\Z)", SOURCE, re.S)
    return match.group(0) if match else ""


def opaque_frame() -> Image.Image:
    return Image.new("RGBA", (180, 60), (30, 34, 40, 255))


class TheLightOnTheMacPill(unittest.TestCase):
    def test_the_native_frame_carries_the_light_painted_as_on_windows(self) -> None:
        overlay, image = bare_overlay(), opaque_frame()
        before = image.tobytes()
        handed = overlay._native_frame_with_light(image)
        reference = image.copy()
        overlay._paint_update_dot(reference)
        self.assertEqual(image.tobytes(), before, "the input, maybe a cached frame, was painted on")
        self.assertNotEqual(handed.tobytes(), before, "no light on the frame the Mac Pill is given")
        self.assertEqual(handed.tobytes(), reference.tobytes())

    def test_no_light_hands_the_frame_through_untouched(self) -> None:
        overlay, image = bare_overlay(flag=""), opaque_frame()
        self.assertEqual(overlay._native_frame_with_light(image).tobytes(), image.tobytes())

    def test_a_light_set_at_rest_reaches_the_mac_pill_at_once(self) -> None:
        from knight_flow import pill_message

        overlay, pill = bare_overlay(flag=""), FakeNativePill()
        overlay.native_pill = pill
        overlay._native_frame_with_light(opaque_frame())  # the last frame the Mac Pill was given
        # The entrance starts invisible (pip_look at 0 ms), so whether its first frame shows depended on
        # how many microseconds passed (green on Windows, red on the Mac, 2026-10-11). The light is read
        # as settled here; the entrance's own frames come from the draw loop.
        overlay._pip_look = lambda now=None: ("red", pill_message.PIP_REST)
        before = len(pill.images)
        overlay.set_update_flag("red")
        self.assertGreater(len(pill.images), before, "the Mac Pill was not given the new light at rest")
        self.assertNotEqual(pill.images[-1].tobytes(), opaque_frame().tobytes())

    def test_both_plain_pill_hand_offs_paint_the_light(self) -> None:
        for name in ("_blit_pill_image", "_draw_compact_reference_visual"):
            with self.subTest(method=name):
                body = method_body(name)
                self.assertIn(".set_image(", body)  # the hand-off is in this method
                self.assertNotRegex(body, r"\.set_image\((?!self\._native_frame_with_light\()")

    def test_the_message_hand_off_does_not_paint_it_twice(self) -> None:
        body = method_body("_flag_paint_keyed")
        self.assertIn("pill.set_image(frame)", body)
        self.assertNotIn("_native_frame_with_light", body)
        self.assertIn("paint_pip", method_body("_flag_frame"))


@unittest.skipUnless(sys.platform == "darwin", "the NativePill exists on macOS only")
class TheLightOnARealMacPill(unittest.TestCase):
    """The Mac qualification must show this class RAN, not skipped: in the Aqua
    session the NativePill is available."""

    def setUp(self) -> None:
        from tests.pill_harness import build_overlay

        self.overlay = build_overlay()

    def tearDown(self) -> None:
        from tests.pill_harness import destroy_overlay

        destroy_overlay(getattr(self, "overlay", None))

    def test_the_light_rises_on_the_mac_pill_and_sinks_back(self) -> None:
        from tests.pill_harness import pump

        pill = self.overlay.native_pill
        self.assertTrue(getattr(pill, "available", False), "no NativePill in the Aqua session")
        seen: list[Image.Image] = []
        original = pill.set_image
        pill.set_image = lambda image: (seen.append(image), original(image))[-1]
        self.overlay.set_update_flag("green")
        pump(self.overlay.root, 0.8)  # entrance 320 ms, then settled
        self.assertTrue(seen, "nothing reached the Mac Pill")
        source = self.overlay._native_pill_source
        lit = source.convert("RGBA") if source.mode != "RGBA" else source.copy()
        self.overlay._paint_update_dot(lit)
        self.assertEqual(seen[-1].tobytes(), lit.tobytes(), "the Mac Pill does not show the settled light")
        self.overlay.set_update_flag("")
        pump(self.overlay.root, 0.8)  # exit 180 ms, then gone
        self.assertEqual(seen[-1].tobytes(), self.overlay._native_pill_source.tobytes(),
                         "the light did not sink back on the Mac Pill")


if __name__ == "__main__":
    unittest.main()
