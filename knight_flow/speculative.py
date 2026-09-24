"""Paste immediately, correct afterwards.

Measured across 745 real dictations, the median time from releasing the key to
seeing text is 2021 ms, and 951 ms of that is the LLM rewrite. The rewrite is
worth having -- it fixes self-corrections, stammers and punctuation that rules
cannot -- but nothing about it needs to happen before the words appear.

So the local formatter's result is pasted straight away, at around 90 ms, and
the rewrite replaces it when it arrives. Wispr Flow reaches ~700 ms by running
a fine-tuned model on dedicated GPU infrastructure; renting inference through a
public API has a floor of roughly 550 ms no matter which model is chosen, so
matching them on raw speed is not available. Not making the person wait for it
is, and it lands ahead of them rather than behind.

That trade only holds while the correction is too quick to watch. It stops
holding for long dictation, and the first version did it anyway: the cap was
900 characters, the real cost is 4.3ms a keystroke, and the result was up to
3.9 seconds of a paragraph deleting itself one character at a time. Reported
from real use as "literally 30 seconds" on the even slower version before it,
and "there's no way anyone will want to watch it delete".

So there are now two decisions rather than one. `worth_speculating` runs first
and answers whether to speculate at all: past the replacement budget it does
not, and the dictation simply waits for the model and arrives once, finished,
with no edit. Nobody notices an extra second at the end of a paragraph they
spent thirty seconds speaking. `should_replace` then judges the cost of the
actual edit rather than the length of the text, so a long paragraph whose
rewrite only changes its last few words is still corrected cheaply.

Batching the keystrokes was tried first and does not work. A single Win32
SendInput call carrying the whole edit measured slower than one call per key,
3886ms against 3396ms for 900 characters: Windows throttles synthetic input per
event and the receiving application still processes every one. No arrangement
of keystrokes escapes the length, which is why the default is to stop doing
long replacements rather than to send them faster.

There is one way out, and it is not a keystroke arrangement at all. Editors
group a paste into a single undo step, so Ctrl+Z removes the whole thing in one
operation and the correction becomes two chords: measured at 100, 300 and 900
characters, 197ms every time. `undo_replacement` turns it on, and turns off the
length ceiling with it, because length has stopped mattering.

It is used only where it buys something. Under the budget, keystrokes cost
120-301ms against undo's flat 156ms, and that ~100ms is not worth undo's one
failure mode; past the budget the keystroke path is not slower, it is refused
outright, so the comparison becomes undo against no correction at all. Most
dictation is a single sentence, which keeps the great majority of corrections
on the path that cannot duplicate anything.

Verified in three real applications with three unrelated undo implementations,
by pasting, correcting, then reading the field back through the clipboard:
Notepad, a Win32 edit control, 156ms and correct at 120, 400 and 900
characters; an Edge textarea, Chromium, 158-227ms and correct; and a Tk Text
widget, 197ms. No duplication in any of them.

So it is on by default in those two engine families and off everywhere else,
which is what "auto" means and what the setting now defaults to. Off elsewhere
because an application with no undo ignores Ctrl+Z and the correction is pasted
after the original rather than over it, so the text appears twice; and one that
groups undo more coarsely than a paste removes something the person wrote.
Neither failure is detectable from here, because the target's contents cannot
be read back in the moment, and both are worse than a slow delete.

Deciding per application rather than globally is the only honest reading of the
evidence. A single boolean forces a choice between "fast and occasionally
destructive" and "safe and slow in the two places it was proven fast", and
neither is true. `paste.undo_is_verified_here` names the list; this module
stays pure and is told the answer.

The untested cases are the rich-text ones -- Word, WordPad, anything on
RichEdit -- and VS Code. Both attempts to close that gap failed, and how they
failed is worth knowing before a third is made.

WordPad could not be brought to the foreground: Windows refuses it to a
process launched from the background while another application holds the
foreground lock, and closing the user's browser to take the lock was not worth
a data point. Hosting a RICHEDIT50W control in-process avoided the foreground
problem and produced a different trap -- the control sat in a STATIC parent,
which does no dialog-style keyboard routing, so neither the undo nor the
corrected paste reached it and the field simply kept its original contents.
Read carelessly that looks like RichEdit refusing to undo. It is a harness
that never delivered a keystroke.

VS Code was the third attempt and failed for a third unrelated reason:
Cursor.exe returns WinError 740, requires elevation, and an agent runs
unelevated. Driving the copy already running was possible and not worth it --
the test sends Ctrl+A and Delete, and the editor holds someone's open files.

So the position is two undo implementations proven, Win32 edit controls and
Chromium, with the rich-text family and Monaco genuinely unknown rather than
suspected bad. A fourth attempt wants Word on a machine that has it, or a
RichEdit control in a real window with a real message loop -- not a STATIC
parent, which was attempt two and silently swallowed every keystroke.

One case is detectable and is refused outright: undo collapses to a single
step because the text arrived as a clipboard paste, and the remote-desktop
route types it instead. There, one Ctrl+Z is as likely to remove three words
as the whole insertion, so `app.py` allows the undo path only for the
clipboard and shift-insert routes.

The remaining risk sits in the replacement itself. Text is already on screen and
possibly already being typed over, so removing the wrong characters destroys
work that was never ours. Every rule below exists to make the replacement refuse
itself whenever it cannot prove it is safe -- and the cost of refusing is only
that someone keeps the locally formatted text, which is the text they get today.

Pure functions over plain values; the OS-touching part is separate and thin.
"""

