"""X-412: the on-device finishing contract, and the honesty when it cannot run.

Every number quoted in these tests was measured on the founder's PC on
2026-09-03 (i7-8700, RTX 3090, Ollama 0.33.2) against three 200-word
dictations. They are in the assertions rather than in a comment because the
whole feature is a claim about time, and a claim about time that nothing
checks is how the local finisher spent months returning the transcript
unchanged with the product reporting success.
"""
from __future__ import annotations

import hashlib
import unittest
from unittest import mock
import urllib.error
from unittest.mock import patch

from knight_flow import llm
from knight_flow.formatting import (
    EXECUTIVE_ADDENDUM,
    FORMAT_INSTRUCTION,
    FORMAT_SYSTEM_PROMPT,
    smart_format,
)
from knight_flow.local_finish import (
    LOCAL_CHILL_MODEL,
    LOCAL_EXECUTIVE_MODEL,
    LOCAL_FINISH_SCHEMA,
    LOCAL_FINISH_SYSTEM,
    LOCAL_THINKING_TAGS,
    MachineSpeed,
    build_local_request,
    choose_local_model,
    context_window,
    estimate_tokens,
    machine_is_too_slow,
    parse_finish_envelope,
    reply_budget,
    vocabulary_terms,
)


# X-465: this module is about the world where local-only is OFF.
#
# Talk DAT! is local-only by default now: the speech route, the formatter and
# the door that lets text leave all read one switch, and a config that has
# never heard of that switch is treated as local-only, which is the right
# answer for a real install upgrading from an older version. The fixtures
# below are bare dicts asking for the managed or bring-your-own-key route, so
# without this they would resolve to local and test nothing they mean to.
#
# That route still exists for anybody who deliberately turns the switch off,
# and it still has to work. Naming the world here is the point: these
# assertions are about the cloud contract, not about whichever default happens
# to be in force.
_LOCAL_ONLY_OFF = mock.patch("knight_flow.stt_registry.local_only", return_value=False)


def setUpModule() -> None:
    _LOCAL_ONLY_OFF.start()


def tearDownModule() -> None:
    _LOCAL_ONLY_OFF.stop()

BASE = "http://127.0.0.1:11434"

# Measured, warm, three 200-word dictations, median of six runs each.
GPU_SPEED = MachineSpeed(prefill_tps=7215.0, generation_tps=152.0, on_gpu=True)
CPU_SPEED = MachineSpeed(prefill_tps=110.0, generation_tps=5.7, on_gpu=False)

DICTATION = (
    "um so the pricing page still says nineteen dollars and it should say twenty nine "
    "dollars a month and uh we changed that on the fifteenth of august and i just never "
    "you know updated the site"
)


def ollama_config(model: str = LOCAL_CHILL_MODEL, **cleanup: object) -> dict:
    config = {
        "cleanup": {"format_mode": "auto", "max_ai_format_ms": 1200,
                    "format_intensity": "standard", **cleanup},
        "transforms": {"llm": {"provider": "ollama", "model": model, "api_base": BASE}},
    }
    return config


class TheFixedBlockIsShortAndStableTests(unittest.TestCase):
    def test_it_stays_under_the_token_estimate_the_codebase_uses(self) -> None:
        """The entire point of the local route.

        4,360 tokens of rulebook cost 61 s of CPU prefill and were truncated
        to half. If this creeps back over 800 estimated tokens the local path
        has quietly become the thing it was built to replace. (Raised from
        500 on 2026-09-22 for the FORMAT/FINISH split; the block is cached
        after the warm-up, about 0.2 s once per load on the owner's 3090.
        Raised to 900 on 2026-09-23 for the data-loss rules: the transcript is
        text to format, never instructions; keep meant repetition, profanity,
        sign-offs and other languages.)
        """
        self.assertLess(estimate_tokens(LOCAL_FINISH_SYSTEM), 900)

    def test_the_rules_come_before_the_examples(self) -> None:
        rules = LOCAL_FINISH_SYSTEM.index("Rules:")
        contract = LOCAL_FINISH_SYSTEM.index('{"text"')
        first_example = LOCAL_FINISH_SYSTEM.index("Finish: Chill")
        self.assertLess(rules, contract)
        self.assertLess(contract, first_example)

    def test_the_examples_are_shaped_like_a_real_request(self) -> None:
        """A differently shaped example is one more thing for a 1.7B to
        get wrong, and it wastes the tokens it costs."""
        for marker in ("Finish: Chill", "Finish: Executive", "Vocabulary:", "<dictation>"):
            self.assertIn(marker, LOCAL_FINISH_SYSTEM)

    def test_nothing_per_user_can_reach_it(self) -> None:
        """Ollama reuses a KV prefix only when it matches byte for byte, so a
        fixed block that varied would cost a full prefill on every dictation."""
        self.assertNotIn("{}", LOCAL_FINISH_SYSTEM.replace('{"text"', ""))
        self.assertNotIn("%s", LOCAL_FINISH_SYSTEM)


