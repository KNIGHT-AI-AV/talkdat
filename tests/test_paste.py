from __future__ import annotations

import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from knight_flow.mac_support import IS_MAC

try:
    from knight_flow.paste import (
        CHROMIUM_ENGINE_LIBRARIES,
        EDIT_MODIFIER,
        UNDO_VERIFIED_PROCESSES,
        copy_selected_text,
        copy_text,
        external_delivery_claim,
        paste_text,
        paste_text_with_receipt,
        replace_by_undo,
        restore_clipboard_if_unchanged,
        undo_is_verified_here,
    )
except ModuleNotFoundError as exc:
    if exc.name != "pyautogui":
        raise
    CHROMIUM_ENGINE_LIBRARIES = ()  # type: ignore[assignment]
    EDIT_MODIFIER = "ctrl"  # type: ignore[assignment]
    UNDO_VERIFIED_PROCESSES = ()  # type: ignore[assignment]
    copy_selected_text = None  # type: ignore[assignment]
    copy_text = None  # type: ignore[assignment]
    external_delivery_claim = None  # type: ignore[assignment]
    paste_text = None  # type: ignore[assignment]
    paste_text_with_receipt = None  # type: ignore[assignment]
    replace_by_undo = None  # type: ignore[assignment]
    restore_clipboard_if_unchanged = None  # type: ignore[assignment]
    undo_is_verified_here = None  # type: ignore[assignment]


