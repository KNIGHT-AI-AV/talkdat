"""Completed speech can finish during the hold without a second delivery."""
from __future__ import annotations

import threading
import unittest
from concurrent.futures import Future
from unittest.mock import patch

from knight_flow import text_pipeline


CONFIG = {"cleanup": {"smart_format": True, "format_mode": "ai", "format_intensity": "executive"},
          "privacy": {"local_only": False},
          "transforms": {"llm": {"provider": "ollama", "api_base": "http://127.0.0.1:11434"}}}
PREFIX = ("Please send the completed report to the whole team before the meeting tomorrow morning. "
          "We need everyone to read the final recommendations and bring their questions.")


class ProgressiveFormattingTests(unittest.TestCase):
    def cache(self, formatter=None):
        from knight_flow.progressive_formatting import ProgressiveFormatter
        cache = ProgressiveFormatter(formatter=formatter)
        self.addCleanup(cache.reset)
        return cache

    def test_finished_exact_text_reuses_work_without_waiting(self):
        landed = threading.Event()
        def finish(raw, config):
            landed.set()
            return text_pipeline.ProcessedText(raw, "Prepared final text.")
        cache = self.cache(finish)
        cache.request(PREFIX, CONFIG)
        self.assertTrue(cache.wait_idle(1))
        self.assertTrue(landed.is_set())
        result = cache.take(PREFIX, CONFIG)
        self.assertEqual(result.text, "Prepared final text.")
        self.assertIsNone(cache.take(PREFIX, CONFIG))

    def test_safe_complete_sentence_prefix_and_short_tail_keep_every_word(self):
        cache = self.cache(lambda raw, config: text_pipeline.prepare_dictation(raw, config, local_only=True))
        cache.request(PREFIX, CONFIG)
        self.assertTrue(cache.wait_idle(1))
        result = cache.take(PREFIX + " Please bring the printed agenda.", CONFIG)
        self.assertIsNotNone(result)
        self.assertEqual(result.text, PREFIX + " Please bring the printed agenda.")
        self.assertEqual(result.original, PREFIX + " Please bring the printed agenda.")

    def test_ambiguous_boundary_corrections_and_config_changes_miss(self):
        for tail in (" and the notes", " Scratch all that. Send a short note.",
                     " Actually no, send it next week.", " Second, invite the reviewers."):
            with self.subTest(tail=tail):
                cache = self.cache(lambda raw, config: text_pipeline.ProcessedText(raw, raw))
                cache.request(PREFIX, CONFIG)
                self.assertTrue(cache.wait_idle(1))
                self.assertIsNone(cache.take(PREFIX + tail, CONFIG))
        cache = self.cache(lambda raw, config: text_pipeline.ProcessedText(raw, raw))
        cache.request(PREFIX, CONFIG)
        self.assertTrue(cache.wait_idle(1))
        self.assertIsNone(cache.take(PREFIX, {**CONFIG, "privacy": {"redact_pii": True}}))

    def test_at_most_one_worker_and_one_newest_request(self):
        blocked, release = threading.Event(), threading.Event()
        calls = []
        def finish(raw, config):
            calls.append(raw)
            if len(calls) == 1:
                blocked.set()
                release.wait(1)
            return text_pipeline.ProcessedText(raw, raw)
        cache = self.cache(finish)
        cache.request(PREFIX, CONFIG)
        self.assertTrue(blocked.wait(1))
        for i in range(20):
            cache.request(PREFIX + f" Draft {i}.", CONFIG)
        release.set()
        self.assertTrue(cache.wait_idle(2))
        self.assertEqual(calls, [PREFIX, PREFIX + " Draft 19."])

    def test_reset_discards_an_in_flight_result(self):
        blocked, release = threading.Event(), threading.Event()
        def finish(raw, config):
            blocked.set()
            release.wait(1)
            return text_pipeline.ProcessedText(raw, raw)
        cache = self.cache(finish)
        cache.request(PREFIX, CONFIG)
        self.assertTrue(blocked.wait(1))
        cache.reset()
        release.set()
        self.assertTrue(cache.wait_idle(2))
        self.assertIsNone(cache.take(PREFIX, CONFIG))

    def test_preparation_does_not_run_plugins_or_write_journal(self):
        with patch("knight_flow.text_pipeline.plugin_text_filters") as plugins, \
             patch("knight_flow.format_journal.record_formatting") as journal:
            result = text_pipeline.prepare_dictation(PREFIX, CONFIG, local_only=True)
        self.assertEqual(result.text, PREFIX)
        plugins.assert_not_called()
        journal.assert_not_called()

    def test_cloud_and_dynamic_snippets_never_prefetch(self):
        finish = unittest.mock.Mock()
        cache = self.cache(finish)
        for config in ({**CONFIG, "transforms": {"llm": {"provider": "openai"}}},
                       {**CONFIG, "transforms": {"llm": {"provider": "ollama", "api_base": "https://example.com"}}},
                       {**CONFIG, "snippets": [{"trigger": "clip", "text": "{clipboard}"}]}):
            cache.request(PREFIX, config)
        self.assertTrue(cache.wait_idle(1))
        finish.assert_not_called()

    def test_completed_stt_segments_publish_without_live_captions(self):
        from knight_flow.stt_sessions import BatchSTTSession
        session = BatchSTTSession.__new__(BatchSTTSession)
        session._cancel_event = threading.Event()
        received = []
        session.on_stable_update = received.append
        first, second = Future(), Future()
        first.set_result("The first sentence.")
        session._publish_stable_pieces([first, second])
        self.assertEqual(received, ["The first sentence."])
        second.set_result("The second sentence.")
        session._publish_stable_pieces([first, second])
        self.assertEqual(received[-1], "The first sentence. The second sentence.")
        session._cancel_event.set()
        session._publish_stable_pieces([first, second])
        self.assertEqual(len(received), 2)

    def test_delivery_uses_prepared_work_and_runs_hooks_once(self):
        from tests.test_app_session_lifecycle import _app
        from knight_flow.paste import PasteReceipt
        app = _app(object())
        app.config = CONFIG.copy()
        app._progressive_formatter = self.cache(lambda raw, config: text_pipeline.ProcessedText(raw, raw))
        app._progressive_formatter.request(PREFIX, app.config)
        self.assertTrue(app._progressive_formatter.wait_idle(1))
        app._note_model_format_ms = lambda ms: None
        app.play_landing_sound = lambda: None
        app.add_history = lambda entry: None
        plugin = unittest.mock.Mock(side_effect=lambda text, cfg: text)
        with patch("knight_flow.app.active_profile", return_value={}), \
             patch("knight_flow.app.apply_profile", side_effect=lambda cfg, profile: cfg), \
             patch("knight_flow.app.paste_text_with_receipt", return_value=PasteReceipt(True, "auto", "clipboard", ())) as paste, \
             patch("knight_flow.app.process_dictation") as process, \
             patch("knight_flow.text_pipeline.plugin_text_filters", return_value=[plugin]), \
             patch("knight_flow.format_journal.record_formatting") as journal, \
             patch("knight_flow.app.save_config"), patch("knight_flow.app.threading.Thread"):
            result = app.handle_dictation(PREFIX)
        self.assertEqual(result["text"], PREFIX)
        process.assert_not_called()
        paste.assert_called_once()
        plugin.assert_called_once()
        journal.assert_called_once()
        self.assertEqual(journal.call_args.kwargs["route"], "prepared_rules")


if __name__ == "__main__":
    unittest.main()
