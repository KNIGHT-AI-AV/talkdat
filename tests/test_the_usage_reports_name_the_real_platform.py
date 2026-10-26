"""Polylane iss_166dd7d7f001clc647h0ggb7: every usage report names the platform it was sent from.

The Mac build shares knight_flow/activation_metrics.py with Windows. The heartbeat
and day-7 reports read the platform, but the install report and the first-dictation
report wrote "windows" as a literal, so every Mac install and every Mac first
dictation was counted as a Windows one, and the per-platform activation numbers
were wrong on both sides. These tests read the bytes each of the four reports
would send, with the platform set each way.
"""

from __future__ import annotations

import contextlib
import json
import sys
import time
import unittest
from unittest import mock

from knight_flow import activation_metrics

API = "https://example.test"


class _Sent:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return b""


def _capture(platform: str, send) -> list[dict]:
    """Run one report with sys.platform set, its thread run inline; return the payloads it sent."""
    captured: list[dict] = []

    def fake_urlopen(request, timeout=0):
        captured.append(json.loads(request.data.decode("utf-8")))
        return _Sent()

    def run_now(target, name=None, daemon=None):
        thread = mock.Mock()
        thread.start = target
        return thread

    with contextlib.ExitStack() as stack:
        stack.enter_context(mock.patch.object(activation_metrics.threading, "Thread", side_effect=run_now))
        stack.enter_context(mock.patch.object(activation_metrics.urllib.request, "urlopen", fake_urlopen))
        stack.enter_context(mock.patch.object(sys, "platform", platform))
        send()
    return captured


def _install(config):
    activation_metrics.report_install(config, lambda _c: None, API)


def _first_dictation(config):
    activation_metrics.record_first_dictation(config, lambda _c: None, API)


def _heartbeat(config):
    activation_metrics.report_heartbeat(config, lambda _c: None, API)


def _day7(config):
    activation_metrics.report_day7(config, lambda _c: None, API)


def _config(report: str) -> dict:
    now = int(time.time())
    metrics = {"install_id": "a" * 32, "first_run_at": now - 60}
    if report == "day7":
        metrics.update(first_run_at=now - 8 * 24 * 60 * 60, first_dictation_at=now - 7 * 24 * 60 * 60,
                       install_acked=True, activation_acked=True)
    return {"metrics": metrics}


REPORTS = {"install": _install, "first dictation": _first_dictation, "heartbeat": _heartbeat, "day7": _day7}


class EveryReportNamesTheRealPlatformTests(unittest.TestCase):
    def check(self, platform: str, expected: str) -> None:
        for name, send in REPORTS.items():
            with self.subTest(report=name, platform=platform):
                config = _config(name)
                sent = _capture(platform, lambda: send(config))
                self.assertEqual(len(sent), 1, f"the {name} report did not send")
                self.assertEqual(sent[0]["platform"], expected)

    def test_a_mac_sends_mac_in_all_four_reports(self) -> None:
        self.check("darwin", "mac")

    def test_windows_sends_windows_in_all_four_reports(self) -> None:
        self.check("win32", "windows")

    def test_no_report_writes_the_platform_as_a_literal(self) -> None:
        """The source half of the same claim: the one helper decides, so a fifth report cannot repeat it."""
        from pathlib import Path

        source = Path(activation_metrics.__file__).read_text(encoding="utf-8")
        for literal in ('"platform": "windows"', '"platform": "mac"'):
            self.assertFalse(literal in source, f"activation_metrics.py still writes {literal}")


if __name__ == "__main__":
    unittest.main()
