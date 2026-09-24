"""Real-Tk proofs for scaled universal chrome and live Text focus paint."""

from __future__ import annotations

import contextlib
import os
import tempfile
import time
import tkinter as tk
import unittest
from unittest import mock

from tests import gui_offscreen  # noqa: F401
from knight_flow import mac_support
from knight_flow.flat_button import FlatButton


def pump(root: tk.Misc, seconds: float = 0.2) -> None:
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        root.update()
        time.sleep(0.01)


def descendants(widget: tk.Misc) -> list[tk.Misc]:
    found: list[tk.Misc] = []
    stack = list(widget.winfo_children())
    while stack:
        child = stack.pop()
        found.append(child)
        stack.extend(child.winfo_children())
    return found


class ChromeScaleAndThemeRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.scale = float(os.environ["TALKDAT_TEST_UI_SCALE"])
        cls._previous_home = os.environ.get("TALK_DAT_HOME")
        cls._home = tempfile.TemporaryDirectory(prefix="talkdat-chrome-scale-")
        os.environ["TALK_DAT_HOME"] = cls._home.name

        from knight_flow.config import load_config
        from knight_flow.overlay import Overlay

        config = load_config()
        ui = config.setdefault("ui", {})
        ui["scale"] = cls.scale
        ui["reduce_motion"] = True
        ui["settings_theme"] = "Flow Dark"
        ui["theme"] = "dark"
        cls.overlay = Overlay(config, callbacks={})
        pump(cls.overlay.root, 0.2)

    @classmethod
    def tearDownClass(cls) -> None:
        with contextlib.suppress(Exception):
            cls.overlay.root.destroy()
        with contextlib.suppress(Exception):
            tk._default_root = None  # type: ignore[attr-defined]
        if cls._previous_home is None:
            os.environ.pop("TALK_DAT_HOME", None)
        else:
            os.environ["TALK_DAT_HOME"] = cls._previous_home
        cls._home.cleanup()

    def test_titlebar_brush_place_lanes_and_hover_note_share_one_scale(self) -> None:
        from knight_flow import ui_scale

        metric = lambda value: ui_scale.px(value, self.overlay.config)
        palette = self.overlay._settings_palette("Flow Dark")

        packed_host = tk.Toplevel(self.overlay.root)
        packed_host.configure(bg=palette["bg"])
        packed_host.geometry(f"{metric(900)}x{metric(240)}+120+120")
        packed_host.attributes("-alpha", 0.0)
        packed_host._talkdat_minimizable = False  # type: ignore[attr-defined]
        bar = self.overlay._make_glass_titlebar(
            packed_host,
            "Scale contract",
            palette["bg"],
            palette["text"],
        )
        self.assertIsNotNone(bar)
        pump(self.overlay.root, 0.08)

        close = next(
            widget
            for widget in descendants(packed_host)
            if isinstance(widget, (tk.Button, FlatButton)) and str(widget.cget("text")) == "Close window"
        )
        self.assertEqual(int(bar.cget("height")), metric(44))
        self.assertEqual(int(close.master.cget("width")), metric(44))
        self.assertEqual(int(close.master.cget("height")), metric(32))
        packed_host.destroy()
        pump(self.overlay.root, 0.04)


    def test_generated_resize_grip_scales_with_its_hit_target(self) -> None:
        from knight_flow import ui_scale

        metric = lambda value: ui_scale.px(value, self.overlay.config)
        palette = self.overlay._settings_palette("Flow Dark")
        host = tk.Toplevel(self.overlay.root)
        host.configure(bg=palette["bg"])
        host.geometry(f"{metric(520)}x{metric(320)}+120+120")
        self.overlay._install_utility_resize_grip(
            host,
            minimum_size=(metric(320), metric(220)),
            bg=palette["bg"],
        )
        pump(self.overlay.root, 0.08)
        grip = next(
            widget
            for widget in descendants(host)
            if isinstance(widget, tk.Canvas)
            and str(widget.cget("cursor")) == mac_support.RESIZE_CORNER_CURSOR
        )
        self.assertEqual(int(grip.cget("width")), metric(22))
        self.assertEqual(int(grip.cget("height")), metric(22))
        self.assertEqual(grip._talkdat_icon_photo.width(), metric(18))  # type: ignore[attr-defined]
        self.assertEqual(grip._talkdat_icon_photo.height(), metric(18))  # type: ignore[attr-defined]
        host.destroy()
        pump(self.overlay.root, 0.04)

    def test_live_dark_to_light_repaint_updates_plain_text_focus_border(self) -> None:
        from knight_flow import ui_scale

        dark = self.overlay._settings_palette("Flow Dark")
        light = self.overlay._settings_palette("Flow Light")
        self.overlay.config.setdefault("ui", {})["settings_theme"] = "Flow Dark"
        self.overlay.config["ui"]["theme"] = "dark"
        self.overlay.open_settings()
        pump(self.overlay.root, 0.85)
        window = self.overlay.utility_windows["settings"]
        fields = [
            widget
            for widget in descendants(window)
            if isinstance(widget, tk.Text)
            and str(widget.cget("bg")) == dark["field"]
            and int(widget.cget("highlightthickness")) > 0
        ]
        self.assertTrue(fields, "Settings exposes no multiline field with a focus border")
        field = fields[0]
        self.assertEqual(int(field.cget("highlightthickness")), ui_scale.px(2, self.overlay.config))
        self.assertEqual(str(field.cget("highlightbackground")), dark["stroke"])
        self.assertEqual(str(field.cget("highlightcolor")), dark["accent"])

        close = next(
            widget
            for widget in descendants(window)
            if isinstance(widget, (tk.Button, FlatButton))
            and str(widget.cget("text")) == "Close window"
        )
        dark_close_icon = str(close._talkdat_icon_photo)  # type: ignore[attr-defined]
        dark_checkbox_keys = set(self.overlay._checkbox_images)

        theme_var = next(
            variable
            for variable in window._settings_tracked_vars  # type: ignore[attr-defined]
            if str(variable.get()) == "Flow Dark"
        )
        theme_var.set("Flow Light")
        pump(self.overlay.root, 0.18)

        self.assertEqual(str(field.cget("bg")), light["field"])
        self.assertEqual(str(field.cget("fg")), light["text"])
        self.assertEqual(str(field.cget("highlightbackground")), light["stroke"])
        self.assertEqual(str(field.cget("highlightcolor")), light["accent"])
        self.assertNotEqual(
            str(close._talkdat_icon_photo),  # type: ignore[attr-defined]
            dark_close_icon,
        )
        self.assertTrue(set(self.overlay._checkbox_images) - dark_checkbox_keys)

        theme_var.set("Flow Dark")
        pump(self.overlay.root, 0.12)
        self.assertEqual(str(field.cget("highlightbackground")), dark["stroke"])
        self.assertEqual(str(field.cget("highlightcolor")), dark["accent"])


if __name__ == "__main__":
    unittest.main()
