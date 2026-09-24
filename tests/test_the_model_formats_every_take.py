"""2026-09-22: the model formats every non-trivial take, and stays loaded to do it.

The owner, repeated since 09-03 and again on 09-22: "I'm not seeing the genius
formatting". Measured on his PC the same night: 33 of 64 journalled takes were
rules-only by design, 18 more were rules because the model was unavailable
(estimates of 1.4-1.9 s against a flat 1.2 s budget, then cold-load timeouts
with nothing resident in Ollama), and 2 good rewrites were refused. These tests
pin the contract that replaced that: residency, a scaled budget, a FORMAT vs
FINISH prompt, a validator that names every refusal, and deterministic rules
for the probe gaps so a machine without a model improves too.
"""
from __future__ import annotations

import inspect
import json
import os
import tempfile
import threading
import unittest
import urllib.error
from pathlib import Path
from unittest import mock
from unittest.mock import patch

from knight_flow import formatting, llm, local_stt
from knight_flow.formatting import (
    EXECUTIVE_ADDENDUM,
    formatter_rejection_reason,
    last_rejection_reason,
    resolve_value_corrections,
    _valid_formatter_output,
)
from knight_flow.local_finish import (
    LOCAL_CHILL_MODEL,
    LOCAL_FINISH_SYSTEM,
    LOCAL_GPU_MODEL,
    MachineSpeed,
    build_local_request,
    predicted_finish_ms,
    relevant_vocabulary,
)
from knight_flow.text_pipeline import process_dictation
from tests.parity_battery import local_config

BASE = "http://127.0.0.1:11434"
GPU = MachineSpeed(prefill_tps=3200.0, generation_tps=120.0, on_gpu=True)


def rules(spoken: str) -> str:
    return process_dictation(spoken, local_config(), local_only=True).text


class TheModelStaysResidentTests(unittest.TestCase):
    def setUp(self) -> None:
        llm._RESIDENCY_CHECKED.clear()
        llm._RESIDENCY_IN_FLIGHT.clear()
        self.addCleanup(llm._RESIDENCY_CHECKED.clear)

    def run_keeper(self, *, loaded, force=True) -> mock.Mock:
        warm = mock.Mock()
        config = local_config(LOCAL_CHILL_MODEL)
        with patch.object(llm, "local_finish_target", return_value=(BASE, LOCAL_CHILL_MODEL)), \
             patch.object(llm, "_ollama_loaded_on_gpu", return_value=loaded), \
             patch.object(llm, "_ollama_ready", return_value=True), \
             patch.object(llm, "warm_local_finish", warm):
            llm.keep_local_finisher_resident(config, force=force)
            for thread in threading.enumerate():
                if thread.name == "TalkDatFinisherResident":
                    thread.join(5)
        return warm

    def test_every_request_asks_ollama_to_keep_the_model_loaded_without_thinking(self) -> None:
        with patch.object(llm, "_post_json", return_value={"message": {"content": "{}"}}) as post:
            llm._ollama_chat("s", "u", api_base=BASE, model=LOCAL_GPU_MODEL, timeout=1,
                             num_ctx=8192, num_predict=128)
            llm._complete_ollama("s", "u", api_base=BASE, model=LOCAL_GPU_MODEL, timeout=1)
        for call in post.call_args_list:
            body = call.args[1]
            self.assertEqual(body["keep_alive"], -1)
            self.assertIs(body["think"], False)

    def test_a_model_that_is_not_resident_is_loaded_in_the_background(self) -> None:
        warm = self.run_keeper(loaded=None)
        warm.assert_called_once_with(BASE, LOCAL_CHILL_MODEL)

    def test_a_resident_model_is_left_alone(self) -> None:
        warm = self.run_keeper(loaded=True)
        warm.assert_not_called()

    def test_checks_are_rate_limited_unless_forced(self) -> None:
        self.run_keeper(loaded=None)
        warm = self.run_keeper(loaded=None, force=False)
        warm.assert_not_called()
        warm = self.run_keeper(loaded=None, force=True)
        warm.assert_called_once()

    def test_a_timeout_schedules_a_reload_for_the_next_take(self) -> None:
        config = local_config(LOCAL_CHILL_MODEL)
        with patch.object(llm, "_ollama_ready", return_value=True), \
             patch.object(llm, "_ollama_models", return_value={LOCAL_CHILL_MODEL}), \
             patch.object(llm, "_ollama_chat", side_effect=TimeoutError()), \
             patch.object(llm, "keep_local_finisher_resident") as keeper:
            self.assertIsNone(llm.local_finish("hello there friend", config, executive=False, budget_seconds=1.0))
        keeper.assert_called_once()
        self.assertTrue(keeper.call_args.kwargs["force"])

    def test_a_dictation_start_checks_residency(self) -> None:
        from knight_flow.app import TalkDatApp

        source = inspect.getsource(TalkDatApp.start_session)
        self.assertIn("keep_local_finisher_resident(self.config)", source)
        self.assertLess(source.index("keep_local_finisher_resident"), source.index("_scribe_busy"))


