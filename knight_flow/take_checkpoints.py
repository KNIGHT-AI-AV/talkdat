"""T8: a long take survives a crash at its last verified checkpoint.

What already exists: AudioSafetyCapture (audio_spool.py) writes every take's
audio to disk as it is captured, fsync'd every half second, and a take that
never finished is offered for recovery. During a long hold the session also
closes segments at pauses and transcribes them in the background (X-405/X-31,
stt_sessions.py). What does not survive is that progress: the segment texts
live in memory, so recovery transcribes the WHOLE recording again -- ten
minutes of speech re-run to recover the last twenty seconds.

A checkpoint is one finished segment written next to the audio: its index,
the byte range of the audio it covers, and its text. Recovery keeps the
contiguous run of checkpoints from the start, transcribes ONLY the audio after
the last kept one, and joins the two with the same seam repair the live path
uses (progressive.join_segment_texts). So:

* every checkpoint that reached the disk is recovered as it was transcribed;
* no completed span repeats, because the remainder starts exactly where the
  kept checkpoints end, on the same byte offsets the audio file holds;
* nothing completed is dropped, because a checkpoint is kept only when the
  audio it describes is actually on disk and every earlier one is too;
* what was never checkpointed -- the tail after the last pause -- is simply
  transcribed from the audio, and its length is reported, never hidden.

A take whose words may not be kept (History off) stores no checkpoint text,
and recovery then transcribes the whole take as before. A password take keeps
nothing at all (AudioSafetyCapture.discard).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class Checkpoint:
    index: int
    start: int
    end: int
    text: str


@dataclass(frozen=True)
class ResumePlan:
    kept: tuple[Checkpoint, ...]
    remainder_start: int
    audio_bytes: int
    bytes_per_second: int

    @property
    def kept_seconds(self) -> float:
        return self.remainder_start / max(1, self.bytes_per_second)

    @property
    def remainder_seconds(self) -> float:
        return max(0, self.audio_bytes - self.remainder_start) / max(1, self.bytes_per_second)


def add_checkpoint(metadata: dict[str, Any], index: int, start: int, end: int, text: str, *,
                   keep_words: bool = True) -> dict[str, Any]:
    """The take's metadata with one more checkpoint. A repeat of an index
    replaces it; a take whose words are not kept records the range only."""
    entry = {"index": int(index), "start": int(start), "end": int(end), "text": str(text or "") if keep_words else None}
    checkpoints = [item for item in metadata.get("checkpoints") or [] if isinstance(item, dict)
                   and item.get("index") != entry["index"]]
    checkpoints.append(entry)
    checkpoints.sort(key=lambda item: int(item.get("index", 0)))
    return {**metadata, "checkpoints": checkpoints}


def verified_checkpoints(metadata: dict[str, Any], audio_bytes: int) -> list[Checkpoint]:
    """The contiguous run of checkpoints from the take's start whose audio is on
    disk and whose text was kept. Stops at the first gap, overlap, missing text
    or range past the end of the audio."""
    kept: list[Checkpoint] = []
    position = 0
    expected = 0
    for item in sorted((item for item in metadata.get("checkpoints") or [] if isinstance(item, dict)),
                       key=lambda item: int(item.get("index", 0))):
        try:
            checkpoint = Checkpoint(int(item["index"]), int(item["start"]), int(item["end"]), item["text"])
        except (KeyError, TypeError, ValueError):
            break
        if checkpoint.index != expected or checkpoint.text is None:
            break
        if checkpoint.start < position or checkpoint.end <= checkpoint.start or checkpoint.end > audio_bytes:
            break
        kept.append(checkpoint)
        position = checkpoint.end
        expected += 1
    return kept


def resume_plan(metadata: dict[str, Any], audio_bytes: int) -> ResumePlan:
    sample_rate = int(metadata.get("sample_rate") or 16000)
    channels = int(metadata.get("channels") or 1)
    kept = verified_checkpoints(metadata, audio_bytes)
    return ResumePlan(tuple(kept), kept[-1].end if kept else 0, int(audio_bytes), sample_rate * channels * 2)


def resume(plan: ResumePlan, pcm16: bytes, transcribe: Callable[[bytes], str]) -> str:
    """The take's text: the kept checkpoints as transcribed, then ONLY the audio
    after them. Gaps between kept checkpoints (silence the planner skipped) are
    not re-transcribed; the planner closes segments at pauses, so they hold no
    speech that a checkpoint did not already cover."""
    from .progressive import join_segment_texts

    pieces = [checkpoint.text for checkpoint in plan.kept]
    remainder = pcm16[plan.remainder_start:]
    if len(remainder) > 512:
        pieces.append(transcribe(remainder).strip())
    return join_segment_texts([piece for piece in pieces if piece])
