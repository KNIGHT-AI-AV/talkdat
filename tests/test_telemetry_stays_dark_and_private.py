"""The telemetry layer must be inert until armed, and private by construction.

WHY THIS EXISTS: the strategy is build-and-measure and the product currently
measures nothing. The layer lands dark -- default off, no endpoint, no call
sites wired -- so it can ship during the billing outage and be armed later by
config alone. These tests pin the two contracts that make that safe:

1. DARK: with the default config, record() writes nothing and flush() sends
   nothing. Arming requires BOTH `telemetry.enabled: true` AND a non-empty
   endpoint, so a stray toggle cannot start uploads to nowhere.

2. PRIVATE: the layer physically cannot carry a transcript. Event names come
   from a closed allowlist; property keys come from a per-event allowlist;
   values are short scalars only. A dictated sentence has no field it fits in.
   The install id is random -- generated, not derived from the machine -- so
   deleting one file makes the install statistically a stranger.

These are behaviour tests against the real module with a fake transport; no
test touches the network or the real %APPDATA% (TALK_DAT_HOME points at a
temp dir, per the house rule that tests never mutate the dev machine).
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from knight_flow import telemetry


def armed_config() -> dict:
    return {"telemetry": {"enabled": True, "endpoint": "https://ph.example/batch", "api_key": "phc_test"}}


class TelemetryEnvironment(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_home = os.environ.get("TALK_DAT_HOME")
        os.environ["TALK_DAT_HOME"] = self._tmp.name

    def tearDown(self) -> None:
        if self._old_home is None:
            os.environ.pop("TALK_DAT_HOME", None)
        else:
            os.environ["TALK_DAT_HOME"] = self._old_home
        self._tmp.cleanup()

    def queue_file(self) -> Path:
        return Path(self._tmp.name) / "telemetry_queue.jsonl"


class TheLayerStaysDark(TelemetryEnvironment):
    def test_default_config_records_nothing(self) -> None:
        telemetry.record({}, "app_started", {"app_version": "0.4.124-beta"})
        self.assertFalse(
            self.queue_file().exists(),
            "a default (unarmed) install must not write a telemetry queue at all",
        )

    def test_enabled_without_endpoint_is_still_dark(self) -> None:
        config = {"telemetry": {"enabled": True, "endpoint": ""}}
        telemetry.record(config, "app_started", {"app_version": "0.4.124-beta"})
        self.assertFalse(
            self.queue_file().exists(),
            "enabled without an endpoint must stay dark -- arming requires both",
        )

    def test_unarmed_flush_sends_nothing(self) -> None:
        calls: list = []
        telemetry.flush({}, transport=lambda *a: calls.append(a) or True)
        self.assertEqual(calls, [], "an unarmed install must never call the transport")


class TheLayerIsPrivateByConstruction(TelemetryEnvironment):
    def test_unknown_event_names_are_dropped(self) -> None:
        telemetry.record(armed_config(), "transcript_captured", {"app_version": "1"})
        self.assertFalse(self.queue_file().exists(), "an event name outside the allowlist must be dropped")

    def test_disallowed_property_keys_are_stripped(self) -> None:
        telemetry.record(
            armed_config(),
            "dictation_completed",
            {"route": "local", "text": "the dictated sentence", "path": "C:/secret"},
        )
        stored = json.loads(self.queue_file().read_text(encoding="utf-8").strip())
        self.assertEqual(
            set(stored["props"]), {"route"},
            "only allowlisted keys may survive; there must be no field a transcript fits in",
        )

    def test_oversized_values_are_dropped_not_truncated(self) -> None:
        telemetry.record(
            armed_config(),
            "dictation_completed",
            {"route": "x" * 500, "app_version": "0.4.124-beta"},
        )
        stored = json.loads(self.queue_file().read_text(encoding="utf-8").strip())
        self.assertNotIn(
            "route", stored["props"],
            "an oversized value is smuggling, not data -- drop the property entirely",
        )
        self.assertEqual(stored["props"].get("app_version"), "0.4.124-beta")

    def test_install_id_is_random_not_machine_derived(self) -> None:
        first = telemetry.install_id()
        again = telemetry.install_id()
        self.assertEqual(first, again, "the id must be stable across reads")
        (Path(self._tmp.name) / "telemetry_id").unlink()
        fresh = telemetry.install_id()
        self.assertNotEqual(
            first, fresh,
            "deleting the id file must yield a NEW id: proof it is generated, not derived",
        )


class TheQueueAndFlushBehave(TelemetryEnvironment):
    def test_queue_is_bounded_and_drops_oldest(self) -> None:
        config = armed_config()
        for index in range(telemetry.MAX_QUEUE_EVENTS + 25):
            telemetry.record(config, "settings_opened", {"app_version": str(index)})
        lines = self.queue_file().read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), telemetry.MAX_QUEUE_EVENTS)
        newest = json.loads(lines[-1])
        self.assertEqual(
            newest["props"]["app_version"], str(telemetry.MAX_QUEUE_EVENTS + 24),
            "overflow must drop the OLDEST events and keep the newest",
        )

    def test_flush_sends_the_batch_and_clears_the_queue(self) -> None:
        config = armed_config()
        telemetry.record(config, "app_started", {"app_version": "0.4.124-beta"})
        telemetry.record(config, "dictation_completed", {"route": "local"})
        sent: list = []

        def transport(url: str, api_key: str, payload: dict) -> bool:
            sent.append((url, api_key, payload))
            return True

        telemetry.flush(config, transport=transport)
        self.assertEqual(len(sent), 1)
        url, api_key, payload = sent[0]
        self.assertEqual(url, "https://ph.example/batch")
        self.assertEqual(api_key, "phc_test")
        self.assertEqual([e["event"] for e in payload["events"]], ["app_started", "dictation_completed"])
        self.assertEqual(payload["install_id"], telemetry.install_id())
        self.assertFalse(self.queue_file().exists(), "a delivered batch must not be re-sent")

    def test_failed_flush_keeps_the_queue_and_never_raises(self) -> None:
        config = armed_config()
        telemetry.record(config, "app_started", {"app_version": "0.4.124-beta"})

        def exploding_transport(url: str, api_key: str, payload: dict) -> bool:
            raise OSError("network is a suggestion")

        telemetry.flush(config, transport=exploding_transport)  # must not raise
        self.assertTrue(
            self.queue_file().exists(),
            "an undelivered batch stays queued for the next flush",
        )

    def test_payload_carries_only_the_expected_top_level_fields(self) -> None:
        config = armed_config()
        telemetry.record(config, "app_started", {"app_version": "0.4.124-beta"})
        sent: list = []
        telemetry.flush(config, transport=lambda u, k, p: sent.append(p) or True)
        self.assertEqual(
            set(sent[0]), {"install_id", "events"},
            "no field for hostname, username or anything else to ride along in",
        )


if __name__ == "__main__":
    unittest.main()
