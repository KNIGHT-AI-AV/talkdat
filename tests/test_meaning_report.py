"""T2: the curated set. Every material change a cleanup can make is reported;
harmless cleanup is not. Synthetic utterances only.

Each case is (what was said, what was finished, the kinds that must be reported).
An empty tuple means the cleanup was harmless and the report must say so.
"""
from __future__ import annotations

import unittest

from knight_flow.meaning_report import KINDS, meaning_report

MATERIAL = [
    # numbers
    ("we need fifteen chairs", "We need fifty chairs.", ("number",)),
    ("the budget is 42000", "The budget is 4200.", ("number",)),
    ("call me at 9 30", "Call me at 9:13.", ("number",)),
    ("version 2.10 ships", "Version 2.1 ships.", ("number",)),
    ("send 3 copies", "Send copies.", ("number",)),
    ("move it to room 101", "Move it to room 110.", ("number",)),
    ("it costs 12 dollars", "It costs 21 dollars.", ("number", "unit")),
    ("order 2 boxes not 20", "Order 20 boxes.", ("number", "negation")),
    ("the code is 4471", "The code is 4417.", ("number",)),
    ("chapter seven", "Chapter eleven.", ("number",)),
    # units
    ("it is fifteen kilometers away", "It is 15 miles away.", ("unit",)),
    ("add 2 kg of flour", "Add 2 lb of flour.", ("unit",)),
    ("growth was 5 percent", "Growth was 5 dollars.", ("unit",)),
    ("the file is 3 gb", "The file is 3 MB.", ("unit",)),
    ("wait 10 minutes", "Wait 10 hours.", ("unit",)),
    ("it weighs 4 pounds", "It weighs 4 ounces.", ("unit",)),
    ("raise it by 2 x", "Raise it by 2%.", ("unit",)),
    ("the trip takes 3 days", "The trip takes 3 weeks.", ("unit",)),
    ("it is $40", "It is €40.", ("unit",)),
    ("use 250 ml", "Use 250 l.", ("unit",)),
    # dates
    ("the meeting is on tuesday", "The meeting is on Thursday.", ("date",)),
    ("ship it in october", "Ship it in November.", ("date",)),
    ("call me tomorrow", "Call me today.", ("date",)),
    ("the review is next week", "The review is this week.", ("date",)),
    ("pay by friday", "Pay by Monday.", ("date",)),
    ("it launched in jan", "It launched in June.", ("date",)),
    ("see you tonight", "See you tomorrow.", ("date",)),
    ("the report is due end of month", "The report is due end of week.", ("date",)),
    ("we met on the 3rd of may", "We met on the 3rd of March.", ("date",)),
    ("book it for sunday", "Book it.", ("date",)),
    # negations
    ("don't send it", "Send it.", ("negation",)),
    ("we can't approve this", "We can approve this.", ("negation",)),
    ("it is not ready", "It is ready.", ("negation",)),
    ("never share the key", "Always share the key.", ("negation",)),
    ("nobody saw the email", "Everybody saw the email.", ("negation",)),
    ("send it", "Don't send it.", ("negation",)),
    ("we won't ship friday", "We will ship Friday.", ("negation",)),
    ("there is no backup", "There is a backup.", ("negation",)),
    ("i didn't sign it", "I signed it.", ("negation",)),
    ("do not delete the folder", "Delete the folder.", ("negation",)),
    # commitments and modals
    ("we might ship on friday", "We will ship on Friday.", ("commitment",)),
    ("you should review it", "You must review it.", ("commitment",)),
    ("i could send it", "I will send it.", ("commitment",)),
    ("we may cancel", "We will cancel.", ("commitment",)),
    ("i will call", "I might call.", ("commitment",)),
    ("they have to sign", "They could sign.", ("commitment",)),
    ("we promise delivery", "We hope for delivery.", ("commitment",)),
    ("i can join", "I will join.", ("commitment",)),
    ("you need to file it", "You may file it.", ("commitment",)),
    ("we agreed to the terms", "We discussed the terms.", ("commitment",)),
    # certainty and hedges
    ("it is probably fine", "It is fine.", ("certainty",)),
    ("maybe we can meet", "We can meet.", ("certainty",)),
    ("it is definitely broken", "It is broken.", ("certainty",)),
    ("it costs at least 100", "It costs 100.", ("certainty",)),
    ("i am not sure it works", "I am sure it works.", ("negation", "certainty")),
    ("it is roughly 30 people", "It is 30 people.", ("certainty",)),
    ("it is fine", "It is probably fine.", ("certainty",)),
    ("possibly next week", "Next week.", ("certainty",)),
    ("it is likely late", "It is late.", ("certainty",)),
    ("perhaps we wait", "We wait.", ("certainty",)),
    # names
    ("send it to Sarah", "Send it to Sara.", ("name",)),
    ("ask Adaeze about it", "Ask Ada about it.", ("name",)),
    ("the api is down", "The Deepgram API is down.", ("name",)),
    ("loop in Mayowa and Tunde", "Loop in Mayowa.", ("name",)),
    ("the client is Acme", "The client is Apex.", ("name",)),
    ("ping Jordan", "Ping Jordan and Kim.", ("name",)),
    ("call Dr Okafor", "Call Dr Okoro.", ("name",)),
    ("it runs on Windows", "It runs on Linux.", ("name",)),
    ("email Priya", "Email the team.", ("name",)),
    ("Kaelyn said yes", "Kaitlyn said yes.", ("name",)),
    # quoted commands
    ('type "git push --force"', 'Type "git push".', ("quote",)),
    ('the label says "do not open"', 'The label says "open".', ("quote", "negation")),
    ('reply "yes"', 'Reply "no".', ("quote", "negation")),
    ('run "rm -rf build"', 'Run "rm -rf".', ("quote",)),
    ('say "sorry for the delay"', 'Say "thanks for waiting".', ("quote",)),
]

