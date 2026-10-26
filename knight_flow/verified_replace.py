"""T1: a polished rewrite replaces the draft only where the draft provably still is.

Why this exists. The instant draft -- the locally formatted text, pasted at
once -- and the model's polished version arrive about a second apart. The old
route bridged that second by editing the person's document after the fact
(backspaces, later Ctrl+Z then Ctrl+V), and it was switched off on 2026-08-21
(bc301a9) for a sound reason: after a committed Ctrl+Z and a failed Ctrl+V no
probe could prove what the document then held, and the person's own words were
what stood to be lost. Since then a dictation waits for the polish and arrives
once.

This module is the way back to the fast draft without that risk. It never
deletes by count and never acts on a guess. A replacement happens only when an
accessibility read -- the same kind caret_context.py already makes -- proves,
at that moment, all of:

* the same window and the same focused element the draft went into;
* a collapsed caret, no selection, not a password field;
* the text before and after the caret is exactly what it was right after the
  draft landed: so nothing was typed, pasted, deleted or moved, anywhere in the
  read window, and the draft is the text immediately before the caret;
* the take that inserted the draft is still the current one, nothing is
  recording, and the polish is not late.

Even then the edit is select-verify-paste, not delete-and-retype: the exact
draft range is selected through the accessibility API, the selection is read
back and must equal the draft, and only then is the polish pasted over it, with
a read-back afterwards. Any step that cannot be proved stops, collapses the
selection back to where the caret was, and keeps the polished text as an
ALTERNATIVE of that take for the person to insert on purpose.

Refusing costs the person nothing they had before: the draft they already see
stays exactly as it is.

Pure over plain values and a small adapter protocol; the UI Automation and AX
adapters live with the platform code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

#: Past this, the person has very likely moved on; a late polish is kept, not applied.
MAX_AGE_SECONDS = 6.0

#: Text this many characters before the draft (and after the caret) must be
#: unchanged. The adapter reads at least len(draft) + this much to the left.
ANCHOR_CHARS = 32

#: Delivery routes whose insertion is one contiguous, readable text change.
#: Typing (remote desktop) and copy-only are never replaced.
REPLACEABLE_ROUTES = frozenset({"clipboard", "shift_insert"})


def _norm(text: str) -> str:
    """Editors report line breaks as \\r\\n, \\r or \\n; compare them as one."""
    return str(text or "").replace("\r\n", "\n").replace("\r", "\n")


def field_form(left: str, text: str) -> str | None:
    """The draft exactly as the field holds it: the shortest tail of ``left``
    that reads as ``text``. A Windows edit control stores a pasted "\\n" as
    "\\r\\n", so the field's copy can be longer than what was pasted, and a
    selection must cover the field's characters, not the paste's."""
    left, want = str(left or ""), _norm(text)
    if not want:
        return None
    for size in range(len(want), 2 * len(want) + 1):
        if size > len(left):
            break
        tail = left[-size:]
        if _norm(tail) == want:
            # A tail opening on the "\n" of a "\r\n" pair must take the "\r" too.
            if tail.startswith("\n") and len(left) > size and left[-size - 1] == "\r":
                tail = left[-size - 1:]
            return tail
    return None


@dataclass(frozen=True)
class TargetRead:
    """One accessibility read of the focused field. ``ok`` is False when the
    read failed, timed out or the control offers no text pattern."""

    ok: bool
    window: int = 0
    element: tuple = ()
    left: str = ""
    right: str = ""
    collapsed: bool = False
    password: bool = False


@dataclass(frozen=True)
class Draft:
    """The instant draft as it was inserted, with the reads around it."""

    take: object
    text: str
    inserted_at: float
    before: TargetRead
    after: TargetRead
    route: str = "clipboard"
    succeeded: bool = True


@dataclass(frozen=True)
class Decision:
    replace: bool
    reason: str


def insertion_proved(draft: Draft) -> str:
    """"" when the reads around the insertion show the draft landed exactly at
    the caret, as one contiguous change; otherwise the reason it is not proved."""
    before, after, text = draft.before, draft.after, _norm(draft.text)
    if not (before.ok and after.ok):
        return "insertion_unread"
    if not text:
        return "insertion_empty"
    if not before.window or before.window != after.window or not before.element or before.element != after.element:
        return "insertion_moved"
    if not (before.collapsed and after.collapsed) or before.password or after.password:
        return "insertion_unsafe_field"
    left_after = _norm(after.left)
    if not left_after.endswith(text):
        # The field changed the text on the way in (autocorrect, smart quotes,
        # a rich-text conversion) or the read was too short to see all of it.
        return "insertion_not_verbatim"
    prefix_after = left_after[: len(left_after) - len(text)]
    prefix_before = _norm(before.left)
    if not prefix_before.endswith(prefix_after):
        return "insertion_moved"
    if len(prefix_after) < min(ANCHOR_CHARS, len(prefix_before)):
        # The read after the paste must still reach back over the anchor.
        return "insertion_read_too_short"
    if _norm(after.right) != _norm(before.right):
        return "insertion_not_at_caret"
    return ""


def decide(draft: Draft, now: TargetRead, polished: str, *, now_s: float, current_take: object,
           recording: bool) -> Decision:
    """Whether the polished text may replace the draft right now. One reason per
    refusal, in the order a person would understand them."""
    text, better = _norm(draft.text), _norm(polished)
    if not better.strip():
        return Decision(False, "no_polish")
    if better == text:
        return Decision(False, "identical")
    if not draft.succeeded:
        return Decision(False, "draft_not_delivered")
    if draft.route not in REPLACEABLE_ROUTES:
        return Decision(False, "route_not_replaceable")
    proof = insertion_proved(draft)
    if proof:
        return Decision(False, proof)
    if current_take is not draft.take:
        return Decision(False, "newer_take")
    if recording:
        return Decision(False, "recording_again")
    if now_s - draft.inserted_at > MAX_AGE_SECONDS:
        return Decision(False, "too_late")
    if not now.ok:
        return Decision(False, "unreadable")
    if now.password:
        return Decision(False, "password_field")
    if not now.window or now.window != draft.after.window:
        return Decision(False, "other_window")
    if not now.element or now.element != draft.after.element:
        return Decision(False, "other_field")
    if not now.collapsed:
        return Decision(False, "selection")
    if _norm(now.left) != _norm(draft.after.left):
        return Decision(False, "changed_before_caret")
    if _norm(now.right) != _norm(draft.after.right):
        return Decision(False, "changed_after_caret")
    return Decision(True, "replace")


class TargetAdapter(Protocol):
    """What the replacement needs from a platform (UI Automation, AX)."""

    def read(self, left_chars: int) -> TargetRead: ...

    def select_before_caret(self, text: str) -> str | None:
        """Select the ``len(text)`` characters before the caret and return the
        selected text as read back, or None when nothing could be selected."""

    def collapse_to(self, read: TargetRead) -> None:
        """Put the caret back where ``read`` saw it, with no selection."""

    def paste(self, text: str) -> bool:
        """Paste over the current selection; True when the paste was delivered."""


@dataclass
class Outcome:
    replaced: bool
    reason: str
    #: The polished text, kept whenever it was not applied (or not proved applied).
    alternative: str | None = None
    steps: list[str] = field(default_factory=list)


def read_bound(draft_text: str) -> int:
    return len(_norm(draft_text)) + ANCHOR_CHARS


def as_delivered(polished: str, formatted: str, delivered: str, drop_period: Any) -> str | None:
    """The polish shaped for the field the way the paste layer shaped the draft.

    ``formatted`` is the draft as the app handed it to the paste layer and
    ``delivered`` what the paste layer put in the field: possibly with a
    leading space, possibly without the trailing period a chat app drops from
    one sentence (``drop_period`` is that rule). The polish gets the same
    shaping. None when the draft's shaping cannot be read off the two, so the
    polish is kept rather than pasted in a shape nobody checked.
    """
    polished, formatted, delivered = str(polished or ""), str(formatted or ""), str(delivered or "")
    lead, rest = "", delivered
    if delivered.startswith(" ") and not formatted.startswith(" "):
        lead, rest = " ", delivered[1:]
    if rest == formatted:
        return lead + polished
    dropped = drop_period(formatted)
    if dropped != formatted and rest == dropped:
        return lead + drop_period(polished)
    return None


def replace_if_proved(adapter: TargetAdapter, draft: Draft, polished: str, *, now_s: float,
                      current_take: object, recording: bool) -> Outcome:
    """Decide, select, verify, paste, verify. Every failure keeps the alternative."""
    now = adapter.read(read_bound(draft.text))
    decision = decide(draft, now, polished, now_s=now_s, current_take=current_take, recording=recording)
    if not decision.replace:
        keep = None if decision.reason in ("no_polish", "identical") else polished
        return Outcome(False, decision.reason, keep, ["decided"])
    steps = ["decided"]
    held = field_form(now.left, draft.text)
    if held is None:
        return Outcome(False, "changed_before_caret", polished, steps)
    selected = adapter.select_before_caret(held)
    steps.append("selected")
    if selected is None or selected != held:
        adapter.collapse_to(now)
        steps.append("collapsed")
        return Outcome(False, "selection_not_the_draft", polished, steps)
    # The selection must not have moved the field or the text around it.
    selecting = adapter.read(read_bound(draft.text))
    if (not selecting.ok or selecting.window != now.window or selecting.element != now.element
            or selecting.collapsed or selecting.password):
        adapter.collapse_to(now)
        steps.append("collapsed")
        return Outcome(False, "selection_unproved", polished, steps)
    if not adapter.paste(polished):
        adapter.collapse_to(now)
        steps.append("collapsed")
        return Outcome(False, "paste_failed", polished, steps)
    steps.append("pasted")
    after = adapter.read(len(_norm(polished)) + ANCHOR_CHARS)
    expected_left = _norm(now.left)[: len(_norm(now.left)) - len(_norm(draft.text))] + _norm(polished)
    if (after.ok and after.window == now.window and after.element == now.element and after.collapsed
            and expected_left.endswith(_norm(after.left)) and _norm(after.left).endswith(_norm(polished))
            and _norm(after.right) == _norm(now.right)):
        steps.append("verified")
        return Outcome(True, "replaced", None, steps)
    # Something landed that cannot be proved to be the polish over the draft.
    # Keep the polish and tell the person to look; never try to repair it. A
    # paste that never arrived leaves the draft selected, and the next key
    # would replace it: put the caret back after whatever the field now holds.
    adapter.collapse_to(now)
    steps.append("collapsed")
    steps.append("unverified")
    return Outcome(False, "check_the_text", polished, steps)


def keep_alternative(entry: dict[str, Any], polished: str, reason: str) -> dict[str, Any]:
    """The take's History record, with the polished version kept beside the draft.

    The record keeps what was delivered (`text`) and what was said (`original`)
    untouched; the alternative is offered, never substituted.
    """
    alternatives = [item for item in entry.get("alternatives", []) if isinstance(item, dict)]
    if not any(item.get("kind") == "polished" and item.get("text") == polished for item in alternatives):
        alternatives.append({"kind": "polished", "text": polished, "reason": reason})
    return {**entry, "alternatives": alternatives}
