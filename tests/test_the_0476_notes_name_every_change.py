"""0.4.176 item 9: the CHANGELOG section, which is also the Store and release notes.

One plain line per change (BUILD-PLAN-0476.md item 9): 8e57037, 57c809b and
3e407bb, then each item of step 1 and the small fixes that ride with it, under
the heading the file's own format uses. The version itself is bumped at
GO_HEAD, so this reads the section by its heading, not by APP_VERSION.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def section() -> str:
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    found = re.search(r"^## 0\.4\.176-beta\n(.*?)(?=^## )", text, re.M | re.S)
    return found.group(1) if found else ""


class TheNotesNameEveryChangeTests(unittest.TestCase):
    def test_it_is_the_newest_section_in_the_files_own_shape(self) -> None:
        text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        headings = re.findall(r"^## (\S+)", text, re.M)
        self.assertEqual(headings[:4], ["0.4.178-beta", "0.4.177-beta", "0.4.176-beta", "0.4.175-beta"])
        body = section()
        paragraphs = [block for block in body.strip().split("\n\n") if block.strip()]
        self.assertEqual(len(paragraphs), 2, "a summary line, then the bullets")
        self.assertFalse(paragraphs[0].startswith("- "))
        bullets = paragraphs[1].splitlines()
        self.assertTrue(all(line.startswith("- ") for line in bullets), "one line per change")
        self.assertGreaterEqual(len(bullets), 12)

    def test_each_change_has_its_line(self) -> None:
        body = section()
        for words in ("asks before it sends usage counts", "Share and Don't share", "Home asks",
                      "updated from 0.4.175", "random install ID, not linked to you or your account",
                      "Settings, Privacy shows your install ID", "Reset keeps your usage counts choice",
                      "no longer opens a web search", "Ollama address on another computer",
                      '"Windows PC" or "Mac"', "say Mac in their request headers",
                      "choosing Your key on the Pill", "Perplexity web search", "kept for recovery",
                      "your dictation is not sent to us", "applies Local-only privacy right away",
                      "license agreement"):
            with self.subTest(words=words):
                self.assertIn(words, body)

    def test_it_reads_as_plain_words(self) -> None:
        body = section()
        self.assertNotIn("anonymous", body.casefold())
        for mark in ("—", "–", "“", "”", "‘", "’"):
            self.assertNotIn(mark, body)


if __name__ == "__main__":
    unittest.main()
