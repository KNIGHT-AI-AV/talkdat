"""X-354: the ghosted setup window -- the UI thread must never park on
the engine lock.

The field failure, from the founder's PC on 0.4.123: onboarding step 6
polls ``status_snapshot`` from the Tk thread at 32ms while it lights the
trigger keycaps. A trigger press runs ``start_session`` on the hotkey
dispatch worker, which held ``self.lock`` through operations that can
each take seconds on a slow machine (credential read through lsass,
model preflight, session arming, the COM mute guard). The Tk thread
blocked inside the poll's unconditional acquire, Windows ghosted the
window at five seconds, and because the holder wedged, the app stayed
frozen forever with nothing after "push_to_talk start" in the log.

Two structural rules fall out, and this file defends both:

  A STATUS READOUT NEVER BUYS CONSISTENCY WITH UI LIVENESS. The snapshot
  waits a bounded 200ms, then serves the previous snapshot marked stale.

  THE SESSION-START LOCK COVERS STATE, NOT SIDE EFFECTS. The mute guard
  and the dead-mic timer run after the lock releases -- and the timer is
  armed through main_thread.post, because the guarded cross-thread
  ``root.after`` deliberately drops delays, which would fire the dead-mic
  check ~25ms in instead of at 2.5 seconds.
"""

from __future__ import annotations

import re
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from knight_flow.app import TalkDatApp

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "knight_flow" / "app.py"
WIZARD = ROOT / "knight_flow" / "ui" / "onboarding.py"


class _QuietRegistry:
    def is_active(self) -> bool:
        return False

    def names(self) -> tuple[str, ...]:
        return ()


class _QuietOverlay:
    state = "idle"


def _bare_app() -> TalkDatApp:
    app = TalkDatApp.__new__(TalkDatApp)
    app.lock = threading.RLock()
    app.session = None
    app.session_mode = "idle"
    app.session_control = "idle"
    app.config = {}
    app.overlay = _QuietOverlay()
    return app


class TheSnapshotServesStaleInsteadOfWaitingTests(unittest.TestCase):
    def test_a_wedged_lock_holder_cannot_park_the_caller(self) -> None:
        """Restores the field defect's shape: another thread owns the app
        lock and never lets go. Before X-354 this call blocked forever --
        the ghost window. Now it returns fast, marked stale."""
        app = _bare_app()
        holding = threading.Event()
        release = threading.Event()

        with patch("knight_flow.app.microphone_registry", return_value=_QuietRegistry()):
            first = app.status_snapshot()
            self.assertNotIn("stale", first)

            def wedge() -> None:
                with app.lock:
                    holding.set()
                    release.wait(5.0)

            holder = threading.Thread(target=wedge, name="TalkDatHotkeyDispatch")
            holder.start()
            try:
                self.assertTrue(holding.wait(2.0))
                started = time.monotonic()
                snapshot = app.status_snapshot()
                elapsed = time.monotonic() - started
            finally:
                release.set()
                holder.join(timeout=5.0)

        self.assertLess(
            elapsed, 1.5,
            "status_snapshot waited on a held engine lock; that wait is the "
            "ghost-window class X-354 removed",
        )
        self.assertTrue(snapshot.get("stale"))
        self.assertEqual(snapshot["session_mode"], "idle",
                         "the stale serve must be the previous real snapshot")

    def test_stale_without_history_still_answers(self) -> None:
        """A first-ever call under contention has no cache to serve. It must
        still answer -- a minimal honest dict, never a wait."""
        app = _bare_app()
        holding = threading.Event()
        release = threading.Event()

        def wedge() -> None:
            with app.lock:
                holding.set()
                release.wait(5.0)

        holder = threading.Thread(target=wedge)
        holder.start()
        try:
            self.assertTrue(holding.wait(2.0))
            snapshot = app.status_snapshot()
        finally:
            release.set()
            holder.join(timeout=5.0)
        self.assertTrue(snapshot.get("stale"))
        self.assertEqual(snapshot.get("app"), "running")

    def test_a_free_lock_serves_fresh_and_restamps_the_cache(self) -> None:
        app = _bare_app()
        with patch("knight_flow.app.microphone_registry", return_value=_QuietRegistry()):
            first = app.status_snapshot()
            app.session_mode = "dictation"
            second = app.status_snapshot()
        self.assertEqual(first["session_mode"], "idle")
        self.assertEqual(second["session_mode"], "dictation")
        self.assertNotIn("stale", second)


class TheSessionStartLockCoversStateNotSideEffectsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = APP.read_text(encoding="utf-8")
        found = re.search(
            r"def start_session\(self.*?(?=\n    def )", cls.source, re.S
        )
        assert found, "start_session moved"
        cls.start = found.group(0)

    def test_the_dead_mic_check_is_defined_outside_the_lock(self) -> None:
        """Function-level indentation (8 spaces) proves the definition sits
        after the ``with self.lock:`` block ended, not inside it."""
        self.assertIn("\n        def no_frames_check", self.start)
        self.assertNotIn("\n            def no_frames_check", self.start)

    def test_the_mute_guard_runs_after_the_lock(self) -> None:
        self.assertIn("\n        self.begin_activation_guards()", self.start)
        self.assertNotIn("\n            self.begin_activation_guards()", self.start)

    def test_the_dead_mic_timer_keeps_its_delay_across_threads(self) -> None:
        """start_session runs on the hotkey dispatch worker, and the guarded
        cross-thread root.after DROPS the requested delay. Armed directly it
        fires ~25ms in -- before the first audio frame can arrive -- and
        every dictation would open with a false "microphone did not start".
        Posting the arm to the Tk thread creates the real 2.5s Tcl timer."""
        self.assertIn(
            "main_thread.post(lambda: self.overlay.root.after(2500, no_frames_check))",
            self.start,
        )
        self.assertNotIn("\n            self.overlay.root.after(2500", self.start)


class TheWizardPollRationsItsLockCrossingsTests(unittest.TestCase):
    def test_the_snapshot_is_cadenced_not_per_tick(self) -> None:
        """Keycap light-up stays at 32ms (hardware reads, no locks); the
        snapshot that phrases the status line crosses into the app lock, so
        it is taken at most every 250ms and cached between ticks."""
        source = WIZARD.read_text(encoding="utf-8")
        found = re.search(r"def _start_key_poll\(self\).*?(?=\n    def )", source, re.S)
        assert found, "_start_key_poll moved"
        poll = found.group(0)
        self.assertIn("_snapshot_cache", poll)
        self.assertIn("0.25", poll)
        self.assertEqual(
            poll.count("self._status_snapshot()"), 1,
            "one guarded snapshot call; a second unguarded one reopens the "
            "per-tick lock traffic",
        )


if __name__ == "__main__":
    unittest.main()
