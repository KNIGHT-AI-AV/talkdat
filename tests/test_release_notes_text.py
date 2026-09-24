from __future__ import annotations

import unittest

from knight_flow.release_notes import readable_release_notes


class ReadableReleaseNotesTests(unittest.TestCase):
    """Release notes arrive as GitHub Markdown and are shown in a plain Text
    widget, so `##` and `**` appeared literally. Someone deciding whether to
    install should be able to read what changed without visiting a browser."""

    def test_headings_become_readable_lines(self) -> None:
        out = readable_release_notes("## Settings was broken\n\nDetails here.")
        self.assertNotIn("##", out)
        self.assertIn("SETTINGS WAS BROKEN", out)

    def test_bold_and_italic_markers_are_removed(self) -> None:
        out = readable_release_notes("This is **important** and *subtle*.")
        self.assertNotIn("*", out)
        self.assertIn("important", out)
        self.assertIn("subtle", out)

    def test_bullets_keep_their_shape(self) -> None:
        out = readable_release_notes("- first thing\n- second thing")
        self.assertIn("first thing", out)
        self.assertEqual(out.count("•"), 2, "bullets should read as bullets")

    def test_inline_code_keeps_its_text(self) -> None:
        out = readable_release_notes("Set `STRIPE_LIVE_MODE` to true.")
        self.assertIn("STRIPE_LIVE_MODE", out)
        self.assertNotIn("`", out)

    def test_links_keep_the_words_not_the_url(self) -> None:
        out = readable_release_notes("See [the guide](https://example.com/x) for more.")
        self.assertIn("the guide", out)
        self.assertNotIn("https://example.com/x", out)

    def test_blockquote_warnings_survive(self) -> None:
        """The broken-build warning is a blockquote; losing it would hide the
        most important line in the notes."""
        out = readable_release_notes("> Do not install this build\n\nrest")
        self.assertIn("Do not install this build", out)

    def test_horizontal_rules_do_not_become_noise(self) -> None:
        out = readable_release_notes("one\n\n---\n\ntwo")
        self.assertNotIn("---", out)

    def test_empty_notes_say_something_useful(self) -> None:
        for value in ("", "   ", None):
            self.assertTrue(readable_release_notes(value).strip())

    def test_it_does_not_collapse_everything_onto_one_line(self) -> None:
        out = readable_release_notes("## A\n\n- one\n- two\n\n## B\n\n- three")
        self.assertGreaterEqual(len(out.splitlines()), 5)

    def test_very_long_notes_are_trimmed_with_a_pointer(self) -> None:
        """A dialog is not a webpage; twenty screens of scroll is not readable."""
        out = readable_release_notes(
            "\n".join(f"- a reasonably wordy changelog entry number {i}" for i in range(400))
        )
        self.assertLess(len(out), 6000)
        self.assertIn("full release notes", out.lower())


if __name__ == "__main__":
    unittest.main()
