from __future__ import annotations

import ast
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "knight_flow" / "overlay.py"


def method_source(name: str) -> str:
    source = OVERLAY.read_text(encoding="utf-8")
    tree = ast.parse(source)
    overlay = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "Overlay"
    )
    method = next(
        node for node in overlay.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    )
    return ast.get_source_segment(source, method) or ""


class PopupLifecycleSourceTests(unittest.TestCase):
    def test_theme_choice_closes_before_mutating_the_watched_variable(self) -> None:
        block = method_source("_open_theme_picker")
        pick = block[block.index("def pick(option:"):block.index("current = variable.get()")]
        self.assertIn("def apply_choice()", pick)
        self.assertIn("variable.set(option)", pick)
        self.assertIn("on_complete=apply_choice", pick)
        self.assertIn("getattr(self, \"_theme_picker\", None) is popup", block)

    def test_owned_transients_have_guarded_singleton_pointers(self) -> None:
        history = method_source("open_history")
        help_note = method_source("_open_help_note")
        self.assertIn("_history_more_popup", history)
        self.assertIn("getattr(window, \"_history_more_popup\", None) is pop", history)
        self.assertIn("_talkdat_help_note_popup", help_note)
        self.assertIn("getattr(window, \"_talkdat_help_note_popup\", None) is pop", help_note)
        self.assertIn("existing_state[\"context\"] = str(context)", help_note)

    def test_settings_receipt_uses_normalized_latest_wins_lifecycle(self) -> None:
        block = method_source("_show_settings_saved_overlay")
        settings = method_source("open_settings")
        self.assertIn("state[\"pending\"]", block)
        self.assertIn("_schedule_popup_present(saved", block)
        self.assertIn("_request_popup_close(owner)", block)
        self.assertIn("layout(str(message))", block)
        self.assertIn("_talkdat_saved_message_label", block)
        self.assertIn("_settings_receipt_icon_surface", block)
        self.assertIn("_talkdat_saved_icon_photo", block)
        self.assertIn("wraplength=content_width", block)
        self.assertIn("_talkdat_saved_palette", block)
        self.assertIn("def create_latest_safely()", block)
        self.assertNotIn("saved.after(1750, saved.destroy)", block)
        self.assertIn(
            "self._show_settings_saved_overlay(window, palette, message)",
            settings,
        )

    def test_caption_feature_toggle_uses_the_utility_close_path(self) -> None:
        block = method_source("toggle_captions")
        opening = block[:block.index("from .captions import CaptionBuffer")]
        self.assertIn("self._request_utility_close(existing)", opening)
        self.assertNotIn("existing.destroy()", opening)

    def test_menu_tooltips_share_the_guarded_motion_lifecycle(self) -> None:
        """X-538: the help chip was the second half of this and is gone.

        Its tooltip was one of four popups that each answered "when do I
        disappear" differently. The chip itself was a duplicate door into
        Settings living in every window's titlebar, so removing it removed a
        behaviour nobody could learn as well as a control nobody needed twice.
        """

        settings = method_source("open_settings")
        self.assertIn("_schedule_popup_present", settings)
        self.assertIn("_request_popup_close", settings)
        self.assertIn('bind("<Destroy>"', settings)
        self.assertIn('active_tooltip.get("window") is tip', settings)

    def test_remaining_action_windows_close_through_the_shared_coordinator(self) -> None:
        expected = {
            "_open_legacy_onboarding": "on_complete=self.open_settings",
            "open_ramble_chooser": "on_complete=lambda: begin(fmt)",
            "open_finish_chooser": "self._request_utility_close(window)",
            "open_update_window": "self._request_utility_close(window)",
        }
        for method, contract in expected.items():
            with self.subTest(method=method):
                self.assertIn(contract, method_source(method))


class PopupLifecycleRuntimeTests(unittest.TestCase):
    def test_real_tk_singletons_and_exact_once_callbacks(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "unittest", "tests.gui_popup_lifecycle", "-v"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            self.fail(
                "popup lifecycle runtime checks failed:\n"
                f"--- stdout ---\n{result.stdout[-5000:]}\n"
                f"--- stderr ---\n{result.stderr[-5000:]}"
            )


if __name__ == "__main__":
    unittest.main()
