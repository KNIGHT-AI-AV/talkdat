"""Tail latency of local live captions on this PC: cadence plus one decode.

Runs the real engine on an 8 s window of speech (a WAV you point it at,
16 kHz mono PCM16) on the GPU path and, with TALK_DAT_FORCE_CPU=1, on the CPU
path. Prints the median of ten warm decodes and the resulting tail latency.
Numbers go in docs/LIVE_CAPTIONS_LOCAL.md.
"""
from __future__ import annotations

import os
import statistics
import sys
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from knight_flow import local_stt
from knight_flow.local_live import DECODE_CADENCE_SECONDS, TAIL_WINDOW_SECONDS


def main(path: str) -> int:
    with wave.open(path, "rb") as handle:
        rate, channels = handle.getframerate(), handle.getnchannels()
        pcm = handle.readframes(handle.getnframes())
    window = pcm[-int(TAIL_WINDOW_SECONDS * rate * channels * 2):]
    gpu = os.environ.get("TALK_DAT_FORCE_CPU") != "1" and local_stt.gpu_available()
    kwargs = dict(model_id=local_stt.DEFAULT_LOCAL_MODEL_ID, sample_rate=rate, channels=channels, language="en-US", gpu=gpu)
    local_stt.transcribe(pcm16=window, **kwargs)  # warm: load + shape compile
    local_stt.transcribe(pcm16=window, **kwargs)
    times = []
    text = ""
    for _ in range(10):
        started = time.perf_counter()
        text = local_stt.transcribe(pcm16=window, **kwargs)
        times.append(time.perf_counter() - started)
    decode = statistics.median(times)
    print(
        f"path={'GPU' if gpu else 'CPU'} window={TAIL_WINDOW_SECONDS}s decode_median={decode:.2f}s "
        f"min={min(times):.2f}s max={max(times):.2f}s tail_latency~={DECODE_CADENCE_SECONDS + decode:.2f}s text={text[:60]!r}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
