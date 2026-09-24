from __future__ import annotations

import threading
import time
import unittest

from knight_flow.stt_sessions import BatchSTTSession


def session(tail_ms: int) -> BatchSTTSession:
    noop = lambda *a, **k: None
    return BatchSTTSession(
        provider_id="openrouter", api_key="k", api_base="https://x", model="m",
        variant="", language="en", sample_rate=16000, channels=1, max_seconds=60,
        no_speech_timeout_seconds=5, silence_timeout_seconds=45,
        tail_capture_ms=tail_ms, min_capture_ms=0, extra={},
        on_update=noop, on_status=noop, on_level=noop, on_done=noop, on_error=noop,
    )


class AdaptiveTailTests(unittest.TestCase):
    """The wait after you release the key used to be a flat sleep.

    tail_capture_ms exists for the case where someone releases a moment before
    they stop talking. That is real but uncommon, and charging every dictation
    the worst case made it 520ms of a 2021ms median -- a quarter of the time
    between releasing the key and seeing text.
    """

    def test_it_returns_early_once_the_tail_goes_quiet(self) -> None:
        s = session(520)
        s._heard_voice = True
        s._last_voice_at = time.monotonic() - 1.0   # silent for a while already
        start = time.monotonic()
        s._drain_tail()
        elapsed = (time.monotonic() - start) * 1000
        self.assertLess(elapsed, 120, "a finished sentence should not pay the full budget")

    def test_it_keeps_waiting_while_speech_is_still_arriving(self) -> None:
        """The budget must remain fully available when it is actually needed,
        or the last word gets cut -- which is worse than any latency."""
        s = session(300)
        s._heard_voice = True
        # The audio callback keeps stamping _last_voice_at for as long as there
        # is anything to hear, so ongoing speech has to be simulated rather
        # than set once -- a single stale timestamp is silence, not speech.
        stop = threading.Event()

        def keep_talking() -> None:
            while not stop.is_set():
                s._last_voice_at = time.monotonic()
                time.sleep(0.01)

        talker = threading.Thread(target=keep_talking, daemon=True)
        talker.start()
        try:
            start = time.monotonic()
            s._drain_tail()
            elapsed = (time.monotonic() - start) * 1000
        finally:
            stop.set()
            talker.join(timeout=1)
        self.assertGreaterEqual(elapsed, 250, "it must not cut speech short")

    def test_a_session_that_never_heard_voice_waits_the_full_budget(self) -> None:
        """Otherwise a quiet mic, or speech the level meter never registered,
        would exit instantly and drop audio that was in fact captured."""
        s = session(200)
        s._heard_voice = False
        start = time.monotonic()
        s._drain_tail()
        self.assertGreaterEqual((time.monotonic() - start) * 1000, 180)

    def test_cancelling_stops_the_wait_immediately(self) -> None:
        s = session(5000)
        s._heard_voice = True
        s._last_voice_at = time.monotonic()
        s._cancel_event.set()
        start = time.monotonic()
        s._drain_tail()
        self.assertLess((time.monotonic() - start) * 1000, 100)

    def test_a_zero_budget_does_not_wait(self) -> None:
        s = session(0)
        start = time.monotonic()
        s._drain_tail()
        self.assertLess((time.monotonic() - start) * 1000, 30)


if __name__ == "__main__":
    unittest.main()
