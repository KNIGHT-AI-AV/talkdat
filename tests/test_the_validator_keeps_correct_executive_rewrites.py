"""X-414: the facts gate must not veto a correct Executive rewrite.

Measured while shipping X-412: the local 4B model produced six correct
Executive rewrites and `_valid_formatter_output` accepted four. The two it
threw away were right. One dropped a dangling English "one" ("the i7 8700 one
and") and the gate read that as a deleted number, because the standalone
number-word pass turns "one" into the fact 1. The other wrote "Tuesday the
12th" for "tuesday the twelfth"; a lone ordinal was never composed on the
source side, so the model's 12 looked invented. The same gate guards the
cloud route, so the cloud was losing the same rewrites.
"""
from __future__ import annotations

import unittest

from knight_flow.formatting import _meaning_anchors, _valid_formatter_output


def accepted(source: str, output: str) -> bool:
    return _valid_formatter_output(source, output, rewrite_mode=True)


class TheGateKeepsCorrectRewritesTests(unittest.TestCase):
    def test_a_dangling_english_one_is_not_a_number(self) -> None:
        source = "so the old laptop the i7 8700 one and the new one both need the update before friday"
        output = "The old laptop, the i7 8700, and the new one both need the update before Friday."
        self.assertTrue(accepted(source, output))

    def test_an_opening_oh_is_not_a_zero(self) -> None:
        source = "oh and also send marcus the deck by friday he asked twice"
        output = "Also, send Marcus the deck by Friday. He asked twice."
        self.assertTrue(accepted(source, output))

    def test_a_lone_ordinal_date_matches_its_numeral(self) -> None:
        source = "the call moved to tuesday the twelfth so push the review to the twentieth"
        output = "The call moved to Tuesday the 12th, so push the review to the 20th."
        self.assertTrue(accepted(source, output))
        self.assertEqual(_meaning_anchors(source), _meaning_anchors(output))

    def test_composed_numbers_still_agree_either_way(self) -> None:
        source = "the budget is forty two thousand dollars and twenty one seats"
        self.assertTrue(accepted(source, "The budget is $42,000 for 21 seats."))
        self.assertTrue(accepted(source, "The budget is forty-two thousand dollars for twenty-one seats."))


class TheGateStillRefusesChangedFactsTests(unittest.TestCase):
    def test_a_changed_number_is_still_refused(self) -> None:
        source = "the budget is twelve thousand and the deadline is the twelfth"
        self.assertFalse(accepted(source, "The budget is 15,000 and the deadline is the 12th."))
        self.assertFalse(accepted(source, "The budget is 12,000 and the deadline is the 13th."))

    def test_a_real_count_of_one_is_still_a_fact_when_written_as_a_numeral(self) -> None:
        # The gate no longer manufactures the fact 1 from the word "one", so a
        # model that writes the numeral 1 for a spoken "one" is adding a digit
        # the speech never had; it falls back to the rules, as any invented
        # numeral does. Writing the word keeps it safe.
        source = "we only need one licence for the whole team"
        self.assertFalse(accepted(source, "We only need 1 licence for the whole team."))
        self.assertTrue(accepted(source, "We only need one licence for the whole team."))

    def test_a_lone_one_after_a_label_noun_is_still_a_numeral(self) -> None:
        # "Group one" is a numeral the model rightly writes as "Group 1";
        # "the old one" never is. The label noun decides.
        source = "group one twelve fifteen p.m. three people group two twelve thirty p.m. two people"
        self.assertTrue(accepted(source, "Group 1: 12:15 P.M. (3 people). Group 2: 12:30 P.M. (2 people)."))
        self.assertTrue(accepted("we are on version one of the deck", "We are on version 1 of the deck."))
        self.assertFalse(accepted("keep the old one and bin the rest", "Keep the old 1 and bin the rest."))

    def test_spoken_list_ordinals_remain_structure(self) -> None:
        source = "first we ship the installer second we measure the funnel third we call the studio"
        output = "1. Ship the installer.\n2. Measure the funnel.\n3. Call the studio."
        self.assertTrue(accepted(source, output))


if __name__ == "__main__":
    unittest.main()
