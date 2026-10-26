"""T3: three synthetic projects, twenty names each that sound alike across
projects. A project's spelling never reaches another project's take, and the
manual edits left after vocabulary repair fall by at least 30% against one
global glossary. Synthetic text only.
"""
from __future__ import annotations

import copy
import unittest

from knight_flow.vocabulary import apply_vocabulary, parse_terms
from knight_flow.word_scopes import (
    active_project, apply_word_scope, glossary, new_project, project_by_id, projects, scoped_dictionary,
)

# What the recognizer writes, and how each project spells that person.
SOUNDS = {
    "sean": ("Sean", "Shawn", "Shaun"), "jon": ("Jon", "John", "Jahn"), "kai": ("Kai", "Kye", "Ky"),
    "lee": ("Lee", "Leigh", "Li"), "zoe": ("Zoe", "Zoey", "Zoee"), "mark": ("Mark", "Marc", "Marq"),
    "claire": ("Claire", "Clare", "Clair"), "ann": ("Ann", "Anne", "An"), "carl": ("Carl", "Karl", "Carle"),
    "eric": ("Eric", "Erik", "Erich"), "brian": ("Brian", "Bryan", "Brien"),
    "steven": ("Steven", "Stephen", "Stevan"), "rachel": ("Rachel", "Rachael", "Rachell"),
    "megan": ("Megan", "Meghan", "Meagan"), "kathy": ("Kathy", "Cathy", "Kathie"),
    "philip": ("Philip", "Phillip", "Phyllip"), "teresa": ("Teresa", "Theresa", "Tereza"),
    "alan": ("Alan", "Allen", "Allan"), "jeff": ("Jeff", "Geoff", "Jef"), "sara": ("Sara", "Sarah", "Sarra"),
}
PROJECTS = ("film", "client", "podcast")
SENTENCES = ("send the cut to {} today", "{} approved the second draft", "ask {} about the schedule")


def config_with_projects() -> dict:
    config = {"dictionary": {"words": [], "terms": [{"text": "Kubernetes", "sounds_like": ["cooper netties"]}],
                             "replacements": []}}
    for index, name in enumerate(PROJECTS):
        project = new_project(config, name.title())
        project["terms"] = [{"text": spellings[index], "sounds_like": [sound]} for sound, spellings in SOUNDS.items()]
    return config


def errors(text: str, expected: dict[str, str]) -> int:
    return sum(1 for sound, spelling in expected.items() for sentence in SENTENCES
               if sentence.format(spelling) not in text)


def transcript() -> str:
    return "\n".join(sentence.format(sound) for sound in SOUNDS for sentence in SENTENCES)


def alone(project: dict) -> list:
    """The project's own terms and nothing else: the most a scope could do."""
    return parse_terms(project["terms"])


class NoProjectLeaksIntoAnother(unittest.TestCase):
    def test_each_project_gets_only_its_own_spellings(self):
        config = config_with_projects()
        for index, name in enumerate(PROJECTS):
            config["dictionary"]["active_project"] = name
            scoped = apply_word_scope(config, active_project(config))
            terms = parse_terms(scoped["dictionary"]["words"] + scoped["dictionary"]["terms"])
            text = apply_vocabulary(transcript(), terms)
            expected = {sound: spellings[index] for sound, spellings in SOUNDS.items()}
            # Scoping adds no error of its own: the scoped dictionary corrects
            # exactly what the project's words alone correct. (What neither
            # corrects is the matcher's limit, not the scope's; see below.)
            baseline = apply_vocabulary(transcript(), alone(project_by_id(config, name)))
            self.assertEqual(errors(text, expected), errors(baseline, expected), f"{name}: {text[:200]}")
            others = {spellings[other] for spellings in SOUNDS.values() for other in range(3) if other != index}
            leaked = {word for word in others if f" {word} " in f" {text} " and word not in expected.values()}
            self.assertEqual(leaked, set(), f"{name} took another project's spelling")

    def test_switching_projects_changes_only_the_next_take(self):
        config = config_with_projects()
        config["dictionary"]["active_project"] = "film"
        film = apply_word_scope(config, active_project(config))
        config["dictionary"]["active_project"] = "client"
        client = apply_word_scope(config, active_project(config))
        self.assertEqual(film["_word_scope"]["project"], "film")
        self.assertEqual(client["_word_scope"]["project"], "client")
        film_terms = {term["text"] for term in film["dictionary"]["terms"]}
        self.assertNotIn("Shawn", film_terms)
        self.assertIn("Shawn", {term["text"] for term in client["dictionary"]["terms"]})

    def test_the_stored_config_is_never_changed_by_a_take(self):
        config = config_with_projects()
        config["dictionary"]["active_project"] = "podcast"
        before = copy.deepcopy(config)
        apply_word_scope(config, active_project(config))
        self.assertEqual(config, before)