from __future__ import annotations

from dataclasses import dataclass

# How long a correction may take before replacing is no longer reasonable. Past
# this, the odds that someone has moved on, clicked elsewhere or typed over the
# text stop being negligible, and a wrong replacement is far worse than a
# missing one.
MAX_REPLACE_AGE_SECONDS = 6.0

# What a synthetic keystroke actually costs, measured end to end: text typed
# into a real focused field, timed from the call until the field held the final
# string. 900 characters took 3886ms, which is 4.3ms each.
#
# This cannot be engineered away, and the attempt is worth recording so nobody
# repeats it. Batching the whole edit into a single Win32 SendInput call --
# one syscall instead of one per keystroke -- measured *slower*, 3886ms against
# 3396ms. Windows throttles synthetic input per event, and the receiving
# application still has to process every one. The cost is in the event stream,
# not in the number of calls that deliver it.
MILLISECONDS_PER_KEYSTROKE = 4.3

# How long the correction may visibly take. Past about a second the edit stops
# reading as a flicker and starts reading as the text rewriting itself, which
# is the thing that was reported as "literally 30 seconds" and "there's no way
# anyone will want to watch it delete".
#
# 500ms is deliberately below that. It keeps the correction for a normal
# spoken sentence, where the rewrite earns its place, and refuses it for a
# paragraph, where watching the delete is worse than keeping the local
# formatting -- which is exactly what the product delivered before speculative
# correction existed.
MAX_REPLACE_MILLISECONDS = 600

# Kept as a name because it reads better at the call site, but it is now a
# consequence of the budget rather than a number someone chose. It was 900,
# which at the measured rate is 3.9 seconds.
MAX_REPLACE_CHARS = int(MAX_REPLACE_MILLISECONDS / MILLISECONDS_PER_KEYSTROKE)


# What the three settings mean. "auto" is the default and the only one that
# looks at which application has focus.
UNDO_REPLACEMENT_CHOICES = ("auto", "always", "never")

_AFFIRMATIVE = {"always", "true", "yes", "on", "1"}


def undo_replacement_choice(setting: object) -> str:
    """Normalise a stored setting to one of UNDO_REPLACEMENT_CHOICES.

    Separate from `undo_replacement_enabled` because Settings has to show the
    choice without knowing which application happens to be in front, and two
    copies of this parsing would eventually disagree about what a stray value
    means.
    """
    if isinstance(setting, bool):
        return "always" if setting else "never"
    if isinstance(setting, str):
        text = setting.strip().lower()
        if text in {"auto", ""}:
            return "auto"
        return "always" if text in _AFFIRMATIVE else "never"
    # Anything that is neither a bool nor a string is not a setting anyone
    # meant to write, and the two remaining answers are not symmetric: "never"
    # costs a slower correction, "always" can paste someone's words twice into
    # an application whose undo was never tested. Truthiness would have made a
    # stray `0.5` or a non-empty list choose the destructive one.
    return "never"


