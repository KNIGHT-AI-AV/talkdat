"""T5: three synthetic glossaries with duplicates, ambiguous words and noise.
Every proposed term is reviewable; nothing the person did not accept is kept;
removing an import is exact. Synthetic files only (written to a temp folder).
"""
from __future__ import annotations

import copy
import json
import tempfile
import time
import unittest
from pathlib import Path

from knight_flow.glossary_import import import_accepted, imports, preview, read_file, remove_import

FILM = """# Crew and cast for the short
Dolly Grip
Gaffer
Best Boy
Siobhan | shivon, shiv on
Kaelyn | kaylin
Gaffer
https://example.com/call-sheet
C:\\Projects\\Film\\notes.txt
We start shooting at seven sharp on Monday morning, please be on time.
Xk9pQ2mZ7rT4vB8n
Steadicam
Siobhan
"""

CLIENT_CSV = """term,sounds like
Kubernetes,cooper netties
PostgreSQL,postgres sequel; post gress
OAuth,oh auth
Kubernetes,
SaaS,sass
Okafor Holdings,
https://client.example/glossary,
This line is a long description of the whole engagement,
Talk DAT!,
"""

MEDICAL = """Metoprolol
Amoxicillin
Atorvastatin
Lisinopril
metoprolol
Hemoglobin A1c
Pt.
/usr/share/dict/words
Ibuprofen
Acetaminophen
!!!
"""


class APreviewBeforeAnything(unittest.TestCase):
    def setUp(self):
        self.config = {"dictionary": {"words": [], "terms": [{"text": "Sean", "sounds_like": ["shawn"]}],
                                      "replacements": []}}

    def test_the_film_list(self):
        before = copy.deepcopy(self.config)
        plan = preview(self.config, FILM, source_name="film.txt")
        self.assertEqual(self.config, before, "a preview must store nothing")
        new = {candidate.text for candidate in plan.of("new")}
        self.assertEqual(new, {"Dolly Grip", "Gaffer", "Best Boy", "Siobhan", "Kaelyn", "Steadicam"})
        self.assertEqual({candidate.text for candidate in plan.of("duplicate")}, {"Gaffer", "Siobhan"})
        reasons = {candidate.reason for candidate in plan.of("rejected")}
        self.assertEqual(reasons, {"a link", "a file path", "a sentence, not a term", "looks like a password or key"})
        siobhan = next(candidate for candidate in plan.of("new") if candidate.text == "Siobhan")
        self.assertEqual(siobhan.sounds_like, ("shivon", "shiv on"))

    def test_the_client_csv(self):
        plan = preview(self.config, CLIENT_CSV, source_name="client.csv")
        new = {candidate.text for candidate in plan.of("new")}
        self.assertTrue({"Kubernetes", "PostgreSQL", "OAuth", "SaaS", "Okafor Holdings"} <= new, new)
        postgres = next(candidate for candidate in plan.candidates if candidate.text == "PostgreSQL")
        self.assertEqual(postgres.sounds_like, ("postgres sequel", "post gress"))
        self.assertIn("Kubernetes", {candidate.text for candidate in plan.of("duplicate")})
        self.assertTrue(any(candidate.reason == "a link" for candidate in plan.of("rejected")))
        self.assertTrue(any(candidate.reason == "a sentence, not a term" for candidate in plan.of("rejected")))

    def test_the_medical_list(self):
        plan = preview(self.config, MEDICAL, source_name="medical.txt")
        new = {candidate.text for candidate in plan.of("new")}
        self.assertTrue({"Metoprolol", "Amoxicillin", "Atorvastatin", "Lisinopril", "Hemoglobin A1c", "Ibuprofen",
                         "Acetaminophen"} <= new, new)
        self.assertIn("metoprolol", {candidate.text for candidate in plan.of("duplicate")})
        self.assertTrue(any(candidate.reason == "a file path" for candidate in plan.of("rejected")))
        self.assertTrue(any(candidate.reason == "no letters or digits" for candidate in plan.of("rejected")))

    def test_known_and_conflicting_words(self):
        plan = preview(self.config, "Sean\nShawn | sean\n", source_name="names.txt")
        self.assertEqual([candidate.text for candidate in plan.of("known")], ["Sean"])
        (conflict,) = plan.of("conflict")
        self.assertEqual((conflict.text, conflict.conflicts_with), ("Shawn", "Sean"))


