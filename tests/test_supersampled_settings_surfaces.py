from __future__ import annotations

import inspect
import unittest

from knight_flow.overlay import Overlay, TRANSPARENT_COLOR


PALETTE = {
    "mode": "dark",
    "bg": "#071012",
    "panel": "#0d1c20",
    "field": "#12272c",
    "stroke": "#33505a",
    "accent": "#31d5ca",
    "warm": "#f0b24a",
}


def raster_overlay(scale: float = 1.0) -> Overlay:
    overlay = object.__new__(Overlay)
    overlay.config = {"ui": {"scale": scale}}
    overlay._settings_header_surface_cache = {}
    return overlay


class SupersampledSettingsSurfaceTests(unittest.TestCase):
    def test_header_uses_real_theme_background_and_cached_antialiased_layers(self) -> None:
        overlay = raster_overlay()
        plate, sheen = overlay._settings_header_layers(640, 96, PALETTE)
        plate_again, sheen_again = overlay._settings_header_layers(640, 96, PALETTE)

        self.assertIs(plate_again, plate)
        self.assertIs(sheen_again, sheen)
        self.assertEqual(plate.size, (640, 96))
        self.assertEqual(sheen.size, (640, 96))
        self.assertTrue(all(alpha == 255 for *_rgb, alpha in plate.getdata()))

        corner = plate.getpixel((0, 0))[:3]
        background = overlay._rgb(PALETTE["bg"])
        transparent_key = overlay._rgb(TRANSPARENT_COLOR)
        self.assertLessEqual(sum(abs(a - b) for a, b in zip(corner, background)), 6)
        self.assertNotEqual(corner, transparent_key)

        # A supersampled radius has intermediate edge colors rather than a
        # binary one-pixel jump from the background to the glass plate.
        diagonal = {plate.getpixel((offset, offset)) for offset in range(0, 28)}
        self.assertGreaterEqual(len(diagonal), 5)

    def test_meter_surface_is_smooth_bounded_and_has_a_distinct_hot_state(self) -> None:
        overlay = raster_overlay(scale=1.5)
        cold = overlay._settings_meter_surface(720, 64, 192, False, PALETTE)
        hot = overlay._settings_meter_surface(720, 64, 192, True, PALETTE)

        self.assertEqual(cold.size, (720, 64))
        self.assertEqual(hot.size, cold.size)
        self.assertEqual(cold.mode, "RGB")
        self.assertNotEqual(cold.tobytes(), hot.tobytes())
        self.assertGreater(len(set(cold.crop((10, 8, 48, 34)).getdata())), 5)

    def test_receipt_mark_is_a_supersampled_alpha_asset(self) -> None:
        overlay = raster_overlay(scale=1.25)
        mark = overlay._settings_receipt_icon_surface(70, 70, PALETTE)

        self.assertEqual(mark.size, (70, 70))
        self.assertEqual(mark.mode, "RGBA")
        alpha_values = {pixel[3] for pixel in mark.getdata()}
        self.assertIn(0, alpha_values)
        self.assertIn(255, alpha_values)
        self.assertTrue(any(0 < alpha < 255 for alpha in alpha_values))

    def test_live_meter_uses_bounded_raster_cache_not_tk_spline_polygons(self) -> None:
        source = inspect.getsource(Overlay.open_settings)
        meter_source = source[
            source.index("def draw_live_meter") : source.index(
                "def finish_live_meter_close"
            )
        ]
        self.assertIn("_settings_meter_surface", meter_source)
        self.assertIn("while len(cache) > 48", meter_source)
        self.assertNotIn("create_polygon", meter_source)
        self.assertNotIn("smooth=True", meter_source)


if __name__ == "__main__":
    unittest.main()
