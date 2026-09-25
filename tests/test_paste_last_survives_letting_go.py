"""P1-5 (find-more sweep): Paste Last pastes after the person lets go of its keys.

The shortcut fires on key-down. `paste_last` read the Windows input tick
straight away, and the paste layer then waited for the modifiers to come up
and checked the tick again before the chord (`can_deliver`). A key release is
input, so the tick had always moved and Paste Last only copied. His log had
7 "paste_last: requested" lines since 09-05 and no outcome line, because the
outcome was only shown on the Pill.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from knight_flow import paste
from knight_flow.paste import PasteReceipt
from tests.test_app_session_lifecycle import _app


class PasteLastSurvivesLettingGo(unittest.TestCase):
    def run_paste_last(self):
        app = _app(object())
        app.last_transcript = "Recovered words"
        app.config["dictation"] = {"paste_mode": "auto"}
        keys = {"held": True}
        # The tick is 9 while the chord is held and 10 once it is let go.
        tick = lambda: 9 if keys["held"] else 10

        def let_go(*_args, **_kwargs) -> bool:
            keys["held"] = False
            return True

        def deliver(_text: str, **options: object) -> PasteReceipt:
            # What paste_text_with_receipt does: settle, then ask before the chord.
            keys["held"] = False
            if not options["can_deliver"]():
                return PasteReceipt(False, "auto", "cancelled", ("clipboard", "cancelled"))
            return PasteReceipt(True, "auto", "clipboard", ("clipboard",))

        with patch("knight_flow.app.paste_text_with_receipt", side_effect=deliver), \
             patch("knight_flow.app.copy_text", return_value=True), \
             patch("knight_flow.app.foreground_window_id", return_value=44), \
             patch("knight_flow.app.foreground_input_generation", side_effect=tick), \
             patch.object(paste, "wait_for_keys_released", side_effect=let_go) as waited, \
             self.assertLogs("knight_flow.app", level="INFO") as logs:
            app.paste_last()
        return app, waited, logs

    def test_the_paste_goes_through_after_the_keys_come_up(self) -> None:
        app, waited, _logs = self.run_paste_last()
        waited.assert_called_once()
        self.assertEqual(app.overlay.states[-1], ("captured", "Pasted and copied last transcript."))

    def test_the_outcome_is_written_to_the_log(self) -> None:
        _app_, _waited, logs = self.run_paste_last()
        outcome = [line for line in logs.output if "paste_last: pasted" in line]
        self.assertEqual(len(outcome), 1, logs.output)
        self.assertIn("method=clipboard", outcome[0])
        self.assertNotIn("Recovered", " ".join(logs.output), "the log carries no words")


class WaitingForTheKeysNeverHangs(unittest.TestCase):
    def test_a_stuck_key_gives_up_at_the_deadline(self) -> None:
        if paste.os.name != "nt":
            self.skipTest("Windows keyboard state")

        class StuckKeys:
            def __init__(self) -> None:
                self.GetAsyncKeyState = lambda _code: -32768  # high bit: held

        with patch.object(paste.ctypes, "WinDLL", return_value=StuckKeys()), \
             patch.object(paste.time, "sleep"):
            self.assertFalse(paste.wait_for_keys_released(timeout_ms=0))

    def test_nothing_held_returns_at_once(self) -> None:
        if paste.os.name != "nt":
            self.skipTest("Windows keyboard state")

        class NoKeys:
            def __init__(self) -> None:
                self.GetAsyncKeyState = lambda _code: 0

        with patch.object(paste.ctypes, "WinDLL", return_value=NoKeys()), \
             patch.object(paste.time, "sleep") as slept:
            self.assertTrue(paste.wait_for_keys_released())
        slept.assert_not_called()


if __name__ == "__main__":
    unittest.main()
