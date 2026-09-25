"""X-634 (interaction grid d4): a left-click on the tray icon opens Talk DAT!.

pystray runs the menu's default item on a left-click (WM_LBUTTONUP), and the
default item, "Open Talk DAT!" (the "show" callback), only re-showed the
Pill, which is already on screen: the click looked dead. It still brings back
a minimized utility window first; with nothing to bring back it now opens
Home.
"""
from __future__ import annotations

import re
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from knight_flow.app import TalkDatApp

ROOT = Path(__file__).resolve().parents[1]


class TheTrayClickTests(unittest.TestCase):
    def test_the_default_item_is_show_and_show_opens_talk_dat(self) -> None:
        tray = (ROOT / "knight_flow" / "tray.py").read_text(encoding="utf-8")
        self.assertRegex(tray, r'"Open Talk DAT!", lambda [^)]+\._call\("show"\),\s*\n\s*default=True')
        app = (ROOT / "knight_flow" / "app.py").read_text(encoding="utf-8")
        self.assertTrue(re.search(r'"show":\s*self\.open_from_tray', app), "the tray's Open still only shows the Pill")


class TheAppOpensHomeTests(unittest.TestCase):
    def app(self, *, restored: bool):
        app = TalkDatApp.__new__(TalkDatApp)
        app.overlay = SimpleNamespace(_ui_thread_id=threading.get_ident(),
                                      reveal_now=mock.Mock(return_value=restored), open_home=mock.Mock())
        return app

    def test_with_nothing_minimized_home_opens(self) -> None:
        app = self.app(restored=False)
        app.open_from_tray()
        app.overlay.reveal_now.assert_called_once()
        app.overlay.open_home.assert_called_once()

    def test_a_minimized_window_comes_back_instead(self) -> None:
        app = self.app(restored=True)
        app.open_from_tray()
        app.overlay.open_home.assert_not_called()

    def test_no_home_over_a_take_in_flight(self) -> None:
        """X-634b: Home would take the focus the words are about to go to."""
        app = self.app(restored=False)
        app.lock = threading.Lock()
        app.session = None
        app.session_token = object()
        app.open_from_tray()
        app.overlay.reveal_now.assert_called_once()
        app.overlay.open_home.assert_not_called()


if __name__ == "__main__":
    unittest.main()
