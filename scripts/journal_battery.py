"""Replay THIS machine's formatting journal through today's pipeline, privately.

    .venv\\Scripts\\python.exe scripts\\journal_battery.py                 # since 2026-09-21
    .venv\\Scripts\\python.exe scripts\\journal_battery.py --since 2026-09-01 --intensity chill
    .venv\\Scripts\\python.exe scripts\\journal_battery.py --rules-only

The public corpus (tests/parity_cases*.py) is written for the repository. The
owner's own dictations are the real test, and they must never leave his PC or
enter the repository. So this script:

- reads the opt-in local journal (%APPDATA%\\TalkDat\\formatting-journal.jsonl);
- runs each raw transcript through `process_dictation` with the local engine
  only (privacy.local_only forced on, loopback Ollama, no journal writes, no
  plugins, no screen names);
- prints AGGREGATES ONLY: counts, route distribution, refusal reason codes,
  latency percentiles and structural quality counters. No transcript, no
  output text and no per-take line is ever printed or written anywhere.

It is a measuring tool for this machine, not a test: nothing imports it.
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import os
import re
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _percentile(values: list[float], share: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[max(0, math.ceil(len(ordered) * share) - 1)], 1)


def _latency(values: list[float]) -> dict:
    return {"n": len(values), "p50_ms": round(statistics.median(values), 1) if values else None,
            "p90_ms": _percentile(values, 0.9), "max_ms": round(max(values), 1) if values else None}


def _journal_entries(path: Path, since: str) -> list[dict]:
    entries = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if str(entry.get("ts", "")) >= since and str(entry.get("raw", "")).strip():
                entries.append(entry)
    return entries


def _release_overhead(log_path: Path, since: str) -> dict:
    """Release-to-delivery minus formatting, from the app log's count-only
    `dictation processed:` lines. What a take costs besides formatting
    (recognition tail, paste) -- so a new formatting time can be turned into
    an ESTIMATED release-to-final figure. The log line holds no transcript."""
    pattern = re.compile(r"^(\S+ \S+) .*dictation processed: .*?format_ms=(\d+).*?release_to_delivery_ms=([\d.]+)")
    overheads = []
    if not log_path.is_file():
        return {"n": 0}
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = pattern.match(line)
        if match and match[1] >= since:
            overheads.append(max(0.0, float(match[3]) - float(match[2])))
    return _latency(overheads)


def _structure(text: str) -> Counter:
    counts: Counter = Counter()
    counts["takes"] += 1
    counts["multi_sentence"] += len(re.findall(r"[.!?](?:\s|$)", text)) >= 2
    counts["question_mark"] += "?" in text
    counts["list"] += bool(re.search(r"(?m)^\s*(?:[-*]|\d+[.)])\s+\S", text))
    counts["paragraph_break"] += "\n\n" in text
    counts["letter_layout"] += bool(re.search(r"\n(?:Thanks|Best|Cheers|Regards|Kind regards),\n\S", text))
    counts["starts_capitalised"] += bool(re.match(r"\s*[A-Z0-9\"'(]", text))
    counts["ends_with_terminal"] += bool(re.search(r"[.!?:)\"']\s*$", text))
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--since", default="2026-09-21", help="journal timestamp lower bound (local time)")
    parser.add_argument("--limit", type=int, default=0, help="at most this many unique takes (0 = all)")
    parser.add_argument("--intensity", choices=("chill", "executive", "journal"), default="journal",
                        help="finish to request; 'journal' reuses each take's recorded intensity")
    parser.add_argument("--rules-only", action="store_true", help="measure the rules lane alone")
    args = parser.parse_args(argv)

    from knight_flow import formatting, llm
    from knight_flow.config import app_dir, load_config
    from knight_flow.text_pipeline import process_dictation

    journal = app_dir() / "formatting-journal.jsonl"
    if not journal.is_file():
        print(json.dumps({"error": "no local formatting journal on this machine"}))
        return 2
    entries = _journal_entries(journal, args.since)
    seen: set[str] = set()
    takes = []
    for entry in entries:
        raw = str(entry["raw"]).strip()
        if raw in seen:
            continue
        seen.add(raw)
        takes.append(entry)
    if args.limit > 0:
        takes = takes[-args.limit:]

    config = copy.deepcopy(load_config())
    config.setdefault("privacy", {})["local_only"] = True  # this machine only
    config.setdefault("diagnostics", {})["formatting_journal"] = False
    config.setdefault("plugins", {})["enabled"] = False
    config.setdefault("dictionary", {})["screen_context"] = False
    config.setdefault("cleanup", {})["format_mode"] = config["cleanup"].get("format_mode", "auto")
    llm_settings = config.setdefault("transforms", {}).setdefault("llm", {})
    base = str(llm_settings.get("api_base") or "http://127.0.0.1:11434")
    if not llm._is_local_ollama_base(base):
        base = "http://127.0.0.1:11434"
        llm_settings["api_base"] = base

    warm = {}
    if not args.rules_only:
        # Mirror the app's launch: warm the configured model (which measures
        # whether it is on the GPU), then the model the router will pick.
        configured = str(llm_settings.get("model") or llm.LOCAL_FORMATTER_MODEL)
        began = time.perf_counter()
        llm.warm_local_finish(base, configured, timeout=120)
        target = llm.local_finish_target(config, executive=True)[1]
        if target != configured:
            llm.warm_local_finish(base, target, timeout=120)
        warm = {"warmup_ms": round((time.perf_counter() - began) * 1000, 1), "model": target}

    routes: Counter = Counter()
    reasons: Counter = Counter()
    structure: Counter = Counter()
    draft_structure: Counter = Counter()
    safety: Counter = Counter()
    by_route_ms: dict[str, list[float]] = {}
    all_ms: list[float] = []
    words_bucket: Counter = Counter()
    changed_from_draft = 0
    for entry in takes:
        raw = str(entry["raw"])
        take_config = copy.deepcopy(config)
        intensity = args.intensity if args.intensity != "journal" else str(entry.get("intensity") or "executive")
        take_config["cleanup"]["format_intensity"] = "executive" if intensity == "executive" else "standard"
        draft = process_dictation(raw, copy.deepcopy(take_config), local_only=True).text
        started = time.perf_counter()
        processed = process_dictation(raw, take_config, local_only=args.rules_only)
        elapsed = (time.perf_counter() - started) * 1000.0
        routes[processed.route] += 1
        if getattr(processed, "rejection", ""):
            reasons[processed.rejection] += 1
        by_route_ms.setdefault(processed.route, []).append(elapsed)
        all_ms.append(elapsed)
        words = len(raw.split())
        words_bucket["<=4" if words <= 4 else "5-24" if words <= 24 else "25-60" if words <= 60 else ">60"] += 1
        structure.update(_structure(processed.text))
        draft_structure.update(_structure(draft))
        changed_from_draft += processed.text != draft
        # Facts the speech carried must survive: numeric anchors and negations.
        source_anchors = formatting._meaning_anchors(draft)
        output_anchors = formatting._meaning_anchors(processed.text)
        safety["numbers_dropped"] += bool(source_anchors - output_anchors) and not formatting.needs_intelligence(draft)
        safety["numbers_added"] += bool(output_anchors - source_anchors)
        negations_in = formatting._meaning_words(draft).get("negation", 0)
        negations_out = formatting._meaning_words(processed.text).get("negation", 0)
        safety["negation_count_changed"] += negations_in != negations_out

    history = Counter(str(entry.get("route", "")) for entry in entries)
    report = {
        "machine_only": True,
        "journal_entries_since": len(entries), "unique_takes_replayed": len(takes), "since": args.since,
        "lane": "rules" if args.rules_only else "production (local engine)", "intensity": args.intensity,
        **warm,
        "words": dict(words_bucket),
        "routes_now": dict(routes.most_common()),
        "routes_in_journal_then": dict(history.most_common()),
        "refusal_reasons": dict(reasons.most_common()),
        "formatting_latency": _latency(all_ms),
        "formatting_latency_by_route": {route: _latency(values) for route, values in by_route_ms.items()},
        "changed_from_rules_draft": changed_from_draft,
        "structure_final": dict(structure), "structure_rules_draft": dict(draft_structure),
        "safety_flags": dict(safety),
    }
    overhead = _release_overhead(app_dir() / "talk-dat.log", args.since)
    if overhead.get("n"):
        fmt = report["formatting_latency"]
        report["release_overhead_besides_formatting"] = overhead
        report["estimated_release_to_final_ms"] = {
            "p50": round(overhead["p50_ms"] + (fmt["p50_ms"] or 0), 1),
            "p90": round(overhead["p90_ms"] + (fmt["p90_ms"] or 0), 1),
            "note": "estimate: this log's non-formatting release-to-delivery plus today's formatting time",
        }
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    os.environ.pop("TALK_DAT_LOCAL_ENGINE_OFFLINE", None)
    raise SystemExit(main())
