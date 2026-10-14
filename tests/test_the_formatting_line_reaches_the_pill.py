"""Review CL4-1 (2026-10-10): with Auto paste off, the formatting line reaches the Pill.

With Auto paste off a take ends on "Captured locally. Auto paste is off." (a warn),
and the formatting line (the X-465 reason, or the escalation after three stalls)
follows it. Round 4 sent that line as an info nobody caused. Through the real
message queue it was never shown while a meeting app was running or the Pill was
withdrawn, and the next press cut it for good. Everywhere else the same line is an
error the person caused, and it gets through all of these.

So the line is an error the person caused, and it waits behind the take's own line
(after_key "state"). It is checked here end to end, on one clock:
- the app's real handle_dictation;
- the Overlay's real set_state and flag, its queue glue (_flag_apply, _flag_pump,
  _flag_preempt, _flag_end_now, _flag_finish, _flag_after_fold), its hold ticks
  (_flag_start_hold, _flag_hold_tick) and its fullscreen stand-down;
- the real island.MessageQueue.

Only the drawing is faked. A message grows for the real grow springs' settle time,
holds for its reading time, then contracts (on the preempt spring when a press cuts
it). A line is READ when its reading time ran out on the Pill, which is when the
Overlay contracts it by itself; a requeued line is read when the rest of its time
runs out after it comes back.
"""
from __future__ import annotations

import heapq
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from knight_flow import island
from knight_flow.formatting import note_local_finish_refusal, take_local_finish_notice
from knight_flow.overlay import Overlay
from knight_flow.paste import PasteReceipt
from tests.test_esc_while_processing_keeps_the_words import processing_app

CAPTURED = "Captured locally. Auto paste is off."
REASON = "Your text was formatted by the built-in rules, not the model"
ESCALATION = "Formatting isn't being applied"
#: Which takes say which line: the reason on its own take, the escalation on the third stall.
LINES = {"the reason": (["model_unavailable"], REASON), "the escalation": (["timeout"] * 3, ESCALATION)}

GROW_MS = max(island.settle_ms(*island.GROW_LENGTH), island.settle_ms(*island.GROW_HEIGHT))
CONTRACT_MS = island.CONTRACT_DELAY_MS + island.settle_ms(*island.CONTRACT)
PREEMPT_MS = island.PREEMPT_TEXT_OUT_MS + island.settle_ms(*island.PREEMPT)
HELD_MS = 2000.0  # how long each take's hotkey is held
FINISH_MS = 800.0  # from the release to the take landing
TAKE_GAP_MS = 30_000.0  # between the takes before the last: each one's lines are long gone


class Clock:
    """root.after on a clock the test moves."""

    def __init__(self) -> None:
        self.now = 0.0
        self._timers: list = []
        self._seq = 0
        self._cancelled: set[str] = set()

    def after(self, delay_ms, callback) -> str:
        self._seq += 1
        heapq.heappush(self._timers, (self.now + max(0.0, float(delay_ms)), self._seq, callback))
        return f"after#{self._seq}"

    def cancel(self, ident) -> None:
        self._cancelled.add(str(ident))

    def run_until(self, until_ms: float) -> None:
        while self._timers and self._timers[0][0] <= until_ms:
            due, seq, callback = heapq.heappop(self._timers)
            self.now = max(self.now, due)
            if f"after#{seq}" not in self._cancelled:
                callback()
        self.now = max(self.now, until_ms)


class _Root:
    def __init__(self, clock: Clock) -> None:
        self.clock = clock

    def after(self, delay_ms, callback):
        return self.clock.after(delay_ms, callback)

    def after_idle(self, callback):
        return self.clock.after(0, callback)

    def after_cancel(self, ident) -> None:
        self.clock.cancel(ident)

    def state(self) -> str:
        return "normal"

    def withdraw(self) -> None:
        return None


class _View:
    """What the Overlay's queue glue and hold ticks read from the message on the Pill."""

    def __init__(self, message: island.Message) -> None:
        self.message = message
        self.phase = "in"
        self.hold_left = None
        self.hold_total = None
        self.hovered = False
        self.keyed = False
        self.preempt = False
        self.bindings: list = []
        self.after_fold = None
        self.pill = SimpleNamespace(x=0, y=0, w=60, h=20)
        self.motion = SimpleNamespace(nudge=lambda _now: None)


