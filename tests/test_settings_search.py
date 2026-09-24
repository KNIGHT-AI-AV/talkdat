from __future__ import annotations

import unittest
from pathlib import Path

from knight_flow.ui.flow_console import SettingsSearchEntry, settings_search_results


ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "knight_flow" / "overlay.py"


class SettingsSearchRankingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.entries = (
            SettingsSearchEntry(
                "Dictation",
                "Mic + paste",
                "Microphone",
                "Choose the input device Talk DAT listens to.",
                ("Voice Mic + Paste",),
            ),
            SettingsSearchEntry(
                "Speech",
                "Local models",
                "Automatically download the selected local model",
                "Downloads on first use.",
                ("Voice Local Models", "offline speech"),
            ),
            SettingsSearchEntry(
                "General",
                "Privacy + updates",
                "Update channel",
                "Stable or beta releases.",
                ("System Privacy + Updates",),
            ),
        )

    def test_exact_label_outranks_help_and_location_matches(self) -> None:
        results = settings_search_results(self.entries, "microphone")
        self.assertEqual(results[0].label, "Microphone")

    def test_help_copy_is_searchable(self) -> None:
        results = settings_search_results(self.entries, "first use")
        self.assertEqual([result.section for result in results], ["Local models"])

    def test_legacy_deep_link_aliases_are_searchable(self) -> None:
        results = settings_search_results(self.entries, "voice local models")
        self.assertEqual(results[0].page, "Speech")

    def test_multiple_words_must_all_match_the_same_destination(self) -> None:
        self.assertEqual(settings_search_results(self.entries, "microphone beta"), ())

    def test_empty_query_returns_no_wall_of_results(self) -> None:
        self.assertEqual(settings_search_results(self.entries, "   "), ())


class SettingsProgressiveDisclosureSourceTests(unittest.TestCase):
    def test_specialist_sections_start_behind_native_disclosures(self) -> None:
        source = OVERLAY.read_text(encoding="utf-8")
        for title in (
            "Dictionary (raw editor)",
            "Advanced (STT)",
            "Backups + diagnostics",
            "Speech check",
        ):
            self.assertIn(f'"{title}":', source)
        self.assertIn('text="Show details"', source)
        self.assertIn('disclosure.configure(text="Hide details")', source)

    def test_search_and_deep_links_expand_a_collapsed_destination(self) -> None:
        source = OVERLAY.read_text(encoding="utf-8")
        selector_start = source.index("def select_settings_page(")
        selector_end = source.index("def refresh_settings_search(", selector_start)
        selector = source[selector_start:selector_end]
        self.assertIn('expand = getattr(holder, "_settings_expand", None)', selector)
        self.assertIn("expand()", selector)

    def test_search_has_keyboard_open_clear_and_control_f_paths(self) -> None:
        source = OVERLAY.read_text(encoding="utf-8")
        self.assertIn('text="Find a setting"', source)
        self.assertIn('"<Control-f>"', source)
        self.assertIn('settings_search_entry.bind(\n            "<Return>"', source)
        self.assertIn('settings_search_entry.bind(\n            "<Escape>"', source)

    def test_compact_rail_results_do_not_cram_the_full_location_on_one_line(self) -> None:
        source = OVERLAY.read_text(encoding="utf-8")
        self.assertIn('settings_search_results_box.insert("end", hit.label)', source)
        self.assertNotIn('settings_search_results_box.insert("end", hit.display)', source)
        self.assertIn('f"Selected: {location}. Enter opens."', source)
        self.assertIn('"<<ListboxSelect>>"', source)


if __name__ == "__main__":
    unittest.main()