class PasteTests(unittest.TestCase):
    @unittest.skipIf(paste_text is None, "pyautogui is not installed in this test interpreter")
    def test_auto_mode_uses_clipboard_for_normal_apps(self) -> None:
        with (
            patch("knight_flow.paste.foreground_is_remote_client", return_value=False),
            patch("knight_flow.paste.clipboard_text", return_value=""),
            patch("knight_flow.paste.copy_text", return_value=True) as copy_text,
            patch("knight_flow.paste.pyautogui.hotkey") as hotkey,
            patch("knight_flow.paste.time.sleep"),
        ):
            self.assertTrue(paste_text("hello", paste_mode="auto"))
            copy_text.assert_called_with("hello")
            hotkey.assert_called_with(EDIT_MODIFIER, "v")

    @unittest.skipIf(paste_text is None, "pyautogui is not installed in this test interpreter")
    def test_auto_mode_types_into_remote_clients(self) -> None:
        with (
            patch("knight_flow.paste.foreground_is_remote_client", return_value=True),
            patch("knight_flow.paste.clipboard_text", return_value=""),
            patch("knight_flow.paste._type_text", return_value=True) as type_text,
            patch("knight_flow.paste.copy_text") as copy_text,
        ):
            self.assertTrue(paste_text("hello", paste_mode="auto", typing_interval_ms=4))
            type_text.assert_called_with("hello", interval_ms=4)
            copy_text.assert_not_called()

    @unittest.skipIf(paste_text_with_receipt is None, "pyautogui is not installed in this test interpreter")
    def test_busy_clipboard_falls_back_to_direct_typing_with_a_receipt(self) -> None:
        with (
            patch("knight_flow.paste.clipboard_text", return_value=""),
            patch("knight_flow.paste.copy_text", return_value=False),
            patch("knight_flow.paste._type_text", return_value=True) as type_text,
        ):
            receipt = paste_text_with_receipt("hello", paste_mode="clipboard", typing_interval_ms=3)

        self.assertTrue(receipt.success)
        self.assertEqual(receipt.method, "direct_type")
        self.assertTrue(receipt.fallback_used)
        self.assertEqual(receipt.attempts, ("clipboard", "direct_type"))
        self.assertEqual(receipt.visible_label(), "Inserted by direct typing after automatic fallback")
        type_text.assert_called_once_with("hello", interval_ms=3)

    @unittest.skipIf(paste_text_with_receipt is None, "pyautogui is not installed in this test interpreter")
    def test_direct_typing_failure_falls_back_to_verified_clipboard_route(self) -> None:
        with (
            patch("knight_flow.paste.foreground_is_remote_client", return_value=True),
            patch("knight_flow.paste.clipboard_text", return_value=""),
            patch("knight_flow.paste._type_text", return_value=False),
            patch("knight_flow.paste.copy_text", return_value=True),
            patch("knight_flow.paste.pyautogui.hotkey") as hotkey,
            patch("knight_flow.paste.time.sleep"),
        ):
            receipt = paste_text_with_receipt("hello", paste_mode="auto")

        self.assertTrue(receipt.success)
        self.assertEqual(receipt.method, "clipboard")
        self.assertTrue(receipt.fallback_used)
        self.assertEqual(receipt.attempts, ("direct_type", "clipboard"))
        hotkey.assert_called_once_with(EDIT_MODIFIER, "v")

    @unittest.skipIf(paste_text_with_receipt is None, "pyautogui is not installed in this test interpreter")
    def test_receipt_reports_total_insertion_failure_without_transcript_content(self) -> None:
        with (
            patch("knight_flow.paste.clipboard_text", return_value="private dictated words"),
            patch("knight_flow.paste.copy_text", return_value=False),
            patch("knight_flow.paste._type_text", return_value=False),
        ):
            receipt = paste_text_with_receipt("private dictated words", paste_mode="clipboard")

        self.assertFalse(receipt.success)
        self.assertEqual(receipt.method, "none")
        self.assertNotIn("private dictated words", str(receipt.as_dict()))

    @unittest.skipIf(paste_text_with_receipt is None, "pyautogui is not installed in this test interpreter")
    def test_enter_failure_does_not_duplicate_text_through_another_route(self) -> None:
        with (
            patch("knight_flow.paste.clipboard_text", return_value=""),
            patch("knight_flow.paste.copy_text", return_value=True),
            patch("knight_flow.paste.pyautogui.hotkey") as hotkey,
            patch("knight_flow.paste.pyautogui.press", side_effect=RuntimeError("enter blocked")),
            patch("knight_flow.paste._type_text") as type_text,
            patch("knight_flow.paste.time.sleep"),
        ):
            receipt = paste_text_with_receipt("hello", paste_mode="clipboard", send_enter=True)

        self.assertTrue(receipt.success)
        self.assertEqual(receipt.attempts, ("clipboard", "enter_failed"))
        self.assertFalse(receipt.fallback_used)
        hotkey.assert_called_once_with(EDIT_MODIFIER, "v")
        type_text.assert_not_called()

    @unittest.skipIf(paste_text_with_receipt is None, "pyautogui is not installed in this test interpreter")
    def test_cancel_during_clipboard_wait_blocks_the_old_ctrl_v(self) -> None:
        current = True
        clipboard_staged = threading.Event()
        continue_delivery = threading.Event()
        result: dict[str, object] = {}

        def blocked_sleep(_seconds: float) -> None:
            clipboard_staged.set()
            self.assertTrue(continue_delivery.wait(2.0))

        with (
            patch("knight_flow.paste.clipboard_text", return_value="original clipboard"),
            patch("knight_flow.paste.copy_text", return_value=True),
            patch("knight_flow.paste.restore_clipboard_if_unchanged") as restore,
            patch("knight_flow.paste.pyautogui.hotkey") as hotkey,
            patch("knight_flow.paste.time.sleep", side_effect=blocked_sleep),
        ):
            worker = threading.Thread(
                target=lambda: result.update(
                    receipt=paste_text_with_receipt(
                        "old dictated result",
                        paste_mode="clipboard",
                        can_deliver=lambda: current,
                    )
                )
            )
            worker.start()
            self.assertTrue(clipboard_staged.wait(2.0))
            current = False
            continue_delivery.set()
            worker.join(2.0)

        self.assertFalse(worker.is_alive())
        receipt = result["receipt"]
        self.assertFalse(receipt.success)
        self.assertEqual(receipt.method, "cancelled")
        hotkey.assert_not_called()
        restore.assert_called_once_with("old dictated result", "original clipboard")

    @unittest.skipIf(paste_text_with_receipt is None, "pyautogui is not installed in this test interpreter")
    def test_cancel_after_direct_typing_commits_finishes_without_a_stale_fragment(self) -> None:
        current = True
        emitted: list[str] = []

        def type_transaction(text: str, **_options: object) -> None:
            nonlocal current
            emitted.append(text)
            current = False

        with (
            patch("knight_flow.paste.clipboard_text", return_value=""),
            patch("knight_flow.paste.pyautogui.typewrite", side_effect=type_transaction),
            patch("knight_flow.paste.pyautogui.press") as press,
        ):
            receipt = paste_text_with_receipt(
                "abcd",
                paste_mode="type",
                can_deliver=lambda: current,
            )

        self.assertEqual(emitted, ["abcd"])
        self.assertTrue(receipt.success)
        self.assertEqual(receipt.method, "direct_type")
        press.assert_not_called()

    @unittest.skipIf(paste_text_with_receipt is None, "pyautogui is not installed in this test interpreter")
    def test_cancel_during_copy_only_restores_the_previous_clipboard(self) -> None:
        current = True

        def delayed_copy(_text: str) -> bool:
            nonlocal current
            current = False
            return True

        with (
            patch("knight_flow.paste.clipboard_text", return_value="previous clipboard"),
            patch("knight_flow.paste.copy_text", side_effect=delayed_copy),
            patch("knight_flow.paste.restore_clipboard_if_unchanged") as restore,
        ):
            receipt = paste_text_with_receipt(
                "old result",
                paste_mode="copy_only",
                can_deliver=lambda: current,
            )

        self.assertFalse(receipt.success)
        self.assertEqual(receipt.method, "cancelled")
        restore.assert_called_once_with("old result", "previous clipboard")

    @unittest.skipIf(paste_text_with_receipt is None, "pyautogui is not installed in this test interpreter")
    def test_back_to_back_direct_typing_transactions_never_interleave(self) -> None:
        first_entered = threading.Event()
        release_first = threading.Event()
        second_worker_started = threading.Event()
        second_entered = threading.Event()
        calls: list[str] = []
        receipts: list[object] = []

        def blocked_type(text: str, **_options: object) -> bool:
            calls.append(text)
            if text == "old paragraph":
                first_entered.set()
                self.assertTrue(release_first.wait(2.0))
            else:
                second_entered.set()
            return True

        def deliver_second() -> None:
            second_worker_started.set()
            receipts.append(paste_text_with_receipt("new result", paste_mode="type"))

        with (
            patch("knight_flow.paste.clipboard_text", return_value=""),
            patch("knight_flow.paste._type_text", side_effect=blocked_type),
        ):
            first = threading.Thread(
                target=lambda: receipts.append(
                    paste_text_with_receipt("old paragraph", paste_mode="type")
                )
            )
            second = threading.Thread(target=deliver_second)
            first.start()
            self.assertTrue(first_entered.wait(2.0))
            second.start()
            self.assertTrue(second_worker_started.wait(2.0))
            self.assertFalse(
                second_entered.wait(0.15),
                "a replacement delivery entered while the committed old transaction was still typing",
            )
            release_first.set()
            first.join(2.0)
            second.join(2.0)

        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(calls, ["old paragraph", "new result"])
        self.assertEqual(len(receipts), 2)
        self.assertTrue(all(receipt.success for receipt in receipts))

    @unittest.skipIf(paste_text_with_receipt is None, "pyautogui is not installed in this test interpreter")
    def test_partial_direct_typing_failure_never_pastes_the_full_text_after_the_prefix(self) -> None:
        emitted: list[str] = []

        def fail_after_prefix(text: str, **_options: object) -> None:
            emitted.append(text[:2])
            raise RuntimeError("remote client stopped accepting input")

        with (
            patch("knight_flow.paste.clipboard_text", return_value=""),
            patch("knight_flow.paste.pyautogui.typewrite", side_effect=fail_after_prefix),
            patch("knight_flow.paste.pyautogui.hotkey") as hotkey,
            patch("knight_flow.paste.copy_text") as copy,
        ):
            receipt = paste_text_with_receipt("abcdef", paste_mode="type")

        self.assertEqual(emitted, ["ab"])
        self.assertFalse(receipt.success)
        self.assertEqual(receipt.method, "direct_type_partial")
        hotkey.assert_not_called()
        copy.assert_not_called()

    @unittest.skipIf(restore_clipboard_if_unchanged is None, "pyautogui is not installed in this test interpreter")
    def test_clipboard_restore_preserves_a_newer_user_copy(self) -> None:
        with (
            patch("knight_flow.paste._CLIPBOARD_OWNERSHIP", None),
            patch("knight_flow.paste._restore_windows_clipboard_text_if_owned") as restore,
        ):
            restored = restore_clipboard_if_unchanged("dictated text", "old clipboard")

        self.assertFalse(restored)
        restore.assert_not_called()

    @unittest.skipIf(restore_clipboard_if_unchanged is None, "pyautogui is not installed in this test interpreter")
    def test_clipboard_restore_replaces_only_the_inserted_value(self) -> None:
        with (
            patch("knight_flow.paste._CLIPBOARD_OWNERSHIP", ("dictated text", 41)),
            patch(
                "knight_flow.paste._restore_windows_clipboard_text_if_owned",
                return_value=True,
            ) as restore,
            patch("knight_flow.paste.clipboard_sequence_number", return_value=42),
        ):
            restored = restore_clipboard_if_unchanged("dictated text", "old clipboard")

        self.assertTrue(restored)
        restore.assert_called_once_with("dictated text", "old clipboard", 41)

    def test_clipboard_restore_refuses_a_newer_sequence_even_if_text_was_just_checked(self) -> None:
        with (
            patch("knight_flow.paste._CLIPBOARD_OWNERSHIP", ("dictated text", 41)),
            patch(
                "knight_flow.paste._restore_windows_clipboard_text_if_owned",
                return_value=False,
            ) as restore,
        ):
            restored = restore_clipboard_if_unchanged("dictated text", "old clipboard")

        self.assertFalse(restored)
        restore.assert_called_once_with("dictated text", "old clipboard", 41)

    @unittest.skipIf(IS_MAC, "patches ctypes.windll, which exists only on Windows")
    def test_atomic_restore_rechecks_sequence_after_opening_the_clipboard(self) -> None:
        from unittest.mock import MagicMock

        from knight_flow.paste import _restore_windows_clipboard_text_if_owned

        user32 = SimpleNamespace(
            OpenClipboard=MagicMock(return_value=1),
            CloseClipboard=MagicMock(return_value=1),
            EmptyClipboard=MagicMock(return_value=1),
            GetClipboardData=MagicMock(return_value=1),
            SetClipboardData=MagicMock(return_value=1),
        )
        kernel32 = SimpleNamespace(
            GlobalAlloc=MagicMock(return_value=1),
            GlobalLock=MagicMock(return_value=1),
            GlobalUnlock=MagicMock(return_value=1),
            GlobalFree=MagicMock(return_value=0),
        )
        with (
            patch("knight_flow.paste.os.name", "nt"),
            patch(
                "knight_flow.paste.ctypes.windll",
                SimpleNamespace(user32=user32, kernel32=kernel32),
            ),
            patch(
                "knight_flow.paste.clipboard_sequence_number",
                side_effect=[41, 42],
            ),
        ):
            restored = _restore_windows_clipboard_text_if_owned(
                "dictated text",
                "old clipboard",
                41,
            )

        self.assertFalse(restored)
        user32.OpenClipboard.assert_called_once_with(None)
        user32.EmptyClipboard.assert_not_called()
        user32.SetClipboardData.assert_not_called()
        user32.CloseClipboard.assert_called_once_with()


