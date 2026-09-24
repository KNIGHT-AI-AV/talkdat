from __future__ import annotations

import ast
import unittest
from pathlib import Path

from knight_flow.ui.onboarding import ROUTE_CARDS

SOURCE = Path(__file__).resolve().parents[1] / "knight_flow" / "ui" / "onboarding.py"


class TheFirstRunChoiceSaysWhatItCostsTests(unittest.TestCase):
    """X-516 replaces the X-59 doctrine, on his order: "No CLoud at all".

    X-59 (2026-08-10) was "cloud leads": the managed card came first, badged
    START HERE, because the first dictation had to be instantly good. That
    card described a service that no longer exists, and it was pre-selected
    for anyone with an account, so first run would have opened on a route that
    cannot run.

    Local leads now, and it leads on its own merits rather than as the
    consolation half of the moon: nothing to sign up for, nothing to pay
    before trying it, and the audio never leaves the machine. The old local
    card apologised for being "a step behind Cloud"; there is nothing left for
    it to be behind.

    What these tests pin is unchanged in spirit: the order IS the
    recommendation, every card is honest about what it costs, and the copy
    lives in exactly one place.
    """

    def test_local_leads(self) -> None:
        self.assertEqual(next(iter(ROUTE_CARDS)), "local",
                         "the card order IS the recommendation")
        local = " ".join(ROUTE_CARDS["local"]).lower()
        self.assertIn("start here", local, "the lead card has to say it leads")

    def test_local_is_honest_about_what_it_owns_and_what_it_costs(self) -> None:
        local = " ".join(ROUTE_CARDS["local"]).lower()
        self.assertIn("forever", local, "local's selling point is permanence")
        self.assertTrue(any(phrase in local for phrase in ("never leaves", "offline")),
                        "privacy is local's other half")
        self.assertNotIn("behind cloud", local, "there is no cloud left to be behind")
        self.assertNotIn("step behind", local)

    def test_each_card_is_honest_about_what_it_costs(self) -> None:
        """2026-09-22: Talk DAT! is free. Local says so and sells nothing --
        no weekly cap, no Local Forever to buy. Bring-your-own still names who
        bills it: the person's own provider."""
        local = " ".join(ROUTE_CARDS["local"]).lower()
        byok = " ".join(ROUTE_CARDS["byok"]).lower()
        self.assertIn("free", local, "local is free, and the card should say so")
        for gone in ("local forever", "buy", "trial", "$", "a week"):
            with self.subTest(phrase=gone):
                self.assertNotIn(gone, local)
        self.assertTrue(any(word in byok for word in ("your own", "billed", "your key")))

    def test_no_card_offers_a_managed_service(self) -> None:
        """The card set is the whole first-run choice, so a managed entry here
        would put it back in front of every new person regardless of what the
        resolvers do."""
        self.assertEqual(set(ROUTE_CARDS), {"local", "byok"})
        joined = " ".join(" ".join(card) for card in ROUTE_CARDS.values()).lower()
        for gone in ("talk dat! managed", "talk dat! cloud", "managed cloud"):
            with self.subTest(phrase=gone):
                self.assertNotIn(gone, joined)

    def test_every_route_has_a_title_badge_and_description(self) -> None:
        for route, card in ROUTE_CARDS.items():
            with self.subTest(route=route):
                self.assertEqual(len(card), 3)
                for part in card:
                    self.assertTrue(str(part).strip())

    def test_the_copy_exists_in_exactly_one_place(self) -> None:
        """It was written out twice. A correction to one copy would have missed
        the other, which is precisely how the download message came to say two
        different things in 0.4.26."""
        tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
        literals = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Dict)
            and {k.value for k in node.keys if isinstance(k, ast.Constant)} >= {"local", "byok"}
        ]
        self.assertEqual(len(literals), 1, f"route copy is defined in {len(literals)} places")


if __name__ == "__main__":
    unittest.main()
