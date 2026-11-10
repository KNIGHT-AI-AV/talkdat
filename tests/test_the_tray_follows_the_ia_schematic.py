"""The owner, 2026-11-06: an industry-standard menu architecture, "fully researched ... in the most ergonomic possible"
way. Phase 2 of the lane's map (IA-SCHEMATIC.md section 2, rules R5, R6 and R14-R18 of MENU-IA-RESEARCH.md): the tray.

Five groups: Open Talk DAT! (the default item), Start hands-free dictation, Pause listening (a check item whose label
never flips) and Cancel what's recording; History, Scratchpad and Translate; Show the Pill (checked while the Pill shows,
and it hides or shows it), Settings and Help; the install-update item, only while an update waits; Restart Talk DAT!,
Panic stop and, behind its own separator, Quit Talk DAT!. "More" is dissolved: Status goes to the icon's tooltip (which
names the state) and Help, Stats and Local models to Settings, Share an idea to Help. Cancel what's recording stays
visible at all times: the tray holds no recording state (a row shown only while recording is phase 4 if wanted).

The menu is read through a stand-in for pystray that keeps every option the tray passes and shows the items as pystray
does (hidden items dropped, a run of separators shown as one).
"""
from __future__ import annotations

import sys
import threading
import types
import unittest
from types import SimpleNamespace
from unittest import mock

from knight_flow.app import TalkDatApp
from knight_flow.tray import TrayController
from tests.capability_crosswalk import app_commands, tray_commands

IDLE = ["Open Talk DAT!", "Start hands-free dictation", "Pause listening", "Cancel what's recording", "-",
        "History", "Scratchpad", "Translate", "-",
        "Show the Pill", "Settings", "Help", "-",
        "Restart Talk DAT!", "Panic stop", "-", "Quit Talk DAT!"]
COMMANDS = {"Open Talk DAT!": "show", "Start hands-free dictation": "hands_free", "Pause listening": "pause",
            "Cancel what's recording": "cancel", "History": "history", "Scratchpad": "scratchpad",
            "Translate": "translation", "Show the Pill": "toggle_pill", "Settings": "settings", "Help": "help",
            "Install update v0.4.178": "install_update", "Restart Talk DAT!": "restart", "Panic stop": "panic",
            "Quit Talk DAT!": "quit"}


def stand_in():
    fake = types.ModuleType("pystray")
    seen = {}

    class MenuItem:
        def __init__(self, text, action, checked=None, radio=False, default=False, visible=True, enabled=True):
            self._text, self.action, self._checked, self.default, self._visible = text, action, checked, default, visible

        @property
        def text(self):
            return self._text(self) if callable(self._text) else self._text

        @property
        def checked(self):
            return None if self._checked is None else self._checked(self)

        @property
        def visible(self):
            return self._visible(self) if callable(self._visible) else bool(self._visible)

    class Menu:
        SEPARATOR = MenuItem("- - - -", None)

        def __init__(self, *items):
            self.items = items

    class Icon:
        def __init__(self, name, image, title, menu):
            self.name, self.title, self.menu, self.updates = name, title, menu, 0
            seen["icon"] = self

        def run(self):
            seen["ran"] = True

        def update_menu(self):
            self.updates += 1

    fake.MenuItem, fake.Menu, fake.Icon = MenuItem, Menu, Icon
    return fake, seen


def shown(icon, fake):
    """The labels pystray would draw: hidden items dropped, separators collapsed and trimmed."""
    out = []
    for item in icon.menu.items:
        if item is fake.Menu.SEPARATOR:
            if out and out[-1] != "-":
                out.append("-")
            continue
        if item.visible:
            out.append(item.text)
    while out and out[-1] == "-":
        out.pop()
    return out


def items(icon, fake):
    return {item.text: item for item in icon.menu.items if item is not fake.Menu.SEPARATOR}


