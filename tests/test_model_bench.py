"""T6: the bench's arithmetic and decision, on fake engines. No model is loaded,
no audio is rendered and nothing is played; the real two-engine run on one
Windows and one Mac machine waits for a permitted idle window.
"""
from __future__ import annotations

import unittest

from knight_flow.model_bench import (
    DEFAULT_MAX_WER, PASSAGE, bench_engine, may_run, recommend, tts_command, word_error_rate,
)


class WordErrorRate(unittest.TestCase):
    def test_counts(self):
        self.assertEqual(word_error_rate("send the report", "send the report"), 0.0)
        self.assertAlmostEqual(word_error_rate("send the report", "send a report"), 1 / 3)
        self.assertAlmostEqual(word_error_rate("send the report", "send report"), 1 / 3)
        self.assertAlmostEqual(word_error_rate("send the report", "please send the report"), 1 / 3)
        self.assertEqual(word_error_rate("", ""), 0.0)
        self.assertEqual(word_error_rate("", "noise"), 1.0)

    def test_case_and_punctuation_do_not_count(self):
        self.assertEqual(word_error_rate("Send the report, please.", "send the report please"), 0.0)
        self.assertEqual(word_error_rate(PASSAGE, PASSAGE.upper()), 0.0)


class OneEngine(unittest.TestCase):
    def test_cold_and_warm_are_separate(self):
        # Each call takes the next step: cold 2.0 s, then warm 0.5 s each.
        durations = iter([2.0, 0.5, 0.5, 0.5])
        state = {"t": 0.0}

        def clock():
            return state["t"]

        def transcribe():
            state["t"] += next(durations)
            return PASSAGE

        result = bench_engine("parakeet", transcribe, clock=clock, memory=lambda: 812.0)
        self.assertFalse(result.failed)
        self.assertAlmostEqual(result.cold_ms, 2000.0)
        self.assertEqual(result.warm_ms, [500.0, 500.0, 500.0])
        self.assertEqual(result.wer, 0.0)
        self.assertEqual(result.peak_memory_mb, 812.0)

    def test_a_failing_engine_is_a_result(self):
        def transcribe():
            raise RuntimeError("GetElementType is not implemented")

        result = bench_engine("canary", transcribe)
        self.assertTrue(result.failed)
        self.assertIn("GetElementType", result.detail)


class TheRecommendation(unittest.TestCase):
    def results(self):
        def engine(model_id, ms, text):
            state = {"t": 0.0}

            def clock():
                return state["t"]

            def transcribe():
                state["t"] += ms / 1000.0
                return text
            return bench_engine(model_id, transcribe, clock=clock)

        sloppy = PASSAGE.replace("three copies", "free coffees").replace("Tuesday", "Thursday")
        return [engine("fast-sloppy", 120, sloppy + " uh um"), engine("middle", 400, PASSAGE),
                engine("slow-perfect", 900, PASSAGE), bench_engine("broken", lambda: 1 / 0)]

    def test_the_fastest_model_that_meets_the_gate(self):
        recommendation = recommend(self.results(), max_wer=DEFAULT_MAX_WER)
        self.assertEqual(recommendation.model_id, "middle")
        self.assertEqual(recommendation.meets, ("middle", "slow-perfect"))
        self.assertEqual(recommendation.misses, ("fast-sloppy",))
        self.assertEqual(recommendation.failed, ("broken",))

    def test_a_looser_gate_admits_the_sloppy_one(self):
        self.assertEqual(recommend(self.results(), max_wer=0.5).model_id, "fast-sloppy")

    def test_nothing_meets_a_strict_gate_without_a_perfect_engine(self):
        results = [result for result in self.results() if result.model_id == "fast-sloppy"]
        recommendation = recommend(results, max_wer=0.01)
        self.assertEqual(recommendation.model_id, "")
        self.assertEqual(recommendation.misses, ("fast-sloppy",))


class WhenItMayRun(unittest.TestCase):
    def test_only_on_request_and_never_over_work(self):
        self.assertEqual(may_run(take_active=False, person_requested=True, audio_work_active=False), "")
        self.assertTrue(may_run(take_active=False, person_requested=False, audio_work_active=False))
        self.assertTrue(may_run(take_active=True, person_requested=True, audio_work_active=False))
        self.assertTrue(may_run(take_active=False, person_requested=True, audio_work_active=True))

    def test_the_passage_is_rendered_to_a_file_never_played(self):
        windows = tts_command("win32", "C:/t/passage.txt", "C:/t/passage.wav")
        self.assertIn("SetOutputToWaveFile", windows[-1])
        self.assertNotIn("SetOutputToDefaultAudioDevice", windows[-1])
        mac = tts_command("darwin", "/t/passage.txt", "/t/passage.wav")
        self.assertIn("-o", mac)
        self.assertIsNone(tts_command("linux", "a", "b"))


if __name__ == "__main__":
    unittest.main()
