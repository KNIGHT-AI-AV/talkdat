"""0.4.176: no usage report leaves the computer before the person answers (consent before capture).

TEAM KNIGHT's rulings of 2026-10-26/27 under the owner's "safe and fair" order
(BUILD-PLAN-0476.md item 4; the brief for step 1): no usage report of any kind --
first open, first dictation, still in use, day 7 -- leaves the computer until the
person has seen the usage counts choice and answered it. "Don't share" sends
nothing, ever, until they turn the switch on in Settings, Privacy.

An install upgrading from 0.4.175 that never answered (its switch was on by
default, untouched) counts as NOT answered: it sends nothing until it is asked
and says yes. An install whose person turned the switch off keeps it off and is
not asked.

The config keys: privacy.share_usage_counts holds the answer (off until a yes)
and privacy.usage_counts_asked says the person answered, either way.

What this file defends:

  THE GATE: official_build.share_usage_counts is true only after a yes, so
  activation_api_base is "" for every report until then.

  THE UPGRADE: what a config written before 0.4.176 means, decided once at load.

  THE LAUNCH REPORTS WAIT: first open and still in use go at launch only after a
  yes, or as soon as a yes is saved during the session, once.

  A FIRST DICTATION BEFORE THE ANSWER waits too, and goes after a yes.
"""
from __future__ import annotations

import contextlib
import copy
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from knight_flow import activation_metrics, official_build

ROOT = Path(__file__).resolve().parents[1]
KNIGHT = official_build.KNIGHT_API_BASE


@contextlib.contextmanager
def build(official: bool, **env: str):
    clean = {k: v for k, v in os.environ.items() if not k.startswith("TALKDAT_")}
    clean.update(env)
    with mock.patch.object(official_build, "OFFICIAL", official), \
            mock.patch.object(official_build, "BAKED_API_BASE", ""), \
            mock.patch.object(official_build, "BAKED_UPDATE_REPOSITORY", ""), \
            mock.patch.dict(os.environ, clean, clear=True):
        yield


@contextlib.contextmanager
def captured_reports():
    """Every report the senders would POST, run on this thread, nothing on the network."""
    sent: list[dict] = []

    class Answered:
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def read(self): return b""

    def fake_urlopen(request, timeout=0):
        sent.append(json.loads(request.data.decode("utf-8")))
        return Answered()

    def run_now(target, name=None, daemon=None):
        thread = mock.Mock()
        thread.start = target
        return thread

    with mock.patch.object(activation_metrics.threading, "Thread", side_effect=run_now), \
            mock.patch.object(activation_metrics.urllib.request, "urlopen", fake_urlopen):
        yield sent


def stage(report: dict) -> str:
    return report.get("stage") or ("first dictation" if "secondsToFirstDictation" in report else "?")


class TheGateOpensOnlyOnAYesTests(unittest.TestCase):
    def test_nothing_is_sent_before_an_answer(self) -> None:
        with build(True):
            for config in ({}, {"privacy": {}}, {"privacy": {"local_only": True}},
                           # 0.4.175's default, never touched: on, and never an answer.
                           {"privacy": {"share_usage_counts": True}},
                           {"privacy": {"share_usage_counts": True, "usage_counts_asked": False}},
                           {"privacy": {"share_usage_counts": True, "usage_counts_asked": "yes"}}):
                with self.subTest(config=config):
                    self.assertFalse(official_build.usage_counts_answered(config))
                    self.assertFalse(official_build.share_usage_counts(config))
                    self.assertEqual(official_build.activation_api_base(config), "")
                    self.assertTrue(official_build.usage_counts_question_open(config))

    def test_a_yes_opens_it_and_a_no_keeps_it_shut(self) -> None:
        with build(True):
            config = {"privacy": {"local_only": True}}
            official_build.record_usage_counts_answer(config, True)
            self.assertEqual(config["privacy"],
                             {"local_only": True, "share_usage_counts": True, "usage_counts_asked": True})
            self.assertEqual(official_build.activation_api_base(config), KNIGHT)
            self.assertFalse(official_build.usage_counts_question_open(config))
            official_build.record_usage_counts_answer(config, False)
            self.assertEqual(official_build.activation_api_base(config), "")
            self.assertFalse(official_build.usage_counts_question_open(config), "a no is an answer too")
            broken = {"privacy": "garbage"}
            official_build.record_usage_counts_answer(broken, True)
            self.assertEqual(broken["privacy"], {"share_usage_counts": True, "usage_counts_asked": True})

    def test_only_a_real_yes_counts_once_answered(self) -> None:
        with build(True):
            for value, on in ((True, True), (1, True), ("yes", True), (" On ", True),
                              (False, False), (0, False), ("off", False), (None, False), ([], False), ({}, False)):
                config = {"privacy": {"share_usage_counts": value, "usage_counts_asked": True}}
                with self.subTest(value=value):
                    self.assertIs(official_build.share_usage_counts(config), on)

    def test_a_source_build_and_the_kill_switch_never_ask(self) -> None:
        for official, env in ((False, {}), (True, {"TALKDAT_NO_PHONE_HOME": "1"})):
            with build(official, **env), self.subTest(official=official, env=env):
                self.assertFalse(official_build.usage_counts_question_open({}))
                yes = {"privacy": {"share_usage_counts": True, "usage_counts_asked": True}}
                self.assertEqual(official_build.activation_api_base(yes), "")

    def test_the_default_config_has_not_answered(self) -> None:
        from knight_flow.config import DEFAULT_CONFIG

        self.assertIs(DEFAULT_CONFIG["privacy"]["share_usage_counts"], False)
        self.assertIs(DEFAULT_CONFIG["privacy"]["usage_counts_asked"], False)


