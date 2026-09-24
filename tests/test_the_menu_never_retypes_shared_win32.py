"""X-605: the Pill menu's placement code never changes the app's shared Win32 bindings.

ctypes.windll.user32 is ONE object per process. shell_app._pill_anchor set
GetMonitorInfoW.argtypes on it to its own MonitorInfo class, so after the first
right-click every other caller -- overlay._active_monitor_work_area (which keeps
the Pill on the monitor you are using) and monitors.list_monitors -- passed its
own MONITORINFO and got ctypes.ArgumentError. The full suite logged it 51 times
on 0.4.159. Private WinDLL handles keep argtypes to the code that set them.
"""
from __future__ import annotations

import ctypes
import re
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SHELL = ROOT / "knight_flow" / "web_shell"


class NoSharedArgtypesTests(unittest.TestCase):
    def test_no_web_shell_module_sets_argtypes_on_the_shared_windll(self):
        for path in sorted(SHELL.glob("*.py")):
            source = path.read_text(encoding="utf-8")
            with self.subTest(file=path.name):
                self.assertIsNone(re.search(r"ctypes\.windll\.\w+\.\w+\.(argtypes|restype)", source))
                shared = re.findall(r"(\w+)\s*=\s*ctypes\.windll\.(\w+)\s*$", source, re.M)
                for name, _dll in shared:
                    self.assertIsNone(re.search(rf"\b{name}\.\w+\.(argtypes|restype)\s*=", source),
                                      f"{name} is ctypes.windll's shared handle")

    @unittest.skipUnless(sys.platform == "win32", "Win32 bindings")
    def test_placing_the_menu_leaves_the_shared_bindings_untouched(self):
        from knight_flow.web_shell.shell_app import AppShell

        shared = ctypes.windll.user32
        before = {name: getattr(shared, name).argtypes
                  for name in ("GetMonitorInfoW", "GetWindowRect", "GetAncestor", "MonitorFromWindow")}
        root = SimpleNamespace(winfo_rootx=lambda: 10, winfo_rooty=lambda: 20, winfo_width=lambda: 112,
                               winfo_height=lambda: 33, winfo_id=lambda: 0)
        shell = SimpleNamespace(overlay=SimpleNamespace(root=root, _logical_work_area=lambda: (0, 0, 800, 600)))
        AppShell._pill_anchor(shell, 60, 30)  # no real window: it falls back, after binding
        after = {name: getattr(shared, name).argtypes for name in before}
        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
