"""2026-10-11, owner-approved site fix T1 and the coordinator's follow-up for 0.4.172:
the speech route a person's own provider key turns on has ONE name, "Your key".

The Pill's switch, the setup window and the site said "Your key"; the Pill menu's
Speech choice said "Use your key". And the setup window's PINNED SWITCHES line still
had a "Cloud" label: a setup saved before X-516 (no managed route any more) and
resumed later put "managed" back in the route and printed "Speech: Cloud". Talk DAT
runs no cloud (the owner's 09-22 spec), so that word was false, not just old. Its
"Auto" fallback named another retired route. The setup never applied either one:
_commit_voice_route accepts only "local" or "byok".

Pinned here: no shipped text says "Use your key"; the pinned line names only the
two routes that exist; a resumed route outside them falls back to the one the
config resolves to.
"""
from __future__ import annotations

from pathlib import Path
import re
import unittest

from knight_flow.ui.onboarding import pinned_route_label, resumed_route

ROOT = Path(__file__).resolve().parents[1]
SHIPPED = [
    *(ROOT / "knight_flow").rglob("*.py"),
    *(ROOT / "knight_flow" / "web_shell" / "shell_assets").rglob("*.js"),
    *(ROOT / "knight_flow" / "web_shell" / "shell_assets").rglob("*.html"),
    *(ROOT / "installer").rglob("*.py"),
    *(ROOT / "docs").glob("*.html"),
    *(ROOT / "docs").glob("*.js"),
]


class YourKeyHasOneName(unittest.TestCase):
    def test_no_shipped_text_says_use_your_key(self):
        said = [f"{path.relative_to(ROOT).as_posix()}:{number}"
                for path in SHIPPED
                for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1)
                if re.search(r"use your key", line, re.IGNORECASE)]
        self.assertEqual(said, [])

    def test_the_search_finds_a_known_positive(self):
        # The scan above passes on an empty list, so prove it reads these files: the
        # Pill's own switch names the route "Your key" in overlay.py.
        overlay = (ROOT / "knight_flow" / "overlay.py").read_text(encoding="utf-8")
        self.assertIn('("byok", "Your key")', overlay)
        self.assertIn(ROOT / "knight_flow" / "web_shell" / "shell_assets" / "shell.js", SHIPPED)

    def test_the_pinned_line_names_only_the_two_routes(self):
        self.assertEqual(pinned_route_label("local"), "Local")
        self.assertEqual(pinned_route_label("byok"), "Your key")

    def test_a_retired_or_unknown_route_is_not_named(self):
        for retired in ("managed", "cloud", "auto", "", "talk_dat_cloud", None):
            with self.subTest(route=retired):
                label = pinned_route_label(retired)
                self.assertEqual(label, "not chosen")
                self.assertNotIn("Cloud", label)
                self.assertNotIn("Auto", label)

    def test_the_setup_window_uses_both_rules(self):
        # The two helpers prove nothing if the setup window does not call them.
        source = (ROOT / "knight_flow" / "ui" / "onboarding.py").read_text(encoding="utf-8")
        self.assertIn("route_label = pinned_route_label(current_route)", source)
        self.assertIn('self.route_var.set(resumed_route(flags.get("route"), self.route_var.get()))', source)
        self.assertNotIn('"Cloud" if current_route', source)

    def test_a_resumed_route_keeps_only_local_or_your_key(self):
        self.assertEqual(resumed_route("byok", "local"), "byok")
        self.assertEqual(resumed_route(" local ", "byok"), "local")
        for retired in ("managed", "cloud", "auto", "", None):
            with self.subTest(saved=retired):
                self.assertEqual(resumed_route(retired, "local"), "local")
                self.assertEqual(resumed_route(retired, "byok"), "byok")


if __name__ == "__main__":
    unittest.main()
