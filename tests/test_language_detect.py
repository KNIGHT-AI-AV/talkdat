from __future__ import annotations

import unittest

from knight_flow.language_detect import detect_language, should_skip_translation


class BilingualAutoDetectIsConservativeTests(unittest.TestCase):
    """X-30. Off by default, and its ONLY power is to skip a translation when
    the utterance is already decisively in the target language. It never adds
    a language nobody chose, and short or mixed utterances change nothing."""

    def test_decisive_spanish_is_detected(self) -> None:
        text = "no quiero que ellos tienen el problema con esto para nada"
        self.assertEqual(detect_language(text, ("en", "es")), "es")

    def test_decisive_english_is_detected(self) -> None:
        text = "this is not what they should have been doing with the release"
        self.assertEqual(detect_language(text, ("en", "es")), "en")

    def test_short_utterances_refuse_to_judge(self) -> None:
        self.assertEqual(detect_language("hola amigo", ("en", "es")), "")
        self.assertEqual(detect_language("ship it now", ("en", "es")), "")

    def test_a_borrowed_phrase_does_not_flip_the_call(self) -> None:
        text = "we should have been saying gracias to the whole team for this"
        self.assertEqual(detect_language(text, ("en", "es")), "en")

    def test_skip_fires_only_for_target_language_speech(self) -> None:
        spanish = "no quiero que ellos tienen el problema con esto para nada"
        english = "this is not what they should have been doing with the release"
        self.assertTrue(should_skip_translation(spanish, source="en", target="es", enabled=True))
        self.assertFalse(should_skip_translation(english, source="en", target="es", enabled=True))

    def test_disabled_means_never(self) -> None:
        spanish = "no quiero que ellos tienen el problema con esto para nada"
        self.assertFalse(should_skip_translation(spanish, source="en", target="es", enabled=False))

    def test_same_source_and_target_never_skips(self) -> None:
        text = "this is not what they should have been doing with the release"
        self.assertFalse(should_skip_translation(text, source="en", target="en", enabled=True))


if __name__ == "__main__":
    unittest.main()
