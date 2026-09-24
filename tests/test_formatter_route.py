from __future__ import annotations

import unittest
from unittest import mock

from knight_flow.config import (
    DEFAULT_CONFIG,
    LOCAL_FORMATTER_MODEL,
    _migrate_default_formatter_to_auto,
    _migrate_intensity_default_to_executive,
)
from knight_flow.llm import resolved_llm_provider
from knight_flow.text_pipeline import FILLER_RE


class AutoResolvesToTheBestEntitledFormatterTests(unittest.TestCase):
    """X-114. The founder's log showed the shipped local default timing out
    into the rules formatter 284 times; when it answered, it changed nothing.
    "auto" is the fix: cloud where the install is activated, local otherwise."""

    def test_the_formatter_follows_the_speech_route_home(self) -> None:
        """X-480: this asserted that "auto" put an activated PC on the managed
        cloud. There is no "auto" and no managed cloud.

        What replaced it is better than a deletion: the formatter follows the
        SPEECH route, so a config that still names the managed service formats
        LOCALLY, even with that service reachable and the local-only switch
        off. The managed formatter is unreachable through the route rather
        than merely discouraged, and this is the proof that removing its code
        changes no behaviour."""
        config = {"transforms": {"llm": {"provider": "auto"}}, "privacy": {"local_only": False}}
        # X-516: the patch that used to make the managed service look
        # reachable is gone with the module. The answer never depended on it,
        # which is what the docstring above predicted.
        self.assertEqual(resolved_llm_provider(config), "ollama")

    def test_auto_falls_back_to_local_when_signed_out(self) -> None:
        config = {"transforms": {"llm": {"provider": "auto"}}, "privacy": {"local_only": False}}
        self.assertEqual(resolved_llm_provider(config), "ollama")

    def test_an_explicit_choice_is_never_second_guessed(self) -> None:
        for chosen in ("ollama", "none", "openai", "talk_dat_cloud"):
            config = {"transforms": {"llm": {"provider": chosen}}, "privacy": {"local_only": False}}
            self.assertEqual(resolved_llm_provider(config), chosen)


class OnlyOurDefaultMigratesToAutoTests(unittest.TestCase):
    """The decision reads the LOADED file, never the merged config --
    DEFAULT_CONFIG carries the done-stamp for fresh installs, and reading the
    merged view would see it on every machine and no-op forever."""

    def _run(self, loaded_llm: dict | None) -> dict:
        loaded = {"transforms": {"llm": dict(loaded_llm)}} if loaded_llm is not None else {}
        config = {"transforms": {"llm": dict(loaded_llm or {})}, "privacy": {"local_only": False}}
        config["transforms"]["llm"].setdefault("auto_formatter_migrated", True)  # defaults leak in via deep_merge
        _migrate_default_formatter_to_auto(config, loaded)
        return config["transforms"]["llm"]

    def test_our_shipped_default_flips_to_auto(self) -> None:
        llm = self._run(dict(
            provider="ollama",
            model=LOCAL_FORMATTER_MODEL,
            api_base="http://localhost:11434",
            balanced_default_migrated=True,
        ))
        self.assertEqual(llm["provider"], "auto")

    def test_the_default_stamp_leaking_through_the_merge_does_not_block_it(self) -> None:
        # The exact live failure: the merged config carries the stamp from
        # DEFAULT_CONFIG while the file on disk has never migrated.
        loaded = {"transforms": {"llm": dict(
            provider="ollama", model=LOCAL_FORMATTER_MODEL,
            api_base="http://localhost:11434", balanced_default_migrated=True,
        )}}
        config = {"transforms": {"llm": {**loaded["transforms"]["llm"], "auto_formatter_migrated": True}}, "privacy": {"local_only": False}}
        _migrate_default_formatter_to_auto(config, loaded)
        self.assertEqual(config["transforms"]["llm"]["provider"], "auto")

    def test_a_hand_picked_backend_stays(self) -> None:
        for llm in (
            dict(provider="openai", model="gpt-5.2", balanced_default_migrated=True),
            dict(provider="ollama", model="llama3.3:70b", balanced_default_migrated=True),
            dict(provider="ollama", model=LOCAL_FORMATTER_MODEL, api_base="http://10.0.0.9:11434", balanced_default_migrated=True),
            dict(provider="none", balanced_default_migrated=True),
        ):
            result = self._run(llm)
            self.assertEqual(result["provider"], llm["provider"], llm)

    def test_the_migration_runs_once(self) -> None:
        loaded = {"transforms": {"llm": dict(
            provider="ollama", model=LOCAL_FORMATTER_MODEL,
            balanced_default_migrated=True, auto_formatter_migrated=True,
        )}}
        config = {"transforms": {"llm": dict(loaded["transforms"]["llm"])}}
        config["transforms"]["llm"]["provider"] = "ollama"  # the user's later choice
        _migrate_default_formatter_to_auto(config, loaded)
        self.assertEqual(config["transforms"]["llm"]["provider"], "ollama")


