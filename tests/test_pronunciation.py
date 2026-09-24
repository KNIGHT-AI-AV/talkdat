from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from knight_flow import pronunciation


class SayItThreeTimesItWorksForeverTests(unittest.TestCase):
    """X-35. The clips stay local; the aliases are whatever the CURRENT
    engine hears; switching engines re-derives them from the same clips.
    Hand-typed aliases are never ours to delete."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        patcher = mock.patch.object(
            pronunciation, "clips_root", lambda config: Path(self.tmp.name)
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def _store_takes(self, term: str) -> None:
        for index in range(1, 4):
            pronunciation.store_clip({}, term, index, b"RIFFfake")

    def test_takes_store_beside_their_canonical_spelling(self) -> None:
        self._store_takes("Mayowa")
        self.assertEqual(pronunciation.stored_terms({}), ["Mayowa"])
        folder = pronunciation.clips_dir({}, "Mayowa")
        self.assertEqual(len(list(folder.glob("take-*.wav"))), 3)

    def test_harvest_keeps_only_teaching_mishearings(self) -> None:
        """A take heard correctly teaches nothing; duplicates collapse."""
        self._store_takes("Mayowa")
        heard = iter(["my yo wa", "Mayowa", "my yo wa"])
        aliases = pronunciation.harvest_aliases({}, "Mayowa", lambda _p: next(heard))
        self.assertEqual(aliases, ["my yo wa"])

    def test_engine_switch_rederives_but_never_deletes_hand_typed(self) -> None:
        self._store_takes("Mayowa")
        config = {
            "dictionary": {
                "terms": [
                    {"text": "Mayowa", "sounds_like": ["my other"], "trained_aliases": []}
                ]
            }
        }
        changed = pronunciation.refresh_term_aliases(config, lambda _p: "my yo wa")
        self.assertEqual(changed, 1)
        entry = config["dictionary"]["terms"][0]
        self.assertIn("my other", entry["sounds_like"], "hand-typed alias survived")
        self.assertIn("my yo wa", entry["sounds_like"], "fresh engine hearing added")

        # The new engine hears something different: trained aliases swap,
        # the hand-typed one still survives.
        changed = pronunciation.refresh_term_aliases(config, lambda _p: "ma yo a")
        self.assertEqual(changed, 1)
        entry = config["dictionary"]["terms"][0]
        self.assertIn("my other", entry["sounds_like"])
        self.assertIn("ma yo a", entry["sounds_like"])

    def test_a_trained_term_missing_from_the_dictionary_is_created(self) -> None:
        self._store_takes("NavOrb")
        config: dict = {}
        pronunciation.refresh_term_aliases(config, lambda _p: "nav or b")
        entries = config["dictionary"]["terms"]
        self.assertEqual(entries[0]["text"], "NavOrb")
        self.assertIn("nav or b", entries[0]["sounds_like"])

    def test_a_failed_take_is_skipped_not_fatal(self) -> None:
        self._store_takes("Mayowa")

        def flaky(path: Path) -> str:
            if path.name.endswith("2.wav"):
                raise OSError("mic gremlin")
            return "my yo wa"

        aliases = pronunciation.harvest_aliases({}, "Mayowa", flaky)
        self.assertEqual(aliases, ["my yo wa"])


if __name__ == "__main__":
    unittest.main()
