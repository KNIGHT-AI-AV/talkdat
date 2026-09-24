"""The deterministic dictation pipeline.

Every dictation passes through these functions, but tests previously only reached them
indirectly through process_dictation. These cover them directly: voice edit commands,
dictionary and snippet expansion, PII and profanity redaction, URL protection, and the
cleanup levels.
"""

from __future__ import annotations

import unittest

from knight_flow.text_pipeline import (
    add_terminal_punctuation,
    apply_backtrack,
    apply_dictionary,
    apply_snippets,
    capitalize_sentences,
    cleanup_text,
    command_to_transform,
    empathize,
    make_concise,
    make_formal,
    normalize_spaces,
    protect_urls,
    redact_sensitive,
    remove_previous_phrase,
    replace_phrase,
    restore_urls,
    turn_to_list,
    unified_diff,
)


class WhitespaceAndSentenceTests(unittest.TestCase):
    def test_runs_of_whitespace_collapse(self) -> None:
        self.assertEqual(normalize_spaces("  hello   there \t world  "), "hello there world")

    def test_empty_input_stays_empty(self) -> None:
        self.assertEqual(normalize_spaces(""), "")
        self.assertEqual(normalize_spaces("     "), "")

    def test_each_sentence_gets_a_capital(self) -> None:
        self.assertEqual(capitalize_sentences("hello there. how are you?"), "Hello there. How are you?")

    def test_a_full_sentence_gets_a_full_stop(self) -> None:
        self.assertEqual(
            add_terminal_punctuation("this is a longer sentence"), "this is a longer sentence."
        )

    def test_existing_terminal_punctuation_is_never_doubled(self) -> None:
        for text in ("this is already done.", "is it a question?", "stop!", 'he said "no"'):
            self.assertEqual(add_terminal_punctuation(text), text)

    def test_short_fragments_are_left_unpunctuated(self) -> None:
        # Dictating "hello there" into a chat box should not become "hello there."
        self.assertEqual(add_terminal_punctuation("hello there"), "hello there")
        self.assertEqual(add_terminal_punctuation("ok"), "ok")

    def test_multi_line_text_keeps_its_own_structure(self) -> None:
        self.assertEqual(add_terminal_punctuation("line one\nline two here"), "line one\nline two here")

    def test_empty_input_is_returned_as_is(self) -> None:
        self.assertEqual(add_terminal_punctuation(""), "")


class RemovePreviousPhraseTests(unittest.TestCase):
    def test_the_last_sentence_is_dropped(self) -> None:
        self.assertEqual(remove_previous_phrase("One. Two. Three"), "One. Two.")

    def test_a_trailing_terminator_does_not_count_as_the_boundary(self) -> None:
        self.assertEqual(remove_previous_phrase("One. Two."), "One.")

    def test_a_single_sentence_leaves_nothing(self) -> None:
        self.assertEqual(remove_previous_phrase("Only one thing"), "")
        self.assertEqual(remove_previous_phrase(""), "")


class BacktrackTests(unittest.TestCase):
    def test_scratch_that_removes_the_previous_sentence(self) -> None:
        self.assertEqual(
            apply_backtrack("Call Bob at noon. Meet Sue. scratch that"),
            "Call Bob at noon.",
        )

    def test_every_documented_erase_phrase_works(self) -> None:
        for phrase in (
            "scratch that", "strike that", "delete that", "remove that",
            "ignore that", "cancel that", "undo that", "delete last sentence",
            "scratch that last part", "delete that last part",
        ):
            with self.subTest(phrase=phrase):
                self.assertEqual(apply_backtrack(f"Keep this. Drop this. {phrase}"), "Keep this.")

    def test_delete_last_word_removes_exactly_one_word(self) -> None:
        self.assertEqual(apply_backtrack("send the red ball delete last word"), "send the red")

    def test_start_over_discards_everything_before_it(self) -> None:
        self.assertEqual(apply_backtrack("blah blah start over the real text"), "the real text")

    def test_the_commands_are_case_insensitive(self) -> None:
        self.assertEqual(apply_backtrack("Keep this. Drop this. SCRATCH THAT"), "Keep this.")

    def test_ordinary_dictation_is_untouched(self) -> None:
        self.assertEqual(apply_backtrack("just normal text"), "just normal text")

    def test_a_command_with_nothing_before_it_clears_the_text(self) -> None:
        self.assertEqual(apply_backtrack("scratch that"), "")

    def test_repeated_commands_terminate_instead_of_looping(self) -> None:
        # The loop rewrites `text` in place; a command that keeps reappearing would hang.
        self.assertEqual(apply_backtrack("scratch that scratch that"), "")
        self.assertEqual(apply_backtrack("a. b. scratch that scratch that"), "")

    def test_text_after_the_command_is_kept(self) -> None:
        self.assertEqual(apply_backtrack("One. Two. scratch that and then three"), "One. and then three")


