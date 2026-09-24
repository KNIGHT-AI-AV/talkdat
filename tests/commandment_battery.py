"""The dictation commandments, measured. Run: python -m tests.commandment_battery.

`tests/commandment_cases.json` is the companion file of
docs/DICTATION-COMMANDMENTS.md: 229 cases, a positive and a counterexample
for each of the 100 commandments plus 29 mixed-condition cases. This module
offers every case to the real pipeline in the shape the app would see it:

- formatter cases go through `process_dictation`;
- insertion cases also go through `apply_caret_context` and `join_at_caret`
  (and the chat-app period rule for a messenger), exactly as app.py does at
  delivery;
- context the formatter really receives is passed in (settings, dictionary
  words and replacements, window-title names, a simulated model answer, an
  unavailable model); context it never receives (a document on screen, a
  thread in another language, the date) is simply not passed, which is the
  point of those cases: the output must not depend on it;
- cases that need something no unit can supply (recorded audio, the native
  paste layer, a field type the formatter is not told) are SKIPPED with the
  reason, never silently dropped.

The rules lane is deterministic and runs in the unit suite
(tests/test_commandment_cases.py) against a ratchet file,
tests/commandment_baseline.json: every case it lists as passing must keep
passing. Model lanes are explicit and loopback-only:

    python -m tests.commandment_battery                                   # rules
    python -m tests.commandment_battery --model qwen3:4b-instruct-2507-q4_K_M --intensity chill
    python -m tests.commandment_battery --model qwen3:4b-instruct-2507-q4_K_M --intensity executive
    python -m tests.commandment_battery --json out.json                   # every row

A finite set can show a defect; it cannot prove there is none. Report results
as "N of M cases on this set".
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
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

CASES_PATH = Path(__file__).with_name("commandment_cases.json")
BASELINE_PATH = Path(__file__).with_name("commandment_baseline.json")

# docs/DICTATION-COMMANDMENTS.md section 4, "Index" and "Status by category".
CATEGORIES: tuple[tuple[int, int, str], ...] = (
    (1, 8, "Hearing & uncertainty"),
    (9, 17, "Disfluencies & repetition"),
    (18, 27, "Self-corrections & restarts"),
    (28, 36, "Meaning preservation"),
    (37, 45, "Punctuation & capitalization"),
    (46, 53, "Structure & layout"),
    (54, 64, "Numbers & structured info"),
    (65, 73, "Names, spelling & technical language"),
    (74, 80, "Context & its limits"),
    (81, 86, "Insertion & continuation"),
    (87, 93, "User voice & language"),
    (94, 100, "Commands, trust & recovery"),
)
MIXED = "Mixed conditions"
# Every commandment the index marks POLISH; the rest are ESSENTIAL.
POLISH = frozenset({5, 15, 17, 24, 42, 43, 44, 45, 48, 49, 50, 51, 53, 61, 63, 65, 66, 72, 73,
                    76, 82, 83, 86, 91, 92, 93, 99})

# paste.py's chat-app rule reads the foreground executable; the case names the app.
_MESSENGER_APPS = {"slack": "slack.exe", "discord": "discord.exe", "teams": "ms-teams.exe",
                   "whatsapp": "whatsapp.exe", "telegram": "telegram.exe", "signal": "signal.exe"}
_CARET_KEYS = frozenset({"left", "right", "previous_take"})
# Context the formatter never receives. Running the case without it is the
# test: the output may not depend on what was on screen.
_UNREAD_CONTEXT = frozenset({"document_text", "thread_text", "thread_language", "reply_to", "today",
                             "clipboard", "app", "asr_confidence"})

SKIP_AUDIO = "end_to_end: needs recorded audio (docs/DICTATION-COMMANDMENTS.md section 6.1)"
SKIP_NATIVE = "native delivery (focus, clipboard timing): paste layer, not the formatter"
SKIP_FIELD = "destination field type not modelled: {}"
# X-604: the kinds field_context.FieldProbe reports and the pipeline acts on.
_FIELD_KINDS = frozenset({"password", "single-line", "console"})
SKIP_SETTING = "setting not implemented: {}"
SKIP_CONTEXT = "context not passed to the formatter yet: {}"
SKIP_ACTION = "app action, not a formatting pass: {}"


def load_cases(path: Path = CASES_PATH) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def category(case: dict[str, Any]) -> str:
    if str(case["id"]).startswith("MIX"):
        return MIXED
    number = int(case["commandment"])
    for low, high, name in CATEGORIES:
        if low <= number <= high:
            return name
    raise ValueError(f"commandment out of range: {number}")


def priority(case: dict[str, Any]) -> str:
    """ESSENTIAL or POLISH; a mixed case is ESSENTIAL when anything it covers is."""
    numbers = [int(n) for n in case.get("covers") or [case["commandment"]]]
    return "POLISH" if all(n in POLISH for n in numbers) else "ESSENTIAL"


def plan(case: dict[str, Any]) -> tuple[str, str]:
    """(kind, note). kind is format | caret | simulated_model | model_unavailable | skip."""
    context = case.get("context")
    if case["layer"] == "end_to_end":
        return "skip", SKIP_AUDIO
    if context is None:
        return "format", ""
    keys = set(context)
    if "audio" in keys:
        return "skip", SKIP_AUDIO
    if keys & {"focus_at_start", "focus_at_delivery", "clipboard_before", "target_reads_clipboard_after_ms"}:
        return "skip", SKIP_NATIVE
    if "simulated_model_output" in keys:
        return "simulated_model", "the model's answer is supplied; the validator decides"
    if "model" in keys:
        state = str(context["model"])
        if "time" in state or "unavailable" in state:
            return "model_unavailable", "the model is late; the rules draft answers"
        return "format", "healthy model: the lane's own model answers"
    if "action" in keys:
        action = str(context["action"])
        if action == "normal delivery":
            return "format", ""
        return "skip", SKIP_ACTION.format(action)
    if "settings" in keys:
        unknown = set(context["settings"]) - {"censor_profanity"}
        if unknown:
            return "skip", SKIP_SETTING.format(", ".join(sorted(unknown)))
        return "format", "setting applied"
    if "document_spelling" in keys:
        return "skip", SKIP_CONTEXT.format("document spelling variety")
    if "field" in keys:
        field = str(context["field"])
        if field in _FIELD_KINDS:
            return "format", f"the {field} field reaches the formatter"
        if field not in {"text", "multi-line"}:
            return "skip", SKIP_FIELD.format(field)
        return "format", "an ordinary text field is the default"
    if keys == {"caret_context"}:
        return "format", "caret unreadable: standalone formatting"
    if "selection" in keys:
        # The caret reader refuses a selection (caret_context._read_uia), so
        # the take is formatted standalone and replaces the selection.
        return "format", "a selection makes the caret unreadable"
    if keys & _CARET_KEYS:
        return "caret", ""
    return "format", "context not read by the formatter" if keys & _UNREAD_CONTEXT else ""


def case_config(case: dict[str, Any], base: dict[str, Any]) -> dict[str, Any]:
    """The fixture config with everything the case's context legitimately sets."""
    from tests.parity_battery import preset_config

    config = copy.deepcopy(base)
    if case["mode"] == "verbatim":
        config = preset_config(config, "verbatim")
    context = case.get("context") or {}
    settings = context.get("settings") or {}
    if "censor_profanity" in settings:
        config["cleanup"]["censor_profanity"] = bool(settings["censor_profanity"])
    dictionary = config.setdefault("dictionary", {})
    if context.get("dictionary"):
        dictionary["words"] = list(dictionary.get("words") or []) + list(context["dictionary"])
    if context.get("dictionary_replacements"):
        dictionary["replacements"] = [
            {"from": source, "to": target} for source, target in context["dictionary_replacements"].items()
        ]
    names: list[str] = []
    if context.get("visible_names"):
        names.extend(str(name) for name in context["visible_names"])
    if context.get("window_title"):
        from knight_flow.screen_context import names_from_title

        names.extend(names_from_title(str(context["window_title"])))
    if names:
        dictionary["screen_context"] = True
        config["_screen_names"] = names
    if str(context.get("field", "")) in _FIELD_KINDS:
        config["_field"] = str(context["field"])
    return config


