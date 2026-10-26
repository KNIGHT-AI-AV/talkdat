"""T5: import a glossary the person chose, after showing exactly what it adds.

Talk DAT already imports its own JSON vocabulary packs (packs.py), all at once.
A person setting up a project usually has something plainer: a list of names in
a text file, a spreadsheet column, a terminology sheet exported as CSV. This
reads ONE such file the person picked, proposes terms from it, and shows the
preview before anything is stored:

* new terms, ready to add;
* duplicates (in the file twice, or already in the dictionary);
* conflicts (sounds like a term already there, spelled differently -- the
  matcher would refuse to choose between them, so the person must);
* rejected lines, each with its reason (a sentence, a link, a path, a secret,
  too many words, nothing to say).

Only the terms the person accepts are stored, each tagged with the import it
came from. Removing that import removes exactly those entries and nothing else.
The file's text is never kept: not the rejected lines, not the file itself --
only the accepted terms and the import's name.

No connectors, no folders, no documents: one plain text or CSV file.
"""

from __future__ import annotations

import csv
import io
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterable

MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_LINES = 5000
MAX_TERM_WORDS = 5
_HEADER_TERM = {"term", "terms", "word", "words", "name", "names", "spelling", "glossary"}
_HEADER_HEARD = {"sounds like", "sounds_like", "heard as", "aliases", "alias", "pronounced"}
_URL_RE = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
_PATH_RE = re.compile(r"(?:^[A-Za-z]:\\|^\\\\|^/[^\s/]+/|[\\/][^\s\\/]+[\\/])")


@dataclass(frozen=True)
class Candidate:
    text: str
    sounds_like: tuple[str, ...]
    line: int
    status: str            # "new", "duplicate", "known", "conflict", "rejected"
    reason: str = ""
    conflicts_with: str = ""


@dataclass
class Preview:
    source_name: str
    candidates: list[Candidate] = field(default_factory=list)

    def of(self, status: str) -> list[Candidate]:
        return [candidate for candidate in self.candidates if candidate.status == status]


def _reject(text: str) -> str:
    """Why a line is not a term, or ""."""
    from .learned_words import looks_like_a_secret

    stripped = text.strip()
    if not stripped:
        return "empty"
    if _URL_RE.search(stripped):
        return "a link"
    if _PATH_RE.search(stripped):
        return "a file path"
    # A password or key is one token; "Hemoglobin A1c" is a term with a space.
    if " " not in stripped and looks_like_a_secret(stripped):
        return "looks like a password or key"
    if len(stripped.split()) > MAX_TERM_WORDS:
        return "a sentence, not a term"
    if re.search(r"[.!?]$", stripped) and len(stripped.split()) > 2:
        return "a sentence, not a term"
    if any(ord(character) < 32 for character in stripped):
        return "contains control characters"
    if not re.search(r"[A-Za-z0-9]", stripped):
        return "no letters or digits"
    return ""


def _rows(raw: str, filename: str) -> Iterable[tuple[int, str, tuple[str, ...]]]:
    """(line number, term, sounds-like) from plain text or CSV."""
    is_csv = filename.lower().endswith((".csv", ".tsv")) or ("," in raw.splitlines()[0] if raw.strip() else False)
    if is_csv:
        dialect = csv.excel_tab if filename.lower().endswith(".tsv") or "\t" in raw.splitlines()[0] else csv.excel
        reader = csv.reader(io.StringIO(raw), dialect)
        term_column, heard_column = 0, None
        for number, row in enumerate(reader, start=1):
            if number > MAX_LINES:
                break
            cells = [cell.strip() for cell in row]
            if number == 1 and cells and cells[0].lower() in _HEADER_TERM:
                for index, cell in enumerate(cells):
                    if cell.lower() in _HEADER_TERM:
                        term_column = index
                    elif cell.lower() in _HEADER_HEARD:
                        heard_column = index
                continue
            if not cells or term_column >= len(cells):
                yield number, "", ()
                continue
            heard = ()
            if heard_column is not None and heard_column < len(cells):
                heard = tuple(part.strip() for part in re.split(r"[;|/]", cells[heard_column]) if part.strip())
            yield number, cells[term_column], heard
        return
    for number, line in enumerate(raw.splitlines(), start=1):
        if number > MAX_LINES:
            break
        if line.lstrip().startswith("#"):
            continue
        term, _, heard = line.partition("|")
        yield number, term.strip(), tuple(part.strip() for part in heard.split(",") if part.strip())


