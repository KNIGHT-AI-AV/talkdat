"""Tier 0: these are deliberately RED before the corresponding product fixes."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from tests.parity_battery import Case, cases, local_config, run, score, summarize, violations


class ParityHarnessTests(unittest.TestCase):
    def test_zero_cases_cannot_be_a_passing_gate(self):
        self.assertEqual(violations([]), ["empty corpus"])

    def test_the_corpus_is_at_least_two_hundred_cases(self):
        self.assertGreaterEqual(len(cases()), 200)
        extended = [c for c in cases() if c.cohort == "wispr-parity-2026-09-22"]
        self.assertGreaterEqual(len(extended), 150)
        # The probe gaps from the owner's report each have a gated rules row.
        gated = {c.label for c in extended if c.gate}
        for label in ("backtrack make it", "backtrack no wait day", "count list groceries",
                      "quarter", "phone seven", "file name json", "new paragraph", "email team"):
            self.assertIn(label, gated)

    def test_the_data_loss_corpus_covers_every_defect_class(self):
        """2026-09-23: nine classes, each with positive rows and counterexamples."""
        rows = [c for c in cases() if c.cohort == "commandments-2026-09-23"]
        self.assertGreaterEqual(len(rows), 100)
        prefixes = {c.label.split(" ", 1)[0] for c in rows}
        for prefix in ("cmd", "enter", "literal", "dash", "repeat", "filler", "range", "version", "time",
                       "path", "lang", "profanity", "signoff", "inject"):
            self.assertIn(prefix, prefixes)
        self.assertTrue(any(c.enter is True for c in rows) and any(c.enter is False for c in rows))
        self.assertEqual({c.preset for c in rows} - {""}, {"verbatim", "censor"})

    def test_an_enter_that_fires_on_prose_is_a_violation(self):
        case = Case("enter", "to submit the form just press enter", "To submit the form just press enter.",
                    enter=False)
        row = score(case, "To submit the form just.", 1, sent_enter=True)
        self.assertTrue(row["enter_wrong"])
        self.assertEqual(violations([row]), ["enter"])
        self.assertEqual(summarize([row])["enter_mismatches"], 1)
        self.assertFalse(score(case, case.expected, 1, sent_enter=False)["enter_wrong"])

    def test_presets_change_only_what_they_name(self):
        from tests.parity_battery import preset_config

        verbatim = preset_config(local_config(), "verbatim")
        self.assertEqual(verbatim["cleanup"]["level"], "none")
        self.assertTrue(preset_config(local_config(), "censor")["cleanup"]["censor_profanity"])
        with self.assertRaises(ValueError):
            preset_config(local_config(), "bogus")

    def test_an_ungated_target_is_scored_but_does_not_fail_the_rules_gate(self):
        case = Case("model owns it", "x", "Target.", gate=False)
        row = score(case, "Something else.", 1)
        self.assertFalse(row["match"])
        self.assertEqual(violations([row]), [])
        gated = score(Case("rules owns it", "x", "Target."), "Something else.", 1)
        self.assertEqual(violations([gated]), ["rules owns it"])

    def test_a_retracted_value_is_unresolved_not_a_meaning_change(self):
        case = Case("fix", "x", "At 6.", gate=False, retracted=(r"\b5\b",))
        row = score(case, "At 5 actually 6.", 1)
        self.assertTrue(row["unresolved"])
        self.assertFalse(row["meaning_change"])
        self.assertEqual(summarize([row])["unresolved_corrections"], 1)

    def test_acceptable_ignores_commas_and_a_final_stop_only(self):
        case = Case("loose", "x", "We can take the train, the bus or a taxi.")
        self.assertTrue(score(case, "We can take the train, the bus, or a taxi.", 1)["acceptable"])
        self.assertFalse(score(case, "we can take the train the bus or a taxi", 1)["acceptable"])

    def test_the_original_audit_targets_are_not_diluted(self):
        audit = [c for c in cases() if c.cohort == "audit-2026-09-18"]
        self.assertEqual(len(audit), 44)
        self.assertEqual(sum(c.expected is not None for c in audit), 42)
        self.assertEqual(len({c.label for c in cases()}), len(cases()))

    def test_data_loss_guard_fires_on_a_missing_digit(self):
        phone = next(c for c in cases() if c.label == "phone")
        good = score(phone, "Call me at 415-555-1212.", 1)
        bad = score(phone, "Call me at 415-55-1212.", 1)
        self.assertFalse(good["data_loss"])
        self.assertTrue(bad["data_loss"])
        self.assertEqual(summarize([bad])["data_loss_count"], 1)

    def test_meaning_guard_fires_on_the_phonetic_neighbour(self):
        year = next(c for c in cases() if c.label == "year")
        self.assertFalse(score(year, "We launched in 2026.", 1)["meaning_change"])
        self.assertTrue(score(year, "We LinkedIn 2026.", 1)["meaning_change"])

    def test_expected_none_still_checks_meaning(self):
        case = Case("statement", "keep this", None, meaning=(r"keep this",))
        row = score(case, "delete this", 1)
        self.assertIsNone(row["match"])
        self.assertEqual(violations([row]), ["statement"])

    def test_errors_cannot_be_counted_as_success(self):
        def broken(_text, _config):
            raise RuntimeError("synthetic")
        row = run(corpus=(Case("raises", "x", None),), formatter=broken)[0]
        self.assertEqual(row["error"], "RuntimeError")
        self.assertEqual(violations([row]), ["raises"])

    def test_fixture_config_does_not_load_or_write_user_state(self):
        cfg = local_config()
        self.assertFalse(cfg["diagnostics"]["formatting_journal"])
        self.assertFalse(cfg["dictionary"]["screen_context"])
        self.assertFalse(cfg["plugins"]["enabled"])
        self.assertFalse(cfg["transforms"]["llm"]["auto_install"])
        self.assertEqual(cfg["transforms"]["llm"]["provider"], "none")

    def test_rules_lane_cannot_call_a_model(self):
        with patch("knight_flow.formatting.local_finish", side_effect=AssertionError("model call")) as local, \
             patch("knight_flow.formatting.llm_complete", side_effect=AssertionError("provider call")) as remote:
            run(corpus=(Case("simple", "hello world", None),))
        local.assert_not_called()
        remote.assert_not_called()

    def test_statistics_count_cases_not_number_of_broken_invariants(self):
        case = Case("two facts", "x", "correct", facts=("one", "two"))
        report = summarize([score(case, "missing", 4), score(case, "correct one two", 8)])
        self.assertEqual(report["data_loss_count"], 1)
        self.assertEqual(report["median_ms"], 6)
        self.assertEqual(report["p90_ms"], 8)


class RulesParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = run()

    def test_the_expected_column_through_the_real_pipeline(self):
        # Every gated target: the whole original audit and reference, plus the
        # 2026-09-22 rows the rules lane is built to reach deterministically.
        for row in self.rows:
            if row["expected"] is not None and row["gated"]:
                with self.subTest(case=row["label"]):
                    self.assertEqual(row["produced"], row["expected"])

    def test_gated_corrections_are_applied(self):
        self.assertEqual([r["label"] for r in self.rows if r["gated"] and r["unresolved"]], [])

    def test_no_annotated_data_loss(self):
        self.assertEqual([r["label"] for r in self.rows if r["data_loss"]], [])

    def test_no_annotated_meaning_change(self):
        self.assertEqual([r["label"] for r in self.rows if r["meaning_change"]], [])

    def test_no_pipeline_error(self):
        self.assertEqual([r["label"] for r in self.rows if r["error"]], [])


if __name__ == "__main__":
    unittest.main()
