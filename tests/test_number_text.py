"""Written quantities without guessing at unrelated numeric speech."""
import unittest

from knight_flow.number_text import cardinal, normalize_numbers


class NumberNormalizationTests(unittest.TestCase):
    def test_anchored_quantities(self):
        for spoken, expected in (
            ("twenty five users and three hundred forty two signups", "25 users and 342 signups"),
            ("one thousand two hundred and three", "1,203"),
            ("nineteen dollars", "$19"),
            ("five dollars and fifty cents", "$5.50"),
            ("ten percent", "10%"),
            ("twenty five per cent", "25%"),
            ("zero point six billion", "0.6 billion"),
            ("point releases take one day", "point releases take one day"),
            ("one point zero zero six", "1.006"),
            ("call me at four one five five five five one two one two", "call me at 415-555-1212"),
            ("the pin is zero zero one one", "the pin is 0011"),
            ("we launched in twenty twenty six", "we launched in 2026"),
            ("born in nineteen oh five", "born in 1905"),
            ("september eighteenth", "September 18th"),
            ("january twenty first", "January 21st"),
            ("two thirds of users", "two-thirds of users"),
            ("a twenty one year old car", "a 21-year-old car"),
            ("she is twenty one years old", "she is 21 years old"),
        ):
            with self.subTest(spoken=spoken):
                self.assertEqual(normalize_numbers(spoken), expected)

    def test_ambiguous_runs_and_identifiers_are_preserved(self):
        for text in (
            "one hundred hundred",
            "one million million", "the old one", "no one came", "the second quarter",
            "`twenty five dollars`", "https://example.com/twenty_five",
        ):
            with self.subTest(text=text):
                self.assertEqual(normalize_numbers(text), text)

    def test_parser_rejects_bad_grammar(self):
        for text in ("", "one two", "twenty twenty", "zero hundred", "one million million", "one thousand two million"):
            with self.subTest(text=text):
                self.assertIsNone(cardinal(text))

    def test_money_does_not_invent_units_or_cross_sentence_boundaries(self):
        # X-607 (commandment 55): straight after a price word it is one price.
        self.assertEqual(normalize_numbers("the cost is forty nine ninety nine"), "the cost is 49.99")
        self.assertEqual(normalize_numbers("the price is nineteen ninety nine"), "the price is 19.99")
        self.assertEqual(normalize_numbers("we met in nineteen ninety nine"), "we met in 1999")
        self.assertEqual(normalize_numbers("the plan costs nineteen dollars and the pro one is forty nine ninety nine"), "the plan costs $19 and the pro one is $49.99")
        self.assertEqual(normalize_numbers("nineteen dollars. The code is forty nine ninety nine"), "$19. The code is 4999")


if __name__ == "__main__":
    unittest.main()
