from __future__ import annotations

import json
import os
import pathlib
import tempfile
import time
import unittest

from knight_flow import history as history_module
from knight_flow.config import history_path
from knight_flow.history import (
    JsonlHistoryStore,
    SqliteHistoryStore,
    clear_all_history,
    create_history_store,
    export_history,
    history_backend,
    history_stats,
    pin_text,
    pinned_entries,
    suggest_vocabulary,
    unpin_text,
)

JSONL_CONFIG: dict = {}
SQLITE_CONFIG = {"privacy": {"history_backend": "sqlite"}}


class HistoryTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        previous = os.environ.get("TALK_DAT_HOME")
        os.environ["TALK_DAT_HOME"] = self.home.name

        def restore() -> None:
            if previous is None:
                os.environ.pop("TALK_DAT_HOME", None)
            else:
                os.environ["TALK_DAT_HOME"] = previous

        self.addCleanup(restore)

    def stores(self) -> list:
        return [JsonlHistoryStore(), SqliteHistoryStore()]


class BackendSelectionTests(HistoryTestCase):
    def test_jsonl_is_the_default(self) -> None:
        self.assertEqual(history_backend({}), "jsonl")
        self.assertIsInstance(create_history_store({}), JsonlHistoryStore)

    def test_sqlite_is_selected_when_configured(self) -> None:
        self.assertEqual(history_backend(SQLITE_CONFIG), "sqlite")
        self.assertIsInstance(create_history_store(SQLITE_CONFIG), SqliteHistoryStore)

    def test_an_unknown_backend_falls_back_instead_of_failing(self) -> None:
        self.assertEqual(history_backend({"privacy": {"history_backend": "postgres"}}), "jsonl")
        self.assertEqual(history_backend({"privacy": {"history_backend": "  SQLITE  "}}), "sqlite")


class StoreBehaviourTests(HistoryTestCase):
    def test_entries_round_trip_in_order(self) -> None:
        for store in self.stores():
            with self.subTest(backend=store.backend):
                store.clear()
                store.append({"text": "first", "created_at": 1000.0})
                store.append({"text": "second", "created_at": 2000.0})
                texts = [entry.get("text") for entry in store.recent(10)]
                self.assertEqual(texts, ["first", "second"])

    def test_last_text_skips_blank_entries(self) -> None:
        for store in self.stores():
            with self.subTest(backend=store.backend):
                store.clear()
                store.append({"text": "real transcript", "created_at": 1000.0})
                store.append({"text": "   ", "created_at": 2000.0})
                self.assertEqual(store.last_text(), "real transcript")

    def test_last_text_is_empty_on_a_fresh_profile(self) -> None:
        for store in self.stores():
            with self.subTest(backend=store.backend):
                store.clear()
                self.assertEqual(store.last_text(), "")

    def test_search_matches_text_original_and_command(self) -> None:
        for store in self.stores():
            with self.subTest(backend=store.backend):
                store.clear()
                store.append({"text": "buy milk", "created_at": 1000.0})
                store.append({"text": "unrelated", "original": "buy bread", "created_at": 2000.0})
                store.append({"text": "nothing", "command": "buy stamps", "created_at": 3000.0})
                store.append({"text": "totally different", "created_at": 4000.0})
                self.assertEqual(len(store.search("buy")), 3)
                self.assertEqual(len(store.search("nonexistent")), 0)

    def test_an_empty_search_returns_recent_entries(self) -> None:
        for store in self.stores():
            with self.subTest(backend=store.backend):
                store.clear()
                store.append({"text": "one", "created_at": 1000.0})
                self.assertEqual(len(store.search("   ")), 1)

    def test_trim_keeps_only_the_newest_entries(self) -> None:
        for store in self.stores():
            with self.subTest(backend=store.backend):
                store.clear()
                for index in range(10):
                    store.append({"text": f"entry {index}", "created_at": 1000.0 + index})
                store.trim(3)
                remaining = [entry.get("text") for entry in store.recent(50)]
                self.assertEqual(remaining, ["entry 7", "entry 8", "entry 9"])

    def test_trim_with_a_non_positive_limit_is_a_no_op(self) -> None:
        for store in self.stores():
            with self.subTest(backend=store.backend):
                store.clear()
                store.append({"text": "keep me", "created_at": 1000.0})
                store.trim(0)
                self.assertEqual(len(store.recent(10)), 1)

    def test_clear_empties_the_store(self) -> None:
        for store in self.stores():
            with self.subTest(backend=store.backend):
                store.append({"text": "temporary", "created_at": 1000.0})
                store.clear()
                self.assertEqual(store.recent(10), [])


