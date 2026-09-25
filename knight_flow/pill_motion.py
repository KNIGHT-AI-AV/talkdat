"""Pure Pill animation, envelope, and state maths.

Split out of overlay.py so it can be imported and tested without tkinter, PIL, or a
display. overlay.py re-exports every name here, so existing imports keep working.
"""

from __future__ import annotations

import math
from collections.abc import Sequence


TRANSPARENT_COLOR = "#010203"

LIVE_STATES = {"starting", "connected", "listening", "command"}

# X-137 (his spec, verbatim intent): the click's ONLY immediate feedback is
# the compact pill desaturating to gray -- "expanding and displaying full
# color only when active listening begins." starting/connected are the gray
# standby; the grow animation waits for the mic to actually be open.
EXPANDED_STATES = {"listening", "command"}

STANDBY_STATES = {"starting", "connected"}

LOCAL_FORMATTER_PROFILES = (
    ("Realtime - Qwen3 1.7B (recommended)", "qwen3:1.7b", 1200),
    ("Balanced - Qwen3.5 2B", "qwen3.5:2b", 2400),
    ("Quality - Qwen3.5 4B", "qwen3.5:4b", 4200),
    ("Maximum - Qwen3.5 9B", "qwen3.5:9b", 7000),
)

LOCAL_FORMATTER_PROFILE_BY_LABEL = {
    label: (model, budget_ms) for label, model, budget_ms in LOCAL_FORMATTER_PROFILES
}

LOCAL_FORMATTER_PROFILE_BY_MODEL = {
    model: (label, budget_ms) for label, model, budget_ms in LOCAL_FORMATTER_PROFILES
}


# X-170: the draw loop may never own the whole UI thread.
#
# The old reschedule was `after(max(4, delay - render_elapsed_ms))`. Read what
# that does when a frame is slower than its target: delay 16, cost 60, so
# `16 - 60 = -44`, so `max(4, -44)` is **4**. A frame that took 60ms queues the
# next one 4ms later, forever. Drawing then consumes ~94% of the UI thread and
# Tk's event queue never drains, so hovers arrive late, the pill looks frozen
# rather than slow, and a keypress waits behind a backlog of frames.
#
# Measured on the founder's machine WHILE A GAME WAS RUNNING -- which is the
# case that matters, and the one he reported from: 16 fps, 59.9ms per frame
# against a 16.7ms budget, of which 28ms was a single Tk `itemconfigure` (a
# layered, topmost, colour-keyed window costs a full DWM composite per change)
# and ~25ms was PIL refraction work in Python.
#
# So the three symptoms -- "super lag", "graphically unstable", and "press to
# hold not triggering at all" -- are one bug. Not three.
FRAME_DUTY_CYCLE = 0.6

# A frame this slow means the machine cannot afford the expensive visual. Two
# budgets, with a gap between them, because a single threshold flaps: the moment
# downgrading makes frames cheap again it would upgrade, become slow, and
# oscillate visibly.
FRAME_BUDGET_MS = 22.0
FRAME_RECOVERY_MS = 12.0


def next_frame_delay_ms(
    target_ms: int,
    cost_ms: float,
    *,
    duty: float = FRAME_DUTY_CYCLE,
    ceiling_ms: int = 250,
) -> int:
    """Delay before the next frame, so drawing keeps at most `duty` of the thread.

    At the target rate this is just the leftover time in the frame. When a frame
    overruns, the gap grows instead of collapsing to nothing: the animation
    slows down honestly and evenly, and the input queue gets air. An even 10fps
    reads as a slower animation; an uneven 16fps with no input headroom reads as
    a broken application, which is what he was looking at.
    """
    target = max(1, int(target_ms))
    cost = max(0.0, float(cost_ms))
    share = min(0.95, max(0.05, float(duty)))
    # cost / (cost + gap) <= duty  ->  gap >= cost * (1 - duty) / duty
    required_gap = cost * (1.0 - share) / share
    return int(max(1.0, min(float(ceiling_ms), max(float(target) - cost, required_gap))))


def sustained_frame_cost_ms(costs: Sequence[float], sustained: int = 5) -> float:
    """The median of the last `sustained` frames, or 0.0 before there are that many.

    Median, not mean: one 180ms hitch from a garbage collection or a game
    grabbing the GPU must not trigger a permanent visual downgrade, and one fast
    frame must not undo one.
    """
    window = [float(value) for value in list(costs)[-max(1, int(sustained)):]]
    if len(window) < max(1, int(sustained)):
        return 0.0
    window.sort()
    middle = len(window) // 2
    if len(window) % 2:
        return window[middle]
    return (window[middle - 1] + window[middle]) / 2.0


