"""X-609: Scribe says 'stopping' before it wakes the worker, never after.

A loaded full suite (2026-09-24) caught test_scribe_engine's cancel case ending
on 'stopping': finish() woke the worker first, the worker stopped at once and
wrote 'paused', and finish() then overwrote it with 'stopping'. The window
would have stayed on "Closing the audio devices" after the recording stopped.
"""
from __future__ import annotations

import unittest

from knight_flow.scribe_engine import ScribeEngine


class _InstantWorkerEvent:
    """A stop event whose worker reacts the instant it is set."""

    def __init__(self, engine: ScribeEngine) -> None:
        self.engine, self._set = engine, False

    def set(self) -> None:
        self._set = True
        self.engine._state("paused", "Recording stopped.")

    def is_set(self) -> bool:
        return self._set

    def wait(self, _timeout=None) -> bool:
        return self._set


class ScribeStopOrderTests(unittest.TestCase):
    def test_the_workers_state_is_the_last_word(self):
        engine = ScribeEngine({"scribe": {"source": "microphone"}}, dispatch=lambda deliver: deliver(),
                              on_state=lambda *_: None)
        engine.stop_event = _InstantWorkerEvent(engine)
        engine.finish()
        self.assertEqual(engine.phase, "paused")


if __name__ == "__main__":
    unittest.main()
