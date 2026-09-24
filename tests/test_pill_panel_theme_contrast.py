from __future__ import annotations

import unittest
from pathlib import Path

from knight_flow.themes import SETTINGS_THEME_PALETTES
from knight_flow.ui.onboarding import _contrast_ratio


ROOT = Path(__file__).resolve().parents[1]
OVERLAY_SOURCE = (ROOT / "knight_flow" / "overlay.py").read_text(encoding="utf-8")


class PillPanelThemeContrastTests(unittest.TestCase):
    def test_every_menu_copy_surface_pair_meets_aa_in_every_theme(self) -> None:
        failures: list[str] = []
        theme_count = 0
        for family, modes in SETTINGS_THEME_PALETTES.items():
            for mode, palette in modes.items():
                theme_count += 1
                for foreground, background in (
                    ("text", "select"),
                    ("text", "panel"),
                    ("muted", "panel"),
                ):
                    ratio = _contrast_ratio(palette[foreground], palette[background])
                    if ratio < 4.5:
                        failures.append(
                            f"{family} {mode} {foreground}/{background}: {ratio:.2f}:1"
                        )
        # Derived, not written down. A count in an assertion goes stale the
        # first time the catalogue grows, and reports a healthy addition as
        # a failure (X-538, 25 families to 40).
        from knight_flow.themes import SETTINGS_THEME_FAMILIES
        self.assertEqual(theme_count, len(SETTINGS_THEME_FAMILIES) * 2)
        self.assertEqual(failures, [])

    def test_selected_menu_copy_has_no_dark_theme_only_foreground(self) -> None:
        self.assertNotIn("#d8fdf2", OVERLAY_SOURCE.lower())

    def test_route_switch_uses_the_proven_text_foreground_when_selected(self) -> None:
        block = OVERLAY_SOURCE[
            OVERLAY_SOURCE.index("# --- the pinned three-position route switch"):
            OVERLAY_SOURCE.index("# --- the pinned two-sided finish switch")
        ]
        self.assertIn(
            'text_fill = palette["text"] if active or not locked else palette["muted"]',
            block,
        )
        self.assertIn(
            'fill=palette["text"] if active or not locked else palette["muted"]',
            block,
        )
        self.assertNotIn(
            'palette["warm"] if active else palette["text"]',
            block,
        )

    def test_active_rows_and_reset_confirmation_do_not_use_decorative_colors_for_copy(self) -> None:
        rows = OVERLAY_SOURCE[
            OVERLAY_SOURCE.index("menu_hotkey_actions ="):
            OVERLAY_SOURCE.index("def _context_menu_background")
        ]
        self.assertIn('text=title,\n                anchor="w",\n                fill=palette["text"]', rows)
        self.assertIn(
            'fill=palette["text"] if armed or footer_focused else palette["muted"]',
            rows,
        )


if __name__ == "__main__":
    unittest.main()