@unittest.skipIf(paste_text_with_receipt is None, "pyautogui is not installed")
class ExternalDeliveryAtomicityTests(unittest.TestCase):
    def test_a_new_user_copy_after_our_write_is_never_reclaimed_by_retry(self) -> None:
        with (
            patch("knight_flow.paste.pyperclip.copy") as write,
            patch("knight_flow.paste.clipboard_text", return_value="NEW USER COPY"),
            patch("knight_flow.paste.time.sleep"),
        ):
            self.assertFalse(copy_text("dictated result"))

        write.assert_called_once_with("dictated result")

    def test_selection_capture_fails_closed_when_the_sentinel_cannot_be_staged(self) -> None:
        with (
            patch("knight_flow.paste.clipboard_contains_non_text_formats", return_value=False),
            patch("knight_flow.paste.clipboard_text", return_value="private prior clipboard"),
            patch("knight_flow.paste.copy_text", return_value=False),
            patch("knight_flow.paste.pyautogui.hotkey") as hotkey,
        ):
            selected, previous = copy_selected_text()

        self.assertEqual(selected, "")
        self.assertEqual(previous, "private prior clipboard")
        hotkey.assert_not_called()

    def test_selection_capture_restores_only_its_sentinel_after_ctrl_c_failure(self) -> None:
        with (
            patch("knight_flow.paste.clipboard_contains_non_text_formats", return_value=False),
            patch(
                "knight_flow.paste.clipboard_text",
                side_effect=["private prior clipboard", "sentinel still staged"],
            ),
            patch("knight_flow.paste.copy_text", return_value=True),
            patch("knight_flow.paste.pyautogui.hotkey", side_effect=RuntimeError("copy blocked")),
            patch("knight_flow.paste.restore_clipboard_if_unchanged") as restore,
        ):
            selected, previous = copy_selected_text()

        self.assertEqual((selected, previous), ("", "private prior clipboard"))
        restore.assert_called_once()

    def test_selection_capture_cannot_interleave_with_a_competing_clipboard_copy(self) -> None:
        clipboard = {"value": "private prior clipboard"}
        capture_started = threading.Event()
        release_capture = threading.Event()
        competing_write_started = threading.Event()
        result: list[tuple[str, str]] = []

        def write_clipboard(value: str) -> None:
            if value == "competing copy":
                competing_write_started.set()
            clipboard["value"] = value

        def copy_selection(*keys: str) -> None:
            self.assertEqual(keys, (EDIT_MODIFIER, "c"))
            capture_started.set()
            self.assertTrue(release_capture.wait(2.0))
            clipboard["value"] = "selected words"

        with (
            patch("knight_flow.paste.clipboard_contains_non_text_formats", return_value=False),
            patch("knight_flow.paste.clipboard_text", side_effect=lambda: clipboard["value"]),
            patch("knight_flow.paste.pyperclip.copy", side_effect=write_clipboard),
            patch("knight_flow.paste.pyautogui.hotkey", side_effect=copy_selection),
        ):
            selector = threading.Thread(
                target=lambda: result.append(copy_selected_text(timeout=0)),
            )
            selector.start()
            self.assertTrue(capture_started.wait(2.0))

            copier = threading.Thread(target=lambda: copy_text("competing copy"))
            copier.start()
            self.assertFalse(competing_write_started.wait(0.12))

            release_capture.set()
            selector.join(2.0)
            copier.join(2.0)

        self.assertFalse(selector.is_alive())
        self.assertFalse(copier.is_alive())
        self.assertEqual(result, [("selected words", "private prior clipboard")])
        self.assertTrue(competing_write_started.is_set())

    def test_selection_capture_cannot_interleave_with_a_competing_paste(self) -> None:
        clipboard = {"value": "private prior clipboard"}
        capture_started = threading.Event()
        release_capture = threading.Event()
        typing_started = threading.Event()
        result: list[tuple[str, str]] = []

        def write_clipboard(value: str) -> None:
            clipboard["value"] = value

        def copy_selection(*keys: str) -> None:
            self.assertEqual(keys, (EDIT_MODIFIER, "c"))
            capture_started.set()
            self.assertTrue(release_capture.wait(2.0))
            clipboard["value"] = "selected words"

        def type_text(_text: str, **_options: object) -> bool:
            typing_started.set()
            return True

        with (
            patch("knight_flow.paste.clipboard_contains_non_text_formats", return_value=False),
            patch("knight_flow.paste.clipboard_text", side_effect=lambda: clipboard["value"]),
            patch("knight_flow.paste.pyperclip.copy", side_effect=write_clipboard),
            patch("knight_flow.paste.pyautogui.hotkey", side_effect=copy_selection),
            patch("knight_flow.paste._type_text", side_effect=type_text),
        ):
            selector = threading.Thread(
                target=lambda: result.append(copy_selected_text(timeout=0)),
            )
            selector.start()
            self.assertTrue(capture_started.wait(2.0))

            paster = threading.Thread(
                target=lambda: paste_text_with_receipt("pasted words", paste_mode="type"),
            )
            paster.start()
            self.assertFalse(typing_started.wait(0.12))

            release_capture.set()
            selector.join(2.0)
            paster.join(2.0)

        self.assertFalse(selector.is_alive())
        self.assertFalse(paster.is_alive())
        self.assertEqual(result, [("selected words", "private prior clipboard")])
        self.assertTrue(typing_started.is_set())

    def test_rich_clipboard_selection_capture_fails_safe_without_flattening_formats(self) -> None:
        with (
            patch("knight_flow.paste.clipboard_text", return_value="plain fallback for rich data"),
            patch("knight_flow.paste.clipboard_contains_non_text_formats", return_value=True),
            patch("knight_flow.paste.copy_text") as copy,
            patch("knight_flow.paste.pyautogui.hotkey") as hotkey,
            patch("knight_flow.paste.restore_clipboard_if_unchanged") as restore,
        ):
            selected, previous = copy_selected_text()

        self.assertEqual(selected, "")
        self.assertEqual(previous, "plain fallback for rich data")
        copy.assert_not_called()
        hotkey.assert_not_called()
        restore.assert_not_called()

    def test_clipboard_commit_unknown_never_direct_types_a_duplicate(self) -> None:
        # macOS has no Insert key, so the shift_insert route sends the Command chord there.
        for mode, chord in (
            ("clipboard", (EDIT_MODIFIER, "v")),
            ("shift_insert", (EDIT_MODIFIER, "v") if IS_MAC else ("shift", "insert")),
        ):
            emitted: list[str] = []

            def commit_then_raise(*keys: str) -> None:
                if tuple(keys) == chord:
                    emitted.append("abcdef")
                    raise RuntimeError("key release failed after commit")

            with (
                self.subTest(mode=mode),
                patch("knight_flow.paste.clipboard_text", return_value="old clipboard"),
                patch("knight_flow.paste.copy_text", return_value=True),
                patch("knight_flow.paste.pyautogui.hotkey", side_effect=commit_then_raise),
                patch("knight_flow.paste._type_text") as direct_type,
                patch("knight_flow.paste.time.sleep"),
            ):
                receipt = paste_text_with_receipt("abcdef", paste_mode=mode)

            self.assertEqual(emitted, ["abcdef"])
            self.assertFalse(receipt.success)
            self.assertEqual(receipt.method, "clipboard_commit_unknown")
            direct_type.assert_not_called()

    def test_rich_clipboard_is_never_flattened_by_an_automatic_paste(self) -> None:
        # X-406: with no trustworthy snapshot (a metafile, or a clipboard
        # that would not open) the old protection still applies: type.
        with (
            patch("knight_flow.paste.snapshot_clipboard", return_value=None),
            patch("knight_flow.paste.clipboard_contains_non_text_formats", return_value=True),
            patch("knight_flow.paste.clipboard_text", return_value="plain fallback for an image"),
            patch("knight_flow.paste._type_text", return_value=False),
            patch("knight_flow.paste.copy_text") as copy,
        ):
            receipt = paste_text_with_receipt(
                "dictated text",
                paste_mode="auto",
                restore_clipboard=True,
            )

        self.assertFalse(receipt.success)
        self.assertEqual(receipt.method, "protected_rich_clipboard")
        copy.assert_not_called()

    def test_undo_stages_the_replacement_before_touching_the_document(self) -> None:
        with (
            patch("knight_flow.paste.clipboard_text", return_value="old clipboard"),
            patch("knight_flow.paste.copy_text", return_value=False),
            patch("knight_flow.paste.pyautogui.hotkey") as hotkey,
        ):
            outcome = replace_by_undo("Improved result")

        self.assertFalse(outcome.success)
        self.assertFalse(outcome.undo_attempted)
        hotkey.assert_not_called()

    def test_failure_after_undo_is_reported_as_committed_and_never_backspaces(self) -> None:
        calls: list[tuple[str, ...]] = []

        def fail_paste(*keys: str) -> None:
            calls.append(tuple(keys))
            if tuple(keys) == (EDIT_MODIFIER, "v"):
                raise RuntimeError("paste failed after undo")

        with (
            patch("knight_flow.paste.clipboard_text", return_value="old clipboard"),
            patch("knight_flow.paste.copy_text", return_value=True),
            patch("knight_flow.paste.pyautogui.hotkey", side_effect=fail_paste),
            patch("knight_flow.paste.pyautogui.press") as press,
            patch("knight_flow.paste.time.sleep"),
        ):
            outcome = replace_by_undo("Improved result")

        self.assertFalse(outcome.success)
        self.assertTrue(outcome.undo_attempted)
        self.assertEqual(calls, [(EDIT_MODIFIER, "z"), (EDIT_MODIFIER, "v")])
        press.assert_not_called()

    def test_undo_replacement_waits_for_the_shared_output_channel(self) -> None:
        entered = threading.Event()
        finished = threading.Event()

        def hotkey(*_keys: str) -> None:
            entered.set()

        with (
            patch("knight_flow.paste.clipboard_text", return_value="old clipboard"),
            patch("knight_flow.paste.copy_text", return_value=True),
            patch("knight_flow.paste.pyautogui.hotkey", side_effect=hotkey),
            patch("knight_flow.paste.time.sleep"),
        ):
            with external_delivery_claim():
                worker = threading.Thread(
                    target=lambda: (replace_by_undo("Improved result"), finished.set())
                )
                worker.start()
                self.assertFalse(entered.wait(0.12))
            worker.join(2.0)

        self.assertFalse(worker.is_alive())
        self.assertTrue(entered.is_set())
        self.assertTrue(finished.is_set())


