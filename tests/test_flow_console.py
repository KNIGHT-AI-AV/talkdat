from __future__ import annotations

import unittest
import inspect

from knight_flow.config import LOCAL_FORMATTER_MODEL
from knight_flow.overlay import (
    LOCAL_FORMATTER_PROFILES,
    SETTINGS_THEME_FAMILIES,
    SETTINGS_THEME_PALETTES,
)
from knight_flow.ui.flow_console import (
    FLOW_CONSOLE_SECTIONS,
    FlowNavigationRail,
    context_menu_height,
    flow_console_material,
    navigation_layout,
    navigation_step,
)


class FlowConsoleTests(unittest.TestCase):
    def test_primary_navigation_has_exactly_six_flat_sections(self) -> None:
        """X-74 made it one flat level. X-529 removed the seventh.

        Tools carried no settings: it was five buttons that opened other
        windows, and every one already had a home elsewhere. A preferences
        window is the wrong place for a launcher, and the second door is what
        made this read as a menu inside a menu."""
        self.assertEqual(
            [section[0] for section in FLOW_CONSOLE_SECTIONS],
            ["general", "colors", "dictation", "formatting", "speech", "advanced"],
        )

    def test_context_menu_height_contains_every_row_without_excess_gap(self) -> None:
        # X-51 density: 12px top + 12px bottom.
        self.assertEqual(context_menu_height(0), 24)
        self.assertEqual(context_menu_height(1), 64)
        self.assertEqual(context_menu_height(6), 284)
        self.assertEqual(context_menu_height(7), 328)
        self.assertEqual(context_menu_height(9), 416)

    def test_generated_material_is_crop_safe(self) -> None:
        layer = flow_console_material(374, 336, opacity=68)
        self.assertEqual(layer.size, (374, 336))
        self.assertEqual(layer.mode, "RGBA")

    def test_keyboard_navigation_wraps_across_primary_sections(self) -> None:
        keys = [section[0] for section in FLOW_CONSOLE_SECTIONS]
        self.assertEqual(navigation_step(keys, "general", -1), "advanced")
        self.assertEqual(navigation_step(keys, "advanced", 1), "general")
        self.assertEqual(navigation_step(keys, "dictation", 1), "formatting")

    def test_primary_navigation_rows_are_native_buttons(self) -> None:
        source = inspect.getsource(FlowNavigationRail)
        self.assertIn("button = tk.Button(", source)
        self.assertIn('takefocus=1', source)
        self.assertIn('button.bind("<Return>"', source)
        self.assertIn('button.bind("<space>"', source)
        self.assertNotIn("row = tk.Frame(\n                self,\n                height", source)

    def test_navigation_layout_expands_for_scaled_windows_fonts(self) -> None:
        normal = navigation_layout(
            requested_width=188,
            max_text_width=136,
            label_linespace=18,
            description_linespace=13,
        )
        scaled = navigation_layout(
            requested_width=188,
            max_text_width=214,
            label_linespace=27,
            description_linespace=20,
        )
        self.assertEqual(normal.width, 188)
        self.assertEqual(normal.row_height, 64)
        self.assertGreater(scaled.width, normal.width)
        self.assertGreater(scaled.row_height, normal.row_height)
        self.assertLess(scaled.description_wraplength, scaled.width)

    def test_navigation_layout_scales_its_non_text_metrics_too(self) -> None:
        normal = navigation_layout(
            requested_width=188,
            max_text_width=136,
            label_linespace=18,
            description_linespace=13,
        )
        high_dpi = navigation_layout(
            requested_width=188,
            max_text_width=272,
            label_linespace=36,
            description_linespace=26,
            scale=2.0,
        )
        self.assertEqual(high_dpi.width, normal.width * 2)
        self.assertEqual(high_dpi.row_height, normal.row_height * 2)
        self.assertEqual(high_dpi.description_wraplength, normal.description_wraplength * 2)

    def test_formatter_profiles_are_unique_and_keep_realtime_as_default(self) -> None:
        labels = [label for label, _model, _budget in LOCAL_FORMATTER_PROFILES]
        models = [model for _label, model, _budget in LOCAL_FORMATTER_PROFILES]
        budgets = [budget for _label, _model, budget in LOCAL_FORMATTER_PROFILES]
        self.assertEqual(len(labels), len(set(labels)))
        self.assertEqual(len(models), len(set(models)))
        self.assertEqual(models[0], LOCAL_FORMATTER_MODEL)
        self.assertEqual(budgets, sorted(budgets))
        self.assertTrue(all(100 <= budget <= 30_000 for budget in budgets))

    def test_every_settings_theme_has_complete_dark_and_light_palettes(self) -> None:
        self.assertGreaterEqual(len(SETTINGS_THEME_FAMILIES), 15)
        self.assertEqual(set(SETTINGS_THEME_FAMILIES), set(SETTINGS_THEME_PALETTES))
        for family in SETTINGS_THEME_FAMILIES:
            self.assertEqual(set(SETTINGS_THEME_PALETTES[family]), {"Dark", "Light"})


if __name__ == "__main__":
    unittest.main()
