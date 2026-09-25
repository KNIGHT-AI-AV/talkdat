"""X-624 (interaction grid D4, D17): a foreign key aborts a young hold.

Windows shortcuts that start with Ctrl+Win (Ctrl+Win+Left/Right to switch
desktop, Ctrl+Win+D, F4, V, Enter, O, C) all pass through the talk chord. The
hold started 35 ms in, the extra key changed nothing, and any voice caught
pasted into the app on the new desktop. Fix That's Ctrl+Alt+F has the same
shape for AltGr and editor shortcuts.

Now a non-modifier key that no chord layers on the held one, going down while
the hold is pending or in its first 600 ms, cancels the start or sends
<action>_abort, which cancels that take quietly. Space (hands-free) and Esc
(Panic) are layered on purpose and keep working.
"""
from __future__ import annotations

import re
import threading
import time
import types
import unittest
from pathlib import Path
from unittest import mock

from knight_flow.hotkeys import HOLD_ACTIONS, HotkeyController

LAYOUT = {
    "push_to_talk": [["ctrl", "cmd"]],
    "hands_free": [["ctrl", "cmd", "space"]],
    "command_mode": [["ctrl", "cmd", "alt"]],
    "cancel": [["esc"]],
    "panic": [["ctrl", "cmd", "esc"]],
    "fix_that": [["ctrl", "alt", "f"]],
}


class Keyboard:
    """The controller with a recording callback for every action."""

    def __init__(self) -> None:
        self.events: list[str] = []
        self.lock = threading.Lock()
        names = [name for action in LAYOUT for name in (action, f"{action}_stop", f"{action}_abort")]
        self.controller = HotkeyController(LAYOUT, {name: self._recorder(name) for name in names},
                                           hold_debounce_ms=35)
        # The test's keys are not physically down; the controller falls back
        # to its own pressed set, as it does for MIDI notes.
        self._physical = mock.patch("knight_flow.hotkeys.physical_key_down", return_value=None)
        self._physical.start()

    def close(self) -> None:
        self._physical.stop()
        self.controller._cancel_pending()

    def _recorder(self, name: str):
        def record() -> None:
            with self.lock:
                self.events.append(name)
        return record

    def down(self, *keys: str) -> None:
        for key in keys:
            self.controller._on_key_press(_Key(key))

    def up(self, *keys: str) -> None:
        for key in keys:
            self.controller._on_key_release(_Key(key))

    def start_the_hold(self) -> None:
        """Fire the debounce timer now instead of waiting 35 ms for it."""
        self.controller._start_hold_if_still_down()

    def settled(self, count: int) -> list[str]:
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            with self.lock:
                if len(self.events) >= count:
                    break
            time.sleep(0.01)
        time.sleep(0.08)   # and nothing more arrives
        with self.lock:
            return list(self.events)


class _Key:
    """Stands in for a pynput key; key_name() is patched to read .name."""

    def __init__(self, name: str) -> None:
        self.name = name


class AForeignKeyAbortsAYoungHoldTests(unittest.TestCase):
    def setUp(self) -> None:
        self.names = mock.patch("knight_flow.hotkeys.key_name", side_effect=lambda key: key.name)
        self.names.start()
        self.keyboard = Keyboard()

    def tearDown(self) -> None:
        self.keyboard.close()
        self.names.stop()

    def test_ctrl_win_right_is_a_desktop_switch_not_a_take(self) -> None:
        self.keyboard.down("ctrl", "cmd")
        self.keyboard.start_the_hold()
        self.keyboard.down("right")
        self.assertEqual(self.keyboard.settled(2), ["push_to_talk", "push_to_talk_abort"])

    def test_the_same_key_after_600_ms_is_part_of_the_take(self) -> None:
        self.keyboard.down("ctrl", "cmd")
        self.keyboard.start_the_hold()
        self.keyboard.controller._hold_started_at -= 0.7
        self.keyboard.down("right")
        self.assertEqual(self.keyboard.settled(1), ["push_to_talk"])

    def test_a_key_before_the_hold_begins_means_it_never_begins(self) -> None:
        self.keyboard.down("ctrl", "cmd", "d")
        self.keyboard.start_the_hold()
        self.assertEqual(self.keyboard.settled(0), [])

    def test_modifier_repeat_cannot_reopen_an_aborted_hold(self) -> None:
        self.keyboard.down("ctrl", "cmd")
        self.keyboard.start_the_hold()
        self.keyboard.down("right")
        self.keyboard.up("right")
        self.keyboard.down("ctrl")          # auto-repeat of a held modifier
        self.keyboard.start_the_hold()
        self.assertEqual(self.keyboard.settled(2), ["push_to_talk", "push_to_talk_abort"])
        self.keyboard.up("ctrl", "cmd")     # let the chord go, then a real hold works
        self.keyboard.down("ctrl", "cmd")
        self.keyboard.start_the_hold()
        self.assertEqual(self.keyboard.settled(3), ["push_to_talk", "push_to_talk_abort", "push_to_talk"])

    def test_space_still_goes_hands_free_and_esc_still_panics(self) -> None:
        self.keyboard.down("ctrl", "cmd")
        self.keyboard.start_the_hold()
        self.keyboard.down("space")
        events = self.keyboard.settled(2)
        self.assertIn("hands_free", events)
        self.assertNotIn("push_to_talk_abort", events)
        self.keyboard.up("space", "ctrl", "cmd")
        self.keyboard.down("ctrl", "cmd")
        self.keyboard.start_the_hold()
        self.keyboard.down("esc")
        events = self.keyboard.settled(len(events) + 2)
        self.assertIn("panic", events)
        self.assertNotIn("push_to_talk_abort", events)

    def test_auto_repeat_of_a_key_held_before_the_chord_is_not_a_shortcut(self) -> None:
        """X-624b: W held in a game while starting to talk repeats its key-down."""
        self.keyboard.down("w", "ctrl", "cmd")
        self.keyboard.start_the_hold()
        self.keyboard.down("w", "w")   # auto-repeat
        self.assertEqual(self.keyboard.settled(1), ["push_to_talk"])

    def test_fix_that_has_the_same_guard(self) -> None:
        self.keyboard.down("ctrl", "alt", "f")
        self.keyboard.start_the_hold()
        self.keyboard.down("d")
        self.assertEqual(self.keyboard.settled(2), ["fix_that", "fix_that_abort"])

    def test_every_hold_action_wires_its_abort(self) -> None:
        source = (Path(__file__).resolve().parent.parent / "knight_flow" / "app.py").read_text(encoding="utf-8")
        missing = [action for action in HOLD_ACTIONS if not re.search(rf'"{action}_abort":\s*self\.abort_young_hold', source)]
        self.assertEqual(missing, [])


class TheAppCancelsOnlyTheHoldTakeTests(unittest.TestCase):
    def app(self, *, control: str, released: bool):
        import knight_flow.app as app_module

        app = types.SimpleNamespace(lock=threading.Lock(), session=object(), session_control=control,
                                    _released_processing=released, _wake_runtime=None,
                                    overlay=types.SimpleNamespace(_ui_thread_id=threading.get_ident()),
                                    cancel=mock.Mock())
        app_module.TalkDatApp.abort_young_hold(app)
        return app

    def test_a_hold_take_is_cancelled(self) -> None:
        self.app(control="hold", released=False).cancel.assert_called_once()

    def test_a_hands_free_take_the_same_press_stopped_is_left_to_land(self) -> None:
        self.app(control="hands_free", released=True).cancel.assert_not_called()
        self.app(control="hold", released=True).cancel.assert_not_called()


if __name__ == "__main__":
    unittest.main()
