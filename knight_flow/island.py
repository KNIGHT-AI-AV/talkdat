from __future__ import annotations

"""The message model: every message is the Pill itself changing shape (X-740).

The owner rejected messages that "look like a separate piece" and asked for
parts that "morph out of the same asset design element universe, not a weird
overlay". So on the desktop there is no toast window any more: the Pill
lengthens. Its end nearest a side of the screen stays exactly where it is, the
capsule stretches away from it (and rises away from the edge it sits on), the
Pill's own art compresses into the capsule's cap, and the words sit on the same
art, frosted. A message with a button adds a segment of the Pill instead.

This module is the part of that which needs no display: which end stays put and
where the capsule goes (pill_frame), how the three springs move (spring,
PillMotion), how long a message stays (hold_ms), and which message shows when
several arrive (MessageQueue, the rules of the message spec's section 11). No
tkinter here, the way pill_motion.py, ui/flyout.py and
web_shell/menu_geometry.py are, so every rule is tested without a window.
"""

import math
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

TONES = ("info", "done", "warn", "error", "busy")
ORIGINS = ("person", "system", "pill-menu")

# ---------------------------------------------------------------------------
# Springs (message spec 9.1). (response in seconds, damping ratio).
# ---------------------------------------------------------------------------

#: The length on the way out keeps SwiftUI's default damping, the one small
#: settle the Dynamic Island has; everything else is critically damped.
GROW_LENGTH = (0.36, 0.825)
GROW_HEIGHT = (0.30, 1.0)
COMPRESS = (0.26, 1.0)
CONTRACT = (0.26, 1.0)
REPLACE = (0.30, 1.0)
PREEMPT = (0.18, 1.0)

#: Content timing (ms): words arrive once the cap has landed and leave first.
TONE_IN = (90.0, 300.0)
TEXT_IN = (180.0, 340.0)
TEXT_OUT_MS = 90.0
CONTRACT_DELAY_MS = 60.0
PREEMPT_TEXT_OUT_MS = 60.0
REPLACE_TEXT_IN = (90.0, 250.0)
TONE_CHANGE_MS = 210.0
#: Reduced motion (and a machine that cannot draw the stretch in time): the
#: lengthened Pill cross-fades with the resting one, nothing travels.
FADE_MS = 120.0
DOWNGRADED_FADE_MS = 33.0
NUDGE_MS = 220.0
NUDGE_SCALE = 0.03


def spring(t: float, response: float, damping: float) -> float:
    """Progress (0 at rest, 1 at target) of a spring ``t`` seconds after release.

    With ``w = 2 pi / response``: ``1 - (1 + w t) e^(-w t)`` critically damped,
    else ``1 - e^(-d w t) (cos(wd t) + (d w / wd) sin(wd t))`` with
    ``wd = w sqrt(1 - d^2)``. The same formula generated the approved renders.
    """
    if t <= 0.0:
        return 0.0
    w = 2.0 * math.pi / max(1e-6, float(response))
    if damping >= 1.0:
        return 1.0 - (1.0 + w * t) * math.exp(-w * t)
    wd = w * math.sqrt(1.0 - damping * damping)
    return 1.0 - math.exp(-damping * w * t) * (math.cos(wd * t) + (damping * w / wd) * math.sin(wd * t))


def settle_ms(response: float, damping: float, epsilon: float = 0.001) -> float:
    """The last moment (ms) the spring is further than ``epsilon`` from 1."""
    last = 0.0
    t = 0.0
    while t < 3.0:
        if abs(1.0 - spring(t, response, damping)) > epsilon:
            last = t
        t += 0.0005
    return last * 1000.0


def _bezier(p1x: float, p1y: float, p2x: float, p2y: float) -> Callable[[float], float]:
    def solve(x: float) -> float:
        x = max(0.0, min(1.0, x))
        lo, hi = 0.0, 1.0
        for _ in range(32):
            t = (lo + hi) / 2
            bx = 3 * (1 - t) ** 2 * t * p1x + 3 * (1 - t) * t ** 2 * p2x + t ** 3
            if bx < x:
                lo = t
            else:
                hi = t
        t = (lo + hi) / 2
        return 3 * (1 - t) ** 2 * t * p1y + 3 * (1 - t) * t ** 2 * p2y + t ** 3

    return solve


#: cubic-bezier(.2,.8,.2,1) for content arriving, (.4,0,1,1) for it leaving.
EASE_OUT = _bezier(0.2, 0.8, 0.2, 1.0)
EASE_IN = _bezier(0.4, 0.0, 1.0, 1.0)


