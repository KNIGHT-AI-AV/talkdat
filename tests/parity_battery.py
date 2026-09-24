"""Measured formatting contract. Run: python -m tests.parity_battery --json.

No microphone, clipboard, user config, model download or paid API. Model runs
are explicit and loopback-only. Safety counts are fixture-annotated violations,
not a claim that an arbitrary sentence's meaning can be judged by a regex.
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import json
import math
import os
import re
import statistics
from collections import Counter
import time
from dataclasses import dataclass
from typing import Callable
from unittest.mock import patch

from tests.parity_cases import CASES
from tests.parity_cases_extended import CASES as EXTENDED_CASES, COHORT as EXTENDED_COHORT
from tests.parity_cases_commandments import CASES as COMMANDMENT_CASES, COHORT as COMMANDMENT_COHORT


@dataclass(frozen=True)
class Case:
    label: str
    spoken: str
    expected: str | None
    cohort: str = "audit-2026-09-18"
    # Each expression accepts both the intact spoken form and its written form.
    facts: tuple[str, ...] = ()
    meaning: tuple[str, ...] = ()
    forbidden: tuple[str, ...] = ()
    reference: str = "docs/PARITY-AUDIT-2026-09-18.md"
    # False: the target is scored but the rules lane is not expected to reach
    # it (the model's job). Safety checks gate every case regardless.
    gate: bool = True
    alternatives: tuple[str, ...] = ()
    # A value the speaker took back. Still present = correction not applied.
    retracted: tuple[str, ...] = ()
    # Whether the take must press Enter (None = not assessed). A mismatch is a
    # violation on every lane: an Enter fired on prose submits a cut message.
    enter: bool | None = None
    # A named settings preset for this row: "verbatim" or "censor".
    preset: str = ""


FACTS = {
    "phone": (r"(?:four one five five five five one two one two|415[- .]?555[- .]?1212)",),
    "year": (r"(?:twenty twenty six|2026)",),
    "cardinal": (r"(?:twenty five|25)", r"(?:three hundred forty two|342)"),
    "money": (r"(?:nineteen dollars|\$19)", r"(?:forty nine ninety nine|\$49\.99)"),
    "cents": (r"(?:five dollars and fifty cents|\$5\.50)",),
    "decimal": (r"(?:zero point six|0\.6)", r"billion"),
    "percent": (r"(?:ten percent|10%)", r"tuesday"),
    "ordinal date": (r"september", r"(?:eighteenth|18th)"),
    "compound number": (r"(?:twenty one|21)",),
    "fraction": (r"(?:two[ -]thirds|2/3)",),
    "time half past": (r"(?:half past two|2:30)",),
    "time pm": (r"(?:three thirty|3:30)\s*p\.?m\.?",),
}
MEANING = {
    "year": (r"launched in",),
    "literal word comma": (r"\bcomma\b",),
    "lone i": (r"\bnot sure\b",),
    "fused contractions": (r"\bdon't need\b", r"\bcan't ship\b", r"\bwithout the key\b"),
    "quotes": (r"\bnot doing that\b",),
    "question then statement": (r"\bmy message\b", r"\bsent it\b", r"\ban hour ago\b"),
    "two sentences no cue": (r"\bbuild is green\b", r"\bpushed it\b", r"\b(?:ten|10) minutes ago\b"),
    "continuation": (r"^and then we$",),
}
FORBIDDEN = {
    "year": (r"\blinkedin\b",),
    "email": (r"knight\s+ai\+av",),
    "url": (r"talk\s+dat!",),
    "question then statement": (r"sent it[^?]*ago\?$",),
    "two sentences no cue": (r"\?",),
}


def cases() -> tuple[Case, ...]:
    seed = tuple(Case(label, spoken, expected, facts=FACTS.get(label, ()),
                      meaning=MEANING.get(label, ()), forbidden=FORBIDDEN.get(label, ()))
                 for label, spoken, expected in CASES)
    # Two short publisher examples, checked September 19. The second page
    # publishes the spoken example and promises a correction; its exact output
    # below is our target, not a captured Wispr run. Original audit stays separate.
    reference = (
        Case("wispr coffee correction", "Let's do coffee at 2 actually 3.",
             "Let's do coffee at 3.", "published-reference",
             facts=(r"\b3\b",), forbidden=(r"\b2\b",),
             reference="https://docs.wisprflow.ai/articles/5373093536-How-do-I-use-Smart-Formatting-%26-Backtrack"),
        Case("wispr meeting correction", "Let's meet at 2... actually 3",
             "Let's meet at 3.", "published-reference",
             facts=(r"\b3\b",), forbidden=(r"\b2\b",),
             reference="https://wisprflow.ai/features"),
    )
    extended = tuple(
        Case(label, spoken, target, EXTENDED_COHORT,
             facts=tuple(options.get("facts", ())), meaning=tuple(options.get("meaning", ())),
             forbidden=tuple(options.get("forbidden", ())),
             retracted=tuple(options.get("retracted", ())),
             reference="tests/parity_cases_extended.py",
             gate=bool(options.get("gate", False)), alternatives=tuple(options.get("alt", ())))
        for label, spoken, target, options in EXTENDED_CASES
    )
    commandments = tuple(
        Case(label, spoken, target, COMMANDMENT_COHORT,
             facts=tuple(options.get("facts", ())), meaning=tuple(options.get("meaning", ())),
             forbidden=tuple(options.get("forbidden", ())),
             retracted=tuple(options.get("retracted", ())),
             reference="tests/parity_cases_commandments.py",
             gate=bool(options.get("gate", False)), alternatives=tuple(options.get("alt", ())),
             enter=options.get("enter"), preset=str(options.get("preset", "")))
        for label, spoken, target, options in COMMANDMENT_CASES
    )
    return seed + reference + extended + commandments


def preset_config(config: dict, preset: str) -> dict:
    """The settings a row names, applied to the fixture config."""
    if preset == "verbatim":
        from knight_flow.onboarding import WRITING_PRESETS

        config["cleanup"].update(copy.deepcopy(WRITING_PRESETS["verbatim"]["cleanup"]))
    elif preset == "censor":
        config["cleanup"]["censor_profanity"] = True
    elif preset:
        raise ValueError(f"unknown preset {preset!r}")
    return config


def _loose(text: str) -> str:
    """Equal-for-a-reader normalisation: commas, a final full stop, bullet
    glyph and spacing do not change whether the formatting is right."""
    text = text.replace("“", '"').replace("”", '"').replace("’", "'")
    text = re.sub(r"(?m)^\s*[*•]\s+", "- ", text)
    text = text.replace(",", "")
    text = re.sub(r"[ \t]+", " ", text).strip()
    return re.sub(r"[.]$", "", text)


def acceptable(case: Case, produced: str) -> bool | None:
    if case.expected is None:
        return None
    candidates = (case.expected, *case.alternatives)
    return produced in candidates or _loose(produced) in {_loose(c) for c in candidates}


def local_config(model: str | None = None) -> dict:
    from knight_flow.config import DEFAULT_CONFIG

    config = copy.deepcopy(DEFAULT_CONFIG)
    config.setdefault("cleanup", {}).update(smart_format=True, format_mode="auto")
    config.setdefault("diagnostics", {})["formatting_journal"] = False
    config.setdefault("dictionary", {})["screen_context"] = False
    config.setdefault("plugins", {})["enabled"] = False
    config.setdefault("transforms", {}).setdefault("llm", {}).update(
        provider="ollama" if model else "none", model=model or "",
        api_base="http://127.0.0.1:11434", api_key="", auto_install=False,
    )
    config["transforms"]["ollama"]["enabled"] = bool(model)
    return config


def score(case: Case, produced: str, elapsed_ms: float, error: str = "", sent_enter: bool | None = None) -> dict:
    def absent(patterns: tuple[str, ...]) -> list[str]:
        return [p for p in patterns if not re.search(p, produced, re.IGNORECASE)]

    lost = absent(case.facts)
    changed = absent(case.meaning)
    changed += [p for p in case.forbidden if re.search(p, produced, re.IGNORECASE)]
    unresolved = [p for p in case.retracted if re.search(p, produced, re.IGNORECASE)]
    enter_wrong = case.enter is not None and sent_enter is not None and bool(sent_enter) != case.enter
    return {
        "unresolved": bool(unresolved), "failed_retraction_checks": unresolved,
        "label": case.label, "cohort": case.cohort, "reference": case.reference,
        "spoken": case.spoken, "expected": case.expected, "produced": produced,
        "match": produced == case.expected if case.expected is not None else None,
        "acceptable": acceptable(case, produced), "gated": case.gate,
        "data_loss": bool(lost), "meaning_change": bool(changed),
        "data_checks": len(case.facts), "meaning_checks": len(case.meaning) + len(case.forbidden),
        "failed_data_checks": lost, "failed_meaning_checks": changed,
        "ms": round(elapsed_ms, 3), "error": error,
        "enter_expected": case.enter, "enter_sent": sent_enter, "enter_wrong": enter_wrong,
    }


def summarize(rows: list[dict]) -> dict:
    scored = [r for r in rows if r["match"] is not None]
    times = sorted(r["ms"] for r in rows)
    return {
        "cases": len(rows), "exact_match_cases": len(scored),
        "exact_matches": sum(r["match"] is True for r in scored),
        "exact_match_rate": sum(r["match"] is True for r in scored) / len(scored) if scored else None,
        "acceptable_matches": sum(r.get("acceptable") is True for r in scored),
        "acceptable_rate": sum(r.get("acceptable") is True for r in scored) / len(scored) if scored else None,
        "routes": dict(sorted(Counter(r.get("route", "") for r in rows if r.get("route")).items())),
        "rejections": dict(sorted(Counter(r.get("rejection", "") for r in rows if r.get("rejection")).items())),
        "data_loss_count": sum(r["data_loss"] for r in rows),
        "meaning_change_count": sum(r["meaning_change"] for r in rows),
        "unresolved_corrections": sum(bool(r.get("unresolved")) for r in rows),
        "enter_mismatches": sum(bool(r.get("enter_wrong")) for r in rows),
        "data_assessed_cases": sum(r["data_checks"] > 0 for r in rows),
        "meaning_assessed_cases": sum(r["meaning_checks"] > 0 for r in rows),
        "errors": sum(bool(r["error"]) for r in rows),
        "median_ms": statistics.median(times) if times else None,
        "p90_ms": times[max(0, math.ceil(len(times) * .9) - 1)] if times else None,
        "max_ms": max(times) if times else None,
    }


def violations(rows: list[dict]) -> list[str]:
    if not rows:
        return ["empty corpus"]
    return [r["label"] for r in rows
            if ((r["match"] is False or r.get("unresolved")) and r.get("gated", True))
            or r["data_loss"] or r["meaning_change"] or r["error"] or r.get("enter_wrong")]


def run(*, model: str | None = None, corpus: tuple[Case, ...] | None = None,
        formatter: Callable[[str, dict], str] | None = None, intensity: str | None = None) -> list[dict]:
    from knight_flow import formatting
    from knight_flow.text_pipeline import process_dictation

    # Tolerant so the same harness can measure an older checkout (the
    # before/after numbers in docs/TEXT-PARITY.md were taken that way).
    last_rejection_reason = getattr(formatting, "last_rejection_reason", lambda: "")

    config = local_config(model)
    if intensity:
        config["cleanup"]["format_intensity"] = "executive" if intensity == "executive" else "standard"
    selected = corpus if corpus is not None else cases()
    rows = []
    for case in selected:
        started = time.perf_counter()
        error = route = ""
        sent_enter = None
        try:
            case_config = preset_config(copy.deepcopy(config), case.preset)
            if formatter:
                produced = formatter(case.spoken, case_config)
            else:
                processed = process_dictation(case.spoken, case_config, local_only=model is None)
                produced, route = processed.text, processed.route
                sent_enter = bool(processed.send_enter)
            if not isinstance(produced, str):
                raise TypeError("formatter did not return text")
        except Exception as exc:
            produced, error = "", type(exc).__name__
        row = score(case, produced, (time.perf_counter() - started) * 1000, error, sent_enter)
        row["route"] = route
        row["rejection"] = last_rejection_reason() if route.endswith("rules_after_rejection") else ""
        rows.append(row)
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--model", help="explicit local Ollama lane; never downloads a model")
    parser.add_argument("--observe", action="store_true", help="report failures with exit 0, never a passing gate")
    parser.add_argument("--intensity", choices=("chill", "executive"),
                        help="finish to request from the model (default: the shipped default)")
    parser.add_argument("--raw-input", action="store_true",
                        help="experiment: send the model the raw transcript instead of the rules draft")
    parser.add_argument("--cohort", help="only this cohort")
    args = parser.parse_args(argv)
    # Track whether the model was used, not merely which lane was requested.
    from knight_flow import formatting, llm
    calls: list[bool] = []
    original = formatting.local_finish

    def measured(*items, **kwargs):
        answer = original(*items, **kwargs)
        calls.append(bool(answer))
        return answer

    corpus = tuple(c for c in cases() if not args.cohort or c.cohort == args.cohort)
    warmup_ms = None
    with contextlib.ExitStack() as stack:
        stack.enter_context(patch.object(formatting, "local_finish", side_effect=measured))
        if args.raw_input:
            stack.enter_context(patch.object(formatting, "MODEL_SEES_RULES_DRAFT", False))
        if args.model:
            # An explicit model run measures the real engine on purpose.
            os.environ.pop("TALK_DAT_LOCAL_ENGINE_OFFLINE", None)
            # Pin the exact tag: the shipped chooser may upgrade 1.7b to the
            # GPU model, which would make a run labelled 1.7b dishonest. Warm
            # it first so no case pays the load; the warm-up is reported.
            base = "http://127.0.0.1:11434"
            stack.enter_context(patch.object(llm, "local_finish_target", return_value=(base, args.model)))
            began = time.perf_counter()
            llm.warm_local_finish(base, args.model, timeout=120)
            warmup_ms = round((time.perf_counter() - began) * 1000, 1)
        rows = run(model=args.model, intensity=args.intensity, corpus=corpus)
    failed = violations(rows)
    cohorts = {name: summarize([r for r in rows if r["cohort"] == name])
               for name in sorted({r["cohort"] for r in rows})}
    report = {"lane": f"ollama:{args.model}" if args.model else "rules", "intensity": args.intensity or "default",
              "model_input": "raw" if args.raw_input else "rules draft", "warmup_ms": warmup_ms,
              "summary": summarize(rows), "cohorts": cohorts,
              "model_calls": len(calls), "model_empty_results": calls.count(False),
              "status": "FAIL" if failed else "PASS", "rows": rows}
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(json.dumps({k: v for k, v in report.items() if k != "rows"}, indent=2))
        for row in rows:
            if row["label"] in failed:
                print(f"FAIL {row['label']}: {row['produced']!r} -> {row['expected']!r}")
    return 0 if args.observe or not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
