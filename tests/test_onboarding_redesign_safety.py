"""Behavioral safety contracts for the native onboarding redesign.

These tests deliberately exercise the pure lifecycle methods without creating a
Tk root.  First-run setup is allowed to change its presentation, but it may not
leak a live capture into another application, forget earned progress, or hide a
microphone owner from Panic Stop and diagnostics.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from knight_flow.mic_registry import ONBOARDING, MicrophoneRegistry
from knight_flow.onboarding import ONBOARDING_STEPS, mark_onboarding_complete
from knight_flow.ui.onboarding import WINDOWS_DEFAULT_MIC, OnboardingWizard


class _Variable:
    def __init__(self, value: str = "") -> None:
        self.value = value

    def get(self) -> str:
        return self.value

    def set(self, value: str) -> None:
        self.value = value


class _SinkHost:
    """A host whose sink setter makes teardown ordering observable."""

    def __init__(self, sink: object, events: list[tuple[str, object]]) -> None:
        self.events = events
        self._sink = sink

    @property
    def onboarding_test_sink(self) -> object:
        return self._sink

    @onboarding_test_sink.setter
    def onboarding_test_sink(self, sink: object) -> None:
        self.events.append(("sink", sink))
        self._sink = sink


class _ImmediateWindow:
    def __init__(self, events: list[tuple[str, object]] | None = None) -> None:
        self.events = events if events is not None else []
        self._next_after = 0

    def after(self, delay: int, callback: object) -> str:
        self.events.append(("after", delay))
        if delay == 0:
            callback()  # type: ignore[operator]
        self._next_after += 1
        return f"after-{self._next_after}"

    def after_cancel(self, receipt: str) -> None:
        self.events.append(("after_cancel", receipt))


class _Stream:
    def __init__(self, events: list[tuple[str, object]]) -> None:
        self.events = events

    def start(self) -> None:
        self.events.append(("stream", "start"))

    def stop(self) -> None:
        self.events.append(("stream", "stop"))

    def close(self) -> None:
        self.events.append(("stream", "close"))


class _ImmediateThread:
    def __init__(self, *, target, **_kwargs: object) -> None:
        self.target = target

    def start(self) -> None:
        self.target()


class _DeferredThread(_ImmediateThread):
    pending: list[object] = []

    def start(self) -> None:
        self.pending.append(self.target)

    @classmethod
    def run_all(cls) -> None:
        while cls.pending:
            callback = cls.pending.pop(0)
            callback()  # type: ignore[operator]


class _StartFailThread(_ImmediateThread):
    def start(self) -> None:
        raise RuntimeError("thread start failed")


class _FailingStartStream(_Stream):
    def start(self) -> None:
        self.events.append(("stream", "start"))
        raise RuntimeError("start failed")


class _FailingStopStream(_Stream):
    def stop(self) -> None:
        self.events.append(("stream", "stop"))
        raise RuntimeError("stop failed")


class _Registry:
    def __init__(self, events: list[tuple[str, object]]) -> None:
        self.events = events
        self.stopper = None

    def acquire(self, name: str, **details: object) -> int:
        self.events.append(("acquire", (name, details.get("device"), details.get("phase"))))
        self.stopper = details.get("stop")
        return 73

    def release(self, token: int | None) -> bool:
        self.events.append(("release", token))
        return token is not None

    def set_phase(self, token: int, phase: str) -> None:
        self.events.append(("phase", (token, phase)))


class _FocusTarget:
    def __init__(self) -> None:
        self.focused = False

    def focus_set(self) -> None:
        self.focused = True


class _ConfigurableControl:
    def __init__(self) -> None:
        self.options: dict[str, object] = {}

    def winfo_exists(self) -> bool:
        return True

    def configure(self, **options: object) -> None:
        self.options.update(options)


class _FailingRegistry(_Registry):
    def acquire(self, name: str, **details: object) -> int:
        self.events.append(("acquire", (name, details.get("device"), details.get("phase"))))
        raise RuntimeError("registry failed")


class _FailingAfterWindow(_ImmediateWindow):
    def after(self, delay: int, callback: object) -> str:
        if delay == 32:
            self.events.append(("after_failed", delay))
            raise RuntimeError("timer failed")
        return super().after(delay, callback)


def _bare_wizard(config: dict | None = None) -> OnboardingWizard:
    wizard = OnboardingWizard.__new__(OnboardingWizard)
    wizard.config = config if config is not None else {}
    wizard.microphone_tested = False
    wizard.hotkey_rehearsed = False
    wizard.dictation_tested = False
    wizard.route_var = _Variable("managed")
    wizard.access_choice = "private"
    return wizard


class TestSinkOwnershipTests(unittest.TestCase):
    def test_owned_capture_is_cancelled_before_its_sink_is_cleared(self) -> None:
        events: list[tuple[str, object]] = []
        wizard = _bare_wizard()
        # Accessing a bound method again creates a different object.  Store the
        # one object that was installed so identity ownership is meaningful.
        wizard.test_sink = wizard._receive_test_result
        self.assertIsNot(wizard.test_sink, wizard._receive_test_result)
        wizard.host = _SinkHost(wizard.test_sink, events)
        wizard.test_started_by_button = True
        wizard._status_snapshot = lambda: {"session_active": True}
        wizard._invoke_callback = lambda name: events.append(("callback", name))

        wizard._dispose_test_capture()

        self.assertEqual(events, [("callback", "cancel"), ("sink", None)])
        self.assertIsNone(wizard.host.onboarding_test_sink)
        self.assertFalse(wizard.test_started_by_button)

    def test_foreign_sink_is_preserved_and_its_capture_is_not_cancelled(self) -> None:
        events: list[tuple[str, object]] = []
        wizard = _bare_wizard()
        wizard.test_sink = wizard._receive_test_result
        foreign_sink = object()
        wizard.host = _SinkHost(foreign_sink, events)
        wizard.test_started_by_button = True
        wizard._status_snapshot = lambda: {"session_active": True}
        wizard._invoke_callback = lambda name: events.append(("callback", name))

        wizard._dispose_test_capture()

        self.assertEqual(events, [])
        self.assertIs(wizard.host.onboarding_test_sink, foreign_sink)
        self.assertTrue(wizard.test_started_by_button)

    def test_owned_processing_result_is_cancelled_before_sink_clear(self) -> None:
        events: list[tuple[str, object]] = []
        wizard = _bare_wizard()
        wizard.test_sink = wizard._receive_test_result
        wizard.host = _SinkHost(wizard.test_sink, events)
        wizard.test_started_by_button = False
        wizard._status_snapshot = lambda: {
            "session_active": False,
            "overlay_state": "processing",
        }
        wizard._invoke_callback = lambda name: events.append(("callback", name))

        wizard._dispose_test_capture()

        self.assertEqual(events, [("callback", "cancel"), ("sink", None)])

    def test_owned_idle_sink_clears_without_cancelling_unrelated_work(self) -> None:
        events: list[tuple[str, object]] = []
        wizard = _bare_wizard()
        wizard.test_sink = wizard._receive_test_result
        wizard.host = _SinkHost(wizard.test_sink, events)
        wizard.test_started_by_button = False
        wizard._status_snapshot = lambda: {
            "session_active": False,
            "overlay_state": "idle",
        }
        wizard._invoke_callback = lambda name: events.append(("callback", name))

        wizard._dispose_test_capture()

        self.assertEqual(events, [("sink", None)])

    def test_cancel_failure_cannot_leak_the_destroyed_pages_sink(self) -> None:
        events: list[tuple[str, object]] = []
        wizard = _bare_wizard()
        wizard.test_sink = wizard._receive_test_result
        wizard.host = _SinkHost(wizard.test_sink, events)
        wizard.test_started_by_button = True
        wizard._status_snapshot = lambda: {
            "session_active": False,
            "overlay_state": "processing",
        }

        def fail_cancel(_name: str) -> None:
            raise RuntimeError("host cancel failed")

        wizard._invoke_callback = fail_cancel
        wizard._dispose_test_capture()

        self.assertEqual(events, [("sink", None)])
        self.assertIsNone(wizard.host.onboarding_test_sink)
        self.assertFalse(wizard.test_started_by_button)

    def test_cancel_cleanup_does_not_erase_a_new_sink_owner(self) -> None:
        events: list[tuple[str, object]] = []
        wizard = _bare_wizard()
        wizard.test_sink = wizard._receive_test_result
        wizard.host = _SinkHost(wizard.test_sink, events)
        wizard.test_started_by_button = True
        wizard._status_snapshot = lambda: {
            "session_active": False,
            "overlay_state": "processing",
        }
        replacement = object()

        def replace_owner(_name: str) -> None:
            wizard.host.onboarding_test_sink = replacement

        wizard._invoke_callback = replace_owner
        wizard._dispose_test_capture()

        self.assertEqual(events, [("sink", replacement)])
        self.assertIs(wizard.host.onboarding_test_sink, replacement)
        self.assertFalse(wizard.test_started_by_button)

    def test_control_rehearsal_result_stays_inside_setup(self) -> None:
        wizard = _bare_wizard()
        wizard.destroyed = False
        wizard.step_index = next(
            index for index, step in enumerate(ONBOARDING_STEPS) if step.id == "controls"
        )
        wizard.window = _ImmediateWindow()
        wizard.control_status_var = _Variable()
        escaped: list[str] = []
        wizard._set_practice_text = lambda text: escaped.append(text)
        wizard._store_resume_receipt = lambda: escaped.append("saved-as-final-test")
        wizard._offer_finish_choice = lambda: escaped.append("finish-choice")

        wizard._receive_test_result("Rehearsal words")

        self.assertIn("stayed inside setup", wizard.control_status_var.get())
        self.assertEqual(escaped, [])
        self.assertFalse(wizard.dictation_tested)


class ChoiceCardKeyboardTests(unittest.TestCase):
    def test_route_arrows_wrap_between_the_two_routes(self) -> None:
        wizard = _bare_wizard()
        targets = {name: _FocusTarget() for name in ("managed", "local", "byok")}
        wizard.route_buttons = targets
        selected: list[str] = []
        wizard._select_route = selected.append

        result = wizard._move_route_choice("byok", 1)

        self.assertEqual(result, "break")
        self.assertEqual(selected, ["local"])
        self.assertTrue(targets["local"].focused)

    def test_writing_arrows_select_and_focus_the_next_radio_card(self) -> None:
        wizard = _bare_wizard()
        targets = {name: _FocusTarget() for name in ("smart", "fast", "verbatim")}
        wizard.writing_buttons = targets
        selected: list[str] = []
        wizard._select_writing = selected.append

        result = wizard._move_writing_choice("verbatim", 1)

        self.assertEqual(result, "break")
        self.assertEqual(selected, ["smart"])
        self.assertTrue(targets["smart"].focused)

    def test_route_and_writing_cards_are_native_radio_groups_with_all_arrow_keys(self) -> None:
        source = Path(__file__).resolve().parents[1].joinpath(
            "knight_flow", "ui", "onboarding.py"
        ).read_text(encoding="utf-8")

        self.assertGreaterEqual(source.count("tk.Radiobutton("), 2)
        self.assertIn("variable=self.route_var", source)
        self.assertIn("variable=self.writing_var", source)
        self.assertIn('state=tk.NORMAL if enabled else tk.DISABLED', source)
        self.assertIn('("<Left>", "<Up>")', source)
        self.assertIn('("<Right>", "<Down>")', source)

    def test_menu_lesson_opens_the_real_pill_panel(self) -> None:
        source = Path(__file__).resolve().parents[1].joinpath(
            "knight_flow", "ui", "onboarding.py"
        ).read_text(encoding="utf-8")
        start = source.index("def _render_menu(")
        end = source.index("def _render_writing(", start)
        block = source[start:end]

        # 2026-09-23: renamed to match the web shell and the site, which call
        # it the Pill menu; "Pill Panel" was a second coined name for it.
        self.assertIn('"Open the Pill menu"', block)
        self.assertIn("self.host._open_context_menu_from_event()", block)
        self.assertIn("Use arrow keys to explore", block)


class SemanticResumeReceiptTests(unittest.TestCase):
    def test_semantic_step_id_wins_over_a_stale_numeric_position(self) -> None:
        config = {
            "onboarding": {
                "resume_step_id": "menu",
                "resume_step": 1,
                "resume_flags": {
                    "microphone_tested": True,
                    "hotkey_rehearsed": True,
                    "dictation_tested": False,
                    "route": "local",
                    "access_choice": "account",
                },
            }
        }
        wizard = _bare_wizard(config)

        restored = wizard._resume_step_index()

        expected = next(index for index, step in enumerate(ONBOARDING_STEPS) if step.id == "menu")
        self.assertEqual(restored, expected)
        self.assertTrue(wizard.microphone_tested)
        self.assertTrue(wizard.hotkey_rehearsed)
        self.assertFalse(wizard.dictation_tested)
        self.assertEqual(wizard.route_var.get(), "local")
        self.assertEqual(wizard.access_choice, "account")

    def test_unknown_semantic_id_falls_back_to_the_legacy_number(self) -> None:
        wizard = _bare_wizard(
            {"onboarding": {"resume_step_id": "retired-step", "resume_step": "4"}}
        )
        self.assertEqual(wizard._resume_step_index(), 4)

    def test_invalid_legacy_number_falls_back_to_the_first_step(self) -> None:
        wizard = _bare_wizard(
            {"onboarding": {"resume_step_id": "retired-step", "resume_step": "not-a-number"}}
        )
        self.assertEqual(wizard._resume_step_index(), 0)

    def test_receipt_keeps_semantic_and_legacy_positions_during_migration(self) -> None:
        wizard = _bare_wizard({})
        wizard.step_index = next(
            index for index, step in enumerate(ONBOARDING_STEPS) if step.id == "writing"
        )
        wizard.microphone_tested = True
        wizard.hotkey_rehearsed = True
        wizard.dictation_tested = False
        saved: list[str] = []
        wizard._invoke_callback = saved.append

        wizard._store_resume_receipt()

        receipt = wizard.config["onboarding"]
        self.assertEqual(receipt["resume_step_id"], "writing")
        self.assertEqual(receipt["resume_step"], wizard.step_index)
        self.assertEqual(receipt["resume_flags"]["route"], "managed")
        self.assertEqual(saved, ["save_settings"])

    def test_completion_clears_every_resume_receipt(self) -> None:
        config = {
            "onboarding": {
                "resume_step": 8,
                "resume_step_id": "writing",
                "resume_flags": {"microphone_tested": True},
            }
        }

        mark_onboarding_complete(
            config,
            route="managed",
            microphone_tested=True,
            hotkey_rehearsed=True,
            dictation_tested=True,
            access_choice="account",
        )

        self.assertTrue(config["onboarding"]["completed"])
        for key in ("resume_step", "resume_step_id", "resume_flags"):
            self.assertNotIn(key, config["onboarding"])


class OnboardingMicrophoneRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        _DeferredThread.pending.clear()

    @staticmethod
    def _meter_wizard(events: list[tuple[str, object]], window: _ImmediateWindow) -> OnboardingWizard:
        wizard = _bare_wizard()
        wizard.destroyed = False
        wizard.step_index = next(
            index for index, step in enumerate(ONBOARDING_STEPS) if step.id == "microphone"
        )
        wizard.meter_state = {
            "stream": None,
            "after": None,
            "level": 0.0,
            "peak": 0.0,
            "wave": [0.0] * 64,
            "error": "",
        }
        wizard.window = window
        wizard.mic_status_var = _Variable()
        wizard.audio_device_var = _Variable("Studio microphone")
        wizard.mic_box = _ConfigurableControl()
        wizard._selected_device = lambda: 4
        wizard._draw_mic_meter = lambda: None
        return wizard

    def test_meter_registers_a_named_owner_and_panic_stopper_releases_it(self) -> None:
        events: list[tuple[str, object]] = []
        stream = _Stream(events)
        registry = _Registry(events)
        wizard = self._meter_wizard(events, _ImmediateWindow(events))

        def open_stream(**options: object) -> tuple[_Stream, int, int, int]:
            events.append(("open", options.get("device")))
            return stream, 16000, 1, 4

        with (
            patch("knight_flow.ui.onboarding.open_raw_input_stream", side_effect=open_stream),
            patch("knight_flow.ui.onboarding.resolve_input_device", return_value=4),
            patch("knight_flow.ui.onboarding.microphone_registry", return_value=registry),
            patch("knight_flow.ui.onboarding.threading.Thread", _ImmediateThread),
            patch("knight_flow.ui.onboarding.main_thread.post", side_effect=lambda callback: callback()),
        ):
            wizard._start_meter()
            self.assertEqual(wizard.meter_state["mic_token"], 73)
            self.assertEqual(
                next(value for event, value in events if event == "acquire"),
                (ONBOARDING, "Studio microphone", "opening"),
            )
            self.assertIn(("phase", (73, "metering")), events)
            self.assertTrue(callable(registry.stopper))

            registry.stopper()  # type: ignore[operator]

        self.assertIsNone(wizard.meter_state["stream"])
        self.assertNotIn("mic_token", wizard.meter_state)
        self.assertLess(events.index(("stream", "stop")), events.index(("release", 73)))
        self.assertLess(events.index(("stream", "close")), events.index(("release", 73)))

    def test_partial_meter_start_failures_close_stream_and_release_owner(self) -> None:
        scenarios = ("start", "registry", "after")
        for scenario in scenarios:
            with self.subTest(scenario=scenario):
                events: list[tuple[str, object]] = []
                stream = _FailingStartStream(events) if scenario == "start" else _Stream(events)
                registry: _Registry = _FailingRegistry(events) if scenario == "registry" else _Registry(events)
                window = _FailingAfterWindow(events) if scenario == "after" else _ImmediateWindow(events)
                wizard = self._meter_wizard(events, window)

                def open_stream(**_options: object) -> tuple[_Stream, int, int, int]:
                    return stream, 16000, 1, 4

                with (
                    patch("knight_flow.ui.onboarding.open_raw_input_stream", side_effect=open_stream),
                    patch("knight_flow.ui.onboarding.resolve_input_device", return_value=4),
                    patch("knight_flow.ui.onboarding.microphone_registry", return_value=registry),
                    patch("knight_flow.ui.onboarding.threading.Thread", _ImmediateThread),
                    patch("knight_flow.ui.onboarding.main_thread.post", side_effect=lambda callback: callback()),
                ):
                    wizard._start_meter()

                self.assertIsNone(wizard.meter_state["stream"])
                self.assertNotIn("mic_token", wizard.meter_state)
                if scenario == "registry":
                    self.assertNotIn(("stream", "stop"), events)
                    self.assertNotIn(("stream", "close"), events)
                else:
                    self.assertIn(("stream", "stop"), events)
                    self.assertIn(("stream", "close"), events)
                    self.assertIn(("release", 73), events)
                self.assertIn("unavailable", wizard.mic_status_var.get().lower())

    def test_close_and_registry_release_still_run_when_stream_stop_raises(self) -> None:
        events: list[tuple[str, object]] = []
        stream = _FailingStopStream(events)
        registry = _Registry(events)
        wizard = self._meter_wizard(events, _ImmediateWindow(events))
        wizard.meter_state["stream"] = stream
        wizard.meter_state["mic_token"] = 73

        with (
            patch("knight_flow.ui.onboarding.microphone_registry", return_value=registry),
            patch("knight_flow.ui.onboarding.threading.Thread", _ImmediateThread),
            patch("knight_flow.ui.onboarding.main_thread.post", side_effect=lambda callback: callback()),
        ):
            wizard._stop_meter()

        self.assertIsNone(wizard.meter_state["stream"])
        self.assertIn(("stream", "stop"), events)
        self.assertIn(("stream", "close"), events)
        self.assertIn(("release", 73), events)
        self.assertLess(events.index(("stream", "close")), events.index(("release", 73)))

    def test_driver_open_is_deferred_off_the_ui_call(self) -> None:
        events: list[tuple[str, object]] = []
        stream = _Stream(events)
        registry = _Registry(events)
        wizard = self._meter_wizard(events, _ImmediateWindow(events))

        with (
            patch(
                "knight_flow.ui.onboarding.open_raw_input_stream",
                side_effect=lambda **_options: (stream, 16000, 1, 4),
            ),
            patch("knight_flow.ui.onboarding.resolve_input_device", return_value=4),
            patch("knight_flow.ui.onboarding.microphone_registry", return_value=registry),
            patch("knight_flow.ui.onboarding.threading.Thread", _DeferredThread),
            patch("knight_flow.ui.onboarding.main_thread.post", side_effect=lambda callback: callback()),
        ):
            wizard._start_meter()
            self.assertTrue(wizard.meter_state["opening"])
            self.assertEqual(wizard.mic_box.options.get("state"), "disabled")
            self.assertNotIn(("stream", "start"), events)
            self.assertEqual(len(_DeferredThread.pending), 1)
            _DeferredThread.run_all()

        self.assertFalse(wizard.meter_state["opening"])
        self.assertIs(wizard.meter_state["stream"], stream)
        self.assertEqual(wizard.mic_box.options.get("state"), "readonly")
        self.assertIn(("stream", "start"), events)

    def test_selection_change_during_open_restarts_instead_of_mislabeling_device(self) -> None:
        events: list[tuple[str, object]] = []
        wizard = self._meter_wizard(events, _ImmediateWindow(events))
        wizard.meter_state["opening"] = True
        wizard.audio_device_var.set("USB headset")
        wizard._restart_meter = lambda: events.append(("restart", "USB headset"))

        wizard._invoke_callback = lambda _name: None
        wizard._microphone_changed()

        self.assertEqual(wizard.config["audio"]["input_device"], "USB headset")
        self.assertEqual(events, [("restart", "USB headset")])

    def test_device_enumeration_is_deferred_until_after_page_paint(self) -> None:
        events: list[tuple[str, object]] = []
        wizard = self._meter_wizard(events, _ImmediateWindow(events))
        wizard._microphone_query_generation = 0
        wizard.mic_box = _ConfigurableControl()
        wizard.mic_refresh_button = _ConfigurableControl()

        with (
            patch(
                "knight_flow.ui.onboarding.list_input_devices",
                return_value=["Studio microphone", "USB headset"],
            ) as query,
            patch("knight_flow.ui.onboarding.threading.Thread", _DeferredThread),
            patch("knight_flow.ui.onboarding.main_thread.post", side_effect=lambda callback: callback()),
        ):
            wizard._refresh_microphones(initial=True)
            query.assert_not_called()
            self.assertEqual(wizard.mic_refresh_button.options.get("state"), "disabled")
            _DeferredThread.run_all()

        self.assertEqual(
            wizard.mic_box.options.get("values"),
            [WINDOWS_DEFAULT_MIC, "Studio microphone", "USB headset"],
        )
        self.assertEqual(wizard.mic_refresh_button.options.get("state"), "normal")

    def test_driver_close_is_deferred_but_registry_releases_after_close(self) -> None:
        events: list[tuple[str, object]] = []
        stream = _FailingStopStream(events)
        registry = _Registry(events)
        wizard = self._meter_wizard(events, _ImmediateWindow(events))
        wizard.meter_state["stream"] = stream
        wizard.meter_state["mic_token"] = 73

        with (
            patch("knight_flow.ui.onboarding.microphone_registry", return_value=registry),
            patch("knight_flow.ui.onboarding.threading.Thread", _DeferredThread),
            patch("knight_flow.ui.onboarding.main_thread.post", side_effect=lambda callback: callback()),
        ):
            wizard._stop_meter()
            self.assertTrue(wizard.meter_state["closing"])
            self.assertNotIn(("stream", "stop"), events)
            _DeferredThread.run_all()

        self.assertFalse(wizard.meter_state["closing"])
        self.assertLess(events.index(("stream", "close")), events.index(("release", 73)))

    def test_stop_during_open_keeps_privacy_owner_until_stale_stream_closes(self) -> None:
        events: list[tuple[str, object]] = []
        stream = _Stream(events)
        registry = _Registry(events)
        wizard = self._meter_wizard(events, _ImmediateWindow(events))

        with (
            patch(
                "knight_flow.ui.onboarding.open_raw_input_stream",
                return_value=(stream, 16000, 1, 4),
            ),
            patch("knight_flow.ui.onboarding.resolve_input_device", return_value=4),
            patch("knight_flow.ui.onboarding.microphone_registry", return_value=registry),
            patch("knight_flow.ui.onboarding.threading.Thread", _DeferredThread),
            patch("knight_flow.ui.onboarding.main_thread.post", side_effect=lambda callback: callback()),
        ):
            wizard._start_meter()
            wizard._stop_meter()
            self.assertTrue(wizard.meter_state["closing"])
            self.assertIn(("phase", (73, "closing")), events)
            self.assertNotIn(("release", 73), events)
            _DeferredThread.run_all()

        self.assertFalse(wizard.meter_state["closing"])
        self.assertLess(events.index(("stream", "close")), events.index(("release", 73)))

    def test_second_stop_cannot_finish_before_first_driver_close(self) -> None:
        events: list[tuple[str, object]] = []
        callbacks: list[str] = []
        stream = _Stream(events)
        registry = _Registry(events)
        wizard = self._meter_wizard(events, _ImmediateWindow(events))
        wizard.meter_state["stream"] = stream
        wizard.meter_state["mic_token"] = 73

        with (
            patch("knight_flow.ui.onboarding.microphone_registry", return_value=registry),
            patch("knight_flow.ui.onboarding.threading.Thread", _DeferredThread),
            patch("knight_flow.ui.onboarding.main_thread.post", side_effect=lambda callback: callback()),
        ):
            wizard._stop_meter(on_closed=lambda: callbacks.append("first"))
            wizard._stop_meter(on_closed=lambda: callbacks.append("second"))
            self.assertTrue(wizard.meter_state["closing"])
            self.assertEqual(callbacks, [])
            self.assertEqual(len(_DeferredThread.pending), 1)
            _DeferredThread.run_all()

        self.assertFalse(wizard.meter_state["closing"])
        self.assertEqual(callbacks, ["first", "second"])

    def test_panic_keeps_owner_visible_until_async_driver_close_finishes(self) -> None:
        events: list[tuple[str, object]] = []
        stream = _Stream(events)
        registry = MicrophoneRegistry()
        wizard = self._meter_wizard(events, _ImmediateWindow(events))

        with (
            patch(
                "knight_flow.ui.onboarding.open_raw_input_stream",
                return_value=(stream, 16000, 1, 4),
            ),
            patch("knight_flow.ui.onboarding.resolve_input_device", return_value=4),
            patch("knight_flow.ui.onboarding.microphone_registry", return_value=registry),
            patch("knight_flow.ui.onboarding.threading.Thread", _DeferredThread),
            patch("knight_flow.ui.onboarding.main_thread.post", side_effect=lambda callback: callback()),
        ):
            wizard._start_meter()
            _DeferredThread.run_all()
            self.assertTrue(registry.is_active())

            remaining = registry.stop_all()
            self.assertEqual(remaining, (ONBOARDING,))
            self.assertEqual(registry.owners()[0].phase, "closing")
            self.assertNotIn(("stream", "close"), events)

            _DeferredThread.run_all()

        self.assertIn(("stream", "close"), events)
        self.assertFalse(registry.is_active())

    def test_thread_start_failure_cannot_lose_an_attached_driver_handle(self) -> None:
        events: list[tuple[str, object]] = []
        stream = _Stream(events)
        registry = _Registry(events)
        wizard = self._meter_wizard(events, _ImmediateWindow(events))
        wizard.meter_state["stream"] = stream
        wizard.meter_state["mic_token"] = 73

        with (
            patch("knight_flow.ui.onboarding.microphone_registry", return_value=registry),
            patch("knight_flow.ui.onboarding.threading.Thread", _StartFailThread),
            patch("knight_flow.ui.onboarding.main_thread.post", side_effect=lambda callback: callback()),
        ):
            wizard._stop_meter()

        self.assertIn(("stream", "stop"), events)
        self.assertIn(("stream", "close"), events)
        self.assertIn(("release", 73), events)
        self.assertFalse(wizard.meter_state["closing"])

    def test_mic_doctor_supersedes_a_queued_meter_restart(self) -> None:
        events: list[tuple[str, object]] = []
        wizard = self._meter_wizard(events, _ImmediateWindow(events))
        wizard.meter_state["closing"] = True
        wizard.meter_state["on_closed"] = lambda: events.append(("restart", True))
        wizard.host = type(
            "Host",
            (),
            {"open_mic_doctor": lambda _self: events.append(("doctor", True))},
        )()

        wizard._open_mic_doctor()
        wizard._finish_meter_close()

        self.assertEqual(events, [("doctor", True)])

    def test_panic_supersedes_a_queued_meter_restart(self) -> None:
        events: list[tuple[str, object]] = []
        wizard = self._meter_wizard(events, _ImmediateWindow(events))
        wizard.meter_state["closing"] = True
        wizard.meter_state["on_closed"] = lambda: events.append(("restart", True))

        result = wizard._panic_stop_meter()
        wizard._finish_meter_close()

        self.assertIsNotNone(result)
        self.assertEqual(events, [])


if __name__ == "__main__":
    unittest.main()
