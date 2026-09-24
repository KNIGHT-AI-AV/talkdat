"""X-203: a retention limit that one of the two transcript files ignored.

History keeps dictations in two places. `history.jsonl` is the searchable one
and it has always honoured `privacy.history_limit`. `full-transcript-history.txt`
is the SAME dictations in plain text, written beside it on every single
dictation, and no code path in the product ever removed a line from it.

So somebody who set "keep 50" got 50 in one file and every word they had ever
spoken in the other, with nothing in the app to tell them and nothing in the UI
to reach it. On the founder's own machine it reached 1.4 MB covering ten weeks
of dictation, in plain text, in a folder that survives an uninstall.

The size ceiling is the second bound and it is the one that matters for almost
everybody: `history_limit` ships as 0, meaning unlimited, so without it the
default install accumulates forever.

WHAT THIS CANNOT PROVE: that the bytes are unrecoverable afterwards. This
rewrites the file rather than shredding it, and on an SSD the old extents may
persist until they are reused. That is stated rather than implied -- the claim
here is bounded retention, not secure erasure.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from knight_flow.app import (
    FULL_HISTORY_BANNER,
    FULL_HISTORY_MAX_BYTES,
    split_full_history,
    trim_full_history,
)


def entry(number: int, body: str = "") -> str:
    """One record in exactly the shape append_full_history writes."""
    return (
        "\n" + FULL_HISTORY_BANNER + "\n"
        + f"2026-08-19 12:00:00 - entry\n"
        + FULL_HISTORY_BANNER + "\n"
        + f"\nFinal / pasted:\ndictation number {number}{body}\n"
    )


class TheLogIsBoundedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.path = Path(tempfile.mkdtemp()) / "full-transcript-history.txt"

    def write(self, count: int, body: str = "") -> None:
        self.path.write_text("".join(entry(i, body) for i in range(count)), encoding="utf-8")

    def text(self) -> str:
        return self.path.read_text(encoding="utf-8")

    def test_the_users_retention_limit_is_obeyed(self) -> None:
        self.write(40)
        trim_full_history(self.path, {"privacy": {"history_limit": 5}})
        self.assertEqual(len(split_full_history(self.text())), 5)

    def test_it_keeps_the_NEWEST_entries(self) -> None:
        """The half a count assertion cannot see. Keeping the right NUMBER of
        the wrong records is what the original phase bug did, and it reads as
        working from every angle except this one."""
        self.write(40)
        trim_full_history(self.path, {"privacy": {"history_limit": 3}})
        kept = self.text()
        self.assertIn("dictation number 39", kept)
        self.assertIn("dictation number 37", kept)
        self.assertNotIn("dictation number 36", kept)
        self.assertNotIn("dictation number 0", kept)

    def test_trimming_twice_does_not_drift_out_of_phase(self) -> None:
        """Every entry begins with a newline before its banner. Strip that and
        the next split pairs each body with the FOLLOWING header, so the file
        quietly starts keeping halves of two different dictations."""
        self.write(20)
        trim_full_history(self.path, {"privacy": {"history_limit": 6}})
        self.path.write_text(self.text() + entry(100) + entry(101), encoding="utf-8")
        trim_full_history(self.path, {"privacy": {"history_limit": 3}})
        records = split_full_history(self.text())
        self.assertEqual(len(records), 3)
        for record in records:
            with self.subTest(record=record[:60]):
                self.assertEqual(
                    record.count("Final / pasted:"), 1,
                    "a record carries text from more than one dictation",
                )
        self.assertIn("dictation number 101", self.text())

    def test_the_default_install_is_still_bounded_by_size(self) -> None:
        """history_limit ships as 0. Without this the shipped default is an
        unbounded plaintext record of everything the person has ever said."""
        big = "x" * 50_000
        self.write(200, body=big)
        self.assertGreater(self.path.stat().st_size, FULL_HISTORY_MAX_BYTES)
        trim_full_history(self.path, {"privacy": {"history_limit": 0}})
        self.assertLessEqual(self.path.stat().st_size, FULL_HISTORY_MAX_BYTES)

    def test_a_small_unlimited_log_is_left_completely_alone(self) -> None:
        """Trimming is a deletion. It must not happen to somebody who asked for
        unlimited and is nowhere near the ceiling."""
        self.write(10)
        before = self.text()
        trim_full_history(self.path, {"privacy": {"history_limit": 0}})
        self.assertEqual(self.text(), before)

    def test_a_missing_or_unparsable_file_is_not_an_error(self) -> None:
        """This runs on the delivery path of every dictation. It must never be
        the reason a transcript fails to record."""
        trim_full_history(self.path, {"privacy": {"history_limit": 5}})
        self.path.write_text("not the expected shape at all", encoding="utf-8")
        trim_full_history(self.path, {"privacy": {"history_limit": 5}})
        self.assertEqual(self.text(), "not the expected shape at all")

    def test_one_record_is_never_trimmed_to_nothing(self) -> None:
        """A single entry larger than the ceiling would otherwise empty the
        file, losing the dictation that was just delivered."""
        self.write(1, body="y" * (FULL_HISTORY_MAX_BYTES + 1000))
        trim_full_history(self.path, {"privacy": {"history_limit": 0}})
        self.assertIn("dictation number 0", self.text())


class TheTrimIsWiredIntoTheWritePathTests(unittest.TestCase):
    """A trim nothing calls is the same as no trim, and that is precisely the
    state this file exists to end."""

    def test_appending_a_dictation_also_bounds_the_log(self) -> None:
        source = Path(__file__).resolve().parents[1] / "knight_flow" / "app.py"
        text = source.read_text(encoding="utf-8")
        start = text.index("def append_full_history")
        body = text[start:text.index("\n    def ", start + 10)]
        self.assertIn(
            "trim_full_history(path, self.config)", body,
            "the log is appended to but never bounded",
        )


if __name__ == "__main__":
    unittest.main()
