"""X-609: a segment seam is a pause, not a sentence end.

A long take is transcribed in segments that close on a 0.45 s pause, and the
recognizer ends every piece of audio as if a sentence ended there. The owner's
58-second take of 2026-09-23 came back with "PC and Mac only. for this project"
and "building necessarily And then make sure". The seam is repaired from each
piece's own punctuation (knight_flow/progressive.join_segment_texts).
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from knight_flow.progressive import join_segment_texts

ROOT = Path(__file__).resolve().parents[1]


class TheSeamIsRepairedTests(unittest.TestCase):
    def test_a_full_stop_before_a_lowercase_continuation_goes(self):
        self.assertEqual(join_segment_texts(["And we are PC and Mac only.", "for this project."]),
                         "And we are PC and Mac only for this project.")

    def test_a_capital_after_an_unfinished_piece_goes(self):
        self.assertEqual(join_segment_texts(["what we were building necessarily", "And then make sure."]),
                         "what we were building necessarily and then make sure.")

    def test_a_real_sentence_end_stays(self):
        self.assertEqual(join_segment_texts(["from People Ops.", "I'd like all of it."]),
                         "from People Ops. I'd like all of it.")
        self.assertEqual(join_segment_texts(["from finance.", "The signed contracts."]),
                         "from finance. The signed contracts.")

    def test_a_name_after_an_unfinished_piece_keeps_its_capital(self):
        self.assertEqual(join_segment_texts(["we met", "Sarah at noon."]), "we met Sarah at noon.")

    def test_abbreviations_questions_and_trailing_dots_stay(self):
        self.assertEqual(join_segment_texts(["I spoke to Dr.", "smith today"]), "I spoke to Dr. smith today")
        self.assertEqual(join_segment_texts(["did it ship?", "and when"]), "did it ship? and when")
        self.assertEqual(join_segment_texts(["so...", "anyway"]), "so... anyway")

    def test_empty_pieces_are_skipped(self):
        self.assertEqual(join_segment_texts(["", "Hello.", "  ", "there"]), "Hello there")
        self.assertEqual(join_segment_texts([]), "")

    def test_the_session_joins_its_pieces_this_way(self):
        source = (ROOT / "knight_flow" / "stt_sessions.py").read_text(encoding="utf-8")
        self.assertIn("join_segment_texts([*pieces, tail_text])", source)
        self.assertNotIn('" ".join(piece for piece in [*pieces, tail_text] if piece)', source)


class TheAudioLaneCoversTheVoicedCasesTests(unittest.TestCase):
    def test_every_voiced_case_is_scripted_except_the_hardware_timing_ones(self):
        from tests import audio_battery
        from tests.commandment_battery import SKIP_AUDIO, load_cases, plan

        voiced = {case["id"] for case in load_cases() if plan(case) == ("skip", SKIP_AUDIO)}
        self.assertEqual(set(audio_battery.SCRIPTS) - voiced, set(), "a script for a case that is not voiced")
        self.assertEqual(voiced - set(audio_battery.SCRIPTS), {"C003-pos", "C003-neg"},
                         "a voiced case the audio lane does not run")

    def test_the_history_cases_hold_what_the_app_would(self):
        from tests import audio_battery

        cases = {case["id"]: case for case in json.loads(
            (ROOT / "tests" / "commandment_cases.json").read_text(encoding="utf-8"))}
        self.assertIn("accepted", cases["C099-pos"]["context"]["history"])
        self.assertEqual(audio_battery.HISTORY["C099-pos"]["terms"][0]["sounds_like"], ["kaylin"])
        self.assertIn("dismissed", cases["C099-neg"]["context"]["history"])
        self.assertEqual(audio_battery.HISTORY["C099-neg"], {"learn_tombstones": ["kaelyn"]})


if __name__ == "__main__":
    unittest.main()
