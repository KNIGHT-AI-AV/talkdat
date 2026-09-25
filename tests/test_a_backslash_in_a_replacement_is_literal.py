"""P0-1 (find-more sweep): a backslash in the person's own replacement text is text.

`replace_phrase` handed the "Replace with" text of a dictionary entry, and the
expansion of a snippet, to `re.sub` as a template. A template reads a backslash
as an escape, so `D:\\Work\\notes` or `\\\\server\\share` raised "bad escape" on
every take, even when the phrase was never said, and every dictation ended in
"Could not finish dictation". `C:\\new\\temp` did not raise: it pasted a real
newline and tab. The Words page accepts backslashes, so a Windows path was
enough to break the app.
"""

from __future__ import annotations

import unittest

from knight_flow.text_pipeline import apply_dictionary, apply_snippets, replace_phrase


def _dictionary(target: str) -> dict:
    return {"dictionary": {"replacements": [{"from": "my folder", "to": target}]}}


class ABackslashInAReplacementIsLiteral(unittest.TestCase):
    TARGETS = (
        r"C:\Users\Name",
        r"\\server\share",
        r"C:\new\temp",
        r"\1 and \g<0>",
        "ends with a backslash \\",
    )

    def test_each_target_is_pasted_exactly_as_written(self) -> None:
        for target in self.TARGETS:
            with self.subTest(target=target):
                self.assertEqual(
                    apply_dictionary("open my folder now", _dictionary(target)),
                    f"open {target} now",
                )

    def test_an_entry_that_was_not_said_leaves_the_take_alone(self) -> None:
        # The failure was not limited to takes that used the entry: the bad
        # template raised on every take, so one entry broke all dictation.
        for target in self.TARGETS:
            with self.subTest(target=target):
                self.assertEqual(
                    apply_dictionary("nothing to replace here", _dictionary(target)),
                    "nothing to replace here",
                )

    def test_backslash_n_stays_two_characters(self) -> None:
        out = replace_phrase("open my folder", "my folder", r"C:\new\temp")
        self.assertNotIn("\n", out)
        self.assertNotIn("\t", out)
        self.assertEqual(out, r"open C:\new\temp")

    def test_a_snippet_inside_a_sentence_keeps_its_backslashes(self) -> None:
        config = {"snippets": [{"trigger": "share path", "text": r"\\server\share\team"}]}
        self.assertEqual(
            apply_snippets("save it to share path please", config),
            r"save it to \\server\share\team please",
        )

    def test_a_snippet_said_alone_keeps_its_backslashes(self) -> None:
        config = {"snippets": [{"trigger": "home dir", "text": r"C:\Users\Name"}]}
        self.assertEqual(apply_snippets("home dir", config), r"C:\Users\Name")

    def test_case_of_the_match_does_not_change_the_target(self) -> None:
        self.assertEqual(
            replace_phrase("My Folder and MY FOLDER", "my folder", r"D:\Data"),
            r"D:\Data and D:\Data",
        )


if __name__ == "__main__":
    unittest.main()