@contextlib.contextmanager
def _model_answer(answer: str | None) -> Iterator[None]:
    """Stand in for the local model: `answer` is what it returns ("" = late)."""
    from knight_flow import formatting

    with patch.object(formatting, "local_finish", return_value=answer), \
         patch.object(formatting, "llm_configured", return_value=True), \
         patch.object(formatting, "resolved_llm_provider", return_value="ollama"):
        yield


def _messenger_exe(case: dict[str, Any]) -> str:
    app = str((case.get("context") or {}).get("app", "")).strip().lower()
    return _MESSENGER_APPS.get(app, "")


def _normalise_enter(case: dict[str, Any]) -> bool | None:
    keys = case.get("keys")
    if keys is None:
        return None
    return "Enter" in keys


_SURFACE_RE = re.compile(r"[.,;:!?\"()]")


def _surface(text: str) -> str:
    text = text.replace("“", '"').replace("”", '"').replace("’", "'")
    return " ".join(_SURFACE_RE.sub(" ", text.lower()).split())


def classify(case: dict[str, Any], produced: str, send_enter: bool, error: str = "") -> str:
    """exact | acceptable | surface | words | keys | error.

    surface: differs only in capitals, spacing, line breaks or . , ; : ! ? " ( )
    (house style, or a visible defect such as a missing space). words: words,
    numbers or list structure differ. keys: Enter pressed when it should not
    be, or not pressed when it should. A case without a `keys` field must not
    press Enter at all.
    """
    if error:
        return "error"
    expected_enter = _normalise_enter(case)
    if bool(send_enter) != bool(expected_enter):
        return "keys"
    if produced == case["expected"]:
        return "exact"
    if produced in (case.get("acceptable") or []):
        return "acceptable"
    targets = [case["expected"], *(case.get("acceptable") or [])]
    if any(_surface(produced) == _surface(target) for target in targets):
        return "surface"
    return "words"