def undo_replacement_enabled(setting: object, *, verified_application: bool) -> bool:
    """Resolve `dictation.undo_replacement` for the application in front.

    Three states rather than two, because two cannot say what the measurements
    actually support. Undo replacement is constant time and proven correct in
    Win32 edit controls and in Chromium, and completely unknown in RichEdit and
    Monaco. A boolean makes that either "fast, and sometimes duplicates your
    text" or "slow in the two places it was proven fast".

    - "auto"   -- on where the undo grouping was measured, off elsewhere.
    - "always" -- for someone who has tried their own editor and knows.
    - "never"  -- the old behaviour, always backspacing.

    `True` and `False` are still accepted so a config written by an older
    release, or by hand, keeps meaning what it meant.
    """
    choice = undo_replacement_choice(setting)
    if choice == "auto":
        return verified_application
    return choice == "always"


# How slow the model has to be before hiding it is worth a visible edit.
#
# Everything above is built on one measurement: the model round trip cost
# ~951ms, so pasting early saved most of a two-second wait. That number was
# true for a local speech model and an OpenRouter formatter. It stopped being
# true the moment the speech path moved to a hosted streaming provider -- 339ms
# measured against 1338ms local, on the same audio -- and the formatter moved
# to gemini-3.5-flash-lite at 379 output tok/s.
#
# Nothing noticed, because the decision to speculate was made on the LENGTH of
# the dictation and never on the wait it was hiding. So a fast pipeline kept
# paying the full price of speculation -- text that appears, then rewrites
# itself -- to conceal a delay that had become imperceptible. Reported from
# real use as "it keeps deleting itself and rewriting it, which is so stupid
# and really jarring".
#
# 450ms is the threshold because the wait a person actually feels is the whole
# post-speech pipeline, and ~1 second is the long-standing limit for keeping
# someone's train of thought uninterrupted. A cloud dictation spends ~339ms
# reaching final transcript, so a model answering within 450ms lands the
# finished text inside that second on the first try. Past it, arriving twice
# beats arriving late.
SPECULATION_WORTH_HIDING_MS = 450.0


def speculation_earns_its_keep(recent_model_ms: float | None) -> bool:
    """Whether hiding the model round trip is worth a visible correction.

    `recent_model_ms` is the typical measured cost of the model's formatting on
    this machine, or None before any has been measured.

    Unknown means yes. The first dictation after an install has no measurement
    and the safe default is the behaviour that was shipped and tested; a slow
    machine would otherwise pay a full uninstrumented wait to discover it is
    slow. One dictation later the answer is real.
    """
    if recent_model_ms is None:
        return True
    return recent_model_ms > SPECULATION_WORTH_HIDING_MS


@dataclass(frozen=True)
class ReplaceDecision:
    """Whether to replace, and why. The reason is for the log and the tests."""

    replace: bool
    reason: str
    backspaces: int = 0
    use_undo: bool = False


def worth_speculating(raw_length: int, *, undo_replacement: bool = False) -> bool:
    """Whether to paste the local formatting first and correct it afterwards.

    Speculating is only a good trade when the correction that follows is too
    quick to watch. Past that it inverts: the person sees their paragraph
    appear, then sees it deleted a character at a time, and the delete is
    slower and more alarming than simply having waited.

    So long dictation does not speculate at all. It waits for the model --
    about 950ms -- and the finished text arrives once, with no edit. Nobody
    notices an extra second at the end of a paragraph they spent thirty
    seconds speaking; everybody notices the paragraph deleting itself.

    The threshold is the replacement budget, because the worst case for a
    given length is a rewrite that changes the very first character and
    therefore retypes all of it.

    `undo_replacement` removes the threshold entirely. Undoing the paste and
    pasting the correction over it costs the same at 900 characters as at 100
    -- measured at 197ms either way -- so length stops being the thing that
    decides. It is opt-in because an application without undo pastes the
    correction after the original rather than over it, and text appearing
    twice is worse than text appearing late.
    """
    if undo_replacement:
        return True
    return raw_length <= MAX_REPLACE_CHARS


