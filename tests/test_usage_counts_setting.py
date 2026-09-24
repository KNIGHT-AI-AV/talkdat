"""Owner decision 2026-09-23: the anonymous usage counts get their own switch.

"Share anonymous usage counts: first open, first dictation, still in use, day
7. Never your audio or text." It is ``privacy.share_usage_counts``, on by
default in an official build and never on in a source build. Local-only privacy
governs what a person dictates (audio, text, their own provider keys) and no
longer decides the counts. TALKDAT_NO_PHONE_HOME=1 still kills everything.
(The switch itself is pinned in tests/test_official_build.py.)

What this file defends:

  ONE SET OF WORDS. Settings > Privacy (web and Tk fallback) and first-run
  setup (web and Tk fallback) show the owner's text, from one constant.

  THE TOGGLE EXISTS ONLY WHERE IT DOES SOMETHING: an official build without
  the kill switch. A source build never offers a switch that cannot matter.

  SETUP MENTIONS IT ONCE: a line and the toggle, no nag.

  DAY 7 IS WHAT THE SETTING SAYS IT IS: sent once, from a delivered
  dictation a week after first open, never from a launch alone, with the same
  anonymous field set as the heartbeat.

  THE DOCS SAY THE SAME: NETWORK.md, TELEMETRY.md, the public README.
"""

from __future__ import annotations

import contextlib
import copy
import json
import os
import re
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

from knight_flow import activation_metrics, official_build
from knight_flow.config import DEFAULT_CONFIG

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "knight_flow" / "web_shell" / "shell_assets"
FIELD_ID = "privacy.share_usage_counts"


@contextlib.contextmanager
def build(official: bool, **env: str):
    clean = {k: v for k, v in os.environ.items() if not k.startswith("TALKDAT_")}
    clean.update(env)
    with mock.patch.object(official_build, "OFFICIAL", official), \
            mock.patch.object(official_build, "BAKED_API_BASE", ""), \
            mock.patch.object(official_build, "BAKED_UPDATE_REPOSITORY", ""), \
            mock.patch.dict(os.environ, clean, clear=True):
        yield


class OneSetOfWordsTests(unittest.TestCase):
    def test_the_line_is_the_label_and_the_detail(self) -> None:
        detail = official_build.USAGE_COUNTS_DETAIL
        self.assertEqual(official_build.USAGE_COUNTS_LINE,
                         f"{official_build.USAGE_COUNTS_LABEL}: {detail[0].lower()}{detail[1:]}")
        self.assertEqual(official_build.USAGE_COUNTS_LINE,
                         "Share anonymous usage counts: first open, first dictation, still in use, day 7. "
                         "Never your audio or text.")

    def test_settings_declares_the_toggle_in_those_words(self) -> None:
        fields = json.loads((ASSETS / "settings-fields.json").read_text(encoding="utf-8"))
        field = next((f for f in fields if f["id"] == FIELD_ID), None)
        self.assertIsNotNone(field, "Settings > Privacy has no usage-counts toggle")
        self.assertEqual(field["type"], "toggle")
        self.assertEqual(field["page"], "privacy")
        self.assertIs(field["default"], True)
        self.assertIs(field["default"], DEFAULT_CONFIG["privacy"]["share_usage_counts"])
        self.assertEqual(field["label"], official_build.USAGE_COUNTS_LABEL)
        self.assertEqual(field["description"], official_build.USAGE_COUNTS_DETAIL)
        self.assertTrue(field.get("official_only"))
        local = next(f for f in fields if f["id"] == "privacy.local_only")
        self.assertNotEqual(local["section"], field["section"], "the two switches are separate settings")

    def test_setup_and_the_tk_fallbacks_use_the_same_words(self) -> None:
        script = (ASSETS / "setup.js").read_text(encoding="utf-8")
        self.assertIn(official_build.USAGE_COUNTS_LABEL, script)
        self.assertIn(official_build.USAGE_COUNTS_DETAIL, script)
        for name in ("overlay.py", "ui/onboarding.py"):
            source = (ROOT / "knight_flow" / name).read_text(encoding="utf-8")
            with self.subTest(module=name):
                self.assertIn("USAGE_COUNTS_LINE", source)
                self.assertIn("usage_counts_available()", source)
                self.assertIn('"share_usage_counts"', source)


