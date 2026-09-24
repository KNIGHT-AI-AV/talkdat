"""Blind taste test: the local finisher against the cloud, on his own words.

The local-first blueprint (2026-09-05) has one decision no benchmark can
make. Transcription accuracy is published and measurable; whether a 4B model
on this PC writes as well as a frontier model in a datacentre is a judgement,
and it is HIS judgement, on HIS dictations, or it is worthless.

So this takes real transcripts out of the audio spool, runs each one through
both routes, and writes an answer sheet plus a blind sheet where the two
outputs are shuffled per item and labelled A and B. He reads the blind sheet,
writes A or B next to each number, and the score comes out of the answer key.

    .venv\\Scripts\\python.exe scripts/taste_test_formatting.py            # every spooled dictation
    .venv\\Scripts\\python.exe scripts/taste_test_formatting.py --limit 8 --tone executive

Nothing here changes a setting, and the cloud call is skipped with a printed
reason when the route is Local or there is no account, so running it can
never quietly send his text somewhere he did not choose.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from knight_flow.config import load_config  # noqa: E402
from knight_flow.formatting import EXECUTIVE_ADDENDUM, FORMAT_INSTRUCTION, FORMAT_SYSTEM_PROMPT  # noqa: E402
from knight_flow.llm import local_finish, local_finish_refusal, local_finish_target, warm_local_finish  # noqa: E402
from knight_flow import managed_cloud  # noqa: E402

SPOOL = Path(os.environ["APPDATA"]) / "TalkDat" / "audio-spool"


def spooled_transcripts(limit: int) -> list[dict[str, str]]:
    """The raw transcripts he actually dictated, newest last.

    raw_transcript is what the speech model heard, before any formatting: the
    honest input for both routes. Anything shorter than a sentence, and the
    smoke-test probes, are skipped.
    """
    out: list[dict[str, str]] = []
    for path in sorted(glob.glob(str(SPOOL / "*.json")), key=os.path.getmtime):
        try:
            record = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception:
            continue
        raw = str(record.get("raw_transcript") or "").strip()
        if len(raw) < 40:
            continue
        if any(marker in raw.lower() for marker in ("smoke test", "gate probe", "ignore me", "test test")):
            continue
        out.append({
            "id": Path(path).stem,
            "raw": raw,
            "shipped": str(record.get("final_text") or "").strip(),
            "when": str(record.get("created_at") or ""),
        })
    return out[-limit:] if limit else out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=12, help="how many dictations, newest first")
    parser.add_argument("--tone", choices=("executive", "chill"), default="executive")
    parser.add_argument("--out", default=str(ROOT / "docs" / "taste-test"))
    args = parser.parse_args()

    config = load_config()
    executive = args.tone == "executive"
    items = spooled_transcripts(args.limit)
    if not items:
        print("No dictations in the spool long enough to judge. Talk for a sentence or two first.")
        return 1
    print(f"{len(items)} dictations, tone {args.tone}")

    # The app warms the local model at startup and measures its speed; a
    # cold process refuses every request until that has happened, which is
    # what the first run of this script hit.
    api_base, model = local_finish_target(config, executive=executive)
    print(f"warming {model}", flush=True)
    speed = warm_local_finish(api_base, model)
    print("warm" if speed else f"local model did not warm: {local_finish_refusal(config) or 'no reason recorded'}")

    may_use_cloud = managed_cloud.text_may_leave_this_machine(config)
    if not may_use_cloud:
        print("Cloud route unavailable (this PC is set to Local, or there is no account).")
        print("The local column will still be written, so you can judge it against what shipped.")

    rows = []
    for index, item in enumerate(items, start=1):
        print(f"  [{index}/{len(items)}] {item['id'][:22]}", flush=True)
        started = time.perf_counter()
        # A generous budget: this is a judgement of the writing, not a race.
        local = local_finish(item["raw"], config, executive=executive, budget_seconds=30.0) or ""
        local_ms = (time.perf_counter() - started) * 1000

        # The refusal is a fact about the run, not an empty rewrite.
        local_refusal = "" if local else (local_finish_refusal(config) or "no reason recorded")

        cloud, cloud_ms, cloud_error = "", 0.0, ""
        if may_use_cloud:
            started = time.perf_counter()
            try:
                # The same instructions the product sends. Without them the
                # cloud hands the dictation back nearly verbatim and loses a
                # comparison it was never asked to enter.
                cloud = managed_cloud.rewrite_text(
                    config,
                    text=item["raw"],
                    system=FORMAT_SYSTEM_PROMPT + (EXECUTIVE_ADDENDUM if executive else ""),
                    instruction=FORMAT_INSTRUCTION,
                    timeout=30,
                )
            except Exception as error:  # noqa: BLE001 - reported, never swallowed
                cloud_error = f"{type(error).__name__}: {error}"
            cloud_ms = (time.perf_counter() - started) * 1000

        rows.append({**item, "local": local.strip(), "local_ms": round(local_ms),
                     "local_refusal": local_refusal, "cloud": cloud.strip(),
                     "cloud_ms": round(cloud_ms), "cloud_error": cloud_error})

    stamp = time.strftime("%Y-%m-%d-%H%M")
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    blind_path = out_dir / f"{stamp}-blind.md"
    key_path = out_dir / f"{stamp}-answers.json"

    # A pair needs two real answers. Anything else is reported, not shown:
    # judging a blank against a rewrite teaches nothing about either.
    judgeable = [row for row in rows if row["local"] and (row["cloud"] or row["shipped"])]
    dropped = [row for row in rows if row not in judgeable]
    for row in dropped:
        why = row["local_refusal"] or row["cloud_error"] or "both routes returned nothing"
        print(f"  dropped {row['id'][:22]}: {why}")
    if not judgeable:
        print("\nNothing judgeable. Fix the refusal above and run it again.")
        return 1
    rows = judgeable

    rng = random.Random(stamp)
    key = []
    blind = [
        f"# Which reads better? {stamp}",
        "",
        f"Tone: {args.tone}. {len(rows)} of your own dictations, formatted two ways.",
        "Write A or B beside each number. Nothing here says which is which.",
        "",
    ]
    for index, row in enumerate(rows, start=1):
        pair = [("local", row["local"]), ("cloud", row["cloud"])]
        if not row["cloud"]:
            pair = [("local", row["local"]), ("shipped", row["shipped"])]
        rng.shuffle(pair)
        key.append({"n": index, "id": row["id"], "A": pair[0][0], "B": pair[1][0],
                    "local_ms": row["local_ms"], "cloud_ms": row["cloud_ms"],
                    "local_refusal": row["local_refusal"], "cloud_error": row["cloud_error"]})
        blind += [
            f"## {index}",
            "",
            f"> What you said: {row['raw']}",
            "",
            f"**A.** {pair[0][1]}",
            "",
            f"**B.** {pair[1][1]}",
            "",
            "Better: ____",
            "",
        ]

    blind_path.write_text("\n".join(blind), encoding="utf-8")
    key_path.write_text(json.dumps(key, indent=2), encoding="utf-8")

    local_times = [row["local_ms"] for row in rows if row["local_ms"]]
    cloud_times = [row["cloud_ms"] for row in rows if row["cloud_ms"] and not row["cloud_error"]]
    print()
    print(f"Blind sheet: {blind_path}")
    print(f"Answer key:  {key_path}")
    if local_times:
        print(f"Local  median {sorted(local_times)[len(local_times) // 2]} ms")
    if cloud_times:
        print(f"Cloud  median {sorted(cloud_times)[len(cloud_times) // 2]} ms")
    errors = [row["cloud_error"] for row in rows if row["cloud_error"]]
    if errors:
        print(f"Cloud failed on {len(errors)} of {len(rows)}: {errors[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
