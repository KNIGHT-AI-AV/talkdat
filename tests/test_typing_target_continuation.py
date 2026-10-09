"""Mocked direct typing stops for target loss without undo or duplicate paste."""
from __future__ import annotations

import inspect
import sys
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import Mock, patch

from knight_flow.paste import PasteReceipt, paste_text_with_receipt
from tests.test_esc_while_processing_keeps_the_words import processing_app


def windows_handle_guard(mac_counterpart):
    """The app guards typing by the foreground window handle on Windows only.
    On the Mac it guards the focused AX field and refuses one it cannot read;
    each skipped test names the Mac test that covers the same behaviour."""
    return unittest.skipIf(
        sys.platform == "darwin",
        "Windows window-handle guard; Mac counterpart: "
        f"tests.test_mac_dictation_target_guard.MacDictationTargetTests.{mac_counterpart}")


class TypingContinuationTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.keys = SimpleNamespace(PAUSE=.025, press=Mock(), typewrite=Mock(), hotkey=Mock())
        self.stack.enter_context(patch("knight_flow.paste.pyautogui", self.keys))
        self.stack.enter_context(patch("knight_flow.paste.settle_modifiers"))
        self.stack.enter_context(patch("knight_flow.paste.clipboard_text", return_value=""))
        self.stack.enter_context(patch("knight_flow.paste.strip_messenger_trailing_period", side_effect=lambda text, **_kw: text))
        self.copy = self.stack.enter_context(patch("knight_flow.paste.copy_text", return_value=False))

    def guarded_paste(self, text, guard, **options):
        self.assertIn("typing_can_continue", inspect.signature(paste_text_with_receipt).parameters,
                      "direct typing needs its own target continuation guard")
        return paste_text_with_receipt(text, typing_can_continue=guard, **options)

    def test_focus_move_after_one_character_stops_without_another_insertion(self):
        focused = [111]
        typed = []

        def emit(text, **_kw):
            typed.append(text)
            focused[0] = 222

        self.keys.typewrite.side_effect = emit
        receipt = self.guarded_paste("abcd", lambda: focused[0] == 111, paste_mode="type")
        self.assertEqual(typed, ["a"])
        self.assertFalse(receipt.success)
        self.assertEqual(receipt.method, "direct_type_partial")
        self.keys.hotkey.assert_not_called()
        self.copy.assert_not_called()

    def test_focus_move_before_newline_does_not_send_enter_to_the_new_window(self):
        focused = [111]
        typed = []

        def emit(text, **_kw):
            typed.append(text)
            if text == "b":
                focused[0] = 222

        self.keys.typewrite.side_effect = emit
        receipt = self.guarded_paste("ab\ncd", lambda: focused[0] == 111, paste_mode="type")
        self.assertEqual(typed, ["a", "b"])
        self.assertEqual(receipt.method, "direct_type_partial")
        self.keys.press.assert_not_called()
        self.keys.hotkey.assert_not_called()

    def test_focus_move_on_newline_stops_before_the_next_line(self):
        focused = [111]
        typed = []
        self.keys.typewrite.side_effect = lambda text, **_kw: typed.append(text)
        self.keys.press.side_effect = lambda _key: focused.__setitem__(0, 222)
        receipt = self.guarded_paste("ab\ncd", lambda: focused[0] == 111, paste_mode="type")
        self.assertEqual(typed, ["a", "b"])
        self.keys.press.assert_called_once_with("enter")
        self.assertEqual(receipt.method, "direct_type_partial")

    def test_redo_does_not_interrupt_committed_typing_into_the_same_target(self):
        ownership = [True]
        typed = []

        def emit(text, **_kw):
            typed.append(text)
            ownership[0] = False

        self.keys.typewrite.side_effect = emit
        receipt = self.guarded_paste("abcd", lambda: True, paste_mode="type", can_deliver=lambda: ownership[0])
        self.assertEqual(typed, list("abcd"))
        self.assertTrue(receipt.success)
        self.copy.assert_not_called()

    def test_focus_move_after_the_last_character_suppresses_trailing_enter(self):
        focused = [111]
        self.keys.typewrite.side_effect = lambda _text, **_kw: focused.__setitem__(0, 222)
        receipt = self.guarded_paste("a", lambda: focused[0] == 111,
                                     paste_mode="type", send_enter=True)
        self.assertTrue(receipt.success)
        self.assertIn("enter_cancelled", receipt.attempts)
        self.keys.press.assert_not_called()
        self.keys.hotkey.assert_not_called()

    def test_clipboard_commit_does_not_send_enter_after_target_loss(self):
        focused = [111]
        self.copy.return_value = True
        self.keys.hotkey.side_effect = lambda *_keys: focused.__setitem__(0, 222)
        with patch("knight_flow.paste.time.sleep"):
            receipt = self.guarded_paste("a", lambda: focused[0] == 111,
                                         paste_mode="clipboard", send_enter=True)
        self.assertTrue(receipt.success)
        self.assertEqual(receipt.method, "clipboard")
        self.assertIn("enter_cancelled", receipt.attempts)
        self.keys.press.assert_not_called()
        self.keys.typewrite.assert_not_called()

    def test_without_a_target_guard_existing_committed_transaction_completes(self):
        ownership = [True]
        typed = []

        def emit(text, **_kw):
            typed.append(text)
            ownership[0] = False

        self.keys.typewrite.side_effect = emit
        receipt = paste_text_with_receipt("abcd", paste_mode="type", can_deliver=lambda: ownership[0])
        self.assertEqual(typed, ["abcd"])
        self.assertTrue(receipt.success)