class Pill:
    """A real Overlay's message code with the drawing faked, on a test clock."""

    def __init__(self) -> None:
        self.clock = Clock()
        self.fullscreen = False
        self.log: list[tuple[float, str, str]] = []  # (ms, "shown" | "read" | "cut", title)
        overlay = object.__new__(Overlay)
        overlay._ui_thread_id = threading.get_ident()
        overlay.config = {}
        overlay.root = _Root(self.clock)
        overlay._flag_timers = []
        overlay._flag_view = None
        overlay._flag_hold_after = None
        overlay._flag_deferred_compact = None
        overlay._pill_presenter = None
        overlay.current_width, overlay.current_height = 60, 20
        overlay.fullscreen_hidden = False
        overlay.onboarding_test_sink = None
        overlay.state = "idle"
        # set_state's own work that is not about messages (as tests/test_overlay_motion.py does)
        overlay.compact = True
        overlay._open_anim_active = False
        overlay.completion_effect_level = 0.0
        overlay.completion_effect_started_at = None
        overlay.completion_effect_last_tick = None
        overlay.completion_effect_pending = False
        overlay.last_status = ""
        overlay.last_preview = ""
        overlay._set_compact = lambda *_args, **_kwargs: None
        overlay._schedule_idle_return = lambda *_args, **_kwargs: None
        overlay._repaint = lambda: None
        overlay._reset_voice_history = lambda: None
        overlay._apply_geometry = lambda *_args, **_kwargs: None
        overlay.force_visible = lambda: None
        overlay.set_level = lambda _level: None
        overlay._should_hide_for_fullscreen = lambda: self.fullscreen
        overlay._flag_clock_ms = lambda: self.clock.now
        # the drawing
        overlay._flag_show = self._show
        overlay._flag_replace = self._replace
        overlay._flag_update = self._update
        overlay._flag_contract = self._contract
        overlay._flag_draw = lambda: None
        overlay._flag_pointer_on = lambda _view: False
        end_now = overlay._flag_end_now

        def ended_now() -> None:
            view = overlay._flag_view
            if view is not None and view.phase != "out":
                self.log.append((self.clock.now, "cut", view.message.title))
            end_now()

        overlay._flag_end_now = ended_now
        self.overlay = overlay

    # -- the faked drawing ------------------------------------------------------

    def _settle(self, view: _View) -> None:
        def settled() -> None:
            if self.overlay._flag_view is view and view.phase == "in":
                view.phase = "hold"
                self.overlay._flag_start_hold()

        self.clock.after(GROW_MS, settled)

    def _show(self, message: island.Message | None) -> None:
        if message is None:
            return
        view = _View(message)
        self.overlay._flag_view = view
        self.log.append((self.clock.now, "shown", message.title))
        self._settle(view)

    def _replace(self, message: island.Message) -> None:
        view = self.overlay._flag_view
        if view is None:
            self._show(message)
            return
        self.overlay._flag_cancel_hold()
        if view.phase != "out":
            self.log.append((self.clock.now, "cut", view.message.title))
        self._show(message)

    def _update(self, message: island.Message) -> None:
        view = self.overlay._flag_view
        if view is None:
            self._show(message)
            return
        if view.message.tone != message.tone or message.is_segment != view.message.is_segment:
            self._replace(message)
            return
        view.message = message
        if view.phase == "hold":
            self.overlay._flag_cancel_hold()
            self.overlay._flag_start_hold()

    def _contract(self, *, preempt: bool = False) -> None:
        view = self.overlay._flag_view
        if view is None or view.phase == "out":
            return
        self.overlay._flag_cancel_hold()
        view.phase = "out"
        view.preempt = preempt
        ran_out = not preempt and view.hold_left is not None and view.hold_left <= 0
        self.log.append((self.clock.now, "read" if ran_out else "cut", view.message.title))

        def gone() -> None:
            if self.overlay._flag_view is view:
                self.overlay._flag_finish(None)

        self.clock.after(PREEMPT_MS if preempt else CONTRACT_MS, gone)

    # -- what happens -------------------------------------------------------------

    def at(self, when_ms: float, action) -> None:
        self.clock.after(when_ms - self.clock.now, action)

    def press(self) -> None:
        self.overlay.set_state("listening", "Listening.")

    def release(self) -> None:
        self.overlay.set_state("processing", "Finalizing. Mic closing.")

    def withdraw(self, hidden: bool) -> None:
        self.fullscreen = hidden
        self.overlay._sync_fullscreen_visibility()

    def read(self, since_ms: float = 0.0, *, until_ms: float = float("inf")) -> list[str]:
        """The titles read in full, in order, from since_ms up to (not at) until_ms."""
        return [title for when, what, title in self.log if what == "read" and since_ms <= when < until_ms]


