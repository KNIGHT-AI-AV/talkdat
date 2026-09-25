"""Find-more P0-5: on the Mac a dictation gives back everything that was copied.

The paste borrows the pasteboard. On the Mac it saved the old clipboard as
plain text and put that text back, so a copied image or file came back as ""
and formatted text came back plain. The borrowed write carried no
nspasteboard.org marker, so clipboard managers kept every dictation, and
nothing kept it off Universal Clipboard. The restore trusted a text
comparison instead of the pasteboard's changeCount, so a copy the person made
of the words just pasted was overwritten, and it ran a fixed 0.2 s after
Command+V, so an app that read later pasted the old clipboard.

Each test drives the real paste layer against tests/mac_pasteboard_fake.py
(NSPasteboard items, promises, changeCount) on a delivery thread, as the app
does. Every one fails on the code before the fix.
"""
from __future__ import annotations

import contextlib
import threading
import unittest
from unittest.mock import patch

from knight_flow import paste
from tests.mac_pasteboard_fake import (
    CONCEALED,
    CURRENT_HOST_ONLY,
    FILE_URL,
    PLAIN,
    PNG,
    PNG_BYTES,
    RTF,
    TRANSIENT,
    FakePasteboard,
    mac_simulation,
    run_in_worker,
)

DICTATION = "Dictated words."
MARKERS = {TRANSIENT, CONCEALED}


def without_markers(contents):
    return [[(kind, data) for kind, data in item if kind not in MARKERS] for item in contents]


@contextlib.contextmanager
def read_ceiling(seconds: float):
    """Shorten the 2 s wait for a reader, where the code has one."""
    try:
        from knight_flow import mac_pasteboard
    except ImportError:
        yield
        return
    with patch.object(mac_pasteboard, "READ_CEILING_S", seconds):
        yield


