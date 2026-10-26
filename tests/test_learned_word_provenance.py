"""T4: thirty real corrections, thirty ordinary copies, and the awkward cases.
No ordinary copy becomes an active rule; every automatic rule says where it came
from; an undo gives back exactly the output from before. Synthetic text only:
these call the learning functions directly, never the clipboard.
"""
from __future__ import annotations

import copy
import unittest

from knight_flow.learned_words import (
    affected_takes, drop_quarantined, forget, learn_or_quarantine, learned_entries, quarantined,
    release_quarantined, rollback, tombstoned,
)
from knight_flow.vocabulary import apply_vocabulary, parse_terms

NAMES = (
    "Okafor", "Nnamdi", "Kaelyn", "Folake", "Ngozi", "Chidinma", "Babatunde", "Oluwaseun", "Temitope", "Adewale",
    "Chukwuma", "Ifeoma", "Obinna", "Kelechi", "Ngozika", "Tochukwu", "Chiamaka", "Amarachi", "Nkechi", "Uchenna",
    "Kalinda", "Marisol", "Leopold", "Wilhelmina", "Bartholomew", "Thaddeus", "Cornelius", "Isadora", "Penelope",
    "Rosalind", "Gwendolyn", "Fitzgerald", "Mortimer", "Barnabas",
)


def misheard(name: str) -> str:
    """The recognizer's guess: the same consonants, other vowels, lower case.
    (name_repair pairs a fix with a guess by its consonant skeleton.)"""
    return name.lower().translate(str.maketrans("aeiou", "oaeui"))


def _qualifies(name: str) -> bool:
    from knight_flow.name_repair import MIN_SOUNDS, sound_skeleton

    guess = misheard(name)
    return guess != name.lower() and len(sound_skeleton(name)) >= MIN_SOUNDS \
        and sound_skeleton(name) == sound_skeleton(guess)


# (the spelling the person copied, the take it corrected, the word the recognizer was unsure of)
CORRECTIONS = [(name, f"please send the notes to {misheard(name)} today", misheard(name))
               for name in NAMES if _qualifies(name)][:30]

# Ordinary copies the person makes all day; none corrects a dictated word.
ORDINARY = [
    "the", "meeting", "Let's meet at noon", "https://example.com/path", r"C:\Users\someone\file.txt",
    "/home/someone/notes.md", "someone@example.com", "Xk9pQ2mZ7rT4", "a1b2c3d4e5f6g7h8i9", "B2B", "iPhone",
    "SKU-4471", "COVID", "NASA", "USB-C", "v2.10", "12345", "OK", "TODO", "PDF", "Q3", "#launch", "@handle",
    "item.name", "MacBook", "PowerPoint", "YouTube", "GPT4", "re:", "",
]


def config() -> dict:
    return {"dictionary": {"auto_learn": True, "auto_learn_mode": "auto-on-second", "terms": [], "words": []}}


def active_terms(cfg: dict) -> set[str]:
    dictionary = cfg["dictionary"]
    return {term.text for term in parse_terms(dictionary.get("words", []) + dictionary.get("terms", []))}


class NoOrdinaryCopyBecomesARule(unittest.TestCase):
    def test_thirty_ordinary_copies(self):
        cfg = config()
        delivered = "send the report to the team before noon"
        outcomes = {text: learn_or_quarantine(text, cfg, delivered, {"report": 0.4}) for text in ORDINARY}
        self.assertEqual(len(ORDINARY), 30)
        self.assertEqual(active_terms(cfg), set(), f"active rules learned from ordinary copies: {outcomes}")
        # The secrets, paths, addresses and sentences are never even held.
        for text in ("Xk9pQ2mZ7rT4", "a1b2c3d4e5f6g7h8i9", r"C:\Users\someone\file.txt", "/home/someone/notes.md",
                     "https://example.com/path", "Let's meet at noon", "the", ""):
            self.assertEqual(outcomes[text], "ignored", text)
        false_learning = sum(1 for outcome in outcomes.values() if outcome == "learned")
        print(f"\nT4 false-learning: {false_learning} of {len(ORDINARY)} ordinary copies became active rules; "
              f"{sum(1 for o in outcomes.values() if o == 'quarantined')} held for a yes")
        self.assertEqual(false_learning, 0)


class RealCorrectionsAreLearnedWithTheirStory(unittest.TestCase):
    def test_thirty_corrections(self):
        self.assertEqual(len(CORRECTIONS), 30, "fewer than thirty qualifying synthetic corrections")
        cfg = config()
        learned = 0
        for spelling, delivered, heard in CORRECTIONS:
            outcome = learn_or_quarantine(spelling, cfg, delivered, {heard: 0.3})
            learned += outcome == "learned"
        rows = {row["text"]: row for row in learned_entries(cfg)}
        print(f"\nT4 corrections: {learned} of {len(CORRECTIONS)} learned from the take they corrected")
        for spelling, _delivered, heard in CORRECTIONS:
            if spelling in rows:
                row = rows[spelling]
                self.assertEqual(row["heard"], heard)
                self.assertEqual(row["how"], "automatic")
                self.assertTrue(row["at"] and row["id"])
        self.assertEqual(len(rows), learned)
        # Every automatic rule has provenance; nothing is learned without it.
        for entry in cfg["dictionary"]["terms"]:
            self.assertIn("provenance", entry)

    def test_a_correction_fixes_the_next_take(self):
        cfg = config()
        guess = misheard("Okafor")
        self.assertEqual(learn_or_quarantine("Okafor", cfg, f"call {guess} now", {guess: 0.3}), "learned")
        text = apply_vocabulary(f"call {guess} now", parse_terms(cfg["dictionary"]["terms"]))
        self.assertIn("Okafor", text)


