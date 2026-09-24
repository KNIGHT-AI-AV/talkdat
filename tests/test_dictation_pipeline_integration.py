from __future__ import annotations

import unittest

from knight_flow.config import load_config
from knight_flow.formatting import needs_intelligence, _valid_formatter_output
from knight_flow.text_pipeline import process_dictation


REPAIRED = [
    # (what the recognizer heard, what must NOT survive into the output)
    ("Um, so I was thinking that we should probably push the release to Friday. "
     "How is, how is, not OpenRouter, how is Wispr Flow doing this", "OpenRouter"),
    ("call mom, I mean call dad, tonight about the thing", "mom"),
    ("we need to, we need to fix this today", "we need to, we need to"),
]


class RepairReachesTheOutputTests(unittest.TestCase):
    """An end-to-end check on the pipeline, not on its parts.

    Every component of self-correction passed its own tests while the feature
    did nothing: the gate correctly sent the text to the model, the prompt
    correctly repaired it, and _valid_formatter_output then rejected the result
    because repairing a retraction drops a negation. Two correct halves, broken
    together, shipped in 0.4.18 and found only by running real speech through
    the whole thing.

    These assert the property that actually matters -- the retracted words are
    gone from what a person would see -- so no future change to the gate, the
    prompt or the validator can quietly reinstate that failure.

    Skipped when no model is configured, since without one the local formatter
    is the whole pipeline and cannot resolve a retraction.
    """

    @classmethod
    def setUpClass(cls) -> None:
        from knight_flow.formatting import llm_would_format
        cls.config = load_config()
        if not llm_would_format(cls.config):
            raise unittest.SkipTest("no formatter model configured")
        # A generous model budget, FOR THE TEST ONLY. The product ships a
        # ~1.2s cap (max_ai_format_ms) because a dictation cannot wait longer
        # than that, and when the round trip exceeds it the rules path answers
        # instead -- by design. Left at the product value, this test silently
        # measures tonight's network latency instead of repair semantics: one
        # slow evening and every attempt "fails" with byte-identical rules
        # output, which is exactly what happened on 2026-08-07. The question
        # this class asks is "does the repair survive the pipeline when the
        # model answers", so the budget must be big enough that it does.
        cls.config.setdefault("cleanup", {})["max_ai_format_ms"] = 8000
        # A model that cannot be REACHED is a different fact from a model that
        # answered badly, and only the second one is a defect in this code. An
        # empty API balance failed these two tests for hours on 2026-08-07 and
        # the failure text pointed at the repair logic, which was fine. Probe
        # once and skip loudly instead.
        from knight_flow.llm import llm_complete
        if llm_complete("Reply with ok.", "ok", cls.config, timeout_override=20.0) is None:
            raise unittest.SkipTest(
                "the formatter model is unreachable (billing, network or quota) -- "
                "repair semantics cannot be verified without it"
            )

    def test_the_gate_sends_repaired_speech_to_the_model(self) -> None:
        for heard, _ in REPAIRED:
            with self.subTest(heard=heard[:40]):
                self.assertTrue(needs_intelligence(heard),
                                "this text needs the model and the fast path would skip it")

    def test_the_validator_accepts_a_repair_that_drops_a_retraction(self) -> None:
        source = "how is, how is, not OpenRouter, how is Wispr Flow doing this"
        self.assertTrue(
            _valid_formatter_output(source, "How is Wispr Flow doing this?", preserve_meaning=True),
            "the repair is being discarded after the model returns it",
        )

    # The model is sampled, not deterministic, so a single call is a coin flip
    # with a very good coin. Measured over 30 calls on 2026-08-05: 29 resolved
    # the retraction, about 97%. Asserting one call therefore failed roughly
    # one full-suite run in twenty, which trains everyone to re-run a red
    # suite -- the most expensive habit a test can teach.
    #
    # Best of three keeps the assertion honest. At a 3% per-call failure rate
    # two of three failing is about 0.3%, while a genuine regression to, say,
    # 50% still fails this test seven times out of eight.
    ATTEMPTS = 3
    MUST_RESOLVE = 2

    def test_retracted_words_do_not_survive_the_full_pipeline(self) -> None:
        for heard, must_vanish in REPAIRED:
            with self.subTest(heard=heard[:40]):
                outputs = [process_dictation(heard, self.config).text for _ in range(self.ATTEMPTS)]
                resolved = [out for out in outputs if must_vanish not in out]
                self.assertGreaterEqual(
                    len(resolved), self.MUST_RESOLVE,
                    f"{must_vanish!r} was retracted but survived "
                    f"{self.ATTEMPTS - len(resolved)} of {self.ATTEMPTS} attempts. "
                    f"Outputs: {outputs}",
                )

    def test_the_local_path_stays_fast_and_does_not_call_a_model(self) -> None:
        """Speculative delivery pastes this first, so it has to be cheap."""
        import time
        started = time.perf_counter()
        process_dictation(REPAIRED[0][0], self.config, local_only=True)
        elapsed_ms = (time.perf_counter() - started) * 1000
        self.assertLess(elapsed_ms, 250, "the immediate paste must not wait on anything slow")


if __name__ == "__main__":
    unittest.main()
