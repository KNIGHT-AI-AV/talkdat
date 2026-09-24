from __future__ import annotations

import datetime as dt
import tempfile
import unittest
import zipfile
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree

from knight_flow import export_files, export_report, ramble_export

WHEN = dt.datetime(2026, 9, 19, 12, 30)


class CompleteExports(unittest.TestCase):
    def test_concurrent_saves_get_distinct_names_and_complete_content(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            contents = [f"document {i}\n".encode() * 1000 for i in range(16)]
            with ThreadPoolExecutor(max_workers=8) as workers:
                paths = list(workers.map(lambda data: export_files.save_new_export(folder, "report.pdf", data), contents))
            self.assertEqual(len(set(paths)), 16)
            self.assertEqual([path.read_bytes() for path in paths], contents)
            self.assertEqual(set(folder.iterdir()), set(paths))

    def test_original_is_never_replaced(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            original = folder / "report.pdf"
            original.write_bytes(b"already shared")
            result = export_files.save_new_export(folder, "report.pdf", b"new")
            self.assertEqual(original.read_bytes(), b"already shared")
            self.assertEqual(result.name, "report (2).pdf")
            self.assertEqual(result.read_bytes(), b"new")

    def test_only_complete_file_is_published(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            publish = export_files._publish_new
            observed = []

            def inspect(staged, target):
                self.assertFalse(target.exists())
                observed.append(staged.read_bytes())
                return publish(staged, target)

            data = b"all words\n" * 10000
            with patch.object(export_files, "_publish_new", side_effect=inspect):
                target = export_files.save_new_export(folder, "report.txt", data)
            self.assertEqual(observed, [data])
            self.assertEqual(target.read_bytes(), data)

    def test_failed_flush_leaves_no_incomplete_document(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            with patch.object(export_files.os, "fsync", side_effect=OSError("disk full")):
                with self.assertRaisesRegex(OSError, "disk full"):
                    export_files.save_new_export(folder, "report.txt", b"words")
            self.assertEqual(list(folder.iterdir()), [])

    def test_failed_publication_preserves_existing_files_and_cleans_temporary(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            prior = folder / "prior.txt"
            prior.write_bytes(b"prior")
            with patch.object(export_files, "_publish_new", side_effect=PermissionError("locked")):
                with self.assertRaisesRegex(PermissionError, "locked"):
                    export_files.save_new_export(folder, "report.txt", b"words")
            self.assertEqual(list(folder.iterdir()), [prior])
            self.assertEqual(prior.read_bytes(), b"prior")

    def test_filename_cannot_escape_the_chosen_folder(self):
        with tempfile.TemporaryDirectory() as temporary:
            for name in ("", ".", "..", "../report.txt", "nested/report.txt", "..\\report.txt", "report\x00.txt"):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    export_files.save_new_export(Path(temporary), name, b"words")
            self.assertEqual(list(Path(temporary).iterdir()), [])

    def test_cleanup_does_not_hide_the_original_storage_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(export_files.os, "fsync", side_effect=OSError("disk full")), patch.object(Path, "unlink", side_effect=PermissionError("scan in progress")):
                with self.assertLogs(export_files.log, level="WARNING"), self.assertRaisesRegex(OSError, "disk full"):
                    export_files.save_new_export(Path(temporary), "report.txt", b"words")

    def test_cleanup_does_not_report_a_complete_export_as_failed(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(Path, "unlink", side_effect=PermissionError("scan in progress")):
                with self.assertLogs(export_files.log, level="WARNING"):
                    path = export_files.save_new_export(Path(temporary), "report.txt", b"all words")
            self.assertEqual(path.read_bytes(), b"all words")

    def test_same_minute_rambles_both_survive(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(ramble_export, "ramble_folder", return_value=Path(temporary)):
            first = ramble_export.save_ramble("Same title\nfirst", "text", WHEN)
            original = first.read_bytes()
            second = ramble_export.save_ramble("Same title\nsecond", "text", WHEN)
            self.assertNotEqual(first, second)
            self.assertEqual(first.read_bytes(), original)
            self.assertIn(b"second", second.read_bytes())

    def test_same_second_reports_both_survive(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(export_report.time, "strftime", return_value="20260919-123000"):
            first = export_report.export_report_pdf("first", out_dir=Path(temporary))
            original = first.read_bytes()
            second = export_report.export_report_pdf("second", out_dir=Path(temporary))
            self.assertNotEqual(first, second)
            self.assertEqual(first.read_bytes(), original)


class WordAndTextContent(unittest.TestCase):
    @staticmethod
    def body(text):
        with zipfile.ZipFile(BytesIO(ramble_export.render_docx(text, WHEN))) as archive:
            root = ElementTree.fromstring(archive.read("word/document.xml"))
        namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        paragraphs = root.findall(f"{namespace}body/{namespace}p")[2:]
        return ["".join("\t" if node.tag == namespace + "tab" else node.text or "" for node in p.iter() if node.tag in {namespace + "t", namespace + "tab"}) for p in paragraphs]

    def test_blank_paragraphs_and_indentation_are_preserved(self):
        self.assertEqual(self.body("\nfirst\n\n  last\n"), ["", "first", "", "  last", ""])

    def test_tabs_have_word_tab_elements(self):
        self.assertEqual(self.body("one\ttwo\tthree"), ["one\ttwo\tthree"])

    def test_line_endings_become_paragraphs_without_extra_blank_lines(self):
        self.assertEqual(self.body("one\r\ntwo\rthree"), ["one", "two", "three"])

    def test_unicode_and_literal_markup_are_text(self):
        text = '请完成。 مرحبا नमस्ते 👨‍👩‍👧‍👦 <script> & "quote"'
        self.assertEqual(self.body(text), [text])

    def test_unsupported_word_control_characters_fail_without_silent_loss(self):
        for text in ("a\x00b", "a\x01b", "a\ud800b"):
            with self.subTest(text=repr(text)), self.assertRaisesRegex(ValueError, "plain text"):
                ramble_export.render_docx(text, WHEN)

    def test_text_and_markdown_keep_the_original_body(self):
        text = "\n  first\tcolumn\n\n最后 👍🏿  \n"
        for render in (ramble_export.render_text, ramble_export.render_markdown):
            with self.subTest(format=render.__name__):
                self.assertTrue(render(text, WHEN).decode("utf-8").endswith(text + "\n"))

    def test_unicode_titles_remain_readable(self):
        self.assertEqual(ramble_export._title_from("季度计划\nbody"), "季度计划")
        self.assertEqual(ramble_export._title_from("L’équipe prépare le café"), "L’équipe prépare le café")


if __name__ == "__main__":
    unittest.main()