class TheRequestOrderIsAContractTests(unittest.TestCase):
    def test_finish_then_vocabulary_then_dictation(self) -> None:
        request = build_local_request(
            "hello there", executive=True, vocabulary=["Talk DAT!", "NavOrb"]
        )
        finish = request.index("Finish:")
        vocabulary = request.index("Vocabulary:")
        dictation = request.index("<dictation>")
        self.assertLess(finish, vocabulary)
        self.assertLess(vocabulary, dictation)

    def test_the_fixed_block_is_the_system_message_and_the_tail_is_the_user_one(self) -> None:
        """Everything stable above everything that changes, or the cache never
        hits: the fixed block is sent as the system message, the tail as the
        user message, and never the other way round."""
        sent = {}

        def capture(system, user, **kwargs):
            sent["system"], sent["user"] = system, user
            return {"message": {"content": '{"text": "Done."}'},
                    "prompt_eval_count": 600, "prompt_eval_duration": 10_000_000,
                    "eval_count": 40, "eval_duration": 300_000_000}

        with (
            patch("knight_flow.llm._ollama_ready", return_value=True),
            patch("knight_flow.llm._ollama_models", return_value={LOCAL_CHILL_MODEL}),
            patch("knight_flow.llm._ollama_chat", side_effect=capture),
        ):
            llm.local_finish(DICTATION, ollama_config(), executive=False, budget_seconds=1.2)

        self.assertEqual(sent["system"], LOCAL_FINISH_SYSTEM)
        self.assertTrue(sent["user"].startswith("Finish: Chill"))
        self.assertIn(DICTATION, sent["user"])

    def test_the_finish_name_follows_the_intensity(self) -> None:
        self.assertIn("Finish: Executive", build_local_request("x", executive=True))
        self.assertIn("Finish: Chill", build_local_request("x", executive=False))

    def test_an_empty_vocabulary_keeps_the_line(self) -> None:
        """The shape stays constant whether or not anybody taught it a word."""
        self.assertIn("Vocabulary: (none)", build_local_request("x", executive=False))

    def test_the_vocabulary_is_the_user_dictionary_capped(self) -> None:
        config = {"dictionary": {"words": ["NavOrb", "TaskRune", "deepgram"],
                                 "terms": [{"text": "Halcyon Media"}]}}
        terms = vocabulary_terms(config, limit=3)
        self.assertEqual(terms[:2], ["NavOrb", "TaskRune"])
        self.assertEqual(len(terms), 3)
        # A plain-lowercase term teaches a model nothing about spelling and is
        # not worth the tokens.
        self.assertNotIn("deepgram", vocabulary_terms(config))

    def test_the_product_name_rides_along_without_being_taught(self) -> None:
        self.assertIn("Talk DAT!", vocabulary_terms({}))


class TheEnvelopeParserSurvivesTheModelTests(unittest.TestCase):
    def test_a_plain_object(self) -> None:
        self.assertEqual(parse_finish_envelope('{"text": "Ship on Tuesday."}'), "Ship on Tuesday.")

    def test_markdown_fences(self) -> None:
        fenced = '```json\n{"text": "Ship on Tuesday."}\n```'
        self.assertEqual(parse_finish_envelope(fenced), "Ship on Tuesday.")
        self.assertEqual(parse_finish_envelope('```\n{"text": "Ship."}\n```'), "Ship.")

    def test_a_missing_key_with_one_string_value(self) -> None:
        self.assertEqual(parse_finish_envelope('{"output": "Ship on Tuesday."}'), "Ship on Tuesday.")

    def test_a_missing_key_with_several_values_is_refused(self) -> None:
        """Guessing which field held the dictation could paste the wrong one."""
        self.assertEqual(parse_finish_envelope('{"a": "one", "b": "two"}'), "")

    def test_plain_text_with_no_json_at_all(self) -> None:
        """The unconstrained retry answers this way, and so does any model
        that ignored the schema."""
        self.assertEqual(parse_finish_envelope("Ship on Tuesday."), "Ship on Tuesday.")

    def test_an_object_wrapped_in_prose(self) -> None:
        self.assertEqual(
            parse_finish_envelope('Here you go: {"text": "Ship on Tuesday."} hope that helps'),
            "Ship on Tuesday.",
        )

    def test_nothing_at_all(self) -> None:
        self.assertEqual(parse_finish_envelope(""), "")
        self.assertEqual(parse_finish_envelope("   "), "")

    def test_the_schema_asks_for_the_envelope_only(self) -> None:
        """A schema guarantees shape, not content, and constraints can cost a
        small model accuracy. One key is all this asks for."""
        self.assertEqual(list(LOCAL_FINISH_SCHEMA["properties"]), ["text"])


