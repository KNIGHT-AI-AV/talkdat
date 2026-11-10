from __future__ import annotations

import time
import unittest
from unittest import mock

from pathlib import Path

from knight_flow.mac_menu_bar import CHECK_ITEMS, MENU_LAYOUT, OFF, ON, UPDATE_FENCE, MacMenuBar
from knight_flow.tray import TrayController
from tests.tk_support import IS_MAC, acquire_root, probe_error, release_root


def tray_layout() -> list[tuple[str | None, str]]:
    """TrayController's menu, read from its code: (label, action) per item, (None, "") per separator. A label the
    tray computes (the update row) reads as "__update__", the name the menu bar gives it."""
    import ast
    import inspect
    import textwrap

    tree = ast.parse(textwrap.dedent(inspect.getsource(TrayController._run)))
    menu = next(node for node in ast.walk(tree) if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute) and node.func.attr == "Menu")
    layout: list[tuple[str | None, str]] = []
    for arg in menu.args:
        if isinstance(arg, ast.Attribute) and arg.attr == "SEPARATOR":
            layout.append((None, ""))
            continue
        label = arg.args[0].value if isinstance(arg.args[0], ast.Constant) else "__update__"
        call = arg.args[1].body
        layout.append((label, call.args[0].value))
    return layout


def tray_checks() -> set[str]:
    """The tray actions whose items are check items (checked=...)."""
    import ast
    import inspect
    import textwrap

    tree = ast.parse(textwrap.dedent(inspect.getsource(TrayController._run)))
    return {node.args[1].body.args[0].value for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "MenuItem"
            and any(keyword.arg == "checked" for keyword in node.keywords)}


class FakeEntry:
    """An NSMenuItem's three setters, recorded."""

    def __init__(self, title: str = "") -> None:
        self._title, self._state, self._hidden = title, 0, False

    def setTitle_(self, title: str) -> None:  # noqa: N802 - the AppKit name
        self._title = title

    def setState_(self, state: int) -> None:  # noqa: N802
        self._state = state

    def setHidden_(self, hidden: bool) -> None:  # noqa: N802
        self._hidden = bool(hidden)

    def title(self) -> str:
        return self._title

    def state(self) -> int:
        return self._state

    def isHidden(self) -> bool:  # noqa: N802
        return self._hidden


class FakeButton:
    def __init__(self) -> None:
        self.tooltip = ""

    def setToolTip_(self, text: str) -> None:  # noqa: N802
        self.tooltip = text


class FakeStatusItem:
    def __init__(self) -> None:
        self._button = FakeButton()

    def button(self) -> FakeButton:
        return self._button


class NowRoot:
    """A Tk root whose after() runs the call at once."""

    def after(self, _ms: int, call) -> None:
        call()


def built_bar() -> MacMenuBar:
    """A menu bar with fake AppKit entries in place, as _create leaves them, then its state applied once."""
    bar = MacMenuBar({})
    bar._root = NowRoot()
    bar._status_item = FakeStatusItem()
    bar._items = {label: FakeEntry(label) for label, _name in MENU_LAYOUT if label is not None}
    bar._items[UPDATE_FENCE] = FakeEntry()
    bar._apply_state()
    return bar


