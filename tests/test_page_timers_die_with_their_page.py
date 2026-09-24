from __future__ import annotations

import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "knight_flow" / "overlay.py"


class PageTimersDieWithTheirPageTests(unittest.TestCase):
    """A repeating timer inside a SHELL page must guard on one of its own
    widgets, never on the window.

    Before the shell (X-73) a page WAS a window, so `window.winfo_exists()`
    was a correct liveness check and this code was right. Afterwards the
    window outlives every page inside it, and two timers kept running against
    destroyed widgets for the rest of the session: the account refresh every
    700ms, and Mic Doctor's level meter fifteen times a second. Tk routes
    those exceptions to stderr, which a --windowed build throws away, so the
    only symptom a user could see was the CPU.

    Deliberately narrow. A broad "no timer may mention window" rule flags
    four callbacks that are already correct -- the toast checks identity, the
    settings header and the mic meter catch TclError, the sidebar slide is
    finite, and the captions window is not a shell page at all -- and a test
    that fails on correct code teaches people to edit the test.
    """

    def setUp(self) -> None:
        self.source = SOURCE.read_text(encoding="utf-8")

    def test_the_account_refresh_guards_on_its_own_widget(self) -> None:
        block = self.source[self.source.index("        def refresh() -> None:"):][:900]
        self.assertIn("if not sign_in.winfo_exists():", block)
        self.assertNotIn("if not window.winfo_exists():", block)

    def test_the_mic_meter_guards_on_its_own_canvas(self) -> None:
        method = self.source[self.source.index("    def open_mic_doctor(self)"):]
        block = method[method.index("        def poll():"):][:600]
        self.assertIn("level_bar.winfo_exists()", block)
        self.assertNotIn("window.winfo_exists()", block)

    def test_both_timers_still_reschedule_themselves(self) -> None:
        """The guard must not have been 'fixed' by deleting the timer."""
        self.assertIn("window.after(700, refresh)", self.source)
        self.assertIn("window.after(80,poll)", self.source)


if __name__ == "__main__":
    unittest.main()
