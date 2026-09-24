"""X-545: a hard crash leaves nothing in the log the daily scan reads.

`faulthandler` writes its dump to `crash-traceback.log`. The process is gone,
so nothing reaches `talk-dat.log` -- no traceback, no ERROR, not one line. The
scan reads only `talk-dat.log`, so a crash is invisible to it.

On 2026-09-14 the founder's copy died of heap corruption mid-paste. The scan
saw one WARNING, "recovered 1 interrupted protected voice session(s)", and that
warning only exists because a protected voice session happened to be in flight.
A crash a second either side of a dictation leaves the scan reporting a quiet
log over a machine that fell over.

The dump carries NO timestamps of its own, so mtime is the only clock and it
dates the LAST record only. That is stated rather than smoothed over: a file
with five records has one date, and the four before it are undated.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from scripts.read_app_log import DEFAULT_HOURS, read_crash_dump

NOW = datetime(2026, 9, 15, 9, 30, 0)

# Trimmed to shape from his real file: two records, the last one his.
DUMP = '''Windows fatal exception: access violation

Current thread 0x00003d28 (most recent call first):
  Garbage-collecting
  <no Python frame>
Windows fatal exception: code 0xc0000374

Thread 0x000054d0 (most recent call first):
  <no Python frame>

Current thread 0x0000cfb0 (most recent call first):
  File "knight_flow\paste.py", line 516 in snapshot_clipboard
  File "knight_flow\paste.py", line 1259 in paste_text_with_receipt
  File "knight_flow\app.py", line 3071 in handle_dictation
'''


class TheScanCanSeeACrashTests(unittest.TestCase):
    def test_a_recent_dump_is_a_finding_naming_the_fault_and_the_frame(self) -> None:
        crash = read_crash_dump(DUMP, NOW - timedelta(hours=2), now=NOW)
        self.assertIsNotNone(crash)
        self.assertTrue(crash.in_window)
        self.assertIn("0xc0000374", crash.fault)
        self.assertIn("snapshot_clipboard", crash.frame)

    def test_the_last_record_is_the_one_mtime_dates_not_the_first(self) -> None:
        """Five records, one mtime. Reporting the first would date it wrong."""
        crash = read_crash_dump(DUMP, NOW - timedelta(hours=2), now=NOW)
        self.assertEqual(crash.records, 2)
        self.assertNotIn("access violation", crash.fault)

    def test_an_old_dump_is_not_reported_as_todays_news(self) -> None:
        crash = read_crash_dump(DUMP, NOW - timedelta(hours=DEFAULT_HOURS + 5), now=NOW)
        self.assertIsNotNone(crash)
        self.assertFalse(crash.in_window)

    def test_a_file_with_no_fault_record_is_not_a_crash(self) -> None:
        self.assertIsNone(read_crash_dump("nothing to see\n", NOW, now=NOW))
        self.assertIsNone(read_crash_dump("", NOW, now=NOW))


if __name__ == "__main__":
    unittest.main()