def read_file(path: str) -> tuple[str, str]:
    """(text, name) of the one file the person picked. Bounded and decoded
    strictly enough that a binary file is refused rather than imported."""
    from pathlib import Path

    target = Path(path)
    if target.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("Choose a glossary smaller than 2 MB.")
    raw = target.read_bytes()
    if b"\x00" in raw[:4096]:
        raise ValueError("That file is not plain text or CSV.")
    try:
        text = raw.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError:
        # The decoder's own message names bytes and offsets; the person gets the plain one.
        raise ValueError("That file is not plain text or CSV.") from None
    return text.replace("\r\n", "\n").replace("\r", "\n"), target.name


def preview(config: dict[str, Any], raw: str, *, source_name: str, project: dict[str, Any] | None = None) -> Preview:
    from .vocabulary import parse_terms

    dictionary = config.get("dictionary", {}) if isinstance(config, dict) else {}
    holders = list(dictionary.get("words") or []) + list(dictionary.get("terms") or [])
    if project:
        holders += list(project.get("words") or []) + list(project.get("terms") or [])
    existing = parse_terms(holders)
    known = {term.text.casefold() for term in existing}
    keys = {}
    for term in existing:
        for key in term.keys():
            keys.setdefault(key, term.text)
    result = Preview(source_name=source_name)
    seen: set[str] = set()
    for number, text, heard in _rows(raw, source_name):
        reason = _reject(text)
        if reason:
            if reason != "empty":
                result.candidates.append(Candidate(text[:80], (), number, "rejected", reason))
            continue
        folded = text.casefold()
        if folded in seen:
            result.candidates.append(Candidate(text, heard, number, "duplicate", "in the file twice"))
            continue
        seen.add(folded)
        if folded in known:
            result.candidates.append(Candidate(text, heard, number, "known", "already in your words"))
            continue
        parsed = parse_terms([{"text": text, "sounds_like": list(heard)}])
        clash = next((keys[key] for key in (parsed[0].keys() if parsed else ()) if key in keys), "")
        if clash and clash.casefold() != folded:
            result.candidates.append(Candidate(text, heard, number, "conflict",
                                               "sounds like a word you already have", clash))
            continue
        result.candidates.append(Candidate(text, heard, number, "new"))
    return result


def import_accepted(config: dict[str, Any], plan: Preview, accepted: Iterable[str], *,
                    project: dict[str, Any] | None = None) -> dict[str, Any]:
    """Store only the accepted terms (new or conflict the person resolved),
    tagged with this import. Returns the import's record."""
    wanted = {str(text).casefold() for text in accepted}
    source = {"id": uuid.uuid4().hex[:12], "name": plan.source_name,
              "imported_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "count": 0}
    holder = project if project else config.setdefault("dictionary", {})
    created_terms = "terms" not in holder
    target = holder.setdefault("terms", [])
    for candidate in plan.candidates:
        if candidate.status not in ("new", "conflict") or candidate.text.casefold() not in wanted:
            continue
        target.append({"text": candidate.text, "sounds_like": list(candidate.sounds_like),
                       "source": {"id": source["id"], "name": plan.source_name}})
        source["count"] += 1
    if source["count"]:
        record = dict(source)
        if project:
            record["project"] = project.get("id", "")
        if created_terms:
            record["created_terms"] = True
        config.setdefault("dictionary", {}).setdefault("imports", []).append(record)
    elif created_terms:
        del holder["terms"]
    return source


def imports(config: dict[str, Any]) -> list[dict[str, Any]]:
    dictionary = config.get("dictionary", {}) if isinstance(config, dict) else {}
    return [record for record in dictionary.get("imports") or [] if isinstance(record, dict)]


def remove_import(config: dict[str, Any], source_id: str) -> int:
    """Remove exactly the entries one import added, and its record. Returns how many."""
    dictionary = config.get("dictionary", {}) if isinstance(config, dict) else {}
    holders = [dictionary.get("terms") or []]
    holders += [project.get("terms") or [] for project in dictionary.get("projects") or [] if isinstance(project, dict)]
    removed = 0
    for terms in holders:
        for entry in list(terms):
            if isinstance(entry, dict) and isinstance(entry.get("source"), dict) and entry["source"].get("id") == source_id:
                terms.remove(entry)
                removed += 1
    records = dictionary.get("imports") or []
    for record in list(records):
        if isinstance(record, dict) and record.get("id") == source_id:
            records.remove(record)
            if record.get("created_terms"):
                # The import made the list it filled; an exact undo removes it too.
                holder = next((project for project in dictionary.get("projects") or []
                               if isinstance(project, dict) and project.get("id") == record.get("project")),
                              None) if record.get("project") else dictionary
                if isinstance(holder, dict) and holder.get("terms") == []:
                    del holder["terms"]
    if "imports" in dictionary and not dictionary["imports"]:
        del dictionary["imports"]
    return removed
