"""Real-Tk regression coverage for persistent utility-window minimization.

These checks deliberately exercise the shared borderless utility chrome and
the ordinary ``_utility_window`` reentry path.  A mock-only window can prove a
method call but cannot prove that withdrawing/deiconifying an override-redirect
Toplevel preserves its Tcl identity, children, bindings, and route ownership.

The module is launched in a clean interpreter by ``test_gui_regressions``.
"""

from __future__ import annotations

from knight_flow.flat_button import FlatButton  # tk.Button off macOS; a styled Label on Aqua

import contextlib
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

if sys.platform == "win32":
    from tests import gui_offscreen  # noqa: F401  (never show real windows)

try:
    import tkinter as tk
    from tkinter import ttk
except Exception:  # pragma: no cover - tkinter missing entirely
    tk = None  # type: ignore[assignment]
    ttk = None  # type: ignore[assignment]

from knight_flow.config import load_config
from knight_flow.overlay import Overlay


def pump(root: tk.Misc, seconds: float = 0.25) -> None:
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        root.update()
        time.sleep(0.01)


def descendants(widget: tk.Misc) -> list[tk.Misc]:
    found: list[tk.Misc] = []
    for child in widget.winfo_children():
        found.append(child)
        found.extend(descendants(child))
    return found


def widget_text(widget: tk.Misc) -> str:
    try:
        return str(widget.cget("text"))
    except (AttributeError, tk.TclError):
        return ""


