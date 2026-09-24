"""The cached spectrum scroll must be the OLD scroll, faster.

The per-frame LANCZOS rescale + retile in scrolling_spectrum_frame measured
~21ms of every processing frame -- the visible "rainbow lags out when I let
go" hitch. The rewrite caches the scaled strip and its panorama and crops
per frame; this holds it pixel-for-pixel to the original construction.
"""
from __future__ import annotations

import unittest

from PIL import Image

from knight_flow.overlay import scrolling_spectrum_frame


def reference_frame(source, width, height, offset_px):
    """The original per-frame construction, verbatim from pre-cache overlay.py."""
    target_width = max(1, int(width))
    target_height = max(1, int(height))
    strip = source.convert("RGBA")
    if strip.height != target_height:
        scaled_width = max(1, round(strip.width * target_height / max(1, strip.height)))
        strip = strip.resize((scaled_width, target_height), Image.Resampling.LANCZOS)
    period = max(1, strip.width)
    offset = int(offset_px) % period
    tiled = Image.new("RGBA", (target_width + period * 2, target_height), (0, 0, 0, 0))
    for x in range(-offset, tiled.width, period):
        tiled.alpha_composite(strip, (x, 0))
    return tiled.crop((0, 0, target_width, target_height))


def rainbow_strip(width=48, height=16) -> Image.Image:
    strip = Image.new("RGBA", (width, height))
    for x in range(width):
        for y in range(height):
            strip.putpixel((x, y), (int(x * 255 / width), int(y * 255 / height), (x * 7 + y * 3) % 256, 255))
    return strip


class SpectrumScrollEquivalenceTests(unittest.TestCase):
    def test_every_offset_matches_the_original(self) -> None:
        source = rainbow_strip()
        for offset in (0, 1, 7, 47, 48, 49, 500):
            with self.subTest(offset=offset):
                fast = scrolling_spectrum_frame(source, 120, 32, offset)
                slow = reference_frame(source, 120, 32, offset)
                self.assertEqual(fast.tobytes(), slow.tobytes())

    def test_size_changes_mid_scroll_stay_correct(self) -> None:
        """The pill expands while the rainbow plays; a stale cache entry for
        the old size must not serve the new one."""
        source = rainbow_strip()
        first = scrolling_spectrum_frame(source, 90, 24, 5)
        second = scrolling_spectrum_frame(source, 140, 30, 5)
        self.assertEqual(first.size, (90, 24))
        self.assertEqual(second.size, (140, 30))
        self.assertEqual(second.tobytes(), reference_frame(source, 140, 30, 5).tobytes())

    def test_the_cache_actually_caches(self) -> None:
        source = rainbow_strip()
        scrolling_spectrum_frame(source, 120, 32, 0)
        cache = getattr(source, "_talkdat_spectrum_cache", None)
        self.assertTrue(cache, "the panorama should be remembered on the source art")
        panorama_before = cache[(120, 32)][1]
        scrolling_spectrum_frame(source, 120, 32, 9)
        self.assertIs(cache[(120, 32)][1], panorama_before, "a second frame must reuse, not rebuild")


if __name__ == "__main__":
    unittest.main()
