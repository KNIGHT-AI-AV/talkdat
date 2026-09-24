"""Real-window regressions for the lazy Local Models Settings page.

These checks need a clean Tk interpreter.  They exercise the actual catalog,
buttons, background download handoff, and theme repaint rather than inspecting
implementation text.  ``tests.test_gui_regressions`` launches this module in a
dedicated process for that reason.
"""

from __future__ import annotations

from knight_flow import mac_support

import os
import sys
import tempfile
import threading
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


def pump(root, seconds: float = 0.2) -> None:
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        root.update()
        time.sleep(0.01)


def wait_until(root, predicate, *, timeout: float = 4.0, message: str) -> None:
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        root.update()
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError(message)


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


@unittest.skipIf(tk is None, "tkinter unavailable")
class LocalModelWindowLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._previous_home = os.environ.get("TALK_DAT_HOME")
        os.environ["TALK_DAT_HOME"] = tempfile.mkdtemp(prefix="talkdat-model-window-")

        from knight_flow.config import load_config
        from knight_flow.local_stt import LOCAL_MODELS
        from knight_flow.overlay import Overlay

        cls.model = LOCAL_MODELS[0]
        cls.downloaded = False
        config = load_config()
        config.setdefault("ui", {})["reduce_motion"] = True
        config["ui"]["settings_theme"] = "Flow Dark"
        config["ui"]["theme"] = "dark"
        cls.overlay = Overlay(config, callbacks={})
        cls.patchers = (
            mock.patch("knight_flow.overlay.available_local_models", return_value=(cls.model,)),
            mock.patch(
                "knight_flow.overlay.local_model_downloaded",
                side_effect=lambda _model: cls.downloaded,
            ),
            mock.patch(
                "knight_flow.overlay.local_downloaded_size_mb",
                side_effect=lambda _model: cls.model.size_mb if cls.downloaded else 0,
            ),
        )
        for patcher in cls.patchers:
            patcher.start()
        pump(cls.overlay.root, 0.2)

    @classmethod
    def tearDownClass(cls) -> None:
        for patcher in reversed(cls.patchers):
            patcher.stop()
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
        self._drop_settings()
        self.downloaded = False
        type(self).downloaded = False
        self.overlay._local_model_downloads = set()
        ui = self.overlay.config.setdefault("ui", {})
        ui["settings_theme"] = "Flow Dark"
        ui["theme"] = "dark"

    def tearDown(self) -> None:
        self._drop_settings()
        self.overlay._local_model_downloads.clear()

    def _drop_settings(self) -> None:
        shell = getattr(self.overlay, "_shell_window", None)
        if shell is not None:
            try:
                shell.destroy()
            except Exception:
                pass
        for child in tuple(self.overlay.root.winfo_children()):
            if isinstance(child, tk.Toplevel):
                try:
                    child.destroy()
                except Exception:
                    pass
        self.overlay._shell_window = None
        self.overlay.utility_windows.clear()
        pump(self.overlay.root, 0.1)

    def _open_local_models(self):
        self.overlay.open_settings()
        window = self.overlay.utility_windows["settings"]
        window._select_settings_page("Speech", None, "Local Models")  # type: ignore[attr-defined]
        lazy = window._settings_lazy_collections["local_models"]  # type: ignore[attr-defined]
        wait_until(
            self.overlay.root,
            lambda: bool(lazy["ready"]),
            message="the one-row Local Models catalog did not finish building",
        )
        trees = [child for child in descendants(window) if isinstance(child, ttk.Treeview)]
        self.assertEqual(len(trees), 1, "Settings did not expose one local-model catalog")
        return window, trees[0]

    @staticmethod
    def _current_tree(window):
        trees = [
            child
            for child in descendants(window)
            if isinstance(child, ttk.Treeview) and bool(child.winfo_ismapped())
        ]
        if not trees:
            raise AssertionError("the visible local-model catalog is missing")
        return trees[-1]

    @staticmethod
    def _button(window, text: str):
        return next(
            child
            for child in descendants(window)
            if isinstance(child, ttk.Button) and str(child.cget("text")) == text
        )

    @staticmethod
    def _row_status(tree) -> str:
        rows = tree.get_children("")
        if not rows:
            return ""
        values = tree.item(rows[0], "values")
        return str(values[2]) if len(values) >= 3 else ""

    @staticmethod
    def _local_intro(window):
        for candidate in descendants(window):
            if not isinstance(candidate, tk.Label):
                continue
            if str(candidate.cget("text")) == "Local / on-device speech":
                return candidate.master
        raise AssertionError("the Local Models introduction is missing")

    def test_download_completion_refreshes_the_reopened_settings_window(self) -> None:
        worker_started = threading.Event()
        permit_finish = threading.Event()
        worker_returned = threading.Event()

        def download(_model, _status) -> None:
            worker_started.set()
            # Two complete Settings trees are intentionally opened around this
            # worker. Slow Windows CI or a concurrent real-Tk suite can spend
            # several seconds in native layout without indicating a product
            # failure, so keep the worker alive well beyond that cold path.
            if not permit_finish.wait(12.0):
                raise TimeoutError("test did not release the model download")
            type(self).downloaded = True
            worker_returned.set()

        with mock.patch("knight_flow.overlay.download_local_model", side_effect=download):
            first, _tree = self._open_local_models()
            self._button(first, "Download selected").invoke()
            self.assertTrue(worker_started.wait(1.0), "the model worker never started")
            self.assertIn(self.model.id, self.overlay._local_model_downloads)

            self.overlay._request_utility_close(first)
            self.assertTrue(getattr(first, "_talkdat_close_requested", False))
            self.assertIsNone(getattr(self.overlay, "_shell_window", None))
            second, current_tree = self._open_local_models()
            self.assertIsNot(second, first)
            self.assertEqual(self._row_status(current_tree), "Downloading")

            permit_finish.set()
            wait_until(
                self.overlay.root,
                worker_returned.is_set,
                message="the model worker did not return",
            )
            wait_until(
                self.overlay.root,
                lambda: self.model.id not in self.overlay._local_model_downloads,
                message="download completion did not clear the global in-progress state",
            )
            wait_until(
                self.overlay.root,
                lambda: self._row_status(self._current_tree(second)).startswith("Ready"),
                message=(
                    "the current Settings catalog was not refreshed after a download "
                    "owned by the retired window completed"
                ),
            )

        self.assertEqual(str(self._button(second, f"Delete from {mac_support.THIS_COMPUTER}").cget("state")), "normal")

    def test_lazy_local_catalog_repaints_from_dark_to_light(self) -> None:
        window, tree = self._open_local_models()
        intro = self._local_intro(window)
        dark = self.overlay._settings_palette("Flow Dark")
        light = self.overlay._settings_palette("Flow Light")
        style = ttk.Style(window)

        self.assertEqual(str(intro.cget("bg")), dark["panel"])
        self.assertEqual(style.lookup("Flow.Treeview", "fieldbackground"), dark["field"])

        theme_var = next(
            variable
            for variable in window._settings_tracked_vars  # type: ignore[attr-defined]
            if str(variable.get()) == "Flow Dark"
        )
        theme_var.set("Flow Light")
        pump(self.overlay.root, 0.2)

        self.assertEqual(str(intro.cget("bg")), light["panel"])
        self.assertEqual(style.lookup("Flow.Treeview", "background"), light["field"])
        self.assertEqual(style.lookup("Flow.Treeview", "fieldbackground"), light["field"])
        self.assertEqual(style.lookup("Flow.Treeview", "foreground"), light["text"])
        self.assertEqual(style.lookup("Flow.Treeview.Heading", "background"), light["button"])
        self.assertEqual(style.lookup("Flow.Treeview.Heading", "foreground"), light["text"])
        self.assertEqual(str(tree.tag_configure("active", "foreground")), light["accent"])

    def test_thread_start_failure_clears_downloading_and_leaves_retry_enabled(self) -> None:
        window, tree = self._open_local_models()
        button = self._button(window, "Download selected")
        raised = None

        with mock.patch(
            "knight_flow.overlay.threading.Thread.start",
            side_effect=RuntimeError("simulated thread-start refusal"),
        ):
            try:
                button.invoke()
            except Exception as error:  # The assertions below report all damage together.
                raised = error
        lazy = window._settings_lazy_collections["local_models"]  # type: ignore[attr-defined]
        wait_until(
            self.overlay.root,
            lambda: bool(lazy["ready"]),
            message="the local model catalog did not settle after thread-start failure",
        )
        tree = self._current_tree(window)

        retry_buttons = [
            child
            for child in descendants(window)
            if isinstance(child, ttk.Button)
            and str(child.cget("text")) == "Download selected"
        ]
        problems = []
        if raised is not None:
            problems.append(f"the button callback leaked {raised!r}")
        if self.model.id in self.overlay._local_model_downloads:
            problems.append("the global download set still marks the model in progress")
        if self._row_status(tree) == "Downloading":
            problems.append("the visible model row is still marked Downloading")
        if not retry_buttons:
            problems.append("the retry action was not restored")
        elif str(retry_buttons[0].cget("state")) != "normal":
            problems.append("the retry action is disabled")
        self.assertEqual(problems, [])


if __name__ == "__main__":
    unittest.main()
