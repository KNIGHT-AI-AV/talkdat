"""X-182/X-207: a shell page gets its own size without a blank page swap.

Page utilities present as one stable application shell. A fresh hidden Toplevel
is now built at the outgoing page's box and crossfaded only after its layout
completes; the previous same-Toplevel child destruction blocked Tk for about a
second and exposed a transparent shell. The physical surface may change, but
its visual box and page-size contract may not jump.

Concretely: open Settings first and it is roomy; open the trial dialog first and
then Settings, and Settings is cramped into the dialog's box with its own minimum
size never applied. Nothing about it is random, which is exactly why it read as
random.

The fix is grow-only on purpose. X-73's promise is that the window does not jump
between pages, so shrinking each page to its design size would undo that and
would also fight anyone who had resized the window themselves. Growing to fit
gives every page at least the room it was designed for while the position holds.

Run in its own interpreter by tests/test_gui_regressions.py -- see that file for
why real-window tests cannot share a process.
"""

from __future__ import annotations

from knight_flow.flat_button import FlatButton  # tk.Button off macOS; a styled Label on Aqua

import os
import sys
import tempfile
import time
import unittest
from unittest import mock

if sys.platform == "win32":
    from tests import gui_offscreen  # noqa: F401

try:
    import tkinter as tk
    from tkinter import ttk
except Exception:  # pragma: no cover
    tk = None  # type: ignore[assignment]
    ttk = None  # type: ignore[assignment]


def pump(root, seconds: float = 0.8) -> None:
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        root.update()
        time.sleep(0.01)


