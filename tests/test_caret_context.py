"""Insertion must respect real surrounding text without reading whole documents."""
from __future__ import annotations

import unittest
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch

from knight_flow.text_pipeline import process_dictation
from tests.parity_battery import local_config


class CaretFormattingTests(unittest.TestCase):
    def format(self, spoken, left, right="", **extra):
        cfg = local_config()
        cfg["_caret_context"] = {"left": left, "right": right, **extra}
        return process_dictation(spoken, cfg, local_only=True).text

    def test_continuation_is_lowercase_and_does_not_end_the_existing_sentence(self):
        self.assertEqual(self.format("and then we can send it", "I think ", " tomorrow."),
                         "and then we can send it")

    def test_a_new_sentence_still_starts_with_a_capital(self):
        self.assertEqual(self.format("we can send it tomorrow", "All done. "),
                         "We can send it tomorrow.")

    def test_acronyms_names_and_first_person_keep_their_casing(self):
        for spoken, expected in (("i can ship it tomorrow", "I can ship it tomorrow"),
                                 ("api responses are ready now", "API responses are ready now"),
                                 ("monday is the best day", "Monday is the best day"),
                                 ("mayowa has the final build", "Mayowa has the final build")):
            with self.subTest(spoken=spoken):
                self.assertEqual(self.format(spoken, "because ", " for us."), expected)

    def test_explicit_spoken_terminal_and_layout_win_over_inferred_context(self):
        self.assertEqual(self.format("we can ship it period", "I think ", " tomorrow"),
                         "we can ship it.")
        spoken = "first step new line second step"
        self.assertEqual(self.format(spoken, "start ", " here"),
                         process_dictation(spoken, local_config(), local_only=True).text)

    def test_no_context_selected_text_or_password_never_adapts(self):
        expected = "We can send it tomorrow."
        self.assertEqual(self.format("we can send it tomorrow", ""), expected)
        for flag in ("selected", "password"):
            self.assertEqual(self.format("we can send it tomorrow", "because ", " here", **{flag: True}), expected)

    def test_context_does_not_supply_words_or_change_literal_identifiers(self):
        out = self.format("https://API.example.com/MyPath", "private surrounding words ", " more private words")
        self.assertEqual(out, "https://API.example.com/MyPath")
        self.assertNotIn("private", out)

    def test_spacing_uses_adjacent_characters(self):
        from knight_flow.caret_context import join_at_caret
        self.assertEqual(join_at_caret("ready", {"left": "we are ", "right": " now"}), "ready")
        self.assertEqual(join_at_caret("ready", {"left": "we are", "right": "now"}), " ready ")
        self.assertEqual(join_at_caret("ready", {"left": "(", "right": ")"}), "ready")


class CaretReaderTests(unittest.TestCase):
    def test_busy_accessibility_does_not_delay_delivery_or_accumulate_workers(self):
        from knight_flow import caret_context as caret
        entered, release = threading.Event(), threading.Event()

        def blocked():
            entered.set()
            release.wait(2)
            return {"left": "synthetic", "right": ""}

        with patch.object(caret.sys, "platform", "win32"), patch.object(caret, "_read_windows", side_effect=blocked) as reader:
            started = time.perf_counter()
            try:
                self.assertIsNone(caret.read_caret_context(timeout=0.01))
                self.assertTrue(entered.wait(0.1))
                for _ in range(10):
                    self.assertIsNone(caret.read_caret_context(timeout=0.01))
                self.assertEqual(reader.call_count, 1)
                self.assertLess(time.perf_counter() - started, 0.3)
            finally:
                release.set()
                self.assertTrue(caret._READ_LOCK.acquire(timeout=1))
                caret._READ_LOCK.release()

    def test_secure_or_non_editable_elements_never_expose_text(self):
        from knight_flow.caret_context import _read_uia
        constants = SimpleNamespace(UIA_EditControlTypeId=1, UIA_DocumentControlTypeId=2)
        for secure, focused, control in ((True, True, 1), (False, False, 1), (False, True, 3)):
            element = Mock(CurrentIsPassword=secure, CurrentHasKeyboardFocus=focused, CurrentControlType=control)
            automation = Mock()
            automation.GetFocusedElement.return_value = element
            self.assertIsNone(_read_uia(automation, constants))
            element.GetCurrentPattern.assert_not_called()

    def test_actual_delivery_applies_context_after_formatting_without_sending_it_to_model(self):
        from tests.test_app_session_lifecycle import _app
        from knight_flow.paste import PasteReceipt
        app = _app(object())
        app.config = local_config()
        app._caret_context_reader = lambda: {"left": "I think ", "right": " tomorrow."}
        app._note_model_format_ms = lambda _ms: None
        app.play_landing_sound = lambda: None
        app.add_history = lambda _entry: None
        with patch("knight_flow.app.active_profile", return_value={}), \
             patch("knight_flow.app.apply_profile", side_effect=lambda cfg, profile: cfg), \
             patch("knight_flow.app.paste_text_with_receipt", return_value=PasteReceipt(True, "auto", "clipboard", ())) as paste, \
             patch("knight_flow.app.save_config"), \
             patch("knight_flow.app.threading.Thread"), \
             patch("knight_flow.formatting.local_finish", return_value=None) as model:
            result = app.handle_dictation("and then we can send it")
        self.assertEqual(result["text"], "and then we can send it")
        # 2026-09-22: the take itself is offered to the model; the words
        # around the caret never are.
        for call in model.call_args_list:
            self.assertNotIn("I think", call.args[0])
            self.assertNotIn("tomorrow", call.args[0])
        self.assertEqual(paste.call_args.args[0], result["text"])
        self.assertFalse(paste.call_args.kwargs["smart_leading_space"])


if __name__ == "__main__":
    unittest.main()
