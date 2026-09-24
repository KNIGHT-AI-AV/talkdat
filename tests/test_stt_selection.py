from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from knight_flow.stt_registry import (
    PROVIDER_BY_ID,
    provider_settings,
    selected_model_id,
    selected_provider_id,
)
from knight_flow.stt_sessions import selected_stt_api_key


class ProviderSelectionSurvivesAStaleConfigTests(unittest.TestCase):
    """A config naming a provider this build no longer has must not crash.

    Twenty-four places index PROVIDER_BY_ID directly, and a bare dict lookup
    raises KeyError rather than falling back. That is survivable only because
    selected_provider_id and provider_settings both validate first, so an
    unknown id becomes "local" before it reaches any of them.

    It is worth pinning because the failure only appears on upgrade: someone
    who chose a provider that a later release drops opens the app and it dies
    on the way to the microphone, which reads as "the update broke it".
    """

    def test_an_unknown_provider_falls_back_to_local(self) -> None:
        self.assertEqual(selected_provider_id({"stt": {"provider": "a-provider-that-was-removed"}}), "local")

    def test_a_missing_or_empty_provider_falls_back_to_local(self) -> None:
        for config in ({}, {"stt": {}}, {"stt": {"provider": ""}}, {"stt": {"provider": "   "}}):
            with self.subTest(config=config):
                self.assertEqual(selected_provider_id(config), "local")

    def test_whatever_it_returns_can_always_be_indexed(self) -> None:
        """The property the twenty-four bare lookups actually depend on."""
        for provider in ("local", "deepgram", "unknown", "", None):
            with self.subTest(provider=provider):
                chosen = selected_provider_id({"stt": {"provider": provider}} if provider is not None else {})
                self.assertIn(chosen, PROVIDER_BY_ID)

    def test_settings_for_an_unknown_provider_do_not_raise(self) -> None:
        self.assertIsInstance(provider_settings({"stt": {"provider": "gone"}}), dict)


class ApiKeyResolutionOrderTests(unittest.TestCase):
    """Where the key comes from, in order, and why the order is that way.

    Getting this wrong is silent: the session starts, the provider rejects the
    request, and the person sees a transcription failure rather than "no key".
    """

    def config(self, **provider_settings_values) -> dict:
        return {"stt": {"provider": "deepgram", "providers": {"deepgram": provider_settings_values}}}

    def test_the_providers_own_setting_wins(self) -> None:
        with patch.dict(os.environ, {"DEEPGRAM_API_KEY": "from-environment"}, clear=False):
            config = self.config(api_key="your-settings-test-key")
            config["deepgram"] = {"api_key": "from-legacy"}
            self.assertEqual(selected_stt_api_key(config, "deepgram"), "your-settings-test-key")

    def test_the_legacy_deepgram_block_is_still_honoured(self) -> None:
        """Deepgram had a top-level config block before providers existed.
        Dropping it would silently sign out everyone who set a key that way."""
        config = self.config()
        config["deepgram"] = {"api_key": "from-legacy"}
        self.assertEqual(selected_stt_api_key(config, "deepgram"), "from-legacy")

    def test_the_environment_is_the_last_resort(self) -> None:
        with patch.dict(os.environ, {"DEEPGRAM_API_KEY": "from-environment"}, clear=False):
            self.assertEqual(selected_stt_api_key(self.config(), "deepgram"), "from-environment")

    def test_whitespace_is_not_a_key(self) -> None:
        """A key of spaces would pass a truthiness check and fail at the
        provider, which is the least useful place to find out."""
        config = self.config(api_key="   ")
        config["deepgram"] = {"api_key": "  "}
        with patch.dict(os.environ, {"DEEPGRAM_API_KEY": ""}, clear=False):
            self.assertEqual(selected_stt_api_key(config, "deepgram"), "")

    def test_a_local_provider_needs_no_key(self) -> None:
        self.assertEqual(selected_stt_api_key({"stt": {"provider": "local"}}, "local"), "")


class ModelSelectionTests(unittest.TestCase):
    def test_every_provider_resolves_to_some_model(self) -> None:
        """A provider that resolves to an empty model sends a request with no
        model and is refused, which looks like a broken account."""
        missing = []
        for provider_id in PROVIDER_BY_ID:
            model = selected_model_id({"stt": {"provider": provider_id}}, provider_id)
            if not str(model or "").strip():
                missing.append(provider_id)
        self.assertEqual(missing, [], f"providers with no default model: {missing}")


if __name__ == "__main__":
    unittest.main()
