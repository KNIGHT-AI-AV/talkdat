"""X-428: setup records which terms were accepted, and when.

The mechanism matters more than it looks. "Continued use implies acceptance"
(browsewrap) is enforced in roughly 14% of US cases against ~70% for an
affirmative click, and privacy law generally wants consent to be an act rather
than an inference. Setup already ends on a button, so the act is free -- but it
is only worth anything if what it accepted is written down. These tests hold
that recording in place.
"""

from __future__ import annotations

import time
import unittest

from knight_flow.onboarding import (
    PRIVACY_URL,
    TERMS_URL,
    TERMS_VERSION,
    mark_onboarding_complete,
    terms_acceptance,
    terms_are_current,
)


def _finish(config: dict) -> None:
    mark_onboarding_complete(
        config,
        route="local",
        microphone_tested=True,
        hotkey_rehearsed=True,
        dictation_tested=True,
    )


class TermsAcceptanceIsRecorded(unittest.TestCase):
    def test_finishing_setup_records_version_and_time(self) -> None:
        config: dict = {}
        before = int(time.time())
        _finish(config)
        version, accepted_at = terms_acceptance(config)
        self.assertEqual(version, TERMS_VERSION)
        self.assertGreaterEqual(accepted_at, before)

    def test_a_fresh_config_has_accepted_nothing(self) -> None:
        self.assertEqual(terms_acceptance({}), ("", 0))
        self.assertFalse(terms_are_current({}))

    def test_current_after_finishing(self) -> None:
        config: dict = {}
        _finish(config)
        self.assertTrue(terms_are_current(config))

    def test_older_terms_are_not_current(self) -> None:
        """A material terms change bumps TERMS_VERSION; older acceptances stop counting."""
        config = {"onboarding": {"terms_version": "2000-01-01", "terms_accepted_at": 1}}
        self.assertFalse(terms_are_current(config))

    def test_a_version_without_a_timestamp_is_not_acceptance(self) -> None:
        config = {"onboarding": {"terms_version": TERMS_VERSION, "terms_accepted_at": 0}}
        self.assertFalse(terms_are_current(config))

    def test_garbage_timestamp_does_not_raise(self) -> None:
        config = {"onboarding": {"terms_version": TERMS_VERSION, "terms_accepted_at": "soon"}}
        self.assertEqual(terms_acceptance(config)[1], 0)
        self.assertFalse(terms_are_current(config))

    def test_acceptance_does_not_disturb_the_rest_of_onboarding(self) -> None:
        config: dict = {}
        _finish(config)
        onboarding = config["onboarding"]
        self.assertTrue(onboarding["completed"])
        self.assertEqual(onboarding["route"], "local")
        self.assertTrue(onboarding["dictation_tested"])


class TermsLinksArePublicPages(unittest.TestCase):
    """A notice pointing at unreachable terms is worth nothing."""

    def test_urls_are_the_live_pages(self) -> None:
        self.assertEqual(TERMS_URL, "https://www.talkdat.app/terms.html")
        self.assertEqual(PRIVACY_URL, "https://www.talkdat.app/privacy.html")

    def test_version_is_a_date_stamp(self) -> None:
        year, month, day = TERMS_VERSION.split("-")
        self.assertEqual((len(year), len(month), len(day)), (4, 2, 2))
        self.assertTrue(TERMS_VERSION.replace("-", "").isdigit())


class AcceptanceIsLocalOnly(unittest.TestCase):
    """Setup must finish with no network. Offline is the product."""

    def test_marking_complete_opens_no_socket(self) -> None:
        import socket

        real = socket.socket

        def refuse(*args, **kwargs):  # pragma: no cover - only runs on regression
            raise AssertionError("terms acceptance must not touch the network")

        socket.socket = refuse
        try:
            config: dict = {}
            _finish(config)
        finally:
            socket.socket = real
        self.assertTrue(terms_are_current(config))


if __name__ == "__main__":
    unittest.main()
