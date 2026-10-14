"""Every request the web page makes reaches something that answers it (2026-10-09).

The Pill menu redesign added rpc("menu_fit"), so each view could get a window its own
height. The page tests drive shell.js in a stand-in DOM that answers every method, so
they passed. The real host forwards only an allowlist of methods to the app, checked
twice (the renderer's Api.request, and the app's listener, where an unknown method
raises "Invalid shell request"), and menu_fit was not on it: in the app the request
would have been refused and no view would ever have fitted its window.

This reads the methods the page really calls and checks that the host answers each one
itself or forwards it, that both checkpoints read one list, and that the backend answers
every method that list forwards.
"""
from __future__ import annotations

import copy
import multiprocessing
import re
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from knight_flow.config import DEFAULT_CONFIG
from knight_flow.overlay import Overlay
from knight_flow.web_shell import shell_host
from knight_flow.web_shell.menu_geometry import pill_menu_bounds
from knight_flow.web_shell.shell_app import AppShell

ASSETS = Path(__file__).resolve().parents[1] / "knight_flow" / "web_shell" / "shell_assets"
#: Answered by the host itself (shell_host Api.request), never forwarded.
HOST_ANSWERS = {"theme_asset", "cancel_close", "dismiss", "close"}


def page_methods() -> set[str]:
    found: set[str] = set()
    for script in ASSETS.glob("*.js"):
        found |= set(re.findall(r'rpc\("([a-z_]+)"', script.read_text(encoding="utf-8")))
    return found


def shell() -> AppShell:
    overlay = Mock()
    overlay._settings_palette = object.__new__(Overlay)._settings_palette
    rows = object.__new__(Overlay)._context_menu_default_rows()
    overlay._context_menu_rows.return_value = rows
    overlay._context_menu_default_rows.return_value = rows
    overlay._context_menu_access_rows.return_value = rows
    overlay._context_menu_feature_rows.return_value = []
    overlay.MENU_SAFETY_ZONE_ACTIONS = Overlay.MENU_SAFETY_ZONE_ACTIONS
    app = Mock()
    app.config = copy.deepcopy(DEFAULT_CONFIG)
    app.overlay = overlay
    app.pending_update = None
    return AppShell(app, assets=ASSETS, controller_factory=lambda *args, **kwargs: Mock())


class TheHostForwardsWhatThePageAsksTests(unittest.TestCase):
    def test_the_guard_sees_the_pages_real_calls(self) -> None:
        self.assertTrue({"state", "action", "menu_fit"} <= page_methods())

    def test_every_method_the_page_calls_is_answered_or_forwarded(self) -> None:
        missing = sorted(page_methods() - HOST_ANSWERS - set(shell_host.FORWARDED_METHODS))
        self.assertEqual(missing, [], "the host would refuse these requests from the page")

    def test_both_checkpoints_read_the_one_list(self) -> None:
        source = Path(shell_host.__file__).read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"method not in \{", source), "a checkpoint keeps its own copy of the list")
        self.assertEqual(source.count("method not in FORWARDED_METHODS"), 2)

    def test_the_backend_answers_every_forwarded_method(self) -> None:
        backend = shell().backend
        for method in sorted(shell_host.FORWARDED_METHODS):
            with self.subTest(method=method):
                try:
                    backend.handle(method, {})
                except ValueError as error:
                    self.assertNotEqual(str(error), "Unknown settings request.", f"{method} is forwarded to nobody")


class TheMenusRequestsCrossTheRealHostTests(unittest.TestCase):
    """Review T8 (2026-10-10): the menu's two new requests over the host's real path.

    The page's request enters the renderer's Api.request, crosses a real pipe to the
    app's ShellController._listen (the second checkpoint) and reaches the backend, and
    the answer (and, for a fit, the resize command) comes back the same way. Only the
    webview window and the renderer process are stood in for.
    """

    def connect(self, pending=None):
        app = shell().app
        app.pending_update = pending
        # The Tk thread's queue, run at once: the listener's dispatch.
        app._cross_thread_calls = SimpleNamespace(put=lambda work: work())
        app_shell = AppShell(app, assets=ASSETS, controller_factory=shell_host.ShellController)
        renderer_end, app_end = multiprocessing.Pipe(duplex=True)
        controller = app_shell.menu_controller
        self.assertIsInstance(controller, shell_host.ShellController)
        controller.connection, controller.process = app_end, SimpleNamespace(is_alive=lambda: True)
        api = shell_host._RendererApi(renderer_end, mode="menu")
        api._trusted = lambda: True
        api._window = Mock()
        api._place_menu = Mock()
        threads = [threading.Thread(target=controller._listen, args=(app_end,), daemon=True),
                   threading.Thread(target=api._read, daemon=True)]
        for thread in threads:
            thread.start()

        def hang_up():
            renderer_end.close()
            for thread in threads:
                thread.join(5)

        self.addCleanup(hang_up)
        return app, app_shell, api

    def test_a_views_fit_reaches_the_app_and_moves_the_window(self) -> None:
        _app, app_shell, api = self.connect()
        pill, area = (1300, 900, 200, 48), (0, 0, 1920, 1040)
        app_shell._menu_pill, app_shell._menu_work_area, app_shell._menu_scale = pill, area, 1.0
        app_shell._menu_side = "above"
        app_shell._menu_bounds = pill_menu_bounds(pill, area, 1.0, height=472, side="above")
        answer = api.request("menu_fit", {"height": 232})
        expected = pill_menu_bounds(pill, area, 1.0, height=232, side="above")
        self.assertEqual(answer, {"ok": True, "result": {"bounds": list(expected)}})
        api._place_menu.assert_called_once_with(list(expected))
        # The edge that faces the Pill stays put; the far edge moved.
        self.assertEqual(expected[1] + expected[3], app_shell._menu_bounds[1] + app_shell._menu_bounds[3])

    def test_a_fit_the_backend_refuses_comes_back_as_an_error(self) -> None:
        _app, _app_shell, api = self.connect()
        answer = api.request("menu_fit", {"height": 5})
        self.assertFalse(answer["ok"])
        api._place_menu.assert_not_called()

    def test_install_on_the_menu_reaches_the_app_and_nothing_else(self) -> None:
        app, _app_shell, api = self.connect(SimpleNamespace(latest_version="0.4.171-beta", forced=False))
        answer = api.request("action", {"name": "menu:install_update"})
        self.assertTrue(answer["ok"], answer)
        app.install_or_check_update.assert_called_once_with()
        app.check_updates.assert_not_called()


if __name__ == "__main__":
    unittest.main()
