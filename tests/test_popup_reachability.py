from __future__ import annotations

import ast
from pathlib import Path
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "knight_flow" / "overlay.py"


def function_source(name: str) -> str:
    source = OVERLAY.read_text(encoding="utf-8")
    tree = ast.parse(source)
    matches = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
    ]
    if len(matches) != 1:
        raise AssertionError(f"expected exactly one {name!r}, found {len(matches)}")
    return ast.get_source_segment(source, matches[0]) or ""


class SettingsTooltipReachabilitySourceTests(unittest.TestCase):
    def test_settings_tips_have_pointer_and_keyboard_parity(self) -> None:
        block = function_source("attach_tip")

        self.assertIn('widget.bind("<Enter>", enter', block)
        self.assertIn('widget.bind("<Leave>", leave', block)
        self.assertIn('widget.bind("<FocusIn>", focus_in', block)
        self.assertIn('widget.bind("<FocusOut>", focus_out', block)
        self.assertIn('widget.bind("<F1>", pin', block)
        self.assertIn('"tip_hovered": False', block)
        self.assertIn('"pinned": False', block)
        self.assertIn("schedule_tooltip_close(widget)", block)
        self.assertIn('"<Escape>"', block)

    def test_settings_tips_flip_and_clamp_to_the_window_monitor(self) -> None:
        block = function_source("attach_tip")

        self.assertIn("self._popup_work_area(window)", block)
        self.assertIn("metric = lambda value: ui_scale.px(value, self.config)", block)
        self.assertIn("content_width = max(1, width - 2 * pad_x)", block)
        self.assertIn("scrolling = desired_height > available_height", block)
        self.assertIn("above_y = widget.winfo_rooty() - height - gutter", block)
        self.assertIn(
            "x = max(left + gutter, min(x, right - width - gutter))",
            block,
        )
        self.assertIn(
            "y = max(top + gutter, min(y, bottom - height - gutter))",
            block,
        )
        self.assertIn("body_canvas.configure(yscrollcommand=scrollbar.set)", block)
        self.assertIn('"<End>"', block)


class PopupWorkAreaFallbackTests(unittest.TestCase):
    def test_missing_monitor_uses_the_validated_logical_work_area(self) -> None:
        from knight_flow.overlay import Overlay

        overlay = object.__new__(Overlay)
        overlay._window_monitor_work_area = mock.Mock(return_value=None)  # type: ignore[method-assign]
        overlay._logical_work_area = mock.Mock(  # type: ignore[method-assign]
            return_value=(-1280, 40, 0, 760)
        )
        window = mock.Mock()

        self.assertEqual(
            overlay._popup_work_area(window),  # type: ignore[arg-type]
            (-1280, 40, 0, 760),
        )

    def test_invalid_logical_bounds_fall_back_to_the_tk_screen(self) -> None:
        from knight_flow.overlay import Overlay

        overlay = object.__new__(Overlay)
        overlay.root = None
        overlay._window_monitor_work_area = mock.Mock(return_value=None)  # type: ignore[method-assign]
        overlay._logical_work_area = mock.Mock(return_value=(0, 0, 0, 0))  # type: ignore[method-assign]
        window = mock.Mock()
        window.winfo_screenwidth.return_value = 640
        window.winfo_screenheight.return_value = 480

        self.assertEqual(
            overlay._popup_work_area(window),  # type: ignore[arg-type]
            (0, 0, 640, 480),
        )


class ScratchpadReachabilitySourceTests(unittest.TestCase):
    def test_scratchpad_declares_a_real_resize_contract(self) -> None:
        block = function_source("open_scratchpad")

        self.assertIn('"Talk DAT! Scratchpad",', block)
        self.assertIn("resizable=True", block)
        # 760 was the floor measured against 10pt controls. The desktop type
        # scale grew the sidebar's Font/Delete pair and the footer's
        # Save/Close pair, and gui_popup_reachability caught Close landing
        # outside the window at the old width -- then 88px outside that 800
        # floor again on Aqua's wider button metrics. The contract this test
        # holds is that a real floor is declared and that the actions stay
        # inside it.
        self.assertIn("minimum_size=(920, 500)", block)

    def test_font_chooser_exposes_installed_fonts_in_a_scrollable_viewport(self) -> None:
        block = function_source("open_font_chooser")

        self.assertIn("tkfont.families(window)", block)
        self.assertIn("listbox = tk.Listbox(", block)
        self.assertIn("scrollbar = ttk.Scrollbar(", block)
        self.assertIn("yscrollcommand=scrollbar.set", block)
        self.assertIn("search_var.trace_add", block)
        for key in ("<Home>", "<End>", "<Return>", "<Double-Button-1>"):
            with self.subTest(key=key):
                self.assertIn(f'"{key}"', block)
        self.assertIn("listbox.see(target)", block)


if __name__ == "__main__":
    unittest.main()
