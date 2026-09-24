from __future__ import annotations

import time
import unittest

from knight_flow.mac_menu_bar import MENU_LAYOUT, MacMenuBar
from knight_flow.tray import TrayController
from tests.tk_support import IS_MAC, acquire_root, probe_error, release_root


class TheMenuBarOffersTheSameThingsAsTheTrayTests(unittest.TestCase):
    """Two implementations of one menu; they must not drift apart.

    Windows keeps pystray on a worker thread. macOS cannot: AppKit refuses to
    build an NSStatusItem off the main thread, and TrayController._run ends in a
    bare `except Exception: return`, so on macOS the icon silently never
    appeared. The replacement is a separate class, which is exactly the shape of
    thing that grows a different menu six months later.
    """

    def test_every_tray_action_is_reachable_from_the_menu_bar(self) -> None:
        tray_source = TrayController._run.__doc__ or ""
        del tray_source  # the menu lives in code, not the docstring; read it below
        import inspect

        source = inspect.getsource(TrayController._run)
        menu_bar_actions = {name for _label, name in MENU_LAYOUT if name}
        missing = [
            action
            for action in (
                "show", "hide", "hands_free", "pause", "cancel", "settings",
                "status", "stats", "history", "translation", "local_models",
                "scratchpad", "feature_idea", "install_update", "restart",
                "panic", "quit",
            )
            if f'"{action}"' in source and action not in menu_bar_actions
        ]
        self.assertEqual(
            missing, [],
            "these tray actions have no macOS menu bar entry, so Mac users cannot reach them",
        )

    def test_quit_is_present(self) -> None:
        """The app is LSUIElement on macOS: no Dock icon, no application menu.
        Without a Quit entry here the only way out is the Pill's context menu."""
        self.assertIn("quit", {name for _label, name in MENU_LAYOUT if name})

    def test_an_unknown_action_is_ignored_rather_than_raising(self) -> None:
        bar = MacMenuBar({})
        bar._call("no-such-action")  # must not raise

    def test_a_failing_action_does_not_escape_into_appkit(self) -> None:
        """The callback runs inside an Objective-C selector. An exception
        crossing that boundary terminates the process rather than unwinding."""
        def boom() -> None:
            raise RuntimeError("action failed")

        bar = MacMenuBar({"settings": boom})
        bar._call("settings")  # must not raise

    def test_starting_without_a_root_is_a_no_op(self) -> None:
        """Creating the status item off the Tk thread raises inside AppKit, so
        the class refuses rather than doing it on whatever thread called."""
        bar = MacMenuBar({})
        bar.start(None)
        self.assertIsNone(bar._status_item)


@unittest.skipUnless(IS_MAC, "the menu bar is macOS only")
@unittest.skipIf(probe_error is not None, "no usable Tk display")
class TheMenuBarIsBuiltForRealTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = acquire_root()
        self.addCleanup(lambda: release_root(self.root))
        self.calls: list[str] = []
        self.bar = MacMenuBar({name: (lambda n=name: self.calls.append(n))
                               for _label, name in MENU_LAYOUT if name})
        self.addCleanup(self.bar.stop)

    def _start_and_wait(self, timeout: float = 5.0) -> None:
        """Start the bar and pump Tk until the status item exists.

        start() schedules the real work with `after`, so the number of update()
        calls needed is not fixed -- the shared root carries state between tests
        and one pump is sometimes not enough. Waiting on the outcome rather than
        on a guessed number of pumps is what makes this deterministic.
        """
        self.bar.start(self.root)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.root.update()
            self.root.update_idletasks()
            if self.bar._status_item is not None:
                return
            time.sleep(0.02)
        self.fail("the status item was never created")

    def _settle(self) -> None:
        for _ in range(5):
            self.root.update()
            self.root.update_idletasks()
            time.sleep(0.02)

    def test_the_status_item_and_menu_are_created(self) -> None:
        self._start_and_wait()
        self.assertIsNotNone(self.bar._status_item, "no NSStatusItem was created")
        expected = len([1 for label, _name in MENU_LAYOUT if label is not None])
        self.assertEqual(len(self.bar._items), expected)

    def test_the_two_stateful_labels_follow_the_state(self) -> None:
        self._start_and_wait()
        self.assertEqual(self.bar._items["__pause__"].title(), "Pause dictation")
        self.bar.set_paused(True)
        self._settle()
        self.assertEqual(self.bar._items["__pause__"].title(), "Resume dictation")
        self.bar.set_update_available("0.5.0")
        self._settle()
        self.assertEqual(self.bar._items["__update__"].title(), "Install update 0.5.0")

    def test_choosing_an_entry_runs_its_callback(self) -> None:
        self._start_and_wait()
        self.bar._call("settings")
        self.assertIn("settings", self.calls)


if __name__ == "__main__":
    unittest.main()
