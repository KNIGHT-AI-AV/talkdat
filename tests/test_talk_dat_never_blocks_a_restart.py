"""X-606: Talk DAT! never blocks Windows from restarting, and a release smoke
never switches off Start with Windows.

2026-09-24, the owner's PC: Windows restarted at 06:29 and logged "Talk Dat!.exe
attempted to veto the shutdown". The web renderer's close handler cancels a
close to hide the Pill menu or to let Settings ask about a draft, and a
cancelled close while the session ends IS a veto. After the restart Talk DAT!
did not come back, and there was no Start with Windows shortcut: the release
smoke (install, reinstall, uninstall, restore) never put one back.
"""
from __future__ import annotations

import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from knight_flow.web_shell import shell_host

ROOT = Path(__file__).resolve().parents[1]


def _renderer(mode: str, *, ready: bool = True):
    api = shell_host._RendererApi(connection=None, mode=mode)
    api._window = SimpleNamespace(hide=lambda: None, evaluate_js=lambda _js: None)
    if ready:
        api._ready.set()
    return api


class NoWindowVetoesTheSessionEndTests(unittest.TestCase):
    def test_while_windows_is_ending_every_window_closes(self):
        for mode in ("menu", "settings"):
            with self.subTest(mode=mode), patch.object(shell_host, "session_is_ending", return_value=True), \
                 patch.object(threading, "Timer") as timer, patch.object(threading, "Thread") as thread:
                api = _renderer(mode)
                self.assertTrue(api._closing(), "a cancelled close during shutdown is a veto")
                timer.assert_not_called()
                thread.assert_not_called()

    def test_otherwise_the_menu_hides_and_settings_asks_first(self):
        with patch.object(shell_host, "session_is_ending", return_value=False), \
             patch.object(threading, "Timer"), patch.object(threading, "Thread"):
            self.assertFalse(_renderer("menu")._closing())
            self.assertFalse(_renderer("settings")._closing())

    def test_the_announced_session_end_is_remembered(self):
        shell_host._SESSION_ENDING.clear()
        try:
            shell_host._SESSION_ENDING.set()
            self.assertTrue(shell_host.session_is_ending())
        finally:
            shell_host._SESSION_ENDING.clear()


class TheSmokeLeavesShortcutsAsFoundTests(unittest.TestCase):
    def test_start_with_windows_and_the_other_shortcuts_are_restored_both_ways(self):
        script = (ROOT / "scripts" / "smoke_windows_installer.ps1").read_text(encoding="utf-8")
        snapshot = script.index("$ShortcutsBefore = @{}")
        uninstall = script.index('Write-Output "Uninstalling $ExpectedVersion..."')
        self.assertLess(snapshot, uninstall, "recorded before anything is touched")
        self.assertIn('"Startup\\Talk DAT!.lnk"', script)
        restore = script[script.index("Restoring the install this machine had"):]
        self.assertIn("CreateShortcut($path)", restore)
        self.assertIn("Remove-Item -LiteralPath $path", restore)


if __name__ == "__main__":
    unittest.main()
