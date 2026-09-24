from __future__ import annotations

import unittest

from knight_flow.mac_support import THIS_COMPUTER

from knight_flow.stt_registry import (
    PROVIDER_BY_ID,
    PROVIDERS,
    provider_capability_summary,
)


class ThePickerSaysWhenTextWillActuallyArriveTests(unittest.TestCase):
    """The largest difference in felt speed in this product, previously unsaid.

    Measured on one machine against 5 seconds of speech, timed from the end of
    the recording:

        Deepgram, streaming        119-413 ms
        OpenRouter, batch          1371 ms
        bundled local, batch       938-1647 ms, plus 7.9 s on the first call

    A streaming provider has transcribed most of the audio before the key comes
    up, so what is left is a settle. A batch provider cannot begin until the
    recording ends, so the whole cost lands where the person is watching. That
    is the difference between text arriving as you finish and a second and a
    half of nothing, and the model picker treated the two as equivalent.

    Worse than silent: `supports_streaming` was set on eleven providers and only
    one of them streams through this app, and the picker printed "streaming"
    from that flag. Choosing AssemblyAI or Soniox on the strength of it bought a
    full round trip.
    """

    def test_only_providers_with_a_streaming_adapter_claim_to_stream(self) -> None:
        claimed = {p.id for p in PROVIDERS if p.streams_in_app}
        wired = {p.id for p in PROVIDERS if "stream" in p.api_kind}
        self.assertEqual(claimed, wired)
        self.assertEqual(claimed, {"deepgram"}, "if a second one is wired, say so here")

    def test_the_vendor_flag_is_not_used_for_anything_a_user_sees(self) -> None:
        """It is a true statement about the vendor and a false one about us."""
        misleading = [p.id for p in PROVIDERS if p.supports_streaming and not p.streams_in_app]
        self.assertTrue(misleading, "this test is about the gap; it should not be empty")
        for provider_id in misleading:
            with self.subTest(provider=provider_id):
                self.assertNotIn("streaming", provider_capability_summary(provider_id).lower())

    def test_every_provider_says_something_about_when_text_arrives(self) -> None:
        for provider in PROVIDERS:
            with self.subTest(provider=provider.id):
                self.assertTrue(provider.delivery_note.strip())
                self.assertIn(provider.delivery_note, provider_capability_summary(provider.id))

    def test_the_streaming_one_is_described_differently_from_the_rest(self) -> None:
        streaming = PROVIDER_BY_ID["deepgram"].delivery_note
        for provider in PROVIDERS:
            if provider.streams_in_app:
                continue
            with self.subTest(provider=provider.id):
                self.assertNotEqual(provider.delivery_note, streaming)

    def test_an_unavailable_provider_says_so_rather_than_promising_a_round_trip(self) -> None:
        """`external` providers have no adapter at all. Telling someone they
        will wait for a round trip implies one would eventually arrive."""
        for provider in PROVIDERS:
            if provider.api_kind != "external":
                continue
            with self.subTest(provider=provider.id):
                self.assertEqual(provider.delivery_note, "Not available in this build")
                self.assertNotIn("wired", provider.delivery_note.lower())

    def test_the_local_model_is_not_described_as_a_network_round_trip(self) -> None:
        # The phrase names the user's own machine, and that word differs by
        # platform -- "this Mac" reads as somebody else's computer on Windows
        # and vice versa. What matters is that the note says the work happens
        # here rather than over a network.
        self.assertIn(THIS_COMPUTER.lower(), PROVIDER_BY_ID["local"].delivery_note.lower())

    def test_the_claim_is_derived_so_it_cannot_drift_again(self) -> None:
        """A hand-maintained copy of something already knowable is one edit from
        being wrong, which is exactly how the old flag came to describe eleven
        providers that do not do it."""
        import inspect

        from knight_flow.stt_registry import STTProvider

        source = inspect.getsource(STTProvider.streams_in_app.fget)
        self.assertIn("api_kind", source)


if __name__ == "__main__":
    unittest.main()
