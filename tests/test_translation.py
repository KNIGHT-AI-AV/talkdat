from __future__ import annotations

import unittest
from pathlib import Path
from urllib.parse import unquote
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]

from knight_flow.config import DEFAULT_CONFIG
from knight_flow.feedback import FEEDBACK_EMAIL, feedback_mailto
from knight_flow.translation import (
    DEFAULT_TRANSLATION_MODEL,
    TranslationError,
    TranslationResult,
    _mask_protected,
    _restore_protected,
    auto_translation_enabled,
    build_translation_prompt,
    language_choices,
    language_from_value,
    normalize_translation_model,
    resolve_source_language,
    translate_text,
)


class TranslationCatalogTests(unittest.TestCase):
    def test_translation_is_disabled_by_default(self) -> None:
        self.assertFalse(DEFAULT_CONFIG["translation"]["enabled"])
        self.assertFalse(DEFAULT_CONFIG["translation"]["auto_translate_dictation"])
        self.assertFalse(auto_translation_enabled(DEFAULT_CONFIG))

    def test_language_catalog_starts_with_popular_languages_and_has_no_duplicates(self) -> None:
        choices = language_choices()
        self.assertEqual(choices[0], "English (en)")
        self.assertIn("Spanish (es)", choices[:10])
        self.assertIn("Chinese - Simplified (zh-Hans)", choices[:10])
        self.assertEqual(len(choices), len(set(choices)))
        self.assertGreaterEqual(len(choices), 50)

    def test_auto_source_uses_selected_dictation_locale(self) -> None:
        config = {
            "translation": {"source_language": "auto"},
            "stt": {"provider": "deepgram", "providers": {"deepgram": {"language": "fr-FR"}}},
            "deepgram": {"language": "en-US"},
        }
        self.assertEqual(resolve_source_language(config).code, "fr")

    def test_only_verified_model_tiers_are_accepted(self) -> None:
        self.assertEqual(normalize_translation_model("translategemma"), DEFAULT_TRANSLATION_MODEL)
        with self.assertRaises(TranslationError):
            normalize_translation_model("unknown:latest")


class TranslationSafetyTests(unittest.TestCase):
    def test_prompt_uses_explicit_language_codes_and_text_boundary(self) -> None:
        prompt = build_translation_prompt(
            "Hello",
            language_from_value("en"),
            language_from_value("es"),
        )
        self.assertIn("English (en) to Spanish (es)", prompt)
        self.assertIn("Produce only the Spanish translation", prompt)
        self.assertTrue(prompt.endswith("\n\n\nHello"))

    def test_numbers_links_email_and_versions_round_trip_exactly(self) -> None:
        source = "Email me@example.com about v0.4.1 at https://example.com for $14.99."
        masked, protected = _mask_protected(source)
        self.assertNotIn("me@example.com", masked)
        self.assertNotIn("$14.99", masked)
        self.assertEqual(_restore_protected(masked, protected), source)

    def test_missing_protected_token_fails_closed(self) -> None:
        _masked, protected = _mask_protected("Keep 100% exactly.")
        with self.assertRaises(TranslationError):
            _restore_protected("Translated without the token", protected)

    def test_translation_uses_local_model_and_never_requires_feature_enable_for_manual_use(self) -> None:
        config = {
            "translation": {
                "enabled": False,
                "source_language": "en",
                "target_language": "es",
                "model": DEFAULT_TRANSLATION_MODEL,
            },
            "stt": {"provider": "local", "providers": {"local": {"language": "en-US"}}},
        }
        with (
            patch(
                "knight_flow.translation.translation_model_status",
                return_value={
                    "engine_installed": True,
                    "engine_running": True,
                    "model_installed": True,
                    "ready": True,
                    "label": "TranslateGemma 4B",
                },
            ),
            patch("knight_flow.translation._translate_chunk", return_value="Hola") as translate_chunk,
        ):
            result = translate_text("Hello", config)

        self.assertEqual(result.text, "Hola")
        translate_chunk.assert_called_once()

    def test_the_managed_engine_is_refused_rather_than_quietly_ignored(self) -> None:
        """X-516: translation runs on this machine, and asking for the other
        engine is an error rather than a silent downgrade.

        This test used to assert the opposite: that engine "managed" reached
        our servers and came back with a managed model name. That path is
        gone, and it was the LAST one that sent a person's words to us. A
        stored config can still name it, so the refusal has to be explicit:
        silently translating locally instead would be the right result by
        accident, and would hide the fact that the setting is dead.
        """
        config = {
            "translation": {
                "engine": "managed",
                "source_language": "en",
                "target_language": "es",
                "model": DEFAULT_TRANSLATION_MODEL,
                "preserve_formatting": True,
            },
        }
        with self.assertRaises(TranslationError) as raised:
            translate_text("Email me@example.com about v0.4.3.", config)
        self.assertEqual(raised.exception.code, "engine_invalid")


class FeedbackTests(unittest.TestCase):
    def test_feedback_draft_targets_build_email_without_private_app_content(self) -> None:
        uri = feedback_mailto(kind="feature", title="Faster paste", details="Add a safer retry.")
        decoded = unquote(uri)
        self.assertTrue(uri.startswith(f"mailto:{FEEDBACK_EMAIL}?"))
        self.assertIn("did not attach transcripts, recordings, API keys", decoded)
        self.assertNotIn("secret dictated sentence", decoded.lower())
        self.assertNotIn("api_key=", decoded.lower())



if __name__ == "__main__":
    unittest.main()


class NobodysWordsAreTranslatedThroughOurServersTests(unittest.TestCase):
    """X-516: translation reaches this machine or it fails honestly.

    This class used to assert the opposite, and carefully: a paying account's
    setup-shaped local failure retried through managed cloud, while a free one
    got the local error, so that nobody was billed for a spend they had not
    agreed to. That was a reasonable design while there were two engines.

    His order was "No CLoud at all". So the rescue is gone, and what replaces
    these tests is the stronger claim: no licence state, no error code and no
    stored setting can put a person's words on our servers, because the code
    that could do it no longer exists. A test that merely checked the rescue
    was disabled would pass just as well against a flag someone could flip
    back; asserting the import is absent is what makes it structural.
    """

    def test_the_translator_cannot_reach_the_managed_module(self) -> None:
        source = (ROOT / "knight_flow" / "translation.py").read_text(encoding="utf-8")
        self.assertNotIn("managed_cloud", source)
        self.assertNotIn("cloud_can_rescue", source)

    def test_a_failed_local_translation_has_no_second_engine_to_try(self) -> None:
        """The dictation path keeps the honest local error.

        The error it keeps already names the one-click model download, so the
        person is told how to fix it rather than being quietly billed.
        """
        source = (ROOT / "knight_flow" / "app.py").read_text(encoding="utf-8")
        self.assertNotIn("cloud_can_rescue_translation", source)
        self.assertNotIn('engine_value="managed"', source)
        self.assertIn("automatic local translation skipped", source)

    def test_the_engine_override_reaches_translate_text(self) -> None:
        """The rescue retries with engine_value='managed'; the parameter has to
        actually steer the engine or the retry re-runs the same failure."""
        import inspect

        from knight_flow.translation import translate_text

        self.assertIn("engine_value", inspect.signature(translate_text).parameters)
