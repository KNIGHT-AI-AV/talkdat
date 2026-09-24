from __future__ import annotations

import os

import inspect
import unittest
from types import SimpleNamespace
from unittest import mock

import numpy as np
from PIL import Image

from knight_flow.overlay import DWM_THUMBNAIL_PROPERTIES, Overlay
from knight_flow.ui import flow_console


class FakeWindow:
    def __init__(self) -> None:
        self.exists = True
        self.callbacks: dict[str, object] = {}
        self.cancelled: list[str] = []
        self.geometries: list[str] = []
        self.generated: list[tuple[str, str | None]] = []
        self.alpha_values: list[float] = []
        self.destroy_count = 0
        self.bind_calls: list[tuple[str, str | None]] = []
        self.bound_callbacks: dict[str, list[object]] = {}
        self._counter = 0
        self._alpha = 1.0

    def _receipt(self, callback: object) -> str:
        self._counter += 1
        receipt = f"after-{self._counter}"
        self.callbacks[receipt] = callback
        return receipt

    def after(self, _delay: int, callback: object) -> str:
        return self._receipt(callback)

    def after_idle(self, callback: object) -> str:
        return self._receipt(callback)

    def after_cancel(self, receipt: str) -> None:
        self.cancelled.append(receipt)
        self.callbacks.pop(receipt, None)

    def run_next(self) -> None:
        receipt = next(iter(self.callbacks))
        callback = self.callbacks.pop(receipt)
        callback()  # type: ignore[operator]

    def run_all(self, limit: int = 30) -> None:
        for _ in range(limit):
            if not self.callbacks:
                return
            self.run_next()
        raise AssertionError("fake window still owns callbacks")

    def geometry(self, value: str) -> None:
        self.geometries.append(value)

    def winfo_exists(self) -> bool:
        return self.exists

    def event_generate(self, name: str, *, when: str | None = None) -> None:
        self.generated.append((name, when))

    def attributes(self, name: str, value: float | None = None):
        if name != "-alpha":
            return False
        if value is None:
            return self._alpha
        self._alpha = float(value)
        self.alpha_values.append(self._alpha)
        return None

    def bind(self, sequence: str, _callback: object, add: str | None = None) -> str:
        self.bind_calls.append((sequence, add))
        self.bound_callbacks.setdefault(sequence, []).append(_callback)
        return f"bind-{len(self.bind_calls)}"

    def destroy(self) -> None:
        self.destroy_count += 1
        self.exists = False
        event = SimpleNamespace(widget=self)
        for callback in tuple(self.bound_callbacks.get("<Destroy>", ())):
            callback(event)  # type: ignore[operator]


class FakeManagedContent:
    def __init__(self) -> None:
        self.exists = True
        self.manager = "grid"

    def winfo_exists(self) -> bool:
        return self.exists

    def winfo_manager(self) -> str:
        return self.manager

    def grid_remove(self) -> None:
        self.manager = ""

    def grid(self) -> None:
        self.manager = "grid"


class FakeProxyLabel:
    def __init__(self) -> None:
        self.exists = True
        self.lifts = 0

    def place(self, **_kwargs: object) -> None:
        return None

    def place_configure(self, **_kwargs: object) -> None:
        return None

    def configure(self, **_kwargs: object) -> None:
        return None

    def lift(self) -> None:
        self.lifts += 1

    def winfo_exists(self) -> bool:
        return self.exists

    def destroy(self) -> None:
        self.exists = False


class FakeExternalProxy:
    def __init__(self) -> None:
        self.exists = True
        self.geometries: list[str] = []
        self.alpha = 0.0
        self.destroy_count = 0

    def withdraw(self) -> None:
        return None

    def overrideredirect(self, _value: bool) -> None:
        return None

    def transient(self, _owner: object) -> None:
        return None

    def configure(self, **_kwargs: object) -> None:
        return None

    def attributes(self, name: str, value: object | None = None):
        if name == "-alpha":
            if value is None:
                return self.alpha
            self.alpha = float(value)
            return None
        return False

    def geometry(self, value: str) -> None:
        self.geometries.append(value)

    def deiconify(self) -> None:
        return None

    def lift(self, *_args: object) -> None:
        return None

    def update_idletasks(self) -> None:
        return None

    def winfo_exists(self) -> bool:
        return self.exists

    def destroy(self) -> None:
        self.destroy_count += 1
        self.exists = False