# ---------------------------------------------------------------------------
# How long a message stays (message spec section 10).
# ---------------------------------------------------------------------------

WORD_HOLD_MS = 6000
UPDATE_HOLD_MS = 20000
HOVER_RESUME_FLOOR_MS = 1200


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def word_count(title: str, detail: str = "") -> int:
    return len(f"{title} {detail}".split())


def hold_ms(tone: str, title: str, detail: str = "", *, segment: str = "") -> int | None:
    """Reading time. None for busy: it stays until the work it names changes."""
    if segment == "word":
        return WORD_HOLD_MS
    if segment == "update":
        return UPDATE_HOLD_MS
    words = word_count(title, detail)
    if tone == "busy":
        return None
    if tone == "error":
        # The same formula the error toast had (pill_motion.error_toast_hold_ms).
        return int(_clamp(1200 + 220 * words, 4000, 8000))
    if tone == "warn":
        return int(_clamp(1200 + 240 * words, 3000, 6000))
    return int(_clamp(900 + 240 * words, 1800, 4500))


def resumed_hold_ms(original_ms: int) -> int:
    """After the pointer leaves: half the original time, never under 1.2 s."""
    return max(HOVER_RESUME_FLOOR_MS, int(original_ms) // 2)


# ---------------------------------------------------------------------------
# set_state(..., say=...)  (message spec 14.1)
# ---------------------------------------------------------------------------

STATE_TONES = {
    "captured": "done",
    "idle": "info",
    "processing": "busy",
    "starting": "busy",
    "connected": "busy",
    "error": "error",
}


def say_tone(state: str, say: bool | str | None) -> str | None:
    """The tone a state change speaks with, or None for a silent one.

    ``say=None`` keeps today's behaviour: only an error speaks. ``True`` speaks
    with the state's own tone; a tone name speaks with that tone; ``False``
    silences even an error.
    """
    normalized = str(state).strip().lower()
    if say is None:
        return "error" if normalized == "error" else None
    if say is False:
        return None
    if say is True:
        return STATE_TONES.get(normalized)
    text = str(say).strip().lower()
    return text if text in TONES else None


# ---------------------------------------------------------------------------
# Where the Pill stretches (message spec section 3).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int

    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def bottom(self) -> int:
        return self.y + self.h

    @property
    def cx(self) -> float:
        return self.x + self.w / 2.0

    @property
    def cy(self) -> float:
        return self.y + self.h / 2.0

    def inflate(self, amount: int) -> "Rect":
        return Rect(self.x - amount, self.y - amount, self.w + 2 * amount, self.h + 2 * amount)

    def intersects(self, other: "Rect") -> bool:
        return self.x < other.right and other.x < self.right and self.y < other.bottom and other.y < self.bottom

    def contains_point(self, x: float, y: float) -> bool:
        return self.x <= x < self.right and self.y <= y < self.bottom

    def union(self, other: "Rect") -> "Rect":
        left, top = min(self.x, other.x), min(self.y, other.y)
        right, bottom = max(self.right, other.right), max(self.bottom, other.bottom)
        return Rect(left, top, right - left, bottom - top)

    def offset(self, dx: int, dy: int) -> "Rect":
        return Rect(self.x + dx, self.y + dy, self.w, self.h)

    @classmethod
    def from_edges(cls, left: int, top: int, right: int, bottom: int) -> "Rect":
        return cls(int(left), int(top), int(right - left), int(bottom - top))


@dataclass(frozen=True)
class Placement:
    """The lengthened capsule: its rectangle, which end stays, which way it rises."""

    rect: Rect
    pin: str  # "left" | "right": the end that stays exactly where the Pill's end is
    vgrow: str  # "up" | "down" | "center": away from the edge the Pill sits on
    home: str  # "bottom" | "top" | "left" | "right"
    compact: bool = False


PIN_TOLERANCE = 2
CARET_CLEARANCE = 24


def home_edge(pill: Rect, work: Rect) -> str:
    """The work-area edge nearest the Pill's centre (bottom wins a tie)."""
    distances = {
        "bottom": work.bottom - pill.cy,
        "top": pill.cy - work.y,
        "left": pill.cx - work.x,
        "right": work.right - pill.cx,
    }
    return min(distances, key=lambda name: distances[name])


def pinned_end(pill: Rect, work: Rect, home: str) -> str:
    """The end nearer a side of the work area. A centred Pill pins its left
    end, where reading starts; a Pill docked against a side pins that side."""
    if home in ("left", "right"):
        return home
    left_gap = pill.x - work.x
    right_gap = work.right - pill.right
    return "right" if right_gap < left_gap - PIN_TOLERANCE else "left"


def _grow_direction(home: str) -> str:
    return {"bottom": "up", "top": "down"}.get(home, "center")


def _capsule_at(pill: Rect, pin: str, vgrow: str, width: int, height: int, inner: Rect) -> Rect:
    x = pill.x if pin == "left" else pill.right - width
    if vgrow == "up":
        y = pill.bottom - height
    elif vgrow == "down":
        y = pill.y
    else:
        y = int(round(pill.cy - height / 2.0))
    # Taller than the gap it has (a Pill hugging an edge closer than the
    # margin): keep the capsule on screen rather than refuse to speak.
    if inner.h >= height:
        y = int(_clamp(y, inner.y, inner.bottom - height))
    return Rect(int(x), int(y), int(width), int(height))


def pill_frame(
    pill: Rect,
    work: Rect,
    size: tuple[int, int],
    *,
    caret: Rect | None = None,
    margin: int = 12,
    compact_size: tuple[int, int] | None = None,
) -> Placement:
    """Which end of the Pill stays pinned, and the lengthened capsule's rectangle.

    1. The Pill grows taller away from its home edge (the nearest edge).
    2. Along its length the end nearer a side stays exactly where it is.
    3. If the stretch would leave the work area the other end is pinned; if
       neither fits, the compact form (``compact_size``).
    4. A known caret, inflated by 24 px, is never covered if another choice
       exists; when none does the compact form shows anyway, because a message
       must never be lost and the Pill already sits there.
    """
    width, height = max(1, int(size[0])), max(1, int(size[1]))
    home = home_edge(pill, work)
    vgrow = _grow_direction(home)
    first = pinned_end(pill, work, home)
    other = "left" if first == "right" else "right"
    inner = work.inflate(-int(margin))

    def fits(rect: Rect) -> bool:
        return rect.x >= inner.x and rect.right <= inner.right

    def clear_of_caret(rect: Rect) -> bool:
        return caret is None or not rect.inflate(CARET_CLEARANCE).intersects(caret)

    candidates: list[tuple[str, int, int, bool]] = [(first, width, height, False), (other, width, height, False)]
    if compact_size is not None:
        small_w, small_h = max(1, int(compact_size[0])), max(1, int(compact_size[1]))
        candidates += [(first, small_w, small_h, True), (other, small_w, small_h, True)]
    fitting = [
        (pin, w, h, compact, _capsule_at(pill, pin, vgrow, w, h, inner))
        for pin, w, h, compact in candidates
    ]
    fitting = [entry for entry in fitting if fits(entry[4])]
    for pin, _w, _h, compact, rect in fitting:
        if clear_of_caret(rect):
            return Placement(rect, pin, vgrow, home, compact)
    if fitting:
        # Nothing clears the caret: the compact form anyway, where the Pill is.
        compact_fits = [entry for entry in fitting if entry[3]]
        pin, _w, _h, compact, rect = (compact_fits or fitting)[0]
        return Placement(rect, pin, vgrow, home, compact)
    # Nothing fits either way (a very narrow work area): the compact form,
    # slid inside the work area. The pinned end moves; the words are kept.
    w, h = compact_size if compact_size is not None else (width, height)
    w = min(int(w), max(1, inner.w))
    rect = _capsule_at(pill, first, vgrow, w, int(h), inner)
    rect = Rect(int(_clamp(rect.x, inner.x, max(inner.x, inner.right - w))), rect.y, rect.w, rect.h)
    return Placement(rect, first, vgrow, home, True)


def envelope(pill: Rect, placement: Placement, *, overshoot: float = 0.02) -> Rect:
    """The window that holds the whole message: the Pill, the capsule, and the
    length spring's 1% settle past the target on the stretch side."""
    rect = placement.rect
    extra = int(math.ceil(rect.w * overshoot)) + 1
    if placement.pin == "left":
        grown = Rect(rect.x, rect.y, rect.w + extra, rect.h)
    else:
        grown = Rect(rect.x - extra, rect.y, rect.w + extra, rect.h)
    return pill.union(grown)


# ---------------------------------------------------------------------------
# Sizes (message spec 5.1 and 5.2), in design pixels; the caller scales them.
# ---------------------------------------------------------------------------

CAP = 44
FEATHER = 18
TEXT_GAP = 14
TRAIL = 22
MAX_WIDTH = 480
COMPACT_MAX_WIDTH = 320
LINE = 18
ONE_LINE_HEIGHT = 36
MAX_TITLE_LINES = 2
MAX_DETAIL_LINES = 3
SEGMENT_HEIGHT = 36
SEGMENT_TEXT_GAP = 16
SEGMENT_ACTION_GAP = 8
SEGMENT_TRAIL = 6
ACTION_HEIGHT = 28
ACTION_HIT = 44


def capsule_height(lines: int) -> int:
    """36 for one line, 54 for two, +18 for each line after (design px)."""
    return ONE_LINE_HEIGHT + LINE * max(0, int(lines) - 1)


def capsule_width(words_width: float, *, work_width: int, margin: int = 12, compact: bool = False) -> int:
    """cap 44 + 14 + words + 22, capped at min(480, work - 2 x 12) (design px)."""
    limit = min(COMPACT_MAX_WIDTH if compact else MAX_WIDTH, max(1, int(work_width) - 2 * int(margin)))
    return int(min(limit, math.ceil(CAP + TEXT_GAP + float(words_width) + TRAIL)))


# ---------------------------------------------------------------------------
# Motion (message spec 9.2): three independent springs and two schedules,
# every one starting from the value presented on screen.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Shape:
    """One frame of the lengthened Pill, in device pixels and 0..1 levels."""

    w: float
    h: float
    head: float  # the art's width at the pinned end: the Pill's own, down to the cap
    feather: float  # the soft blend from the cap into the frosted body
    text: float = 0.0  # the current words' opacity
    text_old: float = 0.0  # the words being replaced, on their way out
    tone: float = 0.0  # strength of the current tone look over the capsule
    tone_mix: float = 1.0  # 0 = the previous tone's look, 1 = the new one's
    mix: float = 1.0  # reduced motion: 1 = the lengthened Pill, 0 = the resting one
    pulse: float = 1.0  # the repeat nudge (1.03 at its peak)


_SETTLE_CACHE: dict[tuple[float, float], float] = {}


def _cached_settle(response: float, damping: float) -> float:
    # settle_ms is a 6,000-step scan and every frame asks whether it is done.
    key = (float(response), float(damping))
    if key not in _SETTLE_CACHE:
        _SETTLE_CACHE[key] = settle_ms(*key)
    return _SETTLE_CACHE[key]


@dataclass
class _Spring:
    start: float
    target: float
    begun_ms: float
    response: float
    damping: float
    delay_ms: float = 0.0

    def value(self, now_ms: float) -> float:
        t = (now_ms - self.begun_ms - self.delay_ms) / 1000.0
        if t <= 0.0:
            return self.start
        return self.start + (self.target - self.start) * spring(t, self.response, self.damping)

    def settled(self, now_ms: float) -> bool:
        if self.start == self.target:
            return True
        return now_ms - self.begun_ms - self.delay_ms >= _cached_settle(self.response, self.damping)


@dataclass
class _Ramp:
    start: float
    target: float
    begun_ms: float
    delay_ms: float
    duration_ms: float
    curve: Callable[[float], float] = EASE_OUT

    def value(self, now_ms: float) -> float:
        t = now_ms - self.begun_ms - self.delay_ms
        if t <= 0.0:
            return self.start
        if t >= self.duration_ms or self.duration_ms <= 0:
            return self.target
        return self.start + (self.target - self.start) * self.curve(t / self.duration_ms)

    def settled(self, now_ms: float) -> bool:
        return self.start == self.target or now_ms - self.begun_ms - self.delay_ms >= self.duration_ms


def _hold(value: float, now_ms: float) -> _Ramp:
    return _Ramp(value, value, now_ms, 0.0, 0.0)


class PillMotion:
    """The lengthened Pill over time.

    ``rest`` is the Pill (its own width and height, its art filling it);
    ``target`` is the capsule. Every transition starts from ``sample(now)``,
    the value on screen, so an interruption continues from where the part is
    and never from its target.
    """

    def __init__(self, rest: Shape, now_ms: float, *, reduced: bool = False, fade_ms: float = FADE_MS) -> None:
        self.rest = rest
        self.reduced = bool(reduced)
        self.fade_ms = float(fade_ms)
        self.phase = "rest"
        self._geometry: dict[str, _Spring] = {
            name: _Spring(getattr(rest, name), getattr(rest, name), now_ms, 1.0, 1.0)
            for name in ("w", "h", "head", "feather")
        }
        self._text = _hold(0.0, now_ms)
        self._text_old = _hold(0.0, now_ms)
        self._tone: _Spring | _Ramp = _hold(0.0, now_ms)
        self._tone_mix = _hold(1.0, now_ms)
        self._mix = _hold(1.0 if not self.reduced else 0.0, now_ms)
        self._pulse_at: float | None = None
        self.target = rest

    # -- the transitions ----------------------------------------------------

    def grow(self, target: Shape, now_ms: float) -> None:
        self.target = target
        self.phase = "in"
        if self.reduced:
            self._jump(target, now_ms)
            self._text = _hold(1.0, now_ms)
            self._tone = _hold(1.0, now_ms)
            self._mix = _Ramp(self.sample(now_ms).mix, 1.0, now_ms, 0.0, self.fade_ms, lambda x: x)
            return
        presented = self.sample(now_ms)
        springs = {"w": GROW_LENGTH, "h": GROW_HEIGHT, "head": COMPRESS, "feather": COMPRESS}
        for name, (response, damping) in springs.items():
            self._geometry[name] = _Spring(getattr(presented, name), getattr(target, name), now_ms, response, damping)
        self._text = _Ramp(presented.text, 1.0, now_ms, TEXT_IN[0], TEXT_IN[1] - TEXT_IN[0])
        self._tone = _Ramp(presented.tone, 1.0, now_ms, TONE_IN[0], TONE_IN[1] - TONE_IN[0])
        self._mix = _hold(1.0, now_ms)

    def contract(self, now_ms: float, *, preempt: bool = False) -> None:
        self.phase = "out"
        presented = self.sample(now_ms)
        self.target = self.rest
        if self.reduced:
            self._mix = _Ramp(presented.mix, 0.0, now_ms, 0.0, self.fade_ms, lambda x: x)
            return
        response, damping = PREEMPT if preempt else CONTRACT
        delay = 0.0 if preempt else CONTRACT_DELAY_MS
        for name in ("w", "h", "head", "feather"):
            self._geometry[name] = _Spring(getattr(presented, name), getattr(self.rest, name), now_ms,
                                           response, damping, delay)
        out_ms = PREEMPT_TEXT_OUT_MS if preempt else TEXT_OUT_MS
        self._text = _Ramp(presented.text, 0.0, now_ms, 0.0, out_ms, EASE_IN)
        self._text_old = _Ramp(presented.text_old, 0.0, now_ms, 0.0, out_ms, EASE_IN)
        self._tone = _Spring(presented.tone, 0.0, now_ms, response, damping, delay)

    def replace(self, target: Shape, now_ms: float, *, tone_changed: bool) -> None:
        """New words while out: the springs retarget, no contraction between."""
        presented = self.sample(now_ms)
        self.target = target
        self.phase = "in"
        if self.reduced:
            self._jump(target, now_ms)
            self._text_old = _Ramp(1.0, 0.0, now_ms, 0.0, self.fade_ms, lambda x: x)
            self._text = _Ramp(0.0, 1.0, now_ms, 0.0, self.fade_ms, lambda x: x)
            self._tone = _hold(1.0, now_ms)
            self._mix = _Ramp(presented.mix, 1.0, now_ms, 0.0, self.fade_ms, lambda x: x)
            return
        for name in ("w", "h", "head", "feather"):
            self._geometry[name] = _Spring(getattr(presented, name), getattr(target, name), now_ms, *REPLACE)
        self._text_old = _Ramp(max(presented.text, presented.text_old), 0.0, now_ms, 0.0, TEXT_OUT_MS, EASE_IN)
        self._text = _Ramp(0.0, 1.0, now_ms, REPLACE_TEXT_IN[0], REPLACE_TEXT_IN[1] - REPLACE_TEXT_IN[0])
        self._tone = _Ramp(presented.tone, 1.0, now_ms, 0.0, TONE_CHANGE_MS)
        self._tone_mix = _Ramp(0.0, 1.0, now_ms, 0.0, TONE_CHANGE_MS) if tone_changed else _hold(1.0, now_ms)
        self._mix = _hold(1.0, now_ms)

    def nudge(self, now_ms: float) -> None:
        """The same words again within 10 s: a 1.03 nudge, not a second message."""
        if not self.reduced:
            self._pulse_at = now_ms

    def _jump(self, target: Shape, now_ms: float) -> None:
        for name in ("w", "h", "head", "feather"):
            value = getattr(target, name)
            self._geometry[name] = _Spring(value, value, now_ms, 1.0, 1.0)

    # -- reading it ------------------------------------------------------------

    def sample(self, now_ms: float) -> Shape:
        pulse = 1.0
        if self._pulse_at is not None:
            age = now_ms - self._pulse_at
            if 0.0 <= age < NUDGE_MS:
                pulse = 1.0 + NUDGE_SCALE * math.sin(math.pi * age / NUDGE_MS)
            elif age >= NUDGE_MS:
                self._pulse_at = None
        return Shape(
            w=self._geometry["w"].value(now_ms),
            h=self._geometry["h"].value(now_ms),
            head=self._geometry["head"].value(now_ms),
            feather=max(0.0, self._geometry["feather"].value(now_ms)),
            text=_clamp(self._text.value(now_ms), 0.0, 1.0),
            text_old=_clamp(self._text_old.value(now_ms), 0.0, 1.0),
            tone=_clamp(self._tone.value(now_ms), 0.0, 1.0),
            tone_mix=_clamp(self._tone_mix.value(now_ms), 0.0, 1.0),
            mix=_clamp(self._mix.value(now_ms), 0.0, 1.0),
            pulse=pulse,
        )

    def settled(self, now_ms: float) -> bool:
        parts: list[Any] = [*self._geometry.values(), self._text, self._text_old, self._tone, self._tone_mix, self._mix]
        return all(part.settled(now_ms) for part in parts) and self._pulse_at is None


def rest_shape(pill_w: float, pill_h: float) -> Shape:
    return Shape(w=float(pill_w), h=float(pill_h), head=float(pill_w), feather=0.0)


# ---------------------------------------------------------------------------
# Which message shows (message spec section 11).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FlagAction:
    label: str  # "Undo", "Add", "Install"
    run: Callable[[], None]  # called on the UI thread after the segment folds away
    accelerator: str = ""  # "<Alt-d>", bound on the Pill root while shown
    primary: bool = False


@dataclass
class Message:
    title: str
    detail: str = ""
    tone: str = "info"
    actions: tuple[FlagAction, ...] = ()
    key: str = ""
    progress: float | None = None
    hold_ms: int | None = None
    origin: str = "system"
    segment: str = ""  # "word" | "update" | "" : which hold a segment gets
    created_ms: float = 0.0
    seq: int = 0
    remaining_ms: int | None = None  # set when an interrupted message is re-queued

    @property
    def is_segment(self) -> bool:
        return bool(self.actions)

    @property
    def priority(self) -> int:
        if self.tone == "error":
            return 3
        if self.actions or self.tone == "warn":
            return 2
        return 1

    @property
    def words(self) -> str:
        return f"{self.title}\n{self.detail}".strip()

    def reading_ms(self) -> int | None:
        if self.remaining_ms is not None:
            return self.remaining_ms
        if self.hold_ms is not None:
            return int(self.hold_ms)
        return hold_ms(self.tone, self.title, self.detail, segment=self.segment)


@dataclass(frozen=True)
class Context:
    live: bool = False  # the Pill is taking dictation: nothing stretches
    meeting: bool = False  # only errors and segments the person caused
    withdrawn: bool = False  # hidden or standing down for fullscreen: nothing speaks


@dataclass(frozen=True)
class Decision:
    """What the Overlay does with an offered message."""

    kind: str  # show | replace | update | nudge | queue | wait | recent | held | drop
    message: Message | None = None
    reason: str = ""
    due_ms: float | None = None
    requeued: Message | None = None


QUEUE_LIMIT = 3
REPEAT_MS = 10_000.0
PACE_MS = 700.0
BUSY_DELAY_MS = 700.0
BACKGROUND_PER_MINUTE = 6
HELD_ERROR_MS = 60_000.0
RECENT_LIMIT = 20


class MessageQueue:
    """One message on the Pill at a time, and the rules for the rest.

    | error 3, action (a segment) 2, warn 2, busy 1, done 1, info 1 |
    Same key: updated in place, no new entrance. Equal or higher priority:
    replaces the current one. Lower: queued behind it (at most 3 waiting, the
    oldest info or done dropped first; errors and actions never drop). The
    same words within 10 s: a nudge, not a second message. At most one
    entrance per 700 ms. Messages nobody caused: 6 a minute (errors exempt).
    While the Pill is live nothing stretches. During a meeting only errors and
    the person's own segments appear. A withdrawn Pill says nothing; its errors
    wait up to 60 s for it to come back.

    Two rules from the safety lane win over the table where they differ: an
    info never replaces an unread error (the priorities give that), and a
    word notice never replaces another word notice (X-631: the first keeps its
    undo), so a segment is only ever replaced by an error, and comes back.
    """

    def __init__(self) -> None:
        self.showing: Message | None = None
        self.shown_at_ms: float | None = None
        self.waiting: list[Message] = []
        self.pending_busy: dict[str, Message] = {}
        self.held: list[tuple[float, Message]] = []
        self.recent: deque[dict[str, Any]] = deque(maxlen=RECENT_LIMIT)
        self._entrances: deque[float] = deque()
        self._background: deque[float] = deque()
        self._said: dict[str, float] = {}
        self._seq = 0

    # -- bookkeeping -----------------------------------------------------------

    def _stamp(self, message: Message, now_ms: float) -> Message:
        self._seq += 1
        message.seq = self._seq
        if not message.created_ms:
            message.created_ms = now_ms
        return message

    def _remember(self, message: Message, now_ms: float) -> None:
        entry = {
            "time_ms": now_ms,
            "tone": message.tone,
            "title": message.title,
            "detail": message.detail,
            "actions": [action.label for action in message.actions],
            "key": message.key,
        }
        if message.key:
            for existing in self.recent:
                if existing.get("key") == message.key and existing.get("title") == message.title:
                    existing.update(entry)
                    return
        self.recent.append(entry)

    def _enqueue(self, message: Message) -> str:
        if len(self.waiting) >= QUEUE_LIMIT:
            droppable = [item for item in self.waiting if item.tone in ("info", "done") and not item.is_segment]
            if droppable:
                self.waiting.remove(droppable[0])
            elif message.tone in ("info", "done", "busy") and not message.is_segment:
                return "drop"
        self.waiting.append(message)
        # Highest priority first; arrival order within a priority.
        self.waiting.sort(key=lambda item: (-item.priority, item.seq))
        return "queue"

    def _paced(self, now_ms: float) -> float | None:
        if self._entrances and now_ms - self._entrances[-1] < PACE_MS:
            return self._entrances[-1] + PACE_MS
        return None

    def _within_budget(self, message: Message, now_ms: float) -> bool:
        if message.origin != "system" or message.tone == "error":
            return True
        while self._background and now_ms - self._background[0] >= 60_000.0:
            self._background.popleft()
        return len(self._background) < BACKGROUND_PER_MINUTE

    def _entered(self, message: Message, now_ms: float) -> None:
        self.showing = message
        self.shown_at_ms = now_ms
        self._entrances.append(now_ms)
        while len(self._entrances) > 8:
            self._entrances.popleft()
        if message.origin == "system" and message.tone != "error":
            self._background.append(now_ms)
        self._said[message.words] = now_ms

    # -- the rules -------------------------------------------------------------

    def offer(self, message: Message, now_ms: float, context: Context = Context()) -> Decision:
        message = self._stamp(message, now_ms)
        if message.tone not in TONES:
            message.tone = "info"
        if message.tone == "busy" and not message.key:
            # A busy line is always about some work; the work's result (same
            # key) replaces it, or cancels it before it ever shows.
            message.key = "busy"
        self._remember(message, now_ms)
        if context.meeting and not (message.tone == "error" or (message.is_segment and message.origin == "person")):
            return Decision("recent", message, "meeting")
        if context.withdrawn:
            if message.tone == "error":
                self.held.append((now_ms, message))
                return Decision("held", message, "withdrawn")
            return Decision("recent", message, "withdrawn")
        showing = self.showing
        # The same key updates the showing message in place (words, progress,
        # tone). Segments are the exception: a second word keeps its own undo.
        if showing is not None and message.key and message.key == showing.key and not (
            message.is_segment and showing.is_segment
        ):
            self.pending_busy.pop(message.key, None)
            self.showing = message
            self._said[message.words] = now_ms
            return Decision("update", message)
        if message.tone == "busy":
            # Work someone waits on appears only if it is still running 700 ms
            # on; a later line for the same work keeps the first one's clock.
            earlier = self.pending_busy.get(message.key)
            message.created_ms = earlier.created_ms if earlier is not None else now_ms
            self.pending_busy[message.key] = message
            return Decision("wait", message, "busy", due_ms=message.created_ms + BUSY_DELAY_MS)
        if message.key and message.key in self.pending_busy:
            # The result arrived before its busy line ever showed.
            self.pending_busy.pop(message.key, None)
        said_at = self._said.get(message.words)
        if said_at is not None and now_ms - said_at < REPEAT_MS:
            if showing is not None and showing.words == message.words:
                return Decision("nudge", showing)
            return Decision("drop", message, "repeat")
        if not self._within_budget(message, now_ms):
            return Decision("drop", message, "background budget")
        return self._place(message, now_ms, context)

    def _place(self, message: Message, now_ms: float, context: Context) -> Decision:
        showing = self.showing
        if showing is None:
            if context.live:
                return Decision(self._enqueue(message), message, "live")
            due = self._paced(now_ms)
            if due is not None:
                return Decision(self._enqueue(message), message, "pace", due_ms=due)
            self._entered(message, now_ms)
            return Decision("show", message)
        if message.is_segment and showing.is_segment:
            return Decision(self._enqueue(message), message, "a segment waits for the one showing")
        if showing.is_segment and message.tone != "error":
            return Decision(self._enqueue(message), message, "a segment is only replaced by an error")
        if message.priority >= showing.priority:
            # A replaced segment's undo must not be lost: the Overlay hands it
            # back with requeue() and its remaining time, after the error.
            requeued = showing if showing.is_segment else None
            self.showing = message
            self.shown_at_ms = now_ms
            self._said[message.words] = now_ms
            if message.origin == "system" and message.tone != "error":
                self._background.append(now_ms)
            return Decision("replace", message, requeued=requeued)
        return Decision(self._enqueue(message), message, "lower priority")

    def busy_due(self, key: str, now_ms: float, context: Context = Context()) -> Decision:
        """The 700 ms are up: show the busy line if its work is still running."""
        message = self.pending_busy.pop(key, None)
        if message is None:
            return Decision("drop", None, "the work finished first")
        if context.withdrawn:
            return Decision("recent", message, "withdrawn")
        if not self._within_budget(message, now_ms):
            return Decision("drop", message, "background budget")
        return self._place(message, now_ms, context)

    def finished(self, message: Message | None = None) -> None:
        """The showing message has contracted away."""
        if message is None or message is self.showing:
            self.showing = None

    def requeue(self, message: Message, remaining_ms: int | None) -> bool:
        """Dictation interrupted it: errors and segments come back if they
        still had reading time; an info is dropped."""
        if message is self.showing:
            self.showing = None
        if not (message.tone == "error" or message.is_segment):
            return False
        if remaining_ms is not None and remaining_ms <= 0:
            return False
        message.remaining_ms = remaining_ms
        self.waiting.insert(0, message)
        self.waiting.sort(key=lambda item: (-item.priority, item.seq if item is not message else -1))
        return True

    def next(self, now_ms: float, context: Context = Context()) -> Decision:
        """What to show now that nothing is showing (or why not yet)."""
        if self.showing is not None:
            return Decision("drop", None, "one at a time")
        if context.withdrawn or context.live:
            return Decision("drop", None, "not now")
        while self.held and now_ms - self.held[0][0] >= HELD_ERROR_MS:
            self.held.pop(0)
        if self.held:
            _, message = self.held.pop(0)
            self.waiting.insert(0, message)
            self.waiting.sort(key=lambda item: (-item.priority, item.seq))
        if not self.waiting:
            return Decision("drop", None, "nothing waiting")
        due = self._paced(now_ms)
        if due is not None:
            return Decision("wait", None, "pace", due_ms=due)
        candidates = self.waiting
        if context.meeting:
            candidates = [m for m in self.waiting if m.tone == "error" or (m.is_segment and m.origin == "person")]
            for message in [m for m in self.waiting if m not in candidates]:
                self.waiting.remove(message)
            if not candidates:
                return Decision("drop", None, "meeting")
        message = candidates[0]
        self.waiting.remove(message)
        self._entered(message, now_ms)
        return Decision("show", message)

    def recent_messages(self) -> list[dict[str, Any]]:
        return [dict(entry) for entry in self.recent]


def message_from(
    title: str,
    *,
    detail: str = "",
    tone: str = "info",
    actions: Sequence[FlagAction] = (),
    key: str = "",
    progress: float | None = None,
    hold: int | None = None,
    origin: str = "system",
    segment: str = "",
) -> Message:
    tone = str(tone or "info").strip().lower()
    if tone not in TONES:
        tone = "info"
    origin = str(origin or "system").strip().lower()
    if origin not in ORIGINS:
        origin = "system"
    return Message(
        title=" ".join(str(title or "").split()),
        detail=" ".join(str(detail or "").split()),
        tone=tone,
        actions=tuple(actions or ()),
        key=str(key or ""),
        progress=None if progress is None else _clamp(float(progress), 0.0, 1.0),
        hold_ms=None if hold is None else max(0, int(hold)),
        origin=origin,
        segment=segment,
    )


__all__ = [
    "COMPRESS",
    "CONTRACT",
    "Context",
    "Decision",
    "FlagAction",
    "GROW_HEIGHT",
    "GROW_LENGTH",
    "Message",
    "MessageQueue",
    "PREEMPT",
    "PillMotion",
    "Placement",
    "REPLACE",
    "Rect",
    "Shape",
    "capsule_height",
    "capsule_width",
    "envelope",
    "hold_ms",
    "message_from",
    "pill_frame",
    "rest_shape",
    "resumed_hold_ms",
    "say_tone",
    "settle_ms",
    "spring",
]
