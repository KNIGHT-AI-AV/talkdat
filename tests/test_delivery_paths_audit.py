from __future__ import annotations

import re
import unittest
from pathlib import Path

from knight_flow.formatting import needs_intelligence
from knight_flow.text_pipeline import process_dictation

ROOT = Path(__file__).resolve().parents[1]


class EveryDeliveryPathRunsTheVocabularyTests(unittest.TestCase):
    """X-13. Mayowa reported 'talk dat' surviving uncorrected in live use
    while the pipeline corrected it perfectly in probes. The audit: every
    route that can put final text on screen funnels through
    process_dictation, whose pipeline owns the vocabulary pass — and this
    file keeps it that way."""

    def test_the_pipeline_corrects_the_reported_sentence(self) -> None:
        result = process_dictation("i've been using talk dat literally everything i'm saying", {})
        self.assertIn("Talk DAT!", result.text)

    def test_single_final_delivery_uses_the_full_pipeline_and_never_refines_in_place(self) -> None:
        """Vocabulary runs before the one delivery; no later document edit runs."""
        source = (ROOT / "knight_flow" / "app.py").read_text(encoding="utf-8")
        handle = source.split("def handle_dictation", 1)[1].split("\n    def ", 1)[0]
        refine = source.split("def _refine_after_paste", 1)[1].split("\n    def ", 1)[0]
        self.assertIn("speculative = False", handle)
        self.assertIn("process_dictation(raw_text, effective_config, local_only=speculative)", handle)
        self.assertNotIn("process_dictation", refine)
        self.assertIn("safe single delivery is active", refine)

    def test_streaming_partials_are_previews_not_pastes(self) -> None:
        """on_session_update must never deliver text — partials bypass the
        pipeline by design, so the only safe thing they may touch is the
        live draft and the pill preview."""
        source = (ROOT / "knight_flow" / "app.py").read_text(encoding="utf-8")
        update = source.split("def on_session_update", 1)[1].split("\n    def ", 1)[0]
        for forbidden in ("paste_text", "insert_text", "send_keys"):
            self.assertNotIn(forbidden, update)


class MangledRetractionsRouteToTheModelTests(unittest.TestCase):
    """X-22. 'now for version- I mean- now for part 2' arrived as
    'version mean for' — the recognizer ate the 'I' and the repair never
    ran. A bare 'mean' wedged between a content word and a function word now
    routes to the model; verb uses stay on the fast path."""

    def test_the_field_case_routes_to_repair(self) -> None:
        self.assertTrue(needs_intelligence("now for version mean for part 2 of the notes"))

    def test_new_markers_route_too(self) -> None:
        for text in (
            "send it tomorrow strike that send it today",
            "use the blue one forget that use the red one",
        ):
            with self.subTest(text=text):
                self.assertTrue(needs_intelligence(text))

    def test_verb_uses_of_mean_stay_fast(self) -> None:
        for text in (
            "you mean for me to send it",
            "what does that mean for us",
            "they mean the world to me",
        ):
            with self.subTest(text=text):
                self.assertFalse(
                    needs_intelligence(text),
                    f"verb 'mean' misrouted to the model: {text}",
                )


if __name__ == "__main__":
    unittest.main()
