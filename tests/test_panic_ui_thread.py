"""Panic Stop must marshal every UI-owning microphone stopper onto Tk."""

from __future__ import annotations

import queue
import threading
import time
import unittest
from unittest.mock import patch

from knight_flow.app import TalkDatApp


class _RootTripwire:
    def __init__(self, ui_thread_id: int) -> None:
        self.ui_thread_id = ui_thread_id
        self.after_threads: list[int] = []

    def after(self, _delay: int, _callback) -> str:
        called_from = threading.get_ident()
        if called_from != self.ui_thread_id:
            raise AssertionError("Tk scheduling entered from a worker thread")
        self.after_threads.append(called_from)
        return "after-1"


class _OverlayTripwire:
    def __init__(self, ui_thread_id: int) -> None:
        self._ui_thread_id = ui_thread_id
        self.root = _RootTripwire(ui_thread_id)
        self.state = "idle"
        self.state_threads: list[int] = []

    def set_state(self, *_args: object, **_kwargs) -> None:
        called_from = threading.get_ident()
        if called_from != self._ui_thread_id:
            raise AssertionError("overlay state changed from a worker thread")
        self.state_threads.append(called_from)

    def set_level(self, _level: float) -> None:
        if threading.get_ident() != self._ui_thread_id:
            raise AssertionError("overlay level changed from a worker thread")


class _RegistryTripwire:
    def __init__(self, ui_thread_id: int) -> None:
        self.ui_thread_id = ui_thread_id
        self.stop_threads: list[int] = []

    def stop_all(self) -> tuple[str, ...]:
        called_from = threading.get_ident()
        if called_from != self.ui_thread_id:
            raise AssertionError("microphone stopper ran from a worker thread")
        self.stop_threads.append(called_from)
        return ()

    def owners(self) -> tuple[object, ...]:
        return ()

    def is_active(self) -> bool:
        return False

    def names(self) -> tuple[str, ...]:
        return ()


def _bare_app() -> tuple[TalkDatApp, _RegistryTripwire, list[int]]:
    ui_thread_id = threading.get_ident()
    app = TalkDatApp.__new__(TalkDatApp)
    app.overlay = _OverlayTripwire(ui_thread_id)
    app._cross_thread_calls = queue.Queue()
    cancel_threads: list[int] = []

    def cancel() -> None:
        called_from = threading.get_ident()
        if called_from != ui_thread_id:
            raise AssertionError("dictation cancellation ran from a worker thread")
        cancel_threads.append(called_from)

    app.cancel = cancel  # type: ignore[method-assign]
    return app, _RegistryTripwire(ui_thread_id), cancel_threads


