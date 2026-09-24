"""X-284: tray clicks marshal to the Tk thread, and the menu earns its order.

Reported as "my app keeps freezing and crashing" with a BEX64/c0000409 abort
in ucrtbase (2026-08-20 17:26) -- alongside "revamp the system tray right
click menu". They are the same defect. pystray runs its menu on its own win32
thread, TrayController._call invoked the app callback directly on that
thread, and most tray items open Tk windows. Tk touched cross-thread is the
access violation preserved in %APPDATA%/TalkDat/crash-traceback.log: tray
thread alive inside pystray's _mainloop while the fault landed under the Tk
mainloop.

The tell that this was half-known: exactly ONE callback (feature_idea) had
been wrapped in `root.after(0, ...)` at its call site. One patched menu item
is a symptom log. The fix lives in the layer: TrayController now takes a
`dispatch` callable and routes EVERY click through it; the app injects
`root.after(0, fn)`.

These are behaviour tests where behaviour is testable (TrayController is
plain Python -- no pystray import happens until the icon thread starts), and
source pins only where wiring lives in app.py.

X-294 (2026-08-21, "Crashing on PC every click of the menu"): the X-284
marshal was NOT ENOUGH, and the armed dump said why. root.after(0, fn) is
itself a Tcl call, so the marshal still entered Tcl from pystray's thread --
and worse, Python's cyclic collector runs on whichever thread allocates the
700th object. A menu click's own allocations triggered collection ON THE
TRAY THREAD, the collector freed dead tkinter objects there (the overlay
animates, so dead Tk cycles always exist), Tcl panicked at the wrong-thread
touch and called C abort(): the c0000409 fail-fast that faulthandler cannot
see. Read straight from the minidump stack: libffi ctypes wndproc (pystray)
-> _tkinter -> tcl86t Tcl_Panic -> ucrtbase abort, with python313 GC frames
between. Two fixes, both load-bearing:

  * the dispatcher is now a PLAIN queue.put -- the tray thread never enters
    Tcl at all; the Tk thread drains the queue on a 40ms clock
  * automatic gc is disabled at construction and cycle collection happens
    only on the Tk thread, on a timer -- so NO background thread (pystray,
    pynput, audio) can ever free a Tk object again

WHAT THIS CANNOT PROVE: how the menu feels under a real mouse, or that no
OTHER code path frees Tk objects off-thread by plain refcount. It proves the
tray thread's entire vocabulary is queue.put, the collector cannot run
uninvited, the Tk thread drains and collects on its own clock, and the menu
keeps its designed shape.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from knight_flow.tray import TrayController

ROOT = Path(__file__).resolve().parents[1]
TRAY = ROOT / "knight_flow" / "tray.py"
APP = ROOT / "knight_flow" / "app.py"


class EveryClickCrossesToTheUiThreadTests(unittest.TestCase):
    def test_a_dispatcher_receives_the_callback_instead_of_it_running(self) -> None:
        ran, shipped = [], []
        tray = TrayController({"settings": lambda: ran.append("direct")},
                              dispatch=shipped.append)
        tray._call("settings")
        self.assertEqual(ran, [], "the callback ran on the tray thread despite a dispatcher")
        self.assertEqual(len(shipped), 1, "the callback never reached the dispatcher")
        shipped[0]()
        self.assertEqual(ran, ["direct"], "the dispatched callable is not the callback")

    def test_without_a_dispatcher_calls_stay_direct(self) -> None:
        """Headless and test constructions keep working."""
        ran = []
        TrayController({"quit": lambda: ran.append(1)})._call("quit")
        self.assertEqual(ran, [1])

    def test_an_unknown_name_is_a_no_op_either_way(self) -> None:
        shipped = []
        TrayController({}, dispatch=shipped.append)._call("nope")
        self.assertEqual(shipped, [], "an unknown item must not dispatch None")

    def test_the_dispatcher_is_a_plain_queue_put(self) -> None:
        """X-294: root.after(0, fn) was a Tcl call made from the tray thread.
        The only safe dispatcher is one that touches no Tcl: queue.put."""
        source = APP.read_text(encoding="utf-8")
        wiring = re.search(
            r"TrayController\(\s*callbacks,\s*dispatch=self\._cross_thread_calls\.put,?\s*\)",
            source,
        )
        self.assertIsNotNone(wiring, "the tray dispatcher is no longer the plain queue put")
        self.assertNotIn(
            "dispatch=lambda fn: self.overlay.root.after", source,
            "the old Tcl-entering dispatcher is back",
        )

    def test_no_menu_item_calls_back_without_going_through_call(self) -> None:
        """A future item wired straight to a callback would sidestep the
        dispatcher and reopen the crash."""
        source = TRAY.read_text(encoding="utf-8")
        for handler in re.findall(r"pystray\.MenuItem\([^,]+, (lambda [^)]+\))", source):
            with self.subTest(handler=handler):
                self.assertIn("self._call(", handler)


class TheMenuKeepsItsDesignedShapeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = TRAY.read_text(encoding="utf-8")

    def test_open_is_the_default_item(self) -> None:
        """Double-clicking the tray icon opens the overlay without the menu."""
        self.assertRegex(
            self.source,
            r'"Open Talk DAT!", lambda [^)]+\.\_?call\("show"\),\s*\n\s*default=True',
        )

    def test_the_dangerous_pair_sits_fenced_at_the_bottom(self) -> None:
        """Panic and Quit are the two items a sliding hand must not hit on
        the way to something routine; they come last, behind a separator."""
        panic = self.source.index('"Panic stop"')
        quit_ = self.source.index('"Quit Talk DAT!"')
        for name in ('"History"', '"Settings"', '"Hands-free dictation"', 'self._update_label'):
            self.assertLess(self.source.index(name), panic, name + " sits below Panic")
        self.assertLess(panic, quit_, "Quit is the very last item")

    def test_rare_rooms_live_under_more(self) -> None:
        more = self.source[self.source.index("more = pystray.Menu("):self.source.index("menu = pystray.Menu(")]
        for name in ('"Status"', '"Stats"', '"Local models"', '"Hide overlay"',
                     '"Share an idea"', '"Restart Talk DAT!"'):
            with self.subTest(item=name):
                self.assertIn(name, more)

    def test_the_dynamic_labels_survive(self) -> None:
        """Pause/Resume and the update item are the two stateful labels; a
        static string here would lie about the running state."""
        self.assertIn("pystray.MenuItem(self._pause_label,", self.source)
        self.assertIn("pystray.MenuItem(self._update_label,", self.source)


class TheTkThreadOwnsTheGarbageTests(unittest.TestCase):
    """X-294: the collector free-running on background threads was the crash."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = APP.read_text(encoding="utf-8")

    def test_automatic_collection_dies_before_any_thread_exists(self) -> None:
        init = self.source.index("def __init__(self, project_root")
        disable = self.source.index("gc.disable()")
        tray = self.source.index("TrayController(")
        self.assertGreater(disable, init, "gc.disable() must live in __init__")
        self.assertLess(
            disable, tray,
            "gc must be disabled before the first background thread can exist",
        )

    def test_the_tk_thread_collects_on_a_timer(self) -> None:
        body = re.search(
            r"def _collect_garbage_on_tk_thread\(self\) -> None:.*?\n    def ",
            self.source, re.S,
        ).group(0)
        self.assertIn("gc.collect(", body)
        self.assertIn("_collect_garbage_on_tk_thread)", body, "the pass must re-arm itself")
        self.assertIn("% 15 == 0 else 1", body, "the full-heap pass must still happen")

    def test_the_drain_loop_runs_the_callbacks_and_rearms(self) -> None:
        body = re.search(
            r"def _drain_cross_thread_calls\(self\) -> None:.*?\n    def ",
            self.source, re.S,
        ).group(0)
        self.assertIn("get_nowait()", body)
        self.assertIn("fn()", body)
        self.assertIn("queue.Empty", body)
        self.assertIn("_drain_cross_thread_calls)", body, "the drain must re-arm itself")

    def test_run_arms_both_loops_before_the_mainloop(self) -> None:
        drain = self.source.index("self._drain_cross_thread_calls()")
        collect = self.source.index("self._collect_garbage_on_tk_thread()")
        mainloop = self.source.index("self.overlay.run()")
        self.assertLess(drain, mainloop)
        self.assertLess(collect, mainloop)

    def test_a_failing_callback_cannot_kill_the_drain(self) -> None:
        """One bad menu item must not end tray service for the session."""
        body = re.search(
            r"def _drain_cross_thread_calls\(self\) -> None:.*?\n    def ",
            self.source, re.S,
        ).group(0)
        self.assertIn("except Exception:", body)
        self.assertIn("log.exception", body)


if __name__ == "__main__":
    unittest.main()
