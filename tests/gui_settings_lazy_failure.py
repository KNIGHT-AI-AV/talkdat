"""Real Settings rollback when a lazy destination cannot be prepared."""

from __future__ import annotations

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
except Exception:  # pragma: no cover
    tk = None  # type: ignore[assignment]

from knight_flow.overlay import FlowPageStack, Overlay
from knight_flow.ui.flow_console import FlowNavigationRail


def pump(root, seconds: float = 0.25) -> None:
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        root.update()
        time.sleep(0.01)


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


@unittest.skipIf(tk is None, "tkinter unavailable")
class SettingsLazyDestinationFailureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._previous_home = os.environ.get("TALK_DAT_HOME")
        os.environ["TALK_DAT_HOME"] = tempfile.mkdtemp(prefix="talkdat-lazy-failure-")

        from knight_flow.config import load_config

        config = load_config()
        config.setdefault("ui", {})["reduce_motion"] = True
        cls.overlay = Overlay(config, callbacks={})
        pump(cls.overlay.root, 0.3)

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

    def tearDown(self) -> None:
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

    @staticmethod
    def _lazy_loader_registry(rail: FlowNavigationRail) -> dict[str, object]:
        # The rail command delegates preparation to a sibling closure. Walk
        # callable closure cells as a tiny protocol graph rather than relying
        # on source locations or a private test-only product attribute.
        pending = [rail._command]
        visited: set[int] = set()
        while pending:
            callback = pending.pop()
            if id(callback) in visited:
                continue
            visited.add(id(callback))
            closure = getattr(callback, "__closure__", None) or ()
            for cell in closure:
                try:
                    candidate = cell.cell_contents
                except ValueError:
                    continue
                if (
                    isinstance(candidate, dict)
                    and callable(candidate.get("colors"))
                    and callable(candidate.get("dictation"))
                    and callable(candidate.get("formatting"))
                ):
                    return candidate
                if callable(candidate) and getattr(candidate, "__closure__", None):
                    pending.append(candidate)
        raise AssertionError("the Settings rail has no lazy page loader registry")

    @staticmethod
    def _page(stack: FlowPageStack, title: str):
        return next(
            stack.nametowidget(page_id)
            for page_id in stack.tabs()
            if str(stack.tab(page_id, "text")) == title
        )

    def _assert_general_survived(
        self,
        rail: FlowNavigationRail,
        stack: FlowPageStack,
        general,
        colors,
        events: list[str],
    ) -> None:
        self.assertEqual(rail.selected, "general")
        self.assertIs(stack._selected, general)
        self.assertIs(stack._visible, general)
        self.assertEqual(stack.select(), str(general))
        self.assertTrue(general.winfo_ismapped())
        self.assertFalse(colors.winfo_ismapped())
        self.assertEqual(events, [])

    def test_rail_and_deep_link_failures_keep_the_complete_general_page(self) -> None:
        self.overlay.open_settings()
        window = self.overlay.utility_windows["settings"]
        pump(self.overlay.root, 0.8)

        stack = getattr(window, "_settings_page_stack", None)
        self.assertIsInstance(stack, FlowPageStack)
        rail = next(
            child
            for child in descendants(window)
            if isinstance(child, FlowNavigationRail)
        )
        general = self._page(stack, "General")
        colors = self._page(stack, "Colors")
        self.assertEqual(rail.selected, "general")
        self.assertIs(stack._selected, general)
        self.assertIs(stack._visible, general)
        self.assertTrue(general.winfo_ismapped())

        loader_calls: list[str] = []

        def fail_colors() -> None:
            loader_calls.append("colors")
            raise RuntimeError("simulated Colors construction failure")

        loaders = self._lazy_loader_registry(rail)
        original_colors_loader = loaders["colors"]
        events: list[str] = []
        stack.bind(
            "<<NotebookTabChanged>>",
            lambda _event: events.append(str(stack.tab(stack.select(), "text"))),
            add="+",
        )
        callback_errors: list[BaseException] = []
        direct_errors: list[BaseException] = []
        original_callback_reporter = self.overlay.root.report_callback_exception

        def capture_callback_error(_kind, error, _traceback) -> None:
            callback_errors.append(error)

        self.overlay.root.report_callback_exception = capture_callback_error
        loaders["colors"] = fail_colors
        try:
            with (
                mock.patch.object(self.overlay, "set_state") as set_state,
                mock.patch("knight_flow.overlay.log.exception") as log_exception,
            ):
                try:
                    # Invoke the actual native rail button, including its
                    # optimistic selected-row state and callback dispatch.
                    rail._rows["colors"][2].invoke()
                except BaseException as error:
                    direct_errors.append(error)
                pump(self.overlay.root, 0.2)

                self.assertEqual(loader_calls, ["colors"])
                self.assertEqual(callback_errors, [])
                self.assertEqual(direct_errors, [])
                self._assert_general_survived(
                    rail, stack, general, colors, events
                )

                try:
                    window._select_settings_page("Colors", None, "Theme")  # type: ignore[attr-defined]
                except BaseException as error:
                    direct_errors.append(error)
                pump(self.overlay.root, 0.2)

                self.assertEqual(loader_calls, ["colors", "colors"])
                self.assertEqual(callback_errors, [])
                self.assertEqual(direct_errors, [])
                self._assert_general_survived(
                    rail, stack, general, colors, events
                )
                self.assertEqual(set_state.call_count, 2)
                self.assertEqual(log_exception.call_count, 2)
                for call in set_state.call_args_list:
                    self.assertEqual(call.args[0], "error")
                    self.assertIn("Could not open Colors settings", call.args[1])
        finally:
            loaders["colors"] = original_colors_loader
            self.overlay.root.report_callback_exception = original_callback_reporter


if __name__ == "__main__":
    unittest.main()
