from __future__ import annotations

import unittest

from knight_flow import local_stt, stt_registry, stt_sessions

# Verified against https://openrouter.ai/api/v1/models?output_modalities=transcription
# on 2026-08-04. Model slugs are not guessable -- qwen3-asr-flash carries a date
# suffix, parakeet carries its parameter count -- so they are pinned here and any
# drift in the registry fails loudly rather than 404ing at dictation time.
VERIFIED_MODEL_IDS = frozenset({
    "deepgram/nova-3",
    "nvidia/parakeet-tdt-0.6b-v3",
    "qwen/qwen3-asr-flash-2026-02-10",
    "mistralai/voxtral-mini-transcribe",
    "fish-audio/transcribe-1",
    "x-ai/grok-stt-1.0",
    "microsoft/mai-transcribe-1.5",
    "google/chirp-3",
    "openai/gpt-4o-transcribe",
    "openai/gpt-4o-mini-transcribe",
    "openai/whisper-1",
    "openai/whisper-large-v3",
    "openai/whisper-large-v3-turbo",
})


class OpenRouterProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = stt_registry.PROVIDER_BY_ID.get("openrouter")

    def test_the_provider_is_registered(self) -> None:
        self.assertIsNotNone(self.provider, "openrouter provider is missing from PROVIDERS")

    def test_it_routes_through_openrouter_with_one_key(self) -> None:
        self.assertEqual(self.provider.env_key, "OPENROUTER_API_KEY")

    def test_the_composed_transcription_url_is_exactly_right(self) -> None:
        """The OpenAI-compatible transport appends /v1/audio/transcriptions.

        OpenRouter's endpoint is https://openrouter.ai/api/v1/audio/transcriptions,
        so api_base must stop at /api. Storing the documented base verbatim
        (.../api/v1) would compose a doubled /v1/v1/ path and 404 on every
        dictation, which no catalogue-shape test would catch.
        """
        self.assertEqual(
            self.provider.api_base + "/v1/audio/transcriptions",
            "https://openrouter.ai/api/v1/audio/transcriptions",
        )

    def test_it_reuses_the_openai_compatible_adapter(self) -> None:
        """OpenRouter accepts OpenAI-style multipart, so it needs no new transport."""
        self.assertEqual(self.provider.api_kind, "openai_batch")


    def test_it_is_batch_only(self) -> None:
        """OpenRouter's transcription endpoint documents no streaming.

        Advertising streaming here would make the overlay offer a live-partial
        mode that silently never produces partials.
        """
        self.assertFalse(self.provider.supports_streaming)
        self.assertTrue(self.provider.supports_batch)
        for model in self.provider.models:
            self.assertEqual(model.mode, "batch", f"{model.id} is not batch")

    def test_every_model_id_is_a_verified_openrouter_slug(self) -> None:
        for model in self.provider.models:
            self.assertIn(
                model.id,
                VERIFIED_MODEL_IDS,
                f"{model.id!r} is not a slug returned by the OpenRouter models API",
            )

    def test_the_accuracy_leader_is_offered_and_is_not_nova_3(self) -> None:
        """The paid tier needs a model that genuinely beats the free local one.

        Artificial Analysis AA-WER, read 2026-08-04: MAI-Transcribe 1.5 is 2.4%,
        the free local Parakeet TDT 0.6B v3 is 4.5%, and Deepgram Nova-3 is 5.2%
        -- worse than local. Nova-3 leads on speed (505x), not accuracy, and an
        earlier revision of this file had it labelled "most accurate" from a
        secondary blog source. Assert the label sits on the model that measures
        best, so that mistake cannot come back.
        """
        ids = {model.id for model in self.provider.models}
        self.assertIn("microsoft/mai-transcribe-1.5", ids)

        accuracy_labelled = [m for m in self.provider.models if "most accurate" in m.label.lower()]
        self.assertEqual(len(accuracy_labelled), 1)
        self.assertEqual(accuracy_labelled[0].id, "microsoft/mai-transcribe-1.5")
        self.assertNotIn("accurate", stt_registry.model_for_id("openrouter", "deepgram/nova-3").label.lower())

    def test_no_paid_default_duplicates_a_free_local_model(self) -> None:
        """A model already in the local catalogue must never be a sold default.

        Parakeet TDT 0.6B v3 is DEFAULT_LOCAL_MODEL_ID -- it ships free and runs
        on plain CPU. Whisper large-v3 and its turbo variant are local too.
        Offering those over the network is fine as a fallback for weak machines,
        but making one the recommended paid choice charges a subscriber for the
        exact weights already sitting on their disk.
        """
        local_engine_ids = {model.id for model in local_stt.LOCAL_MODELS}
        duplicates = {
            model.id
            for model in self.provider.models
            if model.id.split("/", 1)[-1] in local_engine_ids
        }
        # These genuinely duplicate local models, so they must be labelled as such
        # rather than recommended.
        for model_id in duplicates:
            label = next(m.label for m in self.provider.models if m.id == model_id)
            self.assertNotIn("best value", label.lower(), f"{model_id} duplicates a free local model")
            self.assertNotIn("recommended", label.lower(), f"{model_id} duplicates a free local model")

    def test_the_value_default_is_not_available_locally(self) -> None:
        """Whatever carries the "best value" label must be worth paying for."""
        local_engine_ids = {model.id for model in local_stt.LOCAL_MODELS}
        value_models = [m for m in self.provider.models if "best value" in m.label.lower()]
        self.assertEqual(len(value_models), 1, "exactly one model should carry the value label")
        self.assertNotIn(value_models[0].id.split("/", 1)[-1], local_engine_ids)

    def test_the_key_is_the_persons_own_and_required(self) -> None:
        """2026-09-22: there is no backend key and no paid tier to serve it.

        This used to pin key_optional=True, because Pro and cloud add-on
        subscribers were served by our key. That also disabled the key box in
        Settings, so the only people who could use OpenRouter were the ones
        who could not type a key for it.
        """
        self.assertFalse(self.provider.key_optional)
        self.assertEqual(self.provider.env_key, "OPENROUTER_API_KEY")

    def test_it_appears_in_the_switcher_like_any_other_provider(self) -> None:
        self.assertIn(self.provider.label, stt_registry.provider_labels())
        self.assertEqual(stt_registry.provider_id_for_label(self.provider.label), "openrouter")
        self.assertEqual(stt_registry.provider_label("openrouter"), self.provider.label)

    def test_models_resolve_by_id_and_by_label(self) -> None:
        for model in self.provider.models:
            self.assertEqual(stt_registry.model_for_id("openrouter", model.id).id, model.id)
            self.assertEqual(stt_registry.model_id_for_label("openrouter", model.label), model.id)

    def test_model_labels_are_unique(self) -> None:
        labels = [model.label for model in self.provider.models]
        self.assertEqual(len(labels), len(set(labels)), "duplicate labels break label-to-id lookup")

    def test_model_ids_are_unique(self) -> None:
        """Re-labelling a model must replace it, not add a second copy.

        A duplicate id shows the same model twice in the picker under two
        different names, and model_for_id silently resolves to whichever comes
        first -- so the notes and pricing the user reads may belong to the entry
        that is not being used. Labels alone were unique when this happened, so
        the label check did not catch it.
        """
        ids = [model.id for model in self.provider.models]
        duplicates = sorted({model_id for model_id in ids if ids.count(model_id) > 1})
        self.assertEqual(duplicates, [], f"duplicate model ids: {duplicates}")


