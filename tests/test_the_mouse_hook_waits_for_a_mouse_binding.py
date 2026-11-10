"""Field report 2026-11-05: starting Talk DAT froze the owner's whole PC, and other people's too.

pynput's mouse.Listener is a WH_MOUSE_LL hook that runs inside this Python process.
Windows holds every mouse event on the machine until our callback returns, and the
callback needs our interpreter. During the 14 s model warm the interpreter is busy,
so the cursor stops everywhere. X-436 found this mechanism and removed it for the
right-click hook; the hotkeys still installed one on every start, even though no
default shortcut uses a mouse button.

The rule now: the mouse hook exists only while a shortcut uses a mouse button, or
while a shortcut capture is recording (so a mouse button can still be recorded).
"""
from __future__ import annotations

import copy
import time
import unittest
from unittest import mock

from knight_flow import hotkeys as hotkeys_module
from knight_flow.config import DEFAULT_CONFIG
from knight_flow.hotkeys import HotkeyController


class FakeListener:
    def __init__(self, **callbacks):
        self.callbacks = callbacks
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


class FakeMouseListener(FakeListener):
    made: list["FakeMouseListener"] = []

    def __init__(self, **callbacks):
        super().__init__(**callbacks)
        FakeMouseListener.made.append(self)


def live_mouse_hooks() -> list[FakeMouseListener]:
    return [listener for listener in FakeMouseListener.made if listener.started and not listener.stopped]


class TheMouseHookWaitsForAMouseBinding(unittest.TestCase):
    def setUp(self):
        FakeMouseListener.made = []
        patches = [
            mock.patch.object(hotkeys_module.mouse, "Listener", FakeMouseListener),
            mock.patch.object(hotkeys_module.keyboard, "Listener", FakeListener),
            mock.patch.object(HotkeyController, "_start_gamepad_poller", lambda self: None),
            mock.patch.object(HotkeyController, "_start_midi_listener", lambda self: None),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.controllers: list[HotkeyController] = []

    def tearDown(self):
        for controller in self.controllers:
            controller.stop()

    def controller(self, layout):
        controller = HotkeyController(layout, {})
        self.controllers.append(controller)
        return controller

    def test_the_default_shortcuts_start_no_mouse_hook(self):
        controller = self.controller(copy.deepcopy(DEFAULT_CONFIG["hotkeys"]))
        controller.start()
        self.assertEqual(live_mouse_hooks(), [], "a default start must not hook the mouse")
        self.assertTrue(controller.keyboard_listener.started, "the keyboard shortcuts still listen")

    def test_a_mouse_button_shortcut_starts_the_mouse_hook(self):
        controller = self.controller({"push_to_talk": [["mouse4"]]})
        controller.start()
        self.assertEqual(len(live_mouse_hooks()), 1)

    def test_changing_the_shortcuts_adds_or_removes_the_hook(self):
        controller = self.controller({"push_to_talk": [["ctrl", "cmd"]]})
        controller.start()
        self.assertEqual(live_mouse_hooks(), [])
        controller.update_config({"push_to_talk": [["middle"]]})
        self.assertEqual(len(live_mouse_hooks()), 1, "binding a mouse button turns the hook on")
        with controller.lock:
            controller.pressed.add("middle")
        controller.update_config({"push_to_talk": [["ctrl", "cmd"]]})
        self.assertEqual(live_mouse_hooks(), [], "unbinding the last mouse button turns it off")
        self.assertNotIn("middle", controller.pressed, "a button the hook can no longer release is not held")

    def test_recording_a_shortcut_hooks_the_mouse_only_while_it_records(self):
        controller = self.controller({"push_to_talk": [["ctrl", "cmd"]]})
        controller.start()
        controller.record_shortcut(True)
        self.assertEqual(len(live_mouse_hooks()), 1, "a capture can record a mouse button")
        controller.record_shortcut(False)
        self.assertEqual(live_mouse_hooks(), [])

    def test_a_lapsed_recording_lease_removes_the_hook(self):
        controller = self.controller({"push_to_talk": [["ctrl", "cmd"]]})
        controller.start()
        controller.record_shortcut(True)
        with controller.lock:
            controller._shortcut_recording_until = time.monotonic() - 1  # the UI never said it ended
        deadline = time.monotonic() + 2.0
        while live_mouse_hooks() and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertEqual(live_mouse_hooks(), [], "the watchdog removes a hook nobody needs")

    def test_stop_removes_a_mouse_hook(self):
        controller = self.controller({"push_to_talk": [["mouse5"]]})
        controller.start()
        controller.stop()
        self.assertEqual(live_mouse_hooks(), [])


if __name__ == "__main__":
    unittest.main()
