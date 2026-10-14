"""Paste Last pastes when the mouse moves, and still stops for a key, a click or a focus change.

Owner report, 2026-10-12: clicking Paste Last "doesn't paste anything ever, it just goes to my clipboard". His log
agrees: every Paste Last outcome since 09-27, 7 of 7, is "not pasted method=cancelled copied=True
attempts=clipboard,cancelled". The guard compared the Windows input tick (GetLastInputInfo), which moves for pointer
travel too, and the hand that clicked the menu item moves the mouse inside the tenth of a second the paste takes.

The Mac's tick (mac_support.input_generation) already counts only key-downs and clicks. Windows now reads the same
thing from what it has: a tick that moved while the pointer travelled is that travel; a tick that moved with the
pointer where it was is a key or a click; a key or button newly held, another window, or another focused control
in the same window still stops the paste.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from knight_flow import paste
from knight_flow.paste import PasteReceipt
from tests.test_app_session_lifecycle import _app

PASTED = ("captured", "Pasted and copied last transcript.")
BLOCKED = ("captured", "Copied last transcript. Automatic paste was blocked.")


def run_paste_last(between, **world_changes):
    """Ask for Paste Last, let `between` change the world before the chord, and return the Pill's last state."""
    world = {"window": 44, "tick": 9, "pointer": (100, 100), "held": frozenset(), "focus": 7,
             "travel_moves_tick": True, **world_changes}

    def deliver(_text: str, **options: object) -> PasteReceipt:
        # What paste_text_with_receipt does on the clipboard route: copy, then ask once before the chord.
        between(world)
        if not options["can_deliver"]():
            return PasteReceipt(False, "clipboard", "cancelled", ("clipboard", "cancelled"))
        return PasteReceipt(True, "clipboard", "clipboard", ("clipboard",))

    app = _app(object())
    app.last_transcript = "Recovered words"
    app.config["dictation"] = {"paste_mode": "clipboard"}
    with patch("knight_flow.app.paste_text_with_receipt", side_effect=deliver), \
            patch("knight_flow.app.copy_text", return_value=True), \
            patch("knight_flow.app.foreground_window_id", side_effect=lambda: world["window"]), \
            patch("knight_flow.app.foreground_input_generation", side_effect=lambda: world["tick"]), \
            patch("knight_flow.app.pointer_position", side_effect=lambda: world["pointer"], create=True), \
            patch("knight_flow.app.keys_or_buttons_down", side_effect=lambda: world["held"], create=True), \
            patch("knight_flow.app.foreground_focus_window_id", side_effect=lambda: world["focus"], create=True), \
            patch("knight_flow.app.pointer_travel_moves_input_tick",
                  side_effect=lambda: world["travel_moves_tick"], create=True), \
            patch.object(paste, "wait_for_keys_released", return_value=True), \
            unittest.TestCase().assertLogs("knight_flow.app", level="INFO") as logs:
        app.paste_last()
    return app.overlay.states[-1], logs.output


def mouse_moves(world):
    world.update(tick=world["tick"] + 1, pointer=(world["pointer"][0] + 40, world["pointer"][1] + 25))


class MovingTheMouseIsNotInterference(unittest.TestCase):
    def test_moving_the_mouse_while_it_pastes_still_pastes(self) -> None:
        state, _logs = run_paste_last(mouse_moves)
        self.assertEqual(state, PASTED)

    def test_the_outcome_line_says_pasted_and_carries_no_words(self) -> None:
        _state, logs = run_paste_last(mouse_moves)
        outcome = [line for line in logs if "paste_last: " in line and "method=" in line]
        self.assertEqual(len(outcome), 1, logs)
        self.assertIn("paste_last: pasted method=clipboard", outcome[0])
        self.assertNotIn("Recovered", " ".join(logs))


class RealInterferenceStillStopsIt(unittest.TestCase):
    def test_a_key_or_a_click_with_the_pointer_still_stops_it(self) -> None:
        state, _logs = run_paste_last(lambda world: world.update(tick=world["tick"] + 1))
        self.assertEqual(state, BLOCKED)

    def test_a_key_held_while_the_mouse_moves_stops_it(self) -> None:
        def typing_while_moving(world):
            mouse_moves(world)
            world["held"] = frozenset({0x41})

        state, _logs = run_paste_last(typing_while_moving)
        self.assertEqual(state, BLOCKED)

    def test_a_click_into_another_window_stops_it(self) -> None:
        def click_elsewhere(world):
            mouse_moves(world)
            world["window"] = 55

        state, _logs = run_paste_last(click_elsewhere)
        self.assertEqual(state, BLOCKED)

    def test_a_click_into_another_field_of_the_same_window_stops_it(self) -> None:
        def click_another_field(world):
            mouse_moves(world)
            world["focus"] = 8

        state, _logs = run_paste_last(click_another_field)
        self.assertEqual(state, BLOCKED)

    def test_where_the_tick_ignores_travel_a_moved_tick_is_a_key_or_a_click(self) -> None:
        # The Mac's tick (mac_support.input_generation) moves only for key-downs and clicks, so a moved tick there
        # is never travel, whatever the pointer did.
        state, _logs = run_paste_last(mouse_moves, travel_moves_tick=False)
        self.assertEqual(state, BLOCKED)


if __name__ == "__main__":
    unittest.main()
