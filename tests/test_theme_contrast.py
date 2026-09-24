from __future__ import annotations

import unittest


class ThemeRowsArePreviewsTests(unittest.TestCase):
    """Fifty themes in a plain dropdown are fifty identical lines.

    The first attempt tinted each Listbox row with the theme's panel colour,
    which is one colour out of the five that make a theme recognisable -- and a
    Listbox cannot draw anything else. Reported as "I just had to scroll down,
    but it wasn't obvious", and then again as the previews never arriving.
    """

    def source(self) -> str:
        from pathlib import Path
        return (Path(__file__).resolve().parents[1] / "knight_flow" / "overlay.py").read_text(encoding="utf-8")

    def picker(self) -> str:
        # The picker grew real keyboard, focus-dismissal, and monitor-clamping
        # behavior. A fixed character slice now cuts the function in half and
        # reports missing swatches that are plainly present below the cutoff.
        import inspect
        from knight_flow.overlay import Overlay

        return inspect.getsource(Overlay._open_theme_picker)

    def test_the_picker_no_longer_uses_a_listbox(self) -> None:
        self.assertNotIn("tk.Listbox", self.picker(),
                         "a Listbox can only colour a row; it cannot show a design")

    def test_each_row_shows_background_panel_accent_and_text(self) -> None:
        """X-337: rows wear the MATERIAL (select tinted toward accent) with
        the ink picked by measured contrast -- the bg token painted every
        dark theme the same near-black. Panel and accent still ride as
        swatches; together they are what makes a theme look like itself."""
        picker = self.picker()
        for key in ("theme_material(palette, mode)", "material_ink(palette, material)",
                    'palette["panel"]', 'palette["accent"]'):
            with self.subTest(key=key):
                self.assertIn(key, picker)

    def test_every_palette_has_the_keys_a_row_needs(self) -> None:
        """A missing key would silently drop that theme from the list."""
        from knight_flow.overlay import SETTINGS_THEME_PALETTES
        for family, modes in SETTINGS_THEME_PALETTES.items():
            for mode, palette in modes.items():
                with self.subTest(theme=f"{family} {mode}"):
                    for key in ("bg", "panel", "accent", "text"):
                        self.assertIn(key, palette)

    def test_the_current_theme_is_marked(self) -> None:
        self.assertIn("option == current", self.picker())

    def test_the_list_scrolls(self) -> None:
        picker = self.picker()
        self.assertIn("yview", picker)
        self.assertIn("MouseWheel", picker)


if __name__ == "__main__":
    unittest.main()


# WCAG 2.1 AA for body text. The relaxed 3:1 threshold applies only to large
# text -- 18pt, or 14pt bold -- and none of these roles are drawn at that size.
AA_NORMAL_TEXT = 4.5

# Every surface a label can be drawn on. The same `muted` colour is used across
# all four, so it has to hold on all four.
SURFACES = ("bg", "panel", "surface", "field")


