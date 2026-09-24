"""X-181: a window's buttons must actually be on the window.

Found by an exhaustive capability sweep and confirmed independently. Two windows,
Stats and What's New, packed their button row AFTER a frame with
`fill="both", expand=True`, inside a window with a fixed geometry.

Tk gives an expanding child every pixel left over. So once the content was tall
enough to fill the window -- which for What's New is any release notes of normal
length, and for Stats is always -- the button row was allotted zero height and
never mapped. Refresh, Close and View release simply were not there.

Both windows carry only a custom titlebar, so there is no system close button
either. Escape still worked, which is precisely why this survived: the window
could always be dismissed, so nothing ever felt broken enough to report.

`winfo_ismapped()` is the assertion that matters. A widget that has been created
and packed still reports `winfo_exists()` truthfully while occupying no space at
all, so existence proves nothing here. Only being MAPPED means a person can see
and click it, which is why this test builds the real windows instead of reading
the source.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest

if sys.platform == "win32":
    from tests import gui_offscreen  # noqa: F401  (never on a human's screen)

try:
    import tkinter as tk
    from tkinter import ttk
except Exception:  # pragma: no cover - headless CI without Tk
    tk = None  # type: ignore[assignment]


def pump(root, seconds: float = 1.0) -> None:
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        root.update()
        time.sleep(0.01)


def buttons_in(widget) -> list:
    found = []
    for child in widget.winfo_children():
        if isinstance(child, ttk.Button):
            found.append(child)
        found.extend(buttons_in(child))
    return found


@unittest.skipIf(tk is None, "tkinter unavailable")
class EveryWindowsButtonsAreVisibleTests(unittest.TestCase):
    def setUp(self) -> None:
        # X-181: clear the stale pointer on the way IN as well as out.
        # Cleaning up after ourselves is not enough: these modules run inside a
        # 1600-test suite, and ANY earlier module that built and destroyed a Tk
        # root leaves `tk._default_root` pointing at a dead interpreter. Every
        # PhotoImage our window then creates fails with
        # `image "pyimageNNN" does not exist`. Run alone, both files pass; run
        # after the rest of the suite, they errored six times. Defend at the
        # boundary we control, which is our own setUp.
        try:
            existing = getattr(tk, "_default_root", None)
            if existing is not None and not existing.winfo_exists():
                tk._default_root = None  # type: ignore[attr-defined]
        except Exception:
            try:
                tk._default_root = None  # type: ignore[attr-defined]
            except Exception:
                pass
        self._previous_home = os.environ.get("TALK_DAT_HOME")
        os.environ["TALK_DAT_HOME"] = tempfile.mkdtemp(prefix="talkdat-buttons-")
        from knight_flow.config import load_config
        from knight_flow.overlay import Overlay

        self.overlay = Overlay(load_config(), callbacks={})
        pump(self.overlay.root, 0.4)

    def tearDown(self) -> None:
        try:
            self.overlay.root.destroy()
        except Exception:
            pass
        # Tk binds an image with no explicit master to `tk._default_root`. When a
        # test destroys its root and the next one builds a fresh Overlay, that
        # pointer can still reference the DEAD interpreter, and every PhotoImage
        # the new window makes fails with `image "pyimageNNN" does not exist`.
        #
        # Windows hid this because gui_offscreen changes when windows map; the
        # Mac, which does not use it, failed six tests. Clearing the pointer is
        # what makes a per-test root safe.
        try:
            tk._default_root = None  # type: ignore[attr-defined]
        except Exception:
            pass
        if self._previous_home is None:
            os.environ.pop("TALK_DAT_HOME", None)
        else:
            os.environ["TALK_DAT_HOME"] = self._previous_home

    def _assert_buttons_mapped(self, window, expected_labels: set[str]) -> None:
        pump(self.overlay.root, 1.0)
        self.overlay.root.update_idletasks()
        buttons = buttons_in(window)
        self.assertTrue(buttons, "the window has no ttk buttons at all")
        labels = {str(button.cget("text")) for button in buttons}
        missing = expected_labels - labels
        self.assertEqual(missing, set(), f"these buttons were never created: {missing}")

        unmapped = sorted(
            str(button.cget("text"))
            for button in buttons
            if str(button.cget("text")) in expected_labels and not button.winfo_ismapped()
        )
        self.assertEqual(
            unmapped, [],
            "these buttons exist but occupy no space, so nobody can click them; "
            "the usual cause is an expand=True frame packed before the button "
            f"row in a fixed-size window: {unmapped}",
        )

    def test_whats_new_shows_its_buttons_with_long_notes(self) -> None:
        """Long notes are the trigger: they fill the expanding body completely."""
        notes = "\n".join(f"## Section {n}\n- a change worth reading about" for n in range(40))
        self.overlay.open_whats_new("0.4.100-beta", "0.4.109-beta", notes, "https://example.invalid/r")
        window = self.overlay.utility_windows.get("whats_new")
        self.assertIsNotNone(window, "What's New did not open")
        self._assert_buttons_mapped(window, {"View release", "Close"})

    def test_stats_shows_its_buttons(self) -> None:
        self.overlay.open_stats()
        window = self.overlay.utility_windows.get("stats")
        self.assertIsNotNone(window, "Stats did not open")
        self._assert_buttons_mapped(window, {"Refresh", "Close"})

    def test_the_check_can_tell_mapped_from_merely_existing(self) -> None:
        """Proves the assertion is worth making.

        A button packed after an expanding sibling in a fixed-size window exists
        and reports its text correctly while occupying no space. If
        `winfo_ismapped` did not distinguish that, every test above would pass on
        a broken window.
        """
        window = tk.Toplevel(self.overlay.root)
        window.geometry("200x80")
        try:
            hungry = tk.Frame(window, height=4000)
            hungry.pack(fill="both", expand=True)
            starved = ttk.Button(window, text="Squeezed")
            starved.pack()
            pump(self.overlay.root, 0.5)
            self.overlay.root.update_idletasks()
            self.assertTrue(starved.winfo_exists(), "the control should still exist")
            self.assertFalse(
                starved.winfo_ismapped(),
                "winfo_ismapped cannot detect a squeezed-out control here, so these "
                "tests would pass on a window with no reachable buttons",
            )
        finally:
            window.destroy()


if __name__ == "__main__":
    unittest.main()
