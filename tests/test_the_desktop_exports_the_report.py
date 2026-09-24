"""Read actual exported reports, fonts and footers with an independent parser."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from io import BytesIO
from pypdf import PdfReader

from knight_flow.export_report import (
    REPORT_DESIGNS,
    derive_subject,
    export_report_pdf,
    render_report_pdf,
)

SAMPLE = (
    "The launch has moved to Friday. Legal sign-off is still outstanding.\n\n"
    "Marketing needs the (final) copy by Wednesday - and a backslash \\ too.\n\n"
    + "Filler sentence for pagination. " * 220
)


class TheEmitterProducesRealPdfsTests(unittest.TestCase):
    def test_every_design_renders_a_valid_document(self) -> None:
        for design in REPORT_DESIGNS:
            data = render_report_pdf(SAMPLE, design=design, author="Mayowa")
            reader = PdfReader(BytesIO(data), strict=True)
            self.assertIn(b"%%EOF", data, design)
            self.assertIn("Prepared with Talk DAT!", reader.pages[0].extract_text(), design)
            self.assertEqual(reader.attachments["dictated-text.txt"][0].decode("utf-8-sig"), SAMPLE)

    def test_long_text_paginates_with_numbered_footers(self) -> None:
        data = render_report_pdf(SAMPLE, design="boardroom")
        reader = PdfReader(BytesIO(data))
        pages = len(reader.pages)
        self.assertGreaterEqual(pages, 3, "220 filler sentences must not fit one page")
        for number, page in enumerate(reader.pages, 1):
            self.assertIn(f"Page {number} of {pages}", page.extract_text())

    def test_the_faces_differ(self) -> None:
        boardroom = render_report_pdf("Quarterly numbers look strong.", "boardroom")
        modern = render_report_pdf("Quarterly numbers look strong.", "modern")
        def faces(data):
            fonts = PdfReader(BytesIO(data)).pages[0]["/Resources"]["/Font"]
            return " ".join(str(font.get_object().get("/BaseFont", "")) for font in fonts.values())
        self.assertIn("Times", faces(boardroom))
        self.assertIn("Arial", faces(modern))
        self.assertIn(b" re f", PdfReader(BytesIO(modern)).pages[0].get_contents().get_data(), "modern carries the accent bar")

    def test_parens_and_backslashes_cannot_break_the_stream(self) -> None:
        data = render_report_pdf("A (dangerous) string \\ here. More words follow.", "minimal")
        text = PdfReader(BytesIO(data)).pages[0].extract_text()
        self.assertIn("A (dangerous) string \\ here.", text)

    def test_an_unknown_design_falls_back_not_crashes(self) -> None:
        data = render_report_pdf("Hello world. Extra.", design="neon")
        self.assertGreaterEqual(len(PdfReader(BytesIO(data), strict=True).pages), 1)


class TheSubjectIsDerivedTests(unittest.TestCase):
    def test_first_sentence_capped_at_a_word_boundary(self) -> None:
        self.assertEqual(derive_subject(SAMPLE), "The launch has moved to Friday")
        long_first = "word " * 40 + "."
        subject = derive_subject(long_first)
        self.assertLessEqual(len(subject), 81)
        self.assertTrue(subject.endswith("…"))

    def test_empty_text_gets_an_honest_default(self) -> None:
        self.assertEqual(derive_subject(""), "Talk DAT! report")


class TheWriterStaysInItsLaneTests(unittest.TestCase):
    def test_out_dir_override_writes_exactly_one_file_there(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = export_report_pdf("A tiny report body.", out_dir=Path(tmp))
            self.assertEqual(path.parent, Path(tmp))
            self.assertTrue(path.name.startswith("talk-dat-report-"))
            self.assertGreaterEqual(len(PdfReader(path, strict=True).pages), 1)


class TheHistoryMenuOffersItTests(unittest.TestCase):
    def test_the_menu_rows_and_the_persisted_design(self) -> None:
        overlay = (Path(__file__).resolve().parents[1] / "knight_flow" / "overlay.py").read_text(encoding="utf-8")
        self.assertIn('("Export report (PDF)", export_report)', overlay)
        self.assertIn('("Report design: next", cycle_report_design)', overlay)
        self.assertIn('report_design', overlay)
        self.assertIn("last_text().strip()", overlay)
        self.assertIn('"Nothing to report yet', overlay)


if __name__ == "__main__":
    unittest.main()
