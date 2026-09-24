"""Owner's numeric intent: digits first, formatting only with evidence."""
import unittest

from knight_flow.number_text import normalize_numbers
from knight_flow.formatting import _refine_formatted_output


CASES = (
    ('one two three four', '1234'),
    ('five five', '55'),
    ('zero zero one two', '0012'),
    ('oh seven zero three', '0703'),
    ('oh five minutes should be enough', 'oh five minutes should be enough'),
    ('one 2 three 4', '1234'),
    ('seven', '7'),
    ('my code is seven', 'my code is 7'),
    ('code forty nine ninety nine', 'code 4999'),
    ('twenty twenty six', '20 26'),
    ('numbers ten eleven twelve', 'numbers 10, 11, 12'),
    ('the code is double zero triple five two', 'the code is 005552'),
    ('my social security number is one two three four five six seven eight nine', 'my social security number is 123-45-6789'),
    ('my social security is one two three four five six seven eight', 'my social security is 12345678'),
    ('SSN: 123456789', 'SSN: 123-45-6789'),
    ('my card number is four one one one one one one one one one one one one one one one', 'my card number is 4111 1111 1111 1111'),
    ('credit card 378282246310005', 'credit card 3782 822463 10005'),
    ('the account number is zero zero one two three four five six seven', 'the account number is 001234567'),
    ('serial number 1234567890123456', 'serial number 1234567890123456'),
    ('one two three four five six seven eight nine', '123456789'),
    ('one two three four five six seven eight nine zero', '1234567890'),
    ('call one two three four five six seven eight nine zero', 'call 123-456-7890'),
    ('the phone is broken. My code is one two three four five six seven eight nine zero', 'the phone is broken. My code is 1234567890'),
    ('my card failed, the phone number is four one five five five five one two one two', 'my card failed, the phone number is 415-555-1212'),
    ('phone 4155551212 extension zero zero seven', 'phone 415-555-1212 extension 007'),
    ('the PIN is one two one two', 'the PIN is 1212'),
    ('the scores are one two three', 'the scores are 1, 2, 3'),
    ('choose numbers one two three', 'choose numbers 1, 2, 3'),
    ('one, two, and three', '1, 2, and 3'),
    ('I need one or two chairs', 'I need one or two chairs'),
    ('one of a kind', 'one of a kind'),
    ('no one came', 'no one came'),
    ('I will be there in a second', 'I will be there in a second'),
    ('one on one', 'one on one'),
    ('call me when one of them arrives', 'call me when one of them arrives'),
    ('the phone is one of a kind', 'the phone is one of a kind'),
    ('my card is one of those old ones', 'my card is one of those old ones'),
    ('the code is one of the examples', 'the code is one of the examples'),
    ('double trouble and triple chocolate', 'double trouble and triple chocolate'),
    ('one point zero zero six', '1.006'),
    ('the code is one two and the price is five dollars', 'the code is 12 and the price is $5'),
    ('the total is one thousand two hundred and three', 'the total is 1,203'),
    ('room one thousand two hundred and three', 'room 1203'),
    ('in twenty twenty six', 'in 2026'),
    ('`one two three` https://example.com/one_two three people', '`one two three` https://example.com/one_two three people'),
    ('one hundred hundred', 'one hundred hundred'),
)


class NumericIntentTests(unittest.TestCase):
    def test_spoken_intent(self):
        for spoken, expected in CASES:
            with self.subTest(spoken=spoken):
                self.assertEqual(normalize_numbers(spoken), expected)

    def test_second_pass_does_not_change_numbers_or_spacing(self):
        for _, expected in CASES:
            with self.subTest(expected=expected):
                self.assertEqual(normalize_numbers(expected), expected)

    def test_actual_formatting_path_keeps_every_digit(self):
        self.assertEqual(_refine_formatted_output('My social security is one two three four five six seven eight.'),
                         'My social security is 12345678.')
        self.assertEqual(_refine_formatted_output('My code is zero zero five five.'), 'My code is 0055.')

    def test_large_identifier_is_not_converted_to_integer_or_truncated(self):
        spoken = 'zero one ' * 2000
        self.assertEqual(normalize_numbers('code ' + spoken), 'code ' + '01' * 2000 + ' ')


if __name__ == '__main__':
    unittest.main()
