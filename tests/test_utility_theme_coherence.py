from __future__ import annotations

import ast
import re
import subprocess
import sys
import unittest
from pathlib import Path

from knight_flow.overlay import Overlay
from knight_flow.themes import SETTINGS_THEME_FAMILIES


ROOT = Path(__file__).resolve().parents[1]
OVERLAY_PATH = ROOT / "knight_flow" / "overlay.py"
LEGACY_DARK_SHELL_COLORS = {"#071113", "#102126", "#f4f6fb", "#dfe7f2", "#7ee2c3"}


def method_source(name: str) -> str:
    """Read a method from the current file, not linecache's imported snapshot.

    The full suite imports Overlay early and exercises real Tk windows for a
    while.  A concurrent scoped repair can legitimately add lines to the same
    shared worktree during that run, making ``inspect.getsource`` pair the old
    code object's line number with the new file. Parsing the current file keeps
    this source guard deterministic without weakening what it checks.
    """

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


def relative_luminance(color: str) -> float:
    channels = [int(color[index:index + 2], 16) / 255.0 for index in (1, 3, 5)]
    linear = [
        value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
        for value in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast_ratio(left: str, right: str) -> float:
    left_luminance = relative_luminance(left)
    right_luminance = relative_luminance(right)
    return (max(left_luminance, right_luminance) + 0.05) / (min(left_luminance, right_luminance) + 0.05)


class UtilityThemeSourceTests(unittest.TestCase):
    def test_legacy_fixed_dark_shells_are_gone(self) -> None:
        for name in ("open_history", "open_status", "open_stats", "open_whats_new", "open_update_window"):
            with self.subTest(function=name):
                source = method_source(name).lower()
                offenders = sorted(color for color in LEGACY_DARK_SHELL_COLORS if color in source)
                self.assertEqual(offenders, [], f"{name} still hard-codes the old dark utility shell: {offenders}")
                self.assertIn("_settings_palette", source)
                if name == "open_history":
                    self.assertIsNone(
                        re.search(r"#[0-9a-f]{6}", source),
                        "History still contains a fixed colour instead of a semantic palette role",
                    )
                    self.assertIn('palette_more["danger"]', source)

    def test_all_material_themes_gain_readable_functional_roles(self) -> None:
        overlay = object.__new__(Overlay)
        overlay.config = {"ui": {}}
        for family in SETTINGS_THEME_FAMILIES:
            for mode in ("Dark", "Light"):
                name = f"{family} {mode}"
                with self.subTest(theme=name):
                    palette = overlay._settings_palette(name)
                    for role in ("success", "warning", "danger"):
                        for surface in ("bg", "panel", "surface", "field"):
                            self.assertGreaterEqual(
                                contrast_ratio(palette[role], palette[surface]),
                                4.5,
                                f"{role} is not readable on {name}'s {surface} utility surface",
                            )
                    self.assertGreaterEqual(contrast_ratio(palette["on_accent"], palette["accent"]), 4.5)
                    self.assertGreaterEqual(contrast_ratio(palette["on_accent2"], palette["accent2"]), 4.5)
                    self.assertGreaterEqual(contrast_ratio(palette["on_danger"], palette["danger"]), 4.5)

    def test_light_theme_titlebars_are_given_theme_text_explicitly(self) -> None:
        for name in (
            "open_translation",
            "open_history",
            "open_reset",
            "open_mic_doctor",
            "open_taste_race",
            "open_ramble_chooser",
            "open_feedback_form",
            "open_finish_chooser",
        ):
            with self.subTest(function=name):
                source = method_source(name)
                calls = [line for line in source.splitlines() if "_make_glass_titlebar" in line]
                self.assertTrue(calls, f"{name} no longer creates its custom titlebar")
                self.assertTrue(
                    all('palette["text"]' in line for line in calls),
                    f"{name} can still render the old white title ink on a light theme: {calls}",
                )

    def test_scratchpad_chrome_uses_theme_ink_while_paper_remains_material(self) -> None:
        source = method_source("open_scratchpad")
        self.assertGreaterEqual(source.count('fg=palette["muted"]'), 2)
        self.assertIn('text.tag_configure("paper", background="#d9c3ab")', source)


class UtilityThemeRuntimeProcessTests(unittest.TestCase):
    def test_real_dark_and_light_windows_match_their_semantic_palettes(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "unittest", "tests.gui_utility_theme_coherence", "-v"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=240,
        )
        if result.returncode != 0:
            self.fail(
                "utility theme runtime checks failed in their clean Tk interpreter:\n"
                f"--- stdout ---\n{result.stdout[-5000:]}\n"
                f"--- stderr ---\n{result.stderr[-5000:]}"
            )


if __name__ == "__main__":
    unittest.main()
