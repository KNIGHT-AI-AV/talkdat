"""Deterministic caption races and unavailable-runtime guards; no inference."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from knight_flow import local_stt
from knight_flow.local_live import LivePartials, LiveTailDecoder


class CaptionRevisionTests(unittest.TestCase):
    def test_snapshots_replace_instead_of_appending(self):
        partials = LivePartials()
        revision = partials.revision()
        partials.set_tail("a cat", revision=revision)
        partials.set_tail("a lion", revision=revision)
        self.assertEqual(partials.text(), "a lion")

    def test_closed_segment_invalidates_inflight_tail(self):
        partials = LivePartials()
        revision = partials.revision()
        partials.set_piece(0, "A lion.")
        self.assertFalse(partials.set_tail("a cat", revision=revision))
        self.assertEqual(partials.text(), "A lion.")

    def test_clear_invalidates_inflight_tail(self):
        partials = LivePartials()
        revision = partials.revision()
        partials.clear()
        self.assertFalse(partials.set_tail("old take", revision=revision))
        self.assertEqual(partials.text(), "")

    def test_new_tail_after_commit_is_allowed(self):
        partials = LivePartials()
        partials.set_piece(0, "First sentence.")
        self.assertTrue(partials.set_tail("Second sentence", revision=partials.revision()))
        self.assertEqual(partials.text(), "First sentence. Second sentence")

    def test_out_of_order_commits_remain_ordered(self):
        partials = LivePartials()
        partials.set_piece(1, "Second.")
        revision = partials.revision()
        partials.set_piece(0, "First.")
        self.assertFalse(partials.set_tail("stale", revision=revision))
        self.assertEqual(partials.text(), "First. Second.")

    def test_empty_final_piece_removes_silence_preview(self):
        partials = LivePartials()
        partials.set_tail("noise")
        revision = partials.revision()
        partials.set_piece(0, "")
        self.assertFalse(partials.set_tail("noise", revision=revision))
        self.assertEqual(partials.text(), "")


class DecoderRaceTests(unittest.TestCase):
    def make_decoder(self, decode):
        partials = LivePartials()
        seen = []
        decoder = LiveTailDecoder(
            partials=partials, tail_span=lambda: (0, 64000),
            audio_slice=lambda start, end: b"fake-pcm", decode=decode,
            on_text=seen.append, sample_rate=16000, channels=1,
        )
        return decoder, partials, seen

    def test_piece_landing_inside_decode_does_not_duplicate_preview(self):
        def decode(_pcm):
            decoder.publish_piece(0, "Final lion.")
            return "old cat"

        decoder, partials, seen = self.make_decoder(decode)
        spans = iter([(0, 64000), (0, 0)])

        def span():
            value = next(spans)
            if value == (0, 0):
                decoder._stop.set()
            return value

        # Execute the loop synchronously with a fake clock; no worker or sleep.
        with patch.object(decoder, "_tail_span", side_effect=span), \
             patch("knight_flow.local_live.time.monotonic", side_effect=[0.0, 0.0, 1.0]):
            decoder._run()
        self.assertEqual(partials.text(), "Final lion.")
        self.assertEqual(seen, ["Final lion."])

    def test_cancel_inside_decode_discards_result(self):
        def decode(_pcm):
            decoder.cancel()
            return "cancelled take"

        decoder, partials, seen = self.make_decoder(decode)
        decoder._run()
        self.assertEqual(partials.text(), "")
        self.assertEqual(seen, [])

    def test_late_closed_future_after_cancel_cannot_repopulate(self):
        decoder, partials, seen = self.make_decoder(lambda _pcm: "unused")
        decoder.cancel()
        decoder.publish_piece(0, "old take")
        self.assertEqual(partials.text(), "")
        self.assertEqual(seen, [])

    def test_late_closed_future_after_stop_cannot_publish(self):
        decoder, partials, seen = self.make_decoder(lambda _pcm: "unused")
        partials.set_tail("last preview")
        decoder.stop()
        decoder.publish_piece(0, "late result")
        decoder._publish()
        self.assertEqual(partials.text(), "last preview")
        self.assertEqual(seen, [])

    def test_old_cancelled_decoder_cannot_change_new_take(self):
        old, _, old_seen = self.make_decoder(lambda _pcm: "unused")
        new, new_partials, new_seen = self.make_decoder(lambda _pcm: "unused")
        old.cancel()
        new.publish_piece(0, "new take")
        old.publish_piece(0, "old take")
        self.assertEqual(new_partials.text(), "new take")
        self.assertEqual(new_seen, ["new take"])
        self.assertEqual(old_seen, [])


class ExperimentalRuntimeGateTests(unittest.TestCase):
    def test_redux_is_not_offered_or_selected(self):
        self.assertNotIn("parakeet-redux", {model.id for model in local_stt.available_local_models()})
        self.assertEqual(local_stt.DEFAULT_LOCAL_MODEL_ID, "parakeet-tdt-0.6b-v3")
        self.assertEqual(local_stt.local_model_for_id("parakeet-redux").id, local_stt.DEFAULT_LOCAL_MODEL_ID)
        self.assertTrue(any(model.engine == "faster_whisper" for model in local_stt.LOCAL_MODELS))

    def test_unknown_engine_cannot_touch_disk_import_runtime_or_return_cache(self):
        model = local_stt.LocalModel("parakeet-redux", "Experimental", "kestrel", "moondream/parakeet-redux", 178, "25 languages")
        with patch.dict(local_stt._ENGINES, {model.id: object()}), \
             patch.object(local_stt, "model_dir", side_effect=AssertionError("disk touched")), \
             patch.object(local_stt, "is_downloaded", side_effect=AssertionError("manifest read")), \
             patch.object(local_stt, "_load_onnx_asr", side_effect=AssertionError("runtime loaded")), \
             patch.object(local_stt, "_load_faster_whisper", side_effect=AssertionError("runtime loaded")):
            with self.assertRaisesRegex(local_stt.LocalSTTError, "Unknown local engine: kestrel"):
                local_stt.ensure_loaded(model)


if __name__ == "__main__":
    unittest.main()
