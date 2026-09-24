"""Numbers and literal identifiers must survive every deterministic text pass."""
from __future__ import annotations

import unittest

from knight_flow.formatting import _remove_immediate_repeats
from knight_flow.text_pipeline import apply_dictionary, apply_vocabulary_terms, process_dictation
from tests.parity_battery import local_config


class RepeatIntegrityTests(unittest.TestCase):
    def test_digit_words_and_numeric_runs_are_never_stammers(self):
        for text in (
            "four one five five five five one two one two",
            "we launched in twenty twenty six",
            "the code is 1 1 2 2 1 1",
            "zero zero one one",
            "one two one two",
            "five hundred five hundred",
            "call 555 555 1212",
        ):
            with self.subTest(text=text):
                self.assertEqual(_remove_immediate_repeats(text), text)

    def test_actual_stammers_still_collapse(self):
        self.assertEqual(_remove_immediate_repeats("the the build is is green"), "the build is green")
        self.assertEqual(_remove_immediate_repeats("we should we should probably wait"), "we should probably wait")

    def test_comma_separated_numeric_phrases_also_survive_precleanup(self):
        from knight_flow.text_pipeline import resolve_spoken_retractions
        text = "the code is one two, one two"
        self.assertEqual(resolve_spoken_retractions(text), text)


class DictionaryIntegrityTests(unittest.TestCase):
    def test_public_brands_do_not_replace_phonetic_neighbours(self):
        for text in (
            "we launched in twenty twenty six",
            "the ship launched in June",
            "we linked into the existing service",
            "the blue teeth are painted",
        ):
            with self.subTest(text=text):
                self.assertEqual(apply_vocabulary_terms(text, {}), text)

    def test_real_brands_and_user_pronunciations_still_work(self):
        self.assertEqual(apply_vocabulary_terms("find me on linked in", {}), "find me on LinkedIn")
        cfg = {"dictionary": {"words": ["Mayowa"]}}
        self.assertEqual(apply_vocabulary_terms("my yo wa called", cfg), "Mayowa called")

    def test_literal_identifiers_are_opaque_to_both_dictionary_passes(self):
        cfg = {"dictionary": {"words": ["Mayowa"], "replacements": [{"from": "github", "to": "GitHub Enterprise"}]}}
        for literal in (
            "https://github.com/my-yo-wa/branch",
            "build@github.com",
            "github.com/docs",
            r"C:\github\my_yo_wa.py",
            "./github/my_yo_wa.py",
            "`github my yo wa`",
            "```python\nname = 'github my yo wa'\n```",
            "github_repo",
        ):
            with self.subTest(literal=literal):
                text = "use " + literal + " here"
                self.assertEqual(apply_dictionary(text, cfg), text)
                self.assertEqual(apply_vocabulary_terms(text, cfg), text)

    def test_a_brand_keeps_its_surrounding_quotes_and_sentence_end(self):
        self.assertEqual(apply_vocabulary_terms('Use "github" now.', {}), 'Use "GitHub" now.')
        self.assertEqual(apply_vocabulary_terms("I use talk dat.", {}), "I use Talk DAT!")


class LiteralPipelineTests(unittest.TestCase):
    def test_rules_do_not_rewrite_inside_code_or_identifiers(self):
        for literal in (
            "`i m = one one; comma = 5`",
            "https://example.com/new_line/i_m?value=one_one",
            "build@knightaiav.com",
            r"C:\code\new_line\formatting.py",
            "knight_flow/formatting.py",
        ):
            with self.subTest(literal=literal):
                result = process_dictation("please preserve " + literal + " exactly", local_config(), local_only=True).text
                self.assertIn(literal, result)

    def test_a_model_cannot_drop_or_invent_a_protected_literal(self):
        from knight_flow.formatting import _valid_formatter_output
        for candidate in ("Please keep the file exactly.", "Please keep TDLITERAL9TOKEN exactly."):
            self.assertFalse(_valid_formatter_output("please keep TDLITERAL0TOKEN exactly", candidate, rewrite_mode=True))

    def test_explicit_marks_and_their_literal_names_are_distinct(self):
        for spoken, expected in (
            ("this is well hyphen known", "This is well-known."),
            ("put it open bracket here close bracket please", "Put it [here] please."),
            ("please wait ellipsis", "Please wait..."),
            ("use an ellipsis here", "Use an ellipsis here"),
            ("add a hyphen between those words", "Add a hyphen between those words."),
            ("can we ship this question mark", "Can we ship this?"),
        ):
            with self.subTest(spoken=spoken):
                self.assertEqual(process_dictation(spoken, local_config(), local_only=True).text, expected)

    def test_genuine_words_are_not_false_contractions(self):
        result = process_dictation("the patient is ill and her id is missing", local_config(), local_only=True).text
        self.assertEqual(result, "The patient is ill and her ID is missing.")

    def test_split_contractions_preserve_negation(self):
        result = process_dictation("it s fine but i don t think we can t do it", local_config(), local_only=True).text
        self.assertEqual(result, "It's fine but I don't think we can't do it.")

    def test_existing_bullet_spacing_is_preserved(self):
        result = process_dictation("- alpha\n- beta\n- gamma", local_config(), local_only=True).text
        self.assertEqual(result, "- Alpha\n- Beta\n- Gamma")

    def test_small_custom_terms_can_choose_their_exact_casing(self):
        cfg = local_config()
        cfg["dictionary"]["words"] = ["Api"]
        self.assertEqual(process_dictation("the api is available today", cfg, local_only=True).text, "The Api is available today.")

    def test_no_em_dash_on_the_cleanup_only_lane(self):
        cfg = local_config()
        cfg["cleanup"]["smart_format"] = False
        result = process_dictation("we ship " + chr(8212) + " every platform", cfg, local_only=True).text
        self.assertNotIn(chr(8212), result)


class QuotedPathTests(unittest.TestCase):
    def test_dictionary_cannot_rewrite_a_quoted_path_with_spaces(self):
        from knight_flow.text_pipeline import apply_dictionary
        raw = 'open "C:\\My Files\\audit.py" after lunch'
        self.assertEqual(apply_dictionary(raw, {"dictionary": {"replacements": [
            {"from": "Files", "to": "Documents"}]}}), raw)


if __name__ == "__main__":
    unittest.main()
