"""X-410: the local finisher must receive its whole prompt.

Ollama truncates the input to num_ctx minus the reply budget. With the
shipped 4096 the Executive prompt (about 4,360 tokens with a dictation) was
cut to 2,050 tokens, the model never saw its instructions, and the local
finish echoed the text or wrote nonsense. This pins the window to the prompt.

X-412 replaced the literal with `context_window`, so the assertion moved from
"the number in the source is big enough" to "the function returns a window
that holds the biggest prompt this app can send". That is the same guarantee
tested against the thing that now provides it, and it keeps holding for a
dictation longer than anyone anticipated.
"""
from __future__ import annotations

import unittest

from knight_flow import llm
from knight_flow.formatting import EXECUTIVE_ADDENDUM, FORMAT_SYSTEM_PROMPT
from knight_flow.local_finish import LOCAL_FINISH_SYSTEM, context_window, estimate_tokens


class TheLocalFormatterSeesItsWholePromptTests(unittest.TestCase):
    def test_the_context_window_holds_the_prompt_a_dictation_and_the_answer(self) -> None:
        predict = 1024
        # The heaviest request the app can send on a local engine: the full
        # rulebook plus the Executive addendum plus a long dictation. A BYOK
        # Ollama install still takes exactly this route.
        dictation = "word " * 400
        prompt = FORMAT_SYSTEM_PROMPT + EXECUTIVE_ADDENDUM + dictation
        window = context_window(len(prompt), num_predict=predict)
        self.assertGreaterEqual(
            window,
            estimate_tokens(prompt) + predict,
            f"num_ctx {window} cannot hold the prompt and its answer",
        )
        # X-410's floor survives as a floor: a short prompt never asks Ollama
        # for a window small enough to reintroduce truncation.
        self.assertGreaterEqual(context_window(10, num_predict=predict), 8192)

    def test_every_prompt_constant_still_fits(self) -> None:
        """Whatever the prompts are called, and whatever they grow into."""
        prompts = {
            name: value
            for name, value in list(vars(llm).items()) + list(vars(__import__(
                "knight_flow.formatting", fromlist=["x"]
            )).items())
            if isinstance(value, str) and ("PROMPT" in name or "ADDENDUM" in name)
        }
        self.assertTrue(prompts, "the prompt constants moved; point this test at them")
        system = max((len(v) for n, v in prompts.items() if "PROMPT" in n), default=0)
        addendum = max((len(v) for n, v in prompts.items() if "ADDENDUM" in n), default=0)
        needed = (system + addendum) // 4 + 400 + 1024
        self.assertGreaterEqual(context_window(system + addendum + 1600, num_predict=1024), needed)

    def test_the_local_contract_is_small_enough_to_be_worth_sending(self) -> None:
        """X-412: the whole point of the local path is a short fixed block.

        4,360 tokens of rulebook cost 61 s of CPU prefill and got truncated.
        If this ever creeps back over 800 tokens the local route has quietly
        become the thing it was built to replace. (2026-09-22: raised from 500
        for the FORMAT/FINISH split and its four worked examples. The block is
        warmed once per model load and cached; on the owner's 3090 it costs
        about 0.2 s once, and a CPU machine is refused before it is sent.
        2026-09-23: raised to 900 for the prompt-injection and keep-the-words
        rules.)
        """
        self.assertLess(estimate_tokens(LOCAL_FINISH_SYSTEM), 900)


if __name__ == "__main__":
    unittest.main()
