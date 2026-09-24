from __future__ import annotations

import queue
import sys
import threading
import unittest
from collections import deque
from unittest.mock import patch

from PIL import Image

from knight_flow.overlay import (
    Overlay,
    completion_rainbow_alpha,
    completion_rainbow_enabled,
    fade_layer_edges,
    faceted_voice_trace,
    loading_halo_phase_bucket,
    microphone_energy_envelope,
    next_context_menu_action,
    perceptual_voice_level,
    pill_is_expanded,
    processing_rainbow_step,
    processing_transition_alpha,
    quantized_active_render_key,
    refract_pill_material,
    scrolling_spectrum_frame,
    state_hold_delay_ms,
    transition_frame_index,
    transition_frame_order,
)


class OverlayMotionTests(unittest.TestCase):
    def test_microphone_energy_envelope_rejects_noise_and_maps_newest_audio_to_the_right(self) -> None:
        quiet = microphone_energy_envelope([0.0, 0.0002, 0.0007], 32)
        rising = microphone_energy_envelope([0.0, 0.002, 0.008, 0.025, 0.09], 64)

        self.assertEqual(quiet, (0.0,) * 32)
        self.assertEqual(rising[0], 0.0)
        self.assertEqual(rising[-1], 0.0)
        self.assertGreater(max(rising[40:60]), max(rising[4:24]))
        self.assertGreater(perceptual_voice_level(0.09), perceptual_voice_level(0.008))
        self.assertGreater(max(rising), 0.60)

    def test_live_refraction_preserves_material_size_alpha_and_silence(self) -> None:
        source = Image.new("RGBA", (72, 18), (0, 0, 0, 0))
        for x_index in range(72):
            for y_index in range(18):
                alpha = 255 if 2 <= x_index <= 69 and 1 <= y_index <= 16 else 0
                source.putpixel(
                    (x_index, y_index),
                    (
                        min(255, 20 + x_index * 3),
                        min(255, 30 + y_index * 9),
                        max(0, 210 - x_index * 2),
                        alpha,
                    ),
                )

        silent = refract_pill_material(source, [0.0] * source.width)
        envelope = microphone_energy_envelope(
            [0.0, 0.002, 0.010, 0.045, 0.12, 0.04, 0.006, 0.0],
            source.width,
        )
        active = refract_pill_material(source, envelope)

        self.assertEqual(silent.tobytes(), source.tobytes())
        self.assertEqual(active.size, source.size)
        self.assertEqual(active.getchannel("A").tobytes(), source.getchannel("A").tobytes())
        self.assertNotEqual(active.convert("RGB").tobytes(), source.convert("RGB").tobytes())
        changed = sum(
            1
            for original, reacted in zip(source.convert("RGB").getdata(), active.convert("RGB").getdata())
            if original != reacted
        )
        self.assertGreater(changed, source.width * source.height * 0.30)

    def test_faceted_voice_trace_uses_real_energy_with_sharp_signed_peaks(self) -> None:
        quiet = faceted_voice_trace([0.0] * 96)
        envelope = microphone_energy_envelope(
            [0.0, 0.003, 0.018, 0.085, 0.14, 0.055, 0.012, 0.0],
            96,
        )
        trace = faceted_voice_trace(envelope)

        self.assertEqual(quiet, (0.0,) * 96)
        self.assertEqual(trace[0], 0.0)
        self.assertEqual(trace[-1], 0.0)
        self.assertGreater(max(trace), 0.45)
        self.assertLess(min(trace), -0.35)
        corners = sum(
            1
            for index in range(1, len(trace) - 1)
            if abs(trace[index - 1] - 2.0 * trace[index] + trace[index + 1]) > 0.08
        )
        self.assertGreater(corners, 4)

    def test_voice_history_is_reset_for_each_new_live_session(self) -> None:
        overlay = Overlay.__new__(Overlay)
        overlay.voice_history = deque([0.2] * 48, maxlen=48)
        overlay.voice_history_lock = threading.Lock()

        overlay._reset_voice_history()

        self.assertEqual(overlay._voice_history_snapshot(), (0.0,) * 48)

    def test_context_menu_keyboard_navigation_wraps_and_has_endpoints(self) -> None:
        actions = ["settings", "history", "stats"]

        self.assertEqual(next_context_menu_action(actions, "", "Down"), "settings")
        self.assertEqual(next_context_menu_action(actions, "settings", "Up"), "stats")
        self.assertEqual(next_context_menu_action(actions, "stats", "Down"), "settings")
        self.assertEqual(next_context_menu_action(actions, "history", "Home"), "settings")
        self.assertEqual(next_context_menu_action(actions, "history", "End"), "stats")

    @unittest.skipUnless(
        sys.platform.startswith("win"),
        "the outer-HWND raise is Windows-only; Aqua honours Tk's own -topmost",
    )
    def test_force_visible_raises_outer_window_without_moving_client_handle(self) -> None:
        calls: list[tuple[object, ...]] = []

        class Root:
            def deiconify(self) -> None:
                calls.append(("deiconify",))

            def attributes(self, *args: object) -> None:
                calls.append(("attributes", *args))

            def lift(self) -> None:
                calls.append(("lift",))

            def winfo_id(self) -> int:
                return 11

        class User32:
            def GetAncestor(self, hwnd: int, flag: int) -> int:
                calls.append(("ancestor", hwnd, flag))
                return 22

            def SetWindowPos(self, *args: object) -> int:
                calls.append(("set", *args))
                return 1

            def BringWindowToTop(self, hwnd: int) -> int:
                calls.append(("top", hwnd))
                return 1

        overlay = Overlay.__new__(Overlay)
        overlay.root = Root()
        overlay._position = lambda: calls.append(("position",))

        with patch("knight_flow.overlay.ctypes.windll.user32", User32()):
            overlay.force_visible()

        set_call = next(call for call in calls if call[0] == "set")
        self.assertEqual(set_call[1], 22)
        self.assertEqual(set_call[3:7], (0, 0, 0, 0))
        self.assertEqual(set_call[7] & 0x0003, 0x0003)
        self.assertIn(("top", 22), calls)

    def test_processing_close_crossfades_from_live_art_to_full_rainbow(self) -> None:
        levels = [processing_transition_alpha(index, 13) for index in range(13)]

        self.assertEqual(levels[0], 1.0)
        self.assertEqual(levels[-1], 0.0)
        self.assertEqual(levels, sorted(levels, reverse=True))

    def test_geometry_lowers_minimum_before_resize_and_paints_before_flush(self) -> None:
        events: list[tuple[object, ...]] = []

        class Root:
            def minsize(self, width: int, height: int) -> None:
                events.append(("minsize", width, height))

            def geometry(self, value: str) -> None:
                events.append(("geometry", value))

            def update_idletasks(self) -> None:
                events.append(("flush",))

        class Canvas:
            def place(self, **kwargs: int) -> None:
                events.append(("canvas", kwargs["width"], kwargs["height"]))

        overlay = Overlay.__new__(Overlay)
        overlay.root = Root()
        overlay.canvas = Canvas()
        overlay.config = {"overlay": {"position": "bottom-center"}}
        overlay.bottom_margin = 24
        overlay._last_geometry = "160x29+920+1027"
        overlay._logical_work_area = lambda: (0, 0, 2000, 1080)
        # This test is about ordering -- minimum lowered before the resize,
        # painted before the flush -- against a synthetic screen. The macOS
        # menu-bar offset would shift the y and turn an ordering assertion into
        # a coordinate assertion, so it is pinned out of the way here and
        # covered by tests/test_mac_pill_placement.py instead.
        overlay._tk_y_offset = lambda: 0
        overlay._bottom_clearance = lambda: overlay.bottom_margin
        overlay._last_requested_y = None
        overlay._apply_pill_region = lambda width, height, redraw=True: events.append(
            ("region", width, height, redraw)
        )
        overlay._draw_visual = lambda: events.append(("draw",))

        overlay._apply_geometry(75, 22)

        self.assertLess(events.index(("minsize", 75, 22)), events.index(("geometry", "75x22+962+1034")))
        self.assertLess(events.index(("draw",)), len(events) - 1)
        self.assertEqual(events[-1], ("flush",))

    def test_worker_ui_updates_are_queued_without_calling_tk(self) -> None:
        overlay = Overlay.__new__(Overlay)
        overlay._ui_thread_id = threading.get_ident()
        overlay._ui_commands = queue.SimpleQueue()
        calls: list[str] = []

        self.assertTrue(
            hasattr(overlay, "_post_ui") and hasattr(overlay, "_drain_ui_commands"),
            "Worker callbacks need a nonblocking UI command queue.",
        )
        worker = threading.Thread(target=lambda: overlay._post_ui(lambda: calls.append("ui")))
        worker.start()
        worker.join(timeout=1.0)

        self.assertFalse(worker.is_alive())
        self.assertEqual(calls, [])
        overlay._drain_ui_commands()
        self.assertEqual(calls, ["ui"])

    def test_only_open_mic_states_expand(self) -> None:
        # X-137: starting/connected are the gray compact standby; the grow
        # waits for the mic. See STANDBY_STATES.
        for state in ("listening", "command"):
            with self.subTest(state=state):
                self.assertTrue(pill_is_expanded(state))
        for state in ("starting", "connected", "idle", "processing", "captured", "error"):
            with self.subTest(state=state):
                self.assertFalse(pill_is_expanded(state))

    def test_rainbow_stays_on_for_processing_and_turns_off_after_paste(self) -> None:
        self.assertTrue(completion_rainbow_enabled("processing"))
        self.assertFalse(completion_rainbow_enabled("captured"))
        self.assertFalse(completion_rainbow_enabled("idle"))

        level = processing_rainbow_step(0.0, active=True, elapsed_ms=60, fade_in_ms=120, fade_out_ms=240)
        self.assertAlmostEqual(level, 0.5, places=2)
        self.assertEqual(
            processing_rainbow_step(level, active=True, elapsed_ms=10_000, fade_in_ms=120, fade_out_ms=240),
            1.0,
        )
        self.assertAlmostEqual(
            processing_rainbow_step(1.0, active=False, elapsed_ms=120, fade_in_ms=120, fade_out_ms=240),
            0.5,
            places=2,
        )

    def test_processing_state_starts_immediately_even_while_pill_is_collapsing(self) -> None:
        overlay = Overlay.__new__(Overlay)
        overlay.state = "listening"
        overlay.compact = False
        overlay._open_anim_active = True
        overlay.completion_effect_level = 0.0
        overlay.completion_effect_started_at = None
        overlay.completion_effect_last_tick = None
        overlay.completion_effect_pending = False
        overlay.last_status = ""
        overlay.last_preview = ""
        overlay._set_compact = lambda *_args, **_kwargs: None
        overlay._schedule_idle_return = lambda *_args, **_kwargs: None
        overlay._repaint = lambda: None
        overlay._sync_fullscreen_visibility = lambda: None

        overlay._set_state_now("processing", "Formatting", None)

        self.assertIsNotNone(overlay.completion_effect_started_at)
        self.assertFalse(overlay.completion_effect_pending)

    def test_leaving_processing_preserves_rainbow_level_for_fade_out(self) -> None:
        overlay = Overlay.__new__(Overlay)
        overlay.state = "processing"
        overlay.compact = True
        overlay._open_anim_active = False
        overlay.completion_effect_level = 0.75
        overlay.completion_effect_started_at = 10.0
        overlay.completion_effect_last_tick = 10.0
        overlay.completion_effect_pending = False
        overlay.last_status = ""
        overlay.last_preview = ""
        overlay._set_compact = lambda *_args, **_kwargs: None
        overlay._schedule_idle_return = lambda *_args, **_kwargs: None
        overlay._repaint = lambda: None
        overlay._sync_fullscreen_visibility = lambda: None

        overlay._set_state_now("captured", "Pasted", None)

        self.assertEqual(overlay.completion_effect_level, 0.75)
        self.assertEqual(overlay.completion_effect_started_at, 10.0)

    def test_completion_rainbow_crossfades_in_and_back_out(self) -> None:
        fade_in, hold, fade_out = 120, 220, 260
        self.assertEqual(completion_rainbow_alpha(0, fade_in, hold, fade_out), 0.0)
        self.assertAlmostEqual(completion_rainbow_alpha(60, fade_in, hold, fade_out), 0.5, places=2)
        self.assertEqual(completion_rainbow_alpha(120, fade_in, hold, fade_out), 1.0)
        self.assertEqual(completion_rainbow_alpha(300, fade_in, hold, fade_out), 1.0)
        self.assertAlmostEqual(completion_rainbow_alpha(470, fade_in, hold, fade_out), 0.5, places=2)
        self.assertEqual(completion_rainbow_alpha(600, fade_in, hold, fade_out), 0.0)

    def test_completion_halo_fades_to_true_transparency_at_canvas_edges(self) -> None:
        layer = Image.new("RGBA", (24, 12), (255, 80, 120, 255))
        faded = fade_layer_edges(layer, 4)
        alpha = faded.getchannel("A")
        self.assertEqual(alpha.getpixel((0, 0)), 0)
        self.assertEqual(alpha.getpixel((23, 11)), 0)
        self.assertEqual(alpha.getpixel((12, 6)), 255)
        self.assertGreater(alpha.getpixel((2, 6)), 0)
        self.assertLess(alpha.getpixel((2, 6)), 255)

    def test_processing_spectrum_scrolls_one_direction_and_wraps_without_a_jump(self) -> None:
        source = Image.new("RGBA", (4, 2))
        colors = [(255, 0, 0, 255), (0, 255, 0, 255), (0, 0, 255, 255), (255, 255, 0, 255)]
        for x, color in enumerate(colors):
            for y in range(2):
                source.putpixel((x, y), color)

        shifted = scrolling_spectrum_frame(source, 4, 2, 1)
        wrapped = scrolling_spectrum_frame(source, 4, 2, 4)

        self.assertEqual([shifted.getpixel((x, 0)) for x in range(4)], colors[1:] + colors[:1])
        wrapped_pixels = getattr(wrapped, "get_flattened_data", wrapped.getdata)()
        source_pixels = getattr(source, "get_flattened_data", source.getdata)()
        self.assertEqual(list(wrapped_pixels), list(source_pixels))

    def test_active_render_cache_key_tracks_voice_but_skips_loading_and_hover(self) -> None:
        self.assertEqual(
            quantized_active_render_key(160, 29, (12, 4), voice_level=0.51, hover_level=0.0, loading=False),
            (160, 29, 12, 4, 3),
        )
        self.assertIsNone(
            quantized_active_render_key(160, 29, (12, 4), voice_level=0.51, hover_level=0.2, loading=False)
        )
        self.assertIsNone(
            quantized_active_render_key(160, 29, (12, 4), voice_level=0.51, hover_level=0.0, loading=True)
        )

    def test_context_menu_exposes_every_primary_workspace_without_duplicate_cards(self) -> None:
        """The pill menu carries the DAILY set; five tools relocated to
        Settings -> Tools (X-71, his review). X-118, his IA: Home leads,
        occasional features fold under one expandable row, app control
        closes the menu. Coverage asserts over the EXPANDED view."""
        overlay = Overlay.__new__(Overlay)
        overlay._menu_show_more = False
        collapsed = [row[0] for row in overlay._context_menu_rows()]
        # X-339: "expanded" means the Features SIDE PANEL is out; the flat
        # list no longer grows. Coverage asserts over the union, as ever.
        overlay._menu_show_more = True
        expanded = collapsed + [row[0] for row in overlay._context_menu_feature_rows()]
        # X-118, his IA: Home leads, the occasional features fold under one
        # expandable row, app control closes the menu. Coverage asserts over
        # the EXPANDED view: nothing lost, nothing duplicated.
        # X-143: the finish control is the pinned switch, not a row.
        # X-185: `scribe` joins the folded set. It was fully implemented and
        # reachable from NOWHERE -- the dispatcher already routed "scribe" and
        # app.py already registered scribe_toggle; the only missing piece was a
        # row, so a working feature was invisible to every user. A capability
        # sweep classified it UNREACHABLE for exactly that reason.
        #
        # This list is deliberately exhaustive rather than a subset check, so
        # adding a row is a decision somebody has to write down here. That is
        # working as intended: this assertion is what caught the addition.
        self.assertEqual(sorted(expanded), sorted([
            "settings", "paste_last", "history", "more_features",
            "ramble", "captions", "translation", "scratchpad", "scribe", "local_models",
            "check_updates", "stats", "restart_app", "quit_app",
        ]))
        self.assertEqual(len(expanded), len(set(expanded)), "no card may appear twice")
        self.assertEqual(collapsed[0], "settings", "Home leads the menu")
        self.assertEqual(collapsed[-2:], ["restart_app", "quit_app"], "app control closes the menu")
        self.assertNotIn("ramble", collapsed, "occasional features stay folded until asked for")
        relocated = [tool_id for tool_id, _title in Overlay.RELOCATED_TOOLS]
        self.assertFalse(set(relocated) & set(expanded), "a tool lives in ONE place")
    def test_context_paste_copies_instead_of_typing_when_focus_cannot_be_restored(self) -> None:
        overlay = Overlay.__new__(Overlay)
        calls: list[str] = []
        overlay.callbacks = {
            "paste_last": lambda: calls.append("paste"),
            "copy_last": lambda: calls.append("copy"),
        }
        overlay._foreground_window_is = lambda _hwnd: False
        overlay._restore_foreground_window = lambda _hwnd: False

        overlay._paste_last_from_context(123)

        self.assertEqual(calls, ["copy"])

    def test_context_paste_targets_restored_field_before_insertion(self) -> None:
        overlay = Overlay.__new__(Overlay)
        calls: list[str] = []
        overlay.callbacks = {
            "paste_last": lambda: calls.append("paste"),
            "copy_last": lambda: calls.append("copy"),
        }
        overlay._foreground_window_is = lambda _hwnd: True
        overlay._restore_foreground_window = lambda _hwnd: True

        overlay._paste_last_from_context(123)

        self.assertEqual(calls, ["paste"])

    def test_transition_orders_every_frame_once(self) -> None:
        self.assertEqual(transition_frame_order(4, compact=False), [0, 1, 2, 3])
        self.assertEqual(transition_frame_order(4, compact=True), [3, 2, 1, 0])
        self.assertEqual(transition_frame_order(0, compact=False), [])

    def test_reversed_transition_continues_from_visible_frame(self) -> None:
        self.assertEqual(transition_frame_order(5, compact=True, start_index=2), [2, 1, 0])
        self.assertEqual(transition_frame_order(5, compact=False, start_index=2), [2, 3, 4])

    def test_late_transition_callback_advances_without_overshoot(self) -> None:
        self.assertEqual(transition_frame_index(0.0, 8, 23), 0)
        self.assertEqual(transition_frame_index(7.9, 8, 23), 0)
        self.assertEqual(transition_frame_index(19.0, 8, 23), 2)
        self.assertEqual(transition_frame_index(999.0, 8, 23), 22)

    def test_loading_halo_uses_a_bounded_seamless_cache_cycle(self) -> None:
        self.assertEqual(loading_halo_phase_bucket(0), 0)
        self.assertEqual(loading_halo_phase_bucket(2), 1)
        self.assertEqual(loading_halo_phase_bucket(144), 0)

    def test_zero_completion_hold_returns_to_idle_instead_of_sticking_open(self) -> None:
        self.assertEqual(state_hold_delay_ms("captured", result_hold_ms=0, error_hold_ms=5000), 0)
        self.assertEqual(state_hold_delay_ms("error", result_hold_ms=900, error_hold_ms=5000), 5000)
        self.assertIsNone(state_hold_delay_ms("listening", result_hold_ms=900, error_hold_ms=5000))


if __name__ == "__main__":
    unittest.main()
