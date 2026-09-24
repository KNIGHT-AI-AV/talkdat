"""The founder's-log window must be bounded at BOTH ends, not just the floor.

The daily issue scan reads `%APPDATA%\\TalkDat\\talk-dat.log` and reports
anything that went wrong in the last ~26 hours. That log contains a
deliberate clock-skew fixture from 2026-08-10 whose lines are dated
**2116-12-31**, including:

    2116-12-31 23:55:44 WARNING knight_flow.app: update check failed:
    [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed:
    certificate has expired

This line has now nearly become a finding twice, by two different routes:

  * 2026-09-08, by STRING comparison -- `awk '$1>="2026-09-07"'` treats
    "2116..." as greater than "2026..." lexically, so the skew lines sort as
    today's news. The trap was recorded, and the recorded remedy was "filter
    by real date parsing".
  * 2026-09-13, by DATE comparison -- which is the point of this test. Real
    `datetime` parsing does not help on its own: `datetime(2116, 12, 31) >=
    now - 26h` is simply true, so a floor-only window admits the same line
    for a better reason. The 09-13 scan reproduced it: a lower-bound-only
    filter reported the expired-certificate warning inside the window, and
    only an upper bound removed it.

So the property is not "parse the dates". It is that a window has two
bounds, and that a line the window rejects for being in the FUTURE is
reported as an excluded artifact rather than silently dropped -- a scan that
quietly discards lines it cannot place is how a real fault gets discarded
with them.

The rest of what this pins is the refusal contract this repo already uses:
a log that cannot be read at all must not report "quiet" (X-541's rule, and
the estate's twice-learned lesson that a green meaning *nothing was checked*
is indistinguishable from a green meaning *nothing is wrong*).
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from scripts.read_app_log import CANNOT_READ, scan, verdict_exit_code

NOW = datetime(2026, 9, 13, 9, 18, 0)


def line(when: str, level: str, message: str) -> str:
    return f"{when},000 {level} knight_flow.app: {message}"


# The three shapes that actually appear in his log, kept verbatim so a
# change to the log format fails here rather than in the field.
RECENT = line("2026-09-13 09:08:33", "INFO", "protected voice session finalized: id=x status=delivered bytes=1")
YESTERDAY = line("2026-09-12 08:09:57", "INFO", "Talk DAT! starting")
OLD = line("2026-09-01 12:00:00", "INFO", "Talk DAT! starting")
SKEW_WARNING = line(
    "2116-12-31 23:55:44",
    "WARNING",
    "update check failed: Could not reach the Talk DAT! update service: "
    "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: certificate has expired (_ssl.c:1032).",
)
SKEW_INFO = line("2117-01-01 00:00:05", "INFO", "managed cloud blocked: no active account")


class TheWindowRejectsTheFuture(unittest.TestCase):
    def test_a_future_dated_warning_is_not_a_finding(self):
        """The regression. A floor-only window calls this an expired certificate."""
        window = scan([RECENT, SKEW_WARNING], now=NOW)

        self.assertEqual(window.findings, ())
        self.assertTrue(window.quiet)

    def test_the_future_dated_lines_are_reported_rather_than_dropped(self):
        window = scan([RECENT, SKEW_WARNING, SKEW_INFO], now=NOW)

        self.assertEqual(len(window.future), 2)
        self.assertIn("2116-12-31", window.note)
        # It must be legible as an artifact, not as news.
        self.assertNotIn("certificate has expired", window.note)

    def test_a_line_from_before_the_floor_is_out_of_the_window(self):
        window = scan([OLD, RECENT], now=NOW)

        self.assertEqual([r.message for r in window.records], ["protected voice session finalized: id=x status=delivered bytes=1"])

    def test_both_bounds_are_inclusive_of_the_real_window(self):
        window = scan([YESTERDAY, RECENT], now=NOW, hours=26)

        self.assertEqual(len(window.records), 2)

    def test_a_line_dated_seconds_from_now_is_kept_not_treated_as_skew(self):
        """The ceiling carries slack: a log written as the scan runs is real."""
        just_now = (NOW + timedelta(seconds=30)).strftime("%Y-%m-%d %H:%M:%S")
        window = scan([line(just_now, "INFO", "push_to_talk start")], now=NOW)

        self.assertEqual(len(window.records), 1)
        self.assertEqual(window.future, ())


class RealFaultsStillSurface(unittest.TestCase):
    def test_an_in_window_warning_is_a_finding(self):
        window = scan([RECENT, line("2026-09-13 09:00:00", "WARNING", "update install failed: access denied")], now=NOW)

        self.assertFalse(window.quiet)
        self.assertEqual(window.findings[0].kind, "warning")
        self.assertIn("update install failed", window.findings[0].sample)

    def test_a_traceback_is_attached_to_the_record_above_it(self):
        lines = [
            line("2026-09-13 09:00:00", "ERROR", "exception in callback"),
            "Traceback (most recent call last):",
            '  File "app.py", line 1, in <module>',
            "TclError: invalid command name .!scrollbar",
            RECENT,
        ]
        window = scan(lines, now=NOW)

        self.assertFalse(window.quiet)
        self.assertIn("TclError", window.records[0].detail)

    def test_a_traceback_under_a_future_dated_record_is_excluded_with_it(self):
        lines = [SKEW_WARNING, "Traceback (most recent call last):", "TclError: boom", RECENT]
        window = scan(lines, now=NOW)

        self.assertTrue(window.quiet)
        self.assertIn("TclError", window.future[0].detail)

    def test_a_warning_repeated_more_than_twice_is_its_own_finding(self):
        noisy = [line(f"2026-09-13 09:0{n}:00", "WARNING", "audio backend reset") for n in range(4)]
        window = scan([*noisy, RECENT], now=NOW)

        repeated = [f for f in window.findings if f.kind == "repeated-warning"]
        self.assertEqual(len(repeated), 1)
        self.assertEqual(repeated[0].count, 4)

    def test_a_warning_seen_twice_is_not_the_repeated_finding(self):
        twice = [line(f"2026-09-13 09:0{n}:00", "WARNING", "audio backend reset") for n in range(2)]
        window = scan([*twice, RECENT], now=NOW)

        self.assertEqual([f.kind for f in window.findings if f.kind == "repeated-warning"], [])

    def test_repeated_managed_cloud_refusals_surface_even_at_info_level(self):
        refusals = [line(f"2026-09-13 09:0{n}:00", "INFO", "managed cloud blocked: no active account") for n in range(5)]
        window = scan([*refusals, RECENT], now=NOW)

        self.assertIn("managed-cloud", [f.kind for f in window.findings])

    def test_the_skew_fixtures_managed_cloud_refusals_do_not_trip_it(self):
        """The real log carries ten of these, all dated 2117."""
        refusals = [SKEW_INFO] * 10
        window = scan([*refusals, RECENT], now=NOW)

        self.assertTrue(window.quiet)


class ItRefusesRatherThanReportingQuiet(unittest.TestCase):
    def test_a_log_with_no_parseable_record_cannot_be_read(self):
        window = scan(["", "not a log line at all"], now=NOW)

        self.assertIs(window.quiet, CANNOT_READ)

    def test_cannot_read_exits_two_never_zero(self):
        window = scan([], now=NOW)

        self.assertIs(window.quiet, CANNOT_READ)
        self.assertEqual(verdict_exit_code(window), 2)

    def test_an_empty_window_over_a_readable_log_is_quiet_not_a_refusal(self):
        """He can be away for a day. That is silence, not blindness."""
        window = scan([OLD], now=NOW)

        self.assertIs(window.quiet, True)
        self.assertEqual(verdict_exit_code(window), 0)
        self.assertIn("no activity", window.note)

    def test_findings_exit_one(self):
        window = scan([line("2026-09-13 09:00:00", "ERROR", "crash")], now=NOW)

        self.assertEqual(verdict_exit_code(window), 1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
