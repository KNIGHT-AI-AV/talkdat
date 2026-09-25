"""X-767 (IP audit, 2026-09-24): no theme is shown under someone else's name.

Of the 40 families (80 themes), two carried a name that is someone else's:
"Night City Neon" (Night City is the city of CD PROJEKT's Cyberpunk games,
and its palette is that franchise's yellow #f4ee35, cyan and pink) and
"Champagne Glass" (Champagne is a protected designation of origin). People
now see "Yellow Neon" and "Pale Gold Glass".

The stored names stay the keys -- in saved settings, in the material file
names and in the site-theme map -- so nobody's saved choice changes. The web
shell shows display names and saves stored ones.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from knight_flow.themes import (
    SETTINGS_THEME_DISPLAY_NAMES,
    SETTINGS_THEME_FAMILIES,
    SETTINGS_THEME_PALETTES,
    theme_display_name,
    theme_stored_name,
)

ROOT = Path(__file__).resolve().parents[1]
FIELDS = ROOT / "knight_flow" / "web_shell" / "shell_assets" / "settings-fields.json"
# Words that name a film, show, game, place-of-origin or brand; none may
# reach a person's screen as a theme name.
BORROWED = ("night city", "champagne", "cyberpunk", "matrix", "tron", "blade runner", "barbie", "tiffany",
            "hermes", "pantone", "starbucks", "coca", "ferrari", "lamborghini", "gucci", "chanel", "wispr")


def shown_names() -> list[str]:
    return [theme_display_name(f"{family} {mode}") for family in SETTINGS_THEME_FAMILIES for mode in ("Dark", "Light")]


class TheNamesPeopleSeeTests(unittest.TestCase):
    def test_no_shown_name_borrows_a_brand(self) -> None:
        for name in shown_names():
            for word in BORROWED:
                with self.subTest(name=name, word=word):
                    self.assertNotIn(word, name.lower())

    def test_the_renames(self) -> None:
        self.assertEqual(theme_display_name("Night City Neon Dark"), "Yellow Neon Dark")
        self.assertEqual(theme_display_name("Champagne Glass Light"), "Pale Gold Glass Light")
        self.assertEqual(theme_display_name("Roman Clay Dark"), "Roman Clay Dark")

    def test_display_names_are_unique_and_round_trip(self) -> None:
        names = shown_names()
        self.assertEqual(len(names), len(set(names)))
        for family in SETTINGS_THEME_FAMILIES:
            for mode in ("Dark", "Light"):
                stored = f"{family} {mode}"
                with self.subTest(theme=stored):
                    self.assertEqual(theme_stored_name(theme_display_name(stored)), stored)
                    self.assertEqual(theme_stored_name(stored), stored, "a stored name must pass through unchanged")

    def test_the_stored_keys_did_not_move(self) -> None:
        for stored in SETTINGS_THEME_DISPLAY_NAMES:
            with self.subTest(family=stored):
                self.assertIn(stored, SETTINGS_THEME_FAMILIES)
                self.assertIn(stored, SETTINGS_THEME_PALETTES)
                slug = stored.lower().replace(" ", "-")
                for mode in ("dark", "light"):
                    self.assertTrue((ROOT / "knight_flow" / "assets" / "materials" / f"{slug}-{mode}.png").is_file())

    def test_the_settings_options_show_the_new_labels_and_keep_the_keys(self) -> None:
        fields = json.loads(FIELDS.read_text(encoding="utf-8"))
        field = next(f for f in fields if f["id"] == "ui.settings_theme")
        for option in field["options"]:
            with self.subTest(value=option["value"]):
                self.assertEqual(option["label"], theme_display_name(option["value"]))
                self.assertIn(option["value"].rsplit(" ", 1)[0], SETTINGS_THEME_FAMILIES)


class TheWebShellTests(unittest.TestCase):
    def backend(self, theme: str):
        import copy

        from knight_flow.config import DEFAULT_CONFIG
        from knight_flow.overlay import Overlay
        from knight_flow.web_shell.shell_backend import ShellBackend

        config = copy.deepcopy(DEFAULT_CONFIG)
        config["ui"]["settings_theme"] = theme
        persisted: list = []
        backend = ShellBackend(config, ROOT / "knight_flow" / "web_shell" / "shell_assets", persisted.append,
                               lambda: None, object.__new__(Overlay)._settings_palette)
        return backend, persisted

    def test_a_saved_old_name_shows_the_new_one(self) -> None:
        backend, _ = self.backend("Night City Neon Dark")
        state = backend.handle("state", {})
        self.assertEqual(state["theme"], "Yellow Neon Dark")
        self.assertEqual(state["palette"]["name"], "Yellow Neon Dark")
        self.assertEqual(state["palette"]["accent"], SETTINGS_THEME_PALETTES["Night City Neon"]["Dark"]["accent"])
        names = [theme["name"] for theme in state["themes"]]
        self.assertIn("Pale Gold Glass Light", names)
        self.assertFalse([n for n in names if re.search(r"(?i)night city|champagne", n)])

    def test_choosing_the_new_name_saves_the_stored_key(self) -> None:
        backend, persisted = self.backend("Flow Dark")
        revision = backend.handle("state", {})["revision"]
        backend.handle("save", {"revision": revision, "changes": {"ui.settings_theme": "Pale Gold Glass Light"}})
        self.assertEqual(persisted[-1]["ui"]["settings_theme"], "Champagne Glass Light")
        self.assertEqual(persisted[-1]["ui"]["theme"], "light")
        self.assertEqual(backend.handle("state", {})["theme"], "Pale Gold Glass Light")

    def test_the_tile_label_is_the_display_name(self) -> None:
        from knight_flow.web_shell.theme_assets import material_metadata

        self.assertEqual(material_metadata("Night City Neon")["family"], "Yellow Neon")
        self.assertEqual(material_metadata("Champagne Glass")["family"], "Pale Gold Glass")

    def test_the_material_is_found_by_either_name(self) -> None:
        from knight_flow.web_shell.theme_assets import MaterialLibrary

        library = MaterialLibrary()
        for shown, stored in (("Yellow Neon Dark", "Night City Neon Dark"), ("Pale Gold Glass Light", "Champagne Glass Light")):
            with self.subTest(theme=shown):
                self.assertEqual(library.read(shown, "preview"), library.read(stored, "preview"))


if __name__ == "__main__":
    unittest.main()
