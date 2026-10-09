"""Pure contracts at the mode/validator/local-transport boundaries.

The HTTP responses and clock are synthetic; these are not model/audio acceptance.
"""
import copy
from contextlib import nullcontext
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
import urllib.error
from unittest.mock import Mock, patch

from knight_flow import formatting, llm
from knight_flow.config import DEFAULT_CONFIG
from knight_flow.local_finish import LOCAL_CHILL_MODEL
from knight_flow.text_pipeline import process_dictation

BASE = "http://127.0.0.1:11434"


def local_config(intensity="standard"):
    config = copy.deepcopy(DEFAULT_CONFIG)
    config["cleanup"]["format_intensity"] = intensity
    config["transforms"]["llm"].update(provider="ollama", model=LOCAL_CHILL_MODEL, api_base=BASE)
    return config


class FinishSemanticsTests(unittest.TestCase):
    def test_actual_mode_choice_survives_an_isolated_save_and_reload(self):
        from knight_flow import app, config as settings
        from tests.test_config import MemoryCredentialStore
        for mode in ("executive", "standard"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory, \
                 patch.dict(os.environ, {"TALK_DAT_HOME": directory}), \
                 patch("knight_flow.credentials.credential_store", return_value=MemoryCredentialStore()):
                chosen = local_config()
                fake = SimpleNamespace(config=chosen, overlay=SimpleNamespace(set_state=Mock()))
                fake.save_settings = lambda: settings.save_config(chosen)
                app.TalkDatApp.choose_finish(fake, mode)
                reloaded = settings.load_config(Path(directory))
                self.assertEqual(reloaded["cleanup"]["format_intensity"], mode)
                self.assertTrue(reloaded["cleanup"]["intensity_default_migrated"])

    def test_corporate_prefix_reuse_does_not_attach_an_unpolished_rules_tail(self):
        from knight_flow.progressive_formatting import ProgressiveFormatter, _key
        from knight_flow.text_pipeline import ProcessedText
        source = "Please send the completed report before the meeting tomorrow morning."
        suffix = "We're gonna need the report by Friday."
        for mode in ("standard", "executive"):
            config = local_config(mode)
            cache = ProgressiveFormatter()
            cache._ready = (source, _key(config), ProcessedText(source, source, route="local_model"))
            result = cache.take(source + " " + suffix, config)
            if mode == "executive":
                self.assertIsNone(result, "Corporate must finish the new tail through its model contract")
            else:
                self.assertIsNotNone(result)
                self.assertIn(suffix, result.text)

    def test_a_mode_switch_invalidates_an_existing_progressive_result(self):
        from knight_flow.progressive_formatting import ProgressiveFormatter, _key
        from knight_flow.text_pipeline import ProcessedText
        source = "We need the report before the meeting tomorrow morning."
        config = local_config("standard")
        cache = ProgressiveFormatter()
        cache._ready = (source, _key(config), ProcessedText(source, source, route="local_model"))
        config["cleanup"]["format_intensity"] = "executive"
        self.assertIsNone(cache.take(source, config))

    def test_fallback_feedback_names_the_actual_delivered_style(self):
        from knight_flow import app
        feedback = getattr(app, "local_finish_feedback", lambda code: ("error", "", code))
        state, title, advice = feedback("polish_safety_fallback")
        self.assertEqual(state, "captured")
        self.assertIn("Chill", title)
        self.assertNotIn("rules", title.lower())
        self.assertNotIn("polish_safety_fallback", advice)
        for reason in ("preparing", "model_unavailable", "timeout", "budget_exceeded", "invalid_response", "model_safety_fallback"):
            state, title, advice = feedback(reason)
            self.assertEqual(state, "error")
            self.assertIn("built-in rules", title)
            self.assertNotEqual(advice, reason)

    def test_emphasis_keeps_every_repetition_in_both_modes(self):
        for source, candidate in (("No, no, no!", "No, no!"),
                                  ("Very, very, very good.", "Very, very good."),
                                  ("Bye bye, bye bye.", "Bye bye.")):
            for executive in (False, True):
                with self.subTest(source=source, executive=executive):
                    self.assertEqual(formatting.formatter_rejection_reason(
                        source, candidate, preserve_meaning=not executive,
                        rewrite_mode=executive, transcript=source), "repetition_dropped")

    def test_unchanged_emphasis_and_function_word_stutters_are_allowed(self):
        for source, candidate in (("No no no!", "No, no, no!"),
                                  ("Very very good.", "Very, very good."),
                                  ("We we need to send the report.", "We need to send the report.")):
            self.assertEqual(formatting.formatter_rejection_reason(source, candidate), "")

    def test_corporate_retry_retains_the_reason_and_reports_casual_delivery(self):
        source = "We should probably send the report by Friday."
        bad = "We must send the report by Friday."
        reason = formatting.formatter_rejection_reason(
            source, bad, preserve_meaning=False, rewrite_mode=True, transcript=source)
        self.assertTrue(reason)
        with patch.object(formatting, "llm_configured", return_value=True), \
             patch.object(formatting, "resolved_llm_provider", return_value="ollama"), \
             patch.object(formatting, "local_finish", side_effect=[bad, source]):
            processed = process_dictation(source, local_config("executive"))
        self.assertEqual(processed.text, source)
        self.assertEqual(processed.route, "local_model_chill_after_rejection")
        self.assertEqual(processed.rejection, reason)
        self.assertEqual(formatting.take_local_finish_notice(), "polish_safety_fallback")

    def test_saved_mode_reaches_distinct_local_contracts_without_changing_config(self):
        source = "So basically we're gonna need the report by Friday."
        answers = {False: source, True: "We'll need the report by Friday."}
        for intensity, executive in (("standard", False), ("executive", True)):
            config = local_config(intensity)
            before = copy.deepcopy(config)
            with patch.object(formatting, "llm_configured", return_value=True), \
                 patch.object(formatting, "resolved_llm_provider", return_value="ollama"), \
                 patch.object(formatting, "local_finish", return_value=answers[executive]) as finish:
                processed = process_dictation(source, config)
            self.assertEqual(processed.text, answers[executive])
            self.assertEqual(processed.route, "local_model")
            self.assertEqual(finish.call_args.kwargs["executive"], executive)
            self.assertEqual(config, before)


class LocalDeliveryBudgetTests(unittest.TestCase):
    def setUp(self):
        self.old_speed = dict(llm._LOCAL_SPEED)
        self.old_refused = dict(llm._LOCAL_REFUSED)
        llm._LOCAL_SPEED.clear()
        llm._LOCAL_REFUSED.clear()
        self.addCleanup(self.restore)
        self.clock = Mock(return_value=10.0)
        for target, kwargs in (("local_finish_target", {"return_value": (BASE, LOCAL_CHILL_MODEL)}),
                               ("_ollama_prepare_pending", {"return_value": False}),
                               ("_ollama_ready", {"return_value": True}),
                               ("keep_local_finisher_resident", {})):
            patcher = patch.object(llm, target, **kwargs)
            setattr(self, target, patcher.start())
            self.addCleanup(patcher.stop)
        patcher = patch.object(llm.time, "perf_counter", self.clock)
        patcher.start()
        self.addCleanup(patcher.stop)

    def restore(self):
        llm._LOCAL_SPEED.clear()
        llm._LOCAL_SPEED.update(self.old_speed)
        llm._LOCAL_REFUSED.clear()
        llm._LOCAL_REFUSED.update(self.old_refused)

    def finish(self):
        return llm.local_finish("We need the signed report by Friday.", local_config(),
                                executive=False, budget_seconds=1.2)

    def test_schema_retry_uses_only_the_remaining_budget(self):
        def first(*args, **kwargs):
            self.clock.return_value = 10.9
            raise urllib.error.HTTPError(BASE, 422, "schema unsupported", {}, None)
        with patch.object(llm, "_ollama_chat") as chat:
            chat.side_effect = lambda *a, **kw: first(*a, **kw) if chat.call_count == 1 else {"message": {"content": '{"text":"We need the signed report by Friday."}'}}
            self.assertEqual(self.finish(), "We need the signed report by Friday.")
        self.assertLessEqual(chat.call_args.kwargs["timeout"], 0.31)
        self.assertEqual(chat.call_count, 2)

    def test_an_exhausted_budget_never_starts_a_second_model_request(self):
        def exhausted(*args, **kwargs):
            self.clock.return_value = 12.0
            raise urllib.error.HTTPError(BASE, 422, "schema unsupported", {}, None)
        with patch.object(llm, "_ollama_chat", side_effect=exhausted) as chat:
            self.assertIsNone(self.finish())
        self.assertEqual(chat.call_count, 1)
        self.assertEqual(getattr(llm, "last_local_finish_reason", lambda: "")(), "budget_exceeded")

    def test_take_specific_failures_have_a_reason_without_claiming_slow_hardware(self):
        for code in ("preparing", "model_unavailable", "timeout", "invalid_response"):
            with self.subTest(code=code):
                self._ollama_prepare_pending.return_value = code == "preparing"
                self._ollama_ready.return_value = code != "model_unavailable"
                kwargs = {"side_effect": TimeoutError()} if code == "timeout" else {"return_value": {"message": {"content": ""}}}
                logs = self.assertLogs(llm.log, level="WARNING") if code == "timeout" else nullcontext()
                with patch.object(llm, "_ollama_chat", **kwargs), logs:
                    self.assertIsNone(self.finish())
                self.assertEqual(getattr(llm, "last_local_finish_reason", lambda: "")(), code)
                self.assertEqual(llm._LOCAL_REFUSED, {})


if __name__ == "__main__":
    unittest.main()
