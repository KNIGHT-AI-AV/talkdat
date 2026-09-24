"""A change of register cannot become a change of certainty or permission."""
import unittest

from knight_flow.formatting import _valid_formatter_output


class ExecutiveMeaningTests(unittest.TestCase):
    def test_rewrite_keeps_hedges_negations_and_obligations(self):
        for before, after in (
            ("I'm pretty sure we can finish tomorrow", "We can finish tomorrow."),
            ("We will probably finish tomorrow", "We will finish tomorrow."),
            ("You must not send the report yet", "You may send the report now."),
            ("The number is approximately twenty five", "The number is 25."),
            ("We might need another review before approval", "We need another review before approval."),
        ):
            with self.subTest(before=before):
                self.assertFalse(_valid_formatter_output(before, after, preserve_meaning=False, rewrite_mode=True))

    def test_register_can_change_while_certainty_survives(self):
        self.assertTrue(_valid_formatter_output(
            "hey we will probably get the report to you tomorrow",
            "We will probably deliver the report tomorrow.", preserve_meaning=False, rewrite_mode=True))

    def test_explicit_retraction_can_still_remove_its_negation(self):
        self.assertTrue(_valid_formatter_output(
            "Use the green folder, no wait, use the blue folder",
            "Use the blue folder.", preserve_meaning=False, rewrite_mode=True))
