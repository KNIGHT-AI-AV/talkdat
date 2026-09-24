"""X-178: a shortcut you can record must be a shortcut that fires.

Three actions -- `translate_last`, `pin_last` and `meeting_mode` -- each had:

    a slot in DEFAULT_CONFIG["hotkeys"]        (so it could be assigned)
    a real callback in app.py                  (so it could have worked)
    a row in the Settings shortcut editor      (so it was advertised)

and none of them appeared in hotkeys.TAP_ACTIONS or HOLD_ACTIONS, which is the
only list HotkeyController listens for. So a person could open Settings, find the
action, record a chord, save it successfully, and then press it forever with
nothing happening.

That is worse than the feature being absent. A missing feature sends you looking
for another way; a shortcut that saves and does nothing makes you doubt your own
keyboard, and there is no error anywhere to find.

This guard states the rule rather than the instance: if an action can be ASSIGNED
and can be CALLED, it must be LISTENED FOR. It joins the three lists that have to
agree and fails on any disagreement, so the next action added to two of them is
caught before it ships.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

from knight_flow.config import DEFAULT_CONFIG
from knight_flow.hotkeys import HOLD_ACTIONS, TAP_ACTIONS

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "knight_flow" / "app.py"

# Slots that exist for reasons other than a global hotkey. Keep this list short
# and justified: every entry here is a hole in the guard.
NOT_GLOBAL_HOTKEYS = frozenset({
    # The push-to-talk chord itself is handled by the hold path and is present in
    # HOLD_ACTIONS; nothing else is currently exempt.
})


def configured_shortcut_actions() -> set[str]:
    # The section is called "hotkeys", not "shortcuts". Settings labels it
    # Shortcuts, which is what made the wrong guess plausible; the self-checks in
    # TheGuardActuallyLooksAtSomethingTests are what caught it returning nothing.
    return set(DEFAULT_CONFIG.get("hotkeys", {}))


def dispatcher_callbacks() -> set[str]:
    """Keys of the callbacks dict app.py hands to the overlay and hotkeys.

    Read from the source rather than by constructing TalkDatApp, which would want
    a display, an audio device and a network.
    """
    text = APP.read_text(encoding="utf-8")
    tree = ast.parse(text)
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values):
            if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                continue
            # A callback entry maps a name to something callable, which in this
            # file is always an attribute (self.foo) or a lambda.
            if isinstance(value, (ast.Attribute, ast.Lambda)):
                found.add(key.value)
    return found


def listened_for() -> set[str]:
    return set(TAP_ACTIONS) | set(HOLD_ACTIONS)


class EveryAssignableShortcutIsListenedForTests(unittest.TestCase):
    def test_the_three_that_were_dead_are_alive(self) -> None:
        """Named explicitly, so the regression is unmistakable in the failure."""
        for action in ("translate_last", "pin_last", "meeting_mode"):
            with self.subTest(action=action):
                self.assertIn(
                    action, listened_for(),
                    f"{action} can be assigned in Settings and has a callback, but "
                    "HotkeyController does not listen for it, so the chord does nothing",
                )

    def test_no_shortcut_slot_with_a_callback_goes_unheard(self) -> None:
        """The general rule: assignable + callable must imply listened-for."""
        callbacks = dispatcher_callbacks()
        heard = listened_for()
        dead = sorted(
            action
            for action in configured_shortcut_actions()
            if action in callbacks and action not in heard and action not in NOT_GLOBAL_HOTKEYS
        )
        self.assertEqual(
            dead, [],
            "these actions can be assigned a chord in Settings and have a real "
            "callback, but nothing listens for them, so the chord saves and then "
            f"does nothing: {dead}",
        )

    def test_nothing_is_listened_for_that_cannot_be_assigned(self) -> None:
        """The mirror defect: an action the controller watches for but which has
        no slot can never be given a chord, so the watch is dead weight and the
        capability is invisible."""
        assignable = configured_shortcut_actions()
        orphans = sorted(action for action in listened_for() if action not in assignable)
        self.assertEqual(
            orphans, [],
            "these are listened for but have no shortcut slot, so no one can ever "
            f"trigger them: {orphans}",
        )

    def test_no_action_is_both_a_tap_and_a_hold(self) -> None:
        """One chord cannot mean two things; the overlap would be resolved by
        list order, which is not a decision anybody made."""
        overlap = sorted(set(TAP_ACTIONS) & set(HOLD_ACTIONS))
        self.assertEqual(overlap, [], f"actions registered as both tap and hold: {overlap}")

    def test_the_lists_have_no_duplicates(self) -> None:
        for name, actions in (("TAP_ACTIONS", TAP_ACTIONS), ("HOLD_ACTIONS", HOLD_ACTIONS)):
            with self.subTest(list=name):
                self.assertEqual(len(actions), len(set(actions)), f"{name} lists an action twice")


def settings_editor_actions() -> set[str]:
    """The action ids the Settings shortcut editor offers a row for.

    Read from the `hotkey_labels` literal in overlay.py, because building the
    real Settings window needs a display.
    """
    text = (ROOT / "knight_flow" / "overlay.py").read_text(encoding="utf-8")
    start = text.index("hotkey_labels = [")
    block = text[start: text.index(chr(10) + "        ]", start)]
    tree = ast.parse("x = " + block[block.index("["):] + "]")
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Tuple) and node.elts:
            first = node.elts[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                found.add(first.value)
    return found


class EveryWorkingShortcutIsDiscoverableTests(unittest.TestCase):
    """The mirror of the dead-shortcut bug, and the third direction of the rule.

    0.4.108 fixed actions that were ADVERTISED with nothing listening. This is the
    opposite: actions the dispatcher listens for that the Settings editor never
    lists, so a real working feature cannot be discovered, rebound, or cleared by
    anyone. A capability sweep classified `read_back` UNREACHABLE for precisely
    this reason -- a healthy handler with no user path to it.
    """

    def test_the_two_that_were_hidden_are_listed(self) -> None:
        listed = settings_editor_actions()
        for action in ("fix_that", "read_back"):
            with self.subTest(action=action):
                self.assertIn(
                    action, listed,
                    f"{action} has a default chord and a live handler but no row in "
                    "the Settings shortcut editor, so nobody can find or change it",
                )

    def test_every_listened_for_action_has_an_editor_row(self) -> None:
        listed = settings_editor_actions()
        hidden = sorted(action for action in listened_for() if action not in listed)
        self.assertEqual(
            hidden, [],
            "these actions are dispatched but absent from the Settings shortcut "
            f"editor, so their chords cannot be discovered or rebound: {hidden}",
        )

    def test_the_editor_offers_nothing_that_is_not_dispatched(self) -> None:
        """The 0.4.108 defect, restated against the editor rather than the config."""
        listed = settings_editor_actions()
        dead = sorted(action for action in listed if action not in listened_for())
        self.assertEqual(
            dead, [],
            f"the Settings editor advertises actions nothing listens for: {dead}",
        )


class TheGuardActuallyLooksAtSomethingTests(unittest.TestCase):
    """A guard that silently matches nothing passes forever and protects nothing."""

    def test_the_shortcut_slots_were_found(self) -> None:
        self.assertGreaterEqual(len(configured_shortcut_actions()), 10)

    def test_the_callbacks_were_found(self) -> None:
        callbacks = dispatcher_callbacks()
        self.assertGreaterEqual(len(callbacks), 20)
        for known in ("cancel", "panic", "pin_last"):
            self.assertIn(known, callbacks, "the callback extractor stopped finding real entries")

    def test_the_listen_lists_were_found(self) -> None:
        self.assertGreaterEqual(len(listened_for()), 12)

    def test_the_editor_rows_were_found(self) -> None:
        rows = settings_editor_actions()
        self.assertGreaterEqual(len(rows), 12, "the hotkey_labels extractor found almost nothing")
        self.assertIn("push_to_talk", rows, "the editor extractor stopped finding real rows")


if __name__ == "__main__":
    unittest.main()
