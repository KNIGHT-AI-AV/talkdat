"""Keep optional wake listening subordinate to explicit capture and privacy controls."""

from __future__ import annotations
import json, time
from .wake import WakeWordListener


class WakeRuntime:
    def __init__(self, app):
        self.app = app
        self.signature = None
        self.suspended = False
        self.timer = None
        self.enabled_before = False
        self.not_before = 0
        self.last_wake = None
        self.capture_pending = None
        self.capture_timer = None
        self.capture_deadline = 0

    def cancel_handoff(self):
        pending = self.capture_pending is not None
        self.capture_pending = None
        if self.capture_timer is not None:
            try:
                self.app.overlay.root.after_cancel(self.capture_timer)
            except Exception:
                pass
            self.capture_timer = None
        return pending

    def handoff(self, begin):
        if self.capture_pending is not None:
            return True
        listener = getattr(self.app, "wake_listener", None)
        if listener is None:
            return False
        listener.stop()
        self.not_before = time.monotonic() + 0.5
        if listener.closed.is_set():
            return False
        token = object()
        self.capture_pending = token
        self.capture_deadline = time.monotonic() + 5
        self.app.overlay.set_state(
            "starting", "Closing wake microphone before dictation."
        )

        def confirm():
            if self.capture_pending is not token:
                return
            self.capture_timer = None
            if getattr(self.app, "paused", False) or getattr(
                self.app, "_quitting", False
            ):
                self.cancel_handoff()
                return
            if listener.closed.is_set():
                self.capture_pending = None
                self.not_before = time.monotonic() + 0.5
                begin()
                return
            if time.monotonic() >= self.capture_deadline:
                self.cancel_handoff()
                self.app.overlay.set_state(
                    "error",
                    "The wake microphone is still closing.",
                    "Use Panic Stop to retry before dictating.",
                )
                return
            self.capture_timer = self.app.overlay.root.after(50, confirm)

        self.capture_timer = self.app.overlay.root.after(50, confirm)
        return True

    def busy(self):
        app = self.app
        from .mic_registry import microphone_registry

        listener = getattr(app, "wake_listener", None)
        own = getattr(listener, "_token", None)
        return bool(
            self.capture_pending is not None
            or getattr(app, "session", None) is not None
            or getattr(app, "session_token", None) is not None
            or any(owner.token != own for owner in microphone_registry().owners())
            or getattr(app, "_captions_engine", None) is not None
            or (getattr(app, "meeting", None) is not None and app.meeting.running)
            or bool(getattr(app, "_scribe_busy", lambda: False)())
            or bool(
                getattr(getattr(app, "_pronunciation_practice", None), "active", False)
            )
            or (
                getattr(app, "_microphone_check", None) is not None
                and not app._microphone_check.finished.is_set()
            )
        )

    def suspend(self):
        self.cancel_handoff()
        self.suspended = True
        listener = getattr(self.app, "wake_listener", None)
        if listener is not None:
            listener.stop()

    def stop(self):
        self.suspend()
        if self.timer is not None:
            try:
                self.app.overlay.root.after_cancel(self.timer)
            except Exception:
                pass
            self.timer = None

    def _schedule(self):
        if self.timer is not None or getattr(self.app, "_quitting", False):
            return

        def poll():
            self.timer = None
            self.refresh()

        self.timer = self.app.overlay.root.after(300, poll)

    def refresh(self, *, retry=False):
        app = self.app
        settings = app.config.get("wake_word", {})
        enabled = type(settings) is dict and settings.get("enabled") is True
        if not enabled:
            self.suspended = False
        elif not self.enabled_before:
            self.suspended = False
        self.enabled_before = enabled
        current = getattr(app, "wake_listener", None)
        if (
            not enabled
            or self.suspended
            or getattr(app, "paused", False)
            or getattr(app, "_quitting", False)
            or self.busy()
        ):
            if current is not None:
                current.stop()
            if enabled or (
                current is not None and (current.running or not current.closed.is_set())
            ):
                self._schedule()
            return
        signature = json.dumps(
            {
                "wake": settings,
                "input": app.config.get("audio", {}).get("input_device", ""),
            },
            sort_keys=True,
        )
        if current is not None and signature != self.signature:
            current.stop()
            if (
                current.running
                or not current.closed.is_set()
                or (
                    getattr(current, "_decoder", None) is not None
                    and current._decoder.is_alive()
                )
            ):
                self._schedule()
                return
            app.wake_listener = None
            current = None
        if current is None:
            entry = {}

            def status(message):
                listener = entry["listener"]
                generation = getattr(listener, "generation", 0)
                app._cross_thread_calls.put(
                    lambda: self._status(listener, generation, message)
                )

            def wake():
                listener = entry["listener"]
                generation = getattr(listener, "generation", 0)
                app._cross_thread_calls.put(lambda: self._wake(listener, generation))

            current = WakeWordListener(app.config, on_wake=wake, on_status=status)
            entry["listener"] = current
            app.wake_listener = current
            self.signature = signature
        if (
            not current.running
            and current.closed.is_set()
            and time.monotonic() >= self.not_before
            and (
                current.phase != "detected"
                or self.last_wake == (current, current.generation)
            )
            and (not current.failed or retry)
        ):
            current.start()
        self._schedule()

    def _status(self, listener, generation, message):
        app = self.app
        if (
            getattr(app, "wake_listener", None) is not listener
            or generation != getattr(listener, "generation", 0)
            or listener.message != message
            or getattr(app, "_quitting", False)
        ):
            return
        app._wake_status = {
            "phase": listener.phase,
            "message": message,
            "microphone_open": not listener.closed.is_set(),
        }
        if self.busy():
            return
        if listener.phase in {"error", "close-failed"}:
            app.overlay.set_state(
                "error",
                message,
                "Wake word remains optional. Your regular recording controls are available.",
            )
        elif listener.phase == "listening":
            app.overlay.set_state(
                "idle", message, "Pause or Panic Stop ends wake listening.", say=True
            )

    def _wake(self, listener, generation):
        app = self.app
        identity = (listener, generation)
        if (
            getattr(app, "wake_listener", None) is not listener
            or generation != getattr(listener, "generation", 0)
            or identity == self.last_wake
        ):
            return
        self.last_wake = identity
        if (
            listener.phase != "detected"
            or not listener.closed.is_set()
            or self.suspended
            or getattr(app, "paused", False)
            or getattr(app, "_quitting", False)
            or app.config.get("wake_word", {}).get("enabled") is not True
            or self.busy()
        ):
            return
        self.not_before = time.monotonic() + 2.5
        app.toggle_hands_free()
