"""Pill animation and theme data, testable without tkinter, PIL, or a display.

These live in knight_flow.pill_motion and knight_flow.themes precisely so they can be
exercised on any machine. tests/test_overlay_motion.py still covers the same functions
through the Overlay class, but only where the GUI stack is installed.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

from knight_flow.pill_motion import (
    EXPANDED_STATES,
    LIVE_STATES,
    LOCAL_FORMATTER_PROFILE_BY_LABEL,
    LOCAL_FORMATTER_PROFILE_BY_MODEL,
    LOCAL_FORMATTER_PROFILES,
    TRANSPARENT_COLOR,
    completion_rainbow_alpha,
    completion_rainbow_enabled,
    faceted_voice_trace,
    loading_halo_phase_bucket,
    microphone_energy_envelope,
    next_context_menu_action,
    perceptual_voice_level,
    pill_is_expanded,
    processing_rainbow_step,
    processing_transition_alpha,
    quantized_active_render_key,
    state_hold_delay_ms,
    transition_frame_index,
    transition_frame_order,
)
from knight_flow.themes import (
    SETTINGS_THEME_FAMILIES,
    SETTINGS_THEME_PALETTE_KEYS,
    SETTINGS_THEME_PALETTES,
)


class PillStateTests(unittest.TestCase):
    def test_only_open_mic_states_expand_the_pill(self) -> None:
        # X-137, his spec: the click's receipt is the compact pill going
        # gray; the grow belongs to the mic actually being open. starting
        # and connected are live (render loop runs) but NOT expanded.
        for state in ("listening", "command"):
            self.assertTrue(pill_is_expanded(state), state)
        for state in ("starting", "connected", "idle", "processing", "captured", "error", ""):
            self.assertFalse(pill_is_expanded(state), state)

    def test_state_matching_tolerates_case_and_padding(self) -> None:
        self.assertTrue(pill_is_expanded("  LISTENING  "))
        self.assertTrue(completion_rainbow_enabled("  Processing "))

    def test_the_rainbow_belongs_to_processing_only(self) -> None:
        self.assertTrue(completion_rainbow_enabled("processing"))
        for state in ("listening", "idle", "captured", ""):
            self.assertFalse(completion_rainbow_enabled(state), state)

    def test_hold_delays_are_state_specific(self) -> None:
        self.assertEqual(state_hold_delay_ms("captured", result_hold_ms=900, error_hold_ms=1500), 900)
        self.assertEqual(state_hold_delay_ms("error", result_hold_ms=900, error_hold_ms=1500), 1500)
        self.assertIsNone(state_hold_delay_ms("listening", result_hold_ms=900, error_hold_ms=1500))

    def test_negative_hold_values_never_become_negative_delays(self) -> None:
        self.assertEqual(state_hold_delay_ms("captured", result_hold_ms=-50, error_hold_ms=0), 0)


class CompletionRainbowTests(unittest.TestCase):
    def test_the_pulse_rises_holds_then_falls_to_nothing(self) -> None:
        self.assertEqual(completion_rainbow_alpha(0), 0.0)
        rising = completion_rainbow_alpha(60)
        self.assertGreater(rising, 0.0)
        self.assertLess(rising, 1.0)
        self.assertEqual(completion_rainbow_alpha(200), 1.0)
        falling = completion_rainbow_alpha(470)
        self.assertGreater(falling, 0.0)
        self.assertLess(falling, 1.0)
        self.assertEqual(completion_rainbow_alpha(10_000), 0.0)

    def test_alpha_never_leaves_zero_to_one(self) -> None:
        for elapsed in (-500, 0, 1, 119, 120, 340, 341, 600, 1e6):
            value = completion_rainbow_alpha(elapsed)
            self.assertGreaterEqual(value, 0.0)
            self.assertLessEqual(value, 1.0)

    def test_zero_length_phases_cannot_divide_by_zero(self) -> None:
        self.assertEqual(completion_rainbow_alpha(50, fade_in_ms=0, hold_ms=0, fade_out_ms=0), 0.0)


class ProcessingRainbowTests(unittest.TestCase):
    def test_active_rises_and_inactive_falls(self) -> None:
        self.assertGreater(processing_rainbow_step(0.2, active=True, elapsed_ms=60), 0.2)
        self.assertLess(processing_rainbow_step(0.8, active=False, elapsed_ms=60), 0.8)

    def test_the_level_saturates_rather_than_overshooting(self) -> None:
        self.assertEqual(processing_rainbow_step(0.9, active=True, elapsed_ms=10_000), 1.0)
        self.assertEqual(processing_rainbow_step(0.1, active=False, elapsed_ms=10_000), 0.0)

    def test_out_of_range_input_is_clamped_before_use(self) -> None:
        self.assertEqual(processing_rainbow_step(5.0, active=True, elapsed_ms=0), 1.0)
        self.assertEqual(processing_rainbow_step(-5.0, active=False, elapsed_ms=0), 0.0)

    def test_the_close_transition_hands_off_smoothly(self) -> None:
        # Stored compact-to-active: the active endpoint is live artwork, compact is rainbow.
        self.assertEqual(processing_transition_alpha(0, 10), 1.0)
        self.assertEqual(processing_transition_alpha(9, 10), 0.0)
        values = [processing_transition_alpha(i, 10) for i in range(10)]
        self.assertEqual(values, sorted(values, reverse=True), "handoff must not reverse")

    def test_a_single_frame_transition_does_not_divide_by_zero(self) -> None:
        self.assertEqual(processing_transition_alpha(0, 1), 1.0)


class VoiceLevelTests(unittest.TestCase):
    def test_silence_and_noise_floor_read_as_nothing(self) -> None:
        self.assertEqual(perceptual_voice_level(0.0), 0.0)
        self.assertEqual(perceptual_voice_level(0.0008), 0.0)
        self.assertEqual(perceptual_voice_level(-1.0), 0.0)

    def test_louder_speech_always_reads_higher(self) -> None:
        samples = [0.002, 0.01, 0.05, 0.2, 0.6, 1.0]
        values = [perceptual_voice_level(level) for level in samples]
        self.assertEqual(values, sorted(values))
        self.assertLessEqual(max(values), 1.0)

    def test_levels_above_full_scale_are_clamped(self) -> None:
        self.assertEqual(perceptual_voice_level(9.0), perceptual_voice_level(1.0))


class EnvelopeTests(unittest.TestCase):
    def test_the_envelope_is_always_the_requested_width(self) -> None:
        for width in (1, 2, 7, 64, 192):
            for count in (0, 1, 5, 40):
                envelope = microphone_energy_envelope([0.3] * count, width)
                self.assertEqual(len(envelope), width, f"width={width} count={count}")

    def test_no_microphone_history_is_flat_silence(self) -> None:
        self.assertEqual(microphone_energy_envelope([], 32), (0.0,) * 32)
        self.assertEqual(microphone_energy_envelope([0.0] * 20, 32), (0.0,) * 32)

    def test_the_ends_taper_so_the_pill_silhouette_stays_calm(self) -> None:
        envelope = microphone_energy_envelope([0.9] * 40, 192)
        self.assertLess(envelope[0], max(envelope))
        self.assertLess(envelope[-1], max(envelope))

    def test_a_zero_or_negative_width_still_returns_a_usable_envelope(self) -> None:
        self.assertEqual(len(microphone_energy_envelope([0.5] * 4, 0)), 1)
        self.assertEqual(len(microphone_energy_envelope([0.5] * 4, -8)), 1)


class VoiceTraceTests(unittest.TestCase):
    def test_silence_produces_no_displacement(self) -> None:
        self.assertEqual(faceted_voice_trace([0.0] * 64), (0.0,) * 64)
        self.assertEqual(faceted_voice_trace([0.01] * 64), (0.0,) * 64)

    def test_the_trace_matches_the_envelope_width(self) -> None:
        for width in (2, 16, 192):
            self.assertEqual(len(faceted_voice_trace([0.6] * width)), width)

    def test_both_ends_are_damped_to_zero(self) -> None:
        trace = faceted_voice_trace(microphone_energy_envelope([0.8] * 40, 192))
        self.assertEqual(trace[0], 0.0)
        self.assertEqual(trace[-1], 0.0)

    def test_a_degenerate_envelope_cannot_raise(self) -> None:
        self.assertEqual(faceted_voice_trace([]), ())
        self.assertEqual(faceted_voice_trace([0.9]), (0.0,))


class TransitionFrameTests(unittest.TestCase):
    def test_expanding_runs_forward_and_collapsing_runs_back(self) -> None:
        self.assertEqual(transition_frame_order(4, compact=False), [0, 1, 2, 3])
        self.assertEqual(transition_frame_order(4, compact=True), [3, 2, 1, 0])

    def test_a_mid_animation_reversal_starts_where_it_left_off(self) -> None:
        self.assertEqual(transition_frame_order(6, compact=True, start_index=2), [2, 1, 0])
        self.assertEqual(transition_frame_order(6, compact=False, start_index=4), [4, 5])

    def test_an_out_of_range_start_is_clamped(self) -> None:
        self.assertEqual(transition_frame_order(3, compact=False, start_index=99), [2])
        self.assertEqual(transition_frame_order(3, compact=True, start_index=-5), [0])

    def test_no_frames_means_no_animation(self) -> None:
        self.assertEqual(transition_frame_order(0, compact=True), [])
        self.assertEqual(transition_frame_order(-3, compact=False), [])

    def test_elapsed_time_maps_to_a_frame_and_stops_at_the_last(self) -> None:
        self.assertEqual(transition_frame_index(0, 16, 10), 0)
        self.assertEqual(transition_frame_index(33, 16, 10), 2)
        self.assertEqual(transition_frame_index(10_000, 16, 10), 9)

    def test_frame_index_survives_degenerate_timing(self) -> None:
        self.assertEqual(transition_frame_index(500, 0, 10), 9)
        self.assertEqual(transition_frame_index(-500, 16, 10), 0)
        self.assertEqual(transition_frame_index(500, 16, 1), 0)

    def test_the_loading_halo_cycles_through_seventy_two_buckets(self) -> None:
        self.assertEqual(loading_halo_phase_bucket(0), 0)
        self.assertEqual(loading_halo_phase_bucket(2), 1)
        self.assertEqual(loading_halo_phase_bucket(144), 0)
        self.assertEqual(loading_halo_phase_bucket(-10), 0)


class RenderCacheKeyTests(unittest.TestCase):
    def test_a_stable_pill_produces_a_reusable_key(self) -> None:
        key = quantized_active_render_key(
            192, 44, (3, 4), voice_level=0.42, hover_level=0.0, loading=False
        )
        self.assertEqual(key, (192, 44, 3, 4, 2))

    def test_nothing_is_cached_while_loading_hovering_or_without_flow(self) -> None:
        for flow, hover, loading in (((3, 4), 0.0, True), ((3, 4), 0.5, False), (None, 0.0, False)):
            self.assertIsNone(
                quantized_active_render_key(
                    192, 44, flow, voice_level=0.4, hover_level=hover, loading=loading
                )
            )

    def test_similar_voice_levels_share_a_cache_bucket(self) -> None:
        def key(level: float):
            return quantized_active_render_key(
                192, 44, (1, 1), voice_level=level, hover_level=0.0, loading=False
            )

        self.assertEqual(key(0.40), key(0.42))
        self.assertNotEqual(key(0.40), key(0.80))


class ContextMenuNavigationTests(unittest.TestCase):
    ACTIONS = ["settings", "history", "scratchpad"]

    def test_arrows_move_and_wrap_around(self) -> None:
        self.assertEqual(next_context_menu_action(self.ACTIONS, "settings", "down"), "history")
        self.assertEqual(next_context_menu_action(self.ACTIONS, "scratchpad", "down"), "settings")
        self.assertEqual(next_context_menu_action(self.ACTIONS, "settings", "up"), "scratchpad")

    def test_home_and_end_jump_to_the_edges(self) -> None:
        self.assertEqual(next_context_menu_action(self.ACTIONS, "history", "home"), "settings")
        self.assertEqual(next_context_menu_action(self.ACTIONS, "history", "end"), "scratchpad")

    def test_an_unknown_selection_lands_somewhere_valid(self) -> None:
        self.assertEqual(next_context_menu_action(self.ACTIONS, "gone", "down"), "settings")
        self.assertEqual(next_context_menu_action(self.ACTIONS, "gone", "up"), "scratchpad")
        self.assertEqual(next_context_menu_action(self.ACTIONS, "gone", "left"), "settings")

    def test_an_empty_menu_never_raises(self) -> None:
        self.assertEqual(next_context_menu_action([], "settings", "down"), "")


class FormatterProfileTests(unittest.TestCase):
    def test_the_lookup_tables_agree_with_the_profile_list(self) -> None:
        self.assertEqual(len(LOCAL_FORMATTER_PROFILE_BY_LABEL), len(LOCAL_FORMATTER_PROFILES))
        self.assertEqual(len(LOCAL_FORMATTER_PROFILE_BY_MODEL), len(LOCAL_FORMATTER_PROFILES))
        for label, model, budget in LOCAL_FORMATTER_PROFILES:
            self.assertEqual(LOCAL_FORMATTER_PROFILE_BY_LABEL[label], (model, budget))
            self.assertEqual(LOCAL_FORMATTER_PROFILE_BY_MODEL[model], (label, budget))

    def test_the_tested_default_stays_first_and_fastest(self) -> None:
        label, model, budget = LOCAL_FORMATTER_PROFILES[0]
        self.assertEqual(model, "qwen3:1.7b")
        self.assertIn("recommended", label.lower())
        self.assertEqual(budget, min(b for _, _, b in LOCAL_FORMATTER_PROFILES))


class ThemeDataTests(unittest.TestCase):
    def test_every_family_has_a_light_and_dark_palette(self) -> None:
        # Derived, not written down. This said 25 and went stale the first
        # time a family was added (X-538). What matters is that every
        # family has a palette, not how many there happen to be.
        self.assertEqual(len(SETTINGS_THEME_FAMILIES), len(SETTINGS_THEME_PALETTES))
        for family in SETTINGS_THEME_FAMILIES:
            self.assertIn(family, SETTINGS_THEME_PALETTES, family)
            self.assertEqual(sorted(SETTINGS_THEME_PALETTES[family]), ["Dark", "Light"], family)

    def test_family_names_are_unique_and_the_default_leads(self) -> None:
        """Order is meaningful: the picker reads top to bottom.

        Flow is the product's own look, so it stays first no matter how many
        families are added after it. A duplicate name would silently shadow a
        palette in the dict and make one theme unreachable.
        """
        self.assertEqual(SETTINGS_THEME_FAMILIES[0], "Flow")
        self.assertEqual(
            len(set(SETTINGS_THEME_FAMILIES)),
            len(SETTINGS_THEME_FAMILIES),
            "duplicate theme family name",
        )

    def test_every_palette_defines_every_key_as_a_hex_colour(self) -> None:
        for family, modes in SETTINGS_THEME_PALETTES.items():
            for mode, palette in modes.items():
                self.assertEqual(sorted(palette), sorted(SETTINGS_THEME_PALETTE_KEYS), f"{family}/{mode}")
                for key, colour in palette.items():
                    self.assertRegex(colour, r"^#[0-9a-fA-F]{6}$", f"{family}/{mode}/{key}")

    def test_no_palette_is_defined_for_an_unlisted_family(self) -> None:
        self.assertEqual(set(SETTINGS_THEME_PALETTES), set(SETTINGS_THEME_FAMILIES))

    def test_the_pill_transparency_key_is_a_hex_colour(self) -> None:
        self.assertRegex(TRANSPARENT_COLOR, r"^#[0-9a-fA-F]{6}$")


class ImportCompatibilityTests(unittest.TestCase):
    """overlay.py must keep re-exporting these names.

    Existing code and tests import them from knight_flow.overlay, so the split has to
    stay invisible at the import site. overlay cannot be imported here (it needs
    tkinter), so this is checked against the source.
    """

    def test_overlay_still_re_exports_every_extracted_name(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "knight_flow" / "overlay.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(source)
        reexported: set[str] = set()
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.module in {"pill_motion", "themes"}:
                reexported.update(alias.name for alias in node.names)

        expected = {
            "EXPANDED_STATES", "LIVE_STATES", "LOCAL_FORMATTER_PROFILES",
            "LOCAL_FORMATTER_PROFILE_BY_LABEL", "LOCAL_FORMATTER_PROFILE_BY_MODEL",
            "TRANSPARENT_COLOR", "completion_rainbow_alpha", "completion_rainbow_enabled",
            "faceted_voice_trace", "loading_halo_phase_bucket", "microphone_energy_envelope",
            "next_context_menu_action", "perceptual_voice_level", "pill_is_expanded",
            "processing_rainbow_step", "processing_transition_alpha",
            "quantized_active_render_key", "state_hold_delay_ms", "transition_frame_index",
            "transition_frame_order", "SETTINGS_THEME_FAMILIES", "SETTINGS_THEME_PALETTE_KEYS",
            "SETTINGS_THEME_PALETTES",
        }
        self.assertEqual(expected - reexported, set(), "overlay stopped re-exporting these")

    def test_the_extracted_modules_pull_in_no_gui_stack(self) -> None:
        root = Path(__file__).resolve().parents[1] / "knight_flow"
        for name in ("pill_motion.py", "themes.py"):
            tree = ast.parse((root / name).read_text(encoding="utf-8"))
            imported: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    imported.add(node.module.split(".")[0])
            self.assertEqual(
                imported & {"tkinter", "PIL", "pynput", "sounddevice", "pystray"},
                set(),
                f"{name} must stay importable without a GUI stack",
            )


if __name__ == "__main__":
    unittest.main()
