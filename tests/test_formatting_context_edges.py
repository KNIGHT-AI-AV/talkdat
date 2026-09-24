"""Held-out review cases: a matching word is not always a number or address."""
from __future__ import annotations

import unittest

from knight_flow.number_text import normalize_numbers
from knight_flow.text_pipeline import process_dictation
from tests.parity_battery import local_config


class ContextEdgeTests(unittest.TestCase):
    def test_oh_is_a_zero_only_in_a_decimal_digit_position(self):
        self.assertEqual(normalize_numbers("zero point oh five"), "0.05")
        self.assertEqual(normalize_numbers("oh five minutes should be enough"), "oh five minutes should be enough")

    def test_may_as_a_modal_does_not_become_an_ordinal_date(self):
        self.assertEqual(normalize_numbers("we may first check the logs"), "we may first check the logs")
        self.assertEqual(normalize_numbers("meet on may first"), "meet on May 1st")

    def test_pounds_of_weight_are_not_money(self):
        for phrase in ("the bag weighs twenty pounds", "the cargo weighs one hundred pounds",
                       "buy twenty pounds of rice"):
            with self.subTest(phrase=phrase):
                result = normalize_numbers(phrase)
                self.assertNotIn(chr(163), result)
                self.assertIn("pounds", result)
        self.assertEqual(normalize_numbers("the bag costs twenty pounds"), "the bag costs " + chr(163) + "20")

    def test_a_domain_does_not_swallow_preceding_prose(self):
        self.assertEqual(process_dictation("I like example dot com", local_config(), local_only=True).text,
                         "I like example.com.")

    def test_literal_punctuation_words_are_not_domain_labels(self):
        self.assertEqual(process_dictation("say the words dot com", local_config(), local_only=True).text,
                         "Say the words dot com.")


if __name__ == "__main__":
    unittest.main()