class AtLeastThirtyPercentFewerEdits(unittest.TestCase):
    def test_against_one_global_glossary(self):
        config = config_with_projects()
        scoped_errors = union_errors = first_only_errors = 0
        unfixable = set()
        union_terms = parse_terms([term for project in projects(config) for term in project["terms"]])
        first_only = parse_terms(projects(config)[0]["terms"])
        for index, name in enumerate(PROJECTS):
            expected = {sound: spellings[index] for sound, spellings in SOUNDS.items()}
            scoped = apply_word_scope(config, project_by_id(config, name))
            terms = parse_terms(scoped["dictionary"]["words"] + scoped["dictionary"]["terms"])
            text = apply_vocabulary(transcript(), terms)
            scoped_errors += errors(text, expected)
            unfixable |= {f"{sound}->{expected[sound]}" for sound in SOUNDS
                          if SENTENCES[0].format(expected[sound]) not in text}
            union_errors += errors(apply_vocabulary(transcript(), union_terms), expected)
            first_only_errors += errors(apply_vocabulary(transcript(), first_only), expected)
        total = len(PROJECTS) * len(SOUNDS) * len(SENTENCES)
        # Recorded for the report: the size of each baseline's remaining edits,
        # and the spellings the vocabulary matcher cannot reach even from a
        # project's own words (a short sound-alike alias it does not match).
        print(f"\nT3 edits left of {total}: scoped {scoped_errors}, one glossary with every spelling "
              f"{union_errors}, one glossary with one spelling per sound {first_only_errors}; "
              f"matcher limits: {sorted(unfixable)}")
        for baseline in (union_errors, first_only_errors):
            self.assertGreater(baseline, 0)
            self.assertLessEqual(scoped_errors, baseline * 0.7)


class CollisionsAreResolvedOutLoud(unittest.TestCase):
    def setUp(self):
        self.config = {"dictionary": {"terms": [{"text": "Sean", "sounds_like": ["shawn"]},
                                                {"text": "Kubernetes", "sounds_like": []}],
                                      "words": ["Okafor"], "replacements": [{"from": "asap", "to": "ASAP"}]}}
        self.project = new_project(self.config, "Film")
        self.project["terms"] = [{"text": "Shawn", "sounds_like": ["sean"]}]
        self.project["replacements"] = [{"from": "asap", "to": "as soon as possible"}]

    def test_the_project_wins_and_the_collision_is_reported(self):
        scoped, collisions = scoped_dictionary(self.config, self.project)
        texts = [term["text"] for term in scoped["terms"]]
        self.assertIn("Shawn", texts)
        self.assertNotIn("Sean", texts)
        self.assertIn("Kubernetes", texts)
        self.assertEqual(scoped["words"], ["Okafor"])
        self.assertEqual(len(collisions), 1)
        self.assertEqual((collisions[0].project_spelling, collisions[0].global_spelling, collisions[0].winner),
                         ("Shawn", "Sean", "project"))
        self.assertEqual(scoped["replacements"], [{"from": "asap", "to": "as soon as possible"}])

    def test_a_project_may_keep_the_global_spelling(self):
        self.project["prefer_global"] = ["Sean"]
        scoped, collisions = scoped_dictionary(self.config, self.project)
        texts = [term["text"] for term in scoped["terms"]]
        self.assertIn("Sean", texts)
        self.assertNotIn("Shawn", texts)
        self.assertEqual(collisions[0].winner, "global")

    def test_the_glossary_shows_what_a_take_uses_and_why(self):
        rows = glossary(self.config, self.project)
        by_text = {row["text"]: row for row in rows}
        self.assertEqual(by_text["Shawn"]["source"], "project")
        self.assertEqual(by_text["Kubernetes"]["source"], "global")
        self.assertIn("Shawn", by_text["Sean"]["note"])

    def test_the_same_word_in_both_is_used_once(self):
        self.project["terms"].append({"text": "Kubernetes", "sounds_like": []})
        scoped, collisions = scoped_dictionary(self.config, self.project)
        self.assertEqual([term["text"] for term in scoped["terms"]].count("Kubernetes"), 1)
        self.assertEqual([c for c in collisions if c.project_spelling == "Kubernetes"], [])


class ChoosingTheProject(unittest.TestCase):
    def test_explicit_choice_then_the_app_profile(self):
        config = config_with_projects()
        self.assertIsNone(active_project(config))
        self.assertEqual(active_project(config, {"match": "resolve", "project": "film"})["id"], "film")
        config["dictionary"]["active_project"] = "client"
        self.assertEqual(active_project(config, {"project": "film"})["id"], "client")
        config["dictionary"]["active_project"] = "missing"
        self.assertIsNone(active_project(config))

    def test_no_project_means_the_global_dictionary_untouched(self):
        config = config_with_projects()
        self.assertIs(apply_word_scope(config, None), config)

    def test_a_takes_dictionary_carries_no_other_project(self):
        config = config_with_projects()
        for project in (None, project_by_id(config, "film")):
            scoped, _collisions = scoped_dictionary(config, project)
            self.assertNotIn("projects", scoped)
        take = apply_word_scope(config, project_by_id(config, "client"))
        self.assertNotIn("projects", take["dictionary"])
        self.assertNotIn("Shaun", repr(take["dictionary"]))  # the podcast project's spelling
        self.assertEqual(len(config["dictionary"]["projects"]), 3)  # the stored config keeps them all

    def test_new_project_ids(self):
        config = {}
        first = new_project(config, "Client Work")
        second = new_project(config, "Client Work")
        self.assertEqual((first["id"], second["id"]), ("client-work", "client-work-2"))
        self.assertEqual(new_project(config, "!!!")["id"], "project")

    def test_malformed_projects_are_ignored(self):
        config = {"dictionary": {"projects": [{"id": "Bad Id"}, "nope", {"id": "ok"}, {"id": "ok"}]}}
        self.assertEqual([project["id"] for project in projects(config)], ["ok"])


if __name__ == "__main__":
    unittest.main()
