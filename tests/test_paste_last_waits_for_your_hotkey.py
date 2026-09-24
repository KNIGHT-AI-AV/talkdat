"""X-463: Paste Last copied but never pasted, because his own hotkey was
still held down.

His report, 2026-09-05: "The paste last transcription function fails to
paste, instead only copying the content to the clipboard."

Paste Last is Shift+Alt+Z and delivers the moment the chord is recognised,
while all three keys are still physically down. SendInput does not replace
the keyboard state, it adds to it, so the synthetic Ctrl+V arrives at the
app as Ctrl+Shift+Alt+V. Nothing has that binding, nothing pastes, and the
text sits on the clipboard where the copy left it.

Dictation never showed the fault because push-to-talk ends on RELEASE and
the transcript lands a second later, with the modifiers long up.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path
from unittest import mock

from knight_flow import paste

SOURCE = (Path(__file__).resolve().parents[1] / "knight_flow" / "paste.py").read_text(encoding="utf-8")


class TheChordIsCleanBeforeItIsSentTests(unittest.TestCase):
    def test_every_synthetic_route_settles_the_modifiers_first(self) -> None:
        body = re.search(
            r"def paste_text_with_receipt\(.*?\n(?=def |\Z)", SOURCE, re.S
        ).group(0)
        # The clipboard/Shift+Insert route, and the direct-typing route where a
        # held Shift would capitalise every character.
        self.assertEqual(body.count("settle_modifiers()"), 2, body.count("settle_modifiers()"))
        clipboard_at = body.index('attempts.append(clipboard_method)')
        settle_after_clipboard = body.index("settle_modifiers()", clipboard_at)
        # EDIT_MODIFIER carries the paste chord: Ctrl on Windows, Command on
        # macOS (see paste.EDIT_MODIFIER / mac_support.PASTE_MODIFIER).
        paste_chord_at = body.index('pyautogui.hotkey(EDIT_MODIFIER, "v")', clipboard_at)
        self.assertLess(settle_after_clipboard, paste_chord_at, "settle after the chord is no use")
        type_at = body.index('if text and mode == "type":')
        self.assertLess(type_at, body.index("settle_modifiers()", type_at))

    def test_it_waits_for_the_person_then_forces_the_issue(self) -> None:
        settle = re.search(r"def settle_modifiers\(.*?\n(?=def |\Z)", SOURCE, re.S).group(0)
        self.assertIn("physical_modifiers_down()", settle)
        self.assertIn("pyautogui.keyUp(name)", settle, "a key still held must be released synthetically")
        self.assertIn("deadline", settle, "a stuck key must not hang the paste")

    def test_the_wait_is_short_enough_to_never_feel_like_a_hang(self) -> None:
        self.assertLessEqual(paste.MODIFIER_RELEASE_TIMEOUT_MS, 900)
        self.assertGreaterEqual(paste.MODIFIER_RELEASE_TIMEOUT_MS, 300)

    def test_it_returns_at_once_when_nothing_is_held(self) -> None:
        with mock.patch.object(paste, "physical_modifiers_down", return_value=()) as down:
            with mock.patch.object(paste.time, "sleep") as slept:
                self.assertTrue(paste.settle_modifiers())
        down.assert_called_once()
        slept.assert_not_called()

    def test_it_waits_while_a_modifier_is_down_and_then_proceeds(self) -> None:
        """Shift held for two polls, then released: no synthetic key-up needed."""
        states = [(0x10,), (0x10,), ()]
        with mock.patch.object(paste, "physical_modifiers_down", side_effect=lambda: states.pop(0) if states else ()):
            with mock.patch.object(paste.pyautogui, "keyUp") as key_up:
                with mock.patch.object(paste.time, "sleep"):
                    self.assertTrue(paste.settle_modifiers())
        key_up.assert_not_called()

    def test_a_key_held_past_the_deadline_is_released_synthetically(self) -> None:
        with mock.patch.object(paste, "physical_modifiers_down", return_value=(0x10, 0x12)):
            with mock.patch.object(paste.pyautogui, "keyUp") as key_up:
                with mock.patch.object(paste.time, "sleep"):
                    paste.settle_modifiers(timeout_ms=0)
        released = {call.args[0] for call in key_up.call_args_list}
        self.assertIn("shift", released)
        self.assertIn("alt", released)
        self.assertIn("ctrl", released)

    def test_reading_the_keyboard_can_never_break_a_delivery(self) -> None:
        if paste.mac_support.IS_MAC:
            # No ctypes.windll on macOS at all; the window-server read goes
            # through mac_support.physical_key_down instead.
            with mock.patch.object(paste.mac_support, "physical_key_down", side_effect=RuntimeError):
                self.assertEqual(paste.physical_modifiers_down(), ())
        else:
            with mock.patch.object(paste.ctypes, "windll", None):
                self.assertEqual(paste.physical_modifiers_down(), ())


if __name__ == "__main__":
    unittest.main()
