from __future__ import annotations

import unittest
from unittest import mock
from unittest.mock import patch

from knight_flow.formatting import smart_format
from knight_flow.llm import (
    _OLLAMA_PREPARE_IN_FLIGHT,
    _OLLAMA_PREPARED,
    _complete_ollama,
    llm_complete,
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


class LocalFormatterTests(unittest.TestCase):
    def test_ollama_payload_is_fast_non_thinking_and_warm(self) -> None:
        with patch(
            "knight_flow.llm._post_json",
            return_value={"message": {"content": "Finished text."}},
        ) as post_json:
            output = _complete_ollama(
                "system",
                "user",
                api_base="http://127.0.0.1:11434",
                model="qwen3:0.6b",
                timeout=8,
            )

        self.assertEqual(output, "Finished text.")
        body = post_json.call_args.args[1]
        self.assertIs(body["think"], False)
        self.assertEqual(body["keep_alive"], -1)
        # X-410 raised the window from 4096, which truncated the prompt, and
        # X-412 made 8192 the floor rather than the value: a long dictation
        # grows it, nothing shrinks it below what the prompt needs.
        self.assertGreaterEqual(body["options"]["num_ctx"], 8192)
        self.assertLessEqual(body["options"]["num_predict"], 1024)

    def test_a_long_prompt_grows_the_window_rather_than_being_cut(self) -> None:
        with patch(
            "knight_flow.llm._post_json",
            return_value={"message": {"content": "Finished text."}},
        ) as post_json:
            system = "x" * 40_000
            _complete_ollama(
                system, "y" * 8_000,
                api_base="http://127.0.0.1:11434", model="qwen3:1.7b", timeout=8,
            )
        window = post_json.call_args.args[1]["options"]["num_ctx"]
        self.assertGreaterEqual(window, 48_000 // 4 + 1024)

    def test_automatic_formatting_passes_a_strict_latency_budget(self) -> None:
        config = {
            "cleanup": {"format_mode": "auto", "max_ai_format_ms": 1200},
            "transforms": {
                "llm": {
                    "provider": "ollama",
                    "model": "qwen3:1.7b",
                    "api_base": "http://127.0.0.1:11434",
                }
            },
        }
        text = "This dictation has several connected ideas and needs careful punctuation without becoming a list"
        # X-412: the local route carries the same budget through its own
        # function, so the budget has to be asserted where it now lands.
        with patch("knight_flow.formatting._high_confidence_fast_format", return_value=None), patch(
            "knight_flow.formatting.local_finish", return_value=None
        ) as finish:
            output = smart_format(text, config)

        self.assertTrue(output)
        # 2026-09-22: base 1.2 s plus a per-word share, capped at 3 s.
        from knight_flow.formatting import model_budget_seconds

        self.assertEqual(finish.call_args.kwargs["budget_seconds"], model_budget_seconds(config["cleanup"], text))
        self.assertGreater(finish.call_args.kwargs["budget_seconds"], 1.2)
        self.assertLessEqual(finish.call_args.kwargs["budget_seconds"], 3.0)

    def test_a_cloud_formatter_still_gets_the_budget_as_a_timeout(self) -> None:
        config = {
            "cleanup": {"format_mode": "auto", "max_ai_format_ms": 1200},
            "transforms": {"llm": {"provider": "openrouter", "api_key": "test-key"}},
        }
        text = "This dictation has several connected ideas and needs careful punctuation without becoming a list"
        with patch("knight_flow.formatting._high_confidence_fast_format", return_value=None), patch(
            "knight_flow.formatting.llm_complete", return_value=None
        ) as complete:
            output = smart_format(text, config)

        self.assertTrue(output)
        from knight_flow.formatting import model_budget_seconds

        self.assertEqual(complete.call_args.kwargs["timeout_override"], model_budget_seconds(config["cleanup"], text))

    def test_unavailable_ollama_skips_generation_immediately(self) -> None:
        config = {
            "transforms": {
                "llm": {
                    "provider": "ollama",
                    "model": "qwen3:0.6b",
                    "api_base": "http://127.0.0.1:11434",
                    "timeout": 20,
                }
            }
        }
        with (
            patch("knight_flow.llm._ollama_ready", return_value=False),
            patch("knight_flow.llm._complete_ollama") as complete,
        ):
            self.assertIsNone(llm_complete("system", "user", config))
        complete.assert_not_called()

    def test_formatter_warmup_in_progress_uses_immediate_fallback(self) -> None:
        api_base = "http://127.0.0.1:11434"
        model = "qwen3:1.7b"
        key = (api_base, model)
        config = {
            "transforms": {
                "llm": {
                    "provider": "ollama",
                    "model": model,
                    "api_base": api_base,
                    "timeout": 8,
                }
            }
        }
        _OLLAMA_PREPARE_IN_FLIGHT.add(key)
        _OLLAMA_PREPARED.discard(key)
        try:
            with (
                patch("knight_flow.llm._ollama_ready", return_value=True),
                patch("knight_flow.llm._complete_ollama") as complete,
            ):
                self.assertIsNone(llm_complete("system", "user", config))
            complete.assert_not_called()
        finally:
            _OLLAMA_PREPARE_IN_FLIGHT.discard(key)


if __name__ == "__main__":
    unittest.main()
