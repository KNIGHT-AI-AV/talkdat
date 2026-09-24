"""X-155: every section the settings rail offers must open a page.

Reported twice as "the color tab does nothing". The Colors page existed, was
added to the notebook, and the rail listed it -- but the dict that maps a rail
key to a page had no "colors" entry, so select_top_section looked it up, got
None, and returned. No error, no log, no visual change: a tab that looks alive
and is not.

Nothing else could catch it. The page built fine, so no build test failed. The
rail rendered fine, so no rail test failed. Only the join between them was
broken, and the join was a dict literal nobody diffed against the section list.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "knight_flow" / "overlay.py"
CONSOLE = ROOT / "knight_flow" / "ui" / "flow_console.py"


def _rail_section_keys() -> list[str]:
    """The keys FLOW_CONSOLE_SECTIONS advertises, read from source."""
    tree = ast.parse(CONSOLE.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "FLOW_CONSOLE_SECTIONS":
                return [
                    element.elts[0].value
                    for element in node.value.elts
                    if isinstance(element, ast.Tuple) and element.elts
                ]
    raise AssertionError("FLOW_CONSOLE_SECTIONS not found")


def _mapped_keys() -> list[str]:
    """The keys the top_tabs literal in overlay.py actually maps."""
    tree = ast.parse(OVERLAY.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "top_tabs":
                if isinstance(node.value, ast.Dict):
                    return [
                        key.value
                        for key in node.value.keys
                        if isinstance(key, ast.Constant)
                    ]
    raise AssertionError("top_tabs mapping not found")


class EveryRailSectionOpensAPageTests(unittest.TestCase):
    def test_no_section_is_advertised_without_a_page(self) -> None:
        sections = _rail_section_keys()
        mapped = _mapped_keys()
        self.assertTrue(sections, "the rail lists no sections at all")
        orphans = [key for key in sections if key not in mapped]
        self.assertEqual(
            orphans, [],
            "the rail offers these sections but clicking them does nothing: "
            f"{orphans}",
        )

    def test_colors_specifically_is_reachable(self) -> None:
        """Named on purpose: this is the one that shipped broken."""
        self.assertIn("colors", _rail_section_keys())
        self.assertIn("colors", _mapped_keys())

    def test_the_mapping_does_not_carry_pages_the_rail_never_offers(self) -> None:
        """The other direction: an unreachable page is dead weight."""
        sections = set(_rail_section_keys())
        strays = [key for key in _mapped_keys() if key not in sections]
        self.assertEqual(strays, [], f"pages nothing can navigate to: {strays}")


if __name__ == "__main__":
    unittest.main()
