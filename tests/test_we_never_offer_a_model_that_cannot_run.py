"""X-474: two models in the picker do not run, and one of them was the rescue.

Measured on 2026-09-05 while looking for an accurate second transcription tier.
Both NVIDIA Canary models in the local catalogue fail on this machine:

    RuntimeError: [ONNXRuntimeError] : 6 : RUNTIME_EXCEPTION :
    Non-zero status code returned while running Reshape node. Name:'node_view'

Ruled out one at a time rather than guessed at:

  * not DirectML -- they fail identically with the CPU provider;
  * not the int8 quantization the loader forces on every `nemo-` and
    `istupakov/` model -- they fail unquantized too, downloaded fresh;
  * not a stale download -- the 180M model was re-fetched from the Hub.

So it is onnx-asr 0.12.0 against these graphs, and nothing this product does
at call time can rescue it.

THREE PLACES SAID OTHERWISE, and each one hurt differently:

  * `model_catalog.py` marked both `wired`, whose own docstring defines it as
    "a tested request/runtime path today" and whose UI label is "Ready in Talk
    DAT!". Neither was true.
  * `model_quality.py` advertises canary-1b-v2 at 4.3 word error against
    Parakeet's 6.4, so the picker recommended the broken one as more accurate.
  * `local_fallback.py` listed canary-1b-v2 THIRD in the rescue preference.
    That is the worst of the three: the rescue exists for the moment the
    configured model is missing, and it would have chosen a model that cannot
    run. A rescue that fails is worse than no rescue, because the person has
    already lost the words by the time it runs.

The rule this file defends is not about Canary. It is that a model offered for
download must have a path that was actually executed, and the rescue order may
only contain models that can run. If Canary is ever fixed, by a newer
onnx-asr or different weights, RE-MEASURE IT and move it back deliberately.

WHAT THIS CANNOT PROVE: that every remaining model works. Proving that needs
every model downloaded and run, which is gigabytes and not a unit test. This
pins the two that were measured broken and the shape of the claim.
"""

from __future__ import annotations

import unittest

from knight_flow import local_fallback, local_stt
from knight_flow.model_catalog import LOCAL_MODEL_CATALOG

BROKEN_ON_ONNX_ASR = ("canary-1b-v2", "canary-180m-flash")


class AModelWeOfferMustBeAbleToRunTests(unittest.TestCase):
    def test_the_broken_models_are_not_offered_for_download(self) -> None:
        """The picker downloads about a gigabyte before the first run. Offering
        one that crashes afterwards spends the person's bandwidth and their
        patience to reach an error."""
        offered = {model.id for model in local_stt.LOCAL_MODELS}
        for model_id in BROKEN_ON_ONNX_ASR:
            with self.subTest(model=model_id):
                self.assertNotIn(
                    model_id, offered,
                    f"{model_id} is offered for download and cannot run; see this file's header",
                )

    def test_the_rescue_never_reaches_for_one(self) -> None:
        """The rescue runs at the worst possible moment, when the configured
        model is gone and words are already waiting. Picking something that
        cannot run turns a recoverable moment into a lost dictation."""
        for model_id in BROKEN_ON_ONNX_ASR:
            with self.subTest(model=model_id):
                self.assertNotIn(
                    model_id, local_fallback._PREFERENCE,
                    f"the rescue would choose {model_id}, which cannot run",
                )

    def test_the_catalogue_no_longer_calls_them_ready(self) -> None:
        """`wired` is defined in that module as "a tested request/runtime path
        today" and shown to people as "Ready in Talk DAT!". Saying it about
        something that raises on every call is the plainest kind of untrue."""
        for entry in LOCAL_MODEL_CATALOG:
            if entry.id in BROKEN_ON_ONNX_ASR:
                with self.subTest(model=entry.id):
                    self.assertNotEqual(
                        entry.status, "wired",
                        f"{entry.id} is still advertised as ready and cannot run",
                    )

    def test_the_hosted_nvidia_models_are_untouched(self) -> None:
        """Canary also exists as an NVIDIA-HOSTED model behind their API, which
        is a completely different code path and was never measured here. This
        removal is about the local onnx-asr graphs only, and quietly deleting
        the hosted entry too would be scope creep dressed as a fix."""
        from knight_flow.stt_registry import PROVIDER_BY_ID

        nvidia = PROVIDER_BY_ID.get("nvidia")
        self.assertIsNotNone(nvidia, "the NVIDIA provider is gone")
        hosted = {model.id for model in nvidia.models}
        self.assertIn("canary-1b-v2", hosted,
                      "the hosted NVIDIA model was removed along with the local one")

    def test_parakeet_is_still_the_default_and_still_offered(self) -> None:
        """The point of the removal is that what remains can run. If this ever
        fails, the picker has been emptied rather than corrected."""
        offered = {model.id for model in local_stt.LOCAL_MODELS}
        self.assertIn(local_stt.DEFAULT_LOCAL_MODEL_ID, offered)
        self.assertTrue(len(offered) >= 8, "the catalogue lost more than the two broken models")


if __name__ == "__main__":
    unittest.main()
