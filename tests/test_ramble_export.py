from __future__ import annotations

import datetime as dt
import unittest
import zipfile
from io import BytesIO
from pypdf import PdfReader

from knight_flow.ramble_export import render, render_docx, render_pdf

WHEN = dt.datetime(2026, 8, 9, 15, 30)
TEXT = "The quarterly plan\nFirst we ship the beta.\nThen we tell everyone."


class AnHourOfTalkBecomesADocumentTests(unittest.TestCase):
    """Read the produced document instead of depending on one PDF encoding."""

    def test_the_docx_is_a_valid_package_with_the_words_inside(self) -> None:
        data = render_docx(TEXT, WHEN)
        with zipfile.ZipFile(BytesIO(data)) as archive:
            names = set(archive.namelist())
            self.assertIn("[Content_Types].xml", names)
            self.assertIn("word/document.xml", names)
            document = archive.read("word/document.xml").decode("utf-8")
        self.assertIn("First we ship the beta.", document)
        self.assertIn("Talk DAT!", document)

    def test_the_pdf_has_a_header_pages_and_the_words(self) -> None:
        data = render_pdf(TEXT, WHEN)
        reader = PdfReader(BytesIO(data), strict=True)
        self.assertGreaterEqual(len(reader.pages), 1)
        self.assertIn("First we ship the beta.", reader.pages[0].extract_text())
        self.assertEqual(reader.attachments["dictated-text.txt"][0].decode("utf-8-sig"), TEXT)
        self.assertIn(b"%%EOF", data)

    def test_a_long_ramble_paginates(self) -> None:
        long_text = "\n".join(f"Line number {i} of the very long ramble." for i in range(200))
        data = render_pdf(long_text, WHEN)
        self.assertGreaterEqual(len(PdfReader(BytesIO(data)).pages), 2)

    def test_special_characters_never_break_either_format(self) -> None:
        tricky = 'He said "cost < revenue & (profit)" loudly'
        docx = render_docx(tricky, WHEN)
        with zipfile.ZipFile(BytesIO(docx)) as archive:
            document = archive.read("word/document.xml").decode("utf-8")
        self.assertIn("&lt;", document)
        self.assertIn("&amp;", document)
        pdf = render_pdf(tricky, WHEN)
        self.assertIn('cost < revenue & (profit)', PdfReader(BytesIO(pdf)).pages[0].extract_text())

    def test_every_advertised_format_renders(self) -> None:
        for fmt, extension in (("markdown", "md"), ("word", "docx"), ("pdf", "pdf"), ("text", "txt")):
            with self.subTest(fmt=fmt):
                data, ext = render(TEXT, fmt, WHEN)
                self.assertEqual(ext, extension)
                self.assertGreater(len(data), 40)

    def test_document_title_keeps_the_meaning_of_prices_and_punctuation(self) -> None:
        title = "Le coût est 3 425,75 €."
        data = render_pdf(title + "\nDetails follow.", WHEN)
        self.assertTrue(PdfReader(BytesIO(data)).pages[0].extract_text().startswith(title))
        with zipfile.ZipFile(BytesIO(render_docx(title, WHEN))) as archive:
            self.assertIn(title, archive.read("word/document.xml").decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
