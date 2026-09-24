"""X-29: mirror every delivered dictation into a Markdown folder.

Mayowa's conditions were "space, logistics, and processing" -- all trivial by
design: one append per delivery to a per-day file, no background scanning, no
indexing, off by default. Point it at an Obsidian vault and every dictation
becomes a note without the app knowing what Obsidian is.
"""

from __future__ import annotations

import datetime as _dt
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger("talkdat.export")


def export_folder(config: dict[str, Any]) -> Path | None:
    """The user's chosen folder, or None when the feature is off (default)."""
    raw = str((config.get("export", {}) or {}).get("markdown_folder", "") or "").strip()
    if not raw:
        return None
    return Path(raw).expanduser()


def daily_note_path(folder: Path, when: _dt.datetime) -> Path:
    return folder / f"{when:%Y-%m-%d}.md"


def format_entry(text: str, when: _dt.datetime) -> str:
    """One list item per dictation; multi-line dictations indent under it so
    the file stays valid, readable Markdown."""
    body = str(text or "").strip()
    if not body:
        return ""
    lines = body.splitlines()
    first = f"- **{when:%H:%M}** {lines[0]}"
    rest = [f"  {line}" if line.strip() else "" for line in lines[1:]]
    return "\n".join([first, *rest]) + "\n"


def append_dictation(config: dict[str, Any], text: str, *, now: _dt.datetime | None = None) -> bool:
    """Best-effort, never raises toward delivery: a failed export must never
    cost the words that were already pasted."""
    folder = export_folder(config)
    if folder is None:
        return False
    when = now or _dt.datetime.now()
    entry = format_entry(text, when)
    if not entry:
        return False
    try:
        folder.mkdir(parents=True, exist_ok=True)
        path = daily_note_path(folder, when)
        fresh = not path.exists()
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            if fresh:
                handle.write(f"# Talk DAT!, {when:%A, %B %d, %Y}\n\n")
            handle.write(entry)
        return True
    except Exception:
        log.debug("markdown export failed", exc_info=True)
        return False
