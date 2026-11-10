"""0.4.176: the EULA and the public docs say what this version does.

The site branch's lines (34942763, ported as they are) were true for 0.4.175:
the counts on by default, the two launch reports before setup, Reset turning
the counts back on, command search and a remote Ollama address under Local-only
privacy, and the hostname at sign-in. 0.4.176 changes each of those
(8e57037, 57c809b, and items 4, 5 and 7), so the files that ship with it
(EULA.md inside every build; docs/NETWORK.md, docs/TELEMETRY.md and the
open-source README in the next export) say so, and none keeps a 0.4.175
caveat. The EULA keeps the site's one effective date, set at release.
"""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def flat(name: str) -> str:
    return " ".join((ROOT / name).read_text(encoding="utf-8").split())


class TheDocsSayWhat0476DoesTests(unittest.TestCase):
    def test_no_doc_keeps_a_0475_caveat(self) -> None:
        for name in ("EULA.md", "docs/NETWORK.md", "docs/TELEMETRY.md", "open_source/README.md"):
            with self.subTest(doc=name):
                self.assertNotIn("0.4.175", flat(name))

    def test_the_eula_sends_the_counts_only_after_a_yes_and_command_search_stops_under_local_only(self) -> None:
        eula = flat("EULA.md")
        self.assertIn("Effective date: October 27, 2026", eula, "one date, set at release")
        self.assertIn("The official binaries send the usage counts described in the Privacy Notice only if you "
                      "choose to share them, when the app asks or in Settings, Privacy.", eula)
        self.assertIn("a random install ID, not linked to you or your account", eula)
        self.assertIn("In command mode, if no text is selected and Local-only privacy is off, Talk DAT! opens a "
                      "web search for the words you said at perplexity.ai", eula)

    def test_telemetry_says_nothing_goes_before_an_answer(self) -> None:
        text = flat("docs/TELEMETRY.md")
        self.assertIn("## 1. Usage counts: official builds, only after you say yes, their own switch", text)
        self.assertIn("`privacy.usage_counts_asked`", text)
        self.assertIn("Nothing is sent before an answer.", text)
        self.assertIn("Share and Don't share", text)
        self.assertIn("Home asks", text)
        self.assertIn("Reset keeps the answer.", text)
        self.assertIn("Settings, Privacy shows it", text, "the install ID, for deletion")
        self.assertNotIn("It is on by default", text)

    def test_network_lists_what_0476_sends_and_when(self) -> None:
        text = flat("docs/NETWORK.md")
        self.assertIn("Nothing is sent before you answer", text)
        self.assertIn('"Windows PC" or "Mac"', text, "sign-in sends a plain device label")
        self.assertIn("not while Local-only privacy is on", text, "command search")
        self.assertIn("While Local-only privacy is on, an address on another computer is refused", text)
        self.assertIn("Reset keeps your answer.", text)
        self.assertNotIn("which is the default. In", text)

    def test_the_readme_says_the_same(self) -> None:
        text = flat("open_source/README.md")
        self.assertIn("in your browser, unless Local-only privacy is on.", text)
        self.assertIn("only if you choose to share them when the app asks or in Settings, Privacy", text)
        self.assertIn("| Usage counts | only after you choose Share, with their own switch in Settings, Privacy |", text)


if __name__ == "__main__":
    unittest.main()