class TheCloudPromptIsUntouchedTests(unittest.TestCase):
    """X-412 changed the LOCAL prompt. A cloud or BYOK install must send
    exactly the bytes it sent yesterday."""

    # Each digest is written in four pieces (Python joins adjacent literals)
    # so the prepublish secret scanner, which flags any 40+ hex run, does not
    # mistake a prompt fingerprint for a leaked key.
    EXPECTED = {
        # X-553: the owner changed time style to AM/PM on every lane.
        "FORMAT_SYSTEM_PROMPT": "80e92b5db2aae53c" "32ee93f78083e913" "792bca5d1186e65a" "a9e256abab46cadc",
        # 2026-09-22: Executive is formatting plus a LIGHT polish, not a full
        # rewrite (the owner's current contract; see formatting.py).
        # 2026-09-22: re-pinned after restoring the X-296 "never showy" plain-words
        # sentence that the light-polish rewrite had shortened.
        # 2026-09-23: re-pinned. "Profanity is removed" contradicted the
        # censor_profanity setting and the validator's profanity_removed
        # check; profanity, other languages and emphasis now stay.
        "EXECUTIVE_ADDENDUM": "2828f2527af187c9" "31e2af5092b0fc8c" "bd280510b11c1a1f" "7ec819883af601bb",
        "FORMAT_INSTRUCTION": "1d5b7ee94260de0b" "24ea85df99530c24" "c59815e0098a690e" "2953276efb44a270",
        "REWRITE_SYSTEM_PROMPT": "77a701a4b06167fe" "4f47669de43b6bf9" "c10240372a5646ee" "c9975343b01b880c",
    }

    def test_every_cloud_prompt_is_byte_identical(self) -> None:
        actual = {
            "FORMAT_SYSTEM_PROMPT": FORMAT_SYSTEM_PROMPT,
            "EXECUTIVE_ADDENDUM": EXECUTIVE_ADDENDUM,
            "FORMAT_INSTRUCTION": FORMAT_INSTRUCTION,
            "REWRITE_SYSTEM_PROMPT": llm.REWRITE_SYSTEM_PROMPT,
        }
        for name, expected in self.EXPECTED.items():
            with self.subTest(prompt=name):
                digest = hashlib.sha256(actual[name].encode("utf-8")).hexdigest()
                self.assertEqual(digest, expected, f"{name} changed; the cloud route must not")

    def test_a_cloud_route_still_gets_the_rulebook(self) -> None:
        config = {
            "cleanup": {"format_mode": "auto", "format_intensity": "executive"},
            "transforms": {"llm": {"provider": "openrouter", "api_key": "test-key"}},
        }
        with patch("knight_flow.formatting.llm_complete", return_value=None) as complete:
            smart_format(DICTATION, config)
        system = complete.call_args.args[0]
        self.assertTrue(system.startswith(FORMAT_SYSTEM_PROMPT))
        self.assertIn(EXECUTIVE_ADDENDUM, system)

    def test_a_local_route_never_gets_the_rulebook(self) -> None:
        with (
            patch("knight_flow.formatting.llm_complete") as complete,
            patch("knight_flow.formatting.local_finish", return_value=None) as finish,
        ):
            smart_format(DICTATION, ollama_config())
        complete.assert_not_called()
        finish.assert_called_once()