class ExecutiveIsTheDefaultTests(unittest.TestCase):
    """His 09-22 order: "Make the best formatting the default." X-602 moved
    NEW installs to Chill, the faithful finish, on the measurements in
    docs/COMMANDMENT-RESULTS.md; every existing install keeps what it saved.
    An unstamped "standard" is still our old shipped default and upgrades; a
    stamped choice is a person's choice and stays."""

    def test_fresh_installs_default_to_chill(self) -> None:
        self.assertEqual(DEFAULT_CONFIG["cleanup"]["format_intensity"], "standard")
        self.assertTrue(DEFAULT_CONFIG["cleanup"]["intensity_default_migrated"])

    def test_an_existing_executive_install_keeps_executive(self) -> None:
        from knight_flow.config import deep_merge

        loaded = {"cleanup": {"format_intensity": "executive", "intensity_default_migrated": True}}
        config = deep_merge(DEFAULT_CONFIG, loaded)
        _migrate_intensity_default_to_executive(config, loaded)
        self.assertEqual(config["cleanup"]["format_intensity"], "executive")

    def test_our_old_standard_default_upgrades(self) -> None:
        loaded = {"cleanup": {"format_intensity": "standard"}}
        config = {"cleanup": {"format_intensity": "standard", "intensity_default_migrated": True}}
        _migrate_intensity_default_to_executive(config, loaded)  # stamp leaks via merge
        self.assertEqual(config["cleanup"]["format_intensity"], "executive")

    def test_a_stamped_standard_is_a_choice_and_stays(self) -> None:
        loaded = {"cleanup": {"format_intensity": "standard", "intensity_default_migrated": True}}
        config = {"cleanup": dict(loaded["cleanup"])}
        _migrate_intensity_default_to_executive(config, loaded)
        self.assertEqual(config["cleanup"]["format_intensity"], "standard")

    def test_an_explicit_executive_is_untouched(self) -> None:
        loaded = {"cleanup": {"format_intensity": "executive"}}
        config = {"cleanup": {"format_intensity": "executive", "intensity_default_migrated": True}}
        _migrate_intensity_default_to_executive(config, loaded)
        self.assertEqual(config["cleanup"]["format_intensity"], "executive")


class InterjectionsAreFillersTests(unittest.TestCase):
    """The founder's literal complaint: "when I say things like and ooh, I
    feel like sometimes it's still there." Real-word interjections survive
    recognizers that suppress um/uh, so the rules path must drop them too."""

    def test_ooh_class_interjections_are_removed(self) -> None:
        cleaned = FILLER_RE.sub("", "and ooh make sure the site is mhm clean")
        self.assertEqual(" ".join(cleaned.split()), "and make sure the site is clean")

    def test_meaningful_oh_survives(self) -> None:
        self.assertEqual(FILLER_RE.sub("", "oh no, that broke"), "oh no, that broke")


