"""Late name repair preserves literal examples while repairing ordinary prose."""
import unittest
from knight_flow.name_repair import repair_names

CONFIG = {'dictionary': {'words': ['Kaelyn']}, '_asr_confidence': {'kalen': .3}}

class LiteralNamesTests(unittest.TestCase):
    def test_brand_case_can_be_normalized_without_substituting_quoted_words(self):
        from knight_flow.text_pipeline import apply_vocabulary_terms
        config = {'dictionary': {'terms': [{'text': 'Kaelyn', 'sounds_like': ['kalen']}]}}
        self.assertEqual(apply_vocabulary_terms('Use "github and ask kalen". Ask kalen.', config),
                         'Use "GitHub and ask kalen". Ask Kaelyn.')

    def test_code_inside_a_quote_remains_exact_even_for_brand_case(self):
        from knight_flow.text_pipeline import apply_vocabulary_terms
        self.assertEqual(apply_vocabulary_terms('Use "`github` and github".', {}),
                         'Use "`github` and GitHub".')

    def test_quoted_name_remains_literal_and_unquoted_name_is_repaired(self):
        text = 'She wrote "ask kalen". Ask kalen.'
        self.assertEqual(repair_names(text, CONFIG), 'She wrote "ask kalen". Ask Kaelyn.')

    def test_curly_quoted_name_remains_literal(self):
        self.assertEqual(repair_names('She wrote “ask kalen”. Ask kalen.', CONFIG),
                         'She wrote “ask kalen”. Ask Kaelyn.')

    def test_inline_code_name_remains_literal(self):
        self.assertEqual(repair_names('Run `ask kalen`. Ask kalen.', CONFIG),
                         'Run `ask kalen`. Ask Kaelyn.')

    def test_negation_numbers_and_emphasis_remain_with_unquoted_name(self):
        self.assertEqual(repair_names('No, no, no. Do not ask kalen for 12.50.', CONFIG),
                         'No, no, no. Do not ask Kaelyn for 12.50.')

    def test_single_quotes_with_a_contraction_keep_the_literal_name(self):
        text = "She wrote 'I can't ask kalen'. Ask kalen."
        self.assertEqual(repair_names(text, CONFIG), "She wrote 'I can't ask kalen'. Ask Kaelyn.")

    def test_code_with_quotes_does_not_confuse_the_outer_quotation(self):
        text = 'She wrote "`print("kalen")` and ask kalen". Ask kalen.'
        self.assertEqual(repair_names(text, CONFIG),
                         'She wrote "`print("kalen")` and ask kalen". Ask Kaelyn.')

    def test_vocabulary_and_explicit_dictionary_preserve_quoted_examples(self):
        from knight_flow.text_pipeline import apply_dictionary, apply_vocabulary_terms
        config = {'dictionary': {'terms': [{'text': 'Kaelyn', 'sounds_like': ['kalen']}],
                  'replacements': [{'from': 'kalen', 'to': 'Kaelyn'}]}}
        text = 'She wrote "ask kalen". Ask kalen.'
        expected = 'She wrote "ask kalen". Ask Kaelyn.'
        self.assertEqual(apply_dictionary(text, config), expected)
        self.assertEqual(apply_vocabulary_terms(text, config), expected)

    def test_complete_delivery_keeps_quoted_name_negation_number_and_emphasis(self):
        from unittest.mock import patch
        from knight_flow.text_pipeline import process_dictation
        config = {**CONFIG, 'cleanup': {'level': 'none', 'smart_format': False},
                  'plugins': {'enabled': False}}
        text = 'She wrote "ask kalen". Do not ask kalen for 12.50. No, no, no.'
        with patch('knight_flow.format_journal.record_formatting'):
            result = process_dictation(text, config, local_only=True)
        self.assertEqual(result.text,
                         'She wrote "ask kalen". Do not ask Kaelyn for 12.50. No, no, no.')

if __name__ == '__main__':
    unittest.main()