def relative_luminance(colour: str) -> float:
    digits = colour.lstrip("#")
    channels = [int(digits[index:index + 2], 16) / 255 for index in (0, 2, 4)]
    linear = [
        (value / 12.92) if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4
        for value in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast_ratio(foreground: str, background: str) -> float:
    first, second = relative_luminance(foreground), relative_luminance(background)
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


class ThemeLegibilityTests(unittest.TestCase):
    """Fifty themes shipped without anyone measuring whether they are legible.

    Eighty now, and the fifteen added in X-538 were generated against these
    thresholds rather than checked after the fact.

    Primary text was fine: 200 theme-and-surface combinations, none below AA,
    the worst still at 7.23:1. `muted` was not. Eighty of the same 200 sat
    below AA and the worst was 3.10:1 -- and `muted` carries secondary labels,
    hints and status lines, which is precisely the text someone reads when
    they are unsure what a control does.

    The repair blended each failing `muted` toward its own theme's `text`
    until it cleared AA on all four surfaces, 39% of the way on average.
    Blending toward `text` rather than toward white keeps the hue the theme
    chose, and guarantees a solution exists because `text` already passes.
    """

    def combinations(self):
        from knight_flow.themes import SETTINGS_THEME_PALETTES
        for family, themes in SETTINGS_THEME_PALETTES.items():
            for name, palette in themes.items():
                for surface in SURFACES:
                    yield f"{family}/{name}", surface, palette

    def test_primary_text_is_legible_on_every_surface(self) -> None:
        failures = [
            (theme, surface, round(contrast_ratio(palette["text"], palette[surface]), 2))
            for theme, surface, palette in self.combinations()
            if contrast_ratio(palette["text"], palette[surface]) < AA_NORMAL_TEXT
        ]
        self.assertEqual(failures, [], f"text below WCAG AA: {failures}")

    def test_muted_text_is_legible_on_every_surface(self) -> None:
        """The one that was actually broken, in 40% of combinations."""
        failures = [
            (theme, surface, round(contrast_ratio(palette["muted"], palette[surface]), 2))
            for theme, surface, palette in self.combinations()
            if contrast_ratio(palette["muted"], palette[surface]) < AA_NORMAL_TEXT
        ]
        self.assertEqual(failures, [], f"muted text below WCAG AA: {failures}")

    def test_muted_stays_dimmer_than_primary_text(self) -> None:
        """Setting muted equal to text would satisfy the test above and destroy
        the distinction the colour exists to make."""
        collapsed = sorted({
            theme for theme, _surface, palette in self.combinations()
            if palette["muted"].lower() == palette["text"].lower()
        })
        self.assertEqual(collapsed, [], f"muted is indistinguishable from text in {collapsed}")

    def test_every_theme_defines_every_colour_role(self) -> None:
        """A missing key raises during window construction, inside a Tk
        callback, where a --windowed build has no stderr to report it."""
        from knight_flow.themes import SETTINGS_THEME_PALETTES, SETTINGS_THEME_PALETTE_KEYS

        missing = {
            f"{family}/{name}": sorted(set(SETTINGS_THEME_PALETTE_KEYS) - set(palette))
            for family, themes in SETTINGS_THEME_PALETTES.items()
            for name, palette in themes.items()
            if set(SETTINGS_THEME_PALETTE_KEYS) - set(palette)
        }
        self.assertEqual(missing, {}, f"themes missing colour roles: {missing}")

    def test_the_focus_background_keeps_its_label_readable(self) -> None:
        """Focused controls draw text on `select`, so that pair has to pass.

        Adding a focus indicator is the kind of change that fixes one
        accessibility problem by creating another: an unreadable focused
        button is worse than an invisible focus ring, because the person
        cannot even read what they are about to activate.
        """
        from knight_flow.themes import SETTINGS_THEME_PALETTES
        failures = [
            (f"{family}/{name}", round(contrast_ratio(palette["text"], palette["select"]), 2))
            for family, themes in SETTINGS_THEME_PALETTES.items()
            for name, palette in themes.items()
            if contrast_ratio(palette["text"], palette["select"]) < AA_NORMAL_TEXT
        ]
        self.assertEqual(failures, [], f"focused label below WCAG AA: {failures}")

    def test_the_focus_border_meets_non_text_contrast(self) -> None:
        """WCAG 1.4.11 asks 3:1 for a control boundary that carries meaning.

        For an entry the accent border is the only focus indicator there is,
        so 3:1 against both surfaces it can sit on is the whole requirement.
        Midnight Ink/Dark measured 2.99:1 -- close enough to look fine and
        still wrong, which is exactly what a threshold is for.
        """
        from knight_flow.themes import SETTINGS_THEME_PALETTES
        failures = []
        for family, themes in SETTINGS_THEME_PALETTES.items():
            for name, palette in themes.items():
                against = min(
                    contrast_ratio(palette["accent"], palette["panel"]),
                    contrast_ratio(palette["accent"], palette["button"]),
                )
                if against < 3.0:
                    failures.append((f"{family}/{name}", round(against, 2)))
        self.assertEqual(failures, [], f"focus border below 3:1: {failures}")

    def test_derived_disabled_copy_and_focus_ink_hold_across_every_theme(self) -> None:
        from knight_flow.overlay import Overlay

        overlay = Overlay.__new__(Overlay)
        overlay.config = {}
        failures: list[tuple[str, str, float]] = []
        for theme in overlay._settings_theme_options():
            palette = overlay._settings_palette(theme)
            for surface in ("button", "panel", "field"):
                ratio = contrast_ratio(palette["disabled_text"], palette[surface])
                if ratio < AA_NORMAL_TEXT:
                    failures.append((theme, f"disabled/{surface}", round(ratio, 2)))
            for surface in (
                "bg",
                "panel",
                "surface",
                "glass",
                "button",
                "field",
                "select",
            ):
                ratio = contrast_ratio(palette["text"], palette[surface])
                if ratio < 3.0:
                    failures.append((theme, f"focus/{surface}", round(ratio, 2)))
            for foreground, background in (
                ("on_accent", "accent"),
                ("on_accent2", "accent2"),
                ("on_danger", "danger"),
            ):
                ratio = contrast_ratio(palette[foreground], palette[background])
                if ratio < AA_NORMAL_TEXT:
                    failures.append((theme, f"{foreground}/{background}", round(ratio, 2)))

        self.assertEqual(failures, [], f"derived state colours below contrast floor: {failures}")


class FocusIsVisibleTests(unittest.TestCase):
    """Tabbing moved an invisible cursor.

    Every ttk style mapped "active", which is mouse hover, and none mapped
    "focus". A keyboard user could tab through Settings with no way to tell
    which control Enter or Space would operate. These windows are
    overrideredirect, so there is no OS focus ring to fall back on either.
    """

    def styles(self) -> str:
        import inspect
        from knight_flow.overlay import Overlay

        return inspect.getsource(Overlay._style_settings_widgets)

    def test_buttons_entries_and_checkboxes_all_style_focus(self) -> None:
        styles = self.styles()
        for widget in ("Flow.TButton", "Flow.TEntry", "Flow.TCheckbutton"):
            with self.subTest(widget=widget):
                marker = f'style.map(\n            "{widget}"'
                start = styles.index(marker)
                end = styles.find("\n        style.", start + len(marker))
                block = styles[start:end if end >= 0 else None]
                self.assertIn('"focus"', block, f"{widget} gives no sign it has keyboard focus")

    def test_focus_is_listed_before_active(self) -> None:
        """ttk takes the first matching entry, so a focused control under the
        pointer must still read as focused rather than as merely hovered."""
        styles = self.styles()
        block = styles[styles.index('style.map(\n            "Flow.TButton"'):][:1400]
        self.assertLess(block.index('"focus"'), block.index('"active"'))
