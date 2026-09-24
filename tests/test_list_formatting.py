from __future__ import annotations

import unittest

from knight_flow.config import DEFAULT_CONFIG
from knight_flow.formatting import _lead_in_colon, _shape_list_structure
from knight_flow.text_pipeline import process_dictation


def spoken(text: str) -> str:
    """Run dictation through the rules path only.

    local_only is the path that produces the first paste -- what the person
    actually sees before the model's version replaces it about a second later.
    Testing the model's output is not possible offline and not the point: the
    rules are what has to be right on their own.
    """
    return process_dictation(text, DEFAULT_CONFIG, local_only=True).text


class TheLineBeforeAListEndsWithAColonTests(unittest.TestCase):
    """Reported from live use: "Okay, here's a bullet list." then four items,
    and the full stop stayed a full stop.

    A sentence that introduces a list ends with a colon. That is not a
    preference, it is the convention in every style guide, and getting it wrong
    is exactly the kind of small wrongness that makes dictated text read as
    dictated rather than as writing.

    It used to be applied only where one narrow regex matched -- built around
    phrases like "the fixes are" -- so it fired for almost nothing anybody
    actually says. The rule does not need to recognise the phrasing: any line
    immediately followed by a list item is that list's introduction, whatever
    words it used.
    """

    def test_a_full_stop_before_a_list_becomes_a_colon(self) -> None:
        out = _shape_list_structure("Here are the fixes.\n1. One\n2. Two")
        self.assertTrue(out.startswith("Here are the fixes:"), out)

    def test_it_works_for_wording_no_regex_would_have_predicted(self) -> None:
        """The original failure. Nothing about this phrasing is special."""
        for lead in ("Okay, here's a bullet list.",
                     "So anyway these are the ones I care about.",
                     "Right, the stuff I bought today.",
                     "My three favourite things in the world."):
            with self.subTest(lead=lead):
                out = _shape_list_structure(f"{lead}\n- Apples\n- Trees")
                self.assertTrue(out.splitlines()[0].endswith(":"), out)

    def test_a_lead_in_with_no_punctuation_at_all_gains_a_colon(self) -> None:
        out = _shape_list_structure("The fixes are these\n- one\n- two")
        self.assertEqual(out.splitlines()[0], "The fixes are these:")

    def test_a_question_keeps_its_question_mark(self) -> None:
        """"Ready?" followed by steps is still a question. Replacing that mark
        changes what the sentence is doing."""
        out = _shape_list_structure("Are you ready?\n1. Go\n2. Stop")
        self.assertEqual(out.splitlines()[0], "Are you ready?")

    def test_an_exclamation_keeps_its_point(self) -> None:
        out = _shape_list_structure("Listen up!\n- One\n- Two")
        self.assertEqual(out.splitlines()[0], "Listen up!")

    def test_an_existing_colon_is_left_alone(self) -> None:
        out = _shape_list_structure("Steps:\n1. One\n2. Two")
        self.assertEqual(out.splitlines()[0], "Steps:")

    def test_only_the_line_touching_the_list_is_changed(self) -> None:
        """A paragraph before the introduction keeps its own full stop."""
        out = _shape_list_structure("I went to the shop.\nHere is what I bought.\n- Milk\n- Eggs")
        self.assertEqual(out.splitlines()[0], "I went to the shop.")
        self.assertEqual(out.splitlines()[1], "Here is what I bought:")

    def test_prose_with_no_list_is_untouched(self) -> None:
        text = "Just a sentence.\nAnother sentence."
        self.assertEqual(_shape_list_structure(text), text)

    def test_one_item_between_two_lists_is_not_treated_as_a_lead_in(self) -> None:
        out = _shape_list_structure("Things:\n- A\n- B")
        self.assertEqual(out, "Things:\n- A\n- B")

    def test_the_helper_handles_every_terminal_it_is_given(self) -> None:
        self.assertEqual(_lead_in_colon("Here it is."), "Here it is:")
        self.assertEqual(_lead_in_colon("Here it is,"), "Here it is:")
        self.assertEqual(_lead_in_colon("Here it is;"), "Here it is:")
        self.assertEqual(_lead_in_colon("Here it is"), "Here it is:")
        self.assertEqual(_lead_in_colon("Here it is:"), "Here it is:")
        self.assertEqual(_lead_in_colon(""), "")


