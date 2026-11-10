"""Every quit says who asked for it (2026-10-28, after two quits nobody could attribute).

Talk DAT quit at 2026-10-26 17:03:28Z and again at 2026-10-28 02:05:51Z. Both times
talk-dat.log said only "Talk DAT! quitting", the same line for the tray's Quit, the Pill
menu's Quit, a close sent to the Pill's window, the update install, a finished reset and a
restored backup. Telling them apart took records from outside the app, and even those
could not name the menu.

Now the line names the place that asked: "Talk DAT! quitting: source=tray". A quit that
first waits (for a take to land, for the settings question, for a microphone to close, or
for the UI thread) still names that place when it finally goes.
"""
from __future__ import annotations

import queue
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from knight_flow.overlay import Overlay
from knight_flow.tray import TrayController
from knight_flow.web_shell.reset_adapter import ResetActions
from tests import test_auxiliary_exit, test_backup_shell

ROOT = Path(__file__).resolve().parents[1]
QUIT_LINE = "Talk DAT! quitting"


def quitting_app(case: unittest.TestCase):
    """An app whose quit runs to the end: its wake listener has closed and nothing is landing."""
    fixture = test_auxiliary_exit.AuxiliaryExitTests()
    fixture.setUp()
    case.addCleanup(fixture.doCleanups)
    fixture.app.wake_listener.closed.set()
    saver = mock.patch("knight_flow.app.save_config")
    saver.start()
    case.addCleanup(saver.stop)
    return fixture.app


def quit_lines(case: unittest.TestCase, *steps) -> list[str]:
    """Run each step in order and return the quit lines the app logged, message only."""
    with case.assertLogs("knight_flow.app", "INFO") as logs:
        for step in steps:
            step()
    return [record.getMessage() for record in logs.records if QUIT_LINE in record.getMessage()]


class TheQuitLineNamesWhoAskedTests(unittest.TestCase):
    def test_the_line_names_the_place_that_asked(self) -> None:
        app = quitting_app(self)
        self.assertEqual(quit_lines(self, lambda: app.quit(source="tray")),
                         ["Talk DAT! quitting: source=tray"])

    def test_a_quit_nobody_named_says_so(self) -> None:
        app = quitting_app(self)
        self.assertEqual(quit_lines(self, app.quit), ["Talk DAT! quitting: source=unknown"])


class AQuitThatWaitsStillNamesWhoAskedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = quitting_app(self)

    def test_after_the_take_lands(self) -> None:
        held = []
        self.app._finish_take_then = mock.Mock(side_effect=lambda action, _name: held.append(action) or True)
        lines = quit_lines(self, lambda: self.app.quit(source="pill_menu"), lambda: held.pop()())
        self.assertEqual(lines, ["Talk DAT! quitting: source=pill_menu"])

    def test_after_the_settings_question(self) -> None:
        asked = []
        self.app.web_shell = mock.Mock()
        self.app.web_shell.confirm_exit.side_effect = lambda then: asked.append(then) or True
        lines = quit_lines(self, lambda: self.app.quit(source="tray"), lambda: asked.pop()())
        self.assertEqual(lines, ["Talk DAT! quitting: source=tray"])

    def test_after_a_microphone_closes(self) -> None:
        self.app.wake_listener.closed.clear()

        def closed_then_retry() -> None:
            self.app.wake_listener.closed.set()
            self.app.overlay.root.after.call_args.args[1]()

        lines = quit_lines(self, lambda: self.app.quit(source="restore"), closed_then_retry)
        self.assertEqual(lines, ["Talk DAT! quitting: source=restore"])

    def test_after_crossing_to_the_ui_thread(self) -> None:
        self.app._cross_thread_calls = queue.Queue()
        ui_thread = self.app.overlay._ui_thread_id
        self.app.overlay._ui_thread_id = -1

        def on_the_ui_thread() -> None:
            self.app.overlay._ui_thread_id = ui_thread
            self.app._cross_thread_calls.get_nowait()()

        lines = quit_lines(self, lambda: self.app.quit(source="update"), on_the_ui_thread)
        self.assertEqual(lines, ["Talk DAT! quitting: source=update"])


