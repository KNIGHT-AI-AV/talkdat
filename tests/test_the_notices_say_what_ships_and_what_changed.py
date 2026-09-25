"""X-762 (IP audit, 2026-09-24): the notices say what ships and what changed.

NOTICE said "Models are not included" and THIRD_PARTY_NOTICES.md said model
weights are not "embedded in any installer". The 0.4.167 installer carries
faster_whisper/assets/silero_vad_v6.onnx, a model under MIT (Silero Team).

CC BY 4.0 section 3(a)(1)(B) asks whoever shares the model to "indicate if
You modified the Licensed Material and retain an indication of any previous
modifications" (https://creativecommons.org/licenses/by/4.0/legalcode). Talk
DAT! downloads istupakov's ONNX conversion of Parakeet with int8 weights
(onnx_asr resolves nemo-parakeet-tdt-0.6b-v3 to
istupakov/parakeet-tdt-0.6b-v3-onnx; knight_flow/local_stt.py asks for int8),
so the notice now says so in those words.
"""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def flat(name: str) -> str:
    return " ".join((ROOT / name).read_text(encoding="utf-8").split())


class TheNoticeTests(unittest.TestCase):
    def test_it_no_longer_says_no_model_ships(self) -> None:
        self.assertNotIn("Models are not included.", flat("NOTICE"))
        self.assertNotIn("Model weights are not stored in this repository or embedded in any installer",
                         flat("THIRD_PARTY_NOTICES.md"))

    def test_it_credits_the_model_that_does_ship(self) -> None:
        for name in ("NOTICE", "THIRD_PARTY_NOTICES.md"):
            with self.subTest(file=name):
                text = flat(name)
                self.assertIn("Silero VAD", text)
                self.assertIn("Silero Team", text)
                self.assertIn("MIT", text)

    def test_parakeet_says_what_changed_and_who_changed_it(self) -> None:
        for name in ("NOTICE", "THIRD_PARTY_NOTICES.md"):
            with self.subTest(file=name):
                text = flat(name)
                self.assertIn("Changes:", text)
                self.assertIn("ONNX conversion of NVIDIA's model, with int8 quantized weights, made by istupakov", text)
                self.assertIn("Talk DAT! does not change", text)
                self.assertIn("https://creativecommons.org/licenses/by/4.0/", text)
                self.assertIn("https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3", text)

    def test_the_facts_behind_the_words_still_hold(self) -> None:
        source = (ROOT / "knight_flow" / "local_stt.py").read_text(encoding="utf-8")
        self.assertIn('quantization = "int8" if model.engine_id.startswith(("nemo-", "istupakov/")) else None', source)
        try:
            from onnx_asr import resolver
        except ImportError:
            self.skipTest("onnx-asr is not installed here")
        table = next(value for value in vars(resolver).values()
                     if isinstance(value, dict) and "nemo-parakeet-tdt-0.6b-v3" in value)
        self.assertEqual(table["nemo-parakeet-tdt-0.6b-v3"], "istupakov/parakeet-tdt-0.6b-v3-onnx")

    def test_the_new_parts_are_in_the_human_summary(self) -> None:
        text = flat("THIRD_PARTY_NOTICES.md")
        for needle in ("PortAudio", "PyInstaller bootloader", "Bootloader Exception", ".NET Standard facade",
                       "ASIO builds of PortAudio"):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)


if __name__ == "__main__":
    unittest.main()
