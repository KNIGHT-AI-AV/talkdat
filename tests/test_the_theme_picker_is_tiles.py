"""X-458: the Colors tab is a grid of material tiles, not fifty bars.

His verdict (2026-09-04): "These are UGLY for color bars... we NEED a
redesign. do some research!!!!" The pattern every serious theme picker
uses (macOS Appearance, Slack Themes, Windows Personalization, the iOS
wallpaper picker): a thumbnail of the REAL UI per choice, in a grid, the
name under the thumbnail and never over it, a selection ring, and
light/dark as one control rather than a doubled list.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from knight_flow.themes import SETTINGS_THEME_FAMILIES, SETTINGS_THEME_GROUPS

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = (ROOT / "knight_flow" / "overlay.py").read_text(encoding="utf-8")


def block(pattern: str) -> str:
    found = re.search(pattern, OVERLAY, re.S)
    assert found, "anchor moved: " + pattern
    return found.group(0)


class EveryFamilyHasOneGroupTests(unittest.TestCase):
    def test_the_groups_tile_the_families_exactly_once_in_order(self) -> None:
        listed = [family for _group, members in SETTINGS_THEME_GROUPS for family in members]
        self.assertEqual(listed, list(SETTINGS_THEME_FAMILIES))

    def test_no_group_is_wider_than_the_grid(self) -> None:
        for group, members in SETTINGS_THEME_GROUPS:
            self.assertLessEqual(len(members), 5, group)


class TheTilesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.draw = block(r"def draw_gallery\(\*_args: object\) -> None:.*?gallery_state\[\"rects\"\] = rects")

    def test_one_tile_per_family_in_a_grid(self) -> None:
        self.assertIn("gallery_cols = 5", OVERLAY)
        self.assertIn("for group, members in SETTINGS_THEME_GROUPS:", self.draw)
        self.assertIn("tile_h = int(tile_w * 0.62)", self.draw)
        # The doubled list is gone: options are per family, in the current mode.
        self.assertNotIn("gallery_row_h * len(gallery_options)", OVERLAY)
        self.assertIn('gallery_options[:] = [f"{family} {mode}" for family in gallery_families]', self.draw)

    def test_the_tile_is_the_app_in_that_material(self) -> None:
        tile = block(r"def material_tile_photo.*?material_photo_cache\[key\] = photo")
        for token in ('fill=pal["panel"]', 'fill=pal["text"]', 'fill=pal["muted"]', 'fill=pal["accent"]', 'fill=pal["bg"]'):
            self.assertIn(token, tile, token)
        self.assertIn("rounded_rectangle", tile)

    def test_the_name_lives_under_the_tile_in_the_pages_ink(self) -> None:
        self.assertIn("text=family, anchor=\"nw\"", self.draw)
        self.assertIn("ty + tile_h + pad_y, text=family", self.draw)
        # Never the chip-on-photograph of X-337/X-352.
        self.assertNotIn("gallery_name_font.measure(option) + chip_pad_x", OVERLAY)

    def test_the_chosen_tile_wears_the_ring_and_the_check(self) -> None:
        self.assertIn('outline=pal["accent"], width=3', self.draw)
        self.assertIn('text="\\u2713", fill=pal["bg"]', self.draw)
        self.assertIn('text="current"', self.draw)

    def test_light_and_dark_are_one_control(self) -> None:
        self.assertIn('gallery_modes = ("Dark", "Light")', OVERLAY)
        self.assertIn("for option in gallery_modes:", self.draw)
        click = block(r"def gallery_click\(event: tk\.Event\) -> str:.*?return \"break\"\n")
        self.assertIn('theme_var.set(f"{gallery_family()} {mode}")', click,
                      "the control re-applies the current family in the other mode")

    def test_arrows_walk_the_grid(self) -> None:
        for binding in ('gallery.bind("<Left>"', 'gallery.bind("<Right>"',
                        'gallery.bind("<Up>", lambda _e: gallery_move_focus(-gallery_cols))',
                        'gallery.bind("<Down>", lambda _e: gallery_move_focus(gallery_cols))'):
            self.assertIn(binding, OVERLAY, binding)
        self.assertIn("def gallery_index_at(x: int, y: int) -> int:", OVERLAY)

    def test_the_canvas_grows_to_its_content(self) -> None:
        self.assertIn("gallery.configure(height=total)", self.draw + OVERLAY[OVERLAY.index(self.draw) + len(self.draw):][:600])


if __name__ == "__main__":
    unittest.main()
