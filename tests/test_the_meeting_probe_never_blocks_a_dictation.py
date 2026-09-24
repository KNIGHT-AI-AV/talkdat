"""X-411: the meeting probe answers from its cache and refreshes in the background.

`meeting_in_progress` decides whether a chime may play. It shelled out to
`tasklist`, which takes 1.4 to 2.5 seconds on the founder's PC, and it ran
inside the dictation path twice: at the start chime (so the hold began late)
and at the landing chime (inside the paste window, which the log clocked at
5.4 s for a clipboard paste). The probe now returns what it last knew at once
and refreshes on a thread when the answer is stale, so no dictation waits
for a process listing.
"""
from __future__ import annotations

import threading
import time
import unittest
from unittest.mock import patch

from knight_flow import meeting_quiet


class TheMeetingProbeNeverBlocksTests(unittest.TestCase):
    def setUp(self) -> None:
        meeting_quiet._reset_for_tests()

    def test_a_stale_probe_answers_at_once_and_refreshes_behind(self) -> None:
        started = threading.Event()
        release = threading.Event()

        def slow_scan() -> set[str]:
            started.set()
            release.wait(5)
            return {"zoom.exe"}

        with patch.object(meeting_quiet, "_scan_for_meeting", lambda: bool({"zoom.exe"} & slow_scan())):
            began = time.perf_counter()
            first = meeting_quiet.meeting_in_progress({})
            elapsed = time.perf_counter() - began
            self.assertFalse(first, "nothing known yet means no meeting, and no wait")
            self.assertLess(elapsed, 0.5, "the caller must not wait for the scan")
            self.assertTrue(started.wait(2), "a refresh started in the background")
            release.set()
            meeting_quiet._wait_for_refresh(2)
            self.assertTrue(meeting_quiet.meeting_in_progress({}, now=time.monotonic()), "the refreshed answer is the cached one now")

    def test_only_one_refresh_runs_at_a_time(self) -> None:
        calls = []
        gate = threading.Event()

        def scan() -> set[str]:
            calls.append(1)
            gate.wait(5)
            return set()

        with patch.object(meeting_quiet, "_scan_for_meeting", lambda: bool(scan())):
            for _ in range(5):
                meeting_quiet.meeting_in_progress({})
            gate.set()
            meeting_quiet._wait_for_refresh(2)
        self.assertEqual(len(calls), 1)

    def test_the_cache_is_trusted_for_ten_seconds(self) -> None:
        with patch.object(meeting_quiet, "_scan_for_meeting", lambda: True):
            meeting_quiet.meeting_in_progress({}, now=100.0)
            meeting_quiet._wait_for_refresh(2)
            self.assertTrue(meeting_quiet.meeting_in_progress({}, now=105.0))
        gate = threading.Event()

        def empty_after_gate() -> set[str]:
            gate.wait(5)
            return set()

        with patch.object(meeting_quiet, "_scan_for_meeting", lambda: bool(empty_after_gate())):
            self.assertTrue(meeting_quiet.meeting_in_progress({}, now=105.0), "within the window the cache answers, no scan")
            self.assertTrue(meeting_quiet.meeting_in_progress({}, now=200.0), "stale: the old answer, while a refresh starts")
            gate.set()
            meeting_quiet._wait_for_refresh(2)
            self.assertFalse(meeting_quiet.meeting_in_progress({}, now=200.5))

    def test_opting_out_never_scans(self) -> None:
        with patch.object(meeting_quiet, "_scan_for_meeting", side_effect=AssertionError("scanned")):
            self.assertFalse(meeting_quiet.meeting_in_progress({"notifications": {"meeting_quiet": False}}))


if __name__ == "__main__":
    unittest.main()
