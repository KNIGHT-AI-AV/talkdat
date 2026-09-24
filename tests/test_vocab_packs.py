"""X-120: the industry packs are shipped assets -- broken JSON or duplicate
terms would surface as a support ticket, so the suite owns their shape."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

PACK_DIR = Path(__file__).resolve().parents[1] / "knight_flow" / "assets" / "vocab_packs"


class IndustryPackTests(unittest.TestCase):
    def test_all_four_packs_load_clean(self) -> None:
        slugs = sorted(p.stem for p in PACK_DIR.glob("*.json"))
        self.assertEqual(slugs, ["aviation", "legal", "medical", "military"])
        for slug in slugs:
            pack = json.loads((PACK_DIR / f"{slug}.json").read_text(encoding="utf-8"))
            terms = pack["terms"]
            self.assertGreaterEqual(len(terms), 250, slug)
            self.assertTrue(pack["description"], slug)
            self.assertEqual(len(terms), len({t.lower() for t in terms}), f"{slug} has duplicate terms")
            self.assertTrue(all(t.strip() == t and t for t in terms), f"{slug} has unstripped/empty terms")

    def test_settings_tips_asset_loads(self) -> None:
        tips = json.loads((PACK_DIR.parent / "settings_tips.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(tips), 150)
        self.assertTrue(all(entry.get("label") and entry.get("tip") for entry in tips))


if __name__ == "__main__":
    unittest.main()
