from __future__ import annotations

import ast
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OVERLAY_PATH = ROOT / "knight_flow" / "overlay.py"


def method_source(name: str) -> str:
    source = OVERLAY_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    overlay_class = next(
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Overlay"
    )
    method = next(
        node for node in overlay_class.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
    )
    lines = source.splitlines()
    return "\n".join(lines[method.lineno - 1:method.end_lineno])


class UtilityMinimumLayoutSourceTests(unittest.TestCase):
    def test_overflowing_utilities_expose_keyboard_scroll_contracts(self) -> None:
        for name in ("open_mic_doctor", "open_feedback_form", "open_finish_chooser", "open_stats"):
            with self.subTest(function=name):
                source = method_source(name)
                self.assertIn("scrollable_region", source)
                self.assertIn("wheel_host=window", source)
                self.assertIn("takefocus=1", source)
                self.assertIn('style="Flow.Vertical.TScrollbar"', source)
                for sequence in ("<Prior>", "<Next>", "<Home>", "<End>"):
                    self.assertIn(sequence, source)

    def test_pinned_action_rows_are_reserved_before_expanding_content(self) -> None:
        for name in ("open_status", "open_mic_doctor", "open_feedback_form", "open_stats"):
            with self.subTest(function=name):
                source = method_source(name)
                controls = source.index("controls.pack")
                expanding = source.index('pack(fill="both", expand=True')
                self.assertLess(controls, expanding)
                self.assertIn('side="bottom"', source[:expanding])

    def test_finish_chooser_has_a_real_narrow_structure(self) -> None:
        source = method_source("open_finish_chooser")
        self.assertIn("arrange_finish_cards", source)
        self.assertIn('minimum_size=(480, 320)', source)
        self.assertIn('grid_configure(row=3, column=0, columnspan=2', source)
        self.assertIn('ui_scale.px(680, self.config)', source)

    def test_history_and_stats_protect_long_secondary_text(self) -> None:
        history = method_source("open_history")
        self.assertIn("history_path_label.pack", history)
        self.assertIn("wraplength = max(160, int(event.width))", history)
        self.assertIn("history_path_label.configure(wraplength=wraplength)", history)
        self.assertLess(history.index("controls.pack"), history.index('body.pack(fill="both", expand=True'))
        self.assertIn('controls.pack(side="bottom"', history)

        stats = method_source("open_stats")
        self.assertIn("arrange_metric", stats)
        self.assertIn('width < ui_scale.px(480, self.config)', stats)
        self.assertIn("wraplength = max(120, width - 32 if narrow", stats)
        self.assertIn("value_widget.configure(", stats)

    def test_callbacks_and_mic_disposal_contracts_survive_layout_repairs(self) -> None:
        expected = {
            "open_status": ("status_provider", "check_updates", "panic"),
            "open_mic_doctor": ("mic_doctor_run", "mic_input_select", "add_window_disposer"),
            "open_feedback_form": ('callbacks.get("feedback")', "include_logs"),
            "open_finish_chooser": ("format_intensity", "save_settings"),
            "open_stats": ("history_stats", "usage_summary"),
        }
        for name, contracts in expected.items():
            with self.subTest(function=name):
                source = method_source(name)
                for contract in contracts:
                    self.assertIn(contract, source)


class UtilityMinimumLayoutRuntimeProcessTests(unittest.TestCase):
    def test_real_windows_are_reachable_at_their_minimum_sizes(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "unittest", "tests.gui_utility_minimum_layout", "-v"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=240,
        )
        if result.returncode != 0:
            self.fail(
                "utility minimum-size runtime checks failed in their clean Tk interpreter:\n"
                f"--- stdout ---\n{result.stdout[-7000:]}\n"
                f"--- stderr ---\n{result.stderr[-7000:]}"
            )


if __name__ == "__main__":
    unittest.main()