if __name__ == "__main__":
    unittest.main()


@unittest.skipIf(undo_is_verified_here is None, "pyautogui is not installed")
class TheUndoAllowlistOnlyNamesWhatWasMeasuredTests(unittest.TestCase):
    """Instant correction is on by default in these applications and nowhere else.

    Each entry is an engine rather than a program: Notepad is a Win32 edit
    control and Edge is Chromium, and everything sharing those engines groups a
    paste into one undo step identically. Verified by pasting, correcting, then
    reading the field back through the clipboard -- 156ms in Notepad, 158-227ms
    in an Edge textarea, flat at 120, 400 and 900 characters, no duplication.

    The asymmetry is the whole design and is worth stating plainly: being
    missing costs a slower correction, and being wrongly present costs somebody
    their sentence twice over. So the bar for adding a name is a measurement or
    the same engine, not a reasonable guess about how the editor behaves.

    Word, WordPad and VS Code are deliberately absent. Three attempts to test
    them failed for three unrelated reasons -- a foreground lock, a STATIC
    parent that swallowed every keystroke, and WinError 740 -- so they are
    genuinely unknown rather than known-bad, and unknown means the slow path.
    """

    def focused(self, path: str):
        return patch("knight_flow.paste.foreground_process_path", return_value=path)

    @unittest.skipIf(IS_MAC, "the measured engines are Windows executables")
    def test_the_two_engines_that_were_actually_measured_are_on_it(self) -> None:
        for path in (
            "C:\\Windows\\System32\\notepad.exe",
            "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
        ):
            with self.subTest(path=path), self.focused(path):
                self.assertTrue(undo_is_verified_here())

    @unittest.skipIf(not IS_MAC, "describes the macOS allowlist")
    def test_nothing_on_macos_is_on_the_allowlist_yet(self) -> None:
        """No Mac application has had its undo grouping measured, so every one
        of them takes the slow path. The moment somebody measures TextEdit or
        Safari the way Notepad and Edge were measured, they can be added and
        this test replaced -- until then, guessing costs somebody their
        sentence twice."""
        for path in ("/Applications/Safari.app", "/System/Applications/TextEdit.app", ""):
            with self.subTest(path=path), self.focused(path):
                self.assertFalse(undo_is_verified_here())

    def test_the_untested_editors_are_not(self) -> None:
        """These are the ones a future session will be tempted to add. Adding
        one without measuring it is how someone's paragraph appears twice."""
        for path in (
            "C:\\Program Files\\Microsoft Office\\root\\Office16\\WINWORD.EXE",
            "C:\\Program Files\\Windows NT\\Accessories\\wordpad.exe",
            "C:\\Users\\x\\AppData\\Local\\Programs\\Microsoft VS Code\\Code.exe",
            "C:\\Users\\x\\AppData\\Local\\Programs\\cursor\\Cursor.exe",
            "C:\\Program Files\\Notepad++\\notepad++.exe",
        ):
            with self.subTest(path=path), self.focused(path):
                self.assertFalse(
                    undo_is_verified_here(),
                    f"{path} has never been measured; it must take the slow path",
                )

    def test_an_unknown_or_unreadable_foreground_takes_the_slow_path(self) -> None:
        """foreground_process_path returns an empty string on any failure and
        on non-Windows, and that must not match anything by accident."""
        for path in ("", "C:\\somewhere\\nobody-has-heard-of-this.exe"):
            with self.subTest(path=path), self.focused(path):
                self.assertFalse(undo_is_verified_here())

    def test_notepad_plus_plus_is_not_caught_by_the_notepad_marker(self) -> None:
        """The names are matched exactly for this reason. A substring match
        reads as harmless, and "notepad" also matches Notepad++, a Scintilla
        editor that shares nothing with the control that was measured."""
        self.assertNotIn("notepad++.exe", UNDO_VERIFIED_PROCESSES)
        with self.focused("C:\\Program Files\\Notepad++\\notepad++.exe"):
            self.assertFalse(undo_is_verified_here())

    def test_every_marker_is_a_lowercase_executable_name(self) -> None:
        """The name is lowercased before comparison, so an uppercase marker
        would silently never match and the entry would do nothing."""
        for marker in UNDO_VERIFIED_PROCESSES:
            with self.subTest(marker=marker):
                self.assertEqual(marker, marker.lower())
                self.assertTrue(marker.endswith(".exe"), "matched against a basename")


