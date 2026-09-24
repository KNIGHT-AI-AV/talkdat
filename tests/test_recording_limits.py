from __future__ import annotations

import inspect
import unittest

from knight_flow.config import engine_recording_ceiling


class NobodyHitsTheWallTests(unittest.TestCase):
    """X-41. Mayowa's own dictation was cut off at the 5-minute default, and
    the policy he set is per-ENGINE: local runs to 10 hours, a cloud engine
    stops at 1 hour.

    2026-09-22: Talk DAT! is free, so the generous ceiling that used to be the
    paid one is everyone's. There is no plan argument left to get wrong."""

    def test_local_runs_ten_hours(self) -> None:
        self.assertEqual(engine_recording_ceiling(cloud_engine=False), 36000)

    def test_an_own_key_cloud_engine_stops_at_one_hour(self) -> None:
        """The person's own provider bills by the minute and most refuse a
        longer upload, so it is the one engine with a shorter ceiling."""
        self.assertEqual(engine_recording_ceiling(cloud_engine=True), 3600)

    def test_the_ceiling_does_not_ask_who_is_paying(self) -> None:
        self.assertEqual(list(inspect.signature(engine_recording_ceiling).parameters), ["cloud_engine"])


if __name__ == "__main__":
    unittest.main()