class TheSettingsPageTests(unittest.TestCase):
    def backend(self, config):
        from knight_flow.overlay import Overlay
        from knight_flow.web_shell.shell_backend import ShellBackend

        persisted: list = []
        backend = ShellBackend(config, ASSETS, persisted.append, lambda: None,
                               object.__new__(Overlay)._settings_palette)
        return backend, persisted

    @staticmethod
    def privacy_fields(state) -> dict:
        page = next(page for page in state["pages"] if page["id"] == "privacy")
        return {field["id"]: (section["label"], field) for section in page["sections"] for field in section["fields"]}

    def test_an_official_build_shows_the_toggle_on_by_default(self) -> None:
        config = copy.deepcopy(DEFAULT_CONFIG)
        with build(True):
            backend, _ = self.backend(config)
            fields = self.privacy_fields(backend.snapshot())
        self.assertIn(FIELD_ID, fields)
        section, field = fields[FIELD_ID]
        self.assertEqual(section, "Anonymous usage counts")
        self.assertIs(field["value"], True)
        self.assertNotIn("official_only", field)
        self.assertIn("privacy.local_only", fields)

    def test_turning_it_off_saves_the_setting_and_stops_the_counts(self) -> None:
        config = copy.deepcopy(DEFAULT_CONFIG)
        with build(True):
            backend, persisted = self.backend(config)
            backend.handle("save", {"revision": backend.snapshot()["revision"], "changes": {FIELD_ID: False}})
            self.assertIs(config["privacy"]["share_usage_counts"], False)
            self.assertIs(persisted[-1]["privacy"]["share_usage_counts"], False)
            self.assertIs(config["privacy"]["local_only"], True, "the other switch is untouched")
            self.assertEqual(official_build.activation_api_base(config), "")

    def test_a_source_build_and_the_kill_switch_show_no_toggle(self) -> None:
        for official, env in ((False, {}), (True, {"TALKDAT_NO_PHONE_HOME": "1"})):
            with build(official, **env):
                backend, _ = self.backend(copy.deepcopy(DEFAULT_CONFIG))
                fields = self.privacy_fields(backend.snapshot())
                with self.subTest(official=official, env=env):
                    self.assertNotIn(FIELD_ID, fields)
                    self.assertIn("privacy.local_only", fields)
                    with self.assertRaises(ValueError):
                        backend.handle("save", {"revision": backend.snapshot()["revision"],
                                                "changes": {FIELD_ID: False}})


class SetupMentionsItOnceTests(unittest.TestCase):
    def workspace(self, config):
        from knight_flow.web_shell.setup_workspace import SetupWorkspace

        saved: list = []

        def save(value):
            saved.append(copy.deepcopy(value))
            return {"saved": True, "runtime_refreshed": True}

        mic = mock.Mock()
        mic.snapshot.return_value = {"check": {"phase": "idle", "mode": "mic"},
                                     "devices": {"status": "ready", "devices": [], "message": ""}, "selected": ""}
        return SetupWorkspace(config, save, lambda name, value: [] if name == "permissions" else None, mic), saved

    def test_an_official_build_offers_it_on_by_default(self) -> None:
        config = copy.deepcopy(DEFAULT_CONFIG)
        with build(True):
            service, saved = self.workspace(config)
            self.assertEqual(service.snapshot()["usage_counts"], {"on": True})
            result = service.handle({"operation": "usage", "revision": service.revision(), "value": False})
        self.assertEqual(result["usage_counts"], {"on": False})
        self.assertIs(config["privacy"]["share_usage_counts"], False)
        self.assertIs(saved[-1]["privacy"]["share_usage_counts"], False)
        self.assertIn("Settings, Privacy", result["message"])

    def test_only_a_yes_or_no_with_a_current_revision(self) -> None:
        with build(True):
            service, saved = self.workspace(copy.deepcopy(DEFAULT_CONFIG))
            for payload in ({"operation": "usage", "revision": service.revision(), "value": "off"},
                            {"operation": "usage", "revision": service.revision(), "value": 0},
                            {"operation": "usage", "revision": "stale", "value": False},
                            {"operation": "usage", "value": False}):
                with self.subTest(payload=payload), self.assertRaises(ValueError):
                    service.handle(payload)
        self.assertEqual(saved, [])

    def test_a_source_build_never_mentions_it(self) -> None:
        with build(False):
            service, saved = self.workspace(copy.deepcopy(DEFAULT_CONFIG))
            self.assertIsNone(service.snapshot()["usage_counts"])
            with self.assertRaises(ValueError):
                service.handle({"operation": "usage", "revision": service.revision(), "value": False})
        self.assertEqual(saved, [])

    def test_the_page_says_it_once_with_the_toggle_and_no_nag(self) -> None:
        script = (ASSETS / "setup.js").read_text(encoding="utf-8")
        self.assertEqual(script.count(official_build.USAGE_COUNTS_LABEL), 1)
        self.assertEqual(len(re.findall(r"(?<!function )\busageRow\(\)", script)), 1, "rendered in one chapter only")
        self.assertIn('role:"switch"', script[script.index("function usageRow"):])
        self.assertNotIn("confirm(", script)


