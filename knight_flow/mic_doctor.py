"""X-27: Mic Doctor. Twenty seconds that prevent a hundred refunds.

"It heard me wrong" is almost never the model -- it is a mic set to the
wrong device, a gain floor of nothing, or input so hot it clips. This
module turns one short sample into a verdict a person can act on, and the
same metrics power the mid-session health warning.

Pure analysis over PCM16; capture and UI live with their owners.
"""

from __future__ import annotations

import math
from array import array
from dataclasses import dataclass


@dataclass(frozen=True)
class MicReport:
    speech_rms: float      # loudness while speaking (0..1)
    noise_floor: float     # loudness of the quietest stretch (0..1)
    clipping_ratio: float  # fraction of samples at the rails
    verdict: str           # ok | too_quiet | too_hot | noisy | dead
    advice: str

    @property
    def healthy(self) -> bool:
        return self.verdict == "ok"

    @property
    def snr_db(self) -> float:
        if self.noise_floor <= 0:
            return 60.0
        return 20.0 * math.log10(max(self.speech_rms, 1e-6) / self.noise_floor)


def _chunk_rms(samples: array, start: int, end: int) -> float:
    window = samples[start:end]
    if not window:
        return 0.0
    return math.sqrt(sum(s * s for s in window) / len(window)) / 32768.0


def analyze_sample(pcm16: bytes, *, sample_rate: int = 16000) -> MicReport:
    """One spoken sample in, one actionable verdict out.

    Chunked at 100ms: speech level is the mean of the loudest third of
    chunks, the noise floor is the mean of the quietest fifth -- so the
    pauses between words measure the room, and the words measure the mic.
    """
    if len(pcm16) < 2:
        return MicReport(0.0, 0.0, 0.0, "dead", "No audio arrived at all. Pick a different microphone below.")
    samples = array("h")
    samples.frombytes(pcm16[: len(pcm16) - (len(pcm16) % 2)])
    if not samples:
        return MicReport(0.0, 0.0, 0.0, "dead", "No audio arrived at all. Pick a different microphone below.")

    step = max(1, sample_rate // 10)
    rms_values = [
        _chunk_rms(samples, start, start + step)
        for start in range(0, len(samples), step)
    ]
    rms_values = [value for value in rms_values if value >= 0]
    if not rms_values:
        return MicReport(0.0, 0.0, 0.0, "dead", "No audio arrived at all. Pick a different microphone below.")
    ordered = sorted(rms_values)
    quiet_count = max(1, len(ordered) // 5)
    loud_count = max(1, len(ordered) // 3)
    noise_floor = sum(ordered[:quiet_count]) / quiet_count
    speech_rms = sum(ordered[-loud_count:]) / loud_count
    clipped = sum(1 for value in samples if abs(value) >= 32600)
    clipping_ratio = clipped / len(samples)

    if speech_rms < 0.0025:
        verdict, advice = "dead", "Nothing heard. The selected microphone may be muted or unplugged - pick another below."
    elif clipping_ratio > 0.02:
        verdict, advice = "too_hot", "The signal is clipping. Lower the microphone's input level, or move it a little further away."
    elif speech_rms < 0.015:
        verdict, advice = "too_quiet", "You are very quiet. Move the mic closer or raise its input level - the auto-gain will do the rest."
    elif noise_floor > 0.02 and speech_rms / max(noise_floor, 1e-6) < 3.0:
        verdict, advice = "noisy", "The room is nearly as loud as you are. A closer mic or less background noise will sharpen every word."
    else:
        verdict, advice = "ok", "This microphone sounds great. You are set."
    return MicReport(speech_rms, noise_floor, clipping_ratio, verdict, advice)


def health_warning(report: MicReport) -> str:
    """The one-line mid-session warning, or "" when there is nothing to say."""
    if report.verdict == "ok":
        return ""
    return {
        "dead": "The mic went silent - check it is still connected.",
        "too_hot": "The mic is clipping - lower its input level.",
        "too_quiet": "You are coming through very quietly.",
        "noisy": "Background noise is drowning the words.",
    }.get(report.verdict, "")
