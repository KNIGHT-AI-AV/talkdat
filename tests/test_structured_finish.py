from __future__ import annotations

import unittest
from unittest import mock
from unittest.mock import patch

from knight_flow.formatting import (
    EXECUTIVE_ADDENDUM,
    FORMAT_SYSTEM_PROMPT,
    _high_confidence_fast_format,
    _valid_formatter_output,
    heuristic_format,
)
from knight_flow.text_pipeline import (
    apply_smart_newlines,
    pre_clean_for_format,
    process_dictation,
    resolve_spoken_retractions,
)


# X-465: this module is about the world where local-only is OFF.
#
# Talk DAT! is local-only by default now: the speech route, the formatter and
# the door that lets text leave all read one switch, and a config that has
# never heard of that switch is treated as local-only, which is the right
# answer for a real install upgrading from an older version. The fixtures
# below are bare dicts asking for the managed or bring-your-own-key route, so
# without this they would resolve to local and test nothing they mean to.
#
# That route still exists for anybody who deliberately turns the switch off,
# and it still has to work. Naming the world here is the point: these
# assertions are about the cloud contract, not about whichever default happens
# to be in force.
_LOCAL_ONLY_OFF = mock.patch("knight_flow.stt_registry.local_only", return_value=False)


def setUpModule() -> None:
    _LOCAL_ONLY_OFF.start()


def tearDownModule() -> None:
    _LOCAL_ONLY_OFF.stop()


SPOKEN = (
    "okay today's list number one gym at seven thirty number two send Mayowa the "
    "production report no actually the revised report with the Q3 final numbers in "
    "parentheses before ten thirty number three production review at eleven bring "
    "version two point four and the twelve thousand four hundred fifty dollar budget "
    "number four photo shoot at three fifteen studio B wardrobe black and gold six "
    "product shots new paragraph if it rains move the outdoor setup inside and text "
    "the crew by two"
)

FINISHED = (
    "Today's list:\n"
    "1. Gym: 7:30 a.m.\n"
    "2. Send Mayowa the revised report with the Q3 final numbers (before 10:30 a.m.).\n"
    "3. Production review: 11:00 a.m. Bring version 2.4 and the $12,450 budget.\n"
    "4. Photo shoot: 3:15 p.m. Studio B; wardrobe: black and gold; six product shots.\n\n"
    "If it rains, move the outdoor setup inside and text the crew by 2:00 p.m."
)


class SpokenCorrectionTests(unittest.TestCase):
    def test_no_actually_replaces_a_phrase_with_the_same_head(self) -> None:
        self.assertEqual(
            resolve_spoken_retractions(
                "send Mayowa the production report no actually the revised report with Q3"
            ),
            "send Mayowa the revised report with Q3",
        )

    def test_ambiguous_no_actually_is_left_for_the_model(self) -> None:
        text = "the production report no actually call Mayowa tomorrow"
        self.assertEqual(resolve_spoken_retractions(text), text)


class DecimalAndListMarkerTests(unittest.TestCase):
    def test_a_version_decimal_does_not_become_an_extra_list_item(self) -> None:
        prepared = apply_smart_newlines(
            "number one open the review number two bring version two point four "
            "number three confirm the budget"
        )
        self.assertIn("version two point four", prepared)
        self.assertEqual(prepared.count("\n1. "), 1)
        self.assertEqual(prepared.count("\n2. "), 1)
        self.assertEqual(prepared.count("\n3. "), 1)
        self.assertNotIn("\n4. ", prepared)

    def test_point_one_point_two_remains_a_supported_list_command(self) -> None:
        output = heuristic_format(
            "point one call the studio point two send the report point three confirm the budget"
        )
        self.assertEqual(
            output,
            "1. Call the studio.\n2. Send the report.\n3. Confirm the budget.",
        )

    def test_decimal_prose_stays_prose(self) -> None:
        output = heuristic_format(
            "the release is version two point four and revenue is one point two million"
        )
        self.assertNotIn("\n", output)
        self.assertIn("version two point four", output.lower())


class AgendaIntelligenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cleaned = pre_clean_for_format(
            SPOKEN,
            {"cleanup": {"resolve_retractions": True}},
        )

    def test_contextual_numbers_do_not_take_the_chill_fast_path(self) -> None:
        self.assertIsNone(_high_confidence_fast_format(self.cleaned))

    def test_both_safety_modes_accept_the_same_fact_safe_written_agenda(self) -> None:
        self.assertTrue(
            _valid_formatter_output(
                self.cleaned,
                FINISHED,
                preserve_meaning=True,
                rewrite_mode=False,
            )
        )
        self.assertTrue(
            _valid_formatter_output(
                self.cleaned,
                FINISHED,
                preserve_meaning=False,
                rewrite_mode=True,
            )
        )

    def test_executive_refuses_a_result_that_drops_the_budget(self) -> None:
        unsafe = FINISHED.replace(" and the $12,450 budget", "")
        self.assertFalse(
            _valid_formatter_output(
                self.cleaned,
                unsafe,
                preserve_meaning=False,
                rewrite_mode=True,
            )
        )

    def test_chill_and_executive_both_run_the_intelligent_pass(self) -> None:
        for intensity, minimum_timeout in (("standard", 1.2), ("executive", 1.2)):
            config = {
                "cleanup": {
                    "smart_format": True,
                    "level": "high",
                    "format_mode": "ai",
                    "format_intensity": intensity,
                },
                "transforms": {"llm": {"provider": "openai"}},
            }
            with self.subTest(intensity=intensity), patch(
                "knight_flow.formatting.llm_complete",
                return_value=FINISHED,
            ) as complete:
                output = process_dictation(SPOKEN, config).text

                self.assertEqual(complete.call_count, 1)
                self.assertGreaterEqual(complete.call_args.kwargs["timeout_override"], minimum_timeout)
                self.assertIn("1. Gym: 7:30 AM", output)
                self.assertNotIn("A.M.", output)
                self.assertNotIn("P.M.", output)
                self.assertIn("version 2.4", output)
                self.assertIn("$12,450", output)
                self.assertNotIn("production report no actually", output.lower())
                self.assertIn("\n\nIf it rains", output)

    def test_the_desktop_prompt_carries_the_full_agenda_contract(self) -> None:
        for rule in (
            "AGENDA, SCHEDULE, RUN-OF-SHOW AND TO-DO SPEECH",
            "version two point four",
            "spoken new paragraph after the final item ends the list",
        ):
            self.assertIn(rule.lower(), FORMAT_SYSTEM_PROMPT.lower())
        self.assertIn("stays that document type", EXECUTIVE_ADDENDUM)


if __name__ == "__main__":
    unittest.main()