class TheModelFollowsTheFinishTests(unittest.TestCase):
    INSTALLED = {LOCAL_CHILL_MODEL, LOCAL_EXECUTIVE_MODEL, "qwen3:4b"}

    def test_chill_on_a_gpu_also_takes_the_instruct_model(self) -> None:
        """2026-09-22: the GPU model finishes both finishes. It scored higher
        on the 200-case battery at the same finish, and one resident model is
        one model to keep warm."""
        self.assertEqual(
            choose_local_model(LOCAL_CHILL_MODEL, executive=False,
                               installed=self.INSTALLED, on_gpu=True),
            LOCAL_EXECUTIVE_MODEL,
        )

    def test_chill_without_a_gpu_takes_the_small_model(self) -> None:
        self.assertEqual(
            choose_local_model(LOCAL_CHILL_MODEL, executive=False,
                               installed=self.INSTALLED, on_gpu=False),
            LOCAL_CHILL_MODEL,
        )

    def test_executive_on_a_gpu_takes_the_instruct_model(self) -> None:
        self.assertEqual(
            choose_local_model(LOCAL_CHILL_MODEL, executive=True,
                               installed=self.INSTALLED, on_gpu=True),
            LOCAL_EXECUTIVE_MODEL,
        )

    def test_executive_without_a_gpu_stays_small(self) -> None:
        """The 4B costs 58 s on six CPU threads, so upgrading there buys a
        longer wait for the same rules output."""
        self.assertEqual(
            choose_local_model(LOCAL_CHILL_MODEL, executive=True,
                               installed=self.INSTALLED, on_gpu=False),
            LOCAL_CHILL_MODEL,
        )

    def test_executive_without_the_model_pulled_stays_small(self) -> None:
        self.assertEqual(
            choose_local_model(LOCAL_CHILL_MODEL, executive=True,
                               installed={LOCAL_CHILL_MODEL}, on_gpu=True),
            LOCAL_CHILL_MODEL,
        )

    def test_the_users_own_model_outranks_the_routing(self) -> None:
        for finish in (True, False):
            with self.subTest(executive=finish):
                self.assertEqual(
                    choose_local_model("mistral-small:24b", executive=finish,
                                       installed=self.INSTALLED, on_gpu=True),
                    "mistral-small:24b",
                )

    def test_the_thinking_tag_is_never_chosen(self) -> None:
        """Ollama's qwen3:4b ignores think:false, writes its reasoning as the
        answer, and takes 11.5 s."""
        for on_gpu in (True, False):
            self.assertNotIn(
                choose_local_model(LOCAL_CHILL_MODEL, executive=True,
                                   installed=self.INSTALLED, on_gpu=on_gpu).lower(),
                LOCAL_THINKING_TAGS,
            )


class TheWindowHoldsThePromptTests(unittest.TestCase):
    def test_the_floor_survives(self) -> None:
        self.assertGreaterEqual(context_window(100, num_predict=1024), 8192)

    def test_a_long_prompt_raises_it(self) -> None:
        window = context_window(200_000, num_predict=1024)
        self.assertGreaterEqual(window, 50_000 + 1024)

    def test_the_reply_budget_is_bounded_by_the_input(self) -> None:
        """A model that starts babbling costs a bounded slice of the budget
        rather than all of it."""
        self.assertLessEqual(reply_budget("word " * 200), 1024)
        self.assertGreaterEqual(reply_budget("hi"), 128)