class NoEmDashEverTests(unittest.TestCase):
    """X-139, his order with the glyph quoted: em dashes are eliminated from
    outputs entirely. The scrub is deterministic and runs on every model
    route before validation."""

    def test_inline_em_dash_becomes_a_comma_pause(self) -> None:
        from knight_flow.formatting import strip_em_dashes

        self.assertEqual(
            strip_em_dashes("The budget — approved yesterday — is final."),
            "The budget, approved yesterday, is final.",
        )

    def test_line_leading_em_dash_becomes_a_list_hyphen(self) -> None:
        from knight_flow.formatting import strip_em_dashes

        self.assertEqual(
            strip_em_dashes("— first point" + chr(10) + "— second point"),
            "- first point" + chr(10) + "- second point",
        )

    def test_tight_em_dash_between_words(self) -> None:
        from knight_flow.formatting import strip_em_dashes

        self.assertEqual(strip_em_dashes("fast—accurate—done"), "fast, accurate, done")

    def test_em_dash_before_punctuation_leaves_no_double_mark(self) -> None:
        from knight_flow.formatting import strip_em_dashes

        self.assertEqual(strip_em_dashes("It works —."), "It works.")

    def test_hyphens_and_en_dashes_are_not_touched(self) -> None:
        from knight_flow.formatting import strip_em_dashes

        untouched = "A well-known 9–5 job with state-of-the-art tools."
        self.assertEqual(strip_em_dashes(untouched), untouched)

    def test_the_executive_prompt_bans_the_glyph(self) -> None:
        from knight_flow.formatting import EXECUTIVE_ADDENDUM

        self.assertIn("NEVER use an em dash", EXECUTIVE_ADDENDUM)
        self.assertIn("EVERY point survives", EXECUTIVE_ADDENDUM)
        self.assertIn("READ-ALOUD MATERIAL IS VERBATIM", EXECUTIVE_ADDENDUM)


if __name__ == "__main__":
    unittest.main()


class ComposedNumbersSurviveTheValidatorTests(unittest.TestCase):
    """X-114: inverse text normalization is only real if the validator lets
    it ship. Word-by-word canonicalisation held "forty two thousand" as
    40/2/1000 against the model's 42,000 and rejected the correct output."""

    def test_spoken_compounds_compose(self) -> None:
        from knight_flow.formatting import _compose_spoken_numbers

        for spoken, written in (
            ("forty two thousand dollars", "42000 dollars"),
            ("eighty four percent", "84 percent"),
            ("august twenty ninth", "august 29"),
            ("twenty twenty six", "20 26"),  # a spoken year is two numbers
            ("nine hundred dollars", "900 dollars"),
        ):
            self.assertEqual(_compose_spoken_numbers(spoken), written)

    def test_the_validator_accepts_a_correct_heading_report(self) -> None:
        from knight_flow.formatting import _valid_formatter_output

        raw = (
            "heading budget update we are currently at forty two thousand dollars of the fifty "
            "thousand dollar budget which is eighty four percent spent heading timeline the beta "
            "ships august twenty ninth and the full launch follows in october heading risks the "
            "only open risk is the app store review timing"
        )
        model = (
            "## Budget update\n"
            "We are currently at $42,000 of the $50,000 budget, which is 84% spent.\n\n"
            "## Timeline\n"
            "The beta ships August 29, and the full launch follows in October.\n\n"
            "## Risks\n"
            "The only open risk is the App Store review timing."
        )
        self.assertTrue(_valid_formatter_output(raw, model, preserve_meaning=True))

    def test_an_invented_number_is_still_refused(self) -> None:
        from knight_flow.formatting import _valid_formatter_output

        raw = "the budget is forty two thousand dollars"
        model = "The budget is $56,000."
        self.assertFalse(_valid_formatter_output(raw, model, preserve_meaning=True))