class JsonlSpecificTests(HistoryTestCase):
    def test_a_corrupt_line_never_hides_the_rest_of_the_history(self) -> None:
        store = JsonlHistoryStore()
        store.append({"text": "before", "created_at": 1000.0})
        with history_path().open("a", encoding="utf-8") as file:
            file.write("{not valid json\n")
        store.append({"text": "after", "created_at": 2000.0})
        self.assertEqual([entry.get("text") for entry in store.recent(10)], ["before", "after"])

    def test_recent_on_a_missing_file_is_empty(self) -> None:
        self.assertEqual(JsonlHistoryStore().recent(10), [])


class SqliteSpecificTests(HistoryTestCase):
    def test_unknown_fields_survive_in_the_extra_column(self) -> None:
        store = SqliteHistoryStore()
        store.clear()
        store.append({"text": "hello", "created_at": 1000.0, "route": "clipboard", "duration": 2.5})
        entry = store.recent(1)[0]
        self.assertEqual(entry["route"], "clipboard")
        self.assertEqual(entry["duration"], 2.5)

    def test_send_enter_round_trips_as_a_boolean(self) -> None:
        store = SqliteHistoryStore()
        store.clear()
        store.append({"text": "with enter", "created_at": 1000.0, "send_enter": True})
        self.assertIs(store.recent(1)[0]["send_enter"], True)

    def test_existing_jsonl_history_is_imported_once(self) -> None:
        JsonlHistoryStore().append({"text": "legacy entry", "created_at": 1000.0})
        store = SqliteHistoryStore()
        store.import_jsonl_once()
        self.assertEqual([entry.get("text") for entry in store.recent(10)], ["legacy entry"])

        # A second import must not duplicate what is already stored.
        store.import_jsonl_once()
        self.assertEqual(len(store.recent(10)), 1)


class SqliteConnectionLifetimeTests(HistoryTestCase):
    def test_every_operation_closes_the_connection_it_opened(self) -> None:
        """sqlite3's context manager commits but does not close.

        Relying on it leaked one connection and file handle per history operation,
        which accumulates across a dictation session and keeps the database locked on
        Windows. Every open must be matched by a close.
        """
        import sqlite3

        opened: list[sqlite3.Connection] = []
        real_connect = sqlite3.connect

        def counting_connect(*args, **kwargs):
            connection = real_connect(*args, **kwargs)
            opened.append(connection)
            return connection

        sqlite3.connect = counting_connect
        self.addCleanup(lambda: setattr(sqlite3, "connect", real_connect))

        store = SqliteHistoryStore()
        store.append({"text": "one", "created_at": 1000.0})
        store.append({"text": "two", "created_at": 2000.0})
        store.recent(10)
        store.search("one")
        store.last_text()
        store.trim(5)
        store.clear()

        self.assertGreaterEqual(len(opened), 7, "expected one connection per operation")
        still_open = []
        for connection in opened:
            try:
                connection.execute("SELECT 1")
                still_open.append(connection)
            except sqlite3.ProgrammingError:
                pass
        self.assertEqual(still_open, [], f"{len(still_open)} sqlite connections were left open")


class ClearAllTests(HistoryTestCase):
    def test_clearing_removes_both_backends(self) -> None:
        JsonlHistoryStore().append({"text": "jsonl entry", "created_at": 1000.0})
        SqliteHistoryStore().append({"text": "sqlite entry", "created_at": 1000.0})
        clear_all_history()
        self.assertEqual(JsonlHistoryStore().recent(10), [])
        self.assertEqual(SqliteHistoryStore().recent(10), [])


