from __future__ import annotations

import unittest

from knight_flow.local_stt import LOCAL_MODELS
from knight_flow.model_catalog import (
    CLOUD_MODEL_CATALOG,
    LOCAL_MODEL_CATALOG,
    MODEL_CATALOG_STATUS_LABELS,
    MODEL_CATALOG_STATUSES,
    MODEL_CATALOG_VERIFIED_ON,
    MODEL_GUIDE_DEFAULTS,
    filtered_catalog_entries,
)


class ModelCatalogTests(unittest.TestCase):
    def test_catalog_has_thirty_cloud_and_thirty_local_entries(self) -> None:
        self.assertEqual(len(CLOUD_MODEL_CATALOG), 30)
        self.assertEqual(len(LOCAL_MODEL_CATALOG), 30)
        self.assertEqual(MODEL_CATALOG_VERIFIED_ON, "2026-08-02")

    def test_every_entry_has_primary_documentation_and_lifecycle(self) -> None:
        for entry in CLOUD_MODEL_CATALOG + LOCAL_MODEL_CATALOG:
            with self.subTest(model=entry.id):
                self.assertTrue(entry.id)
                self.assertTrue(entry.label)
                self.assertTrue(entry.provider)
                self.assertTrue(entry.docs_url.startswith("https://"))
                self.assertIn(entry.status, MODEL_CATALOG_STATUSES)

    def test_every_packaged_local_model_is_cataloged_as_wired(self) -> None:
        wired_ids = {entry.id for entry in LOCAL_MODEL_CATALOG if entry.status == "wired"}
        runtime_ids = {model.id for model in LOCAL_MODELS}
        self.assertEqual(wired_ids, runtime_ids)

    def test_new_runtime_candidates_are_not_misrepresented_as_ready(self) -> None:
        pending_ids = {entry.id for entry in LOCAL_MODEL_CATALOG if entry.status == "adapter_pending"}
        self.assertIn("qwen3-asr-1.7b", pending_ids)
        self.assertIn("moss-transcribe-diarize", pending_ids)
        self.assertIn("nemotron-3.5-asr-streaming-0.6b", pending_ids)

    def test_retired_cloud_generations_are_absent(self) -> None:
        catalog_ids = {entry.id for entry in CLOUD_MODEL_CATALOG}
        for retired_id in ("scribe_v1", "stt-rt-v4", "gemini-2.5-flash", "gemini-2.5-pro"):
            self.assertNotIn(retired_id, catalog_ids)

    def test_model_guide_defaults_are_concise_and_current(self) -> None:
        # X-516: three lanes, not four. The managed row is gone with the
        # engine it described.
        self.assertEqual(len(MODEL_GUIDE_DEFAULTS), 3)
        defaults = " ".join(model for _lane, model, _reason in MODEL_GUIDE_DEFAULTS)
        self.assertIn("Parakeet TDT 0.6B v3", defaults)
        self.assertIn("Deepgram Nova-3", defaults)
        # X-516: the managed lane is gone, so the guide must not name it at
        # all. The rule it used to serve -- never tell a reader which engine
        # we run behind the managed tier -- is satisfied by there being no
        # managed tier.
        self.assertNotIn("Talk DAT! Managed", defaults)
        for engine in ("Scribe", "ElevenLabs", "Whisper", "Nova-3 Cloud"):
            self.assertNotIn(f"Managed accuracy {engine}", " ".join(
                f"{lane} {model}" for lane, model, _reason in MODEL_GUIDE_DEFAULTS
            ))
        self.assertIn("Qwen3 1.7B", defaults)
        self.assertEqual(set(MODEL_CATALOG_STATUS_LABELS), MODEL_CATALOG_STATUSES)

    def test_model_guide_filters_by_location_status_and_query(self) -> None:
        local_ready = filtered_catalog_entries(location="local", status="wired")
        self.assertEqual(len(local_ready), len(LOCAL_MODELS))
        self.assertTrue(all(entry.mode == "local" and entry.status == "wired" for entry in local_ready))

        nova = filtered_catalog_entries(location="cloud", query="nova-3")
        self.assertEqual([entry.id for entry in nova], ["nova-3"])

        pending_qwen = filtered_catalog_entries(location="local", status="adapter_pending", query="qwen")
        self.assertEqual(
            {entry.id for entry in pending_qwen},
            {"qwen3-asr-1.7b", "qwen3-asr-0.6b", "canary-qwen-2.5b"},
        )


if __name__ == "__main__":
    unittest.main()
