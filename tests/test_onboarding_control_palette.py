"""Every shipped theme keeps the redesigned primary controls readable."""

from __future__ import annotations

import unittest

from knight_flow.themes import SETTINGS_THEME_PALETTES
from knight_flow.ui.atelier_controls import ATELIER_PALETTE_ROLES
from knight_flow.ui.onboarding import accessible_control_palette


def _luminance(colour: str) -> float:
    raw = colour.strip().lstrip("#")
    channels = [int(raw[index:index + 2], 16) / 255.0 for index in (0, 2, 4)]
    linear = [
        channel / 12.92
        if channel <= 0.04045
        else ((channel + 0.055) / 1.055) ** 2.4
        for channel in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(first: str, second: str) -> float:
    lighter, darker = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


class OnboardingControlPaletteTests(unittest.TestCase):
    def test_the_catalog_still_contains_every_audited_theme(self) -> None:
        count = sum(len(themes) for themes in SETTINGS_THEME_PALETTES.values())
        # Derived, not written down. A count in an assertion goes stale the
        # first time the catalogue grows, and reports a healthy addition as
        # a failure (X-538, 25 families to 40).
        from knight_flow.themes import SETTINGS_THEME_FAMILIES
        self.assertEqual(count, len(SETTINGS_THEME_FAMILIES) * 2)

    def test_all_semantic_button_roles_resolve_for_every_theme(self) -> None:
        missing: dict[str, list[str]] = {}
        for family, themes in SETTINGS_THEME_PALETTES.items():
            for name, palette in themes.items():
                controls = accessible_control_palette(palette)
                absent = sorted(set(ATELIER_PALETTE_ROLES) - set(controls))
                if absent:
                    missing[f"{family}/{name}"] = absent
        self.assertEqual(missing, {})

    def test_normal_hover_pressed_and_disabled_primary_labels_meet_wcag_aa(self) -> None:
        failures: list[tuple[str, str, float]] = []
        for family, themes in SETTINGS_THEME_PALETTES.items():
            for name, palette in themes.items():
                controls = accessible_control_palette(palette)
                pairs = {
                    "normal": (controls["primary"], controls["on_primary"]),
                    "hover": (controls["primary_hover"], controls["on_primary"]),
                    "pressed": (controls["primary_pressed"], controls["on_primary"]),
                    "disabled": (controls["surface_disabled"], controls["on_primary_disabled"]),
                }
                for state, (fill, label) in pairs.items():
                    ratio = _contrast(fill, label)
                    if ratio < 4.5:
                        failures.append((f"{family}/{name}", state, round(ratio, 3)))
        self.assertEqual(failures, [], f"primary control labels below WCAG AA: {failures}")

    def test_requested_canvas_surface_is_preserved(self) -> None:
        first_palette = next(iter(next(iter(SETTINGS_THEME_PALETTES.values())).values()))
        controls = accessible_control_palette(first_palette, canvas="#123456")
        self.assertEqual(controls["canvas"], "#123456")


if __name__ == "__main__":
    unittest.main()
