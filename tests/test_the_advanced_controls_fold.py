"""Tesler's law in Settings: the defaults carry the complexity, so the
specialist controls fold.

Audit of the real Settings windows on 2026-08-31 (DESIGN.md, Behavioral
Laws): the General page opened straight into twenty numeric pill-geometry
fields under its own caption saying "change these only if...", and the
Speech and Formatting pages showed raw JSON editors to everyone. Hick's law
says every visible control is a decision; Tesler's says the complexity is
ours to hold, not the person's. The settings builder already had the
mechanism -- a section whose title is registered in
`advanced_section_summaries` opens collapsed behind "Show details" with a
one-line summary. This pins that the three surfaces are registered and that
the two JSON editors are built INSIDE their folded sections rather than next
to them, which is the difference between folded and merely labelled.

WHAT THIS CANNOT PROVE: that a folded page reads well. The store-screenshot
harness captured the pages after the change, and they were looked at.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "knight_flow" / "overlay.py"


def _registry() -> str:
    source = OVERLAY.read_text(encoding="utf-8")
    start = source.index("advanced_section_summaries = {")
    return source[start:source.index("}", start)]


class TheAdvancedControlsFoldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = OVERLAY.read_text(encoding="utf-8")
        cls.registry = _registry()

    def test_the_three_specialist_surfaces_are_registered(self) -> None:
        for title in ("Pill", "Advanced options JSON", "Custom transforms JSON", "Voice shortcuts"):
            with self.subTest(title=title):
                self.assertRegex(
                    self.registry, rf'"{re.escape(title)}":\s*"',
                    f"{title!r} is no longer a folded section; the page shows its full "
                    "complexity to everyone again",
                )

    def test_a_registered_section_starts_collapsed(self) -> None:
        """The mechanism the registration relies on: a summary means a
        disclosure button and set_expanded(False) at build time."""
        start = self.source.index("def section(host: ttk.Frame, title: str)")
        body = self.source[start:start + 3000]
        self.assertIn("summary = advanced_section_summaries.get(title)", body)
        self.assertIn("set_expanded(False)", body)
        self.assertIn('text="Show details"', body)

    def test_the_json_editors_are_built_inside_their_folds(self) -> None:
        """A label saying 'Advanced' above an always-visible editor is not a
        fold. The editor's PARENT must be the folded section's frame."""
        self.assertIn('stt_extra_tab = section(stt_extra_holder, "Advanced options JSON")', self.source)
        self.assertIn("stt_extra_text = text_box(stt_extra_tab, 7)", self.source)
        self.assertIn('custom_tab = section(custom_holder, "Custom transforms JSON")', self.source)
        self.assertIn("custom_text = text_box(custom_tab, 8)", self.source)

    def test_the_pill_section_keeps_its_home_on_general(self) -> None:
        """Folding is not moving: the founder's IA (X-118) keeps Pill on the
        General page, and test_settings_ia pins the same."""
        self.assertIn('overlay_tab = section(general_page, "Pill")', self.source)


if __name__ == "__main__":
    unittest.main()