class TheGpuModelFinishesBothFinishesTests(unittest.TestCase):
    def setUp(self) -> None:
        llm._LOCAL_SPEED.clear()
        self.addCleanup(llm._LOCAL_SPEED.clear)

    def target(self, executive: bool) -> str:
        config = {"transforms": {"llm": {"provider": "ollama", "model": LOCAL_CHILL_MODEL, "api_base": BASE}}}
        with patch.object(llm, "_ollama_models", return_value={LOCAL_CHILL_MODEL, LOCAL_GPU_MODEL}):
            return llm.local_finish_target(config, executive=executive)[1]

    def test_chill_and_executive_both_take_the_instruct_model_on_a_gpu(self) -> None:
        llm._LOCAL_SPEED[llm.local_finish_key(BASE, LOCAL_CHILL_MODEL)] = GPU
        self.assertEqual(self.target(False), LOCAL_GPU_MODEL)
        self.assertEqual(self.target(True), LOCAL_GPU_MODEL)
        self.assertIn("instruct", LOCAL_GPU_MODEL)

    def test_a_gpu_model_that_spilled_to_the_cpu_is_not_used(self) -> None:
        llm._LOCAL_SPEED[llm.local_finish_key(BASE, LOCAL_CHILL_MODEL)] = GPU
        llm._LOCAL_SPEED[llm.local_finish_key(BASE, LOCAL_GPU_MODEL)] = MachineSpeed(100.0, 8.0, on_gpu=False)
        self.assertEqual(self.target(False), LOCAL_CHILL_MODEL)

    def test_an_unmeasured_machine_stays_on_the_small_model(self) -> None:
        self.assertEqual(self.target(False), LOCAL_CHILL_MODEL)

    def test_the_prediction_is_charged_for_the_dictation_not_the_vocabulary_line(self) -> None:
        dictation = "word " * 20
        request = build_local_request(dictation, executive=False, vocabulary=["Term"] * 30)
        whole = predicted_finish_ms(GPU, request)
        honest = predicted_finish_ms(GPU, request, answer_tokens=len(dictation) // 4)
        self.assertLess(honest, whole)


class ChillAndExecutiveAreDifferentJobsTests(unittest.TestCase):
    def test_the_local_prompt_separates_format_from_finish(self) -> None:
        for rule in ("Corrections:", "Lists:", "Messages:", "Sentences:"):
            self.assertIn(rule, LOCAL_FINISH_SYSTEM)
        self.assertIn("Chill: format only", LOCAL_FINISH_SYSTEM)
        self.assertIn("Executive: format, then polish lightly", LOCAL_FINISH_SYSTEM)

    def test_the_same_draft_is_shown_under_both_finishes_with_different_answers(self) -> None:
        blocks = LOCAL_FINISH_SYSTEM.split("Finish: ")[1:]
        by_dictation: dict[str, dict[str, str]] = {}
        for block in blocks:
            finish = block.split("\n", 1)[0].strip()
            dictation = block.split("<dictation>\n", 1)[1].split("\n</dictation>", 1)[0]
            answer = block.split("</dictation>\n", 1)[1].strip()
            by_dictation.setdefault(dictation, {})[finish] = answer
        pairs = [answers for answers in by_dictation.values() if {"Chill", "Executive"} <= set(answers)]
        self.assertTrue(pairs)
        for answers in pairs:
            self.assertNotEqual(answers["Chill"], answers["Executive"])

    def test_the_request_names_the_finish(self) -> None:
        self.assertNotEqual(build_local_request("x", executive=False), build_local_request("x", executive=True))

    def test_the_cloud_executive_addendum_is_a_light_polish(self) -> None:
        self.assertIn("LIGHT POLISH", EXECUTIVE_ADDENDUM)
        self.assertNotIn("FULL PROFESSIONAL REWRITE", EXECUTIVE_ADDENDUM)

    def test_only_vocabulary_the_dictation_could_mean_is_sent(self) -> None:
        terms = ["Deepgram", "OpenAI", "Talk DAT!", "NavOrb"]
        self.assertEqual(relevant_vocabulary(terms, "the talk dat build is green"), ["Talk DAT!"])
        self.assertEqual(relevant_vocabulary(terms, "ask nav orb about openai"), ["OpenAI", "NavOrb"])
        self.assertEqual(relevant_vocabulary(terms, "I don't think it's ready"), [])


class EveryRefusalHasAReasonTests(unittest.TestCase):
    def reason(self, source: str, output: str, *, executive: bool = False) -> str:
        return formatter_rejection_reason(source, output, preserve_meaning=not executive, rewrite_mode=executive)

    def test_reason_codes(self) -> None:
        cases = {
            "empty": ("send it", "   "),
            "refusal": ("send it", "I'm sorry, I cannot help with that."),
            "invented_name": ("tell the team the api is down", "Tell the team the Deepgram API is down."),
            "number_added": ("the total is 5 dollars", "The total is 6 dollars."),
            "number_dropped": ("we have 25 customers and 342 signups", "We have 25 customers and signups."),
            "negation_changed": ("we should ship it on friday", "We should not ship it on Friday."),
            "paragraph_dropped": ("Thanks for the update.\n\nI will review it tonight.",
                                  "Thanks for the update. I will review it tonight."),
            "list_dropped": ("We need three things:\n1. Milk\n2. Eggs\n3. Bread",
                             "We need three things: milk, eggs and bread."),
            "list_without_intent": ("we tested the build and it passed",
                                    "- We tested the build\n- It passed"),
            "broken_line": ("first we ship then we measure then we decide",
                            "First we ship,\nthen we measure.\nThen we decide."),
            "letter_without_name": ("hey can you send me the file when you get a chance thanks",
                                    "Hey,\n\nCan you send me the file when you get a chance?\n\nThanks,"),
            "continuation_dropped": ("And then we can send it.", "We can send it."),
            # 2026-09-23: the essay this row used to hold is the model ANSWERING
            # the dictation, and now carries that name (prompt_injection,
            # below). "expanded" still names growth without new material.
            "expanded": ("it works on my machine",
                         "It works on my machine. It works on my machine, it works on my machine, "
                         "and it works on my machine."),
            "prompt_injection": ("it works on my machine",
                                 "The statement it works on my machine is a common placeholder used by developers "
                                 "when a problem cannot be reproduced on their own computer."),
        }
        for code, (source, output) in cases.items():
            with self.subTest(code=code):
                self.assertEqual(self.reason(source, output), code)

    def test_executive_reason_codes(self) -> None:
        self.assertEqual(self.reason("we will ship friday", "We will probably ship Friday.", executive=True),
                         "stance_added")
        self.assertEqual(self.reason("the budget is 42000 dollars", "The budget is $56,000.", executive=True),
                         "number_added")

    def test_the_reason_is_kept_for_the_journal(self) -> None:
        self.assertFalse(_valid_formatter_output("send it", "I'm sorry, I cannot help with that."))
        self.assertEqual(last_rejection_reason(), "refusal")
        self.assertTrue(_valid_formatter_output("send it now", "Send it now."))
        self.assertEqual(last_rejection_reason(), "")

    def test_a_refusal_reaches_the_journal_entry(self) -> None:
        config = local_config(LOCAL_CHILL_MODEL)
        config["diagnostics"]["formatting_journal"] = True
        entries = []
        with patch("knight_flow.formatting.local_finish", return_value="I'm sorry, I cannot help with that."), \
             patch("knight_flow.format_journal.record_formatting", side_effect=lambda *a, **k: entries.append(k)):
            result = process_dictation("we can send the final report tomorrow", config)
        self.assertEqual(result.route, "rules_after_rejection")
        self.assertEqual(result.rejection, "refusal")
        self.assertEqual(entries[-1]["reason"], "refusal")

    def test_a_refused_executive_polish_is_retried_as_chill_before_rules(self) -> None:
        config = local_config(LOCAL_CHILL_MODEL)
        config["cleanup"]["format_intensity"] = "executive"
        answers = ["We will probably ship the build on Friday.", "We will ship the build on Friday."]
        with patch("knight_flow.formatting.local_finish", side_effect=answers) as model:
            result = process_dictation("we will ship the build on friday", config)
        self.assertEqual([call.kwargs["executive"] for call in model.call_args_list], [True, False])
        self.assertEqual(result.route, "local_model_chill_after_rejection")
        self.assertEqual(result.text, "We will ship the build on Friday.")

    def test_a_refused_retry_still_lands_on_the_rules_draft_with_the_first_reason(self) -> None:
        config = local_config(LOCAL_CHILL_MODEL)
        config["cleanup"]["format_intensity"] = "executive"
        answers = ["We will probably ship the build on Friday.", "We might ship the build on Friday."]
        with patch("knight_flow.formatting.local_finish", side_effect=answers):
            result = process_dictation("we will ship the build on friday", config)
        self.assertEqual(result.route, "rules_after_rejection")
        self.assertEqual(result.rejection, "stance_added")
        self.assertEqual(result.text, "We will ship the build on Friday.")

    def test_chill_is_not_retried(self) -> None:
        config = local_config(LOCAL_CHILL_MODEL)
        config["cleanup"]["format_intensity"] = "standard"
        with patch("knight_flow.formatting.local_finish", return_value="We will not ship it.") as model:
            process_dictation("we will ship the build on friday", config)
        model.assert_called_once()

    def test_correct_formatting_is_not_refused(self) -> None:
        accepted = {
            "count list": ("We need three things milk eggs and bread.",
                           "We need three things:\n1. Milk\n2. Eggs\n3. Bread"),
            "letter": ("Hey sarah just checking in on the draft can you send it by Friday best alex.",
                       "Hey Sarah,\n\nJust checking in on the draft. Can you send it by Friday?\n\nBest,\nAlex"),
            "paragraphs kept": ("Thanks for the update.\n\nI will review it tonight.",
                                "Thanks for the update.\n\nI will review it tonight."),
            "names": ("I talked to sam and sarah about it.", "I talked to Sam and Sarah about it."),
            "sentences": ("The build passed i will deploy after lunch.", "The build passed. I will deploy after lunch."),
            "correction": ("Invite the sales team actually no invite the whole company.", "Invite the whole company."),
            "product casing": ("It crashes on my iphone.", "It crashes on my iPhone."),
        }
        for label, (source, output) in accepted.items():
            with self.subTest(label=label):
                self.assertEqual(self.reason(source, output), "")

    def test_executive_may_expand_a_contraction(self) -> None:
        self.assertEqual(self.reason("I can't make it and she doesn't know.",
                                     "I cannot make it, and she does not know.", executive=True), "")
        self.assertEqual(self.reason("Nobody has called the repair guy.",
                                     "No one has called the repair technician.", executive=True), "")


class TheRulesCloseTheProbeGapsTests(unittest.TestCase):
    def test_probe_gaps(self) -> None:
        cases = {
            "let's meet at five actually make it six": "Let's meet at 6.",
            "the meeting is on tuesday no wait wednesday": "The meeting is on Wednesday.",
            "we need three things milk eggs and bread": "We need three things:\n1. Milk\n2. Eggs\n3. Bread",
            "hey sarah just checking in on the draft best alex":
                "Hey Sarah,\n\nJust checking in on the draft.\n\nBest,\nAlex",
            "our q three revenue was one point two million dollars": "Our Q3 revenue was $1.2 million.",
            "open config dot json and change the port": "Open config.json and change the port.",
            "call me at five five five one two three four": "Call me at 555-1234.",
            "thanks for the update new paragraph i will review it tonight":
                "Thanks for the update.\n\nI will review it tonight.",
        }
        for spoken, expected in cases.items():
            with self.subTest(spoken=spoken):
                self.assertEqual(rules(spoken), expected)

    def test_a_correction_is_only_a_correction_of_the_same_kind_at_a_clause_end(self) -> None:
        self.assertEqual(resolve_value_corrections("At 2 actually three people came."),
                         "At 2 actually three people came.")
        self.assertEqual(resolve_value_corrections("I actually liked it."), "I actually liked it.")
        self.assertEqual(resolve_value_corrections("Meet Tuesday actually 5 PM."), "Meet Tuesday actually 5 PM.")
        self.assertEqual(resolve_value_corrections("From two to three no wait two to four."),
                         "From two to three no wait two to four.")
        self.assertEqual(resolve_value_corrections("Call at 4 PM no wait 5."), "Call at 5 PM.")
        self.assertEqual(resolve_value_corrections("It is $10 actually $12."), "It is $12.")

    def test_a_seven_digit_run_is_a_phone_number_only_with_a_phone_cue(self) -> None:
        self.assertEqual(rules("the code is five five five one two three four"), "The code is 5551234.")

    def test_a_greeting_alone_is_not_a_letter(self) -> None:
        self.assertNotIn("\n", rules("hey quick question can you send the file"))
        self.assertNotIn("\n", rules("can you send the file when you get a chance thanks sam"))

    def test_an_announced_count_must_match_its_items(self) -> None:
        self.assertNotIn("\n", rules("i need three things done today the tests the docs and the deploy"))
        self.assertNotIn("\n", rules("two things colon the api is down semicolon the site is fine"))

    def test_a_ticket_is_not_the_product(self) -> None:
        self.assertEqual(rules("the ticket is twelve dollars"), "The ticket is $12.")
        self.assertEqual(rules("i built talkdad for windows"), "I built Talk DAT! for windows.")

    def test_kind_of_after_a_determiner_is_not_a_filler(self) -> None:
        self.assertEqual(rules("the kind of work we do is careful"), "The kind of work we do is careful.")
        # X-602 reversed the second half on purpose: "kind of" before an
        # adjective is a hedge (docs/DICTATION-COMMANDMENTS.md commandment
        # 14), and "it was kind of slow" is a weaker claim than "it was slow".
        self.assertEqual(rules("it was kind of slow"), "It was kind of slow.")


class TheReadyMarkerSurvivesAnotherReaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        (self.tmp / "model.onnx").write_bytes(b"x" * 64)
        self.model = local_stt.LocalModel("m", "Model", "onnx_asr", "e", 1, "en")

    def markers(self) -> list[str]:
        return sorted(p.name for p in self.tmp.iterdir() if p.name.startswith(local_stt.READY_MARKER))

    def test_an_unchanged_manifest_is_not_rewritten(self) -> None:
        local_stt._write_ready_manifest(self.model, self.tmp)
        with patch.object(local_stt.os, "replace") as replace:
            local_stt._write_ready_manifest(self.model, self.tmp)
        replace.assert_not_called()

    def test_a_busy_marker_is_retried(self) -> None:
        real = os.replace
        attempts = []

        def flaky(src, dst):
            attempts.append(1)
            if len(attempts) < 3:
                raise PermissionError(32, "The process cannot access the file")
            return real(src, dst)

        with patch.object(local_stt.os, "replace", side_effect=flaky), patch.object(local_stt.time, "sleep"):
            local_stt._write_ready_manifest(self.model, self.tmp)
        self.assertEqual(len(attempts), 3)
        self.assertEqual(self.markers(), [local_stt.READY_MARKER])
        self.assertEqual(json.loads((self.tmp / local_stt.READY_MARKER).read_text())["model_id"], "m")

    def test_a_marker_that_stays_busy_never_fails_the_warm_up(self) -> None:
        with patch.object(local_stt.os, "replace", side_effect=PermissionError(32, "busy")), \
             patch.object(local_stt.time, "sleep"), \
             self.assertLogs(local_stt.log, level="WARNING"):
            local_stt._write_ready_manifest(self.model, self.tmp)  # must not raise
        self.assertEqual(self.markers(), [])  # temporary file cleaned up

    def test_each_writer_has_its_own_temporary_file(self) -> None:
        names = []
        real_write = Path.write_text

        def spy(path, *args, **kwargs):
            names.append(path.name)
            return real_write(path, *args, **kwargs)

        with patch.object(Path, "write_text", spy):
            local_stt._write_ready_manifest(self.model, self.tmp)
        temporary = [name for name in names if name.endswith(".tmp")]
        self.assertEqual(len(temporary), 1)
        self.assertIn(str(os.getpid()), temporary[0])
        self.assertIn(str(threading.get_ident()), temporary[0])

    def test_temporary_markers_are_not_counted_as_payload(self) -> None:
        (self.tmp / f"{local_stt.READY_MARKER}.123.456.tmp").write_text("{}")
        self.assertNotIn(f"{local_stt.READY_MARKER}.123.456.tmp", local_stt._payload_inventory(self.tmp))


if __name__ == "__main__":
    unittest.main()