def effects_downgrade_decision(
    costs: Sequence[float],
    *,
    downgraded: bool,
    sustained: int = 5,
    budget_ms: float = FRAME_BUDGET_MS,
    recovery_ms: float = FRAME_RECOVERY_MS,
) -> bool:
    """Whether the expensive visual should be off, given recent frame costs.

    Hysteresis is the whole point: `budget_ms` turns effects off, and the much
    lower `recovery_ms` turns them back on. Without the gap, downgrading makes
    frames cheap, cheap frames restore the effect, the effect makes frames
    expensive, and the pill visibly pulses between two looks.
    """
    median = sustained_frame_cost_ms(costs, sustained)
    if median <= 0.0:
        return bool(downgraded)
    if downgraded:
        return median > float(recovery_ms)
    return median > float(budget_ms)


def pill_is_expanded(state: str) -> bool:
    return str(state).strip().lower() in EXPANDED_STATES


def completion_rainbow_enabled(state: str) -> bool:
    return str(state).strip().lower() == "processing"


def completion_rainbow_alpha(
    elapsed_ms: float,
    fade_in_ms: int = 120,
    hold_ms: int = 220,
    fade_out_ms: int = 260,
) -> float:
    elapsed = max(0.0, float(elapsed_ms))
    fade_in = max(1, int(fade_in_ms))
    hold = max(0, int(hold_ms))
    fade_out = max(1, int(fade_out_ms))
    if elapsed < fade_in:
        t = elapsed / fade_in
        return t * t * (3.0 - 2.0 * t)
    if elapsed < fade_in + hold:
        return 1.0
    if elapsed < fade_in + hold + fade_out:
        t = (elapsed - fade_in - hold) / fade_out
        eased = t * t * (3.0 - 2.0 * t)
        return 1.0 - eased
    return 0.0


def processing_rainbow_step(
    current: float,
    *,
    active: bool,
    elapsed_ms: float,
    fade_in_ms: int = 120,
    fade_out_ms: int = 240,
) -> float:
    level = max(0.0, min(1.0, float(current)))
    duration = max(1, int(fade_in_ms if active else fade_out_ms))
    distance = max(0.0, float(elapsed_ms)) / duration
    if active:
        return min(1.0, level + distance)
    return max(0.0, level - distance)


def processing_transition_alpha(frame_index: int, frame_count: int) -> float:
    """Rainbow mix for a close transition stored compact-to-active.

    The active endpoint stays on the live artwork while the compact endpoint is
    fully rainbow. This lets release immediately begin a smooth color handoff
    instead of playing a normal-color close clip before processing appears.
    """
    steps = max(1, int(frame_count) - 1)
    progress = 1.0 - max(0.0, min(1.0, int(frame_index) / steps))
    return progress * progress * (3.0 - 2.0 * progress)


def quantized_active_render_key(
    width: int,
    height: int,
    flow_key: tuple[int, int] | None,
    *,
    voice_level: float,
    hover_level: float,
    loading: bool,
) -> tuple[int, ...] | None:
    if flow_key is None or loading or float(hover_level) >= 0.01:
        return None
    voice_bucket = max(0, min(5, round(float(voice_level) * 5.0)))
    return (int(width), int(height), int(flow_key[0]), int(flow_key[1]), voice_bucket)


def perceptual_voice_level(level: float) -> float:
    """Map raw microphone RMS to a speech-focused visual range in dBFS."""
    raw = max(0.0, min(1.0, float(level)))
    noise_floor = 0.0008
    if raw <= noise_floor:
        return 0.0
    floor_db = -62.0
    ceiling_db = -15.0
    dbfs = 20.0 * math.log10(max(raw, 1e-9))
    normalized = max(0.0, min(1.0, (dbfs - floor_db) / (ceiling_db - floor_db)))
    eased = normalized * normalized * (3.0 - 2.0 * normalized)
    return eased**0.72