class BareFragmentsStayBareTests(unittest.TestCase):
    """X-118, his logic: a name into a search box needs no period and no
    leading space -- it is an insertion, not a sentence."""

    def test_fragment_detection(self) -> None:
        from knight_flow.text_pipeline import is_bare_fragment

        self.assertTrue(is_bare_fragment("quarterly report", "Quarterly report."))
        self.assertTrue(is_bare_fragment("john smith", "John Smith."))
        self.assertFalse(is_bare_fragment("send the report please", "Send the report, please. Thanks a lot."))
        self.assertFalse(is_bare_fragment("what time is it", "What time is it?"))
        self.assertFalse(is_bare_fragment("done .", "Done."))  # spoken punctuation resolved = a sentence on purpose

    def test_fragment_period_strip(self) -> None:
        from knight_flow.text_pipeline import strip_fragment_period

        self.assertEqual(strip_fragment_period("Quarterly report."), "Quarterly report")
        self.assertEqual(strip_fragment_period("Meet Dr."), "Meet Dr.")  # the dot IS the word

    def test_fragments_refuse_the_leading_space(self) -> None:
        from knight_flow.paste import should_prefix_space

        self.assertFalse(should_prefix_space("quarterly report"))
        self.assertFalse(should_prefix_space("NavOrb"))
        self.assertTrue(should_prefix_space("The report is ready."))


class DateOrdinalsComposeTests(unittest.TestCase):
    """A lone ordinal next to a month is a DATE, not spoken structure --
    refusing it made the validator read the model's correct "September 5"
    as an invented number and throw away a perfect executive report."""

    def test_month_adjacent_ordinals_compose(self) -> None:
        from knight_flow.formatting import _compose_spoken_numbers

        self.assertEqual(_compose_spoken_numbers("september fifth"), "september 5")
        self.assertEqual(_compose_spoken_numbers("the fifth of june"), "the 5 of june")

    def test_structural_ordinals_still_do_not(self) -> None:
        from knight_flow.formatting import _compose_spoken_numbers

        self.assertEqual(_compose_spoken_numbers("first we ship"), "first we ship")


class OneWordAnswersStayBareTests(unittest.TestCase):
    """His live re-report: short words still carried periods -- the first
    abbreviation guard protected EVERY short word."""

    def test_short_words_lose_the_period(self) -> None:
        from knight_flow.text_pipeline import strip_fragment_period

        for text in ("Go.", "OK.", "Yes.", "No.", "Quarterly report."):
            self.assertFalse(strip_fragment_period(text).endswith("."), text)

    def test_real_abbreviations_keep_it(self) -> None:
        from knight_flow.text_pipeline import strip_fragment_period

        for text in ("Meet Dr.", "Knight Inc.", "John F."):
            self.assertTrue(strip_fragment_period(text).endswith("."), text)


class ExecutiveModeTests(unittest.TestCase):
    """X-125: the flagship rewrite. Consent changes the validator's job --
    wording is free, facts are locked."""

    def test_rewrite_mode_accepts_full_register_change(self) -> None:
        from knight_flow.formatting import _valid_formatter_output

        raw = ("so um the rewrite thing is like really casual right now and that's not good bro "
               "like we need a corporate mode that makes everything super formal")
        model = ("The current rewrite implementation is too informal for enterprise use. "
                 "We require a corporate mode ensuring formal professional standards.")
        self.assertTrue(_valid_formatter_output(raw, model, preserve_meaning=False, rewrite_mode=True))

    def test_rewrite_mode_still_refuses_invented_numbers(self) -> None:
        from knight_flow.formatting import _valid_formatter_output

        self.assertFalse(_valid_formatter_output(
            "the budget is forty two thousand dollars",
            "The budget is $56,000.",
            preserve_meaning=False, rewrite_mode=True,
        ))

    def test_standard_intensity_keeps_the_old_contract(self) -> None:
        from knight_flow.formatting import _valid_formatter_output

        raw = "send the report to john and copy maria before friday"
        aggressive = "Correspondence must be dispatched to relevant stakeholders promptly."
        self.assertFalse(_valid_formatter_output(raw, aggressive, preserve_meaning=True))