class FakeExternalLabel:
    def __init__(self, *_args: object, **_kwargs: object) -> None:
        self.configures = 0

    def pack(self, **_kwargs: object) -> None:
        return None

    def configure(self, **_kwargs: object) -> None:
        self.configures += 1


def bare_overlay(*, reduce_motion: bool = False) -> Overlay:
    overlay = object.__new__(Overlay)
    overlay.config = {"ui": {"reduce_motion": reduce_motion}}
    overlay._root_destroyed = False
    overlay.utility_windows = {}
    overlay._window_disposers = {}
    overlay.utility_drag_origin = None
    overlay.set_state = mock.Mock()
    return overlay


class LatestGeometryWinsTests(unittest.TestCase):
    @staticmethod
    def _prepare_external_host(window: FakeWindow) -> None:
        window.winfo_width = lambda: 640  # type: ignore[attr-defined]
        window.winfo_height = lambda: 480  # type: ignore[attr-defined]
        window.winfo_rootx = lambda: -1920  # type: ignore[attr-defined]
        window.winfo_rooty = lambda: 120  # type: ignore[attr-defined]
        window.winfo_viewable = lambda: True  # type: ignore[attr-defined]
        window.winfo_id = lambda: 101  # type: ignore[attr-defined]
        window.cget = lambda _key: "#071114"  # type: ignore[attr-defined]

    def test_one_hundred_pointer_targets_become_one_geometry(self) -> None:
        overlay = bare_overlay()
        window = FakeWindow()

        for index in range(100):
            overlay._queue_window_geometry(window, f"{500 + index}x400+10+20")  # type: ignore[arg-type]

        self.assertEqual(len(window.callbacks), 1)
        self.assertEqual(window.geometries, [])
        window.run_next()
        self.assertEqual(window.geometries, ["599x400+10+20"])
        self.assertEqual(window.callbacks, {})

    def test_target_arriving_during_flush_gets_one_follow_up_frame(self) -> None:
        overlay = bare_overlay()
        window = FakeWindow()

        def geometry(value: str) -> None:
            window.geometries.append(value)
            if len(window.geometries) == 1:
                overlay._queue_window_geometry(window, "720x520+3+4")  # type: ignore[arg-type]

        window.geometry = geometry  # type: ignore[method-assign]
        overlay._queue_window_geometry(window, "700x500+3+4")  # type: ignore[arg-type]
        window.run_next()
        self.assertEqual(window.geometries, ["700x500+3+4"])
        self.assertEqual(len(window.callbacks), 1)
        window.run_next()
        self.assertEqual(window.geometries, ["700x500+3+4", "720x520+3+4"])

    def test_release_applies_exact_target_and_settles_once(self) -> None:
        overlay = bare_overlay()
        window = FakeWindow()
        overlay._begin_window_resize(window)  # type: ignore[arg-type]
        overlay._queue_window_geometry(window, "899x677+11+12")  # type: ignore[arg-type]
        overlay._queue_window_geometry(window, "900x680+11+12", final=True)  # type: ignore[arg-type]

        self.assertFalse(window._talkdat_live_resize)  # type: ignore[attr-defined]
        self.assertEqual(window.geometries, ["900x680+11+12"])
        self.assertEqual(len(window.callbacks), 1)
        window.run_all()
        self.assertEqual(window.generated, [("<<TalkDATGeometrySettled>>", "tail")])

    def test_cancelled_generation_cannot_touch_a_destroying_window(self) -> None:
        overlay = bare_overlay()
        window = FakeWindow()
        overlay._queue_window_geometry(window, "800x600+0+0")  # type: ignore[arg-type]
        callback = next(iter(window.callbacks.values()))
        overlay._cancel_window_geometry_motion(window)  # type: ignore[arg-type]
        callback()  # type: ignore[operator]
        self.assertEqual(window.geometries, [])

    def test_resize_begin_invalidates_geometry_changed_outside_the_queue(self) -> None:
        overlay = bare_overlay()
        window = FakeWindow()
        overlay._queue_window_geometry(window, "900x680+11+12")  # type: ignore[arg-type]
        window.run_next()
        window.geometry("1000x720+11+12")

        overlay._begin_window_resize(window)  # type: ignore[arg-type]
        overlay._queue_window_geometry(  # type: ignore[arg-type]
            window,
            "900x680+11+12",
            final=True,
        )

        self.assertEqual(window.geometries[-1], "900x680+11+12")
        self.assertEqual(len(window.geometries), 3)

    def test_repress_cancels_the_previous_release_settlement(self) -> None:
        overlay = bare_overlay()
        window = FakeWindow()
        overlay._begin_window_resize(window)  # type: ignore[arg-type]
        overlay._queue_window_geometry(window, None, final=True)  # type: ignore[arg-type]
        self.assertEqual(len(window.callbacks), 1)

        overlay._begin_window_resize(window)  # type: ignore[arg-type]

        self.assertEqual(window.callbacks, {})
        self.assertTrue(window._talkdat_live_resize)  # type: ignore[attr-defined]
        self.assertEqual(window.generated, [])

    def test_resize_proxy_survives_release_then_immediate_repress(self) -> None:
        overlay = bare_overlay()
        window = FakeWindow()
        content = FakeManagedContent()
        proxy = FakeProxyLabel()
        window.winfo_width = lambda: 640  # type: ignore[attr-defined]
        window.winfo_height = lambda: 480  # type: ignore[attr-defined]
        window.winfo_rootx = lambda: 10  # type: ignore[attr-defined]
        window.winfo_rooty = lambda: 20  # type: ignore[attr-defined]
        window.winfo_viewable = lambda: True  # type: ignore[attr-defined]
        window.cget = lambda _key: "#071114"  # type: ignore[attr-defined]

        with (
            mock.patch("knight_flow.overlay.os.name", "posix"),
            mock.patch("PIL.ImageGrab.grab", return_value=Image.new("RGB", (640, 480))),
            mock.patch("knight_flow.overlay.ImageTk.PhotoImage", return_value=object()),
            mock.patch("knight_flow.overlay.tk.Label", return_value=proxy),
        ):
            overlay._install_resize_visual_proxy(window, content)  # type: ignore[arg-type]
            window._talkdat_begin_resize_proxy()  # type: ignore[attr-defined]
            self.assertEqual(content.manager, "")
            window._talkdat_finish_resize_proxy()  # type: ignore[attr-defined]
            self.assertEqual(content.manager, "grid")
            self.assertTrue(window.callbacks)

            window._talkdat_begin_resize_proxy()  # type: ignore[attr-defined]

        self.assertEqual(content.manager, "")
        self.assertEqual(window.callbacks, {})
        self.assertTrue(proxy.exists)
        self.assertTrue(window._talkdat_resize_proxy_state["active"])  # type: ignore[attr-defined]

    @unittest.skipUnless(os.name == "nt", "the external compositor proxy is the Windows path; other platforms keep the in-window proxy")
    def test_external_proxy_gets_live_geometry_and_host_gets_final_once(self) -> None:
        overlay = bare_overlay()
        overlay._make_no_activate = mock.Mock()  # type: ignore[method-assign]
        overlay._window_monitor_work_area = mock.Mock(  # type: ignore[method-assign]
            return_value=(-1920, 0, 0, 1080)
        )
        window = FakeWindow()
        self._prepare_external_host(window)
        content = FakeManagedContent()
        proxy = FakeExternalProxy()
        rail_follow = mock.Mock()
        window._talkdat_follow_menu_rail_box = rail_follow  # type: ignore[attr-defined]

        with (
            mock.patch("knight_flow.overlay.tk.Toplevel", return_value=proxy),
            mock.patch("PIL.ImageGrab.grab", return_value=Image.new("RGB", (640, 480))),
            mock.patch("knight_flow.overlay.ImageTk.PhotoImage", return_value=object()),
            mock.patch("knight_flow.overlay.tk.Label", side_effect=FakeExternalLabel),
        ):
            overlay._install_resize_visual_proxy(window, content)  # type: ignore[arg-type]
            overlay._begin_window_resize(window)  # type: ignore[arg-type]
            for index in range(100):
                overlay._queue_window_geometry(  # type: ignore[arg-type]
                    window,
                    f"{700 + index}x520+-1920+120",
                )
            window.run_next()

            self.assertEqual(window.geometries, [])
            self.assertEqual(proxy.geometries[-1], "799x520+-1920+120")
            self.assertEqual(content.manager, "grid")
            rail_follow.assert_called_with(
                (799, 520, -1920, 120),
                (-1920, 0, 0, 1080),
                False,
            )

            overlay._finish_window_resize(window)  # type: ignore[arg-type]
            self.assertEqual(window.geometries, ["799x520+-1920+120"])
            self.assertTrue(proxy.exists, "proxy vanished before the real tree settled")
            self.assertTrue(
                window._talkdat_live_resize,  # type: ignore[attr-defined]
                "heavy Configure painters woke before the compositor handoff finished",
            )
            window.run_all()

        self.assertFalse(proxy.exists)
        self.assertFalse(window._talkdat_resize_proxy_state["active"])  # type: ignore[attr-defined]
        self.assertFalse(window._talkdat_live_resize)  # type: ignore[attr-defined]
        self.assertEqual(window.generated, [("<<TalkDATGeometrySettled>>", "tail")])
        self.assertEqual(window._alpha, 1.0)

    @unittest.skipUnless(os.name == "nt", "the external compositor proxy is the Windows path; other platforms keep the in-window proxy")
    def test_external_proxy_construction_failure_leaves_no_orphan(self) -> None:
        overlay = bare_overlay()
        overlay._make_no_activate = mock.Mock()  # type: ignore[method-assign]
        overlay._window_monitor_work_area = mock.Mock(return_value=None)  # type: ignore[method-assign]
        window = FakeWindow()
        self._prepare_external_host(window)
        content = FakeManagedContent()
        proxy = FakeExternalProxy()

        with (
            mock.patch("knight_flow.overlay.tk.Toplevel", return_value=proxy),
            mock.patch("PIL.ImageGrab.grab", return_value=Image.new("RGB", (640, 480))),
            mock.patch(
                "knight_flow.overlay.ImageTk.PhotoImage",
                side_effect=RuntimeError("image allocation failed"),
            ),
        ):
            overlay._install_resize_visual_proxy(window, content)  # type: ignore[arg-type]
            overlay._begin_window_resize(window)  # type: ignore[arg-type]
            overlay._queue_window_geometry(  # type: ignore[arg-type]
                window,
                "700x500+-1920+120",
                final=True,
            )

        self.assertFalse(proxy.exists)
        self.assertEqual(proxy.destroy_count, 1)
        self.assertFalse(window._talkdat_resize_proxy_state["active"])  # type: ignore[attr-defined]
        self.assertEqual(window.geometries, ["700x500+-1920+120"])
        self.assertEqual(window._alpha, 1.0)

    def test_every_proxy_uses_one_process_wide_dwm_structure_type(self) -> None:
        source = inspect.getsource(Overlay._install_resize_visual_proxy)
        self.assertNotIn("class _DwmThumbnailProperties", source)
        self.assertIn("ctypes.POINTER(DWM_THUMBNAIL_PROPERTIES)", source)
        self.assertEqual(DWM_THUMBNAIL_PROPERTIES.__name__, "DWM_THUMBNAIL_PROPERTIES")

    def test_proxy_chrome_and_click_through_land_before_alpha_rises(self) -> None:
        source = inspect.getsource(Overlay._install_resize_visual_proxy)
        begin = source[source.index("def begin()") : source.index("def update(")]
        role = 'role=str(getattr(window, "_talkdat_chrome_role", UTILITY_CHROME))'
        transparent = "self._make_no_activate(proxy, click_through=True)"
        reveal = 'proxy.attributes("-alpha", host_alpha)'
        self.assertIn(role, begin)
        self.assertLess(begin.index(role), begin.index("apply_window_chrome("))
        self.assertLess(begin.index("apply_window_chrome("), begin.index(transparent))
        self.assertLess(begin.index(transparent), begin.index(reveal))


