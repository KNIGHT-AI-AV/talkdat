from __future__ import annotations

import ast
from pathlib import Path
import unittest

# Every control below is pinned as FlatButton: that IS tk.Button off macOS, so the
# native-button accessibility contract holds there, while on Aqua it is the
# styled Label mac-port uses because a native button paints its face white
# (tests/test_aqua_rendering.py). Keyboard focus and Enter/space activation are
# part of its API on both.


ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "knight_flow" / "overlay.py"


def overlay_source() -> str:
    return OVERLAY.read_text(encoding="utf-8")


def function_source(name: str) -> str:
    source = overlay_source()
    tree = ast.parse(source)
    matches = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
    ]
    if len(matches) != 1:
        raise AssertionError(f"expected exactly one {name!r}, found {len(matches)}")
    return ast.get_source_segment(source, matches[0]) or ""


class SharedUtilityCloseAccessibilityTests(unittest.TestCase):
    def test_close_is_a_real_focusable_button_with_enter_activation(self) -> None:
        block = function_source("_close_control")

        self.assertIn("glyph = FlatButton(", block)
        self.assertIn("takefocus=1", block)
        self.assertIn("width=ui_scale.px(44, self.config)", block)
        self.assertIn("height=ui_scale.px(32, self.config)", block)
        self.assertIn("glyph.configure(command=go)", block)
        self.assertIn('glyph.bind("<Return>", go', block)
        self.assertNotIn('widget.bind("<Button-1>", go', block)
        self.assertIn('activeforeground=palette.get("on_danger"', block)

    def test_settings_masthead_uses_the_shared_close_with_unsaved_guard(self) -> None:
        block = function_source("open_settings")
        start = block.index("def redraw_header(")
        end = block.index("key_var =", start)
        masthead = block[start:end]

        self.assertIn("settings_header_close = self._close_control(", masthead)
        self.assertIn("command=request_settings_close", masthead)
        self.assertGreaterEqual(masthead.count("show_close=False"), 2)
        self.assertNotIn("def header_click", masthead)
        self.assertNotIn('header.bind("<ButtonPress-1>"', masthead)


class ThemeControlAccessibilityTests(unittest.TestCase):
    def test_picker_rows_are_buttons_with_roving_keyboard_focus(self) -> None:
        block = function_source("_open_theme_picker")

        self.assertIn("button = FlatButton(", block)
        self.assertIn("takefocus=1", block)
        for key in ("<Return>", "<Up>", "<Down>", "<Home>", "<End>", "<Escape>"):
            with self.subTest(key=key):
                self.assertIn(key, block)
        self.assertIn("dismiss_if_focus_left", block)
        self.assertIn("winfo_toplevel() is not popup", block)
        self.assertIn('bg=picker_palette["panel"]', block)
        self.assertIn('button.bind("<MouseWheel>", wheel_picker', block)
        self.assertIn('swatch.bind("<MouseWheel>", wheel_picker', block)

    def test_settings_theme_gallery_keeps_keyboard_access(self) -> None:
        # History: fifty tk.Buttons until X-337; the material gallery is
        # ONE focusable canvas carrying the same keyboard grammar (arrows,
        # Return/space, a focus ring on FocusIn) and live apply through
        # theme_var. Equivalent semantics, two hundred fewer controls.
        block = function_source("open_settings")

        start = block.index("gallery = tk.Canvas(")
        end = block.index("def build_gallery()", start)
        colors = block[start:end]
        self.assertIn("takefocus=1", colors)
        self.assertIn('gallery.bind("<Up>"', colors)
        self.assertIn('gallery.bind("<Down>"', colors)
        self.assertIn('gallery.bind("<Return>"', colors)
        self.assertIn('gallery.bind("<space>"', colors)
        self.assertIn("theme_var.set(gallery_options[index])", colors)
        self.assertIn('gallery.bind("<FocusIn>"', colors)

    def test_settings_finish_switch_has_keyboard_equivalence(self) -> None:
        block = function_source("open_settings")
        start = block.index("finish_holder =")
        end = block.index("# X-145: repaint", start)
        finish = block[start:end]

        self.assertIn("button = tk.Radiobutton(", finish)
        self.assertIn("variable=finish_choice_var", finish)
        self.assertIn("indicatoron=False", finish)
        self.assertIn("command=lambda choice=key: pick_finish(choice)", finish)
        self.assertIn("takefocus=1", finish)
        for key in ("<Return>", "<Left>", "<Right>"):
            with self.subTest(key=key):
                self.assertIn(key, finish)


