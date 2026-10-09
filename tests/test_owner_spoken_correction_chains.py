"""Owner's abandoned story choices must settle even when AI falls back."""
import copy
import unittest

from knight_flow.config import DEFAULT_CONFIG
from knight_flow.text_pipeline import process_dictation, resolve_spoken_retractions


class SpokenCorrectionChains(unittest.TestCase):
    def test_basic_cleanup_preserves_perspective_uncertainty_and_quoted_words(self):
        for level in ("medium", "high"):
            config = copy.deepcopy(DEFAULT_CONFIG)
            config["cleanup"].update(smart_format=False, level=level)
            for source in ("We maybe need the report.", "I think maybe we should wait.",
                           'She wrote "we maybe need the report."'):
                with self.subTest(level=level, source=source):
                    self.assertEqual(process_dictation(source, config, local_only=True).text, source)

    def test_grammatical_double_copulas_are_not_stutters(self):
        for raw in ("What it is is a scheduling problem.",
                    "All this is is a first draft.",
                    "What he is is a careful reviewer."):
            with self.subTest(raw=raw):
                self.assertEqual(resolve_spoken_retractions(raw), raw)
                self.assertEqual(process_dictation(raw, copy.deepcopy(DEFAULT_CONFIG), local_only=True).text, raw)

    def test_changed_mind_and_article_chain_settle_on_the_last_animal(self):
        raw = ("I'm gonna tell you a story about a cat. Actually I changed my mind, no, "
               "I'm gonna tell you a story about a dog. I mean a cat. I mean a lion.")
        expected = "I'm gonna tell you a story about a lion."
        self.assertEqual(resolve_spoken_retractions(raw), expected)
        config = copy.deepcopy(DEFAULT_CONFIG)
        config["cleanup"]["smart_format"] = False
        self.assertEqual(process_dictation(raw, config, local_only=True).text, expected)

    def test_correction_keeps_prior_and_following_sentences(self):
        raw = "Keep this introduction. Tell a story about a dog. I mean a cat. I mean a lion. Then send it."
        self.assertEqual(resolve_spoken_retractions(raw), "Keep this introduction. Tell a story about a lion. Then send it.")

    def test_the_owners_introduction_does_not_hide_the_repeated_story_head(self):
        raw = ("I'm using Talk that right now. So like right now I'll say I'm gonna tell you a story about a cat. "
               "Actually I changed my mind, no, I'm gonna tell you a story about a dog. "
               "I mean a cat. I mean a lion. So I'm gonna be talking about a lion that went to the store.")
        output = resolve_spoken_retractions(raw)
        self.assertNotIn("a cat", output)
        self.assertNotIn("a dog", output)
        self.assertIn("So like right now I'll say I'm gonna tell you a story about a lion.", output)
        self.assertTrue(output.endswith("a lion that went to the store."))

    def test_a_new_clause_after_i_mean_is_an_explanation(self):
        for text in ("I saw a cat. I mean a lion is not a cat.",
                     "I need a plan. I mean a plan that we can afford.",
                     "I changed my mind about the film. Tell me a story."):
            with self.subTest(text=text):
                self.assertEqual(resolve_spoken_retractions(text), text)

    def test_repeated_function_words_are_removed_without_removing_emphasis(self):
        text = "All all the mistakes that it is is making look very very bad."
        self.assertEqual(resolve_spoken_retractions(text), "All the mistakes that it is making look very very bad.")

    def test_grammatical_repetition_is_preserved(self):
        text = "I had had enough. I knew that that was very very bad."
        self.assertEqual(resolve_spoken_retractions(text), text)

    def test_owners_like_stutter_and_a_real_comparison(self):
        self.assertEqual(resolve_spoken_retractions("This is just like like an example."),
                         "This is just like an example.")
        self.assertEqual(resolve_spoken_retractions("I like like-minded people."),
                         "I like like-minded people.")

    def test_verbatim_keeps_the_corrections_as_spoken(self):
        config = copy.deepcopy(DEFAULT_CONFIG)
        config["cleanup"]["level"] = "none"
        raw = "A dog. I mean a cat. I mean a lion."
        self.assertEqual(process_dictation(raw, config, local_only=True).text, raw)

    def test_literal_quotes_do_not_become_spoken_corrections(self):
        config = copy.deepcopy(DEFAULT_CONFIG)
        config["cleanup"]["smart_format"] = False
        raw = 'She said "a dog. I mean a cat."'
        self.assertIn('"a dog. I mean a cat."', process_dictation(raw, config, local_only=True).text)

    def test_explicit_numbered_items_keep_their_layout_and_tone(self):
        config = copy.deepcopy(DEFAULT_CONFIG)
        config["cleanup"].update(smart_format=True, format_mode="heuristic", profanity_filter=False)
        raw = ("Here are four fixes:\n1. It needs fucking formatting.\n"
               "2. It needs itemizing.\n3. Make it clean as fuck.\n4. Keep the intended meaning.")
        output = process_dictation(raw, config, local_only=True).text
        for item in ("1. It needs fucking formatting.", "2. It needs itemizing.",
                     "3. Make it clean as fuck.", "4. Keep the intended meaning."):
            self.assertIn(item, output)


if __name__ == "__main__":
    unittest.main()
