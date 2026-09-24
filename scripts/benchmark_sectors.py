"""X-142: benchmark literally every sector, his order verbatim.

Times every performance-relevant function in the product with repeated
runs and writes the scoreboard to docs/PERFORMANCE_BENCH.md, so every
release can diff itself against the last. Pure local measurement: no
network, no model calls (the rules path is what we own; model latency is
the provider's number and the journal already records it per dictation).

Run from the repo root:  python scripts/benchmark_sectors.py
"""
from __future__ import annotations

import statistics
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

RAMBLE = (
    "so um the quarterly budget is forty two thousand dollars and we ship on "
    "september fifth which is like really soon bro and the team needs the new "
    "vocabulary packs for the medical contract plus the aviation one and uh "
    "make sure the search engine optimization work lands before the business "
    "checkout goes live because the conversion numbers depend on it okay "
) * 3

RESULTS: list[tuple[str, str, float, str]] = []


def bench(sector: str, name: str, func, reps: int = 50, unit_note: str = "") -> None:
    try:
        func()  # warm once; imports, caches, JITs all land here
        times = []
        for _ in range(reps):
            start = time.perf_counter()
            func()
            times.append((time.perf_counter() - start) * 1000.0)
        RESULTS.append((sector, name, statistics.median(times), unit_note))
    except Exception as error:
        RESULTS.append((sector, name, float("nan"), f"SKIPPED: {type(error).__name__}: {error}"))


def main() -> int:
    import json
    import tempfile

    # --- Formatting: the rules stack -----------------------------------
    from knight_flow.formatting import (
        apply_spoken_punctuation,
        heuristic_format,
        strip_em_dashes,
    )

    bench("formatting", "heuristic_format (300-word ramble)", lambda: heuristic_format(RAMBLE), 30)
    bench("formatting", "apply_spoken_punctuation", lambda: apply_spoken_punctuation(RAMBLE))
    bench("formatting", "strip_em_dashes (dash-heavy text)", lambda: strip_em_dashes(RAMBLE.replace(" and ", " — ")))

    # --- Vocabulary + dictionary ---------------------------------------
    from knight_flow.vocabulary import apply_vocabulary, parse_terms, with_brand_terms, with_default_terms

    terms = with_brand_terms(with_default_terms(parse_terms([])))
    bench("vocabulary", "apply_vocabulary (defaults+brands, 300 words)", lambda: apply_vocabulary(RAMBLE, terms), 30)

    # --- The whole local pipeline --------------------------------------
    from knight_flow.text_pipeline import is_bare_fragment, process_dictation

    pipeline_config = {"cleanup": {"smart_format": False, "level": "high"}, "dictation": {}, "transforms": {"llm": {"provider": "none"}}}
    bench("pipeline", "process_dictation local rules end-to-end", lambda: process_dictation(RAMBLE, pipeline_config, local_only=True), 20)
    bench("pipeline", "is_bare_fragment", lambda: is_bare_fragment("send it", "send it"), 200)

    # --- Pill rendering -------------------------------------------------
    from PIL import Image, ImageDraw

    from knight_flow.overlay import Overlay, apply_metallic_sheen, scrolling_spectrum_frame

    strip = Image.open("knight_flow/assets/ui/processing-spectrum-loop-4k.png")
    pill = Image.new("RGBA", (384, 70), (0, 0, 0, 0))
    ImageDraw.Draw(pill).rounded_rectangle((2, 2, 381, 67), radius=32, fill=(60, 64, 66, 255))
    offsets = iter(range(0, 10_000_000, 7))
    bench("pill", "scrolling_spectrum_frame (warm crop)", lambda: scrolling_spectrum_frame(strip, 384, 70, next(offsets)))
    frame = scrolling_spectrum_frame(strip, 384, 70, 0)
    bench("pill", "apply_metallic_sheen", lambda: apply_metallic_sheen(frame, pill), 30)
    bench("pill", "standby gray frame", lambda: Overlay._standby_gray_frame(None, pill.convert("RGB")), 30)

    # --- Config + journal ----------------------------------------------
    from unittest import mock

    tmp = Path(tempfile.mkdtemp())
    config_file = tmp / "config.json"
    config_file.write_text(json.dumps({"cleanup": {"format_intensity": "executive"}}), encoding="utf-8")
    with mock.patch("knight_flow.config.config_path", return_value=config_file):
        from knight_flow.config import load_config, save_config

        bench("config", "load_config (merge + migrations)", lambda: load_config(), 20)
        loaded = load_config()
        bench("config", "save_config (anti-clobber union)", lambda: save_config(loaded), 20)

    from knight_flow.format_journal import record_formatting

    journal_config = {"diagnostics": {"formatting_journal": True}}
    with mock.patch("knight_flow.format_journal.journal_path", return_value=tmp / "journal.jsonl"):
        bench("journal", "record_formatting (one entry)", lambda: record_formatting(
            journal_config, raw=RAMBLE[:400], final=RAMBLE[:400], stage="refine", intensity="executive", route="model", elapsed_ms=900.0
        ))
        from knight_flow.format_journal import journal_tail

        bench("journal", "journal_tail (50-entry file)", lambda: journal_tail())

    # --- Hotkeys ---------------------------------------------------------
    from knight_flow.hotkeys import chord_conflicts

    full_map = {
        "push_to_talk": [["ctrl", "cmd"]],
        "hands_free": [["ctrl", "cmd", "space"]],
        "command_mode": [["ctrl", "cmd", "c"]],
        "fix_that": [["ctrl", "alt", "f"]],
        "paste_last": [["ctrl", "alt", "v"]],
        "cancel": [["esc"]],
    }
    bench("hotkeys", "chord_conflicts (full map)", lambda: chord_conflicts(full_map), 100)

    # --- Session predicates ---------------------------------------------
    from knight_flow.audio_input import likely_has_input_signal

    silence = b"\x00\x00" * 16000
    bench("session", "likely_has_input_signal (1s silence)", lambda: likely_has_input_signal(silence), 100)

    # --- Report ----------------------------------------------------------
    today = date.today().isoformat()
    lines = [
        "# Talk DAT! sector benchmarks",
        "",
        f"Median ms per call, {sys.platform}, measured {today}. Regenerate with",
        "`python scripts/benchmark_sectors.py` and diff this file in the release",
        "commit whenever a sector changes.",
        "",
        "| Sector | Function | Median ms | Note |",
        "|---|---|---|---|",
    ]
    print(f"\n{'Sector':<12} {'Function':<48} {'Median ms':>10}")
    print("-" * 76)
    for sector, name, ms, note in RESULTS:
        display = "n/a" if ms != ms else f"{ms:.3f}"
        print(f"{sector:<12} {name:<48} {display:>10}  {note}")
        lines.append(f"| {sector} | {name} | {display} | {note} |")
    Path("docs/PERFORMANCE_BENCH.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\nwritten: docs/PERFORMANCE_BENCH.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
