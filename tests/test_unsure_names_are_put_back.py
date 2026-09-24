"""X-608: a name the recognizer was unsure of is put back (commandments 6, 7, 99).

Measured on Parakeet on the owner's PC, 2026-09-24: "Kaelyn" came back as
"Kalen" at 0.54 and "Siobhan" as "Syabin" at 0.33, while "clean" and
"kitchen" scored 1.0 -- and "Loop" scored 0.38. The repair needs both the
recognizer's doubt and a name that sounds the same, with three sounds or more.
"""
from __future__ import annotations

import math
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from knight_flow import local_stt
from knight_flow.learned_words import learn_spelling, misheard_form
from knight_flow.name_repair import repair_names, sound_skeleton
from knight_flow.text_pipeline import ProcessedText, complete_prepared_dictation


def _stamped(pieces):
    """A TimestampedResult shape: (token, probability) pairs."""
    return SimpleNamespace(text="".join(token for token, _ in pieces).strip(),
                           tokens=[token for token, _ in pieces],
                           logprobs=[math.log(p) for _, p in pieces])


class TheRecognizerSaysHowSureItWasTests(unittest.TestCase):
    def test_a_word_is_its_least_certain_letter_bearing_piece(self):
        heard = local_stt.word_confidence(_stamped([
            (" Can", 0.99), (" you", 1.0), (" for", 1.0), ("ward", 1.0), (" to", 1.0),
            (" K", 0.541), ("alen", 0.977), ("?", 0.2), (" Lo", 0.377), ("op", 0.995),
            (" in", 0.99), (" ", 0.999), ("2", 0.3), ("6", 0.9), (".", 0.85)]))
        self.assertAlmostEqual(heard["kalen"], 0.541, places=3, msg="the ? is not the word")
        self.assertAlmostEqual(heard["forward"], 1.0, places=3)
        self.assertAlmostEqual(heard["loop"], 0.377, places=3)
        self.assertNotIn("26", heard)
        self.assertNotIn("", heard)

    def test_the_same_word_twice_keeps_its_lower_score(self):
        heard = local_stt.word_confidence(_stamped([(" Kalen", 0.9), (" and", 1.0), (" Kalen", 0.4)]))
        self.assertAlmostEqual(heard["kalen"], 0.4, places=3)

    def test_asked_for_confidence_the_engine_decodes_with_timestamps(self):
        class Engine:
            def __init__(self):
                self.plain = 0

            def recognize(self, audio, sample_rate):
                self.plain += 1
                return "plain"

            def with_timestamps(self):
                return SimpleNamespace(recognize=lambda audio, sample_rate: _stamped([(" Kalen", 0.5)]))

        engine, heard = Engine(), {}
        self.assertEqual(local_stt._recognize_once(engine, [], 16000, heard), "Kalen")
        self.assertAlmostEqual(heard["kalen"], 0.5, places=3)
        self.assertEqual(local_stt._recognize_once(engine, [], 16000, None), "plain")
        self.assertEqual(engine.plain, 1, "no confidence asked, no timestamped decode")

    def test_an_engine_without_timestamps_still_answers(self):
        engine, heard = SimpleNamespace(recognize=lambda audio, sample_rate: "words"), {}
        self.assertEqual(local_stt._recognize_once(engine, [], 16000, heard), "words")
        self.assertEqual(heard, {})

    def test_the_session_keeps_the_takes_confidence_but_not_the_live_tails(self):
        from knight_flow.stt_sessions import BatchSTTSession

        session = BatchSTTSession.__new__(BatchSTTSession)
        session.word_confidence, session._audio = {}, bytearray(b"\0\0")
        import threading

        session._confidence_lock = threading.Lock()
        session.model, session.sample_rate, session.channels, session.language = "m", 16000, 1, "en"
        session.extra, session.recognition_vocabulary, session._safe_status = {}, (), lambda *_: None

        def transcribe(**kwargs):
            if kwargs.get("word_confidence") is not None:
                kwargs["word_confidence"]["kalen"] = 0.5
            return "Kalen"

        with patch.object(local_stt, "transcribe", side_effect=transcribe):
            session._transcribe_local(b"", record=False)
            self.assertEqual(session.word_confidence, {})
            session._transcribe_local(b"")
        self.assertEqual(session.word_confidence, {"kalen": 0.5})


