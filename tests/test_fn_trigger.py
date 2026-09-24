from __future__ import annotations

import sys
import threading
import time
import unittest
from unittest import mock

from knight_flow import mac_support
from knight_flow.hotkeys import HotkeyController
from knight_flow.onboarding import hotkey_labels


class TheMacTriggerIsTheGlobeKeyTests(unittest.TestCase):
    """Hold Fn to talk: the trigger Mac users already know.

    Wispr Flow -- the app this default is deliberately borrowed from -- binds
    virtual keycode 63 to push-to-talk; that mapping was read out of its own
    config on this machine, not assumed. Apple's dictation lives on the same
    key. Ctrl+Cmd survives as the Windows default and as anyone's explicit
    choice.
    """

    def test_fn_maps_to_the_function_virtual_key(self) -> None:
        self.assertEqual(mac_support._MAC_KEYCODES.get("fn"), (63,))

    @unittest.skipUnless(sys.platform == "darwin", "mac default")
    def test_the_default_chord_is_fn_on_mac(self) -> None:
        from knight_flow.config import DEFAULT_CONFIG

        self.assertEqual(DEFAULT_CONFIG["hotkeys"]["push_to_talk"], [["fn"]])

    @unittest.skipUnless(sys.platform == "darwin", "mac label")
    def test_the_label_names_the_globe(self) -> None:
        (label,) = hotkey_labels(("fn",))
        self.assertIn("Fn", label)

    def test_migration_moves_only_the_old_default(self) -> None:
        from knight_flow.config import _migrate_mac_fn_default

        with mock.patch("knight_flow.config.sys") as fake_sys:
            fake_sys.platform = "darwin"
            config = {"hotkeys": {"push_to_talk": [["ctrl", "cmd"]]}}
            _migrate_mac_fn_default(config)
            self.assertEqual(config["hotkeys"]["push_to_talk"], [["fn"]])
            self.assertTrue(config["migrations"]["mac_fn_default"])

            chosen = {"hotkeys": {"push_to_talk": [["alt", "space"]]}}
            _migrate_mac_fn_default(chosen)
            self.assertEqual(chosen["hotkeys"]["push_to_talk"], [["alt", "space"]],
                             "a chord the user chose must never be overwritten")

            again = {"hotkeys": {"push_to_talk": [["ctrl", "cmd"]]},
                     "migrations": {"mac_fn_default": True}}
            _migrate_mac_fn_default(again)
            self.assertEqual(again["hotkeys"]["push_to_talk"], [["ctrl", "cmd"]],
                             "the migration runs once; going BACK to ctrl+cmd is a choice")


class TheFnPollerBehavesLikeWisprTests(unittest.TestCase):
    """Tap = the system's (emoji, input source, Apple dictation). Hold = ours.

    pynput never sees the Globe key -- macOS reports it as a modifier-flags
    change -- so it is polled through CGEventSourceKeyState. The 140ms arm is
    what keeps a tap from opening the microphone for one frame.
    """

    def _run(self, script) -> list[str]:
        events: list[str] = []
        controller = HotkeyController(
            {"push_to_talk": [["fn"]]},
            {"push_to_talk": lambda: events.append("start"),
             "push_to_talk_stop": lambda: events.append("stop")},
        )
        state = {"down": False}
        with mock.patch("knight_flow.mac_support.physical_key_down",
                        lambda name: state["down"] if name == "fn" else False):
            controller.watchdog_stop.clear()
            thread = threading.Thread(target=controller._fn_loop, daemon=True)
            thread.start()
            script(state)
            controller.watchdog_stop.set()
            thread.join(1)
        return events

    def test_a_tap_stays_the_systems(self) -> None:
        def script(state):
            state["down"] = True
            time.sleep(0.06)
            state["down"] = False
            time.sleep(0.2)

        self.assertEqual(self._run(script), [])

    def test_a_hold_starts_and_release_stops(self) -> None:
        def script(state):
            state["down"] = True
            time.sleep(0.4)
            state["down"] = False
            time.sleep(0.25)

        self.assertEqual(self._run(script), ["start", "stop"])

    def test_an_unbound_fn_polls_nothing_into_the_chord_state(self) -> None:
        events: list[str] = []
        controller = HotkeyController(
            {"push_to_talk": [["ctrl", "cmd"]]},
            {"push_to_talk": lambda: events.append("start")},
        )
        with mock.patch("knight_flow.mac_support.physical_key_down", lambda name: True):
            controller.watchdog_stop.clear()
            thread = threading.Thread(target=controller._fn_loop, daemon=True)
            thread.start()
            time.sleep(0.3)
            controller.watchdog_stop.set()
            thread.join(1)
        self.assertEqual(events, [])
        self.assertNotIn("fn", controller.pressed)


if __name__ == "__main__":
    unittest.main()
