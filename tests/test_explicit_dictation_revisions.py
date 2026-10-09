"""Synthetic intent examples; no audio, models, clipboard or network."""
import copy
import unittest
from unittest.mock import patch

from knight_flow.config import DEFAULT_CONFIG
from knight_flow.text_pipeline import process_dictation, resolve_spoken_retractions


class ExplicitRevisionTests(unittest.TestCase):
    def test_compound_cues_and_full_clause_replacements(self):
        cases = [
            ('I want to go the the moon- oh wait sorry no I meant I want to got to the saloon',
             'I want to go to the saloon'),
            ('I want to go to the moon, oh wait, sorry, no, I meant I want to go to the saloon.',
             'I want to go to the saloon.'),
            ('I want to go to the moon. Oh wait, I meant I want to go to the saloon.',
             'I want to go to the saloon.'),
            ('Keep the introduction. I want to visit the moon — sorry, I meant I want to visit the saloon. Then call Maya.',
             'Keep the introduction. I want to visit the saloon. Then call Maya.'),
            ('I want to go to the moon, I meant I want to go to the saloon, no, I meant I want to go to the park.',
             'I want to go to the park.'),
            ('I want to send the report, oh wait, I meant I want to not send the report.',
             'I want to not send the report.'),
            ('We need to call Maya, sorry, I meant we need to call NavOrb.',
             'we need to call NavOrb.'),
            ('Please note that I want to visit the moon, no, I meant I want to visit the saloon.',
             'Please note that I want to visit the saloon.'),
        ]
        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertEqual(resolve_spoken_retractions(raw), expected)

    def test_ambiguous_edits_and_normal_cue_words_are_preserved(self):
        for raw in (
            'I want to go to the moon, oh wait sorry no I meant the saloon.',
            'Send Maya 42, I meant 43.',
            'I want to go to the moon, I meant she wants to go to the saloon.',
            'I actually enjoyed it.',
            "I'm sorry I cannot approve.",
            'I want to go to the moon, I did not mean I want to go to the saloon.',
            'I need a plan. I mean a plan that we can afford.',
            'We can, we should, we must act.',
            'Very very good, really really good.',
            'Had had and that that are grammatical examples.',
            'Send 42.50 to Maya on October 12.',
            'Je veux aller au salon, pas sur la lune.',
            'I want to go to The The concert.',
            'Go now, go now!',
            'Again and again, again and again.',
            'Call Maya, I mean call Maya.',
        ):
            with self.subTest(raw=raw):
                self.assertEqual(resolve_spoken_retractions(raw), raw)

    def test_quotes_code_paths_and_identifiers_are_opaque(self):
        cases = (
            'She said "call Maya, I mean call NavOrb."',
            'She said “I want to go to the moon, I meant I want to go to the saloon.”',
            'She said ‘call Maya, I mean call NavOrb.’',
            'She said «call Maya, I mean call NavOrb.»',
            'She said "call Maya, I mean call NavOrb.',
            "She said 'a dog. I mean a cat.'",
            '`call Maya, I mean call NavOrb`',
            '```text\ncall Maya, I mean call NavOrb\n```',
            'Open /notes/i_mean and keep Maya_42.',
            'Visit https://example.com/i_mean and keep the link.',
            'I want to open /notes/moon, I meant I want to open /notes/saloon.',
        )
        for raw in cases:
            with self.subTest(raw=raw):
                self.assertEqual(resolve_spoken_retractions(raw), raw)

    def test_ordinary_duplicate_article_is_fixed_without_changing_a_name(self):
        self.assertEqual(resolve_spoken_retractions('Go to the the saloon.'), 'Go to the saloon.')
        self.assertEqual(resolve_spoken_retractions('The the moon is bright.'), 'The moon is bright.')
        self.assertEqual(resolve_spoken_retractions('The The played tonight.'), 'The The played tonight.')
        self.assertEqual(resolve_spoken_retractions("it's really, it's really good"), "it's really good")

    def test_rule_path_reaches_final_output_without_model_or_learning(self):
        config = copy.deepcopy(DEFAULT_CONFIG)
        config['cleanup'].update(smart_format=False, level='medium')
        before = copy.deepcopy(config)
        raw = 'i want to go the the moon- oh wait sorry no i meant i want to got to the saloon'
        with patch('knight_flow.text_pipeline.llm_rewrite', side_effect=AssertionError('No model')):
            result = process_dictation(raw, config, local_only=True)
        self.assertEqual(result.text, 'I want to go to the saloon.')
        self.assertEqual(config, before, 'A change of plans must not become a saved preference')

    def test_verbatim_route_keeps_the_spoken_revision(self):
        config = copy.deepcopy(DEFAULT_CONFIG)
        config['cleanup'].update(smart_format=False, level='none')
        raw = 'I want to go to the moon, oh wait sorry no I meant I want to go to the saloon.'
        self.assertEqual(process_dictation(raw, config, local_only=True).text, raw)

    def test_correction_cues_cannot_reuse_a_stale_progressive_prefix(self):
        from knight_flow.progressive_formatting import _joinable
        source = 'I want to go to the moon.'
        config = {'cleanup': {}}
        for suffix in (
            'I meant I want to go to the saloon.',
            'Oh wait sorry no I meant I want to go to the saloon.',
            'I mean I want to go to the saloon.',
        ):
            with self.subTest(suffix=suffix):
                self.assertFalse(_joinable(source, source, suffix, config))