class TheMarkerIsTheOneThatWasAskedForTests(unittest.TestCase):
    """Saying "here's a bullet list" and receiving "1. 2. 3." is ignoring an
    instruction given in as many words."""

    def test_asking_for_bullets_gets_bullets(self) -> None:
        out = _shape_list_structure("Here's a bullet list.\n1. Apples\n2. Trees")
        self.assertIn("- Apples", out)
        self.assertNotIn("1. Apples", out)

    def test_asking_for_numbers_gets_numbers(self) -> None:
        out = _shape_list_structure("Here's a numbered list.\n- Alpha\n- Beta")
        self.assertIn("1. Alpha", out)
        self.assertIn("2. Beta", out)

    def test_a_list_nobody_described_keeps_the_marker_it_has(self) -> None:
        """No instruction means no reason to change anything."""
        out = _shape_list_structure("Here is what happened.\n1. First\n2. Second")
        self.assertIn("1. First", out)

    def test_renumbering_starts_at_one_and_counts_up(self) -> None:
        out = _shape_list_structure("Numbered list.\n- A\n- B\n- C")
        self.assertEqual(out.splitlines()[1:], ["1. A", "2. B", "3. C"])


class AListSpokenAloudIsBuiltTests(unittest.TestCase):
    """The strongest signal there is -- the person said "make this a list" --
    and the rules ignored it completely, returning two sentences of prose."""

    def test_his_reported_case_end_to_end(self) -> None:
        out = spoken("Okay, here's a bullet list. Apples, trees, bicycles, guns.")
        lines = out.splitlines()
        self.assertTrue(lines[0].endswith(":"), out)
        self.assertEqual(lines[1:], ["- Apples", "- Trees", "- Bicycles", "- Guns"])

    def test_a_numbered_list_asked_for_out_loud(self) -> None:
        out = spoken("Give me a numbered list. Wake up, brush teeth, leave the house.")
        self.assertEqual(out.splitlines()[1:], ["1. Wake up", "2. Brush teeth", "3. Leave the house"])

    def test_bullet_points_is_the_same_instruction(self) -> None:
        out = spoken("Bullet points: fast, cheap, reliable.")
        self.assertEqual(out.splitlines()[1:], ["- Fast", "- Cheap", "- Reliable"])

    def test_a_bare_list_command_defaults_to_bullets(self) -> None:
        """An unordered set is what a list is, unless order was asked for."""
        out = spoken("Here's a list. Red, green, blue.")
        self.assertIn("- Red", out)


class ProseThatMentionsAListStaysProseTests(unittest.TestCase):
    """The failure that matters. A missed list is a small disappointment; a
    paragraph chopped into bullets is what makes somebody stop trusting the
    formatter and turn it off."""

    def test_an_enumeration_inside_a_sentence_is_not_a_list(self) -> None:
        text = "I need to buy milk, eggs and bread on the way home."
        self.assertEqual(spoken(text), text)

    def test_the_word_list_in_passing_authorises_nothing(self) -> None:
        text = "We talked about the list of things that went wrong yesterday."
        self.assertEqual(spoken(text), text)

    def test_a_long_thought_after_a_list_command_is_not_chopped_up(self) -> None:
        """Items of twelve words are sentences, and a run of them is a
        paragraph. Refusing is the right answer when it is not obvious."""
        out = spoken(
            "Here is a list. I think we should probably reconsider the entire "
            "approach because it is not working."
        )
        self.assertNotIn("- I think", out)

    def test_a_single_item_is_not_a_list(self) -> None:
        out = spoken("Here's a bullet list. Apples.")
        self.assertNotIn("- Apples", out)


if __name__ == "__main__":
    unittest.main()
