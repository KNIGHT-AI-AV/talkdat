"""One destination, one name (owner's audit, 2026-09-23).

The inventory found the same places under two names at once:

* the Pill menu row is "Features" in the Tk menu and "Tools" in the web menu;
* the same destination is "Offline speech" in the menu but "Local models" in
  Settings, the tray, the sidebar, and "Local speech models" on Speech check;
* the tray says "Quit Talk DAT!" while the Pill menu says "Close Talk DAT!";
* the already-running box calls the product "Talk Dat!";
* the pause message sends people to a resume row the Pill menu does not have.

Settings' names win, because Settings is where a person goes looking. These
checks read the labels the app actually builds, not a copy of them.
"""
from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "knight_flow" / "app.py"
SHELL = ROOT / "knight_flow" / "web_shell" / "shell_assets"


def menu_rows() -> dict[str, tuple[str, str]]:
    """Every Pill menu row, as the Tk menu and the web menu both receive them."""
    from knight_flow.overlay import Overlay

    bare = object.__new__(Overlay)
    bare.config = {"overlay": {}}
    rows = bare._context_menu_default_rows(include_feature_actions=True)
    rows += bare._context_menu_default_rows()
    return {identifier: (label, description) for identifier, label, description, _icon in rows}


def string_literals(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            found.append(node.value)
        elif isinstance(node, ast.JoinedStr):
            found.append("".join(part.value for part in node.values if isinstance(part, ast.Constant)))
    return found


class TheMenuUsesSettingsNamesTests(unittest.TestCase):
    def test_the_features_row_is_tools(self) -> None:
        label, description = menu_rows()["more_features"]
        self.assertEqual(label, "Tools")
        self.assertNotIn("Features", description)

    def test_local_models_has_one_name(self) -> None:
        label, _description = menu_rows()["local_models"]
        self.assertEqual(label, "Local models")
        from knight_flow.web_shell.shell_backend import PAGES

        settings_label = next(page[1] for page in PAGES if page[0] == "models")
        self.assertEqual(label, settings_label, "the menu and Settings name this page differently")
        tray = (ROOT / "knight_flow" / "tray.py").read_text(encoding="utf-8")
        self.assertIn('"Local models"', tray)
        mic_check = (SHELL / "mic-check.js").read_text(encoding="utf-8")
        self.assertNotIn("Local speech models", mic_check)

    def test_quit_is_quit_in_the_menu_and_the_tray(self) -> None:
        label, _description = menu_rows()["quit_app"]
        self.assertEqual(label, "Quit Talk DAT!")
        tray = (ROOT / "knight_flow" / "tray.py").read_text(encoding="utf-8")
        self.assertIn('"Quit Talk DAT!"', tray)
        self.assertNotIn("Close Talk DAT!", tray)

    def test_no_message_still_names_offline_speech(self) -> None:
        offenders = [text for text in string_literals(APP) if "Offline speech" in text]
        self.assertEqual(offenders, [], "a message still sends people to 'Offline speech'")

    def test_the_pause_message_only_points_at_a_real_resume(self) -> None:
        """The tray has "Resume dictation"; the Pill menu has no resume row."""
        offenders = [text for text in string_literals(APP) if re.search(r"resume from the tray or pill menu", text, re.I)]
        self.assertEqual(offenders, [])
        self.assertTrue(any("Resume dictation" in text for text in string_literals(APP)))


class TheProductNameIsSpelledOneWayTests(unittest.TestCase):
    def test_the_already_running_box_says_talk_dat(self) -> None:
        from knight_flow import single_instance

        box = mock.Mock()
        fake_windll = mock.Mock()
        fake_windll.user32.MessageBoxW = box
        with mock.patch.object(single_instance.sys, "platform", "win32"), \
                mock.patch.object(single_instance.ctypes, "windll", fake_windll, create=True):
            single_instance.show_already_running_message()
        box.assert_called_once()
        _owner, text, caption, _flags = box.call_args.args
        self.assertEqual(caption, "Talk DAT!")
        self.assertIn("Talk DAT!", text)
        self.assertNotIn("Talk Dat!", text)
        self.assertNotIn("overlay", text.lower(), "people call it the Pill, not the overlay")

    def test_no_ui_string_spells_it_talk_dat_lowercase(self) -> None:
        """File names ("Talk Dat!.exe") keep their spelling; words people read do not."""
        offenders = {}
        for path in sorted((ROOT / "knight_flow").rglob("*.py")):
            texts = [text for text in string_literals(path) if "Talk Dat!" in text and not re.search(r"Talk Dat!(\.exe|\.spec| Uninstaller|\\|/)", text)]
            if texts:
                offenders[str(path.relative_to(ROOT))] = texts[:3]
        self.assertEqual(offenders, {})


if __name__ == "__main__":
    unittest.main()
