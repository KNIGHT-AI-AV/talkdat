from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from knight_flow.export_markdown import append_dictation, export_folder, format_entry
from knight_flow import meeting_quiet


class MarkdownMirrorTests(unittest.TestCase):
    """X-29. Off by default, one append per delivery, valid Markdown, and a
    failure never raises toward the delivery it rides beside."""

    def test_off_by_default(self) -> None:
        self.assertIsNone(export_folder({}))
        self.assertFalse(append_dictation({}, "hello"))

    def test_a_day_gets_one_file_with_a_heading_and_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = {"export": {"markdown_folder": tmp}}
            when = dt.datetime(2026, 8, 9, 14, 5)
            self.assertTrue(append_dictation(config, "First note", now=when))
            self.assertTrue(append_dictation(config, "Second note", now=when.replace(minute=30)))
            path = Path(tmp) / "2026-08-09.md"
            body = path.read_text(encoding="utf-8")
            self.assertTrue(body.startswith("# Talk DAT!"))
            self.assertIn("- **14:05** First note", body)
            self.assertIn("- **14:30** Second note", body)
            self.assertEqual(body.count("# Talk DAT!"), 1, "heading written once")

    def test_multiline_dictations_stay_valid_markdown(self) -> None:
        entry = format_entry("Title line\nsecond line\nthird", dt.datetime(2026, 8, 9, 9, 0))
        lines = entry.splitlines()
        self.assertTrue(lines[0].startswith("- **09:00** Title line"))
        self.assertTrue(all(line.startswith("  ") or not line for line in lines[1:]))

    def test_an_unwritable_folder_reports_false_never_raises(self) -> None:
        with tempfile.NamedTemporaryFile(delete=False) as blocker:
            blocker_path = blocker.name
        try:
            # A FILE where the folder should be: mkdir must fail everywhere.
            config = {"export": {"markdown_folder": blocker_path + "/sub"}}
            self.assertFalse(append_dictation(config, "hello"))
        finally:
            Path(blocker_path).unlink(missing_ok=True)


class MeetingQuietTests(unittest.TestCase):
    """X-26. Quiet when a conferencing app is alive, silent about being
    wrong, cached so callers may ask constantly, opt-out respected.

    X-411: the scan runs on a refresh thread, so a test asks, waits for the
    refresh, then reads the answer the next call gives."""

    def setUp(self) -> None:
        meeting_quiet._reset_for_tests()

    def _settled(self, now: float) -> bool:
        meeting_quiet.meeting_in_progress({}, now=now)
        meeting_quiet._wait_for_refresh(2)
        return meeting_quiet.meeting_in_progress({}, now=now + 1.0)

    def test_a_zoom_process_means_quiet(self) -> None:
        with mock.patch.object(meeting_quiet, "_scan_for_meeting", return_value=True):
            self.assertTrue(self._settled(100.0))

    def test_no_meeting_apps_means_normal(self) -> None:
        with mock.patch.object(meeting_quiet, "_scan_for_meeting", return_value=False):
            self.assertFalse(self._settled(100.0))

    def test_the_answer_is_cached_between_checks(self) -> None:
        with mock.patch.object(meeting_quiet, "_scan_for_meeting", return_value=True) as probe:
            self.assertTrue(self._settled(100.0))
            self.assertTrue(meeting_quiet.meeting_in_progress({}, now=105.0))
            probe.assert_called_once()

    def test_the_opt_out_wins_without_probing(self) -> None:
        config = {"notifications": {"meeting_quiet": False}}
        with mock.patch.object(meeting_quiet, "_scan_for_meeting") as probe:
            self.assertFalse(meeting_quiet.meeting_in_progress(config, now=200.0))
        probe.assert_not_called()

    def test_a_probe_failure_reads_as_not_in_a_meeting(self) -> None:
        with mock.patch.object(meeting_quiet, "_scan_for_meeting", side_effect=OSError):
            self.assertFalse(self._settled(300.0))

    def test_the_windows_scan_reads_tasklist_names(self) -> None:
        with mock.patch.object(meeting_quiet, "_running_process_names", return_value={"zoom.exe", "explorer.exe"}),              mock.patch.object(meeting_quiet.sys, "platform", "win32"):
            self.assertTrue(meeting_quiet._scan_for_meeting())
        with mock.patch.object(meeting_quiet, "_running_process_names", return_value={"explorer.exe"}),              mock.patch.object(meeting_quiet.sys, "platform", "win32"):
            self.assertFalse(meeting_quiet._scan_for_meeting())


if __name__ == "__main__":
    unittest.main()