class WindowTransitionTests(unittest.TestCase):
    def test_reduced_motion_sets_final_alpha_without_a_timer(self) -> None:
        overlay = bare_overlay(reduce_motion=True)
        window = FakeWindow()
        complete = mock.Mock()
        overlay._animate_window_alpha(  # type: ignore[arg-type]
            window,
            start=0.0,
            target=0.98,
            duration_ms=120,
            on_complete=complete,
        )
        self.assertEqual(window.callbacks, {})
        self.assertEqual(window.alpha_values[-1], 0.98)
        complete.assert_called_once_with()

    def test_elapsed_time_fade_lands_exactly_and_completes_once(self) -> None:
        overlay = bare_overlay()
        window = FakeWindow()
        complete = mock.Mock()
        with mock.patch(
            "knight_flow.overlay.time.perf_counter",
            side_effect=[0.0, 0.0, 0.05, 0.1],
        ):
            overlay._animate_window_alpha(  # type: ignore[arg-type]
                window,
                start=0.0,
                target=1.0,
                duration_ms=100,
                on_complete=complete,
            )
            window.run_all()
        self.assertEqual(window.alpha_values[-1], 1.0)
        self.assertEqual(window.alpha_values, sorted(window.alpha_values))
        complete.assert_called_once_with()

    def test_close_disposes_before_fade_and_destroys_after(self) -> None:
        overlay = bare_overlay(reduce_motion=True)
        window = FakeWindow()
        dispose = mock.Mock()
        overlay.utility_windows = {"scratchpad": window}  # type: ignore[dict-item]
        overlay._window_disposers = {"scratchpad": [dispose]}
        overlay._request_utility_close(window)  # type: ignore[arg-type]
        dispose.assert_called_once_with()
        self.assertEqual(window.destroy_count, 1)

    def test_close_lock_remains_authoritative(self) -> None:
        overlay = bare_overlay(reduce_motion=True)
        window = FakeWindow()
        window._close_locked = True  # type: ignore[attr-defined]
        window._close_lock_message = "Still installing."  # type: ignore[attr-defined]
        overlay._request_utility_close(window)  # type: ignore[arg-type]
        self.assertEqual(window.destroy_count, 0)
        overlay.set_state.assert_called_once_with("processing", "Still installing.", "")

    def test_close_before_present_cancels_the_reveal_and_cannot_resurrect(self) -> None:
        overlay = bare_overlay(reduce_motion=True)
        window = FakeWindow()
        overlay._schedule_utility_present(window)  # type: ignore[arg-type]
        self.assertEqual(len(window.callbacks), 1)

        overlay._request_utility_close(window)  # type: ignore[arg-type]

        self.assertFalse(window.exists)
        self.assertEqual(window.callbacks, {})
        self.assertTrue(window._talkdat_close_requested)  # type: ignore[attr-defined]

    def test_pending_page_geometry_is_scoped_to_the_latest_presentation(self) -> None:
        overlay = bare_overlay(reduce_motion=True)
        window = FakeWindow()
        overlay._schedule_utility_present(  # type: ignore[arg-type]
            window,
            final_geometry="1180x940+1372+431",
        )
        overlay._schedule_utility_present(window)  # type: ignore[arg-type]

        window.run_all()

        self.assertEqual(window.geometries, [])
        self.assertIsNone(window._talkdat_pending_page_geometry)  # type: ignore[attr-defined]

    def test_latest_page_geometry_lands_before_reveal_and_then_clears(self) -> None:
        overlay = bare_overlay(reduce_motion=True)
        window = FakeWindow()
        target = "1180x940+1372+431"
        overlay._schedule_utility_present(  # type: ignore[arg-type]
            window,
            final_geometry=target,
        )

        window.run_all()

        self.assertEqual(window.geometries, [target, target])
        self.assertEqual(window.alpha_values[-1], 1.0)
        self.assertIsNone(window._talkdat_pending_page_geometry)  # type: ignore[attr-defined]

    def test_utility_reveal_cannot_run_inside_builder_idle_measurement(self) -> None:
        source = inspect.getsource(Overlay._schedule_utility_present)
        self.assertIn("window.after(0, queue_second_idle)", source)
        self.assertNotIn("window.after_idle(queue_second_idle)", source)

    def test_represent_invalidates_an_inflight_alpha_tick_before_build(self) -> None:
        overlay = bare_overlay()
        window = FakeWindow()
        with mock.patch("knight_flow.overlay.time.perf_counter", return_value=0.0):
            overlay._animate_window_alpha(  # type: ignore[arg-type]
                window,
                start=0.0,
                target=1.0,
                duration_ms=120,
            )
        stale_tick = next(iter(window.callbacks.values()))

        overlay._schedule_utility_present(window)  # type: ignore[arg-type]
        self.assertEqual(window.alpha_values[-1], 0.0)
        stale_tick()  # type: ignore[operator]

        self.assertEqual(window.alpha_values[-1], 0.0)

    def test_popup_action_runs_once_if_parent_destroys_during_the_fade(self) -> None:
        overlay = bare_overlay()
        window = FakeWindow()
        action = mock.Mock()
        overlay._request_popup_close(  # type: ignore[arg-type]
            window,
            on_complete=action,
        )
        self.assertTrue(window.callbacks)

        window.destroy()
        window.run_all()

        action.assert_called_once_with()

    def test_closing_shell_is_detached_before_its_visual_retirement(self) -> None:
        overlay = bare_overlay(reduce_motion=True)
        window = FakeWindow()
        overlay._shell_window = window  # type: ignore[attr-defined]
        overlay._request_utility_close(window)  # type: ignore[arg-type]
        self.assertIsNone(overlay._shell_window)  # type: ignore[attr-defined]

    def test_closing_an_unpresented_destination_retires_its_visible_cover(self) -> None:
        overlay = bare_overlay(reduce_motion=True)
        outgoing = FakeWindow()
        destination = FakeWindow()
        destination._talkdat_transition_outgoing = outgoing  # type: ignore[attr-defined]
        overlay._shell_window = destination  # type: ignore[attr-defined]

        overlay._request_utility_close(destination)  # type: ignore[arg-type]

        self.assertFalse(destination.exists)
        self.assertFalse(outgoing.exists)
        self.assertIsNone(overlay._shell_window)  # type: ignore[attr-defined]

    def test_reduced_motion_shows_destination_before_old_tree_cleanup(self) -> None:
        source = inspect.getsource(Overlay._schedule_utility_present)
        transition = source[source.index("outgoing = getattr(window"):]
        self.assertLess(
            transition.index("self._animate_window_alpha("),
            transition.index("self._request_utility_close(outgoing)"),
        )


