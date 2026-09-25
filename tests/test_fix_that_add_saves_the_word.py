"""X-626 (interaction grid d1): Fix That's Add saves the word.

After a Fix That correction the app offers the corrected spelling ("Add X?").
The pop-over's Add calls its callback WITH the word, as the clipboard
learner's accept expects; Fix That's accept took no argument, so Add raised a
TypeError that the pop-over swallowed. Nothing was saved and the pop-over
closed as if it had worked.

The test calls the callback exactly as the pop-over does. Sabotage: with the
old zero-argument signature it raises, and this test goes red.
"""
from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from knight_flow.app import TalkDatApp


class FixThatAddSavesTheWordTests(unittest.TestCase):
    def test_add_remembers_the_correction_and_saves(self) -> None:
        offered: list[tuple[str, object]] = []
        app = TalkDatApp.__new__(TalkDatApp)
        app.config = {}
        app.overlay = SimpleNamespace(offer_learned_word=lambda word, callback: offered.append((word, callback)))
        app.save_settings = mock.Mock()
        with (
            mock.patch("knight_flow.learned_words.auto_learn_mode", return_value="ask"),
            mock.patch("knight_flow.learned_words.correction_candidate", return_value=("kuber netes", "Kubernetes")),
            mock.patch("knight_flow.learned_words.already_known", return_value=False),
            mock.patch("knight_flow.learned_words.tombstoned", return_value=False),
            mock.patch("knight_flow.learned_words.remember_correction", return_value=True) as remember,
        ):
            app.offer_correction_learning("kuber netes", "Kubernetes", "spell it Kubernetes")
            self.assertEqual(len(offered), 1)
            word, callback = offered[0]
            self.assertEqual(word, "Kubernetes")
            callback(word)   # exactly what the pop-over's Add does
        remember.assert_called_once_with("kuber netes", "Kubernetes", app.config)
        app.save_settings.assert_called_once()

    def test_the_pop_over_logs_a_failed_add_instead_of_swallowing_it(self) -> None:
        # X-742: Add is the word segment's action; it hands the word back, and
        # a failure in any segment action is logged, never swallowed.
        source = (Path(__file__).resolve().parents[1] / "knight_flow" / "overlay.py").read_text(encoding="utf-8")
        start = source.index("        def decide() -> None:")
        asking = source[start:source.index("        self.flag(", start)]
        self.assertIn("on_reject(word)", asking)
        self.assertNotIn("contextlib.suppress", asking)
        runner = source[source.index("    def _flag_after_fold("):source.index("    def _flag_bind(")]
        self.assertIn('log.exception("a message\'s action failed")', runner)
        self.assertNotIn("contextlib.suppress(Exception):\n                action()", runner)


if __name__ == "__main__":
    unittest.main()