class ReplacementTests(unittest.TestCase):
    def test_replacement_respects_word_boundaries(self) -> None:
        self.assertEqual(
            replace_phrase("nothing to see, thing here", "thing", "item"),
            "nothing to see, item here",
        )

    def test_replacement_ignores_case_in_the_source(self) -> None:
        self.assertEqual(replace_phrase("Thing and THING", "thing", "item"), "item and item")

    def test_an_empty_source_changes_nothing(self) -> None:
        self.assertEqual(replace_phrase("unchanged", "", "x"), "unchanged")

    def test_dictionary_entries_are_applied(self) -> None:
        config = {"dictionary": {"replacements": [{"from": "teh", "to": "the"}]}}
        self.assertEqual(apply_dictionary("teh cat", config), "the cat")

    def test_incomplete_dictionary_entries_are_skipped(self) -> None:
        config = {"dictionary": {"replacements": [{"from": "  ", "to": "x"}, {"from": "y", "to": ""}]}}
        self.assertEqual(apply_dictionary("y and stuff", config), "y and stuff")

    def test_a_missing_dictionary_is_not_an_error(self) -> None:
        self.assertEqual(apply_dictionary("untouched", {}), "untouched")


class SnippetTests(unittest.TestCase):
    CONFIG = {"snippets": [{"trigger": "sig", "text": "Best,\nMayowa"}]}

    def test_a_dictation_that_is_only_the_trigger_expands_fully(self) -> None:
        self.assertEqual(apply_snippets("sig", self.CONFIG), "Best,\nMayowa")

    def test_trailing_punctuation_still_counts_as_an_exact_trigger(self) -> None:
        self.assertEqual(apply_snippets("sig.", self.CONFIG), "Best,\nMayowa")

    def test_a_trigger_inside_a_sentence_is_replaced_in_place(self) -> None:
        self.assertEqual(apply_snippets("add sig here", self.CONFIG), "add Best,\nMayowa here")

    def test_a_disabled_snippet_never_fires(self) -> None:
        config = {"snippets": [{"trigger": "sig", "text": "Best", "enabled": False}]}
        self.assertEqual(apply_snippets("sig", config), "sig")

    def test_the_longest_trigger_wins_when_two_overlap(self) -> None:
        config = {
            "snippets": [
                {"trigger": "addr", "text": "SHORT"},
                {"trigger": "addr home", "text": "LONG"},
            ]
        }
        self.assertEqual(apply_snippets("addr home", config), "LONG")

    def test_a_blank_trigger_cannot_match_everything(self) -> None:
        config = {"snippets": [{"trigger": "  ", "text": "NOPE"}]}
        self.assertEqual(apply_snippets("ordinary text", config), "ordinary text")


class RedactionTests(unittest.TestCase):
    SENSITIVE = "mail a@b.com call 555-123-4567 ssn 123-45-6789"

    def test_nothing_is_redacted_unless_it_is_switched_on(self) -> None:
        self.assertEqual(redact_sensitive(self.SENSITIVE, {}), self.SENSITIVE)
        self.assertEqual(redact_sensitive("what the shit", {}), "what the shit")

    def test_each_pii_shape_is_replaced_with_its_token(self) -> None:
        out = redact_sensitive(self.SENSITIVE, {"privacy": {"redact_pii": True}})
        for token in ("[email]", "[phone]", "[ssn]"):
            self.assertIn(token, out)
        for leaked in ("a@b.com", "555-123-4567", "123-45-6789"):
            self.assertNotIn(leaked, out)

    def test_card_numbers_are_replaced(self) -> None:
        out = redact_sensitive("card 4111 1111 1111 1111 end", {"privacy": {"redact_pii": True}})
        self.assertIn("[card]", out)
        self.assertNotIn("4111", out)

    def test_profanity_keeps_its_first_letter_and_length(self) -> None:
        out = redact_sensitive("oh shit", {"cleanup": {"censor_profanity": True}})
        self.assertEqual(out, "oh s***")

    def test_redaction_and_censoring_are_independent_switches(self) -> None:
        pii_only = redact_sensitive("a@b.com shit", {"privacy": {"redact_pii": True}})
        self.assertIn("[email]", pii_only)
        self.assertIn("shit", pii_only)


