"""Settings says what the app does, in sentences (owner's audit, 2026-09-23).

Three findings from the inventory, each pinned here:

* The Speech page's model select cut the recommended model to "Parakeet TDT
  0.6B v3 (reco..." at both scales. The select now shows the model's name, its
  full catalogue label rides along as a tooltip, and the field's help text says
  which model is recommended in a sentence. Home's status line drops the
  "(recommended)" note too, which also removes its nested brackets.
* Help text started lowercase ("stable gets tested releases; beta gets ..."),
  and several selects showed raw option ids ("stable", "heuristic",
  "shift_insert", "bottom-center"). Help is in sentences now, and options are
  words. Provider API variants and audio codecs keep the provider's spelling.
* settings-fields.json still declared Executive as the writing style's
  default after X-602 moved new installs to Chill. Declared defaults are now
  read from DEFAULT_CONFIG, the one place the real defaults live.
"""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from knight_flow.config import DEFAULT_CONFIG

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "knight_flow" / "web_shell" / "shell_assets"
MISSING = object()

#: Option labels that are deliberately the provider's own identifiers.
TECHNICAL_OPTIONS = ("deepgram.encoding",)


def read_path(config, identifier):
    current = config
    for part in identifier.split("."):
        if not isinstance(current, dict) or part not in current:
            return MISSING
        current = current[part]
    return current


def all_fields():
    from knight_flow.web_shell.shell_backend import declared_fields, provider_fields

    return declared_fields(ASSETS) + provider_fields(copy.deepcopy(DEFAULT_CONFIG))


def backend(config):
    from knight_flow.overlay import Overlay
    from knight_flow.web_shell.shell_backend import ShellBackend

    palette = object.__new__(Overlay)._settings_palette
    return ShellBackend(config, ASSETS, lambda candidate: None, lambda: None, palette)


def snapshot_field(snapshot, identifier):
    for page in snapshot["pages"]:
        for section in page.get("sections", []):
            for field in section["fields"]:
                if field["id"] == identifier:
                    return field
    raise AssertionError(f"{identifier} is not on any page")


class TheSpeechModelFitsItsSelectTests(unittest.TestCase):
    def local_model_field(self):
        return next(field for field in all_fields() if field["id"] == "stt.providers.local.model")

    def test_options_are_names_and_the_recommendation_is_a_sentence(self) -> None:
        field = self.local_model_field()
        labels = [option["label"] for option in field["options"]]
        self.assertTrue(labels)
        self.assertEqual([label for label in labels if "(recommended)" in label], [],
                         "a note inside the option is what got cut off")
        # About what a 250 CSS px select at body size shows without cutting.
        self.assertLessEqual(max(len(label) for label in labels), 26, labels)
        self.assertIn("Parakeet TDT 0.6B v3 (recommended)", [option["title"] for option in field["options"]],
                      "the full catalogue label no longer rides along as a tooltip")
        self.assertIn("Recommended: Parakeet TDT 0.6B v3", field["description"])

    def test_the_live_snapshot_keeps_the_short_names(self) -> None:
        field = snapshot_field(backend(copy.deepcopy(DEFAULT_CONFIG)).snapshot(), "stt.providers.local.model")
        self.assertIn("Parakeet TDT 0.6B v3", [option["label"] for option in field["options"]])
        self.assertTrue(field["description"].startswith("Recommended:"))

    def test_the_select_carries_a_tooltip(self) -> None:
        shell = (ASSETS / "shell.js").read_text(encoding="utf-8")
        start = shell.index('if (field.type === "select") {')
        block = shell[start:shell.index("return select;", start)]
        self.assertIn("select.title", block, "a long option name has no way to be read in full")

    def test_home_names_the_model_without_its_note(self) -> None:
        from knight_flow.web_shell.home_workspace import home_greeting

        speech = home_greeting(json.loads(json.dumps(DEFAULT_CONFIG)))["speech"]
        self.assertEqual(speech["model"], "Parakeet TDT 0.6B v3")


class HelpTextIsInSentencesTests(unittest.TestCase):
    def test_every_help_text_starts_as_a_sentence(self) -> None:
        offenders = [
            f"{field['id']}: {field['description'][:50]}"
            for field in all_fields()
            if (field.get("description") or "")[:1].islower()
        ]
        self.assertEqual(offenders, [])

    def test_options_are_words_not_raw_ids(self) -> None:
        offenders = []
        for field in all_fields():
            if field["id"] in TECHNICAL_OPTIONS or field["id"].endswith(".variant"):
                continue
            for option in field.get("options") or []:
                label, value = str(option.get("label")), str(option.get("value"))
                if label == value and label[:1].islower():
                    offenders.append(f"{field['id']}: {label}")
        self.assertEqual(offenders, [])

    def test_the_update_channel_reads_as_two_sentences(self) -> None:
        field = next(field for field in all_fields() if field["id"] == "updates.channel")
        self.assertEqual(field["description"],
                         "Stable gets tested releases. Beta gets new features earlier, with more rough edges.")
        self.assertEqual([option["label"] for option in field["options"]], ["Stable", "Beta"])


class TheDeclaredDefaultIsTheRealDefaultTests(unittest.TestCase):
    def test_every_declared_default_is_read_from_the_config(self) -> None:
        from knight_flow.web_shell.shell_backend import declared_fields

        mismatched = []
        for field in declared_fields(ASSETS):
            real = read_path(DEFAULT_CONFIG, field["id"])
            if real is not MISSING and field.get("type") != "secret" and field.get("default") != real:
                mismatched.append(f"{field['id']}: {field.get('default')!r} != {real!r}")
        self.assertEqual(mismatched, [])

    def test_the_writing_style_default_is_chill_like_a_new_install(self) -> None:
        from knight_flow.web_shell.shell_backend import declared_fields

        field = next(field for field in declared_fields(ASSETS) if field["id"] == "cleanup.format_intensity")
        real = DEFAULT_CONFIG["cleanup"]["format_intensity"]
        self.assertEqual(field["default"], real)
        label = next(option["label"] for option in field["options"] if option["value"] == real)
        self.assertEqual(label, "Chill", "X-602: new installs start on Chill")
        on_disk = json.loads((ASSETS / "settings-fields.json").read_text(encoding="utf-8"))
        stored = next(item for item in on_disk if item["id"] == "cleanup.format_intensity")
        self.assertEqual(stored["default"], real, "the JSON still carries a stale copy of the default")

    def test_a_config_that_names_no_style_shows_the_real_one(self) -> None:
        config = copy.deepcopy(DEFAULT_CONFIG)
        del config["cleanup"]["format_intensity"]
        snapshot = backend(config).snapshot()
        self.assertEqual(snapshot["intensity"], DEFAULT_CONFIG["cleanup"]["format_intensity"])
        self.assertEqual(snapshot_field(snapshot, "cleanup.format_intensity")["value"],
                         DEFAULT_CONFIG["cleanup"]["format_intensity"])

    def test_the_tk_menus_read_the_same_default(self) -> None:
        from knight_flow.overlay import default_finish

        self.assertEqual(default_finish(), DEFAULT_CONFIG["cleanup"]["format_intensity"])
        source = (ROOT / "knight_flow" / "overlay.py").read_text(encoding="utf-8")
        self.assertNotIn('.get("format_intensity", "executive")', source,
                         "a Tk menu still assumes Executive when the config names no finish")


if __name__ == "__main__":
    unittest.main()
