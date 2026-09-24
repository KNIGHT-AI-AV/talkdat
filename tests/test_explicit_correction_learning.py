import unittest


class ExplicitCorrectionLearningTests(unittest.TestCase):
    def test_spelling_correction_keeps_the_misheard_alias(self):
        from knight_flow.learned_words import correction_candidate, remember_correction
        pair = correction_candidate("Ask May over today.", "Ask Mayowa today.", "Correct the spelling to Mayowa.")
        self.assertEqual(pair, ("May over", "Mayowa"))
        config = {"dictionary": {"terms": []}}
        self.assertTrue(remember_correction(*pair, config))
        self.assertEqual(config["dictionary"]["terms"], [
            {"text":"Mayowa", "sounds_like":["May over"], "learned":True}
        ])
        from knight_flow.recognition_bias import recognition_terms
        self.assertEqual(recognition_terms(config), ("Mayowa",))

    def test_normal_edits_and_rewrites_are_not_spelling_evidence(self):
        from knight_flow.learned_words import correction_candidate
        for before, after, instruction in [
            ("Book Wednesday.", "Book Friday.", "Move it to Friday"),
            ("It costs 20.", "It costs 30.", "Correct the spelling"),
            ("Ask May over today.", "Ask Mayowa tomorrow.", "Correct the spelling to Mayowa"),
            ("Ask Mayowa.", "Ask Mayowa!", "Correct the spelling"),
            ("Open /may/over.", "Open /Mayowa.", "Correct the spelling"),
        ]:
            with self.subTest(instruction=instruction):
                self.assertIsNone(correction_candidate(before, after, instruction))

    def test_tombstones_and_curated_words_remain_authoritative(self):
        from knight_flow.learned_words import remember_correction, add_tombstone
        config = {"dictionary": {"terms":[{"text":"Mayowa", "sounds_like":["my name"]}]}}
        self.assertFalse(remember_correction("May over", "Mayowa", config))
        self.assertEqual(config["dictionary"]["terms"][0]["sounds_like"], ["my name"])
        config = {"dictionary": {"terms":[]}}
        add_tombstone("mayowa", config)
        self.assertFalse(remember_correction("May over", "Mayowa", config))

    def test_app_offers_only_after_a_spelling_edit_and_saves_on_accept(self):
        from knight_flow.app import TalkDatApp
        from types import SimpleNamespace
        from unittest.mock import Mock
        accepted = []
        dummy = SimpleNamespace(config={"dictionary": {"terms":[], "auto_learn_mode":"offer"}},
                                overlay=SimpleNamespace(offer_learned_word=lambda word, callback: accepted.append((word, callback))),
                                save_settings=Mock())
        TalkDatApp.offer_correction_learning(dummy, "Ask May over.", "Ask Mayowa.", "Correct the spelling to Mayowa.")
        self.assertEqual(len(accepted), 1)
        self.assertEqual(dummy.config["dictionary"]["terms"], [])
        accepted[0][1]()
        dummy.save_settings.assert_called_once()
        self.assertEqual(dummy.config["dictionary"]["terms"][0]["text"], "Mayowa")
        dummy.config["dictionary"]["auto_learn"] = False
        TalkDatApp.offer_correction_learning(dummy, "Ask Nav orb.", "Ask NavOrb.", "Correct the spelling to NavOrb.")
        self.assertEqual(len(accepted), 1)

    def test_real_fix_that_delivery_offers_only_after_successful_insertion(self):
        from tests.test_app_session_lifecycle import _app, EDIT_TARGET_A
        from knight_flow.paste import PasteReceipt
        from unittest.mock import Mock, patch
        class InlineThread:
            def __init__(self, *, target, **_kwargs):
                self.target = target
            def start(self):
                self.target()
        for success, method, expected in [(True, "clipboard", 1), (True, "copy_only", 0), (False, "clipboard_commit_unknown", 0)]:
            with self.subTest(success=success, method=method):
                token = object()
                app = _app(token)
                app._fix_that_selection = "Ask May over."
                app._fix_that_clipboard = "unchanged clipboard"
                app._fix_that_window, app._fix_that_focus_window = 91, 191
                app._fix_that_edit_target = EDIT_TARGET_A
                app._fix_that_input_generation = 21
                app.offer_correction_learning = Mock()
                receipt = PasteReceipt(success, "clipboard", method, (method,))
                with (
                    patch("knight_flow.app.threading.Thread", InlineThread),
                    patch("knight_flow.app.foreground_window_id", return_value=91),
                    patch("knight_flow.app.foreground_focus_window_id", return_value=191),
                    patch("knight_flow.app.foreground_edit_target_signature", return_value=EDIT_TARGET_A),
                    patch("knight_flow.app.foreground_input_generation", return_value=21),
                    patch("knight_flow.app.copy_selected_text", return_value=("Ask May over.", "unchanged clipboard")),
                    patch("knight_flow.llm.llm_rewrite", return_value="Ask Mayowa."),
                    patch("knight_flow.app.paste_text_with_receipt", return_value=receipt),
                    patch("knight_flow.app.restore_clipboard_if_unchanged"),
                ):
                    app.apply_fix_that("Correct the spelling to Mayowa.", delivery_token=token)
                self.assertEqual(app.offer_correction_learning.call_count, expected)
                if expected:
                    app.offer_correction_learning.assert_called_once_with("Ask May over.", "Ask Mayowa.", "Correct the spelling to Mayowa.")


if __name__ == "__main__":
    unittest.main()
