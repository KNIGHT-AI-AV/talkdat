"""Real-Tk contracts for DWM-cloaked utility minimization and chrome policy.

The Toplevels and their follower rail are real. Only the Windows protocol
boundary is replaced so cloak verification, focus handoff, native fallback,
and partial-failure cleanup are deterministic on every test host.
"""

from __future__ import annotations

from knight_flow.flat_button import FlatButton  # tk.Button off macOS; a styled Label on Aqua

import contextlib
import os
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest import mock

if sys.platform == "win32":
    from tests import gui_offscreen  # noqa: F401  (never show real windows)

try:
    import tkinter as tk
except Exception:  # pragma: no cover - tkinter missing entirely
    tk = None  # type: ignore[assignment]

import knight_flow.overlay as overlay_module
from knight_flow.config import load_config
from knight_flow.overlay import Overlay


HOST_HWND = 10101
RAIL_HWND = 20202
EXTERNAL_HWND = 30303


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


class FakeUser32:
    """The four Win32 calls reached after the higher-level gates are mocked."""

    def __init__(self, *, native_iconic: bool = False) -> None:
        self.enabled = {HOST_HWND: True, RAIL_HWND: True}
        self.IsWindowEnabled = mock.Mock(
            side_effect=lambda hwnd: bool(self.enabled.get(int(hwnd), True))
        )

        def enable(hwnd, enabled):
            self.enabled[int(hwnd)] = bool(enabled)
            return 1

        self.EnableWindow = mock.Mock(side_effect=enable)
        self.ShowWindow = mock.Mock(return_value=1)
        self.IsIconic = mock.Mock(return_value=bool(native_iconic))