HARMLESS = [
    ("we need fifteen chairs", "We need 15 chairs."),
    ("call me at twelve fifteen p m", "Call me at 12:15 PM."),
    ("the budget is 42000", "The budget is 42,000."),
    ("um so we should uh ship friday", "We should ship Friday."),
    ("send it to sarah", "Send it to Sarah."),
    ("it is fifteen kilometers away", "It is 15 km away."),
    ("growth was 5 percent", "Growth was 5%."),
    ("don't send it", "Do not send it."),
    ("we can't approve this", "We cannot approve this."),
    ("the meeting is on tuesday", "The meeting is on Tuesday."),
    ("ship it in oct", "Ship it in October."),
    ("you need to file it", "You must file it."),
    ("they gotta sign", "They have to sign."),
    ("i'm gonna call", "I'm going to call."),
    ("it costs $40", "It costs 40 dollars."),
    ("wait ten minutes", "Wait 10 minutes."),
    ("the file is 3 gigabytes", "The file is 3 GB."),
    ('type "git push --force"', 'Type "git push --force".'),
    ("it is probably fine", "It's probably fine."),
    ("first buy milk second buy eggs", "1. Buy milk.\n2. Buy eggs."),
    ("hello world", "Hello, world."),
    ("so yeah the report is done", "The report is done."),
    ("we won't ship friday", "We will not ship Friday."),
    ("i will call you tomorrow", "I will call you tomorrow."),
    ("it weighs 4 lbs", "It weighs 4 pounds."),
]


class EveryMaterialChangeIsReported(unittest.TestCase):
    def test_the_material_set(self):
        missed = {}
        for said, finished, kinds in MATERIAL:
            report = meaning_report(said, finished)
            reported = set(report.kinds_changed())
            if not report.material or not set(kinds) <= reported:
                missed[f"{said!r} -> {finished!r}"] = (sorted(reported), kinds)
        self.assertEqual(missed, {})

    def test_the_set_is_the_size_the_handoff_asked_for(self):
        self.assertGreaterEqual(len(MATERIAL) + len(HARMLESS), 100)
        for kind in ("number", "unit", "date", "negation", "commitment", "name", "quote"):
            self.assertGreaterEqual(sum(1 for _, _, kinds in MATERIAL if kind in kinds), 5, kind)


class HarmlessCleanupIsNotFlagged(unittest.TestCase):
    def test_the_harmless_set(self):
        flagged = {}
        for said, finished in HARMLESS:
            report = meaning_report(said, finished)
            if report.material:
                flagged[f"{said!r} -> {finished!r}"] = [(c.kind, c.said, c.written) for c in report.changes]
        self.assertEqual(flagged, {})


class TheReportItself(unittest.TestCase):
    def test_kept_counts(self):
        report = meaning_report("send 3 copies to Sarah on friday", "Send 3 copies to Sarah on Friday.")
        self.assertFalse(report.material)
        self.assertEqual(report.kept["number"], 1)
        self.assertEqual(report.kept["date"], 1)
        self.assertGreaterEqual(report.kept["name"], 1)

    def test_a_change_says_what_was_said_and_what_was_written(self):
        report = meaning_report("the meeting is on tuesday", "The meeting is on Thursday.")
        (change,) = report.changes
        self.assertEqual((change.kind, change.said, change.written), ("date", ("tuesday",), ("thursday",)))

    def test_protected_terms(self):
        report = meaning_report("ask KnightAIAV about it", "Ask Knight AI about it.", protected=["KnightAIAV"])
        self.assertIn("protected", report.kinds_changed())
        report = meaning_report("ask KnightAIAV about it", "Ask KnightAIAV about it.", protected=["KnightAIAV"])
        self.assertNotIn("protected", report.kinds_changed())
        self.assertEqual(report.kept["protected"], 1)

    def test_changes_come_in_reading_order(self):
        report = meaning_report("don't pay Sarah 15 dollars on friday", "Pay Sara 50 euros on Monday.")
        kinds = report.kinds_changed()
        self.assertEqual(list(kinds), sorted(kinds, key=KINDS.index))

    def test_empty_inputs(self):
        self.assertFalse(meaning_report("", "").material)
        self.assertTrue(meaning_report("send 3", "").material)

    def test_may_the_modal_is_not_a_date(self):
        # Taking out a repeated "we may" changes no date; the month still counts.
        self.assertNotIn("date", meaning_report("we may we may ship it", "We may ship it.").kinds_changed())
        self.assertIn("date", meaning_report("ship it on may 5", "Ship it on June 5.").kinds_changed())

    def test_the_history_form_is_plain_values(self):
        import json

        report = meaning_report("the meeting is on tuesday", "The meeting is on Thursday.")
        stored = json.loads(json.dumps(report.as_dict()))
        self.assertTrue(stored["material"])
        self.assertEqual(stored["changes"], [{"kind": "date", "said": ["tuesday"], "written": ["thursday"]}])
        self.assertEqual(stored["kept"], dict(report.kept))

    def test_a_filler_opening_a_sentence_is_not_a_name(self):
        report = meaning_report("So we ship it today. Well it works.", "We ship it today. It works.")
        self.assertNotIn("name", report.kinds_changed())
        self.assertIn("name", meaning_report("So Sarah ships it today.", "So Sara ships it today.").kinds_changed())


if __name__ == "__main__":
    unittest.main()
