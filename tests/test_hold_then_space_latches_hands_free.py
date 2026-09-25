"""X-627 (interaction grid D6): hold, then Space, latches hands-free.

The chord rules promise it (hotkeys.chord_conflicts: "hold Ctrl+Win to talk,
add Space to go hands-free"). What happened: the controller sent
push_to_talk_stop and then hands_free, so the hold's take stopped, the toggle
stopped it again, and the words pasted mid-thought.

Now the live hold is handed over: one hands_free_latch, no stop, and letting
go of the keys does not end the take. The app turns the open hold take into a
hands-free one; the next toggle stops it.
"""
from __future__ import annotations

import threading
import time
import types
import unittest
from unittest import mock

from knight_flow.hotkeys import HotkeyController

LAYOUT = {"push_to_talk": [["ctrl", "cmd"]], "hands_free": [["ctrl", "cmd", "space"]]}
ACTIONS = ("push_to_talk", "push_to_talk_stop", "hands_free", "hands_free_latch")


class _Key:
    def __init__(self, name: str) -> None:
        self.name = name


class TheKeyboardHandsTheHoldOverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.events: list[str] = []
        patches = [
            mock.patch("knight_flow.hotkeys.key_name", side_effect=lambda key: key.name),
            mock.patch("knight_flow.hotkeys.physical_key_down", return_value=None),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.controller = HotkeyController(
            LAYOUT, {name: (lambda n=name: self.events.append(n)) for name in ACTIONS}, hold_debounce_ms=35
        )
        self.addCleanup(self.controller._cancel_pending)

    def keys(self, down: tuple[str, ...] = (), up: tuple[str, ...] = ()) -> None:
        for name in down:
            self.controller._on_key_press(_Key(name))
        for name in up:
            self.controller._on_key_release(_Key(name))

    def settled(self, count: int) -> list[str]:
        deadline = time.monotonic() + 2.0
        while len(self.events) < count and time.monotonic() < deadline:
            time.sleep(0.01)
        time.sleep(0.08)
        return list(self.events)

    def test_space_on_a_live_hold_latches_it(self) -> None:
        self.keys(down=("ctrl", "cmd"))
        self.controller._start_hold_if_still_down()
        self.keys(down=("space",))
        self.assertEqual(self.settled(2), ["push_to_talk", "hands_free_latch"])
        self.keys(up=("space", "ctrl", "cmd"))
        self.assertEqual(self.settled(3), ["push_to_talk", "hands_free_latch"], "letting go ended the take")

    def test_the_toggle_chord_alone_is_still_the_toggle(self) -> None:
        self.keys(down=("ctrl", "cmd", "space"))
        self.assertEqual(self.settled(1), ["hands_free"])


class TheAppKeepsTheTakeOpenTests(unittest.TestCase):
    def app(self, *, control: str = "hold", released: bool = False):
        import knight_flow.app as app_module

        app = types.SimpleNamespace(
            lock=threading.Lock(), session=object(), session_token=object(), session_control=control,
            _released_processing=released, _last_hands_free_toggle_at=0.0, _wake_runtime=None,
            overlay=mock.Mock(), stop_session=mock.Mock(), start_session=mock.Mock(),
        )
        app.overlay._ui_thread_id = threading.get_ident()
        app.toggle_hands_free = lambda source="": app_module.TalkDatApp.toggle_hands_free(app, source)
        return app_module, app

    def test_the_latch_keeps_the_session_open_and_the_next_toggle_stops_it(self) -> None:
        app_module, app = self.app()
        app_module.TalkDatApp.latch_hands_free(app)
        self.assertEqual(app.session_control, "hands_free")
        app.stop_session.assert_not_called()
        app.overlay.set_state.assert_called_with("listening", "Hands-free: toggle to stop.")
        app._last_hands_free_toggle_at -= 1.0   # a beat later
        app.toggle_hands_free()
        app.stop_session.assert_called_once()

    def test_with_no_hold_take_open_space_is_the_ordinary_toggle(self) -> None:
        app_module, app = self.app()
        app.session = None
        app.session_token = None
        app_module.TalkDatApp.latch_hands_free(app)
        app.start_session.assert_called_once()


if __name__ == "__main__":
    unittest.main()
