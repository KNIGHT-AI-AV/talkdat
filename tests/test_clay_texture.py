from __future__ import annotations

import unittest

from knight_flow.clay import (
    CLAY_OPACITY,
    clay_pixel,
    clay_tile_rgb,
    mottle,
    texture_tile_size,
)


class OpacityTests(unittest.TestCase):
    """Utility windows must be opaque.

    They were drawn at -alpha 0.965. Tk applies alpha to the whole window, so
    3.5% of whatever sits behind was compositing straight through the panel --
    and over a bright saturated curve on a near-black panel that is plainly
    visible. It read as unexplained coloured lines drawn across the text.

    Texture is painted instead, which gives the tactile look without letting the
    desktop bleed through anything anyone has to read.
    """

    def test_panels_are_fully_opaque(self) -> None:
        self.assertEqual(CLAY_OPACITY, 1.0)


class MottleTests(unittest.TestCase):
    """The plaster variation itself: small, smooth, and deterministic."""

    def test_it_is_deterministic_for_a_position(self) -> None:
        """A tile redrawn on resize must not shimmer."""
        self.assertEqual(mottle(12, 30, seed=7), mottle(12, 30, seed=7))

    def test_different_positions_differ(self) -> None:
        values = {mottle(x, y, seed=3) for x in range(0, 40, 7) for y in range(0, 40, 7)}
        self.assertGreater(len(values), 1, "a flat field is not a texture")

    def test_variation_stays_subtle(self) -> None:
        """Plaster, not noise. Anything stronger fights the text above it."""
        for x in range(0, 64, 3):
            for y in range(0, 64, 3):
                self.assertGreaterEqual(mottle(x, y, seed=1), -1.0)
                self.assertLessEqual(mottle(x, y, seed=1), 1.0)

    def test_the_seed_changes_the_pattern(self) -> None:
        a = [mottle(x, 5, seed=1) for x in range(20)]
        b = [mottle(x, 5, seed=99) for x in range(20)]
        self.assertNotEqual(a, b)


class ClayPixelTests(unittest.TestCase):
    def test_it_stays_close_to_the_theme_colour(self) -> None:
        """The panel must still read as the selected theme, not as beige."""
        base = (24, 21, 19)
        for x in range(0, 48, 5):
            for y in range(0, 48, 5):
                r, g, b = clay_pixel(base, x, y, seed=2)
                for channel, source in zip((r, g, b), base):
                    self.assertLessEqual(abs(channel - source), 14, f"{(x, y)} drifted too far")

    def test_channels_stay_in_range(self) -> None:
        for base in ((0, 0, 0), (255, 255, 255), (250, 3, 128)):
            for x in range(0, 32, 4):
                r, g, b = clay_pixel(base, x, y=x, seed=5)
                for channel in (r, g, b):
                    self.assertGreaterEqual(channel, 0)
                    self.assertLessEqual(channel, 255)

    def test_a_black_panel_does_not_go_negative(self) -> None:
        for x in range(0, 32, 3):
            self.assertTrue(all(c >= 0 for c in clay_pixel((0, 0, 0), x, 4, seed=1)))

    def test_a_white_panel_does_not_overflow(self) -> None:
        for x in range(0, 32, 3):
            self.assertTrue(all(c <= 255 for c in clay_pixel((255, 255, 255), x, 4, seed=1)))


class TileSizeTests(unittest.TestCase):
    def test_the_tile_is_big_enough_to_hide_repetition(self) -> None:
        self.assertGreaterEqual(texture_tile_size(), 96)

    def test_the_tile_is_small_enough_to_stay_cheap(self) -> None:
        """It is generated per theme change; a huge tile would stall the UI."""
        self.assertLessEqual(texture_tile_size(), 512)


class VectorTileTests(unittest.TestCase):
    def test_vector_tile_matches_the_scalar_reference(self) -> None:
        """The performance path may not change a single sampled paint value."""

        size = texture_tile_size()
        for base, seed in (((13, 28, 32), 11), ((247, 244, 235), 3)):
            with self.subTest(base=base, seed=seed):
                tile = clay_tile_rgb(base, seed=seed)
                self.assertEqual(tile.shape, (size, size, 3))
                for y in range(0, size, 17):
                    for x in range(0, size, 13):
                        self.assertEqual(
                            tuple(int(channel) for channel in tile[y, x]),
                            clay_pixel(base, x, y, seed=seed),
                        )


if __name__ == "__main__":
    unittest.main()