class BindingAndRegionBudgetTests(unittest.TestCase):
    def test_idle_flow_frame_does_not_keep_invalidating_the_rest_gate(self) -> None:
        source = inspect.getsource(Overlay._animate)
        start = source.index("rest_signature = (")
        end = source.index("if at_rest and rest_signature", start)
        signature = source[start:end]

        self.assertNotIn(
            "last_flow_render_key",
            signature,
            "the elapsed idle loop key makes every timer tick redraw while the UI is busy",
        )
        self.assertIn("self.state", signature)
        self.assertIn("self.current_width", signature)
        self.assertIn("target_alpha", signature)

    def test_drag_anywhere_is_installed_once_per_shell(self) -> None:
        overlay = bare_overlay()
        window = FakeWindow()
        overlay._bind_drag_anywhere(window)  # type: ignore[arg-type]
        overlay._bind_drag_anywhere(window)  # type: ignore[arg-type]
        self.assertEqual(len(window.bind_calls), 3)
        self.assertEqual(
            set(window._talkdat_drag_bindings),  # type: ignore[attr-defined]
            {"<ButtonPress-1>", "<B1-Motion>", "<ButtonRelease-1>"},
        )

    def test_drag_fallback_suppresses_painters_until_release(self) -> None:
        overlay = bare_overlay()
        window = FakeWindow()
        window.winfo_x = lambda: 10  # type: ignore[attr-defined]
        window.winfo_y = lambda: 20  # type: ignore[attr-defined]
        overlay._begin_native_window_drag = mock.Mock(return_value=False)  # type: ignore[method-assign]
        overlay._snap_on_release = mock.Mock()  # type: ignore[method-assign]
        overlay._bind_drag_anywhere(window)  # type: ignore[arg-type]

        press = window.bound_callbacks["<ButtonPress-1>"][0]
        release = window.bound_callbacks["<ButtonRelease-1>"][0]
        press(SimpleNamespace(widget=window, x_root=100, y_root=200))
        self.assertTrue(window._talkdat_live_resize)  # type: ignore[attr-defined]

        release(SimpleNamespace(widget=window))
        self.assertFalse(window._talkdat_live_resize)  # type: ignore[attr-defined]
        overlay._snap_on_release.assert_called_once_with(window)

    def test_new_window_drag_settles_the_window_that_lost_its_release(self) -> None:
        overlay = bare_overlay()
        first = FakeWindow()
        second = FakeWindow()
        for index, window in enumerate((first, second), start=1):
            window.winfo_x = lambda value=index: value * 10  # type: ignore[attr-defined]
            window.winfo_y = lambda value=index: value * 20  # type: ignore[attr-defined]
        overlay._begin_native_window_drag = mock.Mock(return_value=False)  # type: ignore[method-assign]
        overlay._snap_on_release = mock.Mock()  # type: ignore[method-assign]
        overlay._bind_drag_anywhere(first)  # type: ignore[arg-type]
        overlay._bind_drag_anywhere(second)  # type: ignore[arg-type]

        first_press = first.bound_callbacks["<ButtonPress-1>"][0]
        second_press = second.bound_callbacks["<ButtonPress-1>"][0]
        second_release = second.bound_callbacks["<ButtonRelease-1>"][0]

        first_press(SimpleNamespace(widget=first, x_root=100, y_root=200))
        self.assertTrue(first._talkdat_live_resize)  # type: ignore[attr-defined]

        # Window A's release was swallowed.  A new press on B must first settle
        # A before the shared drag origin changes ownership.
        second_press(SimpleNamespace(widget=second, x_root=300, y_root=400))
        self.assertFalse(first._talkdat_live_resize)  # type: ignore[attr-defined]
        self.assertTrue(second._talkdat_live_resize)  # type: ignore[attr-defined]

        second_release(SimpleNamespace(widget=second))
        self.assertFalse(first._talkdat_live_resize)  # type: ignore[attr-defined]
        self.assertFalse(second._talkdat_live_resize)  # type: ignore[attr-defined]
        self.assertIsNone(overlay.utility_drag_origin)

    def test_ghost_drag_finishes_live_geometry_motion(self) -> None:
        overlay = bare_overlay()
        window = FakeWindow()
        window.winfo_x = lambda: 10  # type: ignore[attr-defined]
        window.winfo_y = lambda: 20  # type: ignore[attr-defined]
        overlay._begin_native_window_drag = mock.Mock(return_value=False)  # type: ignore[method-assign]
        overlay._bind_drag_anywhere(window)  # type: ignore[arg-type]

        press = window.bound_callbacks["<ButtonPress-1>"][0]
        drag = window.bound_callbacks["<B1-Motion>"][0]
        press(SimpleNamespace(widget=window, x_root=100, y_root=200))
        drag(SimpleNamespace(widget=window, state=0, x_root=110, y_root=210))

        self.assertIsNone(overlay.utility_drag_origin)
        self.assertFalse(window._talkdat_live_resize)  # type: ignore[attr-defined]

    def test_context_unfold_never_recuts_the_native_window(self) -> None:
        source = inspect.getsource(Overlay._step_context_menu_unfold)
        self.assertIn("final_shape=index == len(frames) - 1", source)
        resize_source = inspect.getsource(Overlay._resize_context_menu)
        self.assertNotIn("_apply_window_region", resize_source)
        self.assertNotIn("SetWindowRgn", resize_source)

    def test_host_configure_handlers_reject_descendant_events(self) -> None:
        backdrop = inspect.getsource(Overlay._paint_clay_backdrop)
        utility = inspect.getsource(Overlay._utility_window)
        rail = inspect.getsource(Overlay._attach_menu_rail)
        self.assertIn("event.widget is not window", backdrop)
        self.assertIn("event.widget is not window", utility)
        self.assertIn("event.widget is not window", rail)

    def test_live_proxy_moves_the_rail_hwnd_without_resizing_its_tk_tree(self) -> None:
        source = inspect.getsource(Overlay._attach_menu_rail)
        live = source[
            source.index("def follow_proxy_box"):
            source.index("window._talkdat_follow_menu_rail_box")
        ]
        self.assertIn("if final_shape:", live)
        self.assertIn("move_window_no_activate", live)
        self.assertNotIn("side.geometry(", live)

    def test_utility_resize_has_no_deferred_region_reapply(self) -> None:
        source = inspect.getsource(Overlay._utility_window)
        self.assertNotIn("def apply_region_once", source)
        self.assertNotIn("def schedule_region", source)
        self.assertNotIn("_apply_window_region", source)

    def test_prepress_clay_timer_cannot_paint_during_live_motion(self) -> None:
        overlay = bare_overlay()
        overlay._rgb = mock.Mock(return_value=(10, 20, 30))  # type: ignore[method-assign]
        window = FakeWindow()
        window.winfo_width = lambda: 640  # type: ignore[attr-defined]
        window.winfo_height = lambda: 480  # type: ignore[attr-defined]
        with (
            mock.patch("knight_flow.overlay.clay_field") as clay_field,
            mock.patch("knight_flow.overlay.ImageTk.PhotoImage"),
        ):
            overlay._paint_clay_backdrop(window, "#0a141e")  # type: ignore[arg-type]
            window._talkdat_live_resize = True  # type: ignore[attr-defined]
            window.run_next()
            clay_field.assert_not_called()

            window._talkdat_live_resize = False  # type: ignore[attr-defined]
            settled = window.bound_callbacks["<<TalkDATGeometrySettled>>"][0]
            settled(SimpleNamespace(widget=window))  # type: ignore[operator]
            window.run_all()
            clay_field.assert_called_once_with(640, 480, (10, 20, 30))

    def test_rail_animation_is_cancellable_and_reduced_motion_aware(self) -> None:
        source = inspect.getsource(Overlay._attach_menu_rail)
        self.assertIn("animation_generation", source)
        self.assertIn("side.after_cancel(receipt)", source)
        self.assertIn("self._motion_is_reduced()", source)
        self.assertIn('window.unbind(sequence, funcid)', source)
        self.assertIn("self._install_toplevel_timer_cleanup(side)", source)
        self.assertIn('side.attributes("-alpha", 0.0)', source)
        self.assertIn("self._schedule_popup_present(", source)

        close_source = inspect.getsource(Overlay._request_utility_close)
        self.assertIn('rail_state["closing"] = True', close_source)
        self.assertIn("target=0.0", close_source)

    def test_universal_rail_builds_only_after_the_page_is_presented(self) -> None:
        factory = inspect.getsource(Overlay._utility_window)
        presenter = inspect.getsource(Overlay._schedule_utility_present)

        self.assertIn("_talkdat_pending_menu_rail_current = name", factory)
        self.assertNotIn(
            "after(0, lambda: self._attach_menu_rail",
            factory,
            "the follower rail is competing with the destination's first native map",
        )
        self.assertIn("def attach_presented_rail()", presenter)
        self.assertIn("on_complete=finish_present", presenter)
        self.assertLess(
            presenter.index("def finish_present()"),
            presenter.index("def attach_presented_rail()"),
        )
        self.assertLess(
            presenter.index("def attach_presented_rail()"),
            presenter.index("on_complete=finish_present"),
        )

    def test_context_menu_installs_window_owned_timer_cleanup(self) -> None:
        source = inspect.getsource(Overlay._open_context_menu)
        self.assertIn("self._install_toplevel_timer_cleanup(window)", source)

    def test_retiring_utility_cannot_forget_a_new_same_name_window(self) -> None:
        source = inspect.getsource(Overlay._utility_window)
        self.assertIn("is_current = self.utility_windows.get(name) is window", source)
        self.assertIn("_dispose_window_instance(window, names=(name,))", source)
        self.assertIn("if is_current:", source)