class PinnedTests(HistoryTestCase):
    def test_pinning_is_idempotent_and_removable(self) -> None:
        pin_text("remember this")
        pin_text("remember this")
        self.assertEqual([entry["text"] for entry in pinned_entries()], ["remember this"])
        unpin_text("remember this")
        self.assertEqual(pinned_entries(), [])

    def test_blank_text_is_never_pinned(self) -> None:
        pin_text("   ")
        self.assertEqual(pinned_entries(), [])

    def test_a_corrupt_pinned_file_reads_as_empty(self) -> None:
        history_module.pinned_path().write_text("{ not json", encoding="utf-8")
        self.assertEqual(pinned_entries(), [])


class StatsTests(HistoryTestCase):
    def test_counts_words_entries_and_time_saved(self) -> None:
        store = create_history_store(JSONL_CONFIG)
        now = time.time()
        store.append({"text": "one two three four five", "created_at": now, "type": "entry"})
        store.append({"text": "six seven eight", "created_at": now, "type": "command"})
        stats = history_stats(JSONL_CONFIG)
        self.assertEqual(stats["entries"], 2)
        self.assertEqual(stats["words"], 8)
        self.assertEqual(stats["by_type"], {"entry": 1, "command": 1})
        self.assertEqual(stats["today"], 2)
        self.assertEqual(stats["streak_days"], 1)
        self.assertGreaterEqual(stats["minutes_saved"], 0)

    def test_an_empty_history_produces_zeroed_stats(self) -> None:
        stats = history_stats(JSONL_CONFIG)
        self.assertEqual(stats["entries"], 0)
        self.assertEqual(stats["words"], 0)
        self.assertEqual(stats["streak_days"], 0)
        self.assertEqual(stats["busiest_day"], "")


class VocabularyTests(HistoryTestCase):
    def test_repeated_proper_nouns_are_suggested(self) -> None:
        store = create_history_store(JSONL_CONFIG)
        for _ in range(3):
            store.append({"text": "Ping Mayowa about Knightsbridge", "created_at": time.time()})
        suggestions = suggest_vocabulary(JSONL_CONFIG, [])
        self.assertIn("Mayowa", suggestions)
        self.assertIn("Knightsbridge", suggestions)

    def test_rare_words_common_words_and_known_words_are_excluded(self) -> None:
        store = create_history_store(JSONL_CONFIG)
        for _ in range(3):
            store.append({"text": "Monday Mayowa Alvarez the and for", "created_at": time.time()})
        store.append({"text": "Onceoff mention", "created_at": time.time()})
        suggestions = suggest_vocabulary(JSONL_CONFIG, ["alvarez"])
        self.assertIn("Mayowa", suggestions)
        self.assertNotIn("Monday", suggestions, "calendar words are common vocabulary")
        self.assertNotIn("Alvarez", suggestions, "already in the dictionary")
        self.assertNotIn("Onceoff", suggestions, "seen fewer than three times")


class ExportTests(HistoryTestCase):
    def seed(self) -> None:
        store = create_history_store(JSONL_CONFIG)
        store.append({"text": "first transcript", "created_at": 1_700_000_000.0, "type": "entry"})
        store.append({"text": "", "created_at": 1_700_000_100.0, "type": "entry"})
        store.append({"text": "second transcript", "created_at": 1_700_000_200.0, "type": "entry"})

    def test_markdown_export_skips_blank_entries(self) -> None:
        self.seed()
        path = export_history(JSONL_CONFIG, "md")
        body = path.read_text(encoding="utf-8")
        self.assertTrue(path.name.endswith(".md"))
        self.assertIn("# Talk DAT! history export", body)
        self.assertIn("first transcript", body)
        self.assertIn("second transcript", body)

    def test_text_and_srt_exports_are_written(self) -> None:
        self.seed()
        text_path = export_history(JSONL_CONFIG, "txt")
        self.assertTrue(text_path.name.endswith(".txt"))
        self.assertIn("first transcript", text_path.read_text(encoding="utf-8"))

        srt_path = export_history(JSONL_CONFIG, "srt")
        srt = srt_path.read_text(encoding="utf-8")
        self.assertTrue(srt_path.name.endswith(".srt"))
        self.assertIn(" --> ", srt)
        self.assertTrue(srt.lstrip().startswith("1"))

    def test_an_unknown_format_falls_back_to_markdown(self) -> None:
        self.seed()
        self.assertTrue(export_history(JSONL_CONFIG, "docx").name.endswith(".md"))

    def test_export_never_writes_outside_the_app_directory(self) -> None:
        self.seed()
        path = export_history(JSONL_CONFIG, "md")
        self.assertEqual(path.parent.name, "exports")
        self.assertTrue(str(path).startswith(self.home.name))