class ThisPcSaysWhenItCannotTests(unittest.TestCase):
    def setUp(self) -> None:
        llm._LOCAL_SPEED.clear()
        llm._LOCAL_REFUSED.clear()
        self.addCleanup(llm._LOCAL_SPEED.clear)
        self.addCleanup(llm._LOCAL_REFUSED.clear)

    def key(self, model: str = LOCAL_CHILL_MODEL) -> tuple:
        return llm.local_finish_key(BASE, model)

    def test_the_measured_cpu_is_thirty_times_over_the_budget(self) -> None:
        """36.4 s measured for a 200-word Chill finish on six threads."""
        self.assertTrue(machine_is_too_slow(CPU_SPEED, 1200.0))
        self.assertTrue(machine_is_too_slow(CPU_SPEED, 6000.0))

    def test_the_measured_gpu_is_inside_the_budget(self) -> None:
        self.assertFalse(machine_is_too_slow(GPU_SPEED, 1200.0))

    def test_a_cpu_machine_never_spends_the_budget_finding_out_again(self) -> None:
        llm._LOCAL_SPEED[self.key()] = CPU_SPEED
        with (
            patch("knight_flow.llm._ollama_ready", return_value=True),
            patch("knight_flow.llm._ollama_models", return_value={LOCAL_CHILL_MODEL}),
            patch("knight_flow.llm._ollama_chat") as chat,
        ):
            answer = llm.local_finish(DICTATION, ollama_config(), executive=False, budget_seconds=1.2)
        self.assertIsNone(answer)
        chat.assert_not_called()
        self.assertEqual(llm._LOCAL_REFUSED[self.key()], "too_slow")

    def test_settings_gets_a_sentence_rather_than_a_working_looking_formatter(self) -> None:
        llm._LOCAL_SPEED[self.key()] = CPU_SPEED
        llm._LOCAL_REFUSED[self.key()] = "too_slow"
        with (
            patch("knight_flow.llm._ollama_models", return_value={LOCAL_CHILL_MODEL}),
            patch("knight_flow.llm._local_ollama_executable", return_value="C:/ollama.exe"),
        ):
            verdict = llm.finishing_status(ollama_config())
        self.assertFalse(verdict["ok"])
        self.assertEqual(verdict["reason"], "local_too_slow")
        self.assertIn("GPU", verdict["message"])
        # Customer-facing copy: no em dash, and the product keeps its name.
        self.assertNotIn("\u2014", verdict["message"])
        self.assertNotIn(" -- ", verdict["message"])

    def test_one_very_long_dictation_is_not_a_hardware_verdict(self) -> None:
        """A 900-word ramble that misses the budget on a working GPU must not
        tell somebody their PC needs a GPU."""
        llm._LOCAL_SPEED[self.key()] = GPU_SPEED
        with (
            patch("knight_flow.llm._ollama_ready", return_value=True),
            patch("knight_flow.llm._ollama_models", return_value={LOCAL_CHILL_MODEL}),
            patch("knight_flow.llm._ollama_chat") as chat,
        ):
            answer = llm.local_finish("word " * 900, ollama_config(), executive=False, budget_seconds=1.2)
        self.assertIsNone(answer)
        chat.assert_not_called()
        self.assertEqual(llm._LOCAL_REFUSED, {})

    def test_a_gpu_machine_is_allowed_to_run(self) -> None:
        llm._LOCAL_SPEED[self.key()] = GPU_SPEED
        with (
            patch("knight_flow.llm._ollama_ready", return_value=True),
            patch("knight_flow.llm._ollama_models", return_value={LOCAL_CHILL_MODEL}),
            patch("knight_flow.llm._ollama_chat", return_value={
                "message": {"content": '{"text": "The pricing page still says nineteen dollars."}'},
                "prompt_eval_count": 600, "prompt_eval_duration": 10_000_000,
                "eval_count": 40, "eval_duration": 300_000_000,
            }) as chat,
        ):
            answer = llm.local_finish(DICTATION, ollama_config(), executive=False, budget_seconds=1.2)
        chat.assert_called_once()
        self.assertEqual(answer, "The pricing page still says nineteen dollars.")

    def test_a_cached_prefix_cannot_inflate_the_measured_prefill(self) -> None:
        """Ollama counts the whole prompt and times only the uncached part, so
        dividing one by the other on a warm reply claimed 258 tok/s where the
        machine really does 110."""
        warm = {"prompt_eval_count": 600, "prompt_eval_duration": 10_000_000,
                "eval_count": 40, "eval_duration": 300_000_000}
        llm._LOCAL_SPEED[self.key()] = CPU_SPEED
        llm._record_local_speed(BASE, LOCAL_CHILL_MODEL, warm)
        self.assertEqual(llm._LOCAL_SPEED[self.key()].prefill_tps, CPU_SPEED.prefill_tps)

    def test_a_refused_schema_is_retried_unconstrained(self) -> None:
        """A refused schema is a fact about the engine, not about this
        dictation, so losing the finish over it would be the wrong trade."""
        calls = []

        def answer(system, user, **kwargs):
            calls.append(kwargs.get("schema"))
            if kwargs.get("schema") is not None:
                raise urllib.error.HTTPError(BASE, 400, "bad format", None, None)
            return {"message": {"content": "Plain text answer."},
                    "prompt_eval_count": 600, "prompt_eval_duration": 10_000_000,
                    "eval_count": 40, "eval_duration": 300_000_000}

        with (
            patch("knight_flow.llm._ollama_ready", return_value=True),
            patch("knight_flow.llm._ollama_models", return_value={LOCAL_CHILL_MODEL}),
            patch("knight_flow.llm._ollama_chat", side_effect=answer),
        ):
            output = llm.local_finish(DICTATION, ollama_config(), executive=False, budget_seconds=1.2)
        self.assertEqual(output, "Plain text answer.")
        self.assertEqual(len(calls), 2)
        self.assertIsNone(calls[1])


if __name__ == "__main__":
    unittest.main()