class GainKnobAccessibilityTests(unittest.TestCase):
    def test_knob_is_paired_with_a_native_log_scale(self) -> None:
        block = function_source("gain_meter_knob")

        self.assertIn("slider = ttk.Scale(", block)
        self.assertIn("takefocus=True", block)
        self.assertIn("command=set_from_slider", block)
        self.assertIn('style="Flow.Horizontal.TScale"', block)
        self.assertIn("math.log(value / low) / math.log(high / low)", block)
        self.assertIn("low * ((high / low) ** norm)", block)
        self.assertIn("takefocus=0", block)
        for key in ("<Left>", "<Down>", "<Right>", "<Up>", "<Prior>", "<Next>", "<Home>", "<End>"):
            with self.subTest(key=key):
                self.assertIn(f'slider.bind("{key}"', block)
        self.assertNotIn("canvas.focus_set()", block)

    def test_provider_route_lane_is_a_native_radio_group(self) -> None:
        block = function_source("open_settings")
        start = block.index("routing_lane = tk.Frame(")
        end = block.index("stt_provider_box =", start)
        routing = block[start:end]

        self.assertIn("button = tk.Radiobutton(", routing)
        self.assertIn("variable=provider_lane_var", routing)
        self.assertIn("indicatoron=False", routing)
        self.assertIn("takefocus=1", routing)
        self.assertIn("def select_provider_lane", routing)
        for key in ("<Left>", "<Up>", "<Right>", "<Down>", "<Home>", "<End>"):
            with self.subTest(key=key):
                self.assertIn(key, routing)
        self.assertNotIn("routing_canvas", routing)


class PopupActionAccessibilityTests(unittest.TestCase):
    def test_history_more_rows_are_buttons_and_do_not_close_during_internal_focus_moves(self) -> None:
        block = function_source("open_more_menu")

        self.assertIn("row = FlatButton(", block)
        self.assertIn("takefocus=1", block)
        self.assertIn('button.bind("<Up>"', block)
        self.assertIn('button.bind("<Down>"', block)
        self.assertIn("dismiss_more_if_focus_left", block)
        self.assertIn("winfo_toplevel() is not pop", block)

    def test_update_toast_uses_buttons_without_stealing_focus(self) -> None:
        block = function_source("show_update_popover")

        self.assertIn("update = FlatButton(", block)
        self.assertIn("close = FlatButton(", block)
        self.assertGreaterEqual(block.count("takefocus=1"), 2)
        self.assertIn('self.root.bind(\n                "<Alt-u>"', block)
        self.assertIn('self.root.unbind("<Alt-u>", update_binding)', block)
        self.assertNotIn("focus_force", block)
        self.assertIn('activeforeground=palette.get("on_danger"', block)

    def test_scratchpad_font_picker_is_searchable_and_keyboard_native(self) -> None:
        block = function_source("open_font_chooser")

        self.assertIn("listbox = tk.Listbox(", block)
        self.assertIn("search = ttk.Entry(", block)
        self.assertIn('listbox.bind("<Return>"', block)
        self.assertIn('listbox.bind("<Double-Button-1>"', block)
        self.assertIn("_talkdat_font_chooser", block)
        self.assertIn("dismiss_font_if_focus_left", block)

    def test_learned_word_undo_is_a_button_with_a_non_focus_stealing_accelerator(self) -> None:
        block = function_source("show_learned_word")

        self.assertIn("reject = FlatButton(", block)
        self.assertIn("takefocus=1", block)
        self.assertIn("reject.configure(command=strike_and_reject)", block)
        self.assertIn('self.root.bind(\n            "<Alt-d>"', block)
        self.assertIn('self.root.unbind("<Alt-d>", reject_binding)', block)


class BorderMicroControlAccessibilityTests(unittest.TestCase):
    def test_the_duplicate_titlebar_chrome_stays_gone(self) -> None:
        """X-538. Both controls were re-patched three times and still wrong.

        The theme brush and the "Something wrong?" chip were second doors into
        Settings, placed by absolute pixel guesses in a titlebar with no room
        for them -- X-92 moved them to the top right, X-401 anchored them to a
        handed-over action cluster, X-459 anchored the brush to the chip, and
        his screenshot still showed the chip underneath the Minimize button.

        Theme lives in Settings > Colors and feedback in Settings > General.
        Neither ever needed a copy in the chrome of fifteen surfaces, and this
        test exists so nobody adds a fourth placement guess instead of using
        the place the setting already lives.
        """

        tree = ast.parse(overlay_source())
        defined = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        for gone in ("_attach_theme_brush", "_attach_help_chip"):
            self.assertNotIn(gone, defined)

    def test_help_note_uses_semantic_text_and_monitor_clamping(self) -> None:
        block = function_source("_open_help_note")

        self.assertIn('fg=palette.get("text"', block)
        self.assertIn('fg=palette.get("success"', block)
        self.assertIn("self._window_monitor_work_area(window)", block)
        self.assertNotIn('box.configure(fg="#dbe3ea")', block)
        self.assertNotIn('box.configure(fg="#7ee2c3"', block)