class SerialisationTests(HistoryTestCase):
    def test_jsonl_entries_stay_ascii_safe_on_disk(self) -> None:
        JsonlHistoryStore().append({"text": "café — naïve", "created_at": 1000.0})
        raw = history_path().read_text(encoding="utf-8")
        self.assertNotIn("café", raw, "non-ascii should be escaped for portability")
        entry = json.loads(raw.splitlines()[0])
        self.assertEqual(entry["text"], "café — naïve")


if __name__ == "__main__":
    unittest.main()


class ClearingHistoryActuallyRemovesTheWordsTests(unittest.TestCase):
    """X-234: "Clear text history" left the transcripts recoverable.

    SQLite's default is to mark a deleted row's pages free and move on, so the
    text stayed in the file until something else happened to reuse that space.
    On the one screen somebody opens specifically to make a transcript go away,
    "deleted" meant "no longer displayed".

    Two changes: secure_delete overwrites freed pages as they are released, and
    clear() now VACUUMs so the file is rewritten without them. VACUUM cannot
    run inside a transaction, which is why it sits outside the session rather
    than beside the DELETE.

    STATED PLAINLY, because the difference matters to somebody handling
    sensitive material: this bounds what the FILE contains, not what the DISK
    contains. On flash storage the old blocks can survive until the controller
    reuses them, and no application-level pragma changes that.
    """

    def test_the_text_is_gone_from_the_file_not_just_the_query(self) -> None:
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as directory:
            database = pathlib.Path(directory) / "history.db"
            with patch("knight_flow.history.history_db_path", lambda: database):
                store = SqliteHistoryStore()
                for index in range(40):
                    store.append({"type": "dictation", "text": f"CANARYPHRASE {index}", "original": "raw"})
                self.assertIn(
                    b"CANARYPHRASE", database.read_bytes(),
                    "the fixture never wrote anything, so this test proves nothing",
                )
                store.clear()
                self.assertNotIn(
                    b"CANARYPHRASE", database.read_bytes(),
                    "cleared transcripts are still readable in the database file",
                )

    def test_secure_delete_is_on_for_every_connection(self) -> None:
        source = (pathlib.Path(__file__).resolve().parents[1] / "knight_flow" / "history.py").read_text(encoding="utf-8")
        self.assertIn('PRAGMA secure_delete=ON', source)

    def test_the_vacuum_is_outside_the_transaction(self) -> None:
        """Inside one it raises "cannot VACUUM from within a transaction", and
        the first attempt at this did exactly that."""
        source = (pathlib.Path(__file__).resolve().parents[1] / "knight_flow" / "history.py").read_text(encoding="utf-8")
        start = source.index("    def clear(self)", source.index("class SqliteHistoryStore"))
        body = source[start:source.index("\n    def ", start + 10)]
        delete_at = body.index("DELETE FROM history")
        vacuum_at = body.index("VACUUM")
        session_end = body.index("# VACUUM cannot run inside a transaction")
        self.assertLess(delete_at, session_end)
        self.assertLess(session_end, vacuum_at)

    def test_a_blocked_vacuum_is_not_a_failed_deletion(self) -> None:
        """The rows are already gone and their pages already overwritten. A
        housekeeping miss must not report the deletion as failed."""
        source = (pathlib.Path(__file__).resolve().parents[1] / "knight_flow" / "history.py").read_text(encoding="utf-8")
        self.assertIn("history vacuum skipped", source)
