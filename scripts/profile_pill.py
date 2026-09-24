"""Measure what the pill's animation actually achieves, on this machine.

"Why is ours so choppy?" is a measurement question before it is a code
question. This drives the REAL Overlay -- off the founder's screen, in a
throwaway home -- lets the real _animate loop pace itself exactly as it does
in the shipped app, and reports the numbers the eye feels: the effective
frame rate during live dictation, per-frame draw cost, and the top sinks.

Run:  python scripts/profile_pill.py [seconds]
"""
from __future__ import annotations

import cProfile
import io
import os
import pstats
import statistics
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("TALK_DAT_HOME", tempfile.mkdtemp(prefix="talkdat-profile-"))

SECONDS = float(sys.argv[1]) if len(sys.argv) > 1 else 4.0


def main() -> None:
    from knight_flow.config import load_config
    from knight_flow.overlay import Overlay

    config = load_config()
    overlay = Overlay(config, callbacks={})
    root = overlay.root
    root.geometry("+576+-1440")  # monitor 2, never the founder's screen

    # Let the open animation finish -- _draw_visual stands down while it owns
    # the canvas, and a harness that skips this measures an early return.
    deadline = time.perf_counter() + 5.0
    while overlay._open_anim_active and time.perf_counter() < deadline:
        root.update()
        time.sleep(0.005)

    overlay.set_state("listening", "Profiling...", "")
    deadline = time.perf_counter() + 2.0
    while overlay._open_anim_active and time.perf_counter() < deadline:
        root.update()
        time.sleep(0.005)

    frame_times: list[float] = []
    real_draw = overlay._draw_visual

    def timed_draw() -> None:
        start = time.perf_counter()
        real_draw()
        frame_times.append((time.perf_counter() - start) * 1000.0)

    overlay._draw_visual = timed_draw  # type: ignore[method-assign]

    levels = [0.05, 0.2, 0.45, 0.7, 0.9, 0.65, 0.35, 0.15]
    profiler = cProfile.Profile()
    profiler.enable()
    start_wall = time.perf_counter()
    index = 0
    while time.perf_counter() - start_wall < SECONDS:
        # A speaking voice moves the meter ~every 50ms; the REAL after-loop
        # decides when to draw.
        overlay.set_level(levels[index % len(levels)])
        index += 1
        step_deadline = time.perf_counter() + 0.05
        while time.perf_counter() < step_deadline:
            root.update()
            time.sleep(0.002)
    profiler.disable()
    wall = time.perf_counter() - start_wall

    if not frame_times:
        print("NO FRAMES DRAWN -- the loop never reached _draw_visual; fix the harness")
        return
    drawn = len(frame_times)
    frame_times.sort()
    avg = statistics.fmean(frame_times)
    p95 = frame_times[int(drawn * 0.95) - 1]
    print(f"effective fps     : {drawn / wall:.1f}  ({drawn} frames in {wall:.1f}s of live dictation)")
    print(f"draw cost avg     : {avg:.2f} ms   p95: {p95:.2f} ms   worst: {frame_times[-1]:.2f} ms")
    print(f"active cache size : {len(getattr(overlay, 'active_render_cache', {}))}")

    out = io.StringIO()
    stats = pstats.Stats(profiler, stream=out)
    stats.sort_stats("tottime").print_stats(18)
    print("\nTop sinks (by own time):")
    for line in out.getvalue().splitlines():
        if "knight_flow" in line or "PIL" in line or "ncalls" in line:
            print(line)

    root.destroy()


if __name__ == "__main__":
    main()