def land(pill: Pill, code: str, streak):
    """One take with Auto paste off, landing now; code is its formatting fallback ("" = none)."""
    app, token = processing_app()
    app.overlay = pill.overlay
    app.config["dictation"]["auto_paste"] = False
    if streak is not None:
        app._quiet_fallback_streak = streak

    def formatted(*_args, **_kwargs):
        if code:
            note_local_finish_refusal(code)
        return SimpleNamespace(original="the words", text="The words.", send_enter=False)

    with patch("knight_flow.app.process_dictation", side_effect=formatted), \
         patch("knight_flow.app.paste_text_with_receipt",
               return_value=PasteReceipt(True, "clipboard", "clipboard", ("clipboard",))), \
         patch("knight_flow.app.foreground_window_id", return_value=111):
        app.handle_dictation("the words", delivery_token=token, guided_sink=None)
    return getattr(app, "_quiet_fallback_streak", None)


class TheFormattingLineReachesThePillTests(unittest.TestCase):
    def setUp(self) -> None:
        take_local_finish_notice()

    def tearDown(self) -> None:
        take_local_finish_notice()

    def run_takes(self, codes, *, meeting=False, hidden_for_ms=None, next_press_after_ms=None,
                  live_ms=3000.0, until_ms=60_000.0):
        """The takes in order; returns the Pill and when the last one landed.

        hidden_for_ms: the Pill stands down for a fullscreen video from just before the
        last take lands until that long after. next_press_after_ms: the next take is
        pressed that long after the last one landed, held for live_ms, and lands with
        nothing to say about its formatting."""
        pill = Pill()
        streak = [None]

        def landing(code: str):
            return lambda: streak.__setitem__(0, land(pill, code, streak[0]))

        with patch("knight_flow.meeting_quiet.meeting_in_progress", return_value=meeting):
            start = 0.0
            for index, code in enumerate(codes):
                pill.at(start, pill.press)
                pill.at(start + HELD_MS, pill.release)
                landed = start + HELD_MS + FINISH_MS
                if index == len(codes) - 1 and hidden_for_ms is not None:
                    pill.at(landed - 300.0, lambda: pill.withdraw(True))
                    pill.at(landed + hidden_for_ms, lambda: pill.withdraw(False))
                pill.at(landed, landing(code))
                start = landed + TAKE_GAP_MS
            if next_press_after_ms is not None:
                pressed = landed + next_press_after_ms
                pill.at(pressed, pill.press)
                pill.at(pressed + live_ms, pill.release)
                pill.at(pressed + live_ms + FINISH_MS, landing(""))
            pill.clock.run_until(landed + until_ms)
        return pill, landed

    def assert_read_once(self, pill: Pill, landed: float, title: str) -> None:
        lines = [read for read in pill.read(landed) if read.startswith(title)]
        self.assertEqual(len(lines), 1, f"read after the take: {pill.read(landed)}; log: {pill.log}")

    def test_with_the_pill_visible_both_lines_are_read_in_order(self) -> None:
        for name, (codes, title) in LINES.items():
            with self.subTest(line=name):
                pill, landed = self.run_takes(codes)
                read = pill.read(landed)
                self.assertEqual(len(read), 2, pill.log)
                self.assertEqual(read[0], CAPTURED, "the take's own line was not read first, in full")
                self.assertTrue(read[1].startswith(title), read)

    def test_with_a_meeting_app_running_the_line_is_read(self) -> None:
        # Meeting quiet is on by default and Slack, Teams, Discord or Zoom merely running
        # counts: only errors and the person's own segments get through.
        for name, (codes, title) in LINES.items():
            with self.subTest(line=name):
                pill, landed = self.run_takes(codes, meeting=True)
                self.assert_read_once(pill, landed, title)

    def test_with_the_pill_withdrawn_the_line_is_read_when_it_comes_back(self) -> None:
        for name, (codes, title) in LINES.items():
            with self.subTest(line=name):
                pill, landed = self.run_takes(codes, hidden_for_ms=20_000.0)
                back = landed + 20_000.0
                self.assertEqual(pill.read(landed, until_ms=back), [], "something was said over the video")
                self.assert_read_once(pill, back, title)

    def test_the_next_press_never_cuts_the_line_for_good(self) -> None:
        # Overwatch measured the line cut, and not requeued, by a press 4-8 s later. Every
        # half second from 0.5 s to 12 s: the line is read in full, once, by the end.
        for name, (codes, title) in LINES.items():
            for after_ms in range(500, 12_001, 500):
                with self.subTest(line=name, press_after_ms=after_ms):
                    pill, landed = self.run_takes(codes, next_press_after_ms=float(after_ms))
                    self.assert_read_once(pill, landed, title)


if __name__ == "__main__":
    unittest.main()