@unittest.skipIf(tk is None, "tkinter unavailable")
class APageIsTheSameSizeWhicheverOrderYouOpenItTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        """ONE Tk root for the whole class.

        Each test needs a clean SHELL, not a clean interpreter, and those are
        different things. Building an Overlay per test means a Tk root per test,
        and the second one's images fail against the first's dead interpreter
        (`image "pyimageNNN" does not exist`) -- which is exactly how this module
        failed on the Mac while passing on Windows.

        `_drop_the_shell` gives the clean shell each test actually wants.
        """
        cls._previous_home = os.environ.get("TALK_DAT_HOME")
        os.environ["TALK_DAT_HOME"] = tempfile.mkdtemp(prefix="talkdat-shell-")
        from knight_flow.config import load_config
        from knight_flow.overlay import Overlay

        cls.overlay = Overlay(load_config(), callbacks={})
        pump(cls.overlay.root, 0.4)

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            cls.overlay.root.destroy()
        except Exception:
            pass
        try:
            tk._default_root = None  # type: ignore[attr-defined]
        except Exception:
            pass
        if cls._previous_home is None:
            os.environ.pop("TALK_DAT_HOME", None)
        else:
            os.environ["TALK_DAT_HOME"] = cls._previous_home

    def setUp(self) -> None:
        # A clean shell per test, without a second interpreter.
        self._drop_the_shell()

    def _open_settings_size(self) -> tuple[int, int]:
        self.overlay.open_settings()
        pump(self.overlay.root, 1.2)
        window = self.overlay.utility_windows.get("settings")
        self.assertIsNotNone(window, "Settings did not open")
        window.update_idletasks()
        return int(window.winfo_width()), int(window.winfo_height())

    def _drop_the_shell(self) -> None:
        """Destroy the shared Toplevel so the next page builds a fresh one.

        The defect only appears when the SMALL page is the first to size a shell,
        so the test needs a clean shell twice. Destroying just the shell keeps ONE
        Tk root: building a second root in the same process makes every later
        image fail with `image "pyimageNNN" does not exist`, which is how the
        first version of this test broke on the Mac.
        """
        shell = getattr(self.overlay, "_shell_window", None)
        if shell is not None:
            try:
                shell.destroy()
            except Exception:
                pass
        self.overlay._shell_window = None
        self.overlay.utility_windows.clear()
        pump(self.overlay.root, 0.4)

    def test_settings_is_not_shrunk_by_a_smaller_page_opened_first(self) -> None:
        """The reported shape, and the order matters: SMALL page first.

        Stats is itself a shell page, so opening it second changes nothing -- the
        window simply keeps the size Settings already gave it. The defect is that
        a shell first sized by a small page then imposes that size on a large one.
        """
        designed_w, designed_h = self._open_settings_size()
        self.assertGreater(designed_w, 200, "Settings did not size at all")

        self._drop_the_shell()

        self.overlay.open_stats()
        pump(self.overlay.root, 1.0)
        after_w, after_h = self._open_settings_size()

        self.assertGreaterEqual(
            after_w, designed_w,
            "Settings opened narrower because a smaller page sized the shell first; "
            "the incoming page's size contract was not applied",
        )
        self.assertGreaterEqual(
            after_h, designed_h,
            "Settings opened shorter because a smaller page sized the shell first",
        )

    def test_the_window_does_not_move_between_pages(self) -> None:
        """Grow-only must not cost X-73: the window stays where it was put."""
        self.overlay.open_settings()
        pump(self.overlay.root, 1.2)
        window = self.overlay.utility_windows.get("settings")
        window.update_idletasks()
        before = (int(window.winfo_rootx()), int(window.winfo_rooty()))

        self.overlay.open_history()
        pump(self.overlay.root, 1.0)
        shell = self.overlay.utility_windows.get("history") or window
        shell.update_idletasks()
        after = (int(shell.winfo_rootx()), int(shell.winfo_rooty()))

        for axis, (was, now) in enumerate(zip(before, after)):
            with self.subTest(axis="x" if axis == 0 else "y"):
                self.assertLessEqual(
                    abs(now - was), 8,
                    "the shell jumped position between pages; X-73 requires it to stay put",
                )


    def test_a_grown_page_stays_inside_the_screen(self) -> None:
        """X-191: growing must not push a window off the edge.

        `_utility_geometry` clamps the SIZE to the work area, and the grow-only
        resize then applied that size at the window's current origin. A shell
        sitting near the bottom-right therefore grew straight off the screen,
        taking its footer buttons with it. Growing is the point, so the window is
        pulled back rather than refused.
        """
        self._drop_the_shell()
        self.overlay.open_stats()
        pump(self.overlay.root, 0.8)

        shell = getattr(self.overlay, "_shell_window", None)
        self.assertIsNotNone(shell, "no shell to test")
        work = self.overlay._pill_monitor_work_area()
        if work is None:
            self.skipTest("no work area reported on this display")
        left, top, right, bottom = work

        # Park it hard against the bottom-right corner, then open a bigger page.
        shell.geometry(f"{shell.winfo_width()}x{shell.winfo_height()}"
                       f"+{max(left, right - shell.winfo_width() - 4)}"
                       f"+{max(top, bottom - shell.winfo_height() - 4)}")
        pump(self.overlay.root, 0.5)
        parked_x = int(shell.winfo_rootx())
        parked_y = int(shell.winfo_rooty())

        self.overlay.open_settings()
        pump(self.overlay.root, 1.4)
        window = self.overlay.utility_windows.get("settings")
        window.update_idletasks()

        self.assertIsNot(window, shell, "navigation reused the heavy visible Tk tree")
        expected_x = min(max(left + 8, parked_x), max(left + 8, right - int(window.winfo_width()) - 8))
        expected_y = min(max(top + 8, parked_y), max(top + 8, bottom - int(window.winfo_height()) - 8))
        self.assertLessEqual(abs(int(window.winfo_rootx()) - expected_x), 1)
        self.assertLessEqual(abs(int(window.winfo_rooty()) - expected_y), 1)
        self.assertIsNone(
            getattr(window, "_talkdat_pending_page_geometry", None),
            "the one-shot page geometry survived presentation and can snap a later move",
        )

        far_right = int(window.winfo_rootx()) + int(window.winfo_width())
        far_bottom = int(window.winfo_rooty()) + int(window.winfo_height())
        self.assertLessEqual(
            far_right, right + 1,
            "the page grew past the right edge of the screen, so its right-hand "
            "controls are unreachable",
        )
        self.assertLessEqual(
            far_bottom, bottom + 1,
            "the page grew past the bottom of the screen, so its footer buttons "
            "are unreachable",
        )

    def test_navigation_keeps_the_old_page_visible_until_destination_layout(self) -> None:
        self.overlay.open_settings()
        pump(self.overlay.root, 1.2)
        old = self.overlay.utility_windows["settings"]
        old.update_idletasks()

        started = time.perf_counter()
        self.overlay.open_history()
        elapsed = time.perf_counter() - started
        destination = self.overlay.utility_windows["history"]

        self.assertIsNot(destination, old)
        self.assertLess(elapsed, 0.25, "navigation synchronously destroyed the Settings tree")
        self.assertGreater(float(old.attributes("-alpha")), 0.9)
        self.assertEqual(float(destination.attributes("-alpha")), 0.0)

        pump(self.overlay.root, 1.0)
        self.assertGreater(float(destination.attributes("-alpha")), 0.9)
        old_visible = bool(old.winfo_viewable()) and float(old.attributes("-alpha")) > 0.01
        self.assertFalse(old_visible, "the outgoing page stayed visibly stacked after crossfade")

    def test_failed_destination_build_keeps_the_complete_source_page(self) -> None:
        self.overlay.open_stats()
        pump(self.overlay.root, 0.8)
        old = self.overlay.utility_windows["stats"]
        old.update_idletasks()

        with mock.patch.object(
            self.overlay,
            "_make_glass_titlebar",
            side_effect=RuntimeError("simulated builder failure"),
        ):
            with self.assertRaisesRegex(RuntimeError, "simulated builder failure"):
                self.overlay.open_history()

        pump(self.overlay.root, 0.2)
        self.assertIs(self.overlay.utility_windows.get("stats"), old)
        self.assertNotIn("history", self.overlay.utility_windows)
        self.assertIs(getattr(self.overlay, "_shell_window", None), old)
        self.assertTrue(old.winfo_exists())
        self.assertTrue(old.winfo_viewable())
        self.assertGreater(float(old.attributes("-alpha")), 0.9)

    def test_fresh_settings_has_a_complete_first_paint_until_controls_settle(self) -> None:
        self.overlay.open_settings()
        settings = self.overlay.utility_windows["settings"]
        covers = [
            child
            for child in self.overlay.root.winfo_children()
            if isinstance(child, tk.Toplevel)
            and bool(getattr(child, "_talkdat_settings_loading_cover", False))
        ]
        self.assertEqual(len(covers), 1)
        cover = covers[0]
        self.assertTrue(cover.winfo_viewable())
        self.assertGreater(float(cover.attributes("-alpha")), 0.9)
        self.assertEqual(float(settings.attributes("-alpha")), 0.0)

        pump(self.overlay.root, 0.8)
        self.assertGreater(float(settings.attributes("-alpha")), 0.9)
        self.assertFalse(cover.winfo_exists())

    def test_heavy_settings_collections_build_only_when_their_page_opens(self) -> None:
        self.overlay.open_settings()
        settings = self.overlay.utility_windows["settings"]
        lazy = getattr(settings, "_settings_lazy_collections")

        # History: the button gallery staged its reveal ("ready" grew true
        # over pumped frames). X-337's one-canvas material gallery draws all
        # fifty themes in a single pass, so opening Colors builds it
        # immediately -- staging was only ever a workaround for widget count.
        self.assertFalse(lazy["colors"]["built"])
        self.assertFalse(lazy["local_models"]["ready"])
        self.assertIsNone(lazy["local_models"]["after"])

        selector = getattr(settings, "_select_settings_page")
        selector("Colors", None, "Theme")
        pump(self.overlay.root, 0.4)
        self.assertTrue(lazy["colors"]["built"])

        selector("Speech", None, "Local models")
        self.assertFalse(lazy["local_models"]["ready"])
        self.assertIsNotNone(lazy["local_models"]["after"])
        pump(self.overlay.root, 1.4)
        self.assertTrue(lazy["local_models"]["ready"])
        self.assertIsNone(lazy["local_models"]["after"])

        stack = [settings]
        model_trees = []
        while stack:
            widget = stack.pop()
            stack.extend(widget.winfo_children())
            if isinstance(widget, ttk.Treeview):
                model_trees.append(widget)
        self.assertEqual(len(model_trees), 1)
        self.assertGreaterEqual(len(model_trees[0].get_children("")), 10)
        self.assertTrue(model_trees[0].selection())

        # The previous gallery/catalog created about 334 nested native
        # controls. Keep every option and action, but do not regress to a tree
        # large enough to freeze resize reconciliation again.
        self.assertLess(
            len(self.overlay._toplevel_widget_tree(settings)),
            700,
            "Settings rebuilt the heavyweight theme/model control forest",
        )

        search_labels = {
            str(entry.label)
            for entry in getattr(settings, "_settings_search_entries", ())
        }
        self.assertIn(self.overlay._settings_theme_options()[0], search_labels)

    def test_closing_settings_cover_cancels_the_hidden_destination(self) -> None:
        self.overlay.open_settings()
        settings = self.overlay.utility_windows["settings"]
        covers = [
            child
            for child in self.overlay.root.winfo_children()
            if isinstance(child, tk.Toplevel)
            and bool(getattr(child, "_talkdat_settings_loading_cover", False))
        ]
        self.assertEqual(len(covers), 1)
        cover = covers[0]

        # This is the exact handoff gap a queued X/Escape can hit: the complete
        # cover is visible, while the independently built destination is alpha 0.
        self.assertIs(getattr(settings, "_talkdat_transition_outgoing", None), cover)
        self.overlay._request_utility_close(cover)
        pump(self.overlay.root, 1.0)

        self.assertTrue(getattr(settings, "_talkdat_close_requested", False))
        destination_visible = bool(settings.winfo_viewable()) and float(
            settings.attributes("-alpha")
        ) > 0.01
        self.assertFalse(
            destination_visible,
            "the Settings destination appeared after its visible cover was closed",
        )
        self.assertFalse(cover.winfo_exists())
        self.assertIsNone(getattr(self.overlay, "_shell_window", None))

    def test_settings_cover_build_failure_leaves_no_orphan_surface(self) -> None:
        with mock.patch.object(
            self.overlay,
            "_close_control",
            side_effect=RuntimeError("simulated cover decoration failure"),
        ):
            with self.assertRaisesRegex(RuntimeError, "cover decoration failure"):
                self.overlay.open_settings()

        pump(self.overlay.root, 0.2)
        covers = [
            child
            for child in self.overlay.root.winfo_children()
            if isinstance(child, tk.Toplevel)
            and bool(getattr(child, "_talkdat_settings_loading_cover", False))
        ]
        self.assertEqual(covers, [])
        self.assertIsNone(getattr(self.overlay, "_shell_window", None))
        self.assertNotIn("settings", self.overlay.utility_windows)

    def test_settings_destination_failure_keeps_the_complete_cover(self) -> None:
        with mock.patch.object(
            self.overlay,
            "_style_settings_widgets",
            side_effect=RuntimeError("simulated Settings destination failure"),
        ):
            with self.assertRaisesRegex(RuntimeError, "destination failure"):
                self.overlay.open_settings()

        pump(self.overlay.root, 0.2)
        covers = [
            child
            for child in self.overlay.root.winfo_children()
            if isinstance(child, tk.Toplevel)
            and bool(getattr(child, "_talkdat_settings_loading_cover", False))
            and child.winfo_exists()
        ]
        self.assertEqual(len(covers), 1)
        cover = covers[0]
        self.assertIs(getattr(self.overlay, "_shell_window", None), cover)
        self.assertTrue(cover.winfo_viewable())
        self.assertGreater(float(cover.attributes("-alpha")), 0.9)
        self.assertNotIn("settings", self.overlay.utility_windows)
        status = getattr(cover, "_talkdat_settings_loading_status", None)
        self.assertIsNotNone(status)
        self.assertIn("could not open", str(status.get()).lower())

    def test_settings_rapid_close_reopen_always_has_a_complete_cover(self) -> None:
        prior_reduce_motion = bool(
            self.overlay.config.setdefault("ui", {}).get("reduce_motion", False)
        )
        self.overlay.config["ui"]["reduce_motion"] = True
        try:
            self.overlay.open_settings()
            pump(self.overlay.root, 0.8)
            old = self.overlay.utility_windows["settings"]
            self.overlay._request_utility_close(old)
            self.assertTrue(getattr(old, "_talkdat_close_requested", False))

            # Sliced destruction keeps the retiring route object alive briefly.
            # It must not suppress the first-paint cover for the replacement.
            self.overlay.open_settings()
            reopened = self.overlay.utility_windows["settings"]
            covers = [
                child
                for child in self.overlay.root.winfo_children()
                if isinstance(child, tk.Toplevel)
                and bool(getattr(child, "_talkdat_settings_loading_cover", False))
                and child.winfo_exists()
                and not bool(getattr(child, "_talkdat_close_requested", False))
            ]
            self.assertIsNot(reopened, old)
            self.assertEqual(len(covers), 1)
            self.assertIs(getattr(reopened, "_talkdat_transition_outgoing", None), covers[0])
            self.assertGreater(float(covers[0].attributes("-alpha")), 0.9)
        finally:
            self.overlay.config["ui"]["reduce_motion"] = prior_reduce_motion

    def test_failed_rapid_second_navigation_restores_original_functional_page(self) -> None:
        self.overlay.open_stats()
        pump(self.overlay.root, 0.8)
        original = self.overlay.utility_windows["stats"]
        disposed: list[str] = []
        self.overlay.add_window_disposer("stats", lambda: disposed.append("stats"))

        # Commit an alpha-zero intermediate but supersede it before Tk can run
        # its presentation timer. The original complete Stats page remains the
        # visual and functional rollback surface.
        self.overlay.open_history()
        intermediate = self.overlay.utility_windows["history"]
        self.assertIs(getattr(intermediate, "_talkdat_transition_outgoing", None), original)
        self.assertEqual(disposed, [])

        with mock.patch.object(
            self.overlay,
            "_make_glass_titlebar",
            side_effect=RuntimeError("simulated chained builder failure"),
        ):
            with self.assertRaisesRegex(RuntimeError, "simulated chained builder failure"):
                self.overlay.open_translation()

        pump(self.overlay.root, 0.2)
        self.assertIs(self.overlay.utility_windows.get("stats"), original)
        self.assertIs(getattr(self.overlay, "_shell_window", None), original)
        self.assertEqual(disposed, [], "rollback restored pixels after disposing their behavior")
        self.assertTrue(original.winfo_viewable())
        self.assertGreater(float(original.attributes("-alpha")), 0.9)

    def test_rapid_reopen_same_route_retires_only_the_old_instance(self) -> None:
        self.overlay.open_stats()
        pump(self.overlay.root, 0.8)
        original = self.overlay.utility_windows["stats"]
        disposed: list[str] = []
        self.overlay.add_window_disposer("stats", lambda: disposed.append("old-stats"))

        self.overlay.open_history()
        intermediate = self.overlay.utility_windows["history"]
        self.assertIs(getattr(intermediate, "_talkdat_transition_outgoing", None), original)

        # Reclaim the same public route before the intermediate can present.
        # The disposer must follow the old Toplevel identity, not the reused
        # string "stats", or presenting this destination disables itself.
        self.overlay.open_stats()
        reopened = self.overlay.utility_windows["stats"]
        self.assertIsNot(reopened, original)
        self.overlay.add_window_disposer("stats", lambda: disposed.append("new-stats"))

        pump(self.overlay.root, 0.8)
        self.assertEqual(disposed, ["old-stats"])
        self.assertIs(self.overlay.utility_windows.get("stats"), reopened)
        self.assertTrue(reopened.winfo_viewable())
        self.assertGreater(float(reopened.attributes("-alpha")), 0.9)

    def test_settings_cancel_keeps_unsaved_page_instead_of_navigating(self) -> None:
        self.overlay.open_settings()
        pump(self.overlay.root, 1.2)
        settings = self.overlay.utility_windows["settings"]
        tracked = tuple(getattr(settings, "_settings_tracked_vars", ()))
        self.assertTrue(tracked, "Settings exposes no tracked variables")
        dirty = getattr(settings, "_settings_dirty")
        dirty["armed"] = True
        tracked[0].set(str(tracked[0].get()) + " ")
        self.assertTrue(dirty["value"])

        with mock.patch(
            "knight_flow.overlay.messagebox.askyesnocancel",
            return_value=None,
        ) as ask:
            self.overlay.open_history()

        self.assertEqual(ask.call_count, 1)
        self.assertIs(self.overlay.utility_windows.get("settings"), settings)
        self.assertNotIn("history", self.overlay.utility_windows)
        self.assertIs(getattr(self.overlay, "_shell_window", None), settings)
        dirty["value"] = False

    def test_non_shell_rail_navigation_retires_its_source(self) -> None:
        self.overlay.open_status()
        pump(self.overlay.root, 0.8)
        status = self.overlay.utility_windows["status"]
        rail = getattr(status, "_menu_rail", None)
        self.assertIsNotNone(rail)

        def descendants(widget):
            for child in widget.winfo_children():
                yield child
                yield from descendants(child)

        history_button = next(
            child
            for child in descendants(rail)
            if isinstance(child, (tk.Button, FlatButton)) and str(child.cget("text")) == "History"
        )
        history_button.invoke()
        pump(self.overlay.root, 1.0)

        history = self.overlay.utility_windows.get("history")
        self.assertIsNotNone(history)
        self.assertTrue(history.winfo_viewable())
        status_visible = bool(status.winfo_exists()) and bool(status.winfo_viewable())
        if status_visible:
            status_visible = float(status.attributes("-alpha")) > 0.01
        self.assertFalse(status_visible, "non-shell source stayed stacked behind History")


if __name__ == "__main__":
    unittest.main()