class ExplicitLearningSafetyTests(unittest.TestCase):
    def test_an_unspecified_or_invalid_learning_mode_requires_acceptance(self):
        from knight_flow.learned_words import auto_learn_mode, note_fix_evidence
        for index, config in enumerate(({}, {'dictionary': {}},
                       {'dictionary': {'auto_learn_mode': 'nonsense'}}, copy.deepcopy(DEFAULT_CONFIG))):
            with self.subTest(case=index):
                self.assertEqual(auto_learn_mode(config), 'offer')
                self.assertEqual(note_fix_evidence('SAHVVV', config, 1000.0), 'offer')
                self.assertFalse(config.get('dictionary', {}).get('terms'))

    def test_explicit_automatic_learning_and_off_choices_are_preserved(self):
        from knight_flow.learned_words import auto_learn_mode, note_fix_evidence
        for mode, verdict in (('auto-on-second', 'learn'), ('off', 'ignore')):
            config = {'dictionary': {'auto_learn_mode': mode}}
            self.assertEqual(auto_learn_mode(config), mode)
            self.assertEqual(note_fix_evidence('SAHVVV', config, 1000.0), verdict)

    def test_a_change_of_intent_does_not_create_a_global_replacement(self):
        from knight_flow.learned_words import correction_candidate
        for instruction in ('No, I meant the saloon.', 'Change the destination to saloon.',
                            'Make this more concise.'):
            self.assertIsNone(correction_candidate('I want to go to the moon.',
                                                   'I want to go to the saloon.', instruction))

    def test_accepted_spelling_is_inspectable_reversible_and_rejected_stays_rejected(self):
        from knight_flow.learned_words import correction_candidate, forget, remember_correction
        pair = correction_candidate('Ask May over.', 'Ask Mayowa.', 'Correct the spelling to Mayowa.')
        self.assertEqual(pair, ('May over', 'Mayowa'))
        config = {'dictionary': {'terms': []}}
        self.assertTrue(remember_correction(*pair, config))
        self.assertEqual(config['dictionary']['terms'],
                         [{'text': 'Mayowa', 'sounds_like': ['May over'], 'learned': True}])
        self.assertTrue(forget('Mayowa', config))
        self.assertEqual(config['dictionary']['terms'], [])
        self.assertFalse(remember_correction(*pair, config))

    def test_secrets_and_multiword_or_multiple_edits_are_not_learning_evidence(self):
        from knight_flow.learned_words import correction_candidate, remember_correction
        for before, after, instruction in (
            ('Use the old password.', 'Use AbcDEf1234567890.', 'Correct spelling to AbcDEf1234567890'),
            ('Send Maya 42.', 'Send NavOrb 43.', 'Correct spelling to NavOrb'),
            ('Open the old path.', 'Open /private/key.', 'Correct spelling to /private/key'),
            ('Call the team.', 'Call Maya and NavOrb.', 'Correct spelling to Maya and NavOrb'),
        ):
            with self.subTest(before=before):
                self.assertIsNone(correction_candidate(before, after, instruction))
        config = {'dictionary': {'terms': [{'text': 'Mayowa', 'sounds_like': ['my name']}]}}
        self.assertFalse(remember_correction('May over', 'Mayowa', config))
        self.assertEqual(config['dictionary']['terms'][0]['sounds_like'], ['my name'])


if __name__ == '__main__':
    unittest.main()