class LiveCaptionsControlAccessibilityTests(unittest.TestCase):
    def test_all_caption_actions_are_real_buttons(self) -> None:
        block = function_source("toggle_captions")

        commands = {
            "start": "toggle_listen",
            "mode_button": "toggle_mode",
            "pager_button": "park_pager",
        }
        for name, command in commands.items():
            with self.subTest(name=name):
                self.assertIn(f"{name} = FlatButton(", block)
                self.assertIn(f"command={command}", block)
        self.assertGreaterEqual(block.count("takefocus=1"), 3)
        self.assertIn("close = FlatButton(", block)
        self.assertNotIn("self._close_control(", block)

    def test_start_is_truthfully_disabled_without_an_engine(self) -> None:
        block = function_source("toggle_captions")

        self.assertIn('state="normal" if callable(self.callbacks.get("captions_stream")) else "disabled"', block)
        self.assertNotIn('start.bind("<Button-1>", toggle_listen', block)

    def test_clear_mode_has_one_chrome_free_transparent_close_surface(self) -> None:
        block = function_source("toggle_captions")
        utility = function_source("_utility_window")

        self.assertIn("close_holder, close", block)
        self.assertIn("widget.configure(bg=surface)", block)
        self.assertNotIn('close_holder.configure(bg="#17181b")', block)
        self.assertNotIn("self._bind_edge_resize(window, 420, 96)", block)
        self.assertIn('if name == "captions":', utility)
        self.assertIn('name != "captions"', utility)


class ResponsiveTransientSurfaceTests(unittest.TestCase):
    def test_scratchpad_keeps_the_saved_font_after_paper_styling(self) -> None:
        block = function_source("open_scratchpad")
        # The saved family must survive the paper styling. The SIZE moved onto
        # the shared scale (X-536) -- 12 was already BODY, so this pins the
        # same size by the name that now owns it rather than by the number.
        self.assertIn("font=(scratch_font_family, type_scale.BODY)", block)
        self.assertNotIn('font=("Georgia", 12)', block)

    def test_ramble_indicator_scales_and_clamps_saved_positions(self) -> None:
        block = function_source("show_ramble_indicator")
        self.assertIn("ui_scale.px(232, self.config)", block)
        self.assertIn("list_monitors()", block)
        self.assertIn("self._window_monitor_work_area(bar)", block)

    def test_learned_word_receipt_measures_wraps_and_clamps(self) -> None:
        block = function_source("show_learned_word")
        self.assertIn("receipt_font.measure(label_text)", block)
        self.assertIn("width=max(1, canvas_width", block)
        self.assertIn("self._pill_monitor_work_area()", block)

    def test_long_toasts_wrap_to_the_pill_monitor(self) -> None:
        block = function_source("_show_toast_now")
        self.assertIn("wraplength=wraplength", block)
        self.assertIn("self._pill_monitor_work_area()", block)


class WorkspaceMicroControlAccessibilityTests(unittest.TestCase):
    def test_translation_hero_actions_are_real_truthfully_disabled_buttons(self) -> None:
        block = function_source("open_translation")

        self.assertIn("auto_button = FlatButton(", block)
        self.assertIn("speak_button = FlatButton(", block)
        self.assertIn("command=toggle_auto", block)
        self.assertIn("command=speak_toggle", block)
        self.assertIn('self.callbacks.get("translate_toggle")', block)
        self.assertIn('self.callbacks.get("push_to_talk")', block)
        self.assertNotIn('auto_button.bind("<Button-1>"', block)
        self.assertNotIn('speak_button.bind("<Button-1>"', block)

    def test_history_transcript_rows_are_focusable_copy_buttons(self) -> None:
        block = function_source("load_text")

        self.assertIn("label = FlatButton(", block)
        self.assertIn("command=lambda value=text_value: copy_value(value)", block)
        self.assertIn("takefocus=1", block)
        self.assertIn("reveal_history_label", function_source("open_history"))

    def test_pdf_template_cards_have_keyboard_activation_and_roving_focus(self) -> None:
        block = function_source("show_pdf_gallery")

        self.assertIn("card = FlatButton(", block)
        self.assertIn('compound="top"', block)
        self.assertIn('command=lambda choice=key: choose(f"pdf:{choice}")', block)
        self.assertIn("takefocus=1", block)
        self.assertIn('card.bind("<Return>"', block)
        self.assertIn('card.bind("<Left>"', block)
        self.assertIn('card.bind("<Right>"', block)
        self.assertIn("reveal_pdf_card", block)
        self.assertIn('text="Previous"', block)
        self.assertIn('text="Next"', block)
        self.assertNotIn("card = tk.Frame(", block)


class SettingsSearchLifecycleTests(unittest.TestCase):
    def test_escape_from_results_clears_the_query_and_stale_hits(self) -> None:
        block = function_source("open_settings")
        start = block.index('settings_search_results_box.bind(\n            "<Escape>"')
        end = block.index('settings_search_results_box.bind(\n            "<<ListboxSelect>>"', start)
        escape = block[start:end]

        self.assertIn('settings_search_var.set("")', escape)
        self.assertIn("settings_search_results_box.pack_forget()", escape)
        self.assertIn("settings_search_entry.focus_set()", escape)


class MicDoctorAsyncDisposalTests(unittest.TestCase):
    def test_native_fallback_uses_an_owned_check_and_never_opens_its_own_stream(self):
        block = function_source("open_mic_doctor")
        self.assertNotIn("open_raw_input_stream", block)
        self.assertIn("owned.stop()", block)
        self.assertIn("add_window_disposer", block)
        self.assertIn("InputDevices", block)


if __name__ == "__main__":
    unittest.main()
