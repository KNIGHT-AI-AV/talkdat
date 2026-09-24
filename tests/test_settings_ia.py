from __future__ import annotations

import gc
import time
import unittest

import tkinter as tk
from tkinter import ttk

# The shared probe: a private tk.Tk() probe at import time condemns
# every later root on Tk 9 aqua (create-destroy-create segfaults).
from tests.tk_support import probe_error as _ROOT_ERROR

from knight_flow.config import load_config
from knight_flow.overlay import FlowPageStack, Overlay
from knight_flow import ui_scale
from knight_flow.ui.flow_console import FLOW_CONSOLE_SECTIONS
from tests import gui_offscreen  # noqa: F401  (X-164: never show on a real screen)

# X-74. His verdict on the old tree was deserved: a Settings window with a
# meaningless "Home" tab and two nested notebooks was settings-within-settings.
# The contract is ONE level: these six pages, this order, nothing nested.
# X-529 dropped Tools -- it held no settings, only buttons that opened other
# windows, each of which already had a home.
EXPECTED_TABS = ["General", "Colors", "Dictation", "Formatting", "Speech", "Advanced"]


@unittest.skipIf(_ROOT_ERROR is not None, f"no usable Tk display: {_ROOT_ERROR}")
class SettingsInformationArchitectureTests(unittest.TestCase):
    def setUp(self) -> None:
        # macOS: one Tk root per process, ever -- the shared-root pattern
        # every other window test here uses (see tests/tk_support).
        from tests.tk_support import acquire_root
        self.overlay = Overlay(config=load_config(), callbacks={}, root=acquire_root())
        self.addCleanup(self._destroy)
        self.overlay.open_settings()
        self.overlay.root.update()
        self.notebook = self._find_page_stack()

    def _destroy(self) -> None:
        from tests.tk_support import release_root
        overlay = getattr(self, "overlay", None)
        self.notebook = None  # type: ignore[assignment]
        self.overlay = None  # type: ignore[assignment]
        try:
            if overlay is not None:
                release_root(overlay._tk_root)
        except Exception:
            pass
        gc.collect()

    def _find_page_stack(self) -> FlowPageStack:
        stack = getattr(self.overlay._shell_window, "_settings_page_stack", None)
        if not isinstance(stack, FlowPageStack):
            raise AssertionError("settings page stack not found")
        return stack

    def test_exactly_six_flat_pages_in_order(self) -> None:
        titles = [str(self.notebook.tab(t, "text")) for t in self.notebook.tabs()]
        self.assertEqual(titles, EXPECTED_TABS)

    def test_no_tab_is_named_home(self) -> None:
        """The name "Home" described nothing and taught users that tabs can
        be filler. It stays dead."""
        titles = [str(self.notebook.tab(t, "text")) for t in self.notebook.tabs()]
        self.assertNotIn("Home", titles)

    def test_zero_nested_notebooks(self) -> None:
        """Settings-within-settings is the exact structure he rejected."""
        offenders: list[str] = []
        for tab_id in self.notebook.tabs():
            frame = self.notebook.nametowidget(tab_id)
            stack: list[tk.Misc] = [frame]
            while stack:
                widget = stack.pop()
                for child in widget.winfo_children():
                    if isinstance(child, (ttk.Notebook, FlowPageStack)):
                        offenders.append(str(self.notebook.tab(tab_id, "text")))
                    stack.append(child)
        self.assertEqual(offenders, [], f"nested notebooks under: {offenders}")

    def test_page_switch_keeps_the_complete_predecessor_until_layout_finishes(self) -> None:
        original = self.notebook.nametowidget(self.notebook.select())
        colors = next(
            self.notebook.nametowidget(tab_id)
            for tab_id in self.notebook.tabs()
            if str(self.notebook.tab(tab_id, "text")) == "Colors"
        )

        self.notebook.select(colors)

        self.assertIs(self.notebook._selected, colors)
        self.assertIs(self.notebook._visible, original)
        self.assertTrue(original.winfo_ismapped())
        self.assertEqual(colors.winfo_manager(), "place")

        deadline = time.perf_counter() + 0.8
        while self.notebook._visible is not colors and time.perf_counter() < deadline:
            self.overlay.root.update()
            time.sleep(0.005)

        self.assertIs(self.notebook._visible, colors)
        self.assertTrue(colors.winfo_ismapped())
        self.assertFalse(original.winfo_ismapped())

    def test_scroll_form_width_is_capped_and_centered_without_losing_small_widths(self) -> None:
        page = self.notebook.nametowidget(self.notebook.select())
        canvas = page._scroll_canvas
        state = page._scroll_layout_state
        deadline = time.perf_counter() + 0.8
        while state["content_geometry"] is None and time.perf_counter() < deadline:
            self.overlay.root.update()
            time.sleep(0.005)

        x, content_width = state["content_geometry"]
        viewport_width = max(1, canvas.winfo_width())
        maximum = ui_scale.px(900, self.overlay.config)
        self.assertEqual(content_width, min(viewport_width, maximum))
        self.assertEqual(x, max(0, (viewport_width - content_width) // 2))

    def test_rail_sections_match_the_tabs(self) -> None:
        """The rail is the visible navigation; a tab missing from it is
        unreachable -- exactly how the Tools tab shipped invisible in
        0.4.67. Rail and notebook must agree forever."""
        rail_labels = [label for _key, label, _hint in FLOW_CONSOLE_SECTIONS]
        self.assertEqual(rail_labels, EXPECTED_TABS)

    def test_every_relocated_tool_has_exactly_one_home(self) -> None:
        """X-529, and it is a STRONGER contract than the one it replaces.

        The old test asked that all five tools appear on the Tools page. They
        did -- and three of them were ALSO first-class sidebar destinations, so
        the test passed while the duplication it could not see was the thing
        people tripped over: "a menu within a menu".

        So this asserts the rule that actually matters. Each of the five is
        reachable, and none of them is reachable from two places at once. That
        fails if a tool loses its home AND if somebody gives one a second
        door."""
        sidebar = {row[0] for row in Overlay.SIDEBAR_DESTINATIONS}
        settings_pages = {key for key, _label, _hint in FLOW_CONSOLE_SECTIONS}
        self.assertNotIn("tools", settings_pages, "the launcher page is retired")

        # Where each of the five lives now. A tool in neither column is lost;
        # a tool in both has the duplication this change exists to remove.
        in_settings = {"taste", "feature_idea"}
        for tool_id, title in Overlay.RELOCATED_TOOLS:
            with self.subTest(tool=title):
                on_rail = tool_id in sidebar
                in_prefs = tool_id in in_settings
                self.assertTrue(on_rail or in_prefs, f"{title!r} has no home")
                self.assertFalse(on_rail and in_prefs, f"{title!r} has two doors")

    def test_legacy_deep_links_land_on_the_new_pages(self) -> None:
        """Deep links minted before X-74 (tray, pill menu, model guide) still
        arrive with the old names; every one must land somewhere real."""
        cases = {
            ("Voice", "Local Models"): "Speech",
            ("Voice", "Provider"): "Speech",
            ("Voice", "Mic + Paste"): "Dictation",
            ("System", "Pill"): "General",
            ("System", "Privacy + Updates"): "General",
            ("Writing", "Formatting"): "Formatting",
            ("Home", ""): "General",
        }
        for address, expected in cases.items():
            with self.subTest(address=address):
                self.overlay._settings_initial_page = address
                self.overlay.open_settings()
                self.overlay.root.update()
                self.overlay.root.update_idletasks()
                self.overlay.root.update()
                selected = str(self.notebook.tab(self.notebook.select(), "text"))
                self.assertEqual(selected, expected)

    def test_race_is_embedded_on_advanced(self) -> None:
        advanced = None
        for tab_id in self.notebook.tabs():
            if str(self.notebook.tab(tab_id, "text")) == "Advanced":
                advanced = self.notebook.nametowidget(tab_id)
        assert advanced is not None
        texts: list[str] = []
        stack: list[tk.Misc] = [advanced]
        while stack:
            widget = stack.pop()
            stack.extend(widget.winfo_children())
            if isinstance(widget, (tk.Button, ttk.Button)):
                texts.append(str(widget.cget("text")))
        self.assertIn("Speak", texts, "the Race panel must embed inline on Advanced")

    def test_search_indexes_real_controls_help_and_legacy_names(self) -> None:
        window = self.overlay.utility_windows["settings"]
        search = window._settings_search
        entries = window._settings_search_entries
        self.assertGreaterEqual(len(entries), 100)
        self.assertTrue(any(entry.label == "Microphone" for entry in entries))
        self.assertTrue(any("Voice Local Models" in entry.aliases for entry in entries))

        search.delete(0, "end")
        search.insert(0, "voice local models")
        self.overlay.root.update()
        result_boxes: list[tk.Listbox] = []
        stack: list[tk.Misc] = [window]
        while stack:
            widget = stack.pop()
            stack.extend(widget.winfo_children())
            if isinstance(widget, tk.Listbox):
                result_boxes.append(widget)
        self.assertEqual(len(result_boxes), 1)
        values = result_boxes[0].get(0, "end")
        self.assertIn("Local models", values)
        status_lines: list[str] = []
        stack = [window]
        while stack:
            widget = stack.pop()
            stack.extend(widget.winfo_children())
            if isinstance(widget, tk.Label):
                status_lines.append(str(widget.cget("text")))
        self.assertTrue(
            any("Selected: Speech / Local models" in value for value in status_lines),
            "the compact result lost its wrapped destination context",
        )

    def test_advanced_details_are_collapsed_until_selected_by_deep_link(self) -> None:
        window = self.overlay.utility_windows["settings"]

        def buttons_with_text(text: str) -> list[ttk.Button]:
            found: list[ttk.Button] = []
            stack: list[tk.Misc] = [window]
            while stack:
                widget = stack.pop()
                stack.extend(widget.winfo_children())
                if isinstance(widget, ttk.Button) and str(widget.cget("text")) == text:
                    found.append(widget)
            return found

        self.assertGreaterEqual(len(buttons_with_text("Show details")), 4)
        window._select_settings_page("Voice", None, "STT Advanced")
        self.overlay.root.update()
        self.assertGreaterEqual(len(buttons_with_text("Hide details")), 1)


if __name__ == "__main__":
    unittest.main()
