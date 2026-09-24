"""X-176: the first-run wizard may not promise more than the product does.

Three claims in onboarding were contradicted by the code that runs underneath
them. Reported by the 0.4.104 UI/UX audit and confirmed by an independent read.

1. "Every local model, offline and FREE FOREVER"
   At the time free use was capped weekly after a trial and Local Forever was
   the paid removal of that cap, so the claim was false. 2026-09-22 reversed
   the premise: Talk DAT! is free, with no trial, cap or purchase. The guard
   below now pins the new truth instead -- the wizard may not mention a trial,
   a weekly cap, a price or anything to buy, because none of them exist.

2. "Never loses a dictation / Cloud trouble reroutes to the on-device model
   MID-SENTENCE, then back."
   That describes switching engines inside an utterance and always recovering.
   What happens is a fallback to the on-device model using audio already
   captured, and a first cloud failure can still cost you the phrase.

3. "Your voice stays home / Recordings live on this PC until delivered, and are
   NEVER UPLOADED."
   Shown on every route, including the managed and bring-your-own-key cloud
   routes whose entire mechanism is uploading audio to a transcription service.

The third is the one that matters most. A privacy promise is the single claim a
product cannot round off, and a local-only claim is worth nothing if it is also
printed on the routes where it is false. These tests exist because copy drifts
back: a future edit that wants a punchier card will reach for exactly these
words again.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ONBOARDING = ROOT / "knight_flow" / "ui" / "onboarding.py"


def shipped_strings() -> list[tuple[int, str]]:
    """String literals only, ignoring comments.

    The comments here deliberately quote the old false copy so the next reader
    knows what was wrong and why. Matching on raw text would flag the
    explanation as the offence.
    """
    found: list[tuple[int, str]] = []
    literal = re.compile(r'"[^"\n]*"|\'[^\'\n]*\'')
    for number, line in enumerate(ONBOARDING.read_text(encoding="utf-8").splitlines(), 1):
        if line.lstrip().startswith("#"):
            continue
        for match in literal.finditer(line):
            found.append((number, match.group(0)))
    return found


class NoOverpromiseInShippedCopyTests(unittest.TestCase):
    def _offenders(self, pattern: str) -> list[tuple[int, str]]:
        needle = re.compile(pattern, re.IGNORECASE)
        return [(n, text) for n, text in shipped_strings() if needle.search(text)]

    def test_the_checker_can_see_a_violation(self) -> None:
        """So the guard cannot quietly start matching nothing."""
        self.assertTrue(shipped_strings(), "no string literals were extracted at all")

    def test_nothing_sells_or_meters_anything(self) -> None:
        offenders = self._offenders(
            r"\btrial\b|local forever|\bbuy(ing)?\b|\bpurchase|\bsubscri|\bpric(e|ing)\b"
            r"|\$\d|words a week|\bupgrade\b|\b(free|paid|your|a|pro) plans?\b"
        )
        self.assertEqual(
            offenders, [],
            f"Talk DAT! is free (2026-09-22); onboarding may not sell or meter: {offenders}",
        )

    def test_nothing_claims_a_dictation_is_never_lost(self) -> None:
        offenders = self._offenders(r"never loses|never lose a dictation")
        self.assertEqual(
            offenders, [],
            f"a first cloud failure can still cost the phrase: {offenders}",
        )

    def test_no_card_claims_a_mid_sentence_engine_switch(self) -> None:
        offenders = self._offenders(r"mid-sentence")
        self.assertEqual(
            offenders, [],
            "the fallback re-transcribes audio already captured; it does not swap "
            f"engines inside an utterance: {offenders}",
        )


class ThePrivacyClaimIsRouteAwareTests(unittest.TestCase):
    """The important one: never promise local-only on a route that uploads."""

    def test_the_unconditional_never_uploaded_promise_is_gone(self) -> None:
        text = ONBOARDING.read_text(encoding="utf-8")
        self.assertNotIn(
            '"Recordings live on this PC until delivered, and are never uploaded."', text,
            "the unconditional privacy promise is back, and it is false on every cloud route",
        )

    def test_the_privacy_card_is_chosen_from_the_route(self) -> None:
        text = ONBOARDING.read_text(encoding="utf-8")
        self.assertIn("privacy_card", text)
        block = text[text.index("privacy_card = ("):][:900] if "privacy_card = (" in text else ""
        self.assertTrue(block, "privacy_card is referenced but never built")
        self.assertIn("route_var", text[: text.index("privacy_card = (")][-2000:])

    def test_every_never_uploaded_claim_sits_behind_the_local_branch(self) -> None:
        """The claim is allowed, but only where it is true."""
        text = ONBOARDING.read_text(encoding="utf-8")
        for number, literal in shipped_strings():
            if "never uploaded" not in literal.lower():
                continue
            with self.subTest(line=number):
                lines = text.splitlines()
                window = "\n".join(lines[max(0, number - 12): number])
                self.assertIn(
                    'chosen_route == "local"', window,
                    f"line {number} claims audio is never uploaded outside the local branch: {literal}",
                )

    def test_the_unchosen_route_gets_the_cautious_wording(self) -> None:
        """Before a route is picked, the honest line, not the flattering one."""
        text = ONBOARDING.read_text(encoding="utf-8")
        self.assertIn("You choose where your voice goes", text)
        self.assertIn("Cloud routes send audio to the transcription service", text)


if __name__ == "__main__":
    unittest.main()
