"""X-478: the speech model is chosen by measuring this machine.

The case for it was made by being wrong three times in one afternoon:

  * Parakeet was assumed fastest because it is smallest. On real dictation with
    a working GPU it was the slowest of three.
  * Whisper was written off as unusable on the GPU. It was unusable only
    because a DLL directory was missing from PATH (X-475).
  * Canary was advertised as the higher-accuracy choice and cannot run at all
    (X-474).

And then the probe made the point by itself. With the CUDA runtime present,
Whisper beat Parakeet. With it removed, the same probe on the same machine put
Parakeet 90x ahead, with Whisper slower than realtime. Both readings are
correct. No static ranking survives contact with a particular machine, which
is why the fingerprint below includes whether CUDA is installed.

The shape, which is Handy's and is right: measure, recommend, and let the
person pick whatever they want anyway. The measurement is what makes the
default trustworthy; it does not take the choice away.

What this pins:

  * SPEED ONLY. Accuracy needs ground truth the probe does not have, and a
    number invented for it would be trusted. The clip is generated and no
    transcript is read from it.
  * Nothing is downloaded to be measured. "Let me fetch a gigabyte to find out
    if it is faster" is not a thing to do to someone who wants to talk.
  * A model that fails is RECORDED, not raised. That is the Canary case caught
    automatically next time instead of by hand.
  * A stale verdict is thrown away. It is trusted, so being out of date is
    worse than being absent.
  * A near-tie keeps the existing default rather than churning it.
"""

from __future__ import annotations

import unittest
from unittest import mock

from knight_flow import model_picker


class ItMeasuresRatherThanGuessesTests(unittest.TestCase):
    def test_the_probe_clip_is_generated_not_shipped(self) -> None:
        """Deterministic, so two runs are comparable, and no audio file has to
        ride along in the installer."""
        first = model_picker._probe_audio()
        self.assertEqual(first, model_picker._probe_audio())
        expected = int(model_picker.PROBE_SECONDS * model_picker.PROBE_RATE) * 2
        self.assertEqual(len(first), expected)

    def test_a_model_that_fails_is_recorded_not_raised(self) -> None:
        """Canary raises on every call. Recording that is how the picker stops
        recommending it without anyone having to notice again."""
        def explode(**kwargs):
            raise RuntimeError("Reshape node")

        with mock.patch("knight_flow.local_stt.transcribe", side_effect=explode):
            results = model_picker.measure(["canary-1b-v2"])

        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].failed)
        self.assertIn("Reshape", results[0].detail)

    def test_the_first_call_is_thrown_away(self) -> None:
        """The first call loads the weights. A cold reading has been wrong by
        20x on this machine, so each model is run twice and the warm one is
        the measurement."""
        calls = []

        def counted(**kwargs):
            calls.append(kwargs["model_id"])
            return "words"

        with mock.patch("knight_flow.local_stt.transcribe", side_effect=counted):
            model_picker.measure(["parakeet-tdt-0.6b-v3"])

        self.assertEqual(len(calls), 2, "the cold run was measured or the warm one skipped")


class NothingIsDownloadedToBeMeasuredTests(unittest.TestCase):
    def test_only_models_on_disk_are_candidates(self) -> None:
        """Fetching a gigabyte to discover whether it is faster is not a thing
        to do to someone who just wants to talk."""
        import inspect

        source = inspect.getsource(model_picker.candidates)
        self.assertIn("is_downloaded", source)
        for forbidden in ("download_model", "ensure_downloaded", "snapshot_download"):
            with self.subTest(call=forbidden):
                self.assertNotIn(forbidden, source)