class DaySevenTests(unittest.TestCase):
    WEEK = activation_metrics.DAY7_SECONDS

    def metrics(self, **extra) -> dict:
        now = int(time.time())
        metrics = {"install_id": "b" * 32, "first_run_at": now - self.WEEK - 60,
                   "first_dictation_at": now - self.WEEK, "install_acked": True, "activation_acked": True}
        metrics.update(extra)
        return {"metrics": metrics}

    def send(self, config, action=None) -> list[dict]:
        captured: list[dict] = []

        class Sent:
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def read(self): return b""

        def fake_urlopen(request, timeout=0):
            captured.append(json.loads(request.data.decode("utf-8")))
            return Sent()

        def run_now(target, name=None, daemon=None):
            thread = mock.Mock()
            thread.start = target
            return thread

        with mock.patch.object(activation_metrics.threading, "Thread", side_effect=run_now), \
                mock.patch.object(activation_metrics.urllib.request, "urlopen", fake_urlopen), \
                mock.patch.object(sys, "frozen", True, create=True), \
                mock.patch.dict(os.environ, {}, clear=True):
            (action or (lambda: activation_metrics.record_first_dictation(config, lambda _c: None,
                                                                          "https://example.test")))()
        return [payload for payload in captured if payload.get("stage") == "day7"]

    def test_a_delivered_dictation_a_week_in_sends_it_once_with_the_heartbeat_field_set(self) -> None:
        config = self.metrics()
        sent = self.send(config)
        self.assertEqual(len(sent), 1)
        self.assertEqual(sorted(sent[0]), ["installId", "internal", "platform", "stage", "version"],
                         "day 7's field set changed; justify the new field before widening it")
        for value in sent[0].values():
            self.assertIsInstance(value, (str, int, bool))
        self.assertIs(config["metrics"]["day7_acked"], True)
        self.assertEqual(self.send(config), [], "confirmed, then never again")

    def test_not_before_seven_full_days(self) -> None:
        now = int(time.time())
        self.assertEqual(self.send(self.metrics(first_run_at=now - self.WEEK + 3600)), [])

    def test_not_before_the_server_has_the_first_open_and_the_first_dictation(self) -> None:
        for missing in ("install_acked", "activation_acked", "first_dictation_at"):
            config = self.metrics()
            del config["metrics"][missing]
            with self.subTest(missing=missing):
                self.assertEqual(self.send(config, lambda: activation_metrics.report_day7(
                    config, lambda _c: None, "https://example.test")), [])

    def test_the_first_dictation_itself_is_not_day_seven(self) -> None:
        config = self.metrics()
        del config["metrics"]["first_dictation_at"]
        self.assertEqual(self.send(config), [])

    def test_a_launch_alone_never_sends_it(self) -> None:
        config = self.metrics()

        def launch():
            activation_metrics.stamp_first_run(config, lambda _c: None)
            activation_metrics.report_install(config, lambda _c: None, "https://example.test")
            activation_metrics.report_heartbeat(config, lambda _c: None, "https://example.test")

        self.assertEqual(self.send(config, launch), [])
        app = (ROOT / "knight_flow" / "app.py").read_text(encoding="utf-8")
        self.assertNotIn("report_day7", app, "day 7 rides the delivered-dictation path only")

    def test_a_refusal_is_retried_at_most_once_a_day(self) -> None:
        config = self.metrics()
        attempts: list[int] = []

        def refuse(request, timeout=0):
            attempts.append(1)
            raise OSError("409 day7_not_eligible")

        def run_now(target, name=None, daemon=None):
            thread = mock.Mock()
            thread.start = target
            return thread

        with mock.patch.object(activation_metrics.threading, "Thread", side_effect=run_now), \
                mock.patch.object(activation_metrics.urllib.request, "urlopen", refuse):
            for _ in range(3):
                activation_metrics.report_day7(config, lambda _c: None, "https://example.test")
            self.assertEqual(len(attempts), 1)
            config["metrics"]["last_day7_attempt_at"] -= activation_metrics.DAY7_RETRY_SECONDS + 1
            activation_metrics.report_day7(config, lambda _c: None, "https://example.test")
        self.assertEqual(len(attempts), 2)
        self.assertNotIn("day7_acked", config["metrics"])

    def test_off_when_the_switch_is_off(self) -> None:
        config = self.metrics()
        config["privacy"] = {"share_usage_counts": False}
        with build(True):
            api_base = official_build.activation_api_base(config)
        self.assertEqual(api_base, "")
        self.assertEqual(self.send(config, lambda: activation_metrics.record_first_dictation(
            config, lambda _c: None, api_base)), [])


class TheDocsSayTheSameTests(unittest.TestCase):
    def test_network_telemetry_and_readme(self) -> None:
        # The public README lives at open_source/README.md in the private repo and
        # becomes README.md in the open-source export, so read whichever exists.
        readme = "open_source/README.md" if (ROOT / "open_source" / "README.md").is_file() else "README.md"
        for name in ("docs/NETWORK.md", "docs/TELEMETRY.md", readme):
            text = (ROOT / name).read_text(encoding="utf-8")
            with self.subTest(doc=name):
                self.assertIn("Share anonymous usage counts", text)
                self.assertNotIn("never while Local-only privacy is on", text)
                self.assertNotIn("only with Local-only privacy off", text)
                self.assertNotIn("only when Local-only privacy is turned off", text)
        telemetry = (ROOT / "docs" / "TELEMETRY.md").read_text(encoding="utf-8")
        for stage in ("first open", "first dictation", "still in use", "day 7"):
            self.assertIn(stage, telemetry)


if __name__ == "__main__":
    unittest.main()