class ClaySwatchCacheTests(unittest.TestCase):
    def tearDown(self) -> None:
        flow_console._clay_swatch.cache_clear()

    def test_multiple_sizes_compute_one_procedural_swatch(self) -> None:
        tile = 8

        def tile_rgb(base, *, seed):
            result = np.empty((tile, tile, 3), dtype=np.uint8)
            for y in range(tile):
                for x in range(tile):
                    result[y, x] = (
                        (base[0] + x + seed) % 256,
                        (base[1] + y) % 256,
                        base[2],
                    )
            return result

        with mock.patch.object(
            flow_console,
            "clay_tile_rgb",
            side_effect=tile_rgb,
        ) as render_tile:
            flow_console._clay_swatch.cache_clear()
            first = flow_console.clay_field(17, 11, (10, 20, 30))
            second = flow_console.clay_field(31, 19, (10, 20, 30))

        self.assertEqual(render_tile.call_count, 1)
        self.assertEqual(first.getpixel((0, 0)), second.getpixel((0, 0)))
        self.assertEqual(first.getpixel((8, 0)), first.getpixel((0, 0)))
        self.assertEqual(flow_console._clay_swatch.cache_info().hits, 1)

    def test_expanded_desktop_fields_are_not_retained(self) -> None:
        self.assertFalse(
            hasattr(flow_console.clay_field, "cache_info"),
            "full-window RGBA fields must not live in an LRU cache",
        )

    def test_clay_cache_has_no_background_tk_adjacent_warmup(self) -> None:
        source = inspect.getsource(flow_console)
        self.assertNotIn("TalkDatClayWarm", source)
        self.assertNotIn("threading.Thread", source)


if __name__ == "__main__":
    unittest.main()