class AStaleVerdictIsThrownAwayTests(unittest.TestCase):
    def test_installing_cuda_invalidates_the_measurement(self) -> None:
        """The sharpest case there is. With CUDA the ranking inverted, so a
        verdict measured without it is not merely old, it is wrong."""
        with mock.patch("knight_flow.cuda_runtime.is_installed", return_value=False):
            without = model_picker._fingerprint(["parakeet-tdt-0.6b-v3"])
        with mock.patch("knight_flow.cuda_runtime.is_installed", return_value=True):
            with_cuda = model_picker._fingerprint(["parakeet-tdt-0.6b-v3"])
        self.assertNotEqual(without, with_cuda)

    def test_a_new_model_on_disk_invalidates_it(self) -> None:
        """A model that was not in the race cannot be ranked by a race it
        never ran in."""
        self.assertNotEqual(
            model_picker._fingerprint(["parakeet-tdt-0.6b-v3"]),
            model_picker._fingerprint(["parakeet-tdt-0.6b-v3", "whisper-base"]),
        )

    def test_a_mismatched_verdict_recommends_nothing(self) -> None:
        """Better to say nothing than to recommend from a race on a different
        machine."""
        stored = {"fingerprint": "v3:nocuda:something-else",
                  "results": [{"model_id": "whisper-base", "milliseconds": 10.0,
                               "realtime": 400.0, "failed": False}]}
        with mock.patch.object(model_picker, "read_results", return_value=stored), \
             mock.patch.object(model_picker, "candidates", return_value=["parakeet-tdt-0.6b-v3"]):
            self.assertEqual(model_picker.recommended_model({}), "")


class TheRecommendationTests(unittest.TestCase):
    def _stored(self, rows):
        return {"fingerprint": model_picker._fingerprint([r["model_id"] for r in rows]),
                "results": rows}

    def test_the_fastest_working_model_wins(self) -> None:
        rows = [
            {"model_id": "whisper-large-v3-turbo", "milliseconds": 40263.0, "realtime": 0.1, "failed": False},
            {"model_id": "parakeet-tdt-0.6b-v3", "milliseconds": 453.0, "realtime": 8.8, "failed": False},
        ]
        with mock.patch.object(model_picker, "read_results", return_value=self._stored(rows)), \
             mock.patch.object(model_picker, "candidates",
                               return_value=[r["model_id"] for r in rows]):
            self.assertEqual(model_picker.recommended_model({}), "parakeet-tdt-0.6b-v3")

    def test_a_model_that_cannot_run_is_never_recommended(self) -> None:
        """Even when its recorded time would sort first."""
        rows = [
            {"model_id": "canary-1b-v2", "milliseconds": 1.0, "realtime": 900.0, "failed": True},
            {"model_id": "whisper-base", "milliseconds": 2665.0, "realtime": 1.5, "failed": False},
        ]
        with mock.patch.object(model_picker, "read_results", return_value=self._stored(rows)), \
             mock.patch.object(model_picker, "candidates",
                               return_value=[r["model_id"] for r in rows]):
            self.assertEqual(model_picker.recommended_model({}), "whisper-base")

    def test_a_near_tie_keeps_the_existing_default(self) -> None:
        """Churning the default over three percent of noise is how a person
        finds their app quietly changed itself for no reason they can feel."""
        rows = [
            {"model_id": "whisper-base", "milliseconds": 440.0, "realtime": 9.0, "failed": False},
            {"model_id": "parakeet-tdt-0.6b-v3", "milliseconds": 453.0, "realtime": 8.8, "failed": False},
        ]
        with mock.patch.object(model_picker, "read_results", return_value=self._stored(rows)), \
             mock.patch.object(model_picker, "candidates",
                               return_value=[r["model_id"] for r in rows]):
            self.assertEqual(model_picker.recommended_model({}), "parakeet-tdt-0.6b-v3")

    def test_the_unusable_list_is_reported(self) -> None:
        """So the picker can stop offering them, which is X-474 done by
        measurement instead of by hand."""
        rows = [
            {"model_id": "canary-1b-v2", "milliseconds": 1.0, "realtime": 0.0, "failed": True},
            {"model_id": "parakeet-tdt-0.6b-v3", "milliseconds": 453.0, "realtime": 8.8, "failed": False},
        ]
        with mock.patch.object(model_picker, "read_results", return_value=self._stored(rows)), \
             mock.patch.object(model_picker, "candidates",
                               return_value=[r["model_id"] for r in rows]):
            self.assertEqual(model_picker.unusable_models({}), ["canary-1b-v2"])


class ItClaimsNothingAboutAccuracyTests(unittest.TestCase):
    def test_no_accuracy_is_reported(self) -> None:
        """The probe has no ground truth, so any accuracy number would be
        invented, and an invented number in this file would be believed."""
        import dataclasses

        fields = {f.name for f in dataclasses.fields(model_picker.Measurement)}
        for word in ("accuracy", "wer", "quality", "score"):
            with self.subTest(word=word):
                self.assertNotIn(word, fields)


if __name__ == "__main__":
    unittest.main()
