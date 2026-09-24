"""Finish stable local speech during capture; reuse only unambiguous results."""
from __future__ import annotations

import copy
import hashlib
import json
import re
import threading
from dataclasses import replace
from typing import Any, Callable
from urllib.parse import urlparse

from .text_pipeline import ProcessedText, normalize_spaces, prepare_dictation


_STRUCTURE = re.compile(
    r"\b(?:scratch|strike|delete|remove|undo|start over|never ?mind|forget|ignore|"
    r"actually|correction|instead|first|second|third|finally|bullet|numbered|"
    r"paragraph|new line|next line|press enter|hit enter)\b", re.I)
_CONTINUATION = re.compile(r"^(?:and|but|or|because|which|that|who|whose|with|without|then)\b", re.I)


def _key(config: dict[str, Any]) -> str:
    # The digest stays in RAM. Never put config, credentials or text in logs.
    return hashlib.sha256(json.dumps(config, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def _eligible(raw: str, config: dict[str, Any]) -> bool:
    from .llm import resolved_llm_provider, llm_settings

    cleanup = config.get("cleanup", {})
    if not cleanup.get("smart_format", True) or cleanup.get("level") == "none":
        return False
    if cleanup.get("format_mode", "auto") not in {"auto", "ai"}:
        return False
    if resolved_llm_provider(config) != "ollama" or len(raw.split()) <= 24:
        return False
    settings = llm_settings(config)
    base = (str(settings.get("api_base", "")).strip() if settings.get("provider") != "auto" else "") or "http://127.0.0.1:11434"
    if urlparse(base).hostname not in {"127.0.0.1", "localhost", "::1"}:
        return False
    # A future read of the clipboard/date may differ; evaluating a snippet now
    # would also create an unexpected clipboard read while the mic is open.
    if any("{" in str(item.get("text", "")) for item in config.get("snippets", []) if isinstance(item, dict)):
        return False
    return True


def _joinable(source: str, output: str, suffix: str, config: dict[str, Any]) -> bool:
    from .formatting import needs_intelligence

    if config.get("cleanup", {}).get("tone"):
        return False
    if not source.endswith((".", "?", "!")) or not output.endswith((".", "?", "!")):
        return False
    if any(mark in source + output + suffix for mark in ("\n", "`", '"', "(", ")", "[", "]")):
        return False
    if re.search(r"\b(?:mr|mrs|ms|dr|st|prof|vs|etc|e\.g|i\.e)\.$", source, re.I):
        return False
    if not suffix or not suffix[0].isupper() or len(suffix.split()) > 24 or _CONTINUATION.search(suffix):
        return False
    return not (_STRUCTURE.search(source + " " + suffix) or needs_intelligence(source + " " + suffix))


class ProgressiveFormatter:
    """One active job and one coalesced pending job, with session invalidation.

    Taking a result never waits. Exact matches are reusable; prefix reuse needs
    a complete sentence and a short independent tail. Anything uncertain uses
    the normal full pipeline. Neither this worker nor a completion callback
    can paste text, run user plugins, or write a formatting-journal entry.
    """

    def __init__(self, formatter: Callable[[str, dict[str, Any]], ProcessedText] | None = None):
        self._formatter = formatter or prepare_dictation
        self._lock = threading.Lock()
        self._idle = threading.Event()
        self._idle.set()
        self._generation = 0
        self._pending = None
        self._ready = None
        self._running = False

    def reset(self) -> None:
        with self._lock:
            self._generation += 1
            self._pending = None
            self._ready = None

    def request(self, raw: str, config: dict[str, Any]) -> None:
        try:
            if not _eligible(raw, config):
                return
            frozen = copy.deepcopy(config)
            key = _key(frozen)
        except (TypeError, ValueError, AttributeError):
            return
        with self._lock:
            self._pending = (self._generation, raw, key, frozen)
            if self._running:
                return
            self._running = True
            self._idle.clear()
            threading.Thread(target=self._run, name="TalkDatFormatAhead", daemon=True).start()

    def _run(self) -> None:
        while True:
            with self._lock:
                job, self._pending = self._pending, None
                if job is None:
                    self._running = False
                    self._idle.set()
                    return
            generation, raw, key, config = job
            try:
                result = self._formatter(raw, config)
            except Exception:
                result = None
            with self._lock:
                if generation == self._generation and isinstance(result, ProcessedText):
                    self._ready = (raw, key, result)

    def take(self, raw: str, config: dict[str, Any]) -> ProcessedText | None:
        with self._lock:
            ready = self._ready
            self._generation += 1
            self._ready = self._pending = None
        if ready is None:
            return None
        source, key, result = ready
        try:
            if key != _key(config):
                return None
        except (TypeError, ValueError):
            return None
        if raw == source:
            return replace(result, route="prepared_" + result.route)
        if not raw.startswith(source + " ") or result.send_enter:
            return None
        suffix = raw[len(source):].strip()
        if not _joinable(source, result.text, suffix, config):
            return None
        tail = prepare_dictation(suffix, config, local_only=True)
        return ProcessedText(normalize_spaces(raw), result.text + " " + tail.text,
                             tail.send_enter, "prepared_prefix_" + result.route, result.notice or tail.notice)

    def wait_idle(self, timeout: float) -> bool:
        """Bounded synchronization for diagnostics/tests; delivery never calls it."""
        return self._idle.wait(timeout)