class OnlyAcceptedTermsAreKept(unittest.TestCase):
    def test_nothing_unaccepted_is_stored(self):
        config = {"dictionary": {"words": [], "terms": [], "replacements": []}}
        plan = preview(config, FILM, source_name="film.txt")
        record = import_accepted(config, plan, ["Siobhan", "Gaffer", "We start shooting at seven sharp"])
        self.assertEqual(record["count"], 2)
        stored = json.dumps(config)
        for unrelated in ("Dolly Grip", "Steadicam", "example.com", "Projects", "seven sharp", "Xk9pQ2mZ7rT4vB8n"):
            self.assertNotIn(unrelated, stored, unrelated)
        for entry in config["dictionary"]["terms"]:
            self.assertEqual(entry["source"], {"id": record["id"], "name": "film.txt"})
        self.assertEqual(imports(config)[0]["name"], "film.txt")

    def test_removing_an_import_is_exact(self):
        config = {"dictionary": {"words": ["Okafor"], "terms": [{"text": "Sean", "sounds_like": []}],
                                 "replacements": []}}
        before = copy.deepcopy(config)
        first = import_accepted(config, preview(config, FILM, source_name="film.txt"), ["Siobhan", "Kaelyn"])
        middle = copy.deepcopy(config)
        second = import_accepted(config, preview(config, MEDICAL, source_name="medical.txt"), ["Ibuprofen"])
        self.assertEqual(remove_import(config, second["id"]), 1)
        self.assertEqual(config, middle)
        self.assertEqual(remove_import(config, first["id"]), 2)
        self.assertEqual(config, before)

    def test_an_import_into_a_project(self):
        project = {"id": "film", "name": "Film"}
        config = {"dictionary": {"terms": [], "projects": [project]}}
        before = copy.deepcopy(config)
        record = import_accepted(config, preview(config, FILM, source_name="film.txt", project=project),
                                 ["Siobhan"], project=project)
        self.assertEqual(config["dictionary"]["terms"], [])
        self.assertEqual(project["terms"][0]["text"], "Siobhan")
        self.assertEqual(remove_import(config, record["id"]), 1)
        self.assertEqual(config, before)


class FiftyTermsQuickly(unittest.TestCase):
    def test_fifty_terms_preview_and_import(self):
        lines = "\n".join(f"Term{chr(65 + index % 26)}{index}" for index in range(50))
        config = {"dictionary": {"terms": []}}
        started = time.perf_counter()
        plan = preview(config, lines, source_name="fifty.txt")
        import_accepted(config, plan, [candidate.text for candidate in plan.of("new")])
        elapsed = time.perf_counter() - started
        print(f"\nT5 fifty terms: preview + import {elapsed * 1000:.1f} ms of machine time "
              "(the person's review time needs the UI and is not measured here)")
        self.assertEqual(len(config["dictionary"]["terms"]), 50)
        self.assertLess(elapsed, 5.0)


class TheFileItself(unittest.TestCase):
    def test_a_binary_or_huge_file_is_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            binary = Path(folder) / "image.txt"
            binary.write_bytes(b"\x89PNG\x00\x00\x00")
            with self.assertRaises(ValueError):
                read_file(str(binary))
            text = Path(folder) / "terms.txt"
            text.write_text("\ufeffGaffer\n", encoding="utf-8")
            self.assertEqual(read_file(str(text)), ("Gaffer\n", "terms.txt"))

    def test_a_file_that_decodes_but_holds_nul_bytes_is_refused(self):
        # UTF-16 without its mark is valid UTF-8 byte for byte, NULs and all.
        with tempfile.TemporaryDirectory() as folder:
            wide = Path(folder) / "wide.txt"
            wide.write_bytes("Gaffer\nBest boy\n".encode("utf-16-le"))
            with self.assertRaisesRegex(ValueError, "not plain text"):
                read_file(str(wide))


if __name__ == "__main__":
    unittest.main()
