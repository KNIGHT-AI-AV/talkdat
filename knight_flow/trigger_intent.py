"""What a trigger press MEANS, given where the dictation pipeline is.

X-106. The trigger is one key doing three jobs, and the job is decided by
timing:

- Mic open (still holding / key auto-repeat firing): the press means
  nothing. Ignore it, or key-repeat would cancel every long dictation.
- Released, result in flight, pressed again ALMOST immediately: that is a
  finger bounce, not a decision -- someone says one word, lets go, and the
  key chatters. Cancelling a dictation on a bounce would throw away work on
  a twitch, so the in-flight result is left alone to deliver.
- Released, result in flight, pressed again after a beat: that is a person
  watching the rainbow and deciding "no -- redo". Cancel the in-flight
  dictation and let the press start the new one in the same motion.

Pure decisions, no Tk, so every timing rule is a table test.
"""
from __future__ import annotations

# Below this, a re-press is chatter, not intent. 300ms sits between switch
# bounce / accidental double-taps (well under 200ms) and the fastest
# deliberate "no, redo" a person actually performs (release, see the
# rainbow, press: ~400ms+).
BOUNCE_MS = 300

PRESS_IGNORE = "ignore"
PRESS_START = "start"
PRESS_BOUNCE = "bounce"
PRESS_CANCEL_AND_RESTART = "cancel_and_restart"


def press_intent(
    *,
    recording: bool,
    processing: bool,
    ms_since_release: float | None,
) -> str:
    """Decide what this trigger press should do.

    recording: the microphone is open right now (a session is capturing).
    processing: a released dictation is still being transcribed/formatted.
    ms_since_release: how long ago the trigger was released, if known.
    """
    if recording:
        return PRESS_IGNORE
    if not processing:
        return PRESS_START
    if ms_since_release is not None and ms_since_release < BOUNCE_MS:
        return PRESS_BOUNCE
    return PRESS_CANCEL_AND_RESTART


__all__ = [
    "BOUNCE_MS",
    "PRESS_BOUNCE",
    "PRESS_CANCEL_AND_RESTART",
    "PRESS_IGNORE",
    "PRESS_START",
    "press_intent",
]
