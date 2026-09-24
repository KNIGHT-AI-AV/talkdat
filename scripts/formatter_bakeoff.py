"""X-68: the formatter bake-off, runnable end to end.

Feeds each raw "ours" sample from the paired Wispr corpus to candidate
formatters over OpenRouter -- under the app's OWN system prompt and
instruction, so what is measured is what would ship -- and scores every
candidate on (a) similarity to the Wispr rendering, (b) whether the raw
text already matched (the "do we even need the adjustment layer" answer),
and (c) latency + output tok/s per the standing rule that a model default
is never picked from memory.

Slugs are READ from the OpenRouter catalog at runtime, never guessed.
The key comes from TALK_DAT_BAKEOFF_KEY (a scoped, capped key -- never the
provisioning key). Results land as JSON + a readable table on stdout.

Usage:
    python scripts/formatter_bakeoff.py --out bakeoff_results.json
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import statistics
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from knight_flow.formatting import FORMAT_INSTRUCTION, FORMAT_SYSTEM_PROMPT  # noqa: E402

# The paired corpus (X-68, dictated into both apps 2026-08-10). raw = what
# our pipeline heard; target = Wispr's rendering of the same speech.
# Fragments the doc elides are completed minimally and marked.
CORPUS = [
    {"behavior": "dropped-subject repair + homophone",
     "raw": "The first one was done by Hours and am using them simultaneously.",
     "target": "The first one was done by ours, and I'm using them simultaneously."},
    {"behavior": "dropped-subject repair",
     "raw": "Actually, think the first one is better so going to use it.",
     "target": "Actually, I think the first one is better, so I'm going to use it."},
    {"behavior": "disfluency dedup",
     "raw": "It was like it was like the fastest one I have tried.",
     "target": "It was like the fastest one I have tried."},
    {"behavior": "standalone filler drop",
     "raw": "Like, the second take sounded better to me.",
     "target": "The second take sounded better to me."},
    {"behavior": "colloquial normalization",
     "raw": "We are gonna ship the new build tonight.",
     "target": "We are going to ship the new build tonight."},
    {"behavior": "grammar agreement",
     "raw": "There's two of each in the box.",
     "target": "There are two of each in the box."},
    {"behavior": "number styling: fraction",
     "raw": "It ran at one fifth of the speed.",
     "target": "It ran at 1/5 of the speed."},
    {"behavior": "number styling: compound modifier",
     "raw": "The new one is one third faster.",
     "target": "The new one is one-third faster."},
    {"behavior": "paired parenthetical commas",
     "raw": "It was about a quarter maybe a third of the speed.",
     "target": "It was about a quarter, maybe a third, of the speed."},
    {"behavior": "fragment handling",
     "raw": "I want the reds richer. Just so. Them.",
     "target": "I want the reds richer, just so."},
    {"behavior": "comma join over hard stop",
     "raw": "I did not say that. So just fix our shit.",
     "target": "I didn't say that, so just fix our shit."},
]

# Candidate families -- resolved against the live catalog, cheapest match
# per family, never a guessed slug.
CANDIDATE_FAMILIES = [
    ("baseline flash-lite", "gemini-3.5-flash-lite"),
    ("gemini flash", "gemini-3.5-flash"),
    ("gpt mini", "gpt-5-mini"),
    ("haiku", "claude-haiku-4.5"),
]

API = "https://openrouter.ai/api/v1"


def http_json(url: str, key: str | None = None, body: dict | None = None, timeout: float = 60.0) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data)
    if key:
        request.add_header("Authorization", f"Bearer {key}")
    if body is not None:
        request.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def resolve_slugs() -> dict[str, str]:
    catalog = http_json(f"{API}/models")["data"]
    ids = [entry["id"] for entry in catalog]
    resolved: dict[str, str] = {}
    for label, needle in CANDIDATE_FAMILIES:
        matches = sorted(m for m in ids if needle in m and ":free" not in m)
        if matches:
            resolved[label] = matches[0]
    return resolved


def run_candidate(key: str, slug: str) -> dict:
    latencies: list[float] = []
    scores: list[float] = []
    raw_scores: list[float] = []
    tokens_per_second: list[float] = []
    outputs: list[dict] = []
    for case in CORPUS:
        user = f"{FORMAT_INSTRUCTION}\n\n<dictation>\n{case['raw']}\n</dictation>"
        started = time.perf_counter()
        try:
            reply = http_json(
                f"{API}/chat/completions", key,
                {"model": slug,
                 "messages": [{"role": "system", "content": FORMAT_SYSTEM_PROMPT},
                              {"role": "user", "content": user}],
                 "max_tokens": 400},
            )
            elapsed = time.perf_counter() - started
            text = (reply.get("choices") or [{}])[0].get("message", {}).get("content", "").strip()
            completion_tokens = int(reply.get("usage", {}).get("completion_tokens") or 0)
        except Exception as error:
            outputs.append({"behavior": case["behavior"], "error": str(error)})
            continue
        latencies.append(elapsed * 1000)
        if completion_tokens and elapsed > 0:
            tokens_per_second.append(completion_tokens / elapsed)
        formatted_score = difflib.SequenceMatcher(None, text.lower(), case["target"].lower()).ratio()
        without_layer = difflib.SequenceMatcher(None, case["raw"].lower(), case["target"].lower()).ratio()
        scores.append(formatted_score)
        raw_scores.append(without_layer)
        outputs.append({"behavior": case["behavior"], "output": text,
                        "score": round(formatted_score, 3), "raw_score": round(without_layer, 3)})
    summary = {
        "slug": slug,
        "cases": len(scores),
        "mean_score_with_layer": round(statistics.mean(scores), 3) if scores else None,
        "mean_score_without_layer": round(statistics.mean(raw_scores), 3) if raw_scores else None,
        "p50_ms": round(statistics.median(latencies)) if latencies else None,
        "p95_ms": round(sorted(latencies)[int(len(latencies) * 0.95) - 1]) if len(latencies) >= 2 else None,
        "mean_output_tok_s": round(statistics.mean(tokens_per_second), 1) if tokens_per_second else None,
        "outputs": outputs,
    }
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="bakeoff_results.json")
    args = parser.parse_args()
    key = os.environ.get("TALK_DAT_BAKEOFF_KEY", "").strip()
    if not key:
        raise SystemExit("TALK_DAT_BAKEOFF_KEY is not set (mint a scoped, capped key first)")
    slugs = resolve_slugs()
    print("resolved candidates:", json.dumps(slugs, indent=1))
    results = {}
    for label, slug in slugs.items():
        print(f"running {label} ({slug}) over {len(CORPUS)} cases...")
        results[label] = run_candidate(key, slug)
        s = results[label]
        print(f"  with layer {s['mean_score_with_layer']}  without {s['mean_score_without_layer']}"
              f"  p50 {s['p50_ms']}ms  tok/s {s['mean_output_tok_s']}")
    Path(args.out).write_text(json.dumps(results, indent=1), encoding="utf-8")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
