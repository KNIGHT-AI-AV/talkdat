from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from knight_flow.feedback import build_feedback_payload, submit_feedback
from knight_flow.format_journal import journal_tail
from knight_flow.licensing import DEFAULT_COMMERCE_API_URL


class TheReportGoesToTheBackendTests(unittest.TestCase):
    """X-01. The old Share-an-idea was a mailto: link -- on a PC with no mail
    client it did nothing, silently. The report now posts to the commerce
    service; these tests pin the payload shape and the fallback contract."""

    def test_the_payload_carries_what_the_backend_stores(self) -> None:
        payload = build_feedback_payload(
            kind="feature",
            title="History dates",
            details="The history window is hard to read by date.",
            contact="me@example.com",
            context="menu:history",
        )
        self.assertIn("History dates", payload["text"])
        self.assertIn("hard to read", payload["text"])
        self.assertEqual(payload["context"], "menu:history")
        self.assertEqual(payload["platform"], "mac" if sys.platform == "darwin" else "windows")
        # 2026-09-22: Talk DAT! is free, so there is no plan to report.
        self.assertNotIn("plan", payload)
        self.assertEqual(payload["reply"], "me@example.com")

    def test_language_requests_name_the_language(self) -> None:
        payload = build_feedback_payload(kind="language", language="Yoruba (Nigeria)")
        self.assertIn("Yoruba", payload["text"])
        self.assertEqual(payload["context"], "share-an-idea-language")

    def test_the_endpoint_is_the_single_commerce_hostname(self) -> None:
        """The account-API hostname bug shipped once (api.talkdat... never
        existed). Feedback must ride the same single constant, never a second
        copy of a URL."""
        captured: dict[str, str] = {}

        class FakeResponse:
            def read(self) -> bytes:
                return json.dumps({"received": True}).encode()

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def fake_urlopen(request, timeout=0):
            captured["url"] = request.full_url
            return FakeResponse()

        # Open source (2026-09-23): the inbox belongs to OFFICIAL builds; a
        # build from source falls back to email (tests/test_official_build.py).
        from knight_flow import official_build

        with mock.patch("urllib.request.urlopen", fake_urlopen), \
                mock.patch.object(official_build, "OFFICIAL", True), \
                mock.patch.dict("os.environ", {"TALKDAT_API_BASE": "", "TALKDAT_NO_PHONE_HOME": ""}):
            ok = submit_feedback({"text": "hello"})
        self.assertTrue(ok)
        self.assertEqual(captured["url"], f"{DEFAULT_COMMERCE_API_URL}/v1/feedback")

    def test_a_network_failure_reports_false_never_raises(self) -> None:
        """False is the signal for the mailto fallback -- an exception here
        would lose the report between the two paths."""
        from knight_flow import official_build

        with mock.patch("urllib.request.urlopen", side_effect=OSError("offline")), \
                mock.patch.object(official_build, "OFFICIAL", True):
            self.assertFalse(submit_feedback({"text": "hello"}))

    def test_an_empty_report_is_never_posted(self) -> None:
        with mock.patch("urllib.request.urlopen") as opened:
            self.assertFalse(submit_feedback({"text": ""}))
        opened.assert_not_called()


class FormattingLogConsentTests(unittest.TestCase):
    """X-126. The formatting log contains dictated text, so it travels ONLY
    when the sender ticked the consent box -- the payload must omit the field
    entirely otherwise, and the tail helper must size the attachment to fit
    the server's 64KB request cap."""

    def test_no_consent_means_no_logs_field_at_all(self) -> None:
        payload = build_feedback_payload(kind="feature", title="t", details="d")
        self.assertNotIn("logs", payload)

    def test_consented_logs_ride_along_capped(self) -> None:
        payload = build_feedback_payload(
            kind="feature", title="t", details="d", logs="x" * 90_000
        )
        self.assertEqual(len(payload["logs"]), 48_000)

    def test_blank_logs_are_treated_as_absent(self) -> None:
        payload = build_feedback_payload(kind="feature", title="t", details="d", logs="   ")
        self.assertNotIn("logs", payload)

    def test_journal_tail_returns_newest_entries_within_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "formatting-journal.jsonl"
            lines = [json.dumps({"n": i, "raw": "word " * 30}) for i in range(200)]
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            with mock.patch("knight_flow.format_journal.journal_path", return_value=path):
                tail = journal_tail(max_entries=40, max_bytes=48_000)
        got = [json.loads(line) for line in tail.splitlines()]
        self.assertLessEqual(len(got), 40)
        self.assertEqual(got[-1]["n"], 199)  # newest entry always survives
        self.assertLessEqual(len(tail), 48_000)

    def test_journal_tail_is_empty_when_there_is_no_journal(self) -> None:
        missing = Path(tempfile.gettempdir()) / "talkdat-test-no-such-journal.jsonl"
        with mock.patch("knight_flow.format_journal.journal_path", return_value=missing):
            self.assertEqual(journal_tail(), "")


if __name__ == "__main__":
    unittest.main()
