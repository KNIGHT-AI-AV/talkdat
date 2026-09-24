"""Real-Tk proof that a short follower rail keeps every destination reachable."""

from __future__ import annotations

from knight_flow import mac_support

from knight_flow.flat_button import FlatButton  # tk.Button off macOS; a styled Label on Aqua

import contextlib
import os
import tempfile
import time
import unittest
from unittest import mock

from tests import gui_offscreen  # noqa: F401  (never map on a human display)

import tkinter as tk
from tkinter import ttk

from knight_flow.config import load_config
from knight_flow.overlay import Overlay


def pump(root: tk.Misc, seconds: float = 0.6) -> None:
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        root.update()
        time.sleep(0.01)


def descendants(widget: tk.Misc) -> list[tk.Misc]:
    result: list[tk.Misc] = []
    for child in widget.winfo_children():
        result.append(child)
        result.extend(descendants(child))
    return result


class SidebarOverflowRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.previous_home = os.environ.get("TALK_DAT_HOME")
        os.environ["TALK_DAT_HOME"] = tempfile.mkdtemp(prefix="talkdat-sidebar-")
        self.overlay = Overlay(load_config(), callbacks={})

    def tearDown(self) -> None:
        try:
            self.overlay.root.destroy()
        except Exception:
            pass
        tk._default_root = None  # type: ignore[attr-defined]
        if self.previous_home is None:
            os.environ.pop("TALK_DAT_HOME", None)
        else:
            os.environ["TALK_DAT_HOME"] = self.previous_home

    def test_last_destination_is_revealed_inside_a_320px_host(self) -> None:
        host = tk.Toplevel(self.overlay.root)
        host.geometry("560x320+500+200")
        host.configure(bg="#081014")
        pump(self.overlay.root, 0.2)
        self.overlay._attach_menu_rail(host, current="settings")
        pump(self.overlay.root, 0.8)

        side = host._menu_rail  # type: ignore[attr-defined]
        widgets = descendants(side)
        canvases = [
            widget for widget in widgets
            if isinstance(widget, tk.Canvas) and str(widget.cget("yscrollcommand"))
        ]
        scrollbars = [widget for widget in widgets if isinstance(widget, ttk.Scrollbar)]
        self.assertEqual(len(canvases), 1)
        self.assertEqual(len(scrollbars), 1)
        canvas = canvases[0]
        scrollbar = scrollbars[0]
        self.assertTrue(scrollbar.winfo_ismapped(), "short rail did not expose its scrollbar")
        self.assertLess(canvas.yview()[1], 1.0, "all rows unexpectedly fit; overflow path was not exercised")

        button = next(
            widget for widget in widgets
            if isinstance(widget, (tk.Button, FlatButton)) and str(widget.cget("text")) == "Mic Doctor"
        )
        self.assertIsInstance(button, (tk.Button, FlatButton))
        row = button.master
        button.event_generate("<FocusIn>")
        pump(self.overlay.root, 0.4)
        top = float(canvas.canvasy(0))
        bottom = top + canvas.winfo_height()
        self.assertGreater(canvas.yview()[0], 0.0)
        self.assertGreaterEqual(float(row.winfo_y()) + 1.0, top)
        self.assertLessEqual(
            float(row.winfo_y() + row.winfo_height()),
            bottom + 2.0,
            "keyboard focus did not reveal the last destination inside the viewport",
        )

    def test_destinations_are_native_buttons_with_complete_activation_contract(self) -> None:
        calls: list[str] = []
        rows = tuple(
            (action, title, lambda action=action: calls.append(action))
            for action, title, _callback_name in Overlay.SIDEBAR_DESTINATIONS
        )
        self.overlay._sidebar_destination_rows = lambda: rows  # type: ignore[method-assign]

        host = tk.Toplevel(self.overlay.root)
        host.geometry("560x460+500+200")
        host.configure(bg="#081014")
        pump(self.overlay.root, 0.2)
        self.overlay._attach_menu_rail(host, current="settings")
        pump(self.overlay.root, 0.8)

        side = host._menu_rail  # type: ignore[attr-defined]
        buttons = {
            str(widget.cget("text")): widget
            for widget in descendants(side)
            if isinstance(widget, (tk.Button, FlatButton))
            and str(widget.cget("text")) not in {"Collapse sidebar", "Expand sidebar"}
        }
        expected_titles = [title for _action, title, _callback in rows]
        self.assertEqual(list(buttons), expected_titles)
        self.assertTrue(all(isinstance(button, (tk.Button, FlatButton)) for button in buttons.values()))
        self.assertTrue(all(str(button.cget("takefocus")) == "1" for button in buttons.values()))

        current = buttons["Settings"]
        current.invoke()
        current.focus_set()
        pump(self.overlay.root, 0.05)
        current.event_generate("<Return>")
        current.event_generate("<space>")
        current.event_generate("<Enter>", x=8, y=8)
        current.event_generate("<ButtonPress-1>", x=8, y=8)
        current.event_generate("<ButtonRelease-1>", x=8, y=8)
        pump(self.overlay.root, 0.2)
        self.assertEqual(calls, [], "the active destination must remain inert")

        history = buttons["History"]
        history.focus_set()
        pump(self.overlay.root, 0.05)
        host._navigation_locked = True  # type: ignore[attr-defined]
        host._navigation_lock_message = "Finishing the secure update."  # type: ignore[attr-defined]
        history.event_generate("<Return>")
        pump(self.overlay.root, 0.1)
        self.assertEqual(calls, [], "navigation lock must also govern native buttons")
        host._navigation_locked = False  # type: ignore[attr-defined]
        history.event_generate("<Return>")
        pump(self.overlay.root, 0.1)
        self.assertEqual(calls, ["history"])

        translation = buttons["Translation"]
        translation.focus_set()
        pump(self.overlay.root, 0.05)
        translation.event_generate("<space>")
        pump(self.overlay.root, 0.1)
        self.assertEqual(calls, ["history", "translation"])

        stats = buttons["Stats"]
        stats.event_generate("<Enter>", x=8, y=8)
        stats.event_generate("<ButtonPress-1>", x=8, y=8)
        stats.event_generate("<ButtonRelease-1>", x=8, y=8)
        pump(self.overlay.root, 0.2)
        self.assertEqual(calls, ["history", "translation", "stats"])

    def test_pending_layout_commits_while_hidden_on_the_non_cloaked_restore(self) -> None:
        """X-429: the same claim, on the path that does not get a DWM cloak.

        The cloaked fast path finishes the pending rail layout while DWM still
        withholds the surface. Screen readers, a refused cloak and every
        non-Windows session take the native/withdrawn path instead, and that
        path used to deiconify and clear _talkdat_minimized BEFORE lifting rail
        suspension -- so the layout committed onto a window the user could
        already see. That is the half-packed restore frame the suspension
        exists to prevent.

        It surfaced as roughly one flaky run in eight of the test above, and
        four in four under CPU load, because load is what makes the cloak fail.
        Forcing the cloak off makes it deterministic.
        """
        self.overlay.config.setdefault("ui", {})["reduce_motion"] = False
        self.overlay.config["ui"]["menu_sidebar_open"] = True
        route = "rail_native_restore_probe"
        work_area = (-33000, -33000, -29000, -29000)

        with (
            mock.patch.object(self.overlay, "_pill_monitor_work_area", return_value=work_area),
            mock.patch.object(self.overlay, "_window_monitor_work_area", return_value=work_area),
            # No cloak: this is the path the bug lived on.
            mock.patch.object(self.overlay, "_try_dwm_cloak_utility", return_value=False),
        ):
            palette = self.overlay._settings_palette(self.overlay._settings_theme_key())
            host = self.overlay._utility_window(
                route,
                "Talk DAT! Rail Native Restore Probe",
                "640x460",
                bg=palette["bg"],
                resizable=True,
                minimum_size=(520, 360),
            )
            tk.Frame(host, bg=palette["bg"]).pack(fill="both", expand=True)
            pump(self.overlay.root, 0.9)

            rail = getattr(host, "_menu_rail", None)
            self.assertIsInstance(rail, tk.Toplevel)
            state = getattr(rail, "_talkdat_rail_state", None)
            self.assertIsInstance(state, dict)
            widgets = descendants(rail)
            toggle = next(
                widget
                for widget in widgets
                if isinstance(widget, (tk.Button, FlatButton)) and str(widget.cget("text")) == "Collapse sidebar"
            )
            brand = next(
                widget
                for widget in widgets
                if isinstance(widget, tk.Label) and str(widget.cget("text")) == "Talk DAT!"
            )

            packed_while_minimized: list[bool] = []
            original_pack = brand.pack

            def tracked_pack(*args, **kwargs):
                packed_while_minimized.append(
                    bool(getattr(host, "_talkdat_minimized", False))
                )
                return original_pack(*args, **kwargs)

            with mock.patch.object(brand, "pack", side_effect=tracked_pack):
                toggle.invoke()  # start a collapse, so a layout is pending
                self.overlay._request_utility_minimize(host)
                self.assertTrue(state["suspended"])
                self.assertNotEqual(
                    str(getattr(host, "_talkdat_minimize_mode", "")),
                    "cloaked",
                    "the cloak was supposed to be refused for this test",
                )
                packed_while_minimized.clear()

                toggle.invoke()  # queue "open" while hidden; brand must repack on restore
                self.assertTrue(state["open"])
                self.assertTrue(callable(state["layout_commit"]))

                self.assertTrue(self.overlay._focus_utility_window(route))
                pump(self.overlay.root, 0.25)

            self.assertTrue(
                packed_while_minimized,
                "the queued layout never committed on restore",
            )
            self.assertEqual(
                packed_while_minimized,
                [True] * len(packed_while_minimized),
                "the rail re-laid-out after the host was already visible: "
                "suspension must lift while the window is still hidden",
            )

    def test_minimize_suspends_rail_transition_and_restores_only_latest_layout(self) -> None:
        self.overlay.config.setdefault("ui", {})["reduce_motion"] = False
        self.overlay.config["ui"]["menu_sidebar_open"] = True
        route = "rail_minimize_probe"
        work_area = (-33000, -33000, -29000, -29000)

        with (
            mock.patch.object(self.overlay, "_pill_monitor_work_area", return_value=work_area),
            mock.patch.object(self.overlay, "_window_monitor_work_area", return_value=work_area),
        ):
            palette = self.overlay._settings_palette(self.overlay._settings_theme_key())
            host = self.overlay._utility_window(
                route,
                "Talk DAT! Rail Minimize Probe",
                "640x460",
                bg=palette["bg"],
                resizable=True,
                minimum_size=(520, 360),
            )
            self.assertIsInstance(host, tk.Toplevel)
            tk.Frame(host, bg=palette["bg"]).pack(fill="both", expand=True)
            pump(self.overlay.root, 0.9)

            rail = getattr(host, "_menu_rail", None)
            self.assertIsInstance(rail, tk.Toplevel)
            state = getattr(rail, "_talkdat_rail_state", None)
            self.assertIsInstance(state, dict)
            widgets = descendants(rail)
            toggle = next(
                widget
                for widget in widgets
                if isinstance(widget, (tk.Button, FlatButton)) and str(widget.cget("text")) == "Collapse sidebar"
            )
            brand = next(
                widget
                for widget in widgets
                if isinstance(widget, tk.Label) and str(widget.cget("text")) == "Talk DAT!"
            )
            disabled_row = next(
                widget
                for widget in widgets
                if isinstance(widget, (tk.Button, FlatButton)) and str(widget.cget("text")) == "History"
            )
            header = brand.master
            body = header.master
            items = next(
                child
                for child in body.winfo_children()
                if child is not header and isinstance(child, tk.Frame)
            )
            self.assertEqual(brand.winfo_manager(), "pack")
            self.assertEqual(items.winfo_manager(), "pack")
            self.assertEqual(str(toggle.pack_info().get("side")), "right")
            initial_width = int(state["width"])
            initial_geometry = str(state["last_geometry"])

            # Pin a portable disabled control state and, where Tk exposes it,
            # the Windows/Aqua Toplevel disabled flag. Neither may be reset by
            # withdraw/deiconify or by the deferred layout commit.
            disabled_row.configure(state="disabled")
            native_disabled_supported = False
            with contextlib.suppress(tk.TclError):
                rail.attributes("-disabled", True)
                native_disabled_supported = True

            brand_pack_while_host_minimized: list[bool] = []
            original_brand_pack = brand.pack

            def tracked_brand_pack(*args, **kwargs):
                brand_pack_while_host_minimized.append(
                    bool(getattr(host, "_talkdat_minimized", False))
                )
                return original_brand_pack(*args, **kwargs)

            with (
                mock.patch.object(brand, "pack", side_effect=tracked_brand_pack) as brand_pack,
                mock.patch.object(brand, "pack_forget", wraps=brand.pack_forget) as brand_forget,
                mock.patch.object(items, "pack", wraps=items.pack) as items_pack,
                mock.patch.object(items, "pack_forget", wraps=items.pack_forget) as items_forget,
                mock.patch.object(toggle, "pack", wraps=toggle.pack) as toggle_pack,
                mock.patch.object(toggle, "pack_forget", wraps=toggle.pack_forget) as toggle_forget,
            ):
                # Begin a real animated collapse, then suspend it before Tk can
                # deliver the fade completion or its layout closure.
                toggle.invoke()
                self.assertFalse(state["open"])
                self.assertTrue(state["transitioning"])
                first_pending_layout = state["layout_commit"]
                collapsed_target = int(state["layout_target"])
                self.assertNotEqual(collapsed_target, initial_width)

                self.overlay._request_utility_minimize(host)
                self.assertTrue(state["suspended"])
                self.assertFalse(state["transitioning"])
                if str(getattr(host, "_talkdat_minimize_mode", "")) == "cloaked":
                    self.assertTrue(getattr(host, "_talkdat_cloaked_handles", ()))
                else:
                    self.assertFalse(rail.winfo_viewable())
                # X-360: measure the window this test is actually about.
                #
                # These mocks were installed before toggle.invoke(), so they
                # also counted the LEGITIMATE re-render that happens partway
                # through the collapse animation: as the rail narrows past
                # open_width, apply_follow flips auto_collapsed and renders
                # the icon state, which unpacks the brand. Whether that had
                # happened before the minimize landed came down to how far
                # the animation had travelled, so this test failed roughly
                # once in four runs against completely correct behaviour --
                # and it had been read as "the GUI suite is flaky" rather
                # than as a test measuring the wrong interval.
                #
                # The claim being defended is about what happens AFTER the
                # rail is withdrawn, so the count starts there.
                for spy in (brand_pack, brand_forget, items_pack,
                            items_forget, toggle_pack, toggle_forget):
                    spy.reset_mock()
                frozen_width = int(state["width"])
                frozen_geometry = str(state["last_geometry"])
                frozen_layout = state["layout_commit"]
                pump(self.overlay.root, 0.25)

                # No stale fade/follow callback may mutate a withdrawn rail.
                self.assertEqual(brand_pack.call_count, 0)
                self.assertEqual(brand_forget.call_count, 0)
                self.assertEqual(items_pack.call_count, 0)
                self.assertEqual(items_forget.call_count, 0)
                self.assertEqual(toggle_pack.call_count, 0)
                self.assertEqual(toggle_forget.call_count, 0)
                # Compared against the moment of suspension, not against the
                # values from before the collapse began. How far the animation
                # had travelled when the minimize landed is a race the test
                # does not control and is not making a claim about; that
                # suspension FREEZES whatever it caught is the claim, and it
                # holds at any point in the slide.
                self.assertEqual(int(state["width"]), frozen_width)
                self.assertEqual(str(state["last_geometry"]), frozen_geometry)
                self.assertIs(state["layout_commit"], frozen_layout)
                for timer_key in ("animation_after", "follow_after", "commit_after"):
                    self.assertIsNone(state[timer_key])

                # Queue three competing requests while hidden. Each must only
                # replace the pending closure; none may repack the rail yet.
                toggle.invoke()  # open
                hidden_open_layout = state["layout_commit"]
                toggle.invoke()  # collapse
                hidden_collapse_layout = state["layout_commit"]
                toggle.invoke()  # open is the latest request
                latest_layout = state["layout_commit"]
                self.assertIsNot(hidden_open_layout, first_pending_layout)
                self.assertIsNot(hidden_collapse_layout, hidden_open_layout)
                self.assertIsNot(latest_layout, hidden_collapse_layout)
                self.assertTrue(state["open"])
                self.assertEqual(int(state["layout_target"]), initial_width)
                pump(self.overlay.root, 0.15)
                self.assertEqual(brand_pack.call_count, 0)
                self.assertEqual(brand_forget.call_count, 0)
                self.assertEqual(items_pack.call_count, 0)
                self.assertEqual(items_forget.call_count, 0)
                self.assertEqual(toggle_pack.call_count, 0)
                self.assertEqual(toggle_forget.call_count, 0)

                self.assertTrue(self.overlay._focus_utility_window(route))
                pump(self.overlay.root, 0.25)

                # The one newest layout commits while the host remains visually
                # minimized, whether the follower is withdrawn or DWM-cloaked.
                self.assertEqual(brand_pack.call_count, 1)
                self.assertEqual(items_pack.call_count, 1)
                self.assertEqual(toggle_forget.call_count, 1)
                self.assertEqual(toggle_pack.call_count, 1)
                self.assertEqual(brand_forget.call_count, 0)
                self.assertEqual(items_forget.call_count, 0)
                if mac_support.IS_MAC:
                    # The withdraw path restores before the deferred commit lands
                    # (no DWM cloak to hold the host); exactly one commit is the claim.
                    self.assertEqual(len(brand_pack_while_host_minimized), 1)
                else:
                    self.assertEqual(brand_pack_while_host_minimized, [True])

            self.assertFalse(state["suspended"])
            self.assertFalse(state["transitioning"])
            self.assertIsNone(state["layout_target"])
            self.assertIsNone(state["layout_commit"])
            self.assertEqual(int(state["width"]), initial_width)
            self.assertTrue(host.winfo_viewable())
            self.assertTrue(rail.winfo_viewable())
            self.assertEqual(str(disabled_row.cget("state")), "disabled")
            if native_disabled_supported:
                self.assertTrue(bool(rail.attributes("-disabled")))

            expected = self.overlay._sidebar_docked_geometry(
                host_x=host.winfo_rootx(),
                host_y=host.winfo_rooty(),
                host_width=host.winfo_width(),
                host_height=host.winfo_height(),
                requested_width=initial_width,
                work_area=work_area,
            )
            actual = (
                rail.winfo_width(),
                rail.winfo_height(),
                rail.winfo_rootx(),
                rail.winfo_rooty(),
            )
            self.assertEqual(actual, expected)
            self.assertEqual(str(rail.winfo_geometry()), str(state["last_geometry"]))

            # Rapid interruption cycles retain the same host/follower objects,
            # coalesce back to the latest open layout, and never clear disabled.
            for cycle in range(3):
                with self.subTest(cycle=cycle):
                    toggle.invoke()  # begin collapse
                    self.overlay._request_utility_minimize(host)
                    toggle.invoke()  # latest request returns to open while hidden
                    self.assertTrue(self.overlay._focus_utility_window(route))
                    pump(self.overlay.root, 0.12)
                    self.assertIs(getattr(host, "_menu_rail", None), rail)
                    self.assertIs(self.overlay.utility_windows.get(route), host)
                    self.assertTrue(host.winfo_viewable())
                    self.assertTrue(rail.winfo_viewable())
                    self.assertTrue(state["open"])
                    self.assertFalse(state["suspended"])
                    self.assertFalse(state["transitioning"])
                    self.assertIsNone(state["layout_target"])
                    self.assertIsNone(state["layout_commit"])
                    self.assertEqual(str(disabled_row.cget("state")), "disabled")
                    if native_disabled_supported:
                        self.assertTrue(bool(rail.attributes("-disabled")))
                    self.assertEqual(
                        (
                            rail.winfo_width(),
                            rail.winfo_height(),
                            rail.winfo_rootx(),
                            rail.winfo_rooty(),
                        ),
                        expected,
                    )


if __name__ == "__main__":
    unittest.main()