class AnUpgradeFrom0475Tests(unittest.TestCase):
    """What a config.json written before 0.4.176 means, read once at load."""

    def setUp(self) -> None:
        self._old_home = os.environ.get("TALK_DAT_HOME")
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)
        os.environ["TALK_DAT_HOME"] = self._tmp.name

    def tearDown(self) -> None:
        if self._old_home is None:
            os.environ.pop("TALK_DAT_HOME", None)
        else:
            os.environ["TALK_DAT_HOME"] = self._old_home
        self._tmp.cleanup()

    def load(self, on_disk: dict | None) -> dict:
        from knight_flow.config import config_path, load_config

        if on_disk is not None:
            config_path().write_text(json.dumps(on_disk), encoding="utf-8")
        return load_config(self.home)

    def test_the_untouched_default_on_is_not_an_answer(self) -> None:
        config = self.load({"privacy": {"share_usage_counts": True, "local_only": True},
                            "updates": {"current_version": "0.4.175-beta"}})
        self.assertIs(config["privacy"]["usage_counts_asked"], False)
        self.assertIs(config["privacy"]["share_usage_counts"], False, "the switch reads off until a yes")
        with build(True):
            self.assertEqual(official_build.activation_api_base(config), "")
            self.assertTrue(official_build.usage_counts_question_open(config))

    def test_a_missing_privacy_section_is_not_an_answer(self) -> None:
        # 0.4.175's Reset of the app settings removed the section, which read as on.
        config = self.load({"ui": {"theme": "dark"}})
        self.assertIs(config["privacy"]["usage_counts_asked"], False)
        self.assertIs(config["privacy"]["share_usage_counts"], False)

    def test_a_switch_turned_off_stays_off_and_is_not_asked(self) -> None:
        for value in (False, 0, "off"):
            with self.subTest(value=value):
                config = self.load({"privacy": {"share_usage_counts": value}})
                self.assertIs(config["privacy"]["usage_counts_asked"], True)
                self.assertIs(config["privacy"]["share_usage_counts"], False)
                with build(True):
                    self.assertFalse(official_build.usage_counts_question_open(config))
                    self.assertEqual(official_build.activation_api_base(config), "")

    def test_an_answer_saved_by_0476_is_kept(self) -> None:
        for share in (True, False):
            with self.subTest(share=share):
                config = self.load({"privacy": {"share_usage_counts": share, "usage_counts_asked": True}})
                self.assertIs(config["privacy"]["usage_counts_asked"], True)
                self.assertIs(config["privacy"]["share_usage_counts"], share)
                with build(True):
                    self.assertEqual(official_build.activation_api_base(config), KNIGHT if share else "")

    def test_a_new_install_has_not_answered(self) -> None:
        config = self.load(None)
        self.assertIs(config["privacy"]["usage_counts_asked"], False)
        self.assertIs(config["privacy"]["share_usage_counts"], False)
        from knight_flow.config import config_path

        written = json.loads(config_path().read_text(encoding="utf-8"))
        self.assertIs(written["privacy"]["usage_counts_asked"], False, "a new file is not read as 0.4.175's")

    def test_an_unanswered_switch_never_reads_on(self) -> None:
        config = self.load({"privacy": {"share_usage_counts": True, "usage_counts_asked": False}})
        self.assertIs(config["privacy"]["share_usage_counts"], False)


