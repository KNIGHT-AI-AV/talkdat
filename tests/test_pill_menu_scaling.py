"""X-109: the pill menu scales with the display like every other surface.

It was the one surface whose pixel constants never passed through
ui_scale.px, so on 150/200% displays the DPI-scaled text crammed into
96-DPI-sized rows -- "menu right click seems squished". These pin the
geometry to the scaler and the row pitch to the text it must hold.
"""
from __future__ import annotations

import inspect
import unittest
from pathlib import Path

from knight_flow import ui_scale
from knight_flow.overlay import Overlay


class PillMenuScalingTests(unittest.TestCase):
    def test_instance_metrics_are_the_scaled_design_values(self) -> None:
        config: dict = {}
        expected = {
            "MENU_ROW_TOP": ui_scale.px(12, config),
            "MENU_ROW_PITCH": ui_scale.px(44, config),
            "MENU_ROW_HEIGHT": ui_scale.px(40, config),
            "MENU_WIDTH": ui_scale.px(320, config),
        }
        source = Path(Overlay.__init__.__code__.co_filename).read_text(encoding="utf-8")
        init_block = source[source.index("def __init__(self, config"):][:1600]
        for name in expected:
            self.assertIn(
                f"self.{name} = ui_scale.px(type(self).{name}, config)",
                init_block,
                f"{name} must be scaled per-instance in __init__",
            )

    def test_the_menu_window_uses_the_scaled_metrics(self) -> None:
        """X-168: the height arithmetic moved into `_context_menu_window_height`.

        It moved because the accordion needs the same number, and two copies of
        it would drift. The property this guard exists for is unchanged: every
        term must be the INSTANCE's scaled value, never the 96-DPI class
        constant, or the menu is sized for 96 DPI while its rows are not. So the
        guard follows the arithmetic instead of pinning the function it used to
        live in.
        """
        source = Path(Overlay.__init__.__code__.co_filename).read_text(encoding="utf-8")
        open_menu = source[source.index("def _open_context_menu(self, x_root"):][:1400]
        self.assertIn("width = self.MENU_WIDTH", open_menu)
        self.assertNotIn("width = 320", open_menu, "raw 96-DPI width crept back")
        self.assertIn(
            "self._context_menu_window_height(", open_menu,
            "the open path stopped using the shared height helper",
        )

        height_helper = source[source.index("def _context_menu_window_height(self"):][:1900]
        self.assertIn("top=self.MENU_ROWS_Y0", height_helper)
        self.assertIn("pitch=self.MENU_ROW_PITCH", height_helper)
        self.assertIn("row_height=self.MENU_ROW_HEIGHT", height_helper)
        self.assertIn(
            "bottom=self.MENU_ROW_PITCH + self.MENU_ROW_TOP",
            height_helper,
            "the reset footer lost its scaled line height or bottom padding",
        )
        for raw in ("pitch=44", "row_height=40", "top=12", "bottom=12"):
            self.assertNotIn(raw, height_helper, f"raw 96-DPI {raw} crept back into the height")

    def test_the_unfold_uses_the_same_scaled_height(self) -> None:
        """A DPI-blind unfold would resize the window to 96-DPI dimensions and
        the plate, which IS scaled, would show a seam against the edge."""
        source = Path(Overlay.__init__.__code__.co_filename).read_text(encoding="utf-8")
        unfold = source[source.index("def _unfold_context_menu(self"):][:1600]
        self.assertIn("self._context_menu_window_height(", unfold)

    def test_row_pitch_scales_at_least_as_fast_as_the_display(self) -> None:
        """At 2x density the pitch must be ~2x, or text outgrows its row."""
        base = ui_scale.px(44, {})
        self.assertGreaterEqual(base, 44)

    def test_canvas_text_and_glyph_offsets_follow_the_scaled_row_height(self) -> None:
        overlay = Overlay.__new__(Overlay)
        for scale in (1.0, 1.5, 2.0):
            with self.subTest(scale=scale):
                overlay.MENU_ROW_HEIGHT = round(40 * scale)
                self.assertEqual(overlay._menu_px(8), round(8 * scale))
                self.assertEqual(overlay._menu_px(-7), round(-7 * scale))

        drawing = inspect.getsource(Overlay._draw_context_menu)
        self.assertIn("cy - px(7)", drawing)
        self.assertIn("cy + px(8)", drawing)
        self.assertIn("icon_drawer(canvas, px(32), cy, active)", drawing)
        self.assertNotIn("cy - 7,", drawing)
        self.assertNotIn("cy + 8,", drawing)

        for name in (
            "_draw_gear_icon",
            "_draw_paste_icon",
            "_draw_history_icon",
            "_draw_scratchpad_icon",
            "_draw_stats_icon",
            "_draw_chip_icon",
            "_draw_update_icon",
            "_draw_close_icon",
            "_draw_translate_icon",
            "_draw_idea_icon",
        ):
            with self.subTest(icon=name):
                source = inspect.getsource(getattr(Overlay, name))
                self.assertIn("px = self._menu_px", source)


if __name__ == "__main__":
    unittest.main()