class TheMenuBarIsTheTraysMenuTests(unittest.TestCase):
    """Two implementations of one menu; they must not drift apart.

    Windows keeps pystray on a worker thread. macOS cannot: AppKit refuses to
    build an NSStatusItem off the main thread, and TrayController._run ends in a
    bare `except Exception: return`, so on macOS the icon silently never
    appeared. The replacement is a separate class, which is exactly the shape of
    thing that grows a different menu six months later -- and did: until 0.4.177
    the menu bar still had the tray's pre-IA layout (Show and Hide overlay, Status,
    Stats, Local models, Share an idea, and "Pause dictation" that flipped to
    "Resume dictation").
    """

    def test_the_menu_bar_is_the_trays_menu_item_for_item(self) -> None:
        """0.4.177 IA phase 2 (IA-SCHEMATIC.md section 2): the same items, names, order and groups as the tray."""
        self.assertEqual(list(MENU_LAYOUT), tray_layout())

    def test_the_check_items_are_the_trays(self) -> None:
        self.assertEqual(set(CHECK_ITEMS), tray_checks())
        self.assertEqual(set(CHECK_ITEMS), {"pause", "toggle_pill"})

    def test_pause_listening_is_a_check_whose_label_never_flips(self) -> None:
        """R6: the label never flips; the check says it is paused. "Resume dictation" is gone everywhere."""
        bar = built_bar()
        entry = bar._items["Pause listening"]
        self.assertEqual((entry.title(), entry.state()), ("Pause listening", OFF))
        bar.set_paused(True)
        self.assertEqual((entry.title(), entry.state()), ("Pause listening", ON))
        bar.set_paused(False)
        self.assertEqual((entry.title(), entry.state()), ("Pause listening", OFF))
        source = (Path(__file__).resolve().parents[1] / "knight_flow" / "mac_menu_bar.py").read_text(encoding="utf-8")
        self.assertNotIn("Resume dictation", source)
        self.assertNotIn("Pause dictation", source)

    def test_show_the_pill_is_a_check_that_follows_the_person(self) -> None:
        bar = built_bar()
        entry = bar._items["Show the Pill"]
        self.assertEqual(entry.state(), ON, "the Pill shows until the person hides it")
        bar.set_pill_shown(False)
        self.assertEqual((entry.title(), entry.state()), ("Show the Pill", OFF))
        bar.set_pill_shown(True)
        self.assertEqual(entry.state(), ON)

    def test_the_update_row_shows_only_while_an_update_waits(self) -> None:
        """Check for updates is on Home and Help now; the menu bar shows Install update only while one waits, and
        the fence under it hides with it, so no two dividers meet."""
        bar = built_bar()
        update, fence = bar._items["__update__"], bar._items[UPDATE_FENCE]
        self.assertTrue(update.isHidden())
        self.assertTrue(fence.isHidden())
        bar.set_update_available("0.5.0")
        self.assertEqual((update.title(), update.isHidden(), fence.isHidden()), ("Install update 0.5.0", False, False))
        bar.set_update_available("")
        self.assertTrue(update.isHidden())
        self.assertNotIn("Check for updates", {label for label, _name in MENU_LAYOUT})

    def test_the_icon_names_the_state_as_the_tray_does(self) -> None:
        """R18: Status left the menu; the icon's tooltip says ready or paused, word for word as the tray's."""
        bar, tray = built_bar(), TrayController({})
        self.assertEqual(bar._status_item.button().tooltip, tray.status_text())
        bar.set_paused(True)
        tray.paused = True
        self.assertEqual(bar._status_item.button().tooltip, tray.status_text())
        self.assertEqual(bar.status_text(), "Talk DAT!: paused")

    def test_every_action_has_its_apps_callback_name(self) -> None:
        """The callbacks the app hands over (app.py) carry every action the menu bar can run."""
        app = (Path(__file__).resolve().parents[1] / "knight_flow" / "app.py").read_text(encoding="utf-8")
        missing = [name for label, name in MENU_LAYOUT if label is not None and f'"{name}": self.' not in app]
        self.assertEqual(missing, [])

    def test_quit_is_present(self) -> None:
        """The app is LSUIElement on macOS: no Dock icon, no application menu.
        Without a Quit entry here the only way out is the Pill's context menu."""
        self.assertIn("quit", {name for _label, name in MENU_LAYOUT if name})

    def test_quit_names_the_menu_bar(self) -> None:
        """Every quit names the place that asked (0.4.176, H4's 7e25e3c): the tray's Quit says source=tray. On a
        Mac the menu bar is that place, so its Quit says source=menu_bar; every other entry still takes nothing."""
        quit_app, settings = mock.Mock(), mock.Mock()
        bar = MacMenuBar({"quit": quit_app, "settings": settings})
        bar._call("quit")
        bar._call("settings")
        quit_app.assert_called_once_with(source="menu_bar")
        settings.assert_called_once_with()

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
        expected = len([1 for label, _name in MENU_LAYOUT if label is not None]) + 1  # and the update's fence
        self.assertEqual(len(self.bar._items), expected)

    def test_the_checks_and_the_update_row_follow_the_state(self) -> None:
        self._start_and_wait()
        pause = self.bar._items["Pause listening"]
        self.assertEqual((pause.title(), pause.state()), ("Pause listening", OFF))
        self.bar.set_paused(True)
        self._settle()
        self.assertEqual((pause.title(), pause.state()), ("Pause listening", ON))
        self.assertTrue(self.bar._items["__update__"].isHidden())
        self.bar.set_update_available("0.5.0")
        self._settle()
        self.assertEqual(self.bar._items["__update__"].title(), "Install update 0.5.0")
        self.assertFalse(self.bar._items["__update__"].isHidden())

    def test_choosing_an_entry_runs_its_callback(self) -> None:
        self._start_and_wait()
        self.bar._call("settings")
        self.assertIn("settings", self.calls)


if __name__ == "__main__":
    unittest.main()
