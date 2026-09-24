"""Document integrity, grapheme boundaries and packaged-export fixture checks."""

from __future__ import annotations

import os
import re
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from pypdf import PdfReader
from knight_flow import pdf_documents, pdf_export_smoke
from knight_flow.ramble_export import PDF_TEMPLATES
from knight_flow.export_report import _DESIGN

SOURCE = "Le coût est 3 425,75 €.\n请在星期五之前完成。\nمرحبا بالعالم\nनमस्ते दुनिया\n👨‍👩‍👧‍👦 👍🏿\n<script>alert(1)</script> & (profit)"


def render(text, spec=None, report=False):
    return pdf_documents.render_document(
        text,
        title="Document acceptance",
        meta="Talk DAT!",
        spec=spec or PDF_TEMPLATES["executive"],
        report=report,
    )


def original(data):
    return (
        PdfReader(BytesIO(data), strict=True)
        .attachments["dictated-text.txt"][0]
        .decode("utf-8-sig")
    )


def logical_rows(data):
    rows = []
    for page in PdfReader(BytesIO(data), strict=True).pages:
        for value in re.findall(
            rb"/ActualText <([0-9A-F]+)>", page.get_contents().get_data()
        ):
            rows.append(
                bytes.fromhex(value.decode()).decode("utf-16-be").removeprefix("\ufeff")
            )
    return rows


class UnicodeDocuments(unittest.TestCase):
    def test_every_style_preserves_original_text_and_logical_characters(self):
        for report, styles in ((False, PDF_TEMPLATES), (True, _DESIGN)):
            for name, spec in styles.items():
                with self.subTest(report=report, style=name):
                    data = render(SOURCE, spec, report)
                    self.assertEqual(original(data), SOURCE)
                    rows = "\n".join(logical_rows(data))
                    for line in SOURCE.splitlines():
                        self.assertIn(line, rows)

    def test_source_preserves_spacing_and_line_endings(self):
        text = "\n  Café\t€  12.50\r\n\n请完成。 👨‍👩‍👧‍👦\n"
        self.assertEqual(original(render(text)), text)

    def test_empty_source_is_a_valid_document_with_an_empty_attachment(self):
        self.assertEqual(original(render("")), "")

    def test_unspaced_joined_emoji_wrap_only_between_whole_graphemes(self):
        family = "👨‍👩‍👧‍👦"
        text = family * 140
        rows = [
            row for row in logical_rows(render(text)) if "👨" in row or "\u200d" in row
        ]
        self.assertEqual("".join(rows), text)
        self.assertTrue(all(row.replace(family, "") == "" for row in rows))

    def test_many_distinct_emoji_fit_without_overflowing_the_color_font(self):
        with pdf_documents.Document() as probe:
            self.assertTrue(probe._load_font("emoji"))
            choices = [
                chr(code)
                for code in probe.fonts["emoji"].cmap
                if pdf_documents.EMOJI.search(chr(code))
            ][:270]
        self.assertEqual(len(choices), 270)
        text = " ".join(choices)
        data = render(text)
        self.assertEqual(original(data), text)
        rows = "".join(logical_rows(data))
        for character in choices:
            self.assertIn(character, rows)

    def test_long_link_retains_all_characters_across_lines(self):
        text = "https://example.test/" + "abcXYZ123" * 160
        rows = [
            row
            for row in logical_rows(render(text))
            if "abcXYZ123" in row or "https://" in row
        ]
        self.assertEqual("".join(rows), text)

    def test_long_report_keeps_every_paragraph_and_numbered_footer(self):
        text = "The complete report paragraph. " * 1100
        data = render(text, _DESIGN["boardroom"], True)
        self.assertEqual(original(data), text)
        rows = logical_rows(data)
        body = "".join(
            row
            for row in rows
            if "complete report" in row or row.strip() == "paragraph."
        )
        self.assertEqual(body, text)
        reader = PdfReader(BytesIO(data))
        self.assertGreater(len(reader.pages), 2)
        for number, page in enumerate(reader.pages, 1):
            self.assertIn(f"Page {number} of {len(reader.pages)}", page.extract_text())

    def test_missing_fonts_fail_with_a_lossless_alternative(self):
        with patch.object(pdf_documents, "font_paths", return_value={}):
            with self.assertRaisesRegex(ValueError, "Word or text"):
                render("Keep these words")

    def test_missing_glyph_is_explicit_instead_of_a_question_mark(self):
        with self.assertRaisesRegex(ValueError, "matching system font"):
            render("Keep this \U0010ffff")

    def test_unsupported_control_characters_do_not_make_a_lossy_pdf(self):
        for value in ("a\x00b", "a\ud800b"):
            with (
                self.subTest(value=repr(value)),
                self.assertRaisesRegex(ValueError, "control character"),
            ):
                render(value)

    def test_oversize_document_is_rejected_before_font_work(self):
        with self.assertRaisesRegex(ValueError, "too large"):
            render("a" * 1_000_001)

    def test_export_fixture_uses_only_its_explicit_private_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary) / "proof"
            with patch.dict(os.environ, TALK_DAT_EXPORT_SMOKE_DIR=str(folder)):
                pdf_export_smoke.run()
            import json

            receipt = json.loads((folder / "receipt.json").read_text())
            self.assertTrue(receipt["success"])
            self.assertEqual(len(receipt["files"]), 6)
            source = (folder / "source.txt").read_text(encoding="utf-8")
            for file in receipt["files"]:
                path = folder / file["name"]
                self.assertEqual(path.stat().st_size, file["bytes"])
                if path.suffix == ".pdf":
                    self.assertEqual(original(path.read_bytes()), source)

    def test_export_fixture_refuses_to_overwrite_an_existing_directory(self):
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.dict(os.environ, TALK_DAT_EXPORT_SMOKE_DIR=temporary),
        ):
            with self.assertRaises(FileExistsError):
                pdf_export_smoke.run()


if __name__ == "__main__":
    unittest.main()
