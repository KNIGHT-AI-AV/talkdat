import time
import unittest
from pathlib import Path

from knight_flow.hotkeys import HotkeyController


class HotkeyControllerTests(unittest.TestCase):
    def test_tap_action_stops_an_active_hold_before_running(self) -> None:
        # X-118: actions dispatch through an ordered worker queue now (a slow
        # handler on the hook thread got the hook silently removed by
        # Windows), so the assertion waits for the drain instead of assuming
        # a synchronous call.
        events: list[str] = []
        controller = HotkeyController(
            {
                "push_to_talk": [["ctrl", "cmd"]],
                "hands_free": [["ctrl", "cmd", "space"]],
            },
            {
                "push_to_talk_stop": lambda: events.append("push_to_talk_stop"),
                "hands_free": lambda: events.append("hands_free"),
            },
        )
        controller.active_hold = "push_to_talk"
        controller.pressed = {"ctrl", "cmd", "space"}

        controller._evaluate_press()

        deadline = time.monotonic() + 2.0
        while len(events) < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertIsNone(controller.active_hold)
        self.assertEqual(events, ["push_to_talk_stop", "hands_free"])


class EveryHoldActionHasItsReleaseHalfTests(unittest.TestCase):
    """X-134, found by the catalog audit: fix_that was in HOLD_ACTIONS, so
    release emitted fix_that_stop -- and the app never wired that callback.
    The chord opened the mic and nothing ever closed it. This pins the whole
    class: any action declared holdable must have its _stop wired."""

    def test_every_hold_action_wires_a_stop_callback(self) -> None:
        from knight_flow.hotkeys import HOLD_ACTIONS

        source = (Path(__file__).resolve().parent.parent / "knight_flow" / "app.py").read_text(encoding="utf-8")
        missing = [a for a in HOLD_ACTIONS if f'"{a}_stop"' not in source]
        self.assertEqual(missing, [], "hold actions with no release half wired in app.py")


class MidiTriggerSourceTests(unittest.TestCase):
    """X-120: MIDI notes join the pressed-set as midi_note_<n> through the
    same evaluators as keys and pads, so chords, styles and conflict rules
    apply unchanged. The winmm listener itself is Windows-only hardware; the
    name-based press/release path is what these pin."""

    def test_a_midi_note_chord_triggers(self) -> None:
        events: list[str] = []
        controller = HotkeyController(
            {"push_to_talk": [["midi_note_60"]]},
            {"push_to_talk": lambda: events.append("go")},
        )
        controller._on_key_press_name("midi_note_60")
        deadline = time.monotonic() + 2.0
        while not events and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(events, ["go"])

    def test_release_clears_the_pressed_set(self) -> None:
        controller = HotkeyController({"push_to_talk": [["midi_note_60"]]}, {"push_to_talk": lambda: None})
        controller._on_key_press_name("midi_note_60")
        controller._on_key_release_name("midi_note_60")
        self.assertNotIn("midi_note_60", controller.pressed)

    def test_repeated_note_on_does_not_retrigger(self) -> None:
        events: list[str] = []
        controller = HotkeyController(
            {"push_to_talk": [["midi_note_61"]]},
            {"push_to_talk": lambda: events.append("go")},
        )
        controller._on_key_press_name("midi_note_61")
        deadline = time.monotonic() + 2.0
        while not events and time.monotonic() < deadline:
            time.sleep(0.01)
        controller._on_key_press_name("midi_note_61")
        time.sleep(0.05)
        self.assertEqual(events, ["go"])


if __name__ == "__main__":
    unittest.main()


class ChordConflictRulesTests(unittest.TestCase):
    """X-118, his rule set: nesting DIRECTION decides. hold ⊂ tap layers
    deliberately (Ctrl+Win holds, +Space toggles); tap ⊂ hold is broken by
    physics -- keys go down one at a time, so the tap fires en route."""

    def test_the_shipped_default_layout_is_clean(self) -> None:
        from knight_flow.hotkeys import chord_conflicts

        layout = {
            "push_to_talk": [["ctrl", "cmd"]],
            "hands_free": [["ctrl", "cmd", "space"]],
            "command_mode": [["ctrl", "cmd", "alt"]],
            "cancel": [["esc"]],
        }
        self.assertEqual(chord_conflicts(layout), [])

    def test_a_toggle_inside_a_hold_is_flagged(self) -> None:
        from knight_flow.hotkeys import chord_conflicts

        layout = {
            "hands_free": [["ctrl", "cmd"]],
            "push_to_talk": [["ctrl", "cmd", "x"]],
        }
        findings = chord_conflicts(layout)
        self.assertEqual(len(findings), 1)
        self.assertIn("activates", findings[0])
        self.assertIn("Change either shortcut", findings[0])
        self.assertIn("Hands-free toggle", findings[0])

    def test_identical_chords_are_always_flagged(self) -> None:
        from knight_flow.hotkeys import chord_conflicts

        layout = {
            "hands_free": [["ctrl", "cmd"]],
            "push_to_talk": [["ctrl", "cmd"]],
        }
        findings = chord_conflicts(layout)
        self.assertEqual(len(findings), 1)
        self.assertIn("Shortcut conflict", findings[0])
        self.assertIn("Choose a different shortcut", findings[0])


class TriggerStyleTests(unittest.TestCase):
    def test_one_button_hold_disables_the_toggle_chord(self) -> None:
        from knight_flow.hotkeys import apply_trigger_style

        layout = {"push_to_talk": [["ctrl", "cmd"]], "hands_free": [["ctrl", "cmd", "space"]]}
        result = apply_trigger_style(layout, "hold")
        self.assertEqual(result["hands_free"], [])
        self.assertEqual(result["push_to_talk"], [["ctrl", "cmd"]])

    def test_one_button_toggle_reuses_the_hold_chord(self) -> None:
        from knight_flow.hotkeys import apply_trigger_style

        layout = {"push_to_talk": [["ctrl", "cmd"]], "hands_free": [["ctrl", "cmd", "space"]]}
        result = apply_trigger_style(layout, "toggle")
        self.assertEqual(result["hands_free"], [["ctrl", "cmd"]])
        self.assertEqual(result["push_to_talk"], [])

    def test_both_leaves_the_layout_alone(self) -> None:
        from knight_flow.hotkeys import apply_trigger_style

        layout = {"push_to_talk": [["ctrl", "cmd"]], "hands_free": [["ctrl", "cmd", "space"]]}
        self.assertEqual(apply_trigger_style(layout, "both"), layout)


class GamepadTriggerSourceTests(unittest.TestCase):
    """X-120: controller buttons ride the same pressed-set as keys, so the
    poller only earns its 60Hz while a chord actually names a pad button."""

    def test_pad_keys_in_use_detection(self) -> None:
        quiet = HotkeyController({"push_to_talk": [["ctrl", "cmd"]]}, {})
        self.assertFalse(quiet._pad_keys_in_use())
        loud = HotkeyController({"push_to_talk": [["pad_rb"]]}, {})
        self.assertTrue(loud._pad_keys_in_use())

    def test_pad_chord_triggers_through_the_normal_evaluator(self) -> None:
        events: list[str] = []
        controller = HotkeyController(
            {"hands_free": [["pad_a", "pad_rb"]]},
            {"hands_free": lambda: events.append("hands_free")},
        )
        controller.pressed = {"pad_a", "pad_rb"}
        controller._evaluate_press()
        deadline = time.monotonic() + 2.0
        while not events and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(events, ["hands_free"])
