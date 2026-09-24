"""When to tell someone an update is waiting.

An update nobody installs is an update that does not exist, so the reminder is
not a nicety -- it is the mechanism by which a fix actually reaches anyone. But
this is a dictation app, and the failure mode on the other side is worse than
being ignored: a modal window that steals focus mid-sentence eats the words
someone was speaking. There is no undo for that.

Before this module the rule was "a silent check that finds anything opens the
update window immediately". That fires 2.6 seconds after launch, and again on a
24 hour timer that has no idea whether the microphone is live. Both are capable
of interrupting speech.

So reminders happen at seams -- moments when the person is demonstrably not in
the middle of something:

  START      the app just launched and settled, before any work has begun
  IDLE       a dictation finished and nothing replaced it
  RETURN     they came back to a machine that sat untouched
  QUIT       they are leaving anyway, which is the cheapest moment of all

and the same reminder gets more insistent the longer it is ignored, because a
week-old security fix and a day-old typo fix do not deserve the same patience.

Pure functions over a plain dict -- no tkinter, no network, no clock of its own
-- so every rule below is testable without a running app.
"""

from __future__ import annotations

from dataclasses import dataclass

HOUR = 3600
DAY = 24 * HOUR

# Seams at which a reminder may be shown. Anything not in this set is a moment
# we cannot prove is safe, and the answer there is silence.
TRIGGER_START = "start"
TRIGGER_IDLE = "idle"
TRIGGER_RETURN = "return"
TRIGGER_QUIT = "quit"
TRIGGERS = frozenset({TRIGGER_START, TRIGGER_IDLE, TRIGGER_RETURN, TRIGGER_QUIT})

# How long the machine must sit untouched before coming back counts as a return
# rather than a pause for thought.
RETURN_IDLE_SECONDS = 30 * 60

# A dictation app must not interrupt the sentence after the one it just heard,
# so a finished session is a seam only once the person has actually stopped.
IDLE_SETTLE_SECONDS = 45

# Escalation. The gap between reminders shrinks as the update ages, measured
# from when we first saw it rather than from install, so someone who leaves the
# app running for a fortnight is still told.
_ESCALATION: tuple[tuple[int, int], ...] = (
    (0, 3 * DAY),       # first three days: mention it every three days
    (3 * DAY, DAY),     # after three days: daily
    (14 * DAY, 8 * HOUR),  # after two weeks: three times a day
)

# A security update ignores the gentle end of that ramp. It still never
# interrupts speech -- it just stops waiting three days between mentions.
SECURITY_INTERVAL = 4 * HOUR

# Never show two reminders inside this window, whatever the trigger. Without it
# a quick succession of short dictations would each count as a seam.
MIN_SPACING = 90 * 60


@dataclass(frozen=True)
class ReminderDecision:
    """Whether to remind, and why. The reason is for logs and tests.

    Frozen because a decision that callers can edit is not a decision.
    """

    should_remind: bool
    reason: str
    intrusive: bool = False


def _interval_for(age_seconds: int, security: bool) -> int:
    """How long to wait between reminders for an update of this age."""
    if security:
        return SECURITY_INTERVAL
    interval = _ESCALATION[0][1]
    for threshold, gap in _ESCALATION:
        if age_seconds >= threshold:
            interval = gap
    return interval


def should_remind(state: dict, *, now: int) -> ReminderDecision:
    """Decide whether this moment is one to mention a waiting update.

    `state` is read, never written, so the caller owns persistence and this
    stays a pure function of the inputs.
    """
    if not state.get("update_available"):
        return ReminderDecision(False, "no_update")

    trigger = str(state.get("trigger", ""))
    if trigger not in TRIGGERS:
        return ReminderDecision(False, "not_a_seam")

    # Hard blocks. Each of these is a moment where a window would take
    # something away from the person rather than offer them something.
    if state.get("session_active"):
        return ReminderDecision(False, "dictating")
    if state.get("session_processing"):
        return ReminderDecision(False, "processing")
    if state.get("update_window_open"):
        return ReminderDecision(False, "already_showing")
    if state.get("onboarding_incomplete"):
        return ReminderDecision(False, "onboarding")
    # Someone presenting or recording their screen cannot afford a popup, and
    # they are exactly the audience most likely to be dictating in public.
    if state.get("presenting"):
        return ReminderDecision(False, "presenting")

    version = str(state.get("latest_version", ""))
    if version and version == str(state.get("skip_version", "")):
        return ReminderDecision(False, "skipped_version")

    snooze_until = int(state.get("snooze_until", 0) or 0)
    if snooze_until and now < snooze_until:
        return ReminderDecision(False, "snoozed")

    last_reminded = int(state.get("last_reminded_at", 0) or 0)
    if last_reminded and now - last_reminded < MIN_SPACING:
        return ReminderDecision(False, "too_soon")

    # Leaving is the one seam with nothing to interrupt, so it is offered
    # regardless of where the escalation ramp currently sits. This is the moment
    # an update most often actually gets installed.
    if trigger == TRIGGER_QUIT:
        return ReminderDecision(True, "quit", intrusive=False)

    if trigger == TRIGGER_IDLE:
        settled = int(state.get("seconds_since_session", 0) or 0)
        if settled < IDLE_SETTLE_SECONDS:
            return ReminderDecision(False, "still_working")

    if trigger == TRIGGER_RETURN:
        away = int(state.get("seconds_idle", 0) or 0)
        if away < RETURN_IDLE_SECONDS:
            return ReminderDecision(False, "not_really_away")

    security = bool(state.get("security_update"))
    first_seen = int(state.get("first_seen_at", 0) or 0)
    age = max(0, now - first_seen) if first_seen else 0
    interval = _interval_for(age, security)

    if last_reminded and now - last_reminded < interval:
        return ReminderDecision(False, "waiting_out_interval")

    # Only a security fix, or one that has been ignored for a fortnight, earns a
    # window that takes focus. Everything else is a badge and a toast the person
    # can finish their thought before looking at.
    intrusive = security or age >= 14 * DAY
    return ReminderDecision(True, "due", intrusive=intrusive)


def next_snooze(now: int, *, times_snoozed: int) -> int:
    """When a snoozed reminder should come back.

    Snoozing repeatedly is a person saying "not now" more firmly each time, so
    the gap grows -- but it is capped, because an update that never returns is
    the failure this whole module exists to prevent.
    """
    hours = min(24, 2 ** max(0, times_snoozed))
    return now + hours * HOUR
