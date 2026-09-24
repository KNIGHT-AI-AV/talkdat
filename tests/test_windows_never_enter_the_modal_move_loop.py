"""The modal move loop is banned, permanently (0.4.121).

WM_NCLBUTTONDOWN from inside a Tk callback pumps this thread's messages
while the interpreter is mid-callback; timers re-enter, Tcl panics, the
process aborts (the c0000409 in every 0.4.118-0.4.120 crash report; caught
live via stderr capture 2026-08-21 at _begin_native_window_drag). The
geometry() drag is the one drag.

The function is kept as a documented stub so both call sites keep their
shape; this guard pins that it can never do anything again.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "knight_flow" / "overlay.py"


def code_only(text: str) -> str:
    text = re.sub(r'""".*?"""', "", text, flags=re.S)
    return re.sub(r"^\s*#.*$", "", text, flags=re.M)


class TheModalMoveLoopStaysDeadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = OVERLAY.read_text(encoding="utf-8")
        cls.code = code_only(cls.source)

    def test_the_stub_only_returns_false(self) -> None:
        body = re.search(
            r"def _begin_native_window_drag\(self, window: tk\.Toplevel\) -> bool:.*?(?=\n    def )",
            self.source, re.S,
        ).group(0)
        self.assertIn("return False", body)
        for banned in ("SendMessage", "0x00A1", "WM_NCLBUTTONDOWN", "ReleaseCapture", "ctypes"):
            with self.subTest(banned=banned):
                self.assertNotIn(banned, code_only(body))

    def test_nothing_else_reaches_for_the_loop(self) -> None:
        for banned in ("WM_NCLBUTTONDOWN", "0x00A1"):
            with self.subTest(banned=banned):
                self.assertNotIn(banned, self.code)

    def test_the_geometry_fallback_still_exists(self) -> None:
        """Retiring the native path only works because the pure-Tk drag
        remains wired at both call sites."""
        self.assertGreaterEqual(self.code.count("_begin_native_window_drag(window)"), 2)
        self.assertIn("utility_drag_origin", self.code)


if __name__ == "__main__":
    unittest.main()
