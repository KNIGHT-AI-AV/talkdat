"""The Tk sidebar's Stats row opens the web Stats page (owner's audit, 2026-09-23).

Every row of the Tk sidebar rail goes to the web shell when it works -- History,
Scratchpad, Translation, Words -- except Stats, whose opener built the old Tk
Stats window unconditionally (shot tk-stats-with-sidebar). Stats has a web page;
the Tk window stays as the fallback for when the web renderer cannot start,
exactly the contract open_history keeps.

Real Overlay, real Tk, on a hidden desktop via scripts/run_tests_offscreen.py.
"""
from __future__ import annotations

import copy
import time
import unittest

from knight_flow.config import DEFAULT_CONFIG
from tests import gui_offscreen  # noqa: F401  (X-164: never on a human's screen)
from tests.tk_support import probe_error as _ROOT_ERROR


def forget_default_root() -> None:
    """Tk binds every image made without a master to tkinter's default root.
    A root left behind by an earlier module would own this module's images
    ("image pyimageNN doesn't exist"), so each test starts and ends without
    one, as test_usage_counts_tk does."""
    import tkinter

    existing = getattr(tkinter, "_default_root", None)
    try:
        alive = existing is not None and bool(existing.winfo_exists())
    except Exception:
        alive = False
    if not alive:
        tkinter._default_root = None  # type: ignore[attr-defined]


def pump(root, seconds: float) -> None:
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        root.update()
        time.sleep(0.01)


@unittest.skipIf(_ROOT_ERROR is not None, f"no usable Tk display: {_ROOT_ERROR}")
class TheStatsRowTests(unittest.TestCase):
    def overlay(self, web_settings):
        from knight_flow.overlay import Overlay
        from tests.tk_support import acquire_root, release_root

        forget_default_root()
        self.addCleanup(forget_default_root)
        # macOS: one Tk root per process, ever (tests/tk_support). The Pill is a
        # Toplevel there, so destroying overlay.root left each test's hidden
        # Tk alive as the default root, and the next Overlay's images landed
        # in that dead interpreter ("image pyimageNN does not exist").
        overlay = Overlay(
            copy.deepcopy(DEFAULT_CONFIG), callbacks={"web_settings": web_settings}, root=acquire_root()
        )
        self.addCleanup(release_root, overlay._tk_root)
        pump(overlay.root, 0.3)
        return overlay

    def test_the_sidebar_row_opens_the_web_stats_page(self) -> None:
        opened: list[str] = []
        overlay = self.overlay(lambda page: opened.append(page) or True)
        rows = {action: callback for action, _title, callback in overlay._sidebar_destination_rows()}
        rows["stats"]()
        pump(overlay.root, 0.3)
        self.assertEqual(opened, ["stats"], "the Stats row did not ask the web shell for its page")
        window = overlay.utility_windows.get("stats")
        self.assertTrue(window is None or not window.winfo_exists(), "the old Tk Stats window opened anyway")

    def test_the_tk_window_is_only_the_fallback(self) -> None:
        overlay = self.overlay(lambda page: False)
        overlay.open_stats()
        pump(overlay.root, 0.6)
        window = overlay.utility_windows.get("stats")
        self.assertIsNotNone(window, "with no web shell, Stats must still open somewhere")
        self.assertTrue(window.winfo_exists())


if __name__ == "__main__":
    unittest.main()
