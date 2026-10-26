"""T10: measure the editing dictation saves this person, instead of assuming it.

The Stats page shows "minutes saved" as words / 40 - words / 150 (history.py):
an assumed 40-word-a-minute typist against an assumed 150-word-a-minute
speaker. It flatters everyone equally and is true of no one in particular. A
fast typist who corrects half of every dictation may lose time by dictating,
and the counter can never say so.

This is the measurement instead, opt-in and local:

* a short typing baseline inside Talk DAT's own practice box -- the time to
  type a given passage and the corrections made while doing it (backspaces in
  that box; nothing outside it is watched, ever);
* matched dictation tasks of the same length, in an order that alternates with
  the typing tasks so neither is always done tired or always done fresh;
* each task's completion time INCLUDING the corrections after the dictation.

The result is the median net time per word, typing against dictating, with the
spread and the number of tasks behind it, reported as MEASURED and shown apart
from the old estimate, which stays labeled as an estimate. A result that says
dictation is slower for this person is a valid result and is shown as such.
Nothing here is sent anywhere, and no text is kept: only counts and seconds.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

#: Fewer tasks than this per mode and the result says "not enough to tell".
MIN_TASKS = 3


@dataclass(frozen=True)
class Task:
    mode: str            # "typing" or "dictation"
    words: int
    seconds: float       # until the text was finished, corrections included
    corrections: int = 0  # edits made in Talk DAT's own box

    @property
    def seconds_per_word(self) -> float:
        return self.seconds / max(1, self.words)


def task_order(pairs: int, *, start_with_typing: bool) -> list[str]:
    """Alternating modes (ABBA), so practice and fatigue fall on both evenly."""
    first, second = ("typing", "dictation") if start_with_typing else ("dictation", "typing")
    order: list[str] = []
    for index in range(pairs):
        order += [first, second] if index % 2 == 0 else [second, first]
    return order


@dataclass(frozen=True)
class Measurement:
    enough: bool
    typing_tasks: int
    dictation_tasks: int
    typing_median_spw: float
    dictation_median_spw: float
    #: Negative = dictation is faster. Seconds per word, median of each mode.
    net_seconds_per_word: float
    #: (low, high) spread of dictation's seconds per word: the inter-quartile range.
    dictation_spread: tuple[float, float]
    median_change: float  # dictation's completion time relative to typing, e.g. -0.25 = 25% faster

    def minutes_saved(self, words: int) -> float:
        """Measured minutes saved for this many dictated words (negative = lost)."""
        return -self.net_seconds_per_word * max(0, words) / 60.0


def _spread(values: list[float]) -> tuple[float, float]:
    if len(values) < 2:
        return (values[0], values[0]) if values else (0.0, 0.0)
    quartiles = statistics.quantiles(values, n=4, method="inclusive")
    return quartiles[0], quartiles[2]


def measure(tasks: list[Task]) -> Measurement:
    typing = [task.seconds_per_word for task in tasks if task.mode == "typing" and task.words > 0]
    dictation = [task.seconds_per_word for task in tasks if task.mode == "dictation" and task.words > 0]
    enough = len(typing) >= MIN_TASKS and len(dictation) >= MIN_TASKS
    typing_median = statistics.median(typing) if typing else 0.0
    dictation_median = statistics.median(dictation) if dictation else 0.0
    change = (dictation_median - typing_median) / typing_median if typing_median else 0.0
    return Measurement(enough, len(typing), len(dictation), typing_median, dictation_median,
                       dictation_median - typing_median, _spread(dictation), change)


def estimated_minutes_saved(words: int) -> float:
    """The old counter, unchanged, for the row that stays labeled an estimate."""
    return max(0.0, words / 40 - words / 150)


def stats_rows(measurement: Measurement | None, words: int) -> list[dict]:
    """What the Stats page shows: the estimate always, labeled as one; the
    measurement only when there is enough of it, labeled as measured."""
    rows = [{"label": "estimated", "minutes": round(estimated_minutes_saved(words))}]
    if measurement is not None and measurement.enough:
        rows.append({"label": "measured", "minutes": round(measurement.minutes_saved(words), 1),
                     "tasks": measurement.typing_tasks + measurement.dictation_tasks,
                     "median_change": round(measurement.median_change, 3)})
    return rows


#: The newest practice tasks kept; older ones fall off.
MAX_TASKS = 60


def record_task(config: dict, mode: str, words: int, seconds: float, corrections: int = 0) -> dict | None:
    """T10: one practice task (typing or dictation, timed in Talk DAT's own
    box), kept on this computer -- only after the person turned the
    measurement on. Counts and times only, never any text. None when refused."""
    import math

    measure_config = config.get("editing_measure") if isinstance(config, dict) else None
    if not isinstance(measure_config, dict) or measure_config.get("enabled") is not True:
        return None
    if mode not in ("typing", "dictation") or type(words) is not int or not 1 <= words <= 2000:
        return None
    if type(seconds) not in (int, float) or not math.isfinite(seconds) or not 0 < seconds <= 3600:
        return None
    if type(corrections) is not int or not 0 <= corrections <= 1000:
        return None
    task = {"mode": mode, "words": words, "seconds": round(float(seconds), 2), "corrections": corrections}
    kept = [item for item in measure_config.get("tasks") or [] if isinstance(item, dict)]
    measure_config["tasks"] = (kept + [task])[-MAX_TASKS:]
    return task