@unittest.skipIf(tk is None, "tkinter unavailable")
class PersistentUtilityMinimizeTests(unittest.TestCase):
    ROUTE = "minimize_probe"
    TITLE = "Talk DAT! Minimize Probe"
    GEOMETRY = "520x340"

    @classmethod
    def setUpClass(cls) -> None:
        cls._previous_home = os.environ.get("TALK_DAT_HOME")
        cls._home = tempfile.mkdtemp(prefix="talkdat-utility-minimize-")
        os.environ["TALK_DAT_HOME"] = cls._home
        config = load_config()
        config.setdefault("ui", {})["reduce_motion"] = True
        cls.overlay = Overlay(
            config=config,
            callbacks={
                "license_status": lambda: {},
                "license_activation_status": lambda: {},
                "save_settings": lambda: None,
            },
        )
        pump(cls.overlay.root, 0.3)

    @classmethod
    def tearDownClass(cls) -> None:
        with contextlib.suppress(Exception):
            cls.overlay.root.destroy()
        with contextlib.suppress(Exception):
            tk._default_root = None  # type: ignore[attr-defined]
        if cls._previous_home is None:
            os.environ.pop("TALK_DAT_HOME", None)
        else:
            os.environ["TALK_DAT_HOME"] = cls._previous_home

    def _drop_utilities(self) -> None:
        for child in tuple(self.overlay.root.winfo_children()):
            if isinstance(child, tk.Toplevel):
                with contextlib.suppress(Exception):
                    child.destroy()
        self.overlay.utility_windows.clear()
        self.overlay._window_disposers.clear()
        self.overlay._shell_window = None
        self.overlay._last_minimized_utility = None
        self.overlay._minimized_utility_stack = []
        pump(self.overlay.root, 0.1)

    def tearDown(self) -> None:
        self._drop_utilities()

    def _open_probe(
        self,
        *,
        route: str | None = None,
        title: str | None = None,
    ) -> tuple[tk.Toplevel, ttk.Entry, dict[str, object], list[tuple[str, bool]]]:
        route = route or self.ROUTE
        title = title or self.TITLE
        palette = self.overlay._settings_palette(self.overlay._settings_theme_key())
        window = self.overlay._utility_window(
            route,
            title,
            self.GEOMETRY,
            bg=palette["bg"],
            resizable=True,
            minimum_size=(420, 260),
        )
        self.assertIsInstance(window, tk.Toplevel)

        body = tk.Frame(window, bg=palette["bg"])
        body.pack(fill="both", expand=True, padx=28, pady=24)
        draft = tk.StringVar(master=window, value="Production notes awaiting review")
        entry = ttk.Entry(body, textvariable=draft)
        entry.pack(fill="x")
        state: dict[str, object] = {
            "draft": draft,
            "mic_open": True,
            "mic_token": object(),
        }
        disposed: list[tuple[str, bool]] = []

        def dispose() -> None:
            disposed.append((draft.get(), bool(state["mic_open"])))
            state["mic_open"] = False

        self.overlay.add_window_disposer(route, dispose)
        pump(self.overlay.root, 0.5)
        self.assertTrue(window.winfo_exists())
        return window, entry, state, disposed

    @staticmethod
    def _minimize_buttons(window: tk.Toplevel) -> list[tk.Button]:
        return [
            widget
            for widget in descendants(window)
            if isinstance(widget, (tk.Button, FlatButton)) and widget_text(widget) == "Minimize"
        ]

    def _reenter_probe_route(self) -> None:
        palette = self.overlay._settings_palette(self.overlay._settings_theme_key())
        result = self.overlay._utility_window(
            self.ROUTE,
            self.TITLE,
            self.GEOMETRY,
            bg=palette["bg"],
            resizable=True,
            minimum_size=(420, 260),
        )
        self.assertIsNone(result, "route reentry constructed a duplicate utility")

    def _assert_one_visible_minimize(self, window: tk.Toplevel) -> tk.Button:
        buttons = self._minimize_buttons(window)
        self.assertEqual(len(buttons), 1, "window does not expose exactly one Minimize action")
        minimize = buttons[0]
        window.update_idletasks()
        self.assertTrue(minimize.winfo_ismapped(), "Minimize exists but is not visible")
        self.assertGreater(minimize.winfo_width(), 1)
        self.assertGreater(minimize.winfo_height(), 1)
        window_left = window.winfo_rootx()
        window_top = window.winfo_rooty()
        button_left = minimize.winfo_rootx()
        button_top = minimize.winfo_rooty()
        self.assertGreaterEqual(button_left, window_left)
        self.assertGreaterEqual(button_top, window_top)
        self.assertLessEqual(
            button_left + minimize.winfo_width(),
            window_left + window.winfo_width(),
        )
        self.assertLessEqual(
            button_top + minimize.winfo_height(),
            window_top + window.winfo_height(),
        )
        return minimize

    @staticmethod
    def _window_box(window: tk.Toplevel) -> tuple[int, int, int, int]:
        window.update_idletasks()
        return (
            int(window.winfo_width()),
            int(window.winfo_height()),
            int(window.winfo_rootx()),
            int(window.winfo_rooty()),
        )

    def _assert_visually_hidden(self, window: tk.Toplevel) -> None:
        """A composed DWM cloak stays Tk-mapped but paints and hit-tests nowhere."""

        mode = str(getattr(window, "_talkdat_minimize_mode", ""))
        self.assertTrue(bool(getattr(window, "_talkdat_minimized", False)))
        if mode == "cloaked":
            self.assertTrue(getattr(window, "_talkdat_cloaked_handles", ()))
            return
        self.assertFalse(window.winfo_viewable())

    def test_grid_authored_settings_account_and_current_onboarding_show_minimize(self) -> None:
        hosts = (
            ("settings", self.overlay.open_settings, 1.2),
            ("account", self.overlay.open_account, 0.6),
            ("onboarding", self.overlay.open_onboarding, 0.8),
        )
        for route, open_route, settle_seconds in hosts:
            with self.subTest(route=route):
                self._drop_utilities()
                open_route()
                pump(self.overlay.root, settle_seconds)
                window = self.overlay.utility_windows.get(route)
                self.assertIsInstance(window, tk.Toplevel)
                self.assertTrue(window.winfo_viewable())
                self.assertTrue(
                    any(child.winfo_manager() == "grid" for child in window.winfo_children()),
                    f"{route} did not exercise its grid-authored host",
                )
                self.assertIsNone(
                    getattr(window, "_glass_titlebar", None),
                    f"{route} unexpectedly used the packed shared titlebar",
                )
                self._assert_one_visible_minimize(window)

    def test_tray_show_restores_only_the_last_minimized_utility(self) -> None:
        first, _first_entry, _first_state, _first_disposed = self._open_probe(
            route="minimize_probe_first",
            title="Talk DAT! First Minimize Probe",
        )
        second, _second_entry, _second_state, _second_disposed = self._open_probe(
            route="minimize_probe_second",
            title="Talk DAT! Second Minimize Probe",
        )
        self.overlay._request_utility_minimize(first)
        self.overlay._request_utility_minimize(second)
        pump(self.overlay.root, 0.15)
        self._assert_visually_hidden(first)
        self._assert_visually_hidden(second)
        self.assertIs(getattr(self.overlay, "_last_minimized_utility", None), second)

        with mock.patch.object(
            self.overlay,
            "_focus_utility_window",
            wraps=self.overlay._focus_utility_window,
        ) as focus:
            self.overlay.show()
            pump(self.overlay.root, 0.2)
            focus.assert_called_once_with("minimize_probe_second")

        self._assert_visually_hidden(first)
        self.assertTrue(bool(getattr(first, "_talkdat_minimized", False)))
        self.assertTrue(second.winfo_viewable())
        self.assertFalse(bool(getattr(second, "_talkdat_minimized", False)))
        self.assertIs(self.overlay.utility_windows.get("minimize_probe_first"), first)
        self.assertIs(self.overlay.utility_windows.get("minimize_probe_second"), second)
        self.assertIs(
            getattr(self.overlay, "_last_minimized_utility", None),
            first,
            "the next-most-recent minimized utility was lost",
        )

        self.overlay.show()
        pump(self.overlay.root, 0.2)
        self.assertTrue(first.winfo_viewable())
        self.assertFalse(bool(getattr(first, "_talkdat_minimized", False)))
        self.assertIsNone(getattr(self.overlay, "_last_minimized_utility", None))

    def test_minimized_history_to_stats_preserves_exact_shell_geometry_without_duplicate(self) -> None:
        # Keep the real windows in a synthetic off-screen work area. This lets
        # the product's ordinary monitor clamp and transition code run while
        # making exact origin assertions safe on a developer's desktop.
        work_area = (-33000, -33000, -29000, -29000)
        with (
            mock.patch.object(self.overlay, "_pill_monitor_work_area", return_value=work_area),
            mock.patch.object(self.overlay, "_window_monitor_work_area", return_value=work_area),
        ):
            self.overlay.open_history()
            pump(self.overlay.root, 0.7)
            history = self.overlay.utility_windows["history"]
            history.geometry("900x640+-31920+-31840")
            pump(self.overlay.root, 0.25)
            before = self._window_box(history)

            self.overlay._request_utility_minimize(history)
            pump(self.overlay.root, 0.15)
            self._assert_visually_hidden(history)
            self.assertIs(self.overlay.utility_windows.get("history"), history)

            with mock.patch.object(
                self.overlay,
                "_restore_utility_window",
                wraps=self.overlay._restore_utility_window,
            ) as restore:
                self.overlay.open_stats()
                restore.assert_called_once_with(history)

            stats = self.overlay.utility_windows.get("stats")
            self.assertIsInstance(stats, tk.Toplevel)
            self.assertIsNot(stats, history)
            pump(self.overlay.root, 1.4)
            after = self._window_box(stats)

        # X-461: every window grows to fit content that does not fit, and
        # Stats' charts are named in that feature explicitly. Position and
        # width are still exact -- shell navigation must not move a restored
        # window sideways -- but height is grow-only, not equal, once a page
        # with more content than History replaces it.
        self.assertEqual(after[0], before[0], "shell navigation changed the window's width")
        self.assertGreaterEqual(
            after[1], before[1],
            "shell navigation shrank the window instead of only growing to fit content",
        )
        self.assertEqual(after[2], before[2], "shell navigation moved the window's x position")
        self.assertEqual(after[3], before[3], "shell navigation moved the window's y position")
        self.assertIs(getattr(self.overlay, "_shell_window", None), stats)
        self.assertNotIn("history", self.overlay.utility_windows)
        self.assertIs(self.overlay.utility_windows.get("stats"), stats)
        self.assertFalse(history.winfo_exists(), "retired History survived beside Stats")
        live_stats = [
            child
            for child in self.overlay.root.winfo_children()
            if isinstance(child, tk.Toplevel)
            and child.winfo_exists()
            and str(child.title()) == "Talk DAT! Stats"
        ]
        self.assertEqual(live_stats, [stats], "shell navigation constructed duplicate Stats windows")

    def test_minimize_preserves_exact_window_state_and_close_still_disposes(self) -> None:
        window, entry, state, disposed = self._open_probe()
        identity = str(window)
        original_token = state["mic_token"]
        self.assertTrue(bool(window.overrideredirect()), "probe is not the borderless production path")

        buttons = self._minimize_buttons(window)
        self.assertEqual(len(buttons), 1, "persistent chrome must expose one shared Minimize action")
        minimize = buttons[0]
        minimize.invoke()
        pump(self.overlay.root, 0.15)
        minimize_mode = str(getattr(window, "_talkdat_minimize_mode", ""))

        self.assertTrue(window.winfo_exists(), "minimize destroyed the live Toplevel")
        self.assertIs(self.overlay.utility_windows.get(self.ROUTE), window)
        self._assert_visually_hidden(window)
        self.assertEqual(disposed, [], "minimize ran the close-only disposer")
        self.assertEqual(entry.get(), "Production notes awaiting review")
        self.assertTrue(state["mic_open"], "minimize stopped the active microphone state")
        self.assertIs(state["mic_token"], original_token)

        # Repeating the public request is harmless even while already hidden.
        self.overlay._request_utility_minimize(window)
        self.overlay._request_utility_minimize(window)
        pump(self.overlay.root, 0.1)
        self.assertIs(self.overlay.utility_windows.get(self.ROUTE), window)
        self.assertEqual(disposed, [])

        with (
            mock.patch.object(window, "deiconify", wraps=window.deiconify) as deiconify,
            mock.patch.object(window, "lift", wraps=window.lift) as lift,
            mock.patch.object(window, "focus_force", wraps=window.focus_force) as focus,
        ):
            self._reenter_probe_route()
            pump(self.overlay.root, 0.15)
            if minimize_mode == "cloaked":
                deiconify.assert_not_called()
            else:
                deiconify.assert_called_once_with()
            lift.assert_called_once_with()
            focus.assert_called_once_with()

        self.assertTrue(window.winfo_viewable())
        self.assertEqual(str(window), identity)
        self.assertIs(self.overlay.utility_windows.get(self.ROUTE), window)
        self.assertEqual(entry.get(), "Production notes awaiting review")
        self.assertTrue(state["mic_open"])
        self.assertIs(state["mic_token"], original_token)
        self.assertEqual(disposed, [])

        # Repeating a complete minimize/route-restore cycle must remain a
        # single-instance operation rather than accumulating retired windows.
        self.overlay._request_utility_minimize(window)
        pump(self.overlay.root, 0.05)
        self._reenter_probe_route()
        self._reenter_probe_route()
        pump(self.overlay.root, 0.15)
        self.assertIs(self.overlay.utility_windows.get(self.ROUTE), window)
        self.assertEqual(str(window), identity)
        self.assertEqual(disposed, [])

        self.overlay._request_utility_close(window)
        pump(self.overlay.root, 0.7)
        self.assertEqual(disposed, [("Production notes awaiting review", True)])
        self.assertFalse(bool(state["mic_open"]))
        self.assertNotIn(self.ROUTE, self.overlay.utility_windows)
        self.assertFalse(window.winfo_exists())

    def test_shared_control_is_keyboard_accessible_and_captions_is_excluded(self) -> None:
        window, _entry, _state, _disposed = self._open_probe()
        buttons = self._minimize_buttons(window)
        self.assertEqual(len(buttons), 1)
        minimize = buttons[0]
        self.assertNotEqual(str(minimize.cget("takefocus")), "0")
        self.assertTrue(minimize.bind("<Return>"), "Minimize has no Enter activation")

        palette = self.overlay._settings_palette(self.overlay._settings_theme_key())
        captions = self.overlay._utility_window(
            "captions",
            "Talk DAT! Captions",
            "520x160",
            bg=palette["bg"],
            resizable=True,
            minimum_size=(420, 96),
        )
        self.assertIsInstance(captions, tk.Toplevel)
        tk.Frame(captions, bg=palette["bg"]).pack(fill="both", expand=True)
        pump(self.overlay.root, 0.3)

        self.assertIsNone(getattr(captions, "_glass_titlebar", None))
        self.assertEqual(self._minimize_buttons(captions), [])


if __name__ == "__main__":
    unittest.main()