def microphone_energy_envelope(levels: Sequence[float], width: int) -> tuple[float, ...]:
    """Resample recent real microphone energy across the pill from old to new."""
    target_width = max(1, int(width))
    mapped = [perceptual_voice_level(level) for level in levels]
    history: list[float] = []
    follower = 0.0
    for target in mapped:
        coefficient = 0.76 if target > follower else 0.22
        follower += (target - follower) * coefficient
        history.append(0.0 if follower < 0.025 else follower)
    if not history:
        return (0.0,) * target_width
    if len(history) == 1:
        history = [history[0], history[0]]

    envelope: list[float] = []
    last_index = len(history) - 1
    for x_index in range(target_width):
        position = (x_index / max(1, target_width - 1)) * last_index
        left = int(math.floor(position))
        right = min(last_index, left + 1)
        amount = position - left
        envelope.append(history[left] * (1.0 - amount) + history[right] * amount)

    # One spatial pass removes callback stair-steps without erasing consonants.
    for _ in range(1):
        padded = [envelope[0], envelope[0], *envelope, envelope[-1], envelope[-1]]
        envelope = [
            (
                padded[index]
                + padded[index + 1] * 2.0
                + padded[index + 2] * 3.0
                + padded[index + 3] * 2.0
                + padded[index + 4]
            )
            / 9.0
            for index in range(target_width)
        ]

    if target_width > 8:
        for x_index, value in enumerate(envelope):
            position = x_index / max(1, target_width - 1)
            edge = min(
                1.0,
                max(0.0, position / 0.08),
                max(0.0, (1.0 - position) / 0.08),
            )
            edge = edge * edge * (3.0 - 2.0 * edge)
            envelope[x_index] = value * edge
    return tuple(envelope)


def faceted_voice_trace(envelope: Sequence[float]) -> tuple[float, ...]:
    """Turn real speech energy into an angular, ECG-like refractive trace."""
    values = [max(0.0, min(1.0, float(value))) for value in envelope]
    width = len(values)
    if width < 2 or max(values, default=0.0) <= 0.015:
        return (0.0,) * width

    # The active Pill is 192 px wide. Four-pixel anchors keep the trace crisp
    # enough to read as facets while still representing recent mic callbacks.
    anchor_step = max(3, min(6, round(width / 48)))
    heartbeat = (0.0, 0.34, -0.82, 1.0, -0.38, 0.0)
    anchors: list[tuple[int, float]] = []
    anchor_index = 0
    for x_index in range(0, width, anchor_step):
        energy = values[min(width - 1, x_index)]
        amplitude = 0.0 if energy < 0.025 else energy**0.82
        anchors.append((x_index, heartbeat[anchor_index % len(heartbeat)] * amplitude))
        anchor_index += 1
    if anchors[-1][0] != width - 1:
        anchors.append((width - 1, 0.0))

    trace = [0.0] * width
    for (left_x, left_value), (right_x, right_value) in zip(anchors, anchors[1:]):
        span = max(1, right_x - left_x)
        for x_index in range(left_x, right_x + 1):
            amount = (x_index - left_x) / span
            trace[x_index] = left_value * (1.0 - amount) + right_value * amount

    # Keep the approved round silhouette calm at both ends. Only the material
    # inside it receives the angular speech displacement.
    edge_width = max(4, round(width * 0.07))
    for x_index, value in enumerate(trace):
        edge = min(1.0, x_index / edge_width, (width - 1 - x_index) / edge_width)
        trace[x_index] = value * max(0.0, edge)
    return tuple(trace)


def transition_frame_order(frame_count: int, compact: bool, start_index: int | None = None) -> list[int]:
    count = max(0, int(frame_count))
    if count <= 0:
        return []
    if start_index is None:
        start = count - 1 if compact else 0
    else:
        start = min(count - 1, max(0, int(start_index)))
    return list(range(start, -1, -1)) if compact else list(range(start, count))