class EveryProviderIsActuallyWiredTests(unittest.TestCase):
    """A provider in the registry is offered to the user in Settings.

    If its api_kind has no adapter it is selectable, looks configured, and then
    raises NotImplementedError on the first dictation -- after the user has
    already spoken. The registry and the dispatch table must not drift apart.
    """

    # "external" providers are launched elsewhere rather than transcribed here.
    NOT_TRANSCRIBED_HERE = frozenset({"external"})

    def test_every_registered_provider_has_a_live_adapter(self) -> None:
        missing = [
            f"{provider.id} (api_kind={provider.api_kind})"
            for provider in stt_registry.PROVIDERS
            if provider.api_kind not in self.NOT_TRANSCRIBED_HERE
            and provider.api_kind not in stt_sessions.BatchSTTSession.TRANSCRIBE_HANDLERS
        ]
        self.assertEqual(missing, [], f"selectable providers with no adapter: {missing}")

    def test_every_adapter_name_resolves_to_a_real_method(self) -> None:
        for api_kind, method_name in stt_sessions.BatchSTTSession.TRANSCRIBE_HANDLERS.items():
            self.assertTrue(
                callable(getattr(stt_sessions.BatchSTTSession, method_name, None)),
                f"{api_kind} maps to {method_name}, which is not a method",
            )


if __name__ == "__main__":
    unittest.main()
