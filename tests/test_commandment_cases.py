"""The dictation commandments as a permanent regression suite (X-602).

tests/commandment_cases.json is the companion of docs/DICTATION-COMMANDMENTS.md:
229 cases, a positive and a counterexample per commandment plus 29 mixed
ones. The rules lane is deterministic, so every case it can receive runs here,
with no model and no network, against tests/commandment_baseline.json:

- every case the baseline lists as passing must still pass (a ratchet);
- the count may only go up: a case that newly passes must be added to the
  baseline (python -m tests.commandment_battery --write-baseline), so it can
  never quietly regress again;
- every runnable case the rules lane does not pass carries a written reason
  (the model's judgment, rewrite mode, a conflicting older gold target, or a
  rule not built yet), so nothing is silently dropped;
- a case that needs audio, the native paste layer or a field type the
  formatter is not told is skipped with that reason, never ignored.

The 4B Chill and Executive lanes are measured by the same module:
python -m tests.commandment_battery --model qwen3:4b-instruct-2507-q4_K_M
--intensity chill|executive. Results: docs/COMMANDMENT-RESULTS.md.
"""
from __future__ import annotations

import unittest
from collections import Counter

from tests import commandment_battery as battery


class TheCaseFileTests(unittest.TestCase):
    """The spec's companion file, as the spec describes it (section 6.1)."""

    @classmethod
    def setUpClass(cls):
        cls.cases = battery.load_cases()

    def test_two_hundred_twenty_nine_unique_cases(self):
        self.assertEqual(len(self.cases), 229)
        self.assertEqual(len({case["id"] for case in self.cases}), 229)

    def test_every_commandment_has_a_positive_and_a_boundary(self):
        kinds = Counter((case["commandment"], case["kind"]) for case in self.cases
                        if not case["id"].startswith("MIX"))
        for number in range(1, 101):
            with self.subTest(commandment=number):
                self.assertEqual(kinds[(number, "positive")], 1)
                self.assertEqual(kinds[(number, "boundary")], 1)
        mixed = sorted(case["id"] for case in self.cases if case["id"].startswith("MIX"))
        self.assertEqual(mixed, [f"MIX{n:02d}" for n in range(1, 30)])

    def test_layers_and_modes_match_the_spec(self):
        counts = Counter((case["layer"], case["mode"]) for case in self.cases)
        self.assertEqual(counts, Counter({("formatter", "faithful"): 177, ("insertion", "faithful"): 28,
                                          ("end_to_end", "faithful"): 12, ("formatter", "rewrite"): 8,
                                          ("formatter", "verbatim"): 4}))

    def test_every_case_is_planned_and_every_skip_says_why(self):
        for case in self.cases:
            kind, note = battery.plan(case)
            with self.subTest(case=case["id"]):
                self.assertIn(kind, {"format", "caret", "simulated_model", "model_unavailable", "skip"})
                if kind == "skip":
                    self.assertTrue(note.strip())
                if case["layer"] == "end_to_end":
                    self.assertEqual((kind, note), ("skip", battery.SKIP_AUDIO))

    def test_categories_and_priorities_cover_every_case(self):
        for case in self.cases:
            with self.subTest(case=case["id"]):
                self.assertIn(battery.category(case), {name for *_, name in battery.CATEGORIES} | {battery.MIXED})
                self.assertIn(battery.priority(case), {"ESSENTIAL", "POLISH"})


class TheClassifierTests(unittest.TestCase):
    """The scoring the ratchet relies on, proven to see the failures it claims."""

    case = {"id": "X", "expected": "Send it to finance.", "acceptable": ["Send it to finance"], "critical": True}

    def test_exact_acceptable_surface_words(self):
        self.assertEqual(battery.classify(self.case, "Send it to finance.", False), "exact")
        self.assertEqual(battery.classify(self.case, "Send it to finance", False), "acceptable")
        self.assertEqual(battery.classify(self.case, "send it, to finance!", False), "surface")
        self.assertEqual(battery.classify(self.case, "Send it to legal.", False), "words")

    def test_an_enter_nobody_asked_for_is_a_key_failure(self):
        self.assertEqual(battery.classify(self.case, "Send it to finance.", True), "keys")
        wants_enter = {**self.case, "keys": ["Enter"]}
        self.assertEqual(battery.classify(wants_enter, "Send it to finance.", False), "keys")
        self.assertEqual(battery.classify(wants_enter, "Send it to finance.", True), "exact")

    def test_a_crash_is_a_failure_not_a_skip(self):
        self.assertEqual(battery.classify(self.case, "", False, error="ValueError: boom"), "error")

    def test_the_summary_counts_critical_word_failures(self):
        rows = [{"id": "A", "verdict": "words", "critical": True, "ms": 1.0, "route": "", "rejection": ""},
                {"id": "B", "verdict": "surface", "critical": True, "ms": 1.0, "route": "", "rejection": ""},
                {"id": "C", "verdict": "skipped", "critical": True, "ms": 0.0, "route": "", "rejection": ""}]
        summary = battery.summarize(rows)
        self.assertEqual((summary["ran"], summary["critical_failures"], summary["skipped"]), (2, 1, 1))


