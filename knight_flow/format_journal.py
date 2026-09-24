"""X-125: the formatting journal -- raw vs delivered, per dictation, LOCAL.

The founder's order: "I want to see where the formatting is fucking up...
the formatting before and after and what it did." This file answers that
without touching X-37 (content never leaves the machine): an OPT-IN JSONL
on this PC, default OFF, that records each dictation's raw transcript and
the text each pass delivered. Reviewing it is how formatting bugs become
reproducible instead of anecdotal.

Privacy contract: written only when diagnostics.formatting_journal is
true; lives beside the config; capped and self-rotating. Feedback may attach
an excerpt only with explicit consent. The shared form previews the exact
excerpt before sending; this journal never uploads itself.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

JOURNAL_NAME = "formatting-journal.jsonl"
MAX_BYTES = 5 * 1024 * 1024  # rotate at 5MB; one .1 backup kept


def journal_enabled(config: dict[str, Any]) -> bool:
    return bool(config.get("diagnostics", {}).get("formatting_journal", False))


def journal_path() -> Path:
    from .config import app_dir

    return app_dir() / JOURNAL_NAME


def journal_tail(max_entries: int = 40, max_bytes: int = 48_000) -> str:
    """The newest entries, sized to ride inside a feedback POST (the server
    accepts 64KB total, so the log leaves room for the message around it).
    Returns "" when there is nothing to attach -- callers use that to decide
    whether the consent checkbox has anything to offer."""
    try:
        path = journal_path()
        if not path.exists():
            return ""
        with path.open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - max_bytes * 2))
            raw = handle.read().decode("utf-8", "replace")
        lines = [line for line in raw.splitlines() if line.strip()]
        if size > max_bytes * 2 and lines:
            lines = lines[1:]  # first line is almost certainly a torn entry
        tail = lines[-max_entries:]
        while tail and len("\n".join(tail).encode("utf-8")) > max_bytes:
            tail = tail[1:]
        return "\n".join(tail)
    except Exception:
        log.debug("formatting journal tail unavailable", exc_info=True)
        return ""


def record_formatting(
    config: dict[str, Any],
    *,
    raw: str,
    final: str,
    stage: str,
    intensity: str = "standard",
    route: str = "",
    elapsed_ms: float = 0.0,
    reason: str = "",
) -> None:
    """Append one entry. Never raises; a diagnostics write must not cost a
    dictation."""
    if not journal_enabled(config):
        return
    try:
        path = journal_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > MAX_BYTES:
            backup = path.with_suffix(".jsonl.1")
            backup.unlink(missing_ok=True)
            path.rename(backup)
        entry = {
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "stage": stage,  # "paste" (speculative rules) or "refine" (model)
            "intensity": intensity,
            "route": route,
            "ms": round(float(elapsed_ms), 1),
            # Why a model answer was refused, as a validator reason code.
            "reason": str(reason or ""),
            "raw": raw,
            "final": final,
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        log.debug("formatting journal write skipped", exc_info=True)
