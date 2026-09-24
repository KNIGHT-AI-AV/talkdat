from __future__ import annotations

import unittest

from knight_flow.hotkeys import render_chord, shortcut_conflicts


class TwoActionsOnOneChordMustBeNamedTests(unittest.TestCase):
    """A shared chord is the quiet way a configurable shortcut stops working.

    The dispatcher matches the pressed keys against each action in turn and the
    first match wins, so the second action simply never happens -- no error, no
    log line. The person concludes the feature is broken rather than that two
    of their own bindings collide. Detection has to happen at the moment the
    clash is created, in the settings save, naming both sides.
    """

    def test_the_same_chord_on_two_actions_is_reported(self) -> None:
        clashes = shortcut_conflicts({
            "polish": [["cmd", "alt", "1"]],
            "scratchpad": [["cmd", "alt", "1"]],
        })
        self.assertEqual(len(clashes), 1)
        chord, actions = clashes[0]
        self.assertEqual(actions, ("polish", "scratchpad"))
        self.assertEqual(chord, "cmd+alt+1")

    def test_key_order_does_not_hide_a_conflict(self) -> None:
        """ctrl+alt+1 and alt+ctrl+1 are the same keys to press.

        This is the exact case people hit: rebind one action, forget another
        already uses those keys, and type them in a different order. An
        order-sensitive comparison reports no conflict precisely then.
        """
        clashes = shortcut_conflicts({
            "polish": [["ctrl", "alt", "1"]],
            "view_diff": [["alt", "ctrl", "1"]],
        })
        self.assertEqual(len(clashes), 1)

    def test_distinct_chords_are_not_conflicts(self) -> None:
        self.assertEqual(shortcut_conflicts({
            "polish": [["cmd", "alt", "1"]],
            "turn_to_list": [["cmd", "alt", "3"]],
        }), [])

    def test_unbound_actions_never_conflict(self) -> None:
        """Four actions ship with no keys. Empty must not collide with empty."""
        self.assertEqual(shortcut_conflicts({
            "scratchpad": [],
            "pin_last": [],
            "meeting_mode": [],
        }), [])

    def test_an_action_with_two_chords_conflicts_on_either(self) -> None:
        clashes = shortcut_conflicts({
            "paste_last": [["shift", "alt", "z"], ["f6"]],
            "copy_last": [["f6"]],
        })
        self.assertEqual(len(clashes), 1)
        self.assertEqual(clashes[0][0], "f6")

    def test_three_actions_on_one_chord_are_all_named(self) -> None:
        """Naming only a pair would send somebody hunting for a third clash."""
        clashes = shortcut_conflicts({
            "a": [["f9"]], "b": [["f9"]], "c": [["f9"]],
        })
        self.assertEqual(clashes[0][1], ("a", "b", "c"))


class ChordsAreRenderedTheWayPeopleSayThemTests(unittest.TestCase):
    def test_modifiers_come_first(self) -> None:
        self.assertEqual(render_chord({"1", "alt", "cmd"}), "cmd+alt+1")
        self.assertEqual(render_chord({"z", "shift", "ctrl"}), "ctrl+shift+z")

    def test_a_bare_key_renders_alone(self) -> None:
        self.assertEqual(render_chord({"esc"}), "esc")


class EveryConfigurableActionActuallyDispatchesTests(unittest.TestCase):
    """"Controls, all of which work" means every action in the settings tab is
    wired to a real handler -- a configurable key for a method that does not
    exist is a text box that lies.
    """

    def test_every_default_hotkey_action_has_a_callback_registered(self) -> None:
        import re
        from pathlib import Path

        from knight_flow.config import DEFAULT_CONFIG

        app_source = (Path(__file__).resolve().parents[1] / "knight_flow" / "app.py").read_text(
            encoding="utf-8"
        )
        # Both registration shapes count: a bound method ("cancel": self.cancel)
        # and a lambda ("polish": lambda: self.run_transform("polish")). The
        # first version of this pattern matched only the method form and
        # reported three perfectly working transforms as unwired.
        registered = set(re.findall(r'"([a-z_]+)":\s*(?:lambda\b|self\.)', app_source))
        for action in DEFAULT_CONFIG["hotkeys"]:
            with self.subTest(action=action):
                self.assertIn(
                    action, registered,
                    f"the settings tab offers a key for {action!r} but nothing handles it",
                )


if __name__ == "__main__":
    unittest.main()