class TheRulesLaneRatchetTests(unittest.TestCase):
    """Every commandment case the rules lane can receive, deterministically."""

    @classmethod
    def setUpClass(cls):
        cls.rows = battery.run(battery.load_cases())
        cls.by_id = {row["id"]: row for row in cls.rows}
        cls.baseline = battery.load_baseline()

    def failure(self, case_id: str) -> str:
        row = self.by_id[case_id]
        return f"{case_id}: {row['input']!r} -> {row['produced']!r} (expected {row['expected']!r})"

    def test_no_case_crashes_the_pipeline(self):
        self.assertEqual([self.failure(r["id"]) for r in self.rows if r["verdict"] == "error"], [])

    def test_no_enter_is_pressed_wrongly(self):
        self.assertEqual([self.failure(r["id"]) for r in self.rows if r["verdict"] == "keys"], [])

    def test_every_case_in_the_baseline_still_passes(self):
        for case_id in self.baseline["rules_passing"]:
            with self.subTest(case=case_id):
                self.assertIn(self.by_id[case_id]["verdict"], battery.PASSING, self.failure(case_id))

    def test_the_count_may_only_go_up(self):
        passing = {r["id"] for r in self.rows if r["verdict"] in battery.PASSING}
        self.assertEqual(self.baseline["rules_passing_count"], len(self.baseline["rules_passing"]))
        self.assertGreaterEqual(len(passing), self.baseline["rules_passing_count"])
        newly = sorted(passing - set(self.baseline["rules_passing"]))
        self.assertEqual(newly, [], "these now pass: record them so they cannot regress "
                                    "(python -m tests.commandment_battery --write-baseline)")

    def test_every_case_the_rules_do_not_pass_is_marked_with_a_reason(self):
        marked = self.baseline["rules_not_passing"]
        for row in self.rows:
            if row["verdict"] in battery.PASSING or row["verdict"] == "skipped":
                continue
            with self.subTest(case=row["id"]):
                reason = marked.get(row["id"], "")
                self.assertTrue(reason and reason != battery.UNMARKED, self.failure(row["id"]))
                self.assertRegex(reason, r"^(?:model|rewrite|gold conflict|not built): ")

    def test_skips_are_the_recorded_ones(self):
        skipped = {r["id"]: r["note"] for r in self.rows if r["verdict"] == "skipped"}
        self.assertEqual(skipped, self.baseline["skipped"])

    def test_the_rules_lane_never_reaches_a_model(self):
        # Only the two cases that hand the pipeline a simulated model answer
        # may report a model route; everything else is the rules lane.
        modelled = {r["id"] for r in self.rows if r["route"].startswith("local_model")}
        simulated = {r["id"] for r in self.rows if r["kind"] in {"simulated_model", "model_unavailable"}}
        self.assertLessEqual(modelled, simulated)


class TheRatchetCatchesARegressionTests(unittest.TestCase):
    """A counterfactual: the ratchet must fail when a baseline case breaks."""

    def test_a_broken_baseline_case_is_reported(self):
        case = next(c for c in battery.load_cases() if c["id"] == "C023-neg")
        row = battery.run_case(case, __import__("tests.parity_battery", fromlist=["local_config"]).local_config(None),
                               lane="rules")
        self.assertIn(row["verdict"], battery.PASSING)
        broken = battery.classify(case, "We finished the audit. File from the server.", False)
        self.assertEqual(broken, "words")


if __name__ == "__main__":
    unittest.main()