@unittest.skipIf(tk is None, "tkinter unavailable")
class UtilityDwmCloakRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._previous_home = os.environ.get("TALK_DAT_HOME")
        os.environ["TALK_DAT_HOME"] = tempfile.mkdtemp(prefix="talkdat-dwm-cloak-")
        config = load_config()
        config.setdefault("ui", {})["reduce_motion"] = True
        config["ui"]["settings_theme"] = "Flow Dark"
        config["ui"]["theme"] = "dark"
        config["ui"]["scale"] = 1.0
        config["ui"]["menu_sidebar_open"] = True
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

    def setUp(self) -> None:
        self._drop_utilities()
        ui = self.overlay.config.setdefault("ui", {})
        ui["reduce_motion"] = True
        ui["settings_theme"] = "Flow Dark"
        ui["theme"] = "dark"
        ui["scale"] = 1.0
        ui["menu_sidebar_open"] = True

    def tearDown(self) -> None:
        self._drop_utilities()

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
        self.overlay._settings_initial_page = None
        with contextlib.suppress(Exception):
            pump(self.overlay.root, 0.08)

    def _open_persistent(self, route: str) -> tuple[tk.Toplevel, tk.Toplevel]:
        palette = self.overlay._settings_palette(self.overlay._settings_theme_key())
        window = self.overlay._utility_window(
            route,
            f"Talk DAT! {route}",
            "620x440",
            bg=palette["bg"],
            resizable=True,
            minimum_size=(520, 360),
        )
        self.assertIsInstance(window, tk.Toplevel)
        tk.Frame(window, bg=palette["bg"]).pack(fill="both", expand=True)
        pump(self.overlay.root, 0.9)
        rail = getattr(window, "_menu_rail", None)
        self.assertIsInstance(rail, tk.Toplevel)
        self.assertTrue(window.winfo_viewable())
        self.assertTrue(rail.winfo_viewable())
        return window, rail

    @staticmethod
    def _handle_for(window: tk.Toplevel, host: tk.Toplevel, rail: tk.Toplevel) -> int:
        if window is host:
            return HOST_HWND
        if window is rail:
            return RAIL_HWND
        return 0

    @staticmethod
    def _fake_windll(user32: FakeUser32):
        return SimpleNamespace(
            user32=user32,
            dwmapi=SimpleNamespace(DwmFlush=mock.Mock(return_value=0)),
        )

    def test_verified_cloak_keeps_mapped_hwnds_and_restores_without_remap(self) -> None:
        host, rail = self._open_persistent("dwm_cloak_success")
        host_tk_id = int(host.winfo_id())
        rail_tk_id = int(rail.winfo_id())
        user32 = FakeUser32()
        fake_windll = self._fake_windll(user32)
        cloak_state = {HOST_HWND: False, RAIL_HWND: False}

        def set_cloak(hwnd: int, cloaked: bool) -> bool:
            cloak_state[int(hwnd)] = bool(cloaked)
            return True

        with (
            mock.patch.object(overlay_module.sys, "platform", "win32"),
            mock.patch.object(overlay_module.ctypes, "windll", fake_windll, create=True),
            mock.patch.object(self.overlay, "_screen_reader_is_active", return_value=False),
            mock.patch.object(
                self.overlay,
                "_native_toplevel_handle",
                side_effect=lambda window: self._handle_for(window, host, rail),
            ),
            mock.patch.object(
                self.overlay,
                "_utility_focus_return_window",
                return_value=EXTERNAL_HWND,
            ),
            mock.patch.object(
                self.overlay,
                "_restore_foreground_window",
                return_value=True,
            ) as handoff,
            mock.patch.object(
                self.overlay,
                "_set_dwm_cloak",
                side_effect=set_cloak,
            ) as cloak,
            mock.patch.object(
                self.overlay,
                "_eligible_focus_return_window",
                return_value=0,
            ),
        ):
            self.overlay._request_utility_minimize(host)
            pump(self.overlay.root, 0.1)

            self.assertEqual(str(host._talkdat_minimize_mode), "cloaked")  # type: ignore[attr-defined]
            self.assertTrue(bool(host._talkdat_minimized))  # type: ignore[attr-defined]
            self.assertTrue(host.winfo_viewable())
            self.assertTrue(rail.winfo_viewable())
            self.assertEqual(int(host.winfo_id()), host_tk_id)
            self.assertEqual(int(rail.winfo_id()), rail_tk_id)
            self.assertFalse(user32.enabled[HOST_HWND])
            self.assertFalse(user32.enabled[RAIL_HWND])
            self.assertEqual(cloak_state, {HOST_HWND: True, RAIL_HWND: True})
            self.assertEqual(
                host._talkdat_cloaked_handles,  # type: ignore[attr-defined]
                [(RAIL_HWND, True), (HOST_HWND, True)],
            )
            self.assertTrue(rail._talkdat_rail_state["suspended"])  # type: ignore[attr-defined]
            handoff.assert_called_once_with(EXTERNAL_HWND)
            self.assertEqual(
                cloak.call_args_list,
                [mock.call(RAIL_HWND, True), mock.call(HOST_HWND, True)],
            )

            with (
                mock.patch.object(host, "deiconify", wraps=host.deiconify) as host_deiconify,
                mock.patch.object(host, "withdraw", wraps=host.withdraw) as host_withdraw,
                mock.patch.object(rail, "deiconify", wraps=rail.deiconify) as rail_deiconify,
                mock.patch.object(rail, "withdraw", wraps=rail.withdraw) as rail_withdraw,
            ):
                self.assertTrue(self.overlay._focus_utility_window("dwm_cloak_success"))
                pump(self.overlay.root, 0.15)
                host_deiconify.assert_not_called()
                host_withdraw.assert_not_called()
                rail_deiconify.assert_not_called()
                rail_withdraw.assert_not_called()

            self.assertFalse(bool(host._talkdat_minimized))  # type: ignore[attr-defined]
            self.assertEqual(str(host._talkdat_minimize_mode), "")  # type: ignore[attr-defined]
            self.assertEqual(host._talkdat_cloaked_handles, ())  # type: ignore[attr-defined]
            self.assertTrue(host.winfo_viewable())
            self.assertTrue(rail.winfo_viewable())
            self.assertEqual(int(host.winfo_id()), host_tk_id)
            self.assertEqual(int(rail.winfo_id()), rail_tk_id)
            self.assertTrue(user32.enabled[HOST_HWND])
            self.assertTrue(user32.enabled[RAIL_HWND])
            self.assertEqual(cloak_state, {HOST_HWND: False, RAIL_HWND: False})
            self.assertFalse(rail._talkdat_rail_state["suspended"])  # type: ignore[attr-defined]
            self.assertEqual(
                cloak.call_args_list,
                [
                    mock.call(RAIL_HWND, True),
                    mock.call(HOST_HWND, True),
                    mock.call(RAIL_HWND, False),
                    mock.call(HOST_HWND, False),
                ],
            )

    def test_screen_reader_session_uses_native_fallback_without_cloaking(self) -> None:
        host, rail = self._open_persistent("screen_reader_fallback")
        user32 = FakeUser32(native_iconic=True)
        fake_windll = self._fake_windll(user32)

        with (
            mock.patch.object(overlay_module.sys, "platform", "win32"),
            mock.patch.object(overlay_module.ctypes, "windll", fake_windll, create=True),
            mock.patch.object(self.overlay, "_screen_reader_is_active", return_value=True),
            mock.patch.object(
                self.overlay,
                "_native_toplevel_handle",
                side_effect=lambda window: self._handle_for(window, host, rail),
            ),
            mock.patch.object(self.overlay, "_set_dwm_cloak") as cloak,
            mock.patch.object(self.overlay, "_utility_focus_return_window") as focus_target,
            mock.patch.object(
                self.overlay,
                "_eligible_focus_return_window",
                return_value=0,
            ),
        ):
            self.overlay._request_utility_minimize(host)
            pump(self.overlay.root, 0.1)
            self.assertEqual(str(host._talkdat_minimize_mode), "native")  # type: ignore[attr-defined]
            self.assertTrue(bool(host._talkdat_minimized))  # type: ignore[attr-defined]
            self.assertEqual(host._talkdat_cloaked_handles, ())  # type: ignore[attr-defined]
            self.assertFalse(rail.winfo_viewable())
            cloak.assert_not_called()
            focus_target.assert_not_called()
            user32.ShowWindow.assert_called_once_with(HOST_HWND, 6)

            self.assertTrue(self.overlay._focus_utility_window("screen_reader_fallback"))
            pump(self.overlay.root, 0.12)
            self.assertTrue(host.winfo_viewable())
            self.assertTrue(rail.winfo_viewable())
            self.assertFalse(bool(host._talkdat_minimized))  # type: ignore[attr-defined]
            self.assertEqual(
                user32.ShowWindow.call_args_list,
                [mock.call(HOST_HWND, 6), mock.call(HOST_HWND, 9)],
            )

    def test_failed_focus_handoff_uncloaks_and_reenables_before_fallback(self) -> None:
        host, rail = self._open_persistent("failed_handoff_fallback")
        user32 = FakeUser32(native_iconic=False)
        fake_windll = self._fake_windll(user32)
        cloak_state = {HOST_HWND: False, RAIL_HWND: False}

        def set_cloak(hwnd: int, cloaked: bool) -> bool:
            cloak_state[int(hwnd)] = bool(cloaked)
            return True

        suspension = getattr(rail, "_talkdat_set_suspended")
        with (
            mock.patch.object(overlay_module.sys, "platform", "win32"),
            mock.patch.object(overlay_module.ctypes, "windll", fake_windll, create=True),
            mock.patch.object(self.overlay, "_screen_reader_is_active", return_value=False),
            mock.patch.object(
                self.overlay,
                "_native_toplevel_handle",
                side_effect=lambda window: self._handle_for(window, host, rail),
            ),
            mock.patch.object(
                self.overlay,
                "_utility_focus_return_window",
                return_value=EXTERNAL_HWND,
            ),
            mock.patch.object(
                self.overlay,
                "_restore_foreground_window",
                return_value=False,
            ) as handoff,
            mock.patch.object(
                self.overlay,
                "_set_dwm_cloak",
                side_effect=set_cloak,
            ) as cloak,
            mock.patch.object(
                rail,
                "_talkdat_set_suspended",
                wraps=suspension,
            ) as suspend,
            mock.patch.object(
                self.overlay,
                "_eligible_focus_return_window",
                return_value=0,
            ),
        ):
            self.overlay._request_utility_minimize(host)
            pump(self.overlay.root, 0.12)

            self.assertEqual(str(host._talkdat_minimize_mode), "withdrawn")  # type: ignore[attr-defined]
            self.assertTrue(bool(host._talkdat_minimized))  # type: ignore[attr-defined]
            self.assertEqual(host._talkdat_cloaked_handles, ())  # type: ignore[attr-defined]
            self.assertFalse(host.winfo_viewable())
            self.assertFalse(rail.winfo_viewable())
            self.assertEqual(cloak_state, {HOST_HWND: False, RAIL_HWND: False})
            self.assertTrue(user32.enabled[HOST_HWND])
            self.assertTrue(user32.enabled[RAIL_HWND])
            handoff.assert_called_once_with(EXTERNAL_HWND)
            self.assertEqual(
                cloak.call_args_list,
                [
                    mock.call(RAIL_HWND, True),
                    mock.call(HOST_HWND, True),
                    mock.call(HOST_HWND, False),
                    mock.call(RAIL_HWND, False),
                ],
            )
            self.assertEqual(
                suspend.call_args_list,
                [mock.call(True, True), mock.call(False, True), mock.call(True, False)],
            )
            user32.ShowWindow.assert_called_once_with(HOST_HWND, 6)

            self.assertTrue(self.overlay._focus_utility_window("failed_handoff_fallback"))
            pump(self.overlay.root, 0.15)
            self.assertTrue(host.winfo_viewable())
            self.assertTrue(rail.winfo_viewable())
            self.assertFalse(bool(host._talkdat_minimized))  # type: ignore[attr-defined]

    def test_failed_uncloak_retains_owned_receipts_until_clean_route_retry(self) -> None:
        route = "failed_uncloak_retry"
        host, rail = self._open_persistent(route)
        host_tk_id = int(host.winfo_id())
        rail_tk_id = int(rail.winfo_id())
        user32 = FakeUser32(native_iconic=False)
        fake_windll = self._fake_windll(user32)
        cloak_state = {HOST_HWND: False, RAIL_HWND: False}
        fail_uncloak = True

        def set_cloak(hwnd: int, cloaked: bool) -> bool:
            nonlocal fail_uncloak
            hwnd = int(hwnd)
            if not cloaked and fail_uncloak:
                return False
            cloak_state[hwnd] = bool(cloaked)
            return True

        with (
            mock.patch.object(overlay_module.sys, "platform", "win32"),
            mock.patch.object(overlay_module.ctypes, "windll", fake_windll, create=True),
            mock.patch.object(self.overlay, "_screen_reader_is_active", return_value=False),
            mock.patch.object(
                self.overlay,
                "_native_toplevel_handle",
                side_effect=lambda window: self._handle_for(window, host, rail),
            ),
            mock.patch.object(
                self.overlay,
                "_utility_focus_return_window",
                return_value=EXTERNAL_HWND,
            ),
            mock.patch.object(
                self.overlay,
                "_restore_foreground_window",
                return_value=True,
            ),
            mock.patch.object(
                self.overlay,
                "_set_dwm_cloak",
                side_effect=set_cloak,
            ) as cloak,
            mock.patch.object(
                self.overlay,
                "_eligible_focus_return_window",
                return_value=0,
            ),
        ):
            self.overlay._request_utility_minimize(host)
            pump(self.overlay.root, 0.1)
            receipts = [(RAIL_HWND, True), (HOST_HWND, True)]
            self.assertEqual(host._talkdat_cloaked_handles, receipts)  # type: ignore[attr-defined]
            self.assertEqual(cloak_state, {HOST_HWND: True, RAIL_HWND: True})

            self.assertFalse(self.overlay._restore_utility_window(host))
            pump(self.overlay.root, 0.12)

            self.assertTrue(bool(host._talkdat_minimized))  # type: ignore[attr-defined]
            self.assertEqual(str(host._talkdat_minimize_mode), "cloaked")  # type: ignore[attr-defined]
            self.assertEqual(host._talkdat_cloaked_handles, receipts)  # type: ignore[attr-defined]
            self.assertFalse(bool(host._talkdat_cloak_preserved_mapping))  # type: ignore[attr-defined]
            self.assertTrue(bool(host._talkdat_cloak_native_host))  # type: ignore[attr-defined]
            self.assertIs(self.overlay.utility_windows.get(route), host)
            self.assertIn(host, self.overlay._minimized_utility_stack)
            self.assertIs(self.overlay._last_minimized_utility, host)
            self.assertFalse(host.winfo_viewable())
            self.assertFalse(rail.winfo_viewable())
            self.assertTrue(rail._talkdat_rail_state["suspended"])  # type: ignore[attr-defined]
            self.assertFalse(user32.enabled[HOST_HWND])
            self.assertFalse(user32.enabled[RAIL_HWND])
            self.assertEqual(cloak_state, {HOST_HWND: True, RAIL_HWND: True})
            self.assertIn(mock.call(HOST_HWND, 6), user32.ShowWindow.call_args_list)

            original_toplevel_ids = {
                int(child.winfo_id())
                for child in self.overlay.root.winfo_children()
                if isinstance(child, tk.Toplevel)
            }
            with mock.patch.object(self.overlay, "set_state") as set_state:
                for _attempt in range(2):
                    self.assertIsNone(
                        self.overlay._utility_window(
                            route,
                            "Talk DAT! retry owner",
                            "620x440",
                            bg="#111111",
                        )
                    )
                    self.assertIs(self.overlay.utility_windows.get(route), host)
                    self.assertEqual(
                        {
                            int(child.winfo_id())
                            for child in self.overlay.root.winfo_children()
                            if isinstance(child, tk.Toplevel)
                        },
                        original_toplevel_ids,
                    )
                self.assertEqual(set_state.call_count, 2)
            self.assertTrue(bool(host._talkdat_minimized))  # type: ignore[attr-defined]
            self.assertEqual(host._talkdat_cloaked_handles, receipts)  # type: ignore[attr-defined]

            fail_uncloak = False
            self.assertTrue(self.overlay._focus_utility_window(route))
            pump(self.overlay.root, 0.15)

            self.assertIs(self.overlay.utility_windows.get(route), host)
            self.assertFalse(bool(host._talkdat_minimized))  # type: ignore[attr-defined]
            self.assertEqual(str(host._talkdat_minimize_mode), "")  # type: ignore[attr-defined]
            self.assertEqual(host._talkdat_cloaked_handles, ())  # type: ignore[attr-defined]
            self.assertTrue(bool(host._talkdat_cloak_preserved_mapping))  # type: ignore[attr-defined]
            self.assertFalse(bool(host._talkdat_cloak_native_host))  # type: ignore[attr-defined]
            self.assertNotIn(host, self.overlay._minimized_utility_stack)
            self.assertIsNone(self.overlay._last_minimized_utility)
            self.assertTrue(host.winfo_viewable())
            self.assertTrue(rail.winfo_viewable())
            self.assertEqual(int(host.winfo_id()), host_tk_id)
            self.assertEqual(int(rail.winfo_id()), rail_tk_id)
            self.assertTrue(user32.enabled[HOST_HWND])
            self.assertTrue(user32.enabled[RAIL_HWND])
            self.assertEqual(cloak_state, {HOST_HWND: False, RAIL_HWND: False})
            self.assertEqual(
                cloak.call_args_list[-2:],
                [mock.call(RAIL_HWND, False), mock.call(HOST_HWND, False)],
            )

    def test_partial_cloak_rollback_failure_hides_pair_until_exact_owner_recovers(self) -> None:
        route = "partial_cloak_rollback_retry"
        host, rail = self._open_persistent(route)
        host_tk_id = int(host.winfo_id())
        rail_tk_id = int(rail.winfo_id())
        user32 = FakeUser32(native_iconic=False)
        fake_windll = self._fake_windll(user32)
        cloak_state = {HOST_HWND: False, RAIL_HWND: False}
        allow_uncloak = False

        def set_cloak(hwnd: int, cloaked: bool) -> bool:
            nonlocal allow_uncloak
            hwnd = int(hwnd)
            if cloaked and hwnd == HOST_HWND:
                return False
            if not cloaked and not allow_uncloak:
                return False
            cloak_state[hwnd] = bool(cloaked)
            return True

        with (
            mock.patch.object(overlay_module.sys, "platform", "win32"),
            mock.patch.object(overlay_module.ctypes, "windll", fake_windll, create=True),
            mock.patch.object(self.overlay, "_screen_reader_is_active", return_value=False),
            mock.patch.object(
                self.overlay,
                "_native_toplevel_handle",
                side_effect=lambda window: self._handle_for(window, host, rail),
            ),
            mock.patch.object(
                self.overlay,
                "_utility_focus_return_window",
                return_value=EXTERNAL_HWND,
            ),
            mock.patch.object(
                self.overlay,
                "_restore_foreground_window",
                return_value=True,
            ),
            mock.patch.object(
                self.overlay,
                "_set_dwm_cloak",
                side_effect=set_cloak,
            ) as cloak,
            mock.patch.object(
                self.overlay,
                "_eligible_focus_return_window",
                return_value=0,
            ),
        ):
            self.overlay._request_utility_minimize(host)
            pump(self.overlay.root, 0.12)

            receipts = [(RAIL_HWND, True), (HOST_HWND, True)]
            self.assertTrue(bool(host._talkdat_minimized))  # type: ignore[attr-defined]
            self.assertEqual(str(host._talkdat_minimize_mode), "cloaked")  # type: ignore[attr-defined]
            self.assertEqual(host._talkdat_cloaked_handles, receipts)  # type: ignore[attr-defined]
            self.assertFalse(bool(host._talkdat_cloak_preserved_mapping))  # type: ignore[attr-defined]
            self.assertTrue(bool(host._talkdat_cloak_native_host))  # type: ignore[attr-defined]
            self.assertEqual(cloak_state, {HOST_HWND: False, RAIL_HWND: True})
            self.assertFalse(user32.enabled[HOST_HWND])
            self.assertFalse(user32.enabled[RAIL_HWND])
            self.assertFalse(host.winfo_viewable())
            self.assertFalse(rail.winfo_viewable())
            self.assertEqual(
                cloak.call_args_list[:3],
                [
                    mock.call(RAIL_HWND, True),
                    mock.call(HOST_HWND, True),
                    mock.call(RAIL_HWND, False),
                ],
            )

            original_toplevel_ids = {
                int(child.winfo_id())
                for child in self.overlay.root.winfo_children()
                if isinstance(child, tk.Toplevel)
            }
            with mock.patch.object(self.overlay, "set_state") as set_state:
                self.assertIsNone(
                    self.overlay._utility_window(
                        route,
                        "Talk DAT! partial retry owner",
                        "620x440",
                        bg="#111111",
                    )
                )
                set_state.assert_called_once()
            self.assertIs(self.overlay.utility_windows.get(route), host)
            self.assertEqual(
                {
                    int(child.winfo_id())
                    for child in self.overlay.root.winfo_children()
                    if isinstance(child, tk.Toplevel)
                },
                original_toplevel_ids,
            )
            self.assertTrue(bool(host._talkdat_minimized))  # type: ignore[attr-defined]
            self.assertEqual(host._talkdat_cloaked_handles, receipts)  # type: ignore[attr-defined]
            self.assertEqual(cloak_state, {HOST_HWND: False, RAIL_HWND: True})

            allow_uncloak = True
            self.assertTrue(self.overlay._focus_utility_window(route))
            pump(self.overlay.root, 0.15)

            self.assertIs(self.overlay.utility_windows.get(route), host)
            self.assertFalse(bool(host._talkdat_minimized))  # type: ignore[attr-defined]
            self.assertEqual(str(host._talkdat_minimize_mode), "")  # type: ignore[attr-defined]
            self.assertEqual(host._talkdat_cloaked_handles, ())  # type: ignore[attr-defined]
            self.assertTrue(host.winfo_viewable())
            self.assertTrue(rail.winfo_viewable())
            self.assertEqual(int(host.winfo_id()), host_tk_id)
            self.assertEqual(int(rail.winfo_id()), rail_tk_id)
            self.assertTrue(user32.enabled[HOST_HWND])
            self.assertTrue(user32.enabled[RAIL_HWND])
            self.assertEqual(cloak_state, {HOST_HWND: False, RAIL_HWND: False})
            self.assertEqual(
                cloak.call_args_list[-2:],
                [mock.call(RAIL_HWND, False), mock.call(HOST_HWND, False)],
            )

    def test_transient_routes_have_no_minimize_or_alt_m(self) -> None:
        routes = tuple(sorted(Overlay.NON_MINIMIZABLE_UTILITY_ROUTES))
        for route in routes:
            with self.subTest(route=route):
                self._drop_utilities()
                palette = self.overlay._settings_palette(self.overlay._settings_theme_key())
                window = self.overlay._utility_window(
                    route,
                    f"Talk DAT! {route}",
                    "480x300",
                    bg=palette["bg"],
                )
                self.assertIsInstance(window, tk.Toplevel)
                tk.Frame(window, bg=palette["bg"]).pack(fill="both", expand=True)
                pump(self.overlay.root, 0.45)

                self.assertFalse(bool(window._talkdat_minimizable))  # type: ignore[attr-defined]
                self.assertEqual(
                    [
                        widget
                        for widget in descendants(window)
                        if isinstance(widget, (tk.Button, FlatButton)) and widget_text(widget) == "Minimize"
                    ],
                    [],
                )
                self.assertFalse(window.bind("<Alt-m>"))
                with mock.patch.object(
                    self.overlay,
                    "_request_utility_minimize",
                    wraps=self.overlay._request_utility_minimize,
                ) as request:
                    window.event_generate("<Alt-m>")
                    pump(self.overlay.root, 0.04)
                    request.assert_not_called()

                self.overlay._request_utility_minimize(window)
                pump(self.overlay.root, 0.04)
                self.assertFalse(bool(window._talkdat_minimized))  # type: ignore[attr-defined]
                self.assertEqual(str(window._talkdat_minimize_mode), "")  # type: ignore[attr-defined]
                self.assertTrue(window.winfo_viewable())
                self.assertIs(self.overlay.utility_windows.get(route), window)

    def test_minimize_chrome_scales_to_200_percent_and_repaints_live_theme(self) -> None:
        self.overlay.config.setdefault("ui", {})["scale"] = 2.0
        scaled, _rail = self._open_persistent("scaled_chrome_probe")
        minimize = next(
            widget
            for widget in descendants(scaled)
            if isinstance(widget, (tk.Button, FlatButton)) and widget_text(widget) == "Minimize"
        )
        close = next(
            widget
            for widget in descendants(scaled)
            if isinstance(widget, (tk.Button, FlatButton)) and widget_text(widget) == "Close window"
        )
        self.assertEqual(int(minimize.master.cget("width")), 168)
        self.assertEqual(int(minimize.master.cget("height")), 64)
        self.assertEqual(int(close.master.cget("width")), 88)
        self.assertEqual(int(close.master.cget("height")), 64)
        self.assertGreaterEqual(minimize.winfo_width(), 168)
        self.assertGreaterEqual(minimize.winfo_height(), 64)
        self._drop_utilities()

        self.overlay.config["ui"]["scale"] = 1.0
        self.overlay.config["ui"]["settings_theme"] = "Flow Dark"
        self.overlay.config["ui"]["theme"] = "dark"
        self.overlay.open_settings()
        pump(self.overlay.root, 1.25)
        settings = self.overlay.utility_windows["settings"]
        minimize = next(
            widget
            for widget in descendants(settings)
            if isinstance(widget, (tk.Button, FlatButton)) and widget_text(widget) == "Minimize"
        )
        close = next(
            widget
            for widget in descendants(settings)
            if isinstance(widget, (tk.Button, FlatButton)) and widget_text(widget) == "Close window"
        )
        theme_options = set(self.overlay._settings_theme_options())
        theme_variable = ""
        for widget in descendants(settings):
            if not isinstance(widget, (tk.Button, FlatButton)):
                continue
            variable = str(widget.cget("textvariable"))
            if not variable:
                continue
            with contextlib.suppress(tk.TclError):
                if str(widget.getvar(variable)) in theme_options:
                    theme_variable = variable
                    break
        self.assertTrue(theme_variable, "Settings does not expose its live theme variable")
        target_theme = next(option for option in theme_options if option.endswith(" Light"))
        target_palette = self.overlay._settings_palette(target_theme)
        settings.setvar(theme_variable, target_theme)
        pump(self.overlay.root, 0.25)

        self.assertEqual(str(settings.cget("bg")), target_palette["bg"])
        self.assertEqual(str(minimize.master.cget("bg")), target_palette["bg"])
        self.assertEqual(str(minimize.cget("bg")), target_palette["bg"])
        self.assertEqual(str(minimize.cget("fg")), target_palette["muted"])
        self.assertEqual(
            str(minimize.cget("activebackground")),
            target_palette.get("select", target_palette.get("button", target_palette["bg"])),
        )
        self.assertEqual(str(minimize.cget("activeforeground")), target_palette["text"])
        self.assertEqual(str(minimize.cget("highlightbackground")), target_palette["bg"])
        self.assertEqual(str(minimize.cget("highlightcolor")), target_palette["warm"])
        self.assertEqual(str(close.master.cget("bg")), target_palette["bg"])
        self.assertEqual(str(close.cget("bg")), target_palette["bg"])
        self.assertEqual(str(close.cget("fg")), target_palette["muted"])
        self.assertEqual(str(close.cget("activebackground")), target_palette["danger"])
        self.assertEqual(
            str(close.cget("activeforeground")),
            target_palette.get("on_danger", target_palette["text"]),
        )
        self.assertTrue(minimize.winfo_ismapped())
        self.assertTrue(close.winfo_ismapped())


if __name__ == "__main__":
    unittest.main()
