from __future__ import annotations

import ast
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "knight_flow" / "overlay.py"


def method_source(name: str) -> str:
    source = OVERLAY.read_text(encoding="utf-8")
    tree = ast.parse(source)
    overlay_class = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Overlay")
    method = next(
        node for node in overlay_class.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
    )
    return ast.get_source_segment(source, method) or ""


class RemainingUtilityMinimumSourceTests(unittest.TestCase):
    def test_fixed_footers_are_reserved_before_expanding_content(self) -> None:
        expectations = {
            "open_model_guide": ('controls.pack(side="bottom"', "table_frame.pack"),
            "open_translation": ('controls.pack(side="bottom"', 'content.pack(fill="both", expand=True'),
            "open_reset": ('reset_footer.pack(side="bottom"', 'body.pack(fill="both", expand=True'),
            "open_add_words": ('buttons.pack(side="bottom"', 'holder.pack(fill="both", expand=True'),
        }
        for name, (footer, content) in expectations.items():
            with self.subTest(function=name):
                source = method_source(name)
                self.assertIn(footer, source)
                self.assertIn(content, source)
                self.assertLess(source.index(footer), source.index(content))

    def test_account_supplies_close_footer_and_keyboard_scroll_contracts(self) -> None:
        source = method_source("open_account")
        self.assertIn("header_close = self._close_control", source)
        self.assertIn("window.rowconfigure(2, minsize=", source)
        self.assertIn("account_canvas.configure(takefocus=1)", source)
        for sequence in ("<Prior>", "<Next>", "<Home>", "<End>"):
            self.assertIn(sequence, source)

    def test_translation_has_responsive_cloud_and_local_lanes(self) -> None:
        source = method_source("open_translation")
        self.assertIn("arrange_route_options", source)
        self.assertIn("arrange_action_rows", source)
        self.assertIn("primary_controls", source)
        self.assertIn("local_controls", source)
        for contract in (
            "translate_toggle",
            "translation_translate",
            "translation_install_runtime",
            "translation_install_model",
            "translation_paste",
            "add_window_disposer",
        ):
            self.assertIn(contract, source)

    def test_destructive_and_dictionary_callbacks_survive_layout_changes(self) -> None:
        reset_source = method_source("open_reset")
        self.assertIn("perform(", reset_source)
        self.assertIn("license_forget", reset_source)
        words_source = method_source("open_add_words")
        self.assertIn("record_pronunciation", words_source)
        self.assertIn("apply_runtime_config", words_source)
        self.assertIn("save_settings", words_source)


class RemainingUtilityMinimumRuntimeProcessTests(unittest.TestCase):
    def test_real_tk_windows_pass_at_every_declared_minimum(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "unittest", "tests.gui_remaining_utility_minimum_layout", "-v"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=240,
        )
        if result.returncode != 0:
            self.fail(
                "remaining utility minimum-size runtime checks failed:\n"
                f"--- stdout ---\n{result.stdout[-9000:]}\n"
                f"--- stderr ---\n{result.stderr[-9000:]}"
            )


if __name__ == "__main__":
    unittest.main()