class PanicStopUiThreadTests(unittest.TestCase):
    def test_worker_panic_queues_the_entire_operation(self) -> None:
        app, registry, cancel_threads = _bare_app()
        worker_errors: list[BaseException] = []

        def invoke() -> None:
            try:
                app.panic_stop()
            except BaseException as error:  # pragma: no cover - asserted below
                worker_errors.append(error)

        with patch("knight_flow.app.microphone_registry", return_value=registry):
            worker = threading.Thread(
                target=invoke,
                name="TalkDatHotkeyDispatch",
            )
            worker.start()
            worker.join(timeout=2.0)
            self.assertFalse(worker.is_alive())
            self.assertEqual(worker_errors, [])
            self.assertEqual(cancel_threads, [])
            self.assertEqual(registry.stop_threads, [])
            self.assertEqual(app._cross_thread_calls.qsize(), 1)

            app._drain_cross_thread_calls()

        self.assertEqual(cancel_threads, [app.overlay._ui_thread_id])
        self.assertEqual(registry.stop_threads, [app.overlay._ui_thread_id])
        self.assertEqual(app.overlay.root.after_threads, [app.overlay._ui_thread_id])

    def test_ui_thread_panic_remains_immediate(self) -> None:
        app, registry, cancel_threads = _bare_app()

        with patch("knight_flow.app.microphone_registry", return_value=registry):
            app.panic_stop()

        self.assertEqual(cancel_threads, [app.overlay._ui_thread_id])
        self.assertEqual(registry.stop_threads, [app.overlay._ui_thread_id])
        self.assertTrue(app._cross_thread_calls.empty())

    def test_slow_dictation_join_cannot_delay_other_panic_stoppers(self) -> None:
        app, registry, _cancel_threads = _bare_app()
        app.cancel = TalkDatApp.cancel.__get__(app, TalkDatApp)  # type: ignore[method-assign]
        join_started = threading.Event()
        release_join = threading.Event()

        class SlowSession:
            def __init__(self) -> None:
                self.cancelled = False

            def cancel(self) -> None:
                self.cancelled = True

            def join(self, timeout: float) -> None:
                join_started.set()
                release_join.wait(timeout)

            def current_text(self) -> str:
                return "unfinished words"

        session = SlowSession()
        app.lock = threading.RLock()
        app.session = session
        app.session_token = object()
        app._guided_delivery_token = object()
        app._deferred_delivery_owner = object()
        app.safety_capture = None
        app.safety_capture_token = object()
        app.safety_capture_failure_token = object()
        app.session_chime_token = object()
        app.session_mode = "dictation"
        app.session_control = "hold"
        app.session_error_message = ""
        app._released_processing = True
        app._trigger_released_at = 1.0
        app.release_activation_guards = lambda: None  # type: ignore[method-assign]
        app.play_sound = lambda _name: None  # type: ignore[method-assign]

        with patch("knight_flow.app.microphone_registry", return_value=registry):
            started = threading.Event()

            def run_panic() -> None:
                app.panic_stop()
                started.set()

            began = time.perf_counter()
            run_panic()
            elapsed = time.perf_counter() - began

        self.assertTrue(started.is_set(), "Panic waited for the session join")
        self.assertLess(elapsed, 0.15, "Panic spent the driver join budget on Tk")
        self.assertTrue(session.cancelled)
        self.assertTrue(join_started.wait(0.2), "background cleanup did not begin")
        self.assertEqual(registry.stop_threads, [app.overlay._ui_thread_id])
        release_join.set()

    def test_detached_dictation_stays_disclosed_until_driver_join_finishes(self) -> None:
        app, registry, _cancel_threads = _bare_app()
        app.cancel = TalkDatApp.cancel.__get__(app, TalkDatApp)  # type: ignore[method-assign]
        app.config = {}
        join_started = threading.Event()
        release_join = threading.Event()

        class SlowSession:
            def cancel(self) -> None:
                pass

            def join(self, timeout: float) -> None:
                join_started.set()
                release_join.wait(timeout)

            def current_text(self) -> str:
                return "unfinished words"

        session = SlowSession()
        app.lock = threading.RLock()
        app.session = session
        app.session_token = object()
        app._guided_delivery_token = object()
        app._deferred_delivery_owner = object()
        app.safety_capture = None
        app.safety_capture_token = object()
        app.safety_capture_failure_token = object()
        app.session_chime_token = object()
        app.session_mode = "dictation"
        app.session_control = "hold"
        app.session_error_message = ""
        app._released_processing = True
        app._trigger_released_at = 1.0
        app.release_activation_guards = lambda: None  # type: ignore[method-assign]
        app.play_sound = lambda _name: None  # type: ignore[method-assign]

        with patch("knight_flow.app.microphone_registry", return_value=registry):
            app.cancel()
            self.assertTrue(join_started.wait(0.2), "background driver close did not begin")
            snapshot = app.status_snapshot()
            self.assertTrue(snapshot["microphone_in_use"])
            self.assertTrue(snapshot["dictation_close_pending"])
            self.assertEqual(snapshot["microphone_owners"], "dictation (closing)")

            release_join.set()
            deadline = time.monotonic() + 1.0
            while app.status_snapshot()["dictation_close_pending"] and time.monotonic() < deadline:
                time.sleep(0.01)
            closed = app.status_snapshot()

        self.assertFalse(closed["dictation_close_pending"])
        self.assertFalse(closed["microphone_in_use"])
        self.assertEqual(closed["microphone_owners"], "none")


if __name__ == "__main__":
    unittest.main()