def app_with(config: dict):
    from knight_flow.app import TalkDatApp

    app = object.__new__(TalkDatApp)
    app.config = config
    return app


def launched(answer: bool | None) -> dict:
    now = int(time.time())
    config = {"metrics": {"install_id": "c" * 32, "first_run_at": now - 30}, "privacy": {"local_only": True}}
    if answer is not None:
        official_build.record_usage_counts_answer(config, answer)
    return config


class TheLaunchReportsWaitTests(unittest.TestCase):
    def send(self, app) -> list[dict]:
        with build(True), captured_reports() as sent, \
                mock.patch("knight_flow.app.save_config", lambda _config: True), \
                mock.patch.object(sys, "frozen", True, create=True):
            app.send_usage_reports()
        return sent

    def test_an_unanswered_install_sends_neither_launch_report(self) -> None:
        self.assertEqual(self.send(app_with(launched(None))), [])

    def test_a_no_sends_nothing(self) -> None:
        self.assertEqual(self.send(app_with(launched(False))), [])

    def test_a_yes_sends_both_and_only_once_a_session(self) -> None:
        app = app_with(launched(True))
        self.assertEqual([stage(report) for report in self.send(app)], ["install", "heartbeat"])
        self.assertEqual(self.send(app), [], "a second save in the same session sends nothing more")

    def test_a_yes_saved_during_the_session_sends_them_then(self) -> None:
        app = app_with(launched(None))
        self.assertEqual(self.send(app), [], "the launch waited")
        official_build.record_usage_counts_answer(app.config, True)
        self.assertEqual([stage(report) for report in self.send(app)], ["install", "heartbeat"])

    def test_without_an_install_id_it_waits_for_the_launch_to_make_one(self) -> None:
        config = launched(True)
        del config["metrics"]["install_id"]
        app = app_with(config)
        self.assertEqual(self.send(app), [])
        config["metrics"]["install_id"] = "d" * 32
        self.assertEqual([stage(report) for report in self.send(app)], ["install", "heartbeat"])

    def test_the_launch_and_every_settings_save_ask_for_them(self) -> None:
        import ast

        source = (ROOT / "knight_flow" / "app.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        app_class = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "TalkDatApp")
        methods = {node.name: ast.get_source_segment(source, node) for node in app_class.body
                   if isinstance(node, ast.FunctionDef)}
        self.assertIn("self.send_usage_reports()", methods["run"])
        self.assertNotIn("report_install(", methods["run"], "the launch no longer sends on its own")
        self.assertNotIn("report_heartbeat(", methods["run"])
        self.assertIn("self.send_usage_reports()", methods["save_settings"])
        self.assertIn("_metrics_api = activation_api_base(self.config)", methods["send_usage_reports"])


class AFirstDictationBeforeTheAnswerWaitsTests(unittest.TestCase):
    def test_it_is_kept_until_a_yes_and_sent_after(self) -> None:
        config = launched(None)
        with build(True), captured_reports() as sent, mock.patch.object(sys, "frozen", True, create=True):
            activation_metrics.record_first_dictation(config, lambda _c: None,
                                                      official_build.activation_api_base(config))
            self.assertEqual(sent, [], "nothing before the answer")
            self.assertIn("first_dictation_at", config["metrics"], "kept on this computer to send later")
            official_build.record_usage_counts_answer(config, True)
            activation_metrics.record_first_dictation(config, lambda _c: None,
                                                      official_build.activation_api_base(config))
        self.assertEqual([stage(report) for report in sent], ["first dictation"])

    def test_a_no_never_sends_it(self) -> None:
        config = launched(False)
        with build(True), captured_reports() as sent:
            for _ in range(2):
                activation_metrics.record_first_dictation(config, lambda _c: None,
                                                          official_build.activation_api_base(config))
        self.assertEqual(sent, [])


class ResetKeepsTheAnswerTests(unittest.TestCase):
    """0.4.176 item 5 (TEAM KNIGHT's decision): Reset never turns the counts back
    on silently, because Reset keeps the person's answer. In 0.4.175 Reset's App
    settings removed the privacy section, and a missing section read as on."""

    ANSWER = ("share_usage_counts", "usage_counts_asked")

    def answered(self, share: bool) -> dict:
        config = {"privacy": {"local_only": False, "save_history": False, "redact_pii": True},
                  "metrics": {"install_id": "e" * 32}, "ui": {"theme": "light"}}
        official_build.record_usage_counts_answer(config, share)
        return config

    def test_app_settings_keep_the_answer_and_reset_the_rest_of_privacy(self) -> None:
        from knight_flow.reset import CATEGORY_BY_KEY, prune_config

        for share in (True, False):
            with self.subTest(share=share):
                config = self.answered(share)
                pruned = prune_config(config, CATEGORY_BY_KEY["settings"].config_keys)
                self.assertEqual(pruned["privacy"], {"share_usage_counts": share, "usage_counts_asked": True})
                self.assertNotIn("ui", pruned)
                self.assertEqual(pruned["metrics"], config["metrics"], "the install ID is never pruned")
                self.assertEqual(config["privacy"]["local_only"], False, "the original is left alone")

    def test_every_preset_keeps_it(self) -> None:
        from knight_flow.reset import CATEGORY_BY_KEY, PRESETS, prune_config

        for preset, categories in PRESETS.items():
            keys = tuple(key for category in categories for key in CATEGORY_BY_KEY[category].config_keys)
            with self.subTest(preset=preset):
                pruned = prune_config(self.answered(True), keys)
                self.assertEqual({k: pruned["privacy"][k] for k in self.ANSWER},
                                 {"share_usage_counts": True, "usage_counts_asked": True})

    def test_an_unanswered_install_stays_unanswered(self) -> None:
        from knight_flow.reset import CATEGORY_BY_KEY, prune_config

        config = {"privacy": {"share_usage_counts": False, "usage_counts_asked": False}}
        pruned = prune_config(config, CATEGORY_BY_KEY["settings"].config_keys)
        with build(True):
            self.assertTrue(official_build.usage_counts_question_open(pruned))
            self.assertEqual(official_build.activation_api_base(pruned), "")
        self.assertEqual(prune_config({}, CATEGORY_BY_KEY["settings"].config_keys), {})

    def test_a_real_reset_of_app_settings_keeps_it_through_the_restart(self) -> None:
        from knight_flow import reset
        from knight_flow.config import app_dir, config_path, load_config, save_config

        old_home = os.environ.get("TALK_DAT_HOME")
        with tempfile.TemporaryDirectory() as home:
            os.environ["TALK_DAT_HOME"] = home
            try:
                config = load_config(Path(home))
                official_build.record_usage_counts_answer(config, True)
                config["privacy"]["local_only"] = False
                save_config(config)
                outcome = reset.perform(
                    ["settings"], app_dir(),
                    read_config=lambda: json.loads(config_path().read_text(encoding="utf-8")),
                    write_config=lambda pruned, forget: save_config(pruned, forget_sections=forget))
                self.assertIn("privacy", outcome["removed"])
                restarted = load_config(Path(home))
            finally:
                if old_home is None:
                    os.environ.pop("TALK_DAT_HOME", None)
                else:
                    os.environ["TALK_DAT_HOME"] = old_home
        self.assertIs(restarted["privacy"]["local_only"], True, "the rest of privacy is back to its default")
        self.assertIs(restarted["privacy"]["usage_counts_asked"], True)
        self.assertIs(restarted["privacy"]["share_usage_counts"], True)
        with build(True):
            self.assertFalse(official_build.usage_counts_question_open(restarted), "not asked again")

    def test_the_reset_page_says_the_answer_stays(self) -> None:
        from knight_flow.reset import CATEGORY_BY_KEY

        self.assertIn("except your usage counts choice", CATEGORY_BY_KEY["settings"].consequence)


if __name__ == "__main__":
    unittest.main()