class AppTypingGuardTests(unittest.TestCase):
    def test_partial_insertion_keeps_the_full_result_and_reports_the_prefix(self):
        app, token = processing_app()
        app.config["dictation"]["paste_mode"] = "type"
        modes = []

        def paste(text, **options):
            modes.append((text, options["paste_mode"]))
            if options["paste_mode"] == "copy_only":
                return PasteReceipt(True, "copy_only", "copy_only", ("copy_only",))
            return PasteReceipt(False, "type", "direct_type_partial",
                                ("direct_type", "direct_type_partial"))

        with (
            patch("knight_flow.app.foreground_window_id", return_value=111),
            patch("knight_flow.app.process_dictation",
                  return_value=SimpleNamespace(original="the words", text="The words.", send_enter=False)),
            patch("knight_flow.app.paste_text_with_receipt", side_effect=paste),
            patch("knight_flow.app.take_local_finish_notice", return_value=""),
        ):
            result = app.handle_dictation("the words", delivery_token=token, guided_sink=None)
        self.assertEqual(modes, [("The words.", "type"), ("The words.", "copy_only")])
        self.assertEqual(result["delivery"]["method"], "copy_only")
        self.assertEqual(app.history[0]["text"], "The words.")
        self.assertEqual(app.overlay.states[-1][1],
                         "Typing stopped. Some text may already have been inserted.")

    def delivery_guard(self, original_window):
        app, token = processing_app()
        app.config["dictation"]["paste_mode"] = "type"
        focused = [original_window]
        received = []

        def paste(_text, **options):
            received.append(options)
            return PasteReceipt(True, "type", "direct_type", ("direct_type",))

        with (
            patch("knight_flow.app.foreground_window_id", side_effect=lambda: focused[0]),
            patch("knight_flow.app.process_dictation",
                  return_value=SimpleNamespace(original="the words", text="The words.", send_enter=False)),
            patch("knight_flow.app.paste_text_with_receipt", side_effect=paste),
        ):
            app.handle_dictation("the words", delivery_token=token, guided_sink=None)
        guard = received[0].get("typing_can_continue")
        self.assertTrue(callable(guard), "the app did not provide a target continuation guard")
        return app, token, focused, guard

    @windows_handle_guard("test_known_field_guard_does_not_depend_on_the_redo_token")
    def test_guard_owns_a_known_window_but_does_not_depend_on_redo_token(self):
        app, _token, focused, guard = self.delivery_guard(111)
        app.session_token = object()
        with patch("knight_flow.app.foreground_window_id", side_effect=lambda: focused[0]):
            self.assertTrue(guard())
            focused[0] = 222
            self.assertFalse(guard())
            focused[0] = 111
            self.assertFalse(guard(), "a refused target must stay refused")

    def test_esc_still_withholds_a_committed_take_on_the_same_target(self):
        app, token, _focused, guard = self.delivery_guard(111)
        app._withheld_delivery_token = token
        with patch("knight_flow.app.foreground_window_id", return_value=111):
            self.assertFalse(guard())

    @windows_handle_guard("test_unknown_field_does_not_invent_a_target_identity")
    def test_unknown_window_does_not_invent_target_identity(self):
        _app, _token, _focused, guard = self.delivery_guard(0)
        with patch("knight_flow.app.foreground_window_id", return_value=222):
            self.assertTrue(guard())


if __name__ == "__main__":
    unittest.main()