class EachPlaceNamesItselfTests(unittest.TestCase):
    @staticmethod
    def bare_overlay(**callbacks) -> Overlay:
        overlay = Overlay.__new__(Overlay)
        overlay.context_menu_target_hwnd = None
        overlay._close_context_menu = mock.Mock()
        overlay.callbacks = callbacks
        return overlay

    def test_the_tray(self) -> None:
        items = []
        fake = types.ModuleType("pystray")

        class MenuItem:
            def __init__(self, text, action, **_options) -> None:
                self.text, self.action = text, action
                items.append(self)

        class Menu:
            SEPARATOR = object()

            def __init__(self, *entries) -> None:
                self.entries = entries

        class Icon:
            def __init__(self, *_args) -> None:
                pass

            def run(self) -> None:
                pass

        fake.MenuItem, fake.Menu, fake.Icon = MenuItem, Menu, Icon
        quit_app = mock.Mock()
        tray = TrayController({"quit": quit_app})
        with mock.patch.dict(sys.modules, {"pystray": fake}), mock.patch("knight_flow.tray.make_tray_image"):
            tray._run()
        item = next(item for item in items if item.text == "Quit Talk DAT!")
        item.action(None, item)
        quit_app.assert_called_once_with(source="tray")

    def test_the_tray_still_crosses_to_the_ui_thread_with_its_name(self) -> None:
        quit_app, shipped = mock.Mock(), []
        TrayController({"quit": quit_app}, dispatch=shipped.append)._call("quit", source="tray")
        quit_app.assert_not_called()
        shipped[0]()
        quit_app.assert_called_once_with(source="tray")

    def test_the_pill_menu(self) -> None:
        quit_app, restart = mock.Mock(), mock.Mock()
        self.bare_overlay(quit=quit_app, restart=restart)._activate_context_menu_action("quit_app")
        quit_app.assert_called_once_with(source="pill_menu")
        restart.assert_not_called()

    def test_the_pill_menus_restart_is_unchanged(self) -> None:
        quit_app, restart = mock.Mock(), mock.Mock()
        self.bare_overlay(quit=quit_app, restart=restart)._activate_context_menu_action("restart_app")
        restart.assert_called_once_with()
        quit_app.assert_not_called()

    def test_a_close_sent_to_the_pills_window(self) -> None:
        quit_app = mock.Mock()
        self.bare_overlay(quit=quit_app).close()
        quit_app.assert_called_once_with(source="window_close")

    def test_a_finished_reset(self) -> None:
        posts = []
        app = SimpleNamespace(_reset_finished=True, quit=mock.Mock(),
                              _cross_thread_calls=SimpleNamespace(put=posts.append))
        ResetActions(SimpleNamespace(app=app), threads=lambda: []).finish()
        posts.pop()()
        app.quit.assert_called_once_with(settings_confirmed=True, source="reset")

    def test_a_restored_backup(self) -> None:
        backup = test_backup_shell.BackupShellTests()
        backup.setUp()
        self.addCleanup(backup.doCleanups)
        backup.call("restore_backup")
        backup.call("restore_backup_confirm")
        backup.app._cross_thread_calls.put.call_args.args[0]()
        backup.app.quit.assert_called_once_with(settings_confirmed=True, source="restore")


class TheClosuresOnlyALiveTkRootRunsNameThemselvesTests(unittest.TestCase):
    """The update install and the Tk restore and reset dialogs quit from closures that run
    only on a live Tk root, so their call sites are read from the source."""

    def test_the_update_install(self) -> None:
        source = (ROOT / "knight_flow" / "app.py").read_text(encoding="utf-8")
        self.assertIn('self.overlay.root.after(2200, lambda: self.quit(source="update"))', source)

    def test_the_tk_restore(self) -> None:
        source = (ROOT / "knight_flow" / "overlay.py").read_text(encoding="utf-8")
        block = source[source.index('messagebox.askyesno("Restore and quit?"'):]
        block = block[:block.index("except Exception as exc:")]
        self.assertIn('callback(source="restore")', block)

    def test_the_tk_reset_fallback(self) -> None:
        source = (ROOT / "knight_flow" / "overlay.py").read_text(encoding="utf-8")
        block = source[source.index('finish = self.callbacks.get("reset_finish")'):]
        block = block[:block.index('erase_button.configure(text="Close Talk DAT"')]
        self.assertIn('source="reset"', block)


if __name__ == "__main__":
    unittest.main()
