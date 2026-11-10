"""The Pill menu's submenus open beside their row, where Windows 11 puts them (the owner's order of 2026-11-05).

WinUI's MenuFlyoutSubItem opens its submenu in a popup of its own, beside the parent, which stays open
(FLUENT-MENUS-SPEC.md B6, from CascadingMenuHelper.cpp): its left edge sits 4 px inside the row's right edge and its
top on the row's top; with no room on the right it mirrors to the left with the same 4 px overlap, and with no room
on either side it is right-aligned to the screen; with no room below it opens upward, its bottom on the row's bottom,
and with no room for that either its top is the screen's top. It is never larger than the screen. Bounds are
physical pixels, so the 4 px overlap scales with the display.
"""
from __future__ import annotations

import unittest

from knight_flow.web_shell.menu_geometry import submenu_bounds

WORK = (0, 0, 1920, 1040)  # left, top, right, bottom
ROW = (1000, 600, 296, 32)  # x, y, width, height of the row that opens the submenu


class TheSubmenuOpensBesideItsRow(unittest.TestCase):
    def test_room_to_the_right_and_below(self):
        self.assertEqual(submenu_bounds(ROW, (240, 120), WORK), [1000 + 296 - 4, 600, 240, 120])

    def test_no_room_on_the_right_mirrors_to_the_left(self):
        row = (1700, 600, 200, 32)
        self.assertEqual(submenu_bounds(row, (240, 120), WORK), [1700 - 240 + 4, 600, 240, 120])

    def test_no_room_on_either_side_right_aligns_to_the_screen(self):
        work = (0, 0, 500, 1040)
        row = (100, 600, 300, 32)
        self.assertEqual(submenu_bounds(row, (240, 120), work), [500 - 240, 600, 240, 120])

    def test_no_room_below_opens_upward_from_the_rows_bottom(self):
        row = (100, 980, 296, 32)
        self.assertEqual(submenu_bounds(row, (240, 160), WORK), [100 + 296 - 4, 980 + 32 - 160, 240, 160])

    def test_no_room_above_or_below_starts_at_the_screens_top(self):
        work = (0, 0, 1920, 300)
        row = (100, 100, 296, 32)
        self.assertEqual(submenu_bounds(row, (240, 280), work), [100 + 296 - 4, 0, 240, 280])

    def test_the_overlap_scales_with_the_display(self):
        self.assertEqual(submenu_bounds(ROW, (360, 180), WORK, 1.5)[0], 1000 + 296 - 6)
        row = (1700, 600, 200, 48)
        self.assertEqual(submenu_bounds(row, (360, 180), WORK, 1.5)[0], 1700 - 360 + 6)

    def test_a_monitor_left_of_the_main_one(self):
        work = (-1920, 0, 0, 1040)
        row = (-400, 300, 296, 32)
        self.assertEqual(submenu_bounds(row, (240, 120), work), [-400 - 240 + 4, 300, 240, 120])

    def test_a_submenu_taller_than_the_screen_is_cut_to_it(self):
        work = (0, 0, 1920, 400)
        self.assertEqual(submenu_bounds((100, 100, 296, 32), (240, 900), work), [100 + 296 - 4, 0, 240, 400])


if __name__ == "__main__":
    unittest.main()
