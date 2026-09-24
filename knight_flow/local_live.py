"""Local live captions: growing words while the trigger is held (X-416).

The batch session already transcribes closed speech segments during the hold
(X-405) and keeps the results in futures nobody shows. This module turns
those results, plus a rolling decode of the open segment, into the partial
text the Pill's caption line displays. The release path never reads any of
it: the finished text comes from the batch path exactly as before.

Pure pieces plus one thread runner. No Tk, no sockets, no audio device.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable


class LivePartials:
    """Closed-segment texts in segment order, then the open segment's tail."""

    def __init__(self) -> None:
        self._pieces: dict[int, str] = {}
        self._tail = ""
        self._lock = threading.Lock()

    def set_piece(self, index: int, text: str) -> None:
        with self._lock:
            self._pieces[int(index)] = text.strip()
            # The closed segment now covers what the tail was previewing.
            self._tail = ""

    def set_tail(self, text: str) -> None:
        with self._lock:
            self._tail = text.strip()

    def clear(self) -> None:
        with self._lock:
            self._pieces.clear()
            self._tail = ""

    def text(self) -> str:
        with self._lock:
            ordered = [self._pieces[key] for key in sorted(self._pieces)]
            return " ".join(part for part in [*ordered, self._tail] if part).strip()


# An 8 s window lands in the 10 s DirectML bucket every time, so a warm engine
# never compiles a new shape mid-hold (local_stt.GPU_BUCKETS_S). Long enough
# for a sentence of context, short enough to decode in ~0.2 s on a GPU.
TAIL_WINDOW_SECONDS = 8.0
# How often the open segment is decoded. Tail latency is roughly cadence plus
# one decode; measured numbers live in docs/LIVE_CAPTIONS_LOCAL.md.
DECODE_CADENCE_SECONDS = 0.8
MIN_TAIL_SECONDS = 1.0


def tail_window(start: int, end: int, sample_rate: int, channels: int) -> tuple[int, int] | None:
    """The byte span of the open segment worth decoding now, or None.

    Never more than TAIL_WINDOW_SECONDS, always ending at `end`, both ends on
    a PCM16 frame boundary so the WAV writer sees whole frames."""
    frame = 2 * max(1, int(channels))
    bytes_per_second = frame * max(1, int(sample_rate))
    end -= end % frame
    if end - start < MIN_TAIL_SECONDS * bytes_per_second:
        return None
    window_start = max(start, end - int(TAIL_WINDOW_SECONDS * bytes_per_second))
    window_start += (-window_start) % frame
    return (window_start, end)


def decode_due(*, now: float, last: float | None) -> bool:
    return last is None or (now - last) >= DECODE_CADENCE_SECONDS


def live_captions_wanted(config: dict[str, Any] | None, *, provider_id: str, gpu: bool) -> bool:
    """The toggle, on the local route. `gpu` is accepted for the record and
    not required: an 8 s window decoded in 0.42 s on the RTX 3090 and 0.38 s
    on the i7-8700's six cores (scripts/measure_local_live_latency.py), so a
    CPU carries the preview too. A slower machine is protected by the
    decoder's adaptive cadence, never by a refusal."""
    stt = (config or {}).get("stt", {}) if isinstance(config, dict) else {}
    return bool(stt.get("local_live_captions", False)) and provider_id == "local"


class LiveTailDecoder:
    """Decode the open segment's tail on a cadence and publish the joined text.

    One thread, one decode at a time, never touching the session's buffer
    except through `audio_slice` (a copy of a byte range). `decode` is the
    session's own local transcribe on a WAV of that slice; on a warm GPU it
    costs about 0.2 s for the 10 s bucket. A decode that raises is logged and
    the loop continues: a preview may miss a beat, the dictation may not."""

    def __init__(
        self,
        *,
        partials: LivePartials,
        tail_span: Callable[[], tuple[int, int]],
        audio_slice: Callable[[int, int], bytes],
        decode: Callable[[bytes], str],
        on_text: Callable[[str], None],
        sample_rate: int,
        channels: int,
        cadence_seconds: float = DECODE_CADENCE_SECONDS,
    ) -> None:
        self.partials = partials
        self._tail_span = tail_span
        self._audio_slice = audio_slice
        self._decode = decode
        self._on_text = on_text
        self._sample_rate = int(sample_rate)
        self._channels = int(channels)
        self._base_cadence = float(cadence_seconds)
        self._cadence = float(cadence_seconds)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="TalkDatLiveTail", daemon=True)
        self._thread.start()

    def stop(self, timeout: float | None = 0.5) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout)

    def cancel(self) -> None:
        self.stop(timeout=0.5)
        self.partials.clear()

    def publish_piece(self, index: int, text: str) -> None:
        """A closed segment's text arrived (a progressive future finished)."""
        self.partials.set_piece(index, text)
        self._publish()

    def _publish(self) -> None:
        try:
            self._on_text(self.partials.text())
        except Exception:  # the caption strip must never take the mic down
            pass

    def _run(self) -> None:
        last: float | None = None
        while not self._stop.is_set():
            now = time.monotonic()
            if last is not None and (now - last) < self._cadence:
                self._stop.wait(0.02)
                continue
            last = now
            try:
                start, end = self._tail_span()
                window = tail_window(start, end, self._sample_rate, self._channels)
                if window is None:
                    continue
                text = self._decode(self._audio_slice(*window))
            except Exception:
                continue
            # A machine that needs a second per decode gets a two-second
            # cadence, so the preview never eats the CPU the dictation needs.
            self._cadence = max(self._base_cadence, 2.0 * (time.monotonic() - now))
            if self._stop.is_set():
                return
            self.partials.set_tail(text)
            self._publish()
