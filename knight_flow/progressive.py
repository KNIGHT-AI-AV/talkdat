"""X-31: the progressive pipeline. Long dictations stop paying for their
length twice.

Mayowa's own framing: while he is mid-ramble, the first half could already
be transcribed during a pause -- then the tail is all that remains at
release, and one reconcile pass over the FULL text applies vocabulary,
retractions and formatting with complete context.

This module is the pure half: a planner that watches chunk sizes and
levels and decides where a segment closes. It never touches audio bytes --
the session owns those -- so every rule here is testable with numbers.

A segment closes when BOTH are true:
- enough voiced audio has accumulated (short bursts stay whole; the
  reconcile pass needs sentences, not syllables), and
- the speaker has been silent long enough that a clause boundary is more
  likely than a breath.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# X-456: the release pays only for the tail after the last closed segment,
# so the tail IS the wait between "I stopped talking" and formatting. His
# logged takes left 3 to 14 s tails behind 5.0 s / 0.65 s; 4.0 s of voice and
# a 0.45 s pause close sooner, and a clause that runs past LONG_SEGMENT_SECONDS
# without a real pause closes on the next 0.25 s dip, so a fast talker's tail
# is bounded instead of being the whole take.
MIN_SEGMENT_SECONDS = 4.0
SILENCE_CLOSE_SECONDS = 0.45
LONG_SEGMENT_SECONDS = 9.0
LONG_SEGMENT_CLOSE_SECONDS = 0.25
VOICE_LEVEL = 0.025


@dataclass
class SegmentPlanner:
    sample_rate: int
    channels: int = 1
    _bytes_seen: int = 0
    _segment_start: int = 0
    _voiced_seconds: float = 0.0
    _silence_seconds: float = 0.0
    boundaries: list[tuple[int, int]] = field(default_factory=list)

    def _seconds(self, chunk_bytes: int) -> float:
        frame = 2 * max(1, self.channels)
        return chunk_bytes / frame / max(1, self.sample_rate)

    def observe(self, chunk_bytes: int, level: float, voiced: bool | None = None) -> tuple[int, int] | None:
        """Feed one captured chunk; a returned (start, end) byte span means
        that segment is closed and may transcribe NOW.

        `voiced` is the VoiceGate's verdict when the caller has one. Without
        it the fixed VOICE_LEVEL applies, which is only honest for raw mic
        levels (X-405)."""
        duration = self._seconds(chunk_bytes)
        self._bytes_seen += chunk_bytes
        if voiced if voiced is not None else level >= VOICE_LEVEL:
            self._voiced_seconds += duration
            self._silence_seconds = 0.0
            return None
        self._silence_seconds += duration
        close_after = (
            LONG_SEGMENT_CLOSE_SECONDS
            if self._voiced_seconds >= LONG_SEGMENT_SECONDS
            else SILENCE_CLOSE_SECONDS
        )
        if (
            self._voiced_seconds >= MIN_SEGMENT_SECONDS
            and self._silence_seconds >= close_after
        ):
            span = (self._segment_start, self._bytes_seen)
            self.boundaries.append(span)
            self._segment_start = self._bytes_seen
            self._voiced_seconds = 0.0
            self._silence_seconds = 0.0
            return span
        return None

    def tail_span(self) -> tuple[int, int]:
        """Whatever remains after the last closed segment."""
        return (self._segment_start, self._bytes_seen)


class VoiceGate:
    """Voiced-or-silent, for a level the adaptive front end may have boosted.

    X-405: the planner compared post-front-end levels against a fixed
    VOICE_LEVEL of 0.025. The front end drives speech toward a target and
    lifts the pauses with it, so on the founder's PC a 67-second take never
    once dropped under the threshold: no segment closed, the whole take was
    transcribed after release, and release-to-text took 32 seconds. This gate
    judges each chunk against what THIS recording sounds like: a slow floor
    (the quietest recent level, allowed to drift up) and the running level of
    speech. A pause is anything well under both; speech is anything above.
    Pure and testable: numbers in, a bool out.
    """

    FLOOR_DRIFT = 1.002  # per chunk: the floor may rise ~10% a second, never faster
    FLOOR_RATIO = 2.0  # a pause sits under twice the floor
    SPEECH_RATIO = 0.35  # and under about a third of running speech
    SPEECH_SMOOTHING = 0.1

    def __init__(self) -> None:
        self.floor: float | None = None
        self.speech = 0.0

    def voiced(self, level: float) -> bool:
        level = max(0.0, float(level))
        if self.floor is None or level < self.floor:
            self.floor = level
        else:
            self.floor = min(level, self.floor * self.FLOOR_DRIFT)
        threshold = max(VOICE_LEVEL, self.floor * self.FLOOR_RATIO, self.speech * self.SPEECH_RATIO)
        if level >= threshold:
            self.speech = level if not self.speech else self.speech + (level - self.speech) * self.SPEECH_SMOOTHING
            return True
        return False
