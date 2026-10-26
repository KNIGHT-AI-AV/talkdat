"""The ten increments wired into the app: T3 a take's words, T4 the clipboard
learner, T7 a locked take and its receipt. Lightweight app objects (no Tk, no
device); the take-level flows run on fakes.
"""
from __future__ import annotations

import unittest

from knight_flow import net_fence
from knight_flow.app import TalkDatApp
from knight_flow.word_scopes import active_project, apply_word_scope, new_project
from tests.test_app_session_lifecycle import _app


class ALockedTake(unittest.TestCase):
    def setUp(self) -> None:
        net_fence.set_local_only(False)
        self.addCleanup(net_fence.set_local_only, False)
        self.app = _app(object())
        self.app.config = {"privacy": {"local_only": False}}
        self.app._take_view = None
        self.addCleanup(TalkDatApp._end_take_view, self.app)

    def test_a_profile_marked_local_only_locks_the_take(self) -> None:
        self.assertTrue(TalkDatApp._lock_for_this_take(self.app, {"match": "chart", "local_only": True}))
        self.assertFalse(TalkDatApp._lock_for_this_take(self.app, {"match": "slack"}))
        self.assertFalse(TalkDatApp._lock_for_this_take(self.app, {"local_only": "yes"}))

    def test_the_next_take_request_is_used_once(self) -> None:
        self.app.config["privacy"]["lock_next_take"] = True
        self.assertTrue(TalkDatApp._lock_for_this_take(self.app, {}))
        self.assertFalse(TalkDatApp._lock_for_this_take(self.app, {}))
        self.assertFalse(self.app.config["privacy"]["lock_next_take"])

    def test_the_receipt_records_refused_attempts_and_closes_the_view(self) -> None:
        token = object()
        self.app._take_view = (token, net_fence.begin_take(locked=True), True)
        with self.assertRaises(net_fence.LocalOnlyBlocked):
            net_fence.assert_cloud_allowed("https://api.deepgram.com/v1/listen", "Speech transcription")
        config = {"privacy": {"local_only": True}, "_take_locked": True}
        receipt = TalkDatApp._take_receipt(self.app, token, config, "rules")
        self.assertTrue(receipt["locked"])
        self.assertEqual(receipt["formatter_route"], "rules")
        self.assertEqual([item["host"] for item in receipt["remote_attempts"]], ["api.deepgram.com"])
        self.assertTrue(all(item["refused"] for item in receipt["remote_attempts"]))
        self.assertIsNone(self.app._take_view)
        self.assertFalse(net_fence.take_locked())

    def test_another_takes_receipt_is_not_written(self) -> None:
        token = object()
        self.app._take_view = (token, net_fence.begin_take(locked=True), True)
        self.assertIsNone(TalkDatApp._take_receipt(self.app, object(), {}, "rules"))
        self.assertTrue(net_fence.take_locked(), "the view must stay with its own take")

    def test_a_new_take_ends_the_previous_view(self) -> None:
        self.app._take_view = (object(), net_fence.begin_take(locked=True), True)
        TalkDatApp._end_take_view(self.app)
        self.assertFalse(net_fence.take_locked())
        TalkDatApp._end_take_view(self.app)  # nothing open: harmless


class ATakesWords(unittest.TestCase):
    def test_the_active_project_reaches_the_take_config(self) -> None:
        config = {"dictionary": {"terms": [{"text": "Sean", "sounds_like": ["shawn"]}]}}
        project = new_project(config, "Film")
        project["terms"] = [{"text": "Shawn", "sounds_like": ["sean"]}]
        config["dictionary"]["active_project"] = project["id"]
        take = apply_word_scope(config, active_project(config, {}))
        self.assertEqual([term["text"] for term in take["dictionary"]["terms"]], ["Shawn"])
        self.assertEqual(take["_word_scope"]["project"], "film")

    def test_the_learning_project_follows_the_active_one(self) -> None:
        app = _app(object())
        app.config = {"dictionary": {}}
        self.assertEqual(TalkDatApp._learning_project(app), "")
        project = new_project(app.config, "Client")
        app.config["dictionary"]["active_project"] = project["id"]
        self.assertEqual(TalkDatApp._learning_project(app), "client")


class StatsShowsTheMeasuredSaving(unittest.TestCase):
    def setUp(self) -> None:
        import os
        import tempfile

        self._old = os.environ.get("TALK_DAT_HOME")
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["TALK_DAT_HOME"] = self._tmp.name

    def tearDown(self) -> None:
        import os

        if self._old is None:
            os.environ.pop("TALK_DAT_HOME", None)
        else:
            os.environ["TALK_DAT_HOME"] = self._old
        self._tmp.cleanup()

    def test_none_until_there_are_enough_tasks(self) -> None:
        from knight_flow.history import history_stats

        self.assertIsNone(history_stats({"privacy": {}})["minutes_saved_measured"])
        config = {"editing_measure": {"tasks": [{"mode": "typing", "words": 40, "seconds": 60}]}}
        self.assertIsNone(history_stats(config)["minutes_saved_measured"])

    def test_the_measured_saving_beside_the_estimate(self) -> None:
        from knight_flow.history import history_stats

        tasks = ([{"mode": "typing", "words": 40, "seconds": 60.0}] * 3
                 + [{"mode": "dictation", "words": 40, "seconds": 40.0}] * 3)
        stats = history_stats({"editing_measure": {"tasks": tasks}})
        measured = stats["minutes_saved_measured"]
        self.assertEqual(measured["tasks"], 6)
        self.assertAlmostEqual(measured["median_change"], -0.333, places=3)
        self.assertEqual(stats["minutes_saved"], 0)  # the estimate is unchanged: no words dictated yet


class TheSourceIsWiredAsDesigned(unittest.TestCase):
    """Contract checks on the delivery code these increments touch."""

    @classmethod
    def setUpClass(cls) -> None:
        from pathlib import Path

        cls.app_source = (Path(__file__).resolve().parents[1] / "knight_flow" / "app.py").read_text(encoding="utf-8")

    def test_history_keeps_the_meaning_report_and_the_receipt(self) -> None:
        self.assertIn('entry["meaning"] = meaning_report(processed.original, processed.text', self.app_source)
        self.assertIn('entry["receipt"] = take_receipt', self.app_source)
        # The paste's own receipt is read after History; the take's must not replace it.
        self.assertNotIn("receipt = self._take_receipt(", self.app_source.replace("take_receipt = self._take_receipt(", ""))

    def test_every_take_config_is_scoped(self) -> None:
        self.assertIn("session_config = apply_word_scope(session_config, active_project(self.config, profile))",
                      self.app_source)
        self.assertIn("effective_config = _apply_word_scope(effective_config, _active_project(self.config, profile))",
                      self.app_source)

    def test_the_lock_is_applied_last_at_take_start(self) -> None:
        start = self.app_source.index("session_config = apply_word_scope(session_config, active_project")
        lock = self.app_source.index("session_config = lock_take(session_config)", start)
        create = self.app_source.index("session = create_stt_session(", start)
        self.assertLess(lock, create)

    def test_the_learner_quarantines(self) -> None:
        self.assertIn("learn_or_quarantine(captured, self.config, delivered, unsure, project=project)", self.app_source)
        self.assertIn("release_quarantined(word, self.config)", self.app_source)


if __name__ == "__main__":
    unittest.main()