class UndoGivesBackTheOldOutput(unittest.TestCase):
    def test_rollback_restores_previous_output(self):
        cfg = config()
        guess = misheard("Nnamdi")
        sample = f"loop in {guess} and the team"
        before = apply_vocabulary(sample, parse_terms(cfg["dictionary"]["terms"]))
        self.assertEqual(learn_or_quarantine("Nnamdi", cfg, f"loop in {guess}", {guess: 0.3}), "learned")
        changed = apply_vocabulary(sample, parse_terms(cfg["dictionary"]["terms"]))
        self.assertNotEqual(changed, before)
        (row,) = learned_entries(cfg)
        removed = rollback(cfg, row["id"])
        self.assertEqual(removed["text"], "Nnamdi")
        self.assertEqual(apply_vocabulary(sample, parse_terms(cfg["dictionary"]["terms"])), before)
        self.assertTrue(tombstoned("Nnamdi", cfg))
        self.assertEqual(learn_or_quarantine("Nnamdi", cfg, f"loop in {guess}", {guess: 0.3}), "ignored")

    def test_rollback_of_an_unknown_id_changes_nothing(self):
        cfg = config()
        guess = misheard("Nnamdi")
        learn_or_quarantine("Nnamdi", cfg, f"loop in {guess}", {guess: 0.3})
        before = copy.deepcopy(cfg)
        self.assertIsNone(rollback(cfg, "not-an-id"))
        self.assertEqual(cfg, before)

    def test_a_hand_added_word_cannot_be_rolled_back(self):
        cfg = config()
        cfg["dictionary"]["terms"].append({"text": "Okafor", "sounds_like": ["okafur"]})
        self.assertEqual(learned_entries(cfg), [])
        self.assertFalse(forget("Okafor", cfg))
        self.assertEqual(cfg["dictionary"]["terms"][0]["text"], "Okafor")


class TheQuarantine(unittest.TestCase):
    def test_a_shape_with_no_correction_waits_for_a_yes(self):
        cfg = config()
        self.assertEqual(learn_or_quarantine("SAHVVV", cfg, "send it to the artist", {}), "quarantined")
        self.assertNotIn("SAHVVV", active_terms(cfg))
        self.assertEqual([item["text"] for item in quarantined(cfg)], ["SAHVVV"])
        self.assertEqual(learn_or_quarantine("SAHVVV", cfg, "", {}), "quarantined")
        self.assertEqual(len(quarantined(cfg)), 1)
        self.assertTrue(release_quarantined("SAHVVV", cfg))
        self.assertIn("SAHVVV", active_terms(cfg))
        self.assertEqual(quarantined(cfg), [])
        (row,) = learned_entries(cfg)
        self.assertEqual(row["how"], "accepted from quarantine")

    def test_a_no_is_final(self):
        cfg = config()
        learn_or_quarantine("B2B", cfg, "", {})
        self.assertTrue(drop_quarantined("B2B", cfg))
        self.assertEqual(quarantined(cfg), [])
        self.assertEqual(learn_or_quarantine("B2B", cfg, "", {}), "ignored")

    def test_a_copied_password_or_key_is_never_held(self):
        cfg = config()
        for secret in ("Xq7Lm2Rv9Tz4", "k3v9q2m7x5r8t1w6"):  # a generated password, a key
            self.assertEqual(learn_or_quarantine(secret, cfg, "", {}), "ignored", secret)
        # Even when it would pair with a word the take was unsure of.
        self.assertEqual(learn_or_quarantine("Xq7Lm2Rv9Tz4", cfg, "the code is xqlmrvtz", {"xqlmrvtz": 0.2}),
                         "ignored")
        self.assertEqual(quarantined(cfg), [])
        self.assertEqual(learned_entries(cfg), [])


class ProjectsKeepTheirLearnedWords(unittest.TestCase):
    def test_a_word_learned_in_a_project_stays_there(self):
        cfg = config()
        cfg["dictionary"]["projects"] = [{"id": "film", "name": "Film", "terms": []}]
        guess = misheard("Okafor")
        self.assertEqual(learn_or_quarantine("Okafor", cfg, f"ask {guess}", {guess: 0.3}, project="film"), "learned")
        self.assertEqual(cfg["dictionary"]["terms"], [])
        self.assertEqual(cfg["dictionary"]["projects"][0]["terms"][0]["text"], "Okafor")
        (row,) = learned_entries(cfg)
        self.assertEqual(row["project"], "film")
        self.assertTrue(forget("Okafor", cfg))
        self.assertEqual(cfg["dictionary"]["projects"][0]["terms"], [])


class WhatAWordChanged(unittest.TestCase):
    def test_affected_takes(self):
        history = [{"text": "Ask Siobhan about it."}, {"text": "Nothing here."}, {"text": "Siobhan, call me."}]
        self.assertEqual(len(affected_takes(history, "Siobhan")), 2)
        self.assertEqual(affected_takes(history, "Sio"), [])
        self.assertEqual(len(affected_takes(history * 30, "Siobhan", limit=5)), 5)


if __name__ == "__main__":
    unittest.main()
