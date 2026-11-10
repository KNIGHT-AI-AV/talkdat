"""Field report 2026-11-05: starting Talk DAT froze the whole PC.

A low-level keyboard or mouse hook's callback runs in the process that installed it, and Windows holds
every key and mouse event on the machine until it returns. Measured the same day, the startup model load
locks every other Python thread in the app out for 7.1 s of a 7.4 s load (5.6 s in one stretch), so a
hook in the app's own process stalls the PC's input for that long. The hooks now run in a small helper
process that does nothing else: its callbacks only hand a name to a queue, and the app reads the names
from a pipe in order whenever it can. If the helper cannot start or goes away, the hooks come back into
the app so the shortcuts keep working.
"""
from __future__ import annotations

import os
import queue
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from knight_flow import hotkeys as hotkeys_module
from knight_flow import input_helper
from knight_flow.hotkeys import HotkeyController
from tests import fake_pynput  # noqa: F401  (the package the helper imports by name)
from tests.fake_pynput import keyboard as fake_keyboard
from tests.fake_pynput import mouse as fake_mouse

ROOT = Path(__file__).resolve().parents[1]


class Connection:
    """One end of the pipe, for serve() run on a thread. send() can be made to block."""

    def __init__(self):
        self.sent: "queue.Queue[tuple[str, str]]" = queue.Queue()
        self.inbox: "queue.Queue[object]" = queue.Queue()
        self.open = threading.Event()
        self.open.set()

    def send(self, item):
        self.open.wait()
        self.sent.put(item)

    def recv(self):
        item = self.inbox.get()
        if item is EOFError:
            raise EOFError
        return item

    def next_sent(self, timeout=2.0):
        return self.sent.get(timeout=timeout)


class TheHelperProcessHooksAndForwards(unittest.TestCase):
    def setUp(self):
        os.environ.pop("TALKDAT_FAKE_KEYS", None)
        fake_keyboard.LISTENERS.clear()
        fake_mouse.LISTENERS.clear()
        self.connection = Connection()
        self.served = threading.Thread(target=input_helper.serve, args=(self.connection, False, "tests.fake_pynput"), daemon=True)
        self.served.start()
        self.assertEqual(self.connection.next_sent(), ("ready", ""))

    def tearDown(self):
        self.connection.open.set()
        self.connection.inbox.put(EOFError)
        self.served.join(timeout=2.0)

    def test_a_key_travels_as_its_name(self):
        keys = fake_keyboard.LISTENERS[-1]
        keys.on_press(fake_keyboard.Key.ctrl_l)
        keys.on_release(fake_keyboard.Key.ctrl_l)
        self.assertEqual(self.connection.next_sent(), ("down", "ctrl"))
        self.assertEqual(self.connection.next_sent(), ("up", "ctrl"))

    def test_the_hook_never_waits_for_the_app(self):
        # The app is busy (here: its end of the pipe is not being read). The hook must answer at once.
        self.connection.open.clear()
        keys = fake_keyboard.LISTENERS[-1]

        def press_many():
            for _ in range(50):
                keys.on_press(fake_keyboard.Key.ctrl_l)
                keys.on_release(fake_keyboard.Key.ctrl_l)

        # On a thread of its own, so a callback that blocks fails this test instead of hanging it.
        presser = threading.Thread(target=press_many, daemon=True)
        presser.start()
        presser.join(timeout=0.5)
        self.assertFalse(presser.is_alive(), "a hook callback waited for the app")
        self.connection.open.set()
        self.assertEqual(self.connection.next_sent(), ("down", "ctrl"), "the names arrive once the app reads again")

    def test_the_mouse_hook_follows_the_app(self):
        self.assertEqual(fake_mouse.LISTENERS, [], "no mouse hook until the app asks for one")
        self.connection.inbox.put("mouse_on")
        deadline = time.monotonic() + 2.0
        while not fake_mouse.LISTENERS and time.monotonic() < deadline:
            time.sleep(0.01)
        buttons = fake_mouse.LISTENERS[-1]
        self.assertTrue(buttons.started)
        buttons.on_click(0, 0, fake_mouse.Button.x1, True)
        self.assertEqual(self.connection.next_sent(), ("down", "mouse4"))
        self.connection.inbox.put("mouse_off")
        deadline = time.monotonic() + 2.0
        while not buttons.stopped and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(buttons.stopped)

    def test_the_helper_unhooks_when_the_app_goes_away(self):
        keys = fake_keyboard.LISTENERS[-1]
        self.connection.inbox.put(EOFError)
        self.served.join(timeout=2.0)
        self.assertFalse(self.served.is_alive())
        self.assertTrue(keys.stopped)


class FakeHelper:
    made: list["FakeHelper"] = []

    def __init__(self, on_event, on_lost, **_options):
        self.on_event = on_event
        self.on_lost = on_lost
        self.mouse = False
        self.started_with = None
        self.mouse_calls: list[bool] = []
        self.stopped = False
        FakeHelper.made.append(self)

    def start(self, *, mouse):
        self.started_with = mouse
        self.mouse = mouse

    def set_mouse(self, on):
        self.mouse = on
        self.mouse_calls.append(on)

    def stop(self):
        self.stopped = True


class InProcessListener:
    made: list["InProcessListener"] = []

    def __init__(self, **callbacks):
        self.started = False
        InProcessListener.made.append(self)

    def start(self):
        self.started = True

    def stop(self):
        pass