class AnUnsureNameIsPutBackTests(unittest.TestCase):
    def config(self, confidence, words=("Kaelyn", "Siobhan"), **extra):
        return {"dictionary": {"words": list(words)}, "_asr_confidence": confidence, **extra}

    def test_the_battery_names(self):
        self.assertEqual(repair_names("Can you forward this to kaylin?", self.config({"kaylin": 0.41})),
                         "Can you forward this to Kaelyn?")
        self.assertEqual(repair_names("Loop in shivon and Brennan.", self.config({"shivon": 0.38})),
                         "Loop in Siobhan and Brennan.")
        self.assertEqual(repair_names("Can you ask Kalen's team?", self.config({"kalen": 0.54})),
                         "Can you ask Kaelyn's team?")

    def test_a_word_it_heard_clearly_is_never_touched(self):
        self.assertEqual(repair_names("Please clean the kitchen.", self.config({"clean": 1.0})),
                         "Please clean the kitchen.")
        self.assertEqual(repair_names("We launched in 2026.",
                                      self.config({"launched": 0.97}, words=("LinkedIn",))),
                         "We launched in 2026.")

    def test_no_confidence_means_no_repair(self):
        self.assertEqual(repair_names("ask kalen", {"dictionary": {"words": ["Kaelyn"]}}), "ask kalen")

    def test_a_two_sound_name_never_takes_an_unsure_word(self):
        self.assertEqual(sound_skeleton("Lupe"), sound_skeleton("loop"))
        self.assertEqual(repair_names("Loop in the team.", self.config({"loop": 0.38}, words=("Lupe",))),
                         "Loop in the team.")

    def test_two_names_that_sound_alike_veto_each_other(self):
        self.assertEqual(sound_skeleton("Colin"), sound_skeleton("Kaelyn"))
        self.assertEqual(repair_names("ask kalen", self.config({"kalen": 0.4}, words=("Kaelyn", "Colin"))),
                         "ask kalen")

    def test_screen_names_count_unless_screen_context_is_off(self):
        on = {"dictionary": {}, "_screen_names": ["Siobhan Kelly"], "_asr_confidence": {"shivon": 0.4}}
        self.assertEqual(repair_names("thanks shivon", on), "thanks Siobhan")
        off = {**on, "dictionary": {"screen_context": False}}
        self.assertEqual(repair_names("thanks shivon", off), "thanks shivon")

    def test_the_repair_runs_at_completion_and_never_in_a_terminal(self):
        processed = lambda: ProcessedText(original="ask kalen", text="Ask kalen.", send_enter=False, route="rules")
        config = self.config({"kalen": 0.4})
        self.assertEqual(complete_prepared_dictation(processed(), config).text, "Ask Kaelyn.")
        self.assertEqual(complete_prepared_dictation(processed(), {**config, "_field": "console"}).text,
                         "Ask kalen.")


class AHandFixTeachesTheMishearingTests(unittest.TestCase):
    def test_the_fix_is_paired_with_the_unsure_word_it_replaced(self):
        self.assertEqual(misheard_form("Kaelyn", "Can you forward this to Kalen?", {"kalen": 0.54}), "kalen")
        config: dict = {}
        self.assertTrue(learn_spelling("Kaelyn", config, "Can you forward this to Kalen?", {"kalen": 0.54}))
        self.assertEqual(config["dictionary"]["terms"],
                         [{"text": "Kaelyn", "sounds_like": ["kalen"], "learned": True}])

    def test_a_word_it_was_sure_of_is_never_made_an_alias(self):
        self.assertEqual(misheard_form("Kaelyn", "Please clean the kitchen.", {"clean": 1.0}), "")
        self.assertEqual(misheard_form("Kaelyn", "Please clean the kitchen.", {}), "")
        config: dict = {}
        self.assertTrue(learn_spelling("Kaelyn", config, "Please clean the kitchen.", {"clean": 1.0}))
        self.assertEqual(config["dictionary"]["terms"],
                         [{"text": "Kaelyn", "sounds_like": [], "learned": True}])

    def test_two_candidates_are_one_too_many(self):
        self.assertEqual(misheard_form("Kaelyn", "Kalen and Kaylin", {"kalen": 0.5, "kaylin": 0.5}), "")


if __name__ == "__main__":
    unittest.main()
