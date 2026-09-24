"""Personal words must reach decoding, without editing a shared recognizer."""
import types
import unittest
from unittest.mock import patch

import numpy as np

from knight_flow import local_stt


class RecognitionDictionaryTests(unittest.TestCase):
    def test_whisper_receives_terms_before_decoding(self):
        calls = []
        def transcribe(audio, **kwargs):
            calls.append(kwargs)
            return [types.SimpleNamespace(text=" Mayowa arrived.")], None
        engine = types.SimpleNamespace(transcribe=transcribe)
        self.assertEqual(local_stt._recognize_faster_whisper(
            engine, np.zeros(160), "en-US", vocabulary=("Mayowa", "NavOrb")
        ), "Mayowa arrived.")
        self.assertEqual(calls[0]["hotwords"], "Mayowa, NavOrb")

    def test_only_personal_bounded_plain_terms_enter_bias(self):
        from knight_flow.recognition_bias import recognition_terms
        config = {"dictionary": {"words": ["Mayowa", "Mayowa", "some@example.com", "C:/private"],
                  "terms": [{"text": "NavOrb", "sounds_like": ["nav orb"]}, {"text": "x" * 100}]}}
        self.assertEqual(recognition_terms(config), ("Mayowa", "NavOrb"))
        self.assertEqual(recognition_terms({"dictionary": {"recognition_bias": False, "words": ["Mayowa"]}}), ())
        self.assertLessEqual(len(recognition_terms({"dictionary": {"words": ["Name " + chr(65+i//26) + chr(65+i%26) for i in range(100)]}})), 64)

    def test_acoustic_ambiguity_is_biased_but_blanks_and_strong_evidence_survive(self):
        from knight_flow.recognition_bias import PhraseBias
        vocab = {0: "<blk>", 1: " Ma", 2: "y", 3: "owa", 4: "over", 5: " dog"}
        bias = PhraseBias(vocab, ("Mayowa",), blank_id=0)
        ambiguous = np.array([-3., -3., -3., 0.4, 0.8, -3.])
        output = bias.apply(ambiguous, [1, 2])
        self.assertEqual(int(output.argmax()), 3)
        self.assertEqual(int(ambiguous.argmax()), 4, "Input logits are shared and must not be mutated")
        blank = ambiguous.copy(); blank[0] = 2.
        np.testing.assert_array_equal(bias.apply(blank, [1, 2]), blank)
        strong = ambiguous.copy(); strong[4] = 5.
        self.assertEqual(int(bias.apply(strong, [1, 2]).argmax()), 4)
        self.assertEqual(int(bias.apply(ambiguous, [5]).argmax()), 4)

    def test_per_call_adapter_never_mutates_shared_model_or_duration(self):
        from knight_flow.recognition_bias import with_transducer_bias
        class NemoConformerTdt:
            _vocab = {0:"<blk>", 1:" Ma", 2:"y", 3:"owa", 4:"over"}
            _blank_idx = 0
            def _decode(self, tokens, previous_state, encoder):
                return np.array([-3., -3., -3., .4, .8]), 2, previous_state
        original = types.SimpleNamespace(asr=NemoConformerTdt())
        adapted = with_transducer_bias(original, ("Mayowa",))
        self.assertIsNot(adapted, original)
        self.assertIsNot(adapted.asr, original.asr)
        state = object()
        logits, step, next_state = adapted.asr._decode([1, 2], state, None)
        self.assertEqual(int(logits.argmax()), 3)
        self.assertEqual(step, 2)
        self.assertIs(next_state, state)
        self.assertEqual(int(original.asr._decode([1, 2], state, None)[0].argmax()), 4)
        self.assertIs(with_transducer_bias(original, ()), original)
        unsupported = types.SimpleNamespace(asr=object())
        self.assertIs(with_transducer_bias(unsupported, ("Mayowa",)), unsupported)

    def test_shared_two_letter_prefix_is_not_evidence_for_a_personal_name(self):
        from knight_flow.recognition_bias import PhraseBias
        bias = PhraseBias({0:"<blk>", 1:" Co", 2:"m", 3:"n", 4:"estor"}, ("Comestor",), blank_id=0)
        logits = np.array([-3., -3., .4, .8, -3.])
        self.assertEqual(int(bias.apply(logits, [1]).argmax()), 3)

    def test_real_batch_call_carries_personal_terms_to_local_transcriber(self):
        from knight_flow.stt_sessions import transcribe_pcm
        from knight_flow.config import DEFAULT_CONFIG
        import copy
        config = copy.deepcopy(DEFAULT_CONFIG)
        config["dictionary"] = {"words": ["Mayowa"], "terms": [{"text":"NavOrb"}]}
        with patch.object(local_stt, "transcribe", return_value="Mayowa.") as call:
            self.assertEqual(transcribe_pcm(config, b"\x00\x00" * 160, 16000, 1, provider_id="local"), "Mayowa.")
        self.assertEqual(call.call_args.kwargs.get("vocabulary"), ("Mayowa", "NavOrb"))


if __name__ == "__main__":
    unittest.main()
