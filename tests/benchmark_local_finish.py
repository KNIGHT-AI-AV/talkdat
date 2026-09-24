"""Explicit, pinned-model local benchmark; never part of test discovery."""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import time
from pathlib import Path
from unittest.mock import patch

from tests.parity_battery import cases, run, summarize, violations


def benchmark(model: str, *, rounds: int = 2) -> dict:
    from knight_flow import formatting, llm

    os.environ.pop("TALK_DAT_LOCAL_ENGINE_OFFLINE", None)  # measure the real engine
    base = "http://127.0.0.1:11434"
    installed = llm._ollama_models(base) or set()
    if model.lower() not in installed:
        raise ValueError("The exact requested model is not installed; this benchmark never downloads weights.")
    started = time.perf_counter()
    speed = llm.warm_local_finish(base, model, timeout=60)
    warm_ms = (time.perf_counter() - started) * 1000
    reports = []
    for index in range(rounds):
        calls, validations, finishes = [], [], []
        original_chat, original_validate = llm._ollama_chat, formatting._valid_formatter_output
        original_finish = formatting.local_finish

        def chat(*args, **kwargs):
            began = time.perf_counter()
            receipt = {"model": kwargs.get("model"), "error": ""}
            try:
                payload = original_chat(*args, **kwargs)
                receipt.update({k: payload.get(k) for k in (
                    "prompt_eval_count", "eval_count", "prompt_eval_duration", "eval_duration", "load_duration")})
                return payload
            except Exception as exc:
                receipt["error"] = type(exc).__name__
                raise
            finally:
                receipt["ms"] = round((time.perf_counter() - began) * 1000, 3)
                calls.append(receipt)

        def validate(*args, **kwargs):
            accepted = original_validate(*args, **kwargs)
            validations.append(bool(accepted))
            return accepted

        def finish(*args, **kwargs):
            answer = original_finish(*args, **kwargs)
            finishes.append(bool(answer))
            return answer

        # Pin the exact installed tag. The normal Executive chooser may upgrade
        # a 1.7b request, which would make a comparison labelled 1.7b dishonest.
        # Disable the fast path only for this experiment to compare the models,
        # independently from the production routing benchmark.
        with patch.object(llm, "local_finish_target", return_value=(base, model)), \
             patch.object(llm, "_ollama_chat", side_effect=chat), \
             patch.object(formatting, "_valid_formatter_output", side_effect=validate), \
             patch.object(formatting, "local_finish", side_effect=finish), \
             patch.object(formatting, "_high_confidence_fast_format", return_value=None):
            rows = run(model=model, corpus=cases())
        reports.append({
            "round": index + 1, "summary": summarize(rows),
            "cohorts": {name: summarize([r for r in rows if r["cohort"] == name])
                        for name in sorted({r["cohort"] for r in rows})},
            "model_finish_attempts": len(finishes), "nonempty_model_outputs": sum(finishes),
            "accepted_model_outputs": sum(validations), "rejected_model_outputs": len(validations) - sum(validations),
            "actual_requests": calls, "violations": violations(rows), "rows": rows,
        })
    return {"model": model, "mode": "pinned-model, fast path disabled", "warmup_ms": round(warm_ms, 3),
            "machine_speed": dataclasses.asdict(speed) if speed else None, "rounds": reports}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.rounds <= 5:
        parser.error("rounds must be between 1 and 5")
    report = benchmark(args.model, rounds=args.rounds)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "rounds"}))
    for result in report["rounds"]:
        print(json.dumps({k: v for k, v in result.items() if k not in {"rows", "actual_requests"}}))
        print("actual requested models:", sorted({r["model"] for r in result["actual_requests"]}))
    return 0  # An experiment reports failures; the separate parity gate enforces them.


if __name__ == "__main__":
    raise SystemExit(main())