PASSING = frozenset({"exact", "acceptable"})
FAILING_HARD = frozenset({"words", "keys", "error"})


def run_case(case: dict[str, Any], base: dict[str, Any], *, lane: str) -> dict[str, Any]:
    """One case through the pipeline the way the app would run it."""
    from knight_flow.caret_context import apply_caret_context, join_at_caret
    from knight_flow.text_pipeline import process_dictation

    kind, note = plan(case)
    row: dict[str, Any] = {
        "id": case["id"], "commandment": case["commandment"], "category": category(case),
        "priority": priority(case), "critical": bool(case["critical"]), "layer": case["layer"],
        "mode": case["mode"], "kind": kind, "note": note, "input": case["input"],
        "expected": case["expected"], "lane": lane,
    }
    if kind == "skip":
        row.update(produced="", send_enter=False, route="", rejection="", ms=0.0, error="", verdict="skipped")
        return row
    config = case_config(case, base)
    model_lane = lane != "rules"
    stack = contextlib.ExitStack()
    if kind == "simulated_model":
        stack.enter_context(_model_answer(str(case["context"]["simulated_model_output"])))
    elif kind == "model_unavailable":
        stack.enter_context(_model_answer(""))
    local_only = not model_lane and kind not in {"simulated_model", "model_unavailable"}
    started = time.perf_counter()
    error = ""
    processed = None
    produced = ""
    try:
        with stack:
            processed = process_dictation(case["input"], config, local_only=local_only)
            produced = processed.text
            if kind == "caret":
                context = case["context"]
                caret = {"left": context.get("left", ""), "right": context.get("right", "")}
                produced = join_at_caret(apply_caret_context(produced, case["input"], caret, config), caret)
            messenger = _messenger_exe(case)
            if messenger and case["layer"] == "insertion":
                from knight_flow import paste

                from knight_flow.caret_context import ends_with_spoken_mark

                with patch.object(paste, "foreground_process_name", return_value=messenger):
                    produced = paste.strip_messenger_trailing_period(
                        produced, keep=ends_with_spoken_mark(case["input"]))
    except Exception as exc:  # a crash is a result, not a harness failure
        error = f"{type(exc).__name__}: {exc}"
    elapsed = (time.perf_counter() - started) * 1000
    send_enter = bool(getattr(processed, "send_enter", False))
    row.update(
        produced=produced, send_enter=send_enter, route=getattr(processed, "route", ""),
        rejection=getattr(processed, "rejection", ""), ms=round(elapsed, 2), error=error,
    )
    row["verdict"] = classify(case, produced, send_enter, error)
    return row


def run(cases: list[dict[str, Any]] | None = None, *, model: str | None = None,
        intensity: str | None = None) -> list[dict[str, Any]]:
    """Every case on one lane. `model=None` is the rules lane."""
    from tests.parity_battery import local_config

    base = local_config(model)
    if intensity:
        base["cleanup"]["format_intensity"] = "executive" if intensity == "executive" else "standard"
    lane = "rules" if not model else (intensity or "default")
    return [run_case(case, base, lane=lane) for case in (cases if cases is not None else load_cases())]


def _pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * q) - 1)]


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ran = [r for r in rows if r["verdict"] != "skipped"]
    verdicts = Counter(r["verdict"] for r in ran)
    critical_failures = [r["id"] for r in ran if r["critical"] and r["verdict"] in FAILING_HARD]
    times = [r["ms"] for r in ran]
    return {
        "cases": len(rows), "ran": len(ran), "skipped": len(rows) - len(ran),
        "exact": verdicts["exact"], "acceptable": verdicts["acceptable"],
        "passing": verdicts["exact"] + verdicts["acceptable"],
        "surface": verdicts["surface"], "words": verdicts["words"], "keys": verdicts["keys"],
        "errors": verdicts["error"], "critical_failures": len(critical_failures),
        "critical_failure_ids": critical_failures,
        "routes": dict(sorted(Counter(r["route"] for r in ran if r["route"]).items())),
        "rejections": dict(sorted(Counter(r["rejection"] for r in ran if r["rejection"]).items())),
        "median_ms": statistics.median(times) if times else None, "p90_ms": _pct(times, 0.9),
        "max_ms": max(times) if times else None,
    }


