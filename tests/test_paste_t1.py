"""T1's two paste-layer pieces: a paste that may never fall back to typing (a
replacement over a selection is pasted whole or not at all), and the route the
paste layer really took, recorded for the later replacement. Every system call
is patched: nothing reaches a keyboard, a clipboard or a window.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

try:
    from knight_flow.paste import (
        drop_single_sentence_period, paste_text_with_receipt, strip_messenger_trailing_period,
    )
except ModuleNotFoundError as exc:
    if exc.name != "pyautogui":
        raise
    drop_single_sentence_period = paste_text_with_receipt = strip_messenger_trailing_period = None  # type: ignore


@unittest.skipIf(paste_text_with_receipt is None, "pyautogui is not installed in this test interpreter")
class AReplacementIsNeverTyped(unittest.TestCase):
    def test_a_remote_client_refuses_instead_of_typing(self) -> None:
        with (
            patch("knight_flow.paste.foreground_is_remote_client", return_value=True),
            patch("knight_flow.paste.clipboard_text", return_value=""),
            patch("knight_flow.paste._type_text", return_value=True) as type_text,
            patch("knight_flow.paste.copy_text") as copy,
            patch("knight_flow.paste.pyautogui.hotkey") as hotkey,
        ):
            receipt = paste_text_with_receipt("Send it now.", paste_mode="auto", allow_typing=False)
        self.assertFalse(receipt.success)
        self.assertEqual(receipt.method, "typing_refused")
        type_text.assert_not_called()
        copy.assert_not_called()
        hotkey.assert_not_called()

    def test_a_rich_clipboard_refuses_instead_of_typing(self) -> None:
        with (
            patch("knight_flow.paste.snapshot_clipboard", return_value=None),
            patch("knight_flow.paste.clipboard_contains_non_text_formats", return_value=True),
            patch("knight_flow.paste.clipboard_text", return_value="an image's text"),
            patch("knight_flow.paste._type_text", return_value=True) as type_text,
            patch("knight_flow.paste.copy_text") as copy,
        ):
            receipt = paste_text_with_receipt("Send it now.", paste_mode="clipboard", restore_clipboard=True,
                                              allow_typing=False)
        self.assertEqual(receipt.method, "typing_refused")
        type_text.assert_not_called()
        copy.assert_not_called()

    def test_a_busy_clipboard_is_not_followed_by_typing(self) -> None:
        with (
            patch("knight_flow.paste.clipboard_text", return_value=""),
            patch("knight_flow.paste.copy_text", return_value=False),
            patch("knight_flow.paste.settle_modifiers"),
            patch("knight_flow.paste._type_text", return_value=True) as type_text,
            patch("knight_flow.paste.pyautogui.hotkey") as hotkey,
            patch("knight_flow.paste.pyautogui.press") as press,
        ):
            receipt = paste_text_with_receipt("Send it now.", paste_mode="clipboard", allow_typing=False)
        self.assertFalse(receipt.success)
        self.assertEqual(receipt.method, "none")
        self.assertEqual(receipt.attempts, ("clipboard", "typing_refused"))
        type_text.assert_not_called()
        hotkey.assert_not_called()
        press.assert_not_called()

    def test_typing_stays_the_fallback_everywhere_else(self) -> None:
        with (
            patch("knight_flow.paste.clipboard_text", return_value=""),
            patch("knight_flow.paste.copy_text", return_value=False),
            patch("knight_flow.paste.settle_modifiers"),
            patch("knight_flow.paste._type_text", return_value=True) as type_text,
        ):
            receipt = paste_text_with_receipt("hello", paste_mode="clipboard")
        self.assertEqual(receipt.method, "direct_type")
        type_text.assert_called_once()


@unittest.skipIf(paste_text_with_receipt is None, "pyautogui is not installed in this test interpreter")
class TheDeliveredRouteIsTheOneTaken(unittest.TestCase):
    def test_a_rich_clipboard_draft_is_recorded_as_typed(self) -> None:
        delivered: list = []
        with (
            patch("knight_flow.paste.snapshot_clipboard", return_value=None),
            patch("knight_flow.paste.clipboard_contains_non_text_formats", return_value=True),
            patch("knight_flow.paste.clipboard_text", return_value=""),
            patch("knight_flow.paste.settle_modifiers"),
            patch("knight_flow.paste._type_text", return_value=True),
        ):
            receipt = paste_text_with_receipt("draft words", paste_mode="clipboard", restore_clipboard=True,
                                              delivered=delivered)
        self.assertEqual(receipt.method, "direct_type")
        self.assertEqual(delivered, [("draft words", "type")])

    def test_the_text_as_shaped(self) -> None:
        delivered: list = []
        with (
            patch("knight_flow.paste.foreground_is_remote_client", return_value=False),
            patch("knight_flow.paste.clipboard_text", return_value=""),
            patch("knight_flow.paste.copy_text", return_value=True),
            patch("knight_flow.paste.foreground_process_name", return_value="slack.exe"),
            patch("knight_flow.paste.settle_modifiers"),
            patch("knight_flow.paste.pyautogui.hotkey"),
            patch("knight_flow.paste.time.sleep"),
        ):
            paste_text_with_receipt("Sounds good.", paste_mode="auto", delivered=delivered)
        self.assertEqual(delivered, [("Sounds good", "clipboard")])


@unittest.skipIf(drop_single_sentence_period is None, "pyautogui is not installed in this test interpreter")
class TheOneSentenceRule(unittest.TestCase):
    CASES = ("Sounds good.", "Sounds good. See you.", "Really?", "Wait...", "one\ntwo.", "Done.  ", "")

    def test_the_rule(self) -> None:
        self.assertEqual(drop_single_sentence_period("Sounds good."), "Sounds good")
        self.assertEqual(drop_single_sentence_period("Done.  "), "Done")
        for unchanged in ("Sounds good. See you.", "Really?", "Wait...", "one\ntwo.", ""):
            self.assertEqual(drop_single_sentence_period(unchanged), unchanged)

    def test_the_messenger_rule_is_unchanged(self) -> None:
        for text in self.CASES:
            with patch("knight_flow.paste.foreground_process_name", return_value="slack.exe"):
                self.assertEqual(strip_messenger_trailing_period(text), drop_single_sentence_period(text), text)
                self.assertEqual(strip_messenger_trailing_period(text, keep=True), text)
            with patch("knight_flow.paste.foreground_process_name", return_value="winword.exe"):
                self.assertEqual(strip_messenger_trailing_period(text), text)

    def test_the_foreground_is_asked_only_when_the_rule_would_change_the_text(self) -> None:
        with patch("knight_flow.paste.foreground_process_name", return_value="slack.exe") as name:
            strip_messenger_trailing_period("Sounds good. See you.")
        name.assert_not_called()


if __name__ == "__main__":
    unittest.main()