class TheTrayMenuTests(unittest.TestCase):
    def tray(self, **callbacks):
        fake, seen = stand_in()
        tray = TrayController(callbacks)
        with mock.patch.dict(sys.modules, {"pystray": fake}), mock.patch("knight_flow.tray.make_tray_image"):
            tray._run()
        return tray, seen["icon"], fake

    def test_five_groups_with_open_first_and_quit_last(self):
        _tray, icon, fake = self.tray()
        self.assertEqual(shown(icon, fake), IDLE)

    def test_the_install_item_shows_only_while_an_update_waits(self):
        tray, icon, fake = self.tray()
        tray.set_update_available("v0.4.178")
        expected = IDLE[:IDLE.index("Restart Talk DAT!")] + ["Install update v0.4.178", "-"] + IDLE[IDLE.index("Restart Talk DAT!"):]
        self.assertEqual(shown(icon, fake), expected)
        tray.set_update_available("")
        self.assertEqual(shown(icon, fake), IDLE)

    def test_open_is_the_only_default_item(self):
        _tray, icon, fake = self.tray()
        self.assertEqual([label for label, item in items(icon, fake).items() if item.default], ["Open Talk DAT!"])

    def test_pause_listening_is_checked_while_paused_and_never_renamed(self):
        tray, icon, fake = self.tray()
        pause = items(icon, fake)["Pause listening"]
        self.assertIs(pause.checked, False)
        tray.set_paused(True)
        self.assertIs(pause.checked, True)
        self.assertEqual(pause.text, "Pause listening")
        self.assertIn("Pause listening", shown(icon, fake))

    def test_show_the_pill_is_checked_while_the_pill_shows(self):
        tray, icon, fake = self.tray()
        show = items(icon, fake)["Show the Pill"]
        self.assertIs(show.checked, True)
        tray.set_pill_shown(False)
        self.assertIs(show.checked, False)
        self.assertEqual(show.text, "Show the Pill")

    def test_more_is_dissolved(self):
        _tray, icon, fake = self.tray()
        self.assertEqual([item.text for item in icon.menu.items if isinstance(item.action, fake.Menu)], [])
        for gone in ("More", "Status", "Stats", "Local models", "Hide overlay", "Share an idea", "Check for updates"):
            self.assertNotIn(gone, items(icon, fake))

    def test_cancel_stays_visible_because_the_tray_holds_no_recording_state(self):
        tray, icon, fake = self.tray()
        tray.set_paused(True)
        self.assertIn("Cancel what's recording", shown(icon, fake))

    def test_the_tooltip_names_the_state_and_follows_it(self):
        tray, icon, _fake = self.tray()
        self.assertEqual(icon.title, "Talk DAT!: ready")
        tray.set_paused(True)
        self.assertEqual(icon.title, "Talk DAT!: paused")
        tray.set_paused(False)
        self.assertEqual(icon.title, "Talk DAT!: ready")

    def test_every_item_runs_its_command(self):
        called = []
        callbacks = {name: (lambda name=name, **kwargs: called.append((name, kwargs))) for name in set(COMMANDS.values())}
        tray, icon, fake = self.tray(**callbacks)
        tray.set_update_available("v0.4.178")
        for label, command in COMMANDS.items():
            with self.subTest(item=label):
                called.clear()
                items(icon, fake)[label].action(icon, items(icon, fake)[label])
                self.assertEqual(called, [(command, {"source": "tray"} if command == "quit" else {})])

    def test_the_crosswalk_reads_the_new_commands(self):
        self.assertTrue({"toggle_pill", "help"} <= set(tray_commands()))
        self.assertEqual(set(tray_commands()) & {"status", "stats", "local_models", "hide", "feature_idea"}, set())


class TheAppAnswersTheTrayTests(unittest.TestCase):
    def app(self):
        app = TalkDatApp.__new__(TalkDatApp)
        app.overlay = SimpleNamespace(_ui_thread_id=threading.get_ident(), hide=mock.Mock(), show=mock.Mock(),
                                      reveal_now=mock.Mock(return_value=True), open_home=mock.Mock(),
                                      open_status=mock.Mock(), root=SimpleNamespace(after=lambda _ms, fn: fn()))
        app.tray = mock.Mock()
        return app

    def test_the_registry_answers_show_the_pill_and_help(self):
        self.assertTrue({"toggle_pill", "help"} <= set(app_commands()))

    def test_show_the_pill_hides_it_then_shows_it_and_tells_the_tray(self):
        app = self.app()
        app.toggle_pill()
        app.overlay.hide.assert_called_once_with()
        app.tray.set_pill_shown.assert_called_with(False)
        app.toggle_pill()
        app.overlay.show.assert_called_once_with()
        app.tray.set_pill_shown.assert_called_with(True)

    def test_open_talk_dat_shows_the_pill_so_the_check_comes_back(self):
        app = self.app()
        app.toggle_pill()
        app.open_from_tray()
        app.tray.set_pill_shown.assert_called_with(True)
        app.toggle_pill()
        app.overlay.hide.assert_called_with()
        self.assertEqual(app.overlay.hide.call_count, 2, "after Open, Show the Pill hides it again")

    def test_help_opens_help_where_the_status_panel_lives(self):
        app = self.app()
        app.open_help()
        app.overlay.open_status.assert_called_once_with()

    def test_the_paused_message_names_the_row_that_resumes(self):
        app = TalkDatApp.__new__(TalkDatApp)
        app.overlay = mock.Mock()
        app.overlay._ui_thread_id = threading.get_ident()
        app.tray = mock.Mock()
        app.paused = False
        app.refresh_wake_word = lambda: None
        app.cancel = mock.Mock()
        app._finish_take_then = lambda *_args: False
        app.toggle_pause()
        title, detail = app.overlay.set_state.call_args.args[1:3]
        self.assertEqual(title, "Talk DAT! paused. Triggers are off.")
        self.assertEqual(detail, "To resume, choose Pause listening again in the Pill menu or the tray.")
        app.tray.set_paused.assert_called_with(True)


if __name__ == "__main__":
    unittest.main()
