"""Real Tk control metrics for one isolated DPI scale.

Launched in a fresh interpreter because Tk font and style state is process
global.  The parent test runs this module once per supported scale.
"""

from __future__ import annotations

import os
import unittest
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

from PIL import Image

from tests import gui_offscreen  # noqa: F401

from knight_flow import ui_scale
from knight_flow.overlay import Overlay


class AppTextScalingRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scale = float(os.environ["TALKDAT_TEST_UI_SCALE"])
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.tk.call("tk", "scaling", 96.0 * self.scale / 72.0)
        self.overlay = Overlay.__new__(Overlay)
        self.overlay.root = self.root
        self.overlay.config = {"ui": {"scale": self.scale}}

    def tearDown(self) -> None:
        self.root.destroy()

    def _padding(self, style: ttk.Style, name: str) -> tuple[int, ...]:
        return tuple(int(float(value)) for value in self.root.tk.splitlist(style.lookup(name, "padding")))

    def test_controls_keep_scaled_breathing_room_in_both_core_themes(self) -> None:
        for theme in ("Flow Dark", "Flow Light"):
            with self.subTest(theme=theme):
                palette = self.overlay._settings_palette(theme)
                self.overlay._style_settings_widgets(self.root, palette)
                style = ttk.Style(self.root)
                expected_control_padding = (
                    ui_scale.px(12, self.overlay.config),
                    ui_scale.px(8, self.overlay.config),
                )
                self.assertEqual(self._padding(style, "Flow.TButton"), expected_control_padding)
                self.assertEqual(self._padding(style, "Flow.TEntry"), expected_control_padding)
                self.assertEqual(self._padding(style, "Flow.TCombobox"), expected_control_padding)
                self.assertEqual(
                    int(float(style.lookup("Flow.TCombobox", "arrowsize"))),
                    ui_scale.px(16, self.overlay.config),
                )
                self.assertEqual(
                    style.lookup("Flow.TButton", "foreground", ("disabled",)),
                    palette["disabled_text"],
                )
                self.assertEqual(
                    style.lookup("Flow.TEntry", "foreground", ("disabled",)),
                    palette["disabled_text"],
                )
                self.assertEqual(
                    int(float(style.lookup("Flow.TButton", "borderwidth"))),
                    ui_scale.px(2, self.overlay.config),
                )
                self.assertEqual(
                    int(float(style.lookup("Flow.TButton", "focusthickness"))),
                    ui_scale.px(2, self.overlay.config),
                )
                self.assertEqual(
                    style.lookup("Flow.TButton", "bordercolor", ("focus",)),
                    palette["text"],
                )
                self.assertEqual(
                    style.lookup(
                        "Flow.TButton",
                        "bordercolor",
                        ("disabled", "focus"),
                    ),
                    palette["stroke"],
                )
                self.assertEqual(
                    style.lookup(
                        "Flow.Accent.TButton",
                        "focuscolor",
                        ("pressed", "focus"),
                    ),
                    palette["on_accent2"],
                )
                self.assertEqual(
                    style.lookup(
                        "Flow.Danger.TButton",
                        "focuscolor",
                        ("focus",),
                    ),
                    palette["on_danger"],
                )
                self.assertEqual(
                    style.lookup(
                        "Flow.TCombobox",
                        "fieldbackground",
                        ("disabled", "readonly", "focus"),
                    ),
                    palette["panel"],
                )
                self.assertEqual(
                    style.lookup(
                        "Flow.TCombobox",
                        "bordercolor",
                        ("readonly", "focus"),
                    ),
                    palette["text"],
                )

                button = ttk.Button(self.root, text="Save settings", style="Flow.TButton")
                entry = ttk.Entry(self.root, style="Flow.TEntry")
                combo = ttk.Combobox(self.root, values=("System default",), style="Flow.TCombobox")
                check = ttk.Checkbutton(self.root, text="Keep formatting", style="Flow.TCheckbutton")
                for widget in (button, entry, combo, check):
                    widget.pack()
                self.root.update_idletasks()

                entry_font = tkfont.Font(root=self.root, font=entry.cget("font"))
                minimum_field_height = entry_font.metrics("linespace") + 2 * expected_control_padding[1]
                self.assertGreaterEqual(entry.winfo_reqheight(), minimum_field_height)
                self.assertGreaterEqual(combo.winfo_reqheight(), minimum_field_height)
                self.assertGreater(button.winfo_reqheight(), entry_font.metrics("linespace"))

                resting_size = (button.winfo_reqwidth(), button.winfo_reqheight())
                button.state(["focus"])
                self.root.update_idletasks()
                self.assertEqual(
                    (button.winfo_reqwidth(), button.winfo_reqheight()),
                    resting_size,
                    "reserved focus rings must never shift button geometry",
                )

                indicator_sizes = {
                    image.width()
                    for key, images in self.overlay._checkbox_images.items()
                    if key[-1] == ui_scale.px(16, self.overlay.config)
                    for image in images
                }
                self.assertEqual(indicator_sizes, {ui_scale.px(16, self.overlay.config)})

                for widget in (button, entry, combo, check):
                    widget.destroy()

    def test_plain_multiline_fields_get_scaled_focus_and_inner_padding(self) -> None:
        palette = self.overlay._settings_palette("Flow Dark")
        self.overlay._style_settings_widgets(self.root, palette)
        field = tk.Text(self.root, width=32, height=4)
        field.pack()
        self.root.update_idletasks()
        self.assertEqual(int(field.cget("highlightthickness")), ui_scale.px(2, self.overlay.config))
        self.assertEqual(int(field.cget("padx")), ui_scale.px(12, self.overlay.config))
        self.assertEqual(int(field.cget("pady")), ui_scale.px(8, self.overlay.config))
        self.assertEqual(str(field.cget("highlightcolor")), palette["accent"])

    def test_settings_header_text_stays_inside_and_separate(self) -> None:
        palette = self.overlay._settings_palette("Flow Dark")
        self.overlay.settings_header_photos = {}
        self.overlay._compact_wave_frame = (
            lambda width, height, active=True: Image.new("RGBA", (width, height), palette["accent"])
        )
        width = ui_scale.px(1180, self.overlay.config)
        height = ui_scale.px(96, self.overlay.config)
        canvas = tk.Canvas(self.root, width=width, height=height)
        canvas.pack()
        self.root.update_idletasks()
        self.overlay._draw_settings_header(
            canvas,
            width,
            height,
            "Flow Dark",
            show_close=False,
        )
        title = next(
            item for item in canvas.find_all()
            if canvas.type(item) == "text" and canvas.itemcget(item, "text") == "Talk DAT!"
        )
        # The subtitle used to end "- local private config"; that phrase was
        # internal vocabulary and is gone. The test is about geometry, not
        # wording, so it now finds the subtitle by the theme name the line
        # still carries.
        subtitle = next(
            item for item in canvas.find_all()
            if canvas.type(item) == "text" and "Flow Dark" in canvas.itemcget(item, "text")
        )
        title_box = canvas.bbox(title)
        subtitle_box = canvas.bbox(subtitle)
        self.assertIsNotNone(title_box)
        self.assertIsNotNone(subtitle_box)
        assert title_box is not None and subtitle_box is not None
        self.assertGreaterEqual(title_box[1], 0)
        self.assertLessEqual(subtitle_box[3], height)
        self.assertLess(title_box[3], subtitle_box[1])


if __name__ == "__main__":
    unittest.main()
