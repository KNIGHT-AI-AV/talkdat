from __future__ import annotations

import unittest

from knight_flow.stt_registry import (
    FLAGSHIP_CLOUD_PROVIDER_IDS,
    PROVIDER_BY_ID,
    activation_provider_id,
    flagship_cloud_provider_labels,
    provider_is_ready,
)


class ProviderLinkTests(unittest.TestCase):
    def test_only_wired_and_local_providers_can_be_activated(self) -> None:
        self.assertTrue(provider_is_ready("deepgram"))
        self.assertTrue(provider_is_ready("openai"))
        self.assertTrue(provider_is_ready("local"))
        self.assertTrue(provider_is_ready("xai"))
        self.assertTrue(provider_is_ready("smallest"))
        self.assertTrue(provider_is_ready("soniox"))
        self.assertFalse(provider_is_ready("does-not-exist"))

    def test_pending_provider_preview_preserves_current_working_route(self) -> None:
        self.assertEqual(activation_provider_id("xai", "deepgram"), "xai")
        self.assertEqual(activation_provider_id("cohere", "local"), "local")
        self.assertEqual(activation_provider_id("openai", "deepgram"), "openai")
        self.assertEqual(activation_provider_id("does-not-exist", "does-not-exist"), "local")

    def test_flagship_cloud_providers_have_login_and_key_links(self) -> None:
        provider_ids = [
            "deepgram",
            "openai",
            "elevenlabs",
            "xai",
            "smallest",
            "soniox",
            "groq",
            "mistral",
            "assemblyai",
            "google_gemini",
            "google_cloud",
            "azure",
            "aws",
            "speechmatics",
            "cohere",
            "gladia",
            "rev_ai",
            "nvidia",
            "alibaba",
        ]
        for provider_id in provider_ids:
            with self.subTest(provider_id=provider_id):
                provider = PROVIDER_BY_ID[provider_id]
                self.assertTrue(provider.login_url.startswith("https://"))
                self.assertTrue(provider.api_keys_url.startswith("https://"))
                self.assertTrue(provider.docs_url.startswith("https://"))

    def test_onboarding_flagship_cloud_catalog_has_ten_working_choices(self) -> None:
        self.assertEqual(len(FLAGSHIP_CLOUD_PROVIDER_IDS), 10)
        self.assertEqual(len(flagship_cloud_provider_labels()), 10)
        for provider_id in FLAGSHIP_CLOUD_PROVIDER_IDS:
            with self.subTest(provider_id=provider_id):
                self.assertTrue(provider_is_ready(provider_id))

    def test_local_provider_does_not_need_cloud_login(self) -> None:
        provider = PROVIDER_BY_ID["local"]
        self.assertEqual(provider.login_url, "")
        self.assertEqual(provider.api_keys_url, "")

    def test_active_model_pickers_hide_retired_generations(self) -> None:
        retired_by_provider = {
            "elevenlabs": {"scribe_v1"},
            "google_gemini": {"gemini-2.5-pro", "gemini-2.5-flash"},
            "assemblyai": {"universal-2", "universal"},
            "deepgram": {"nova-2", "enhanced", "base", "whisper"},
            "google_cloud": {"chirp", "latest_long", "latest_short"},
            "azure": {"mai-transcribe-1"},
            "gladia": {"solaria-1"},
        }
        for provider_id, retired_ids in retired_by_provider.items():
            picker_ids = {model.id for model in PROVIDER_BY_ID[provider_id].models}
            with self.subTest(provider=provider_id):
                self.assertTrue(retired_ids.isdisjoint(picker_ids))

        gemini_ids = {model.id for model in PROVIDER_BY_ID["google_gemini"].models}
        self.assertIn("gemini-3.6-flash", gemini_ids)
        self.assertIn("gemini-3.5-flash-lite", gemini_ids)


if __name__ == "__main__":
    unittest.main()