def breakdown(rows: list[dict[str, Any]], key: str | Callable[[dict[str, Any]], str]) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[key(row) if callable(key) else str(row[key])].append(row)
    return {name: summarize(group) for name, group in groups.items()}


def report(rows: list[dict[str, Any]], *, lane: str, model: str | None, warmup_ms: float | None) -> dict[str, Any]:
    return {
        "lane": lane, "model": model or "", "warmup_ms": warmup_ms,
        "measured": time.strftime("%Y-%m-%d %H:%M"),
        "summary": summarize(rows),
        "by_category": breakdown(rows, "category"),
        "by_priority": breakdown(rows, "priority"),
        "by_mode": breakdown(rows, "mode"),
        "by_layer": breakdown(rows, "layer"),
        "rows": rows,
    }


def load_baseline(path: Path = BASELINE_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


UNMARKED = "UNMARKED: say why the rules lane cannot pass this case"


def baseline_from(rows: list[dict[str, Any]], previous: dict[str, Any] | None = None) -> dict[str, Any]:
    """The ratchet file for the rules lane.

    `rules_passing` is every case the rules lane passes today: each must keep
    passing, and the count may only go up. `rules_not_passing` marks every
    runnable case it does not pass with the reason (kept from `previous`), so
    no case is silently dropped; `skipped` records what cannot run here.
    """
    previous = previous or {}
    reasons = dict(previous.get("rules_not_passing") or {})
    passing = sorted(r["id"] for r in rows if r["verdict"] in PASSING)
    failing = sorted(r["id"] for r in rows if r["verdict"] not in PASSING and r["verdict"] != "skipped")
    return {
        "about": ("Rules-lane ratchet for tests/commandment_cases.json (docs/DICTATION-COMMANDMENTS.md). "
                  "Every id in rules_passing must keep passing; the count may only go up. "
                  "Regenerate with: python -m tests.commandment_battery --write-baseline"),
        "rules_passing_count": len(passing),
        "rules_passing": passing,
        "rules_not_passing": {case_id: reasons.get(case_id, UNMARKED) for case_id in failing},
        "skipped": {r["id"]: r["note"] for r in rows if r["verdict"] == "skipped"},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", help="explicit local Ollama lane (loopback, never downloads)")
    parser.add_argument("--intensity", choices=("chill", "executive"), help="finish the model is asked for")
    parser.add_argument("--json", metavar="PATH", help="write the full report, every row, here")
    parser.add_argument("--only", help="comma-separated case ids")
    parser.add_argument("--write-baseline", action="store_true",
                        help="rules lane only: rewrite tests/commandment_baseline.json, keeping existing reasons")
    args = parser.parse_args(argv)
    if args.write_baseline and (args.model or args.only):
        parser.error("--write-baseline is the rules lane over every case")
    from knight_flow import llm

    cases = load_cases()
    if args.only:
        wanted = {item.strip() for item in args.only.split(",")}
        cases = [case for case in cases if case["id"] in wanted]
    warmup_ms = None
    with contextlib.ExitStack() as stack:
        if args.model:
            # An explicit model run measures the real engine on purpose; pin
            # the exact tag and warm it so no case pays the load.
            os.environ.pop("TALK_DAT_LOCAL_ENGINE_OFFLINE", None)
            base_url = "http://127.0.0.1:11434"
            stack.enter_context(patch.object(llm, "local_finish_target", return_value=(base_url, args.model)))
            began = time.perf_counter()
            llm.warm_local_finish(base_url, args.model, timeout=120)
            warmup_ms = round((time.perf_counter() - began) * 1000, 1)
        rows = run(cases, model=args.model, intensity=args.intensity)
    lane = "rules" if not args.model else (args.intensity or "default")
    result = report(rows, lane=lane, model=args.model, warmup_ms=warmup_ms)
    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
    if args.write_baseline:
        previous = load_baseline() if BASELINE_PATH.exists() else None
        BASELINE_PATH.write_text(json.dumps(baseline_from(rows, previous), indent=1, ensure_ascii=False) + "\n",
                                 encoding="utf-8", newline="\n")
    printable = {k: v for k, v in result.items() if k not in {"rows", "by_category", "by_mode", "by_layer"}}
    print(json.dumps(printable, indent=1, ensure_ascii=False))
    for row in rows:
        if row["verdict"] in FAILING_HARD and row["critical"]:
            print(f"CRITICAL {row['id']}: {row['produced']!r} (expected {row['expected']!r})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
