from __future__ import annotations

import json
import logging
import math
import sqlite3
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any

from .config import app_dir, history_db_path, history_path


log = logging.getLogger(__name__)


HISTORY_BACKENDS = ("jsonl", "sqlite")

COMMON_WORDS = frozenset(
    "the and for with that this from have will your you are was were has had can could would should "
    "about just like into over under then than them they their there here when what where which while "
    "been being our out not but all any some more most very much many each other after before because "
    "his her him she he it its is am be do does did done get got make made go went come came say said "
    "see saw know knew think thought take took good great new old big small first last next one two "
    "three today tomorrow yesterday please thanks thank hello okay yes no maybe also really still "
    "monday tuesday wednesday thursday friday saturday sunday january february march april may june "
    "july august september october november december".split()
)

_COLUMNS = ("type", "text", "original", "command", "transform", "url", "send_enter", "created_at")

_SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at REAL NOT NULL,
    type TEXT NOT NULL DEFAULT 'entry',
    text TEXT NOT NULL DEFAULT '',
    original TEXT NOT NULL DEFAULT '',
    command TEXT NOT NULL DEFAULT '',
    transform TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    send_enter INTEGER NOT NULL DEFAULT 0,
    extra TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_history_created_at ON history(created_at);
"""

_sqlite_lock = threading.Lock()


class JsonlHistoryStore:
    backend = "jsonl"

    def append(self, entry: dict[str, Any]) -> None:
        path = history_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(entry, ensure_ascii=True) + "\n")

    def recent(self, limit: int = 100) -> list[dict[str, Any]]:
        path = history_path()
        if not path.exists():
            return []
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            # An unreadable history file presents as an empty history, which
            # looks exactly like a working install that has never been used.
            log.warning("could not read history at %s", path, exc_info=True)
            return []
        entries: list[dict[str, Any]] = []
        for line in lines[-max(1, limit):]:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                entries.append(item)
        return entries

    def last_text(self) -> str:
        for entry in reversed(self.recent(500)):
            text = str(entry.get("text", "")).strip()
            if text:
                return text
        return ""

    def search(self, query: str, limit: int = 100) -> list[dict[str, Any]]:
        needle = query.strip().lower()
        if not needle:
            return self.recent(limit)
        matches = [
            entry
            for entry in self.recent(10000)
            if needle in str(entry.get("text", "")).lower()
            or needle in str(entry.get("original", "")).lower()
            or needle in str(entry.get("command", "")).lower()
        ]
        return matches[-max(1, limit):]

    def trim(self, limit: int) -> None:
        if limit <= 0:
            return
        path = history_path()
        if not path.exists():
            return
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
            if len(lines) > limit:
                path.write_text("\n".join(lines[-limit:]) + "\n", encoding="utf-8")
        except OSError:
            pass

    def clear(self) -> None:
        path = history_path()
        if path.exists():
            path.write_text("", encoding="utf-8")


class SqliteHistoryStore:
    backend = "sqlite"

    def _connect(self) -> sqlite3.Connection:
        path = history_db_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path, timeout=5)
        connection.execute("PRAGMA journal_mode=WAL")
        # X-234: "Clear text history" left the words recoverable.
        #
        # SQLite's default is to mark a deleted row's pages free and move on,
        # so the text stays in the file until something else happens to reuse
        # that space. On the one screen somebody visits specifically to make a
        # transcript go away, "deleted" meant "not shown".
        #
        # secure_delete overwrites freed pages as they are released. Stated
        # rather than implied: this bounds what the FILE contains, not what the
        # DISK contains. On flash storage the old blocks may survive until the
        # controller reuses them, and no application-level pragma changes that.
        connection.execute("PRAGMA secure_delete=ON")
        connection.executescript(_SQLITE_SCHEMA)
        return connection

    @contextmanager
    def _session(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        """Yield a connection and always close it again.

        sqlite3's own context manager commits or rolls back but never closes, so
        `with self._connect() as connection` leaked one open connection and one file
        handle per history operation. That accumulates across a dictation session and
        keeps the database file locked on Windows.
        """
        connection = self._connect()
        try:
            if write:
                with connection:
                    yield connection
            else:
                yield connection
        finally:
            connection.close()

    def append(self, entry: dict[str, Any]) -> None:
        extra = {key: value for key, value in entry.items() if key not in _COLUMNS}
        with _sqlite_lock, self._session(write=True) as connection:
            connection.execute(
                "INSERT INTO history (created_at, type, text, original, command, transform, url, send_enter, extra)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    float(entry.get("created_at") or time.time()),
                    str(entry.get("type", "entry")),
                    str(entry.get("text", "")),
                    str(entry.get("original", "")),
                    str(entry.get("command", "")),
                    str(entry.get("transform", "")),
                    str(entry.get("url", "")),
                    1 if entry.get("send_enter") else 0,
                    json.dumps(extra, ensure_ascii=True),
                ),
            )

    def recent(self, limit: int = 100) -> list[dict[str, Any]]:
        with _sqlite_lock, self._session() as connection:
            rows = connection.execute(
                "SELECT created_at, type, text, original, command, transform, url, send_enter, extra"
                " FROM history ORDER BY id DESC LIMIT ?",
                (max(1, limit),),
            ).fetchall()
        return [self._row_to_entry(row) for row in reversed(rows)]

    def last_text(self) -> str:
        with _sqlite_lock, self._session() as connection:
            row = connection.execute(
                "SELECT text FROM history WHERE TRIM(text) != '' ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return str(row[0]).strip() if row else ""

    def search(self, query: str, limit: int = 100) -> list[dict[str, Any]]:
        needle = query.strip()
        if not needle:
            return self.recent(limit)
        pattern = f"%{needle}%"
        with _sqlite_lock, self._session() as connection:
            rows = connection.execute(
                "SELECT created_at, type, text, original, command, transform, url, send_enter, extra"
                " FROM history WHERE text LIKE ? OR original LIKE ? OR command LIKE ?"
                " ORDER BY id DESC LIMIT ?",
                (pattern, pattern, pattern, max(1, limit)),
            ).fetchall()
        return [self._row_to_entry(row) for row in reversed(rows)]

    def trim(self, limit: int) -> None:
        if limit <= 0:
            return
        with _sqlite_lock, self._session(write=True) as connection:
            connection.execute(
                "DELETE FROM history WHERE id NOT IN (SELECT id FROM history ORDER BY id DESC LIMIT ?)",
                (limit,),
            )

    def clear(self) -> None:
        with _sqlite_lock, self._session(write=True) as connection:
            connection.execute("DELETE FROM history")
        # VACUUM cannot run inside a transaction, and _session opens one, so it
        # goes here on its own connection AFTER the delete has committed.
        #
        # DELETE only frees the pages. VACUUM is what gives them back and
        # rewrites the file without them: skip it and the database keeps both
        # its old size and its old contents, which is the entire complaint.
        with _sqlite_lock:
            connection = self._connect()
            try:
                connection.execute("VACUUM")
            except sqlite3.OperationalError:
                # A vacuum blocked by another reader is a housekeeping miss,
                # not a failed deletion: the rows are already gone and
                # secure_delete has already overwritten their pages.
                log.debug("history vacuum skipped", exc_info=True)
            finally:
                connection.close()

    def import_jsonl_once(self) -> None:
        with _sqlite_lock, self._session() as connection:
            count = connection.execute("SELECT COUNT(*) FROM history").fetchone()[0]
        if count:
            return
        for entry in JsonlHistoryStore().recent(10000):
            try:
                self.append(entry)
            except sqlite3.Error:
                return

    @staticmethod
    def _row_to_entry(row: tuple[Any, ...]) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "created_at": row[0],
            "type": row[1],
            "text": row[2],
            "original": row[3],
            "command": row[4],
            "transform": row[5],
            "url": row[6],
            "send_enter": bool(row[7]),
        }
        try:
            extra = json.loads(row[8])
        except (json.JSONDecodeError, TypeError):
            extra = {}
        if isinstance(extra, dict):
            for key, value in extra.items():
                entry.setdefault(key, value)
        return {key: value for key, value in entry.items() if value not in ("", None)}


def history_backend(config: dict[str, Any]) -> str:
    backend = str(config.get("privacy", {}).get("history_backend", "jsonl")).strip().lower()
    return backend if backend in HISTORY_BACKENDS else "jsonl"


def create_history_store(config: dict[str, Any]) -> JsonlHistoryStore | SqliteHistoryStore:
    if history_backend(config) == "sqlite":
        store = SqliteHistoryStore()
        try:
            store.import_jsonl_once()
            return store
        except sqlite3.Error:
            # Silently handing back the other backend means someone who chose
            # SQLite in Settings gets JSONL, keeps the setting, and has no way
            # to find out why search behaves differently.
            log.warning("sqlite history unavailable; falling back to JSONL", exc_info=True)
            return JsonlHistoryStore()
    return JsonlHistoryStore()


def clear_all_history() -> None:
    JsonlHistoryStore().clear()
    if history_db_path().exists():
        try:
            SqliteHistoryStore().clear()
        except sqlite3.Error:
            # Someone asked to delete their transcripts and some of them are
            # still on disk. Silence here is the one that matters most in this
            # file: the person believes their history is gone.
            log.error("failed to clear the sqlite history; transcripts may remain", exc_info=True)


def clear_saved_text() -> list[str]:
    """Find-more P0-6: everything "Clear text history" deletes, in one place.

    Both Clear buttons (web shell and Tk) cleared History, the full transcript
    file and the drafts, but left the raw and finished text of every take in
    the formatting journal and in each protected recording's metadata, and the
    Tk one said "History cleared." even when a store could not be cleared.
    This clears every store of dictated text except pins, which the dialog
    says it keeps; recordings keep their audio and lose their words.

    Returns what could not be cleared, in plain words. Empty means all of it.
    """
    from .audio_spool import blank_safety_transcripts
    from .config import full_history_path, live_draft_path, recovered_draft_path
    from .format_journal import journal_path

    failed: list[str] = []
    try:
        JsonlHistoryStore().clear()
    except OSError:
        log.error("failed to clear the history file", exc_info=True)
        failed.append("the history file")
    if history_db_path().exists():
        try:
            SqliteHistoryStore().clear()
        except (sqlite3.Error, OSError):
            log.error("failed to clear the sqlite history; transcripts may remain", exc_info=True)
            failed.append("the searchable history")
    for label, path in (("the full transcript file", full_history_path()), ("the live draft", live_draft_path()),
                        ("the recovered draft", recovered_draft_path())):
        try:
            if path.exists():
                path.write_text("", encoding="utf-8")
        except OSError:
            log.error("failed to clear %s", path.name, exc_info=True)
            failed.append(label)
    journal = journal_path()
    for path in (journal, journal.with_suffix(".jsonl.1")):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            log.error("failed to delete %s", path.name, exc_info=True)
            if "the formatting journal" not in failed:
                failed.append("the formatting journal")
    if blank_safety_transcripts():
        failed.append("the words saved with some recordings")
    return failed


def pinned_path():
    return app_dir() / "pinned.json"


def pinned_entries() -> list[dict[str, Any]]:
    path = pinned_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [entry for entry in data if isinstance(entry, dict)] if isinstance(data, list) else []


def pin_text(text: str) -> None:
    text = str(text).strip()
    if not text:
        return
    entries = pinned_entries()
    if any(entry.get("text") == text for entry in entries):
        return
    entries.append({"text": text, "created_at": time.time()})
    pinned_path().write_text(json.dumps(entries, ensure_ascii=True, indent=2), encoding="utf-8")


def unpin_text(text: str) -> None:
    entries = [entry for entry in pinned_entries() if entry.get("text") != text]
    pinned_path().write_text(json.dumps(entries, ensure_ascii=True, indent=2), encoding="utf-8")


def _activity_datetime(value):
    if type(value) not in (int, float):
        return None
    try:
        return datetime.fromtimestamp(value) if math.isfinite(value) else None
    except (ValueError, OverflowError, OSError):
        log.debug('Saved activity timestamp cannot be represented on this computer', exc_info=True)
        return None


def history_stats(config):
    rows = create_history_store(config).recent(20001)
    capped = len(rows) > 20000
    entries = [row for row in rows[-20000:] if isinstance(row, dict)]
    today = datetime.fromtimestamp(time.time()).date()
    words = dictated_words = dictations = unknown_dates = 0
    days, by_type, day_words = {}, {}, {}
    spoken_days = set()
    dictation_types = {'dictation', 'recovered_dictation', 'entry'}
    for entry in entries:
        text = entry.get('text')
        count = len(text.split()) if isinstance(text, str) else 0
        words += count
        kind = str(entry.get('type', 'entry'))
        by_type[kind] = by_type.get(kind, 0) + 1
        spoken = kind in dictation_types
        if spoken:
            dictated_words += count
            dictations += 1
        created = _activity_datetime(entry.get('created_at'))
        if created is None:
            unknown_dates += 1
            continue
        day = created.date().isoformat()
        days[day] = days.get(day, 0) + 1
        day_words[day] = day_words.get(day, 0) + (count if spoken else 0)
        if spoken:
            spoken_days.add(day)
    streak = 0
    probe = today
    while probe.isoformat() in days:
        streak += 1
        probe -= timedelta(days=1)
    minutes_saved = max(0.0, dictated_words / 40 - dictated_words / 150)
    week = []
    for offset in range(6, -1, -1):
        date = (today - timedelta(days=offset)).isoformat()
        week.append({'date': date, 'entries': days.get(date, 0),
                     'dictated_words': day_words.get(date, 0)})
    return {
        'entries': len(entries), 'words': words, 'active_days': len(days),
        'streak_days': streak, 'minutes_saved': round(minutes_saved),
        'by_type': by_type, 'busiest_day': max(days, key=days.get) if days else '',
        'today': days.get(today.isoformat(), 0), 'dictations': dictations,
        'dictated_words': dictated_words, 'unknown_dates': unknown_dates,
        'daily': week, 'capped': capped, 'limit': 20000,
        'dictation_active_days': len(spoken_days),
    }



def suggest_vocabulary(config: dict[str, Any], existing: list[str], limit: int = 20) -> list[str]:
    known = {str(word).strip().lower() for word in existing}
    counts: dict[str, int] = {}
    for entry in create_history_store(config).recent(5000):
        for token in str(entry.get("text", "")).split():
            word = token.strip(".,!?;:()[]\"'")
            if len(word) < 4 or not word[0].isupper() or not word.isalpha():
                continue
            lower = word.lower()
            if lower in COMMON_WORDS or lower in known:
                continue
            counts[word] = counts.get(word, 0) + 1
    frequent = [word for word, count in counts.items() if count >= 3]
    frequent.sort(key=lambda word: -counts[word])
    return frequent[:limit]


def _subtitle_lines(text, width=42):
    """Wrap at grapheme boundaries; whitespace becomes subtitle line spacing."""
    import regex
    clusters = regex.findall(r'\X', ' '.join(text.split()))
    start = 0
    while start < len(clusters):
        cut = min(start + width, len(clusters))
        if cut < len(clusters):
            space = next((i for i in range(cut, start, -1) if clusters[i] == ' '), start)
            if space > start:
                cut = space
        line = ''.join(clusters[start:cut]).strip()
        if line:
            yield line
        start = cut
        while start < len(clusters) and clusters[start] == ' ':
            start += 1


def _subtitle_stamp(milliseconds):
    seconds, fraction = divmod(milliseconds, 1000)
    minutes, second = divmod(seconds, 60)
    hours, minute = divmod(minutes, 60)
    return f'{hours:02}:{minute:02}:{second:02},{fraction:03}'


def export_history_document(config, fmt='md'):
    """Publish a complete bounded history export and return its saved receipt.

    Subtitle drafts have estimated relative cues. History has no audio alignment.
    Text and Markdown retain each nonblank entry's original whitespace.
    """
    from .export_files import save_new_export

    rows = create_history_store(config).recent(20001)
    capped = len(rows) > 20000
    entries = [row for row in rows[-20000:] if isinstance(row, dict)
               and isinstance(row.get('text'), str) and row['text'].strip()]
    if not entries:
        raise ValueError('No saved text is available to export. Refresh History and try again.')
    fmt = fmt if fmt in {'md', 'txt', 'srt'} else 'md'
    lines = []
    unknown_dates = 0
    if fmt == 'srt':
        import itertools
        cursor, cue = 0, 0
        for entry in entries:
            wrapped = iter(_subtitle_lines(entry['text']))
            while block := list(itertools.islice(wrapped, 2)):
                cue += 1
                duration = max(1500, min(6000, round(sum(len(line) for line in block) / 15 * 1000)))
                lines.extend([str(cue), f'{_subtitle_stamp(cursor)} --> {_subtitle_stamp(cursor + duration)}', *block, ''])
                cursor += duration
    else:
        if fmt == 'md':
            lines.append(f"# Talk DAT! history export - {time.strftime('%Y-%m-%d %H:%M')}\n")
        if capped:
            lines.append('Includes the most recent 20,000 saved entries. Older entries remain in History.\n')
        for entry in entries:
            created = _activity_datetime(entry.get('created_at'))
            unknown_dates += created is None
            stamp = created.strftime('%Y-%m-%d %H:%M') if created else 'Date unavailable'
            text = entry['text']
            if fmt == 'md':
                kind = str(entry.get('type') or 'entry').replace('_', ' ').replace('\n', ' ').replace('\r', ' ')
                lines.append(f'## {stamp} - {kind}\n\n{text}\n')
            else:
                lines.append(f'[{stamp}]\n{text}\n')
    stamp = time.strftime('%Y%m%d-%H%M%S')
    title = 'subtitle-draft' if fmt == 'srt' else 'history'
    path = save_new_export(app_dir() / 'exports', f'talk-dat-{title}-{stamp}.{fmt}', ('\n'.join(lines) + '\n').encode('utf-8'))
    return {'path': path, 'entries': len(entries), 'capped': capped, 'limit': 20000,
            'format': fmt, 'estimated_timing': fmt == 'srt', 'unknown_dates': unknown_dates}


def export_history(config: dict[str, Any], fmt: str = 'md'):
    return export_history_document(config, fmt)['path']