def transition_frame_index(elapsed_ms: float, frame_delay_ms: int, frame_count: int) -> int:
    count = max(0, int(frame_count))
    if count <= 1:
        return 0
    delay = max(1, int(frame_delay_ms))
    return min(count - 1, max(0, int(max(0.0, float(elapsed_ms)) // delay)))


def loading_halo_phase_bucket(phase: int) -> int:
    return (max(0, int(phase)) // 2) % 72


# X-640 (polish audit P0-2): the press receipt is the compact Pill draining to
# gray (X-137). It used to swap to gray in one frame; it now drains over 90 ms,
# starting half way so the receipt still lands on the very first frame. X-137
# forbids MOTION in standby, and a change of colour is not motion: nothing
# moves or grows, only the saturation settles.
STANDBY_FADE_MS = 90
STANDBY_FIRST_LEVEL = 0.5


def standby_gray_level(elapsed_ms: float, *, reduced_motion: bool = False) -> float:
    """How far (0.5..1) the standby Pill has drained to gray after `elapsed_ms`."""
    if reduced_motion:
        return 1.0
    t = max(0.0, float(elapsed_ms)) / STANDBY_FADE_MS
    if t >= 1.0:
        return 1.0
    # Ease out: most of the change lands at once, the rest settles.
    return STANDBY_FIRST_LEVEL + (1.0 - STANDBY_FIRST_LEVEL) * (1.0 - (1.0 - t) ** 3)


# 2026-09-23, the owner's audit: "captured/pasted" and "error" looked exactly
# like idle, so a finished dictation and a failed one gave the same answer --
# none. Each now has a brief look of its own, painted over the Pill's own
# artwork so it keeps its hand-drawn texture:
#
#   captured -> a teal settle: in fast, out slow, gone in about half a second.
#   error    -> an ember glow with two soft beats, held until the next take
#               (any new state replaces it) or about three seconds.
#
# Reduced motion keeps the colour and drops the motion: the tint is static for
# the same span, with no rise, beat or fade (an on/off change of colour is not
# vestibular motion). Critically damped throughout, no overshoot: this is
# feedback for an outcome, not the end of a flick.
FEEDBACK_STATES = ("captured", "error")
SUCCESS_FEEDBACK_MS = 520
ERROR_FEEDBACK_MS = 3000
SUCCESS_FEEDBACK_PEAK = 0.9
REDUCED_MOTION_SUCCESS_LEVEL = 0.8
_SUCCESS_RISE_MS = 90
_ERROR_RISE_MS = 140
_ERROR_BEAT_MS = 380
_ERROR_BEATS = 2
_ERROR_BEAT_DEPTH = 0.26
_ERROR_FADE_MS = 380


def _ease(value: float) -> float:
    t = max(0.0, min(1.0, float(value)))
    return t * t * (3.0 - 2.0 * t)


def state_feedback_level(state: str, elapsed_ms: float, *, reduced_motion: bool = False) -> float:
    """Strength (0..1) of the success or error look, `elapsed_ms` after it began.

    Zero for every other state, and zero once the look has run its course, so a
    caller can paint it unconditionally.
    """
    normalized = str(state).strip().lower()
    elapsed = max(0.0, float(elapsed_ms))
    if normalized == "captured":
        if elapsed >= SUCCESS_FEEDBACK_MS:
            return 0.0
        if reduced_motion:
            return REDUCED_MOTION_SUCCESS_LEVEL
        if elapsed < _SUCCESS_RISE_MS:
            return SUCCESS_FEEDBACK_PEAK * _ease(elapsed / _SUCCESS_RISE_MS)
        # The settle: fast at first, then easing to nothing, so the teal comes
        # to rest rather than switching off.
        progress = (elapsed - _SUCCESS_RISE_MS) / (SUCCESS_FEEDBACK_MS - _SUCCESS_RISE_MS)
        return SUCCESS_FEEDBACK_PEAK * (1.0 - progress) ** 2
    if normalized == "error":
        if elapsed >= ERROR_FEEDBACK_MS:
            return 0.0
        if reduced_motion:
            return 1.0
        if elapsed < _ERROR_RISE_MS:
            return _ease(elapsed / _ERROR_RISE_MS)
        beats_end = _ERROR_RISE_MS + _ERROR_BEAT_MS * _ERROR_BEATS
        if elapsed < beats_end:
            phase = (elapsed - _ERROR_RISE_MS) / _ERROR_BEAT_MS
            return 1.0 - _ERROR_BEAT_DEPTH * math.sin(math.pi * phase) ** 2
        fade_start = ERROR_FEEDBACK_MS - _ERROR_FADE_MS
        if elapsed < fade_start:
            return 1.0
        return 1.0 - _ease((elapsed - fade_start) / _ERROR_FADE_MS)
    return 0.0


def state_feedback_bucket(level: float) -> int:
    """The level quantized for the Pill's at-rest check.

    Fine enough that the settle animates every frame, coarse enough that the
    held ember reads as unchanged and the idle loop goes back to sleep.
    """
    return int(round(max(0.0, min(1.0, float(level))) * 50))


def error_toast_hold_ms(title: str, detail: str = "") -> int:
    """How long an error message stays up: long enough to read both lines.

    Unhurried reading pace (about 220 ms a word) plus a moment to look up,
    floored at four seconds and capped at eight; a click puts it away sooner.
    A toast that vanishes before its second line is read has told nobody what
    to do next.
    """
    words = len(f"{title} {detail}".split())
    return int(max(4000, min(8000, 1200 + 220 * words)))


def state_hold_delay_ms(state: str, *, result_hold_ms: int, error_hold_ms: int) -> int | None:
    normalized = str(state).strip().lower()
    if normalized == "captured":
        return max(0, int(result_hold_ms))
    if normalized == "error":
        return max(0, int(error_hold_ms))
    return None


def toast_fade_alpha(elapsed_ms: float, *, hold_ms: int, fade_ms: int) -> float:
    """Opacity of a transient toast: held fully opaque, then faded to nothing.

    Checked in this order deliberately. Testing the hold first would keep a
    zero-length fade permanently opaque, and dividing by the fade window before
    the end-of-life check would divide by zero.
    """
    fade = max(0, fade_ms)
    if elapsed_ms >= hold_ms + fade:
        return 0.0
    if elapsed_ms <= hold_ms:
        return 1.0
    remaining = (hold_ms + fade) - elapsed_ms
    return max(0.0, min(1.0, remaining / fade))


def toast_is_finished(elapsed_ms: float, *, hold_ms: int, fade_ms: int) -> bool:
    """Whether the toast has fully faded and its window should be destroyed."""
    return elapsed_ms >= hold_ms + max(0, fade_ms)


# X-620, the interaction grid's ACK primitive: the answer a gesture gets when
# it has no function where it landed. The control's own press response at a
# small scale, then stillness. Never a message, never a sound, never a layout,
# geometry or focus change. It plays only when a gesture ENDS (release, keyup),
# never on the press, never after a cancel, never when a function already ran.
#
#   motion   1 to 2 px over 180 ms: 0, +1.5 px at 30%, -0.6 px at 65%, 0.
#   reduced  an opacity dip instead (to 0.88 and back over 140 ms).
#   limit    one per surface per 700 ms, at most 4 per 3 s app-wide; a repeat
#            inside the window does nothing (no restart, no queue).
ACK_DURATION_MS = 180
_ACK_KEYS = ((0.0, 0.0), (0.30, 1.5), (0.65, -0.6), (1.0, 0.0))
ACK_REDUCED_MS = 140
ACK_REDUCED_FLOOR = 0.88
ACK_SURFACE_GAP_MS = 700
ACK_WINDOW_MS = 3000
ACK_WINDOW_LIMIT = 4


def ack_magnitude(elapsed_ms: float) -> float:
    """Signed travel in pixels along the gesture's direction, `elapsed_ms` in."""
    elapsed = float(elapsed_ms)
    if elapsed <= 0.0 or elapsed >= ACK_DURATION_MS:
        return 0.0
    progress = elapsed / ACK_DURATION_MS
    for (left_t, left_v), (right_t, right_v) in zip(_ACK_KEYS, _ACK_KEYS[1:]):
        if progress <= right_t:
            amount = _ease((progress - left_t) / max(1e-9, right_t - left_t))
            return left_v + (right_v - left_v) * amount
    return 0.0


def ack_offset(elapsed_ms: float, direction: tuple[float, float] = (0.0, 1.0)) -> tuple[int, int]:
    """Whole-pixel (dx, dy) for the ACK at `elapsed_ms`.

    `direction` is the gesture's: straight down (0, 1) for a press, the drag's
    own vector for a drag. It is normalised, so only its angle matters.
    Talk DAT! has no rotary control, so the rotation case never arises.
    """
    dx, dy = float(direction[0]), float(direction[1])
    length = math.hypot(dx, dy)
    if length <= 0.0:
        dx, dy, length = 0.0, 1.0, 1.0
    travel = ack_magnitude(elapsed_ms)

    def whole(value: float) -> int:
        # Half away from zero: Python's round() sends the 1.5 px peak to 2
        # only by the accident of banker's rounding.
        return int(math.copysign(math.floor(abs(value) + 0.5), value))

    return whole(dx / length * travel), whole(dy / length * travel)


def ack_opacity(elapsed_ms: float) -> float:
    """The reduced-motion ACK: opacity down to 0.88 and back over 140 ms."""
    elapsed = float(elapsed_ms)
    if elapsed <= 0.0 or elapsed >= ACK_REDUCED_MS:
        return 1.0
    half = ACK_REDUCED_MS / 2.0
    depth = _ease(elapsed / half) if elapsed <= half else _ease((ACK_REDUCED_MS - elapsed) / half)
    return 1.0 - (1.0 - ACK_REDUCED_FLOOR) * depth


def ack_is_running(elapsed_ms: float, *, reduced_motion: bool) -> bool:
    return 0.0 <= float(elapsed_ms) < (ACK_REDUCED_MS if reduced_motion else ACK_DURATION_MS)


def ack_key_moment_ms(*, reduced_motion: bool) -> float:
    """The one moment an ACK must reach the screen: the press itself (the
    +1.5 px peak) or, under reduced motion, the deepest point of the dip."""
    return ACK_REDUCED_MS / 2.0 if reduced_motion else ACK_DURATION_MS * _ACK_KEYS[1][0]


def ack_catch_up(elapsed_ms: float, *, key_shown: bool, reduced_motion: bool) -> tuple[float, bool]:
    """X-620b: (the moment to draw, whether the key moment has now been drawn).

    A frame that arrives after the key moment, before any frame has shown
    it, draws the key moment instead. The Pill's frames slow down under load
    (X-170 measured 60 ms against a 16.7 ms budget), and a 180 ms ACK
    sampled that coarsely could skip the press and read as nothing at all.
    """
    key = ack_key_moment_ms(reduced_motion=reduced_motion)
    if key_shown:
        return float(elapsed_ms), True
    if float(elapsed_ms) >= key:
        return key, True
    return float(elapsed_ms), False


class AckLimiter:
    """Who may ACK right now. Pure: the caller passes the clock.

    Only allowed ACKs count against the limits; a refused one leaves no trace,
    so hammering a surface cannot extend its own silence.
    """

    def __init__(
        self,
        *,
        surface_gap_ms: float = ACK_SURFACE_GAP_MS,
        window_ms: float = ACK_WINDOW_MS,
        window_limit: int = ACK_WINDOW_LIMIT,
    ) -> None:
        self.surface_gap_ms = float(surface_gap_ms)
        self.window_ms = float(window_ms)
        self.window_limit = int(window_limit)
        self._last_by_surface: dict[str, float] = {}
        self._recent: list[float] = []

    def allow(self, surface: str, now_ms: float) -> bool:
        now = float(now_ms)
        last = self._last_by_surface.get(surface)
        if last is not None and now - last < self.surface_gap_ms:
            return False
        self._recent = [stamp for stamp in self._recent if now - stamp < self.window_ms]
        if len(self._recent) >= self.window_limit:
            return False
        self._last_by_surface[surface] = now
        self._recent.append(now)
        return True


def next_context_menu_action(actions: list[str], current: str, key: str) -> str:
    if not actions:
        return ""
    normalized = str(key).strip().lower()
    if normalized == "home":
        return actions[0]
    if normalized == "end":
        return actions[-1]
    if normalized not in {"up", "down"}:
        return current if current in actions else actions[0]
    if current not in actions:
        return actions[-1] if normalized == "up" else actions[0]
    offset = -1 if normalized == "up" else 1
    return actions[(actions.index(current) + offset) % len(actions)]


def apply_menu_order(default_ids: list[str], saved: list[str]) -> list[str]:
    """X-06: the user's saved menu order, healed against app updates.

    The rule Mayowa set: a reordered menu stays reordered "even throughout
    the updates" -- and an update that ADDS an item must slot the newcomer at
    its default position without disturbing the user's arrangement. So the
    default list is the frame: items the user ordered permute among the
    positions they collectively occupy, items the user has never seen stay
    exactly where the default puts them, and saved ids that no longer exist
    are ignored.
    """
    default_ids = list(default_ids)
    known = set(default_ids)
    wanted = [item for item in saved if item in known]
    if not wanted:
        return default_ids
    wanted_set = set(wanted)
    result = list(default_ids)
    slots = [index for index, item in enumerate(default_ids) if item in wanted_set]
    for slot, item in zip(slots, wanted):
        result[slot] = item
    return result