class UrlProtectionTests(unittest.TestCase):
    def test_urls_survive_a_protect_and_restore_round_trip(self) -> None:
        original = "see https://x.com/a?b=1 and www.y.io now"
        protected, tokens = protect_urls(original)
        self.assertNotIn("https://", protected)
        self.assertEqual(len(tokens), 2)
        self.assertEqual(restore_urls(protected, tokens), original)

    def test_markdown_links_are_protected_whole(self) -> None:
        protected, tokens = protect_urls("read [the docs](https://example.com/x)")
        self.assertEqual(list(tokens.values()), ["[the docs](https://example.com/x)"])
        self.assertEqual(restore_urls(protected, tokens), "read [the docs](https://example.com/x)")

    def test_text_without_urls_is_unchanged(self) -> None:
        protected, tokens = protect_urls("no links here")
        self.assertEqual(protected, "no links here")
        self.assertEqual(tokens, {})

    def test_restoring_with_no_tokens_is_a_no_op(self) -> None:
        self.assertEqual(restore_urls("plain", {}), "plain")


class CleanupLevelTests(unittest.TestCase):
    def test_level_none_only_normalises_whitespace(self) -> None:
        self.assertEqual(cleanup_text("  um   hello   world  ", {"cleanup": {"level": "none"}}), "um hello world")

    def test_medium_removes_fillers_and_finishes_the_sentence(self) -> None:
        out = cleanup_text("um i think maybe we should go", {"cleanup": {"level": "medium"}})
        self.assertEqual(out, "I think we should go.")

    def test_light_capitalises_without_forcing_punctuation(self) -> None:
        out = cleanup_text("hello there", {"cleanup": {"level": "light"}})
        self.assertEqual(out, "Hello there")

    def test_an_unknown_level_does_not_raise(self) -> None:
        self.assertIsInstance(cleanup_text("some text", {"cleanup": {"level": "banana"}}), str)

    def test_backtrack_can_be_switched_off(self) -> None:
        config = {"cleanup": {"level": "none", "backtrack": False}}
        self.assertIn("scratch that", cleanup_text("keep this scratch that", config))


class DeterministicTransformTests(unittest.TestCase):
    def test_concise_drops_padding_phrases(self) -> None:
        self.assertEqual(make_concise("I wanted to basically say hello"), "say hello")

    def test_formal_swaps_casual_words_and_closes_the_sentence(self) -> None:
        self.assertEqual(make_formal("hey thanks for the stuff"), "Hello Thank you for the details.")

    def test_a_list_is_built_from_sentences_or_separators(self) -> None:
        self.assertEqual(turn_to_list("Buy eggs. Call Bob."), "- Buy eggs.\n- Call Bob.")
        self.assertEqual(turn_to_list("eggs, milk and bread"), "- Eggs\n- Milk\n- Bread")

    def test_an_empty_list_input_produces_nothing(self) -> None:
        self.assertEqual(turn_to_list(""), "")

    def test_empathize_prefixes_and_lowercases_the_join(self) -> None:
        self.assertEqual(empathize("This is broken"), "I hear you. this is broken.")
        self.assertEqual(empathize("this is broken"), "I hear you. this is broken.")

    def test_empathize_leaves_empty_input_alone(self) -> None:
        self.assertEqual(empathize(""), "")
        self.assertEqual(empathize("   "), "")


class CommandRoutingTests(unittest.TestCase):
    def test_spoken_commands_route_to_the_right_transform(self) -> None:
        cases = {
            "make it a prompt": "prompt_engineer",
            "bullet points": "turn_to_list",
            "turn that into a list": "turn_to_list",
            "be more formal": "formal",
            "make it professional": "formal",
            "keep it brief": "concise",
            "make it shorter": "concise",
            "be kind about it": "empathize",
        }
        for command, expected in cases.items():
            with self.subTest(command=command):
                self.assertEqual(command_to_transform(command), expected)

    def test_an_unrecognised_command_falls_back_to_polish(self) -> None:
        self.assertEqual(command_to_transform("do something clever"), "polish")
        self.assertEqual(command_to_transform(""), "polish")

    def test_routing_ignores_case(self) -> None:
        self.assertEqual(command_to_transform("BE MORE FORMAL"), "formal")


class DiffTests(unittest.TestCase):
    def test_a_change_is_reported_with_both_sides(self) -> None:
        diff = unified_diff("hello world", "hello there")
        self.assertIn("-hello world", diff)
        self.assertIn("+hello there", diff)

    def test_identical_text_produces_no_diff(self) -> None:
        self.assertEqual(unified_diff("same", "same"), "")


if __name__ == "__main__":
    unittest.main()