class ADictationGivesTheClipboardBackWhole(unittest.TestCase):
    def setUp(self) -> None:
        self.board = FakePasteboard()

    def dictate(self, text: str = DICTATION, *, reader_delay: float = 0.0, reads: bool = True, then=None):
        """One dictation with restore on (the default). The target app reads the
        pasteboard when Command+V reaches it, `reader_delay` seconds later."""
        got: list[str] = []
        timers: list[threading.Timer] = []

        def target_reads() -> None:
            got.append(self.board.plain_text())
            if then is not None:
                then()

        def hotkey(*keys: str) -> None:
            if keys[-1] != "v" or not reads:
                return
            if reader_delay:
                timer = threading.Timer(reader_delay, target_reads)
                timers.append(timer)
                timer.start()
            else:
                target_reads()

        with mac_simulation(self.board), \
             patch.object(paste.pyautogui, "hotkey", side_effect=hotkey), \
             patch.object(paste, "foreground_is_remote_client", return_value=False):
            receipt = run_in_worker(paste.paste_text_with_receipt, text, paste_mode="auto", restore_clipboard=True)
            for timer in timers:
                timer.join(5.0)
        return receipt, got

    def our_writes(self, text: str) -> list:
        encoded = text.encode("utf-8")
        return [item for item in self.board.written if item.data.get(PLAIN) == encoded]

    def test_a_copied_image_comes_back_byte_for_byte(self) -> None:
        self.board.hold([(PNG, PNG_BYTES)])
        receipt, got = self.dictate()

        self.assertEqual((receipt.success, receipt.method), (True, "clipboard"))
        self.assertEqual(got, [DICTATION])
        self.assertEqual(without_markers(self.board.contents()), [[(PNG, PNG_BYTES)]])
        # The dictation's own write said "do not keep this" and stayed on this Mac.
        dictation = self.our_writes(DICTATION)
        self.assertEqual(len(dictation), 1, "the dictation was written once")
        self.assertIn(TRANSIENT, dictation[0].types())
        self.assertEqual(dictation[0].clear_option, CURRENT_HOST_ONLY)

    def test_formatted_text_and_every_item_come_back(self) -> None:
        rich = [(RTF, b"{\\rtf1\\ansi {\\b bold} words}"), (PLAIN, b"bold words")]
        files = [(FILE_URL, b"file:///Users/me/notes.txt"), (PLAIN, b"notes.txt")]
        self.board.hold(rich, files)
        receipt, got = self.dictate()

        self.assertTrue(receipt.success)
        self.assertEqual(got, [DICTATION])
        self.assertEqual(without_markers(self.board.contents()), [rich, files])

    def test_a_copy_made_after_the_paste_is_never_overwritten(self) -> None:
        # The person copies the words that just landed. The text is the same as
        # the dictation, so only the changeCount can tell the copy is theirs.
        self.board.hold([(PLAIN, b"old words")])
        receipt, got = self.dictate(then=lambda: self.board.hold([(PLAIN, DICTATION.encode())]))

        self.assertTrue(receipt.success)
        self.assertEqual(got, [DICTATION])
        self.assertEqual(self.board.contents(), [[(PLAIN, DICTATION.encode())]], "their copy stays")

    def test_a_late_reader_gets_the_dictation_and_the_image_after_it(self) -> None:
        # Commandment 85 on the Mac: the target handles Command+V 0.35 s later,
        # past the old fixed 0.2 s restore.
        self.board.hold([(PNG, PNG_BYTES)])
        receipt, got = self.dictate(reader_delay=0.35)

        self.assertTrue(receipt.success)
        self.assertEqual(got, [DICTATION], "the target must read the dictation, never the old clipboard")
        self.assertEqual(without_markers(self.board.contents()), [[(PNG, PNG_BYTES)]])

    def test_with_no_reader_the_dictation_stays_as_real_data(self) -> None:
        self.board.hold([(PNG, PNG_BYTES)])
        with read_ceiling(0.4):
            receipt, _got = self.dictate(reads=False)

        self.assertTrue(receipt.success)
        # Nobody read it: the old clipboard is not put back over a paste that may
        # still come, and the dictation no longer depends on Talk DAT! running.
        self.assertEqual([kind for kind, _ in without_markers(self.board.contents())[0]], [PLAIN])
        self.assertEqual(self.board.items[0].data.get(PLAIN), DICTATION.encode())
        self.assertIn(TRANSIENT, self.board.types())

    def test_every_restoring_paste_on_the_mac_takes_the_snapshot(self) -> None:
        # Plain text too: the snapshot is what carries the changeCount proof, and
        # an empty pasteboard comes back empty rather than as "".
        self.board.hold([(PLAIN, b"old words")])
        receipt, _got = self.dictate()

        self.assertTrue(receipt.success)
        self.assertEqual(without_markers(self.board.contents()), [[(PLAIN, b"old words")]])
        empty = FakePasteboard()
        self.board = empty
        self.dictate()
        self.assertEqual(without_markers(empty.contents()), [], "an empty pasteboard stays empty")


class APasswordIsConcealed(unittest.TestCase):
    def test_a_password_that_falls_back_to_the_pasteboard_is_marked_concealed(self) -> None:
        board = FakePasteboard()
        board.hold([(PLAIN, b"old words")])
        with mac_simulation(board), \
             patch.object(paste, "_type_text", return_value=False), \
             patch.object(paste.pyautogui, "hotkey"):
            run_in_worker(
                paste.paste_text_with_receipt, "hunter two", paste_mode="type",
                smart_leading_space=False, restore_clipboard=False, concealed=True,
            )
        ours = [item for item in board.written if item.data.get(PLAIN) == b"hunter two"]
        self.assertTrue(ours, "typing failed, so the words went to the pasteboard")
        self.assertIn(CONCEALED, ours[-1].types())
        self.assertIn(TRANSIENT, ours[-1].types())
        self.assertEqual(ours[-1].clear_option, CURRENT_HOST_ONLY)

    def test_the_app_asks_for_a_concealed_write_on_a_password_take(self) -> None:
        from knight_flow import field_context as fc
        from tests import test_the_field_decides_the_text as field_tests

        case = field_tests.TheAppKeepsNothingFromAPasswordTests("test_a_password_is_typed_and_leaves_no_trace")
        _app, _result, password_paste, _history, _states = case.take(fc.PASSWORD, "Blue harbor seven.")
        self.assertIs(password_paste.call_args.kwargs.get("concealed"), True)
        _app, _result, ordinary_paste, _history, _states = case.take(fc.MULTI_LINE, "blue harbor seven")
        self.assertFalse(ordinary_paste.call_args.kwargs.get("concealed", False))