@unittest.skipIf(undo_is_verified_here is None, "pyautogui is not installed")
@unittest.skipIf(IS_MAC, "engine detection reads the .dll layout beside a Windows .exe")
class ChromiumForksAreRecognisedWithoutBeingNamedTests(unittest.TestCase):
    """A hardcoded browser list was already wrong on the machine that ships it.

    The list held the browsers a developer thinks of. The machine this is built
    on runs none of them -- its browser is Comet, a Perplexity fork that did
    not exist a year ago -- so the feature would have stayed off in the one
    application its owner actually dictates into, and nothing would have said
    so. Arc, Zen and Dia are the same problem waiting.

    Asking the executable beats guessing its name. A Chromium browser ships the
    engine beside itself or in a version folder, and an Electron application --
    which bundles Chromium but wraps it in a custom editor with its own undo
    stack -- ships neither. That is exactly the line the list draws by hand
    when it excludes Slack and Discord, so it is the right thing to test.
    """

    def install(self, layout: dict) -> str:
        """A fake install tree: {relative folder: [file names]}."""
        import os
        import shutil
        import tempfile

        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        for folder, names in layout.items():
            target = os.path.join(root, folder) if folder else root
            os.makedirs(target, exist_ok=True)
            for name in names:
                open(os.path.join(target, name), "w").close()
        return root

    def verified(self, exe_path: str) -> bool:
        from knight_flow.paste import _chromium_browsers

        _chromium_browsers.clear()
        with patch("knight_flow.paste.foreground_process_path", return_value=exe_path):
            return undo_is_verified_here()

    def test_an_engine_dll_beside_the_executable_is_enough(self) -> None:
        """Chrome, Brave and Comet all lay out this way."""
        import os

        root = self.install({"": ["chrome.dll", "someforkbrowser.exe"]})
        self.assertTrue(self.verified(os.path.join(root, "someforkbrowser.exe")))

    def test_an_engine_dll_in_a_version_folder_is_enough(self) -> None:
        """Edge lays out this way, with msedge.dll one level down."""
        import os

        root = self.install({"": ["futureedge.exe"], "151.0.4129.59": ["msedge.dll"]})
        self.assertTrue(self.verified(os.path.join(root, "futureedge.exe")))

    def test_an_electron_application_is_not_a_browser(self) -> None:
        """The distinction the whole feature rests on. Checked against a real
        Electron install: resources/, ffmpeg.dll, libGLESv2.dll, no engine."""
        import os

        root = self.install(
            {"": ["ffmpeg.dll", "libGLESv2.dll", "chatapp.exe"], "resources": ["app.asar"]}
        )
        self.assertFalse(
            self.verified(os.path.join(root, "chatapp.exe")),
            "an Electron app ships a rich composer with its own undo stack",
        )

    def test_an_ordinary_application_is_not_a_browser(self) -> None:
        import os

        root = self.install({"": ["something.exe", "helper.dll"]})
        self.assertFalse(self.verified(os.path.join(root, "something.exe")))

    def test_a_directory_it_cannot_read_is_not_evidence(self) -> None:
        """Failing open would enable the destructive path on a guess."""
        self.assertFalse(self.verified("Z:\\not\\a\\real\\drive\\browser.exe"))

    def test_the_answer_is_cached_per_executable(self) -> None:
        """One stat per application per run, not one per dictation. The same
        fix as the PID cache in Work Mode Guardian, for the same reason."""
        import os

        from knight_flow.paste import _chromium_browsers, _looks_like_a_chromium_browser

        root = self.install({"": ["chrome.dll", "forkbrowser.exe"]})
        exe = os.path.join(root, "forkbrowser.exe")
        _chromium_browsers.clear()
        self.assertTrue(_looks_like_a_chromium_browser(exe))
        with patch("os.path.exists", side_effect=AssertionError("asked the disk twice")):
            self.assertTrue(_looks_like_a_chromium_browser(exe))

    def test_both_engine_names_are_checked(self) -> None:
        """Chrome-family and Edge use different DLL names, and dropping either
        silently disables the fallback for half the browsers there are."""
        self.assertEqual(set(CHROMIUM_ENGINE_LIBRARIES), {"chrome.dll", "msedge.dll"})


