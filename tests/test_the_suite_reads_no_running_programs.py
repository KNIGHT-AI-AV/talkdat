"""The suite's answers must not depend on what else is open on the computer
that runs it. The meeting check asks tasklist whether a conferencing app is
running; with Zoom open on the PC that ran the full suite (2026-10-22), every
Pill message that was not an error was held back and four GUI tests failed.
The test package answers "nothing else is running"; a test that needs a
meeting fakes one. Fakes only: no program is started.
"""
from __future__ import annotations

import importlib.util
import subprocess
import unittest
from unittest import mock

from knight_flow import meeting_quiet

# What tasklist prints while Zoom is open.
LISTING = subprocess.CompletedProcess(
    ["tasklist"], 0,
    stdout='"Zoom.exe","4242","Console","1","90,000 K"\n"explorer.exe","1","Console","1","9,000 K"\n',
    stderr="",
)


def unpinned_meeting_quiet():
    """A fresh copy of the product module, which the test package never touched."""
    spec = importlib.util.spec_from_file_location("_meeting_quiet_unpinned", meeting_quiet.__file__)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TheSuiteReadsNoRunningPrograms(unittest.TestCase):
    def test_the_meeting_check_reads_no_process_list(self) -> None:
        with (
            mock.patch.object(subprocess, "run", return_value=LISTING) as run,
            mock.patch.object(meeting_quiet.sys, "platform", "win32"),
        ):
            self.assertEqual(meeting_quiet._running_process_names(), set())
            self.assertFalse(meeting_quiet._scan_for_meeting(), "an open Zoom reached the suite")
        run.assert_not_called()

    def test_without_the_test_package_the_same_listing_is_a_meeting(self) -> None:
        # The control: the test package, not the fake listing, keeps the suite out of meeting mode.
        product = unpinned_meeting_quiet()
        with (
            mock.patch.object(subprocess, "run", return_value=LISTING),
            mock.patch.object(product.sys, "platform", "win32"),
        ):
            self.assertIn("zoom.exe", product._running_process_names())
            self.assertTrue(product._scan_for_meeting())


if __name__ == "__main__":
    unittest.main()