class TheSelectionCaptureLeavesRichContentAlone(unittest.TestCase):
    def test_selecting_text_never_writes_over_a_copied_image(self) -> None:
        board = FakePasteboard()
        board.hold([(PNG, PNG_BYTES)])
        with mac_simulation(board), patch.object(paste.pyautogui, "hotkey") as hotkey:
            selected, _previous = paste.copy_selected_text()

        self.assertEqual(selected, "")
        self.assertEqual(board.contents(), [[(PNG, PNG_BYTES)]])
        hotkey.assert_not_called()

    def test_the_probe_reads_types_only(self) -> None:
        board = FakePasteboard()
        cases = (
            ([], False),
            ([[(PLAIN, b"words")]], False),
            ([[(PLAIN, b"words"), (TRANSIENT, b"")]], False),
            ([[(PNG, PNG_BYTES)]], True),
            ([[(RTF, b"{\\rtf1}"), (PLAIN, b"words")]], True),
            ([[(PLAIN, b"one")], [(PLAIN, b"two")]], True),
        )
        for items, rich in cases:
            with self.subTest(items=[[kind for kind, _ in item] for item in items]):
                board.hold(*items)
                reads_before = board.promise_reads
                with mac_simulation(board):
                    self.assertIs(paste.clipboard_contains_non_text_formats(), rich)
                self.assertEqual(board.promise_reads, reads_before)

    def test_a_selection_capture_still_gives_the_clipboard_back(self) -> None:
        # Guard: Command+C lands while the capture waits for it, so the Mac reads
        # the selection's changeCount after the wait, not before.
        board = FakePasteboard()
        board.hold([(PLAIN, b"old words")])
        pending: list = []

        def hotkey(*keys: str) -> None:
            if keys[-1] == "c":
                pending.append(lambda: board.hold([(PLAIN, b"teh cat")]))

        def sleep(_seconds: float) -> None:
            while pending:
                pending.pop(0)()

        with mac_simulation(board), \
             patch.object(paste.pyautogui, "hotkey", side_effect=hotkey), \
             patch.object(paste.time, "sleep", side_effect=sleep):
            selected, previous = paste.copy_selected_text()
            restored = paste.restore_clipboard_if_unchanged(selected, previous)

        self.assertEqual((selected, previous, restored), ("teh cat", "old words", True))
        self.assertEqual(board.plain_text(), "old words")


class ThePlainClipboardSwitchStillMeansNoNativeCalls(unittest.TestCase):
    def test_with_the_switch_on_the_mac_writes_through_pyperclip_only(self) -> None:
        # Guard: tests/__init__.py sets TALK_DAT_PLAIN_CLIPBOARD=1 so the Mac
        # suite never reaches the real pasteboard; it must still mean exactly
        # the old behaviour there.
        import os

        board = FakePasteboard()
        board.hold([(PLAIN, b"old words")])
        with mac_simulation(board), \
             patch.dict(os.environ, {"TALK_DAT_PLAIN_CLIPBOARD": "1"}), \
             patch.object(paste.pyautogui, "hotkey"), \
             patch.object(paste, "foreground_is_remote_client", return_value=False):
            receipt = run_in_worker(paste.paste_text_with_receipt, DICTATION, paste_mode="auto", restore_clipboard=True)

        self.assertTrue(receipt.success)
        self.assertEqual(board.promise_reads, 0)
        self.assertTrue(all(option is None for option in board.clears), "no native (current-host) write")
        self.assertFalse(any(TRANSIENT in item.types() for item in board.written))
        self.assertEqual(board.plain_text(), "old words")


if __name__ == "__main__":
    unittest.main()
