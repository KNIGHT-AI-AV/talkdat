"""P0-4 (find-more sweep), commandment 85: a slow app never pastes the old clipboard.

The paste layer put the dictation on the clipboard, sent Ctrl+V, and restored
the person's previous clipboard a fixed 0.2 s later. An app that handles the
keystroke later (Word or Teams under load, an Electron app, a VM) read the
clipboard after the restore and pasted whatever was there before, a password
included. The commandment battery skipped C085 ("native delivery, clipboard
timing") and nothing else covered it.

The borrowed clipboard is now a delayed-render offer (knight_flow/clipboard_owner.py):
the restore waits for the target's read, and past a 2 s ceiling the dictation
stays on the clipboard instead.

The end-to-end cases run a real paste against a real clipboard in a window
station of their own (tests/clipboard_station.py), so the person's clipboard
is never touched and no key is ever sent: the "target" is a separate process
that reads the clipboard a set time after the chord.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from knight_flow import clipboard_owner, paste

STATION = Path(__file__).resolve().parent / "clipboard_station.py"


@unittest.skipUnless(sys.platform == "win32", "the Windows clipboard")
class ALateReaderGetsTheDictation(unittest.TestCase):
    def station(self, read_after_ms: int, *extra: str) -> dict:
        with tempfile.TemporaryDirectory() as home:
            finished = subprocess.run(
                [sys.executable, str(STATION), str(read_after_ms), *extra],
                capture_output=True, timeout=120, cwd=str(STATION.parents[1]),
                env={**os.environ, "TALK_DAT_HOME": home},
            )
        output = finished.stdout.decode("utf-8", "replace").strip()
        if finished.returncode != 0 and "CreateWindowStationW failed" in finished.stderr.decode("utf-8", "replace"):
            self.skipTest("this machine refuses a private window station")
        self.assertEqual(finished.returncode, 0, finished.stderr.decode("utf-8", "replace"))
        report = json.loads(output.splitlines()[-1])
        self.assertNotIn("error", report, report)
        self.assertTrue(report["success"], report)
        return report

    def test_c085_neg_a_target_that_reads_900_ms_late_gets_the_dictation(self) -> None:
        report = self.station(900)
        self.assertEqual(report["target_read"], "Hello there", "the slow app pasted the old clipboard")
        self.assertEqual(report["clipboard_after"], "ABC-123", "the person's clipboard was not put back")

    def test_c085_pos_a_quick_target_gets_it_and_the_clipboard_comes_back(self) -> None:
        report = self.station(50)
        self.assertEqual((report["target_read"], report["clipboard_after"]), ("Hello there", "ABC-123"))
        self.assertLess(report["elapsed_s"], 1.0, "a quick read must not wait for the ceiling")

    def test_a_target_that_never_reads_keeps_the_dictation_on_the_clipboard(self) -> None:
        report = self.station(-1)
        self.assertEqual(report["clipboard_after"], "Hello there")
        self.assertGreaterEqual(report["elapsed_s"], clipboard_owner.READ_CEILING_S - 0.1)

    def test_a_clipboard_manager_reading_first_falls_back_to_the_old_delay(self) -> None:
        # Its read comes before the target's, so the target's is silent; the
        # restore then keeps the old 0.2 s, no worse than before this fix.
        report = self.station(50, "early")
        self.assertEqual((report["target_read"], report["clipboard_after"]), ("Hello there", "ABC-123"))


class _FakeOwner:
    def __init__(self, outcome: str) -> None:
        self.outcome, self.kept, self.rendered_sequence = outcome, 0, 77

    def offer(self, _text: str, mark_private) -> int:
        mark_private()
        return 41

    def wait_for_read(self, _chord_at: float, _target_pid: int) -> str:
        return self.outcome

    def keep(self) -> bool:
        self.kept += 1
        return True


class TheRestoreFollowsTheRead(unittest.TestCase):
    def paste(self, outcome: str):
        owner = _FakeOwner(outcome)
        keys = type("Keys", (), {"hotkey": staticmethod(lambda *_k: None), "press": staticmethod(lambda *_k: None)})
        # _borrow_clipboard checks mac_support.IS_MAC before it ever looks at
        # clipboard_owner.borrowed_clipboard: on a real Mac that branch takes
        # mac_pasteboard.borrow() first and this fake owner is never reached.
        # The delayed-render protocol under test here (offer/wait_for_read/
        # keep, and the restore that follows the read) is the shared, portable
        # half -- forcing the Windows branch is what the fully-mocked
        # pyautogui/clipboard_text/restore_clipboard_if_unchanged around it
        # were already assuming.
        with patch.object(paste.mac_support, "IS_MAC", False), \
             patch.object(paste, "clipboard_sequence_number", return_value=1), \
             patch.object(clipboard_owner, "borrowed_clipboard", return_value=owner), \
             patch.object(paste, "_mark_open_clipboard_private"), \
             patch.object(paste, "pyautogui", keys), \
             patch.object(paste, "settle_modifiers", return_value=True), \
             patch.object(paste, "clipboard_text", return_value="ABC-123"), \
             patch.object(paste, "clipboard_contains_non_text_formats", return_value=False), \
             patch.object(paste, "foreground_is_remote_client", return_value=False), \
             patch.object(paste, "foreground_window_id", return_value=0), \
             patch.object(paste, "restore_clipboard_if_unchanged", return_value=True) as restore:
            receipt = paste.paste_text_with_receipt("Hello there", restore_clipboard=True, paste_mode="clipboard")
        return receipt, owner, restore

    def test_after_the_read_the_old_clipboard_comes_back(self) -> None:
        receipt, owner, restore = self.paste("read")
        self.assertTrue(receipt.success)
        restore.assert_called_once_with("Hello there", "ABC-123")
        self.assertEqual(owner.kept, 0)

    def test_no_read_by_the_ceiling_keeps_the_dictation(self) -> None:
        receipt, owner, restore = self.paste("none")
        self.assertTrue(receipt.success)
        restore.assert_not_called()
        self.assertEqual(owner.kept, 1, "the promise must become real data")

    def test_a_newer_copy_is_never_overwritten(self) -> None:
        _receipt, _owner, restore = self.paste("lost")
        restore.assert_not_called()

    def test_the_test_package_never_borrows_the_real_clipboard(self) -> None:
        self.assertEqual(os.environ.get("TALK_DAT_PLAIN_CLIPBOARD"), "1")
        self.assertIsNone(clipboard_owner.borrowed_clipboard())


if __name__ == "__main__":
    unittest.main()