class RichClipboardSnapshotTests(unittest.TestCase):
    """X-406: an image on the clipboard used to force key-by-key typing, which
    took 10.5 seconds for a 1,072-character dictation. The snapshot keeps the
    image and lets the paste go through the clipboard."""

    @unittest.skipIf(paste_text_with_receipt is None, "pyautogui is not installed in this test interpreter")
    def test_a_snapshot_lets_the_paste_use_the_clipboard_and_restores_it(self) -> None:
        snapshot = [(8, b"dib bytes"), (49_161, b"<html>rich</html>")]
        with (
            patch("knight_flow.paste.clipboard_contains_non_text_formats", return_value=True),
            patch("knight_flow.paste.snapshot_clipboard", return_value=snapshot),
            patch("knight_flow.paste.clipboard_text", return_value="plain fallback for an image"),
            patch("knight_flow.paste.copy_text", return_value=True) as copy,
            patch("knight_flow.paste.pyautogui.hotkey") as hotkey,
            patch("knight_flow.paste._type_text") as direct_type,
            patch("knight_flow.paste.restore_clipboard_snapshot", return_value=True) as restore_snapshot,
            patch("knight_flow.paste.restore_clipboard_if_unchanged") as restore_text,
            patch("knight_flow.paste.time.sleep"),
        ):
            receipt = paste_text_with_receipt("dictated text", paste_mode="clipboard", restore_clipboard=True)

        self.assertTrue(receipt.success)
        self.assertEqual(receipt.method, "clipboard")
        copy.assert_called_once_with("dictated text")
        # The paste chord is Ctrl+V here and Command+V on the Mac branch.
        from knight_flow import paste as paste_module

        hotkey.assert_called_with(getattr(paste_module, "EDIT_MODIFIER", "ctrl"), "v")
        direct_type.assert_not_called()
        restore_snapshot.assert_called_once_with(snapshot, "dictated text")
        restore_text.assert_not_called()

    @unittest.skipIf(paste_text_with_receipt is None, "pyautogui is not installed in this test interpreter")
    def test_a_snapshot_is_only_taken_when_the_clipboard_is_rich_and_restore_is_wanted(self) -> None:
        with (
            patch("knight_flow.paste.clipboard_contains_non_text_formats", return_value=False),
            patch("knight_flow.paste.snapshot_clipboard") as snapshot,
            patch("knight_flow.paste.clipboard_text", return_value=""),
            patch("knight_flow.paste.copy_text", return_value=True),
            patch("knight_flow.paste.pyautogui.hotkey"),
            patch("knight_flow.paste.restore_clipboard_if_unchanged"),
            patch("knight_flow.paste.time.sleep"),
        ):
            paste_text_with_receipt("plain", paste_mode="clipboard", restore_clipboard=True)
        snapshot.assert_not_called()

    def test_restore_refuses_when_talk_dat_no_longer_owns_the_clipboard(self) -> None:
        from knight_flow import paste as module

        previous = module._CLIPBOARD_OWNERSHIP
        module._CLIPBOARD_OWNERSHIP = None
        try:
            self.assertFalse(module.restore_clipboard_snapshot([(13, b"x\x00")], "dictated text"))
        finally:
            module._CLIPBOARD_OWNERSHIP = previous