class TheAppUsesTheHelper(unittest.TestCase):
    def setUp(self):
        FakeHelper.made = []
        InProcessListener.made = []
        patches = [
            mock.patch.object(input_helper, "InputHelper", FakeHelper),
            mock.patch.object(hotkeys_module.keyboard, "Listener", InProcessListener),
            mock.patch.object(hotkeys_module.mouse, "Listener", InProcessListener),
            mock.patch.object(HotkeyController, "_start_gamepad_poller", lambda self: None),
            mock.patch.object(HotkeyController, "_start_midi_listener", lambda self: None),
            mock.patch("knight_flow.hotkeys.physical_key_down", return_value=None),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.controllers: list[HotkeyController] = []

    def tearDown(self):
        for controller in self.controllers:
            controller.stop()

    def controller(self, layout, **options):
        controller = HotkeyController(layout, {}, **options)
        self.controllers.append(controller)
        return controller

    def test_the_keyboard_hook_is_not_in_the_app(self):
        controller = self.controller({"push_to_talk": [["ctrl", "cmd"]]}, input_process=True)
        controller.start()
        self.assertEqual(len(FakeHelper.made), 1)
        self.assertIs(FakeHelper.made[0].started_with, False)
        self.assertEqual(InProcessListener.made, [], "a hook was installed in the app's own process")

    def test_the_helpers_names_reach_the_shortcuts(self):
        controller = self.controller({"push_to_talk": [["ctrl", "cmd"]]}, input_process=True)
        controller.start()
        helper = FakeHelper.made[0]
        helper.on_event("down", "ctrl")
        helper.on_event("down", "cmd")
        self.assertEqual(controller.pressed, {"ctrl", "cmd"})
        helper.on_event("up", "cmd")
        self.assertEqual(controller.pressed, {"ctrl"})

    def test_the_helper_hooks_the_mouse_only_for_a_mouse_shortcut(self):
        controller = self.controller({"push_to_talk": [["mouse4"]]}, input_process=True)
        controller.start()
        helper = FakeHelper.made[0]
        self.assertIs(helper.started_with, True)
        helper.on_event("down", "mouse4")
        self.assertIn("mouse4", controller.pressed)
        controller.update_config({"push_to_talk": [["ctrl", "cmd"]]})
        self.assertEqual(helper.mouse_calls, [False])
        self.assertNotIn("mouse4", controller.pressed)
        self.assertEqual(InProcessListener.made, [])

    def test_a_lost_helper_brings_the_hooks_back(self):
        controller = self.controller({"push_to_talk": [["ctrl", "cmd"]]}, input_process=True)
        controller.start()
        with self.assertLogs("knight_flow.hotkeys", level="WARNING"):
            FakeHelper.made[0].on_lost()
        self.assertEqual(len(InProcessListener.made), 1, "the shortcuts must keep working")
        self.assertTrue(InProcessListener.made[0].started)

    def test_a_helper_that_cannot_start_leaves_the_hooks_in_the_app(self):
        def broken(*_args, **_kwargs):
            raise OSError("spawn failed")

        with mock.patch.object(input_helper, "InputHelper", broken):
            controller = self.controller({"push_to_talk": [["ctrl", "cmd"]]}, input_process=True)
            controller.start()
        self.assertEqual(len(InProcessListener.made), 1)

    def test_stop_ends_the_helper_and_its_names(self):
        controller = self.controller({"push_to_talk": [["ctrl", "cmd"]]}, input_process=True)
        controller.start()
        helper = FakeHelper.made[0]
        controller.stop()
        self.assertTrue(helper.stopped)
        helper.on_event("down", "ctrl")
        self.assertEqual(controller.pressed, set(), "a name after stop() was taken")

    def test_without_the_helper_the_hooks_stay_in_the_app(self):
        controller = self.controller({"push_to_talk": [["ctrl", "cmd"]]})
        controller.start()
        self.assertEqual(FakeHelper.made, [])
        self.assertEqual(len(InProcessListener.made), 1)


class TheRealPipe(unittest.TestCase):
    """The helper spawned for real (multiprocessing spawn, as the frozen app runs it), with fake listeners."""

    def setUp(self):
        os.environ["TALKDAT_FAKE_KEYS"] = "ctrl_l"
        self.addCleanup(os.environ.pop, "TALKDAT_FAKE_KEYS", None)
        self.events: "queue.Queue[tuple[str, str]]" = queue.Queue()
        self.lost = threading.Event()
        self.helper = input_helper.InputHelper(lambda kind, name: self.events.put((kind, name)), self.lost.set,
                                               listeners="tests.fake_pynput")
        self.addCleanup(self.helper.stop)
        self.helper.start(mouse=False)

    def test_a_key_arrives_through_the_pipe_and_stop_ends_the_process(self):
        self.assertEqual(self.events.get(timeout=60), ("down", "ctrl"))
        self.assertEqual(self.events.get(timeout=5), ("up", "ctrl"))
        self.assertTrue(self.helper.ready.wait(5))
        self.helper.stop()
        self.assertIsNotNone(self.helper.process.exitcode, "the helper process is still running")
        time.sleep(0.2)
        self.assertFalse(self.lost.is_set(), "a deliberate stop was reported as a loss")

    def test_a_helper_that_dies_is_reported(self):
        self.assertEqual(self.events.get(timeout=60), ("down", "ctrl"))
        self.helper.process.terminate()  # our own child, by its own handle
        self.assertTrue(self.lost.wait(10), "the app was not told its hooks are gone")


class TheAppStartsTheHelperOnWindows(unittest.TestCase):
    def test_the_app_asks_for_the_helper_on_windows(self):
        # TALKDAT_APP_SOURCE lets a mutation run point this at a changed copy.
        path = Path(os.environ.get("TALKDAT_APP_SOURCE") or ROOT / "knight_flow" / "app.py")
        source = path.read_text(encoding="utf-8")
        call = source[source.index("self.hotkeys = HotkeyController("):]
        call = call[:call.index("\n        )\n")]
        self.assertIn('input_process=sys.platform == "win32"', call)


if __name__ == "__main__":
    unittest.main()
