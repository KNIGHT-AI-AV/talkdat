from __future__ import annotations

import unittest

from knight_flow.screen_context import names_from_title
from knight_flow.text_pipeline import apply_vocabulary_terms


class NamesComeOffTheScreenTests(unittest.TestCase):
    """X-34. One on-device read of the foreground window title; its proper
    nouns bias that dictation's vocabulary. Nothing uploaded, nothing stored,
    and app chrome never mistaken for a person."""

    def test_a_mail_reply_yields_the_correspondent(self) -> None:
        names = names_from_title("RE: Contract with Adaeze Okafor - Mail - Microsoft Edge")
        self.assertIn("Adaeze Okafor", names)
        self.assertNotIn("Microsoft Edge", names)
        self.assertNotIn("Mail", names)

    def test_app_chrome_alone_yields_nothing(self) -> None:
        for title in ("Untitled - Notepad", "New Tab - Google Chrome", ""):
            with self.subTest(title=title):
                self.assertEqual(names_from_title(title), [])

    def test_runs_stay_together_and_dedupe(self) -> None:
        names = names_from_title("Adaeze Okafor, Adaeze Okafor and Chidi Eze | Slack")
        self.assertEqual(names.count("Adaeze Okafor"), 1)
        self.assertIn("Chidi Eze", names)

    def test_the_limit_holds(self) -> None:
        title = " - ".join(f"Person Number{i} Name{i}" for i in range(20))
        self.assertLessEqual(len(names_from_title(title)), 8)


class ScreenNamesBiasTheDictationTests(unittest.TestCase):
    def test_a_screen_name_repairs_its_mishearing(self) -> None:
        out = apply_vocabulary_terms(
            "I emailed adesa okafor this morning",
            {"_screen_names": ["Adaeze Okafor"]},
        )
        self.assertEqual(out, "I emailed Adaeze Okafor this morning")

    def test_the_off_switch_is_respected(self) -> None:
        out = apply_vocabulary_terms(
            "I emailed adesa okafor",
            {"_screen_names": ["Adaeze Okafor"], "dictionary": {"screen_context": False}},
        )
        self.assertEqual(out, "I emailed adesa okafor")

    def test_a_users_own_entry_outranks_the_screen(self) -> None:
        """The user taught a spelling that answers to the same sound; the
        window title's version must stay out entirely -- two same-key terms
        veto each other in the matcher, which would cost the user the
        correction they set up."""
        out = apply_vocabulary_terms(
            "I emailed adesa okafor",
            {
                "_screen_names": ["Adaeze Okafor"],
                "dictionary": {"terms": [{"text": "Adesa Okafore"}]},
            },
        )
        self.assertIn("Adesa Okafore", out)
        self.assertNotIn("Adaeze", out)

    def test_no_screen_names_changes_nothing(self) -> None:
        out = apply_vocabulary_terms("plain sentence here", {"_screen_names": []})
        self.assertEqual(out, "plain sentence here")


if __name__ == "__main__":
    unittest.main()