def should_replace(state: dict, *, now: float) -> ReplaceDecision:
    """Decide whether the improved text may overwrite what was pasted.

    `state` is read and never written, so the caller owns everything mutable
    and this stays a pure function of its inputs.
    """
    pasted = str(state.get("pasted_text", "") or "")
    improved = str(state.get("improved_text", "") or "")

    if not pasted:
        return ReplaceDecision(False, "nothing_pasted")
    if not improved:
        # A failed or empty rewrite must leave the good local text alone.
        return ReplaceDecision(False, "no_improvement")
    if improved == pasted:
        return ReplaceDecision(False, "identical")

    # The delivery has to have actually worked. Replacing after a failed paste
    # would delete whatever happens to be in front of the cursor instead.
    if not state.get("paste_succeeded", False):
        return ReplaceDecision(False, "paste_failed")

    # Typing into a different window would send the correction there. A zero
    # handle means Windows could not prove the target; two failed reads must
    # never become permission merely because ``0 == 0``.
    paste_window = int(state.get("paste_window", 0) or 0)
    foreground_window = int(state.get("foreground_window", 0) or 0)
    if not paste_window or not foreground_window or foreground_window != paste_window:
        return ReplaceDecision(False, "window_changed")

    if state.get("user_typed_since_paste", False):
        return ReplaceDecision(False, "user_typed")

    # A session already recording again means the person has moved on, and the
    # next dictation is about to paste into the same place.
    if state.get("session_active", False):
        return ReplaceDecision(False, "recording_again")

    age = now - float(state.get("pasted_at", 0.0) or 0.0)
    if age > MAX_REPLACE_AGE_SECONDS:
        return ReplaceDecision(False, "too_late")

    # Enter submits in most applications: the text has left, and backspacing
    # would eat whatever the field contains now.
    if state.get("sent_enter", False):
        return ReplaceDecision(False, "already_submitted")

    # Judge the cost of this particular edit, not the length of the text.
    #
    # The old test was `len(pasted) > MAX_REPLACE_CHARS`, which is the wrong
    # question twice over. A long paragraph whose rewrite only changes its last
    # few words costs a handful of keystrokes and was being refused; a short one
    # rewritten from the first character costs its whole length and was being
    # allowed. What the person sees is the keystrokes, so that is what decides.
    backspaces, _ = replacement_plan(pasted, improved)
    if backspaces <= MAX_REPLACE_CHARS:
        # Keystrokes, even where undo is available. Under the budget they cost
        # 120-301ms against undo's flat 156ms, and the ~100ms undo would save
        # is not worth its one failure mode: an application that groups undo
        # differently from a paste leaves the text twice over, and that cannot
        # be detected from here.
        #
        # Most dictation is one sentence, so this keeps the overwhelming
        # majority of corrections on the path that is incapable of duplicating
        # anything, and spends the risk only where it buys something.
        return ReplaceDecision(True, "replace", backspaces=backspaces)

    # Past the budget the keystroke path is not slow, it is refused -- watching
    # a paragraph delete itself is worse than keeping the local formatting. So
    # the comparison here is not "undo versus typing", it is "undo versus no
    # correction at all", and undo replaces the whole paste in one operation
    # whatever its length.
    if state.get("undo_replacement", False):
        return ReplaceDecision(True, "replace_by_undo", backspaces=backspaces, use_undo=True)
    return ReplaceDecision(False, "too_long", backspaces=backspaces)


def common_prefix_length(left: str, right: str) -> int:
    """How much of the two versions is identical from the start.

    The rewrite usually changes punctuation and a few words rather than the
    opening, so replacing only the differing tail cuts the number of synthetic
    keystrokes -- and every keystroke skipped is a smaller window in which the
    person can type into the middle of the replacement.
    """
    limit = min(len(left), len(right))
    index = 0
    while index < limit and left[index] == right[index]:
        index += 1
    return index


def replacement_plan(pasted: str, improved: str) -> tuple[int, str]:
    """(backspaces, text to type) to turn what was pasted into the improvement.

    Only the tail after the shared prefix is rewritten.
    """
    shared = common_prefix_length(pasted, improved)
    return len(pasted) - shared, improved[shared:]
