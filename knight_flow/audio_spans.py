"""T9: where in a take the audio went wrong, so that part can be heard again.

Mic Doctor (mic_doctor.py) turns one short sample into one verdict -- dead,
too quiet, too hot, noisy, or fine -- which is the right tool before a take
and the wrong one after it. "Why was that word wrong?" is about two seconds
somewhere in a minute, and a verdict for the whole minute cannot point there.

This splits a take's audio into 100 ms chunks with Mic Doctor's own measures
(level, the rails for clipping) and merges neighbouring chunks into SPANS:

* clipped -- samples at the rails, the one fault no processing can undo;
* silent  -- nothing arrived for longer than a pause (a dropped mic, a mute);
* noisy   -- the room was nearly as loud as the speech around it.

Each span carries its start and end in milliseconds. A span is reported only
when it lasts long enough to matter, and a take of clean speech reports
nothing -- a list of warnings on every take would be the noisy meter this is
meant not to be. ``span_audio`` cuts the audio for one span (with a little
context either side) so that just that part can be replayed or transcribed
again; the original recording is never changed.

Pure over PCM16 bytes; capture, storage and UI live with their owners.
"""

from __future__ import annotations

import math
from array import array
from dataclasses import dataclass

CHUNK_MS = 100
CLIP_LEVEL = 32600
#: A chunk is clipped when this share of its samples sit at the rails.
CLIP_SHARE = 0.01
#: Below this RMS a chunk is silence (Mic Doctor's "dead" floor).
SILENT_RMS = 0.0025
#: Silence shorter than this is a pause between words, not a fault.
MIN_SILENT_MS = 1500
#: Noise: a chunk this loud, between voiced chunks this much louder at most.
NOISY_RMS = 0.02
NOISY_RATIO = 3.0
MIN_NOISY_MS = 600
MIN_CLIPPED_MS = 100


@dataclass(frozen=True)
class Span:
    kind: str
    start_ms: int
    end_ms: int

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms


def _chunks_plain(pcm16: bytes, sample_rate: int, channels: int) -> list[tuple[float, float]]:
    """(rms 0..1, share of samples at the rails) per 100 ms chunk, in plain Python."""
    samples = array("h")
    samples.frombytes(pcm16[: len(pcm16) - (len(pcm16) % 2)])
    step = max(1, sample_rate * max(1, channels) * CHUNK_MS // 1000)
    out = []
    for start in range(0, len(samples), step):
        window = samples[start:start + step]
        if not window:
            continue
        rms = math.sqrt(sum(value * value for value in window) / len(window)) / 32768.0
        clipped = sum(1 for value in window if abs(value) >= CLIP_LEVEL) / len(window)
        out.append((rms, clipped))
    return out


def _chunks_numpy(pcm16: bytes, sample_rate: int, channels: int) -> list[tuple[float, float]]:
    """The same per-chunk measures with numpy (a Talk DAT dependency): a
    ten-minute take in milliseconds rather than seconds."""
    import numpy as np

    step = max(1, sample_rate * max(1, channels) * CHUNK_MS // 1000)
    values = np.frombuffer(pcm16[: len(pcm16) - (len(pcm16) % 2)], dtype="<i2").astype(np.float64)
    out = []
    for start in range(0, len(values), step):
        window = values[start:start + step]
        if not len(window):
            continue
        out.append((float(np.sqrt(np.mean(window * window))) / 32768.0,
                    float(np.count_nonzero(np.abs(window) >= CLIP_LEVEL)) / len(window)))
    return out


def _chunks(pcm16: bytes, sample_rate: int, channels: int) -> list[tuple[float, float]]:
    try:
        return _chunks_numpy(pcm16, sample_rate, channels)
    except ImportError:
        return _chunks_plain(pcm16, sample_rate, channels)


def _merge(flags: list[bool], kind: str, minimum_ms: int) -> list[Span]:
    spans, start = [], None
    for index, flagged in enumerate([*flags, False]):
        if flagged and start is None:
            start = index
        elif not flagged and start is not None:
            if (index - start) * CHUNK_MS >= minimum_ms:
                spans.append(Span(kind, start * CHUNK_MS, index * CHUNK_MS))
            start = None
    return spans


def analyze_spans(pcm16: bytes, *, sample_rate: int = 16000, channels: int = 1) -> list[Span]:
    chunks = _chunks(pcm16, sample_rate, channels)
    if not chunks:
        return []
    levels = [rms for rms, _ in chunks]
    voiced = sorted(level for level in levels if level >= NOISY_RMS)
    speech = voiced[len(voiced) * 2 // 3] if voiced else 0.0  # a loud-but-typical speech level
    clipped = [share >= CLIP_SHARE for _, share in chunks]
    silent = [rms < SILENT_RMS for rms, _ in chunks]
    noisy = [
        not clipped[index] and NOISY_RMS <= rms and speech > 0 and speech / max(rms, 1e-6) < NOISY_RATIO
        and _steady(levels, index)
        for index, rms in enumerate(levels)
    ]
    spans = (_merge(clipped, "clipped", MIN_CLIPPED_MS) + _merge(silent, "silent", MIN_SILENT_MS)
             + _merge(noisy, "noisy", MIN_NOISY_MS))
    return sorted(spans, key=lambda span: (span.start_ms, span.kind))


def _steady(levels: list[float], index: int, window: int = 1) -> bool:
    """Noise is steady; speech comes and goes. A chunk is noise-like when its
    neighbours sit within 40% of it. One chunk either side: a wider window
    would trim a real noise span by its width at each end."""
    around = levels[max(0, index - window): index + window + 1]
    middle = levels[index]
    return all(abs(level - middle) <= 0.4 * middle for level in around)


def span_audio(pcm16: bytes, span: Span, *, sample_rate: int = 16000, channels: int = 1,
               context_ms: int = 300) -> bytes:
    """The bytes of one span with ``context_ms`` either side, aligned to whole
    samples. A copy: the recording itself is never changed."""
    frame = 2 * max(1, channels)
    per_ms = sample_rate * frame / 1000.0
    start = max(0, int((span.start_ms - context_ms) * per_ms) // frame * frame)
    end = min(len(pcm16), int((span.end_ms + context_ms) * per_ms) // frame * frame)
    return bytes(pcm16[start:end])


def as_metadata(spans: list[Span]) -> list[dict]:
    return [{"kind": span.kind, "start_ms": span.start_ms, "end_ms": span.end_ms} for span in spans]
