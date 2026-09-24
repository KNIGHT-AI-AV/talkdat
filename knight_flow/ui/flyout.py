"""One popup contract for the whole application.

His report, and it is four separate faults in one sentence: "the menu does not
disappear when inactive. It requires industry-standard menu pop-ups that vanish
when not active, reappear if the user has not yet pressed enter, and preserve
the text the user was in the middle of typing in case they click away. The
feature must be both hover-activated and click-activated."

Every popup in this app currently invents its own answer to that. The theme
picker closes on ``<FocusOut>``, the help tooltip closes on ``<Leave>``, the
history overflow closes on neither, and none of them opens on hover or keeps a
half-typed value. Four surfaces, four behaviours, and a person cannot learn any
of them because none agrees with the others.

The state machine lives here, in one place, with no tkinter import, so it can be
reasoned about and tested without a display -- the same split ``pill_motion``
uses for the Pill's animation maths. The Tk bindings that drive it are a thin
layer above; they decide *when* an event happened, this decides *what it means*.

Two decisions worth stating, because both are the difference between a menu that
feels industry-standard and one that feels almost right:

**Hover opens after a delay, and closes after a longer one.** Opening instantly
on hover means a menu flashes at you every time the pointer crosses the bar on
its way somewhere else. Closing instantly on leave means the diagonal path from
a trigger to the item you want -- which always leaves the trigger before it
reaches the popup -- dismisses the thing you were reaching for. The asymmetry is
the whole trick, and it is why ``OPEN_DELAY_MS`` is short and ``CLOSE_GRACE_MS``
is roughly twice it.

**A click is not a slower hover.** Clicking commits: it opens now, with no
delay, and it pins the popup open so crossing the pointer away no longer closes
it. Only a click elsewhere, Escape, or a choice will close a pinned popup. This
is what makes a menu usable with a trackpad and what makes it keyboard-safe.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Final


#: How long the pointer must rest on a trigger before its popup opens.
#: Short enough to feel like a hover, long enough that crossing the control on
#: the way somewhere else never opens anything.
OPEN_DELAY_MS: Final[int] = 320

#: How long a popup survives after the pointer leaves both it and its trigger.
#: Deliberately longer than OPEN_DELAY_MS: the pointer's path from a trigger to
#: the row it wants leaves the trigger before it reaches the popup, and every
#: menu that closes instantly on leave is unusable for exactly that reason.
CLOSE_GRACE_MS: Final[int] = 620


@dataclass
class Draft:
    """What a person had typed, and whether they had finished saying it.

    Preserved across a close so clicking away does not destroy work. ``committed``
    is the Enter key: once they have committed, the draft is spent and reopening
    starts clean rather than re-offering a value that has already been applied.
    """

    text: str = ""
    committed: bool = False


@dataclass
class Flyout:
    """The open/closed state of one popup, and every reason it changes.

    Every method returns the action the caller should now take -- ``"open"``,
    ``"close"``, ``"schedule_open"``, ``"schedule_close"``, ``"cancel_open"``,
    ``"cancel_close"`` or ``None`` -- rather than doing it. That is what lets the
    whole contract be tested with no display: the decisions are here, and the
    only thing Tk contributes is the timer and the event.
    """

    open: bool = False
    #: True once a click opened it. A pinned popup ignores the pointer leaving.
    pinned: bool = False
    pointer_in_trigger: bool = False
    pointer_in_popup: bool = False
    open_pending: bool = False
    close_pending: bool = False
    drafts: dict[str, Draft] = field(default_factory=dict)

    # -- pointer ---------------------------------------------------------

    def pointer_entered_trigger(self) -> str | None:
        self.pointer_in_trigger = True
        if self.close_pending:
            self.close_pending = False
            return "cancel_close"
        if self.open or self.open_pending:
            return None
        self.open_pending = True
        return "schedule_open"

    def pointer_left_trigger(self) -> str | None:
        self.pointer_in_trigger = False
        if self.open_pending and not self.open:
            # They passed over it on the way somewhere else. Nothing opened, so
            # nothing has to close; just forget the intention.
            self.open_pending = False
            return "cancel_open"
        return self._maybe_schedule_close()

    def pointer_entered_popup(self) -> str | None:
        self.pointer_in_popup = True
        if self.close_pending:
            self.close_pending = False
            return "cancel_close"
        return None

    def pointer_left_popup(self) -> str | None:
        self.pointer_in_popup = False
        return self._maybe_schedule_close()

    def _maybe_schedule_close(self) -> str | None:
        if self.pinned or not self.open:
            return None
        if self.pointer_in_trigger or self.pointer_in_popup:
            return None
        if self.close_pending:
            return None
        self.close_pending = True
        return "schedule_close"

    # -- timers ----------------------------------------------------------

    def open_timer_fired(self) -> str | None:
        """The hover delay elapsed. Open only if the pointer is still there."""

        self.open_pending = False
        if self.open or not self.pointer_in_trigger:
            return None
        self.open = True
        return "open"

    def close_timer_fired(self) -> str | None:
        """The grace period elapsed. Close only if the pointer is still away."""

        self.close_pending = False
        if not self.open or self.pinned:
            return None
        if self.pointer_in_trigger or self.pointer_in_popup:
            return None
        self.open = False
        return "close"

    # -- click, keyboard, and the world outside --------------------------

    def clicked_trigger(self) -> str | None:
        """A click toggles, immediately, and pins what it opens.

        Clicking a popup that hover already opened does not close it -- that
        reads as the menu fighting you. It pins the popup that is already there,
        which is what a person means by clicking something they can see.
        """

        if self.open:
            if not self.pinned:
                self.pinned = True
                return "cancel_close" if self.close_pending else None
            self.open = False
            self.pinned = False
            return "close"
        self.open_pending = False
        self.open = True
        self.pinned = True
        return "open"

    def clicked_outside(self) -> str | None:
        """A click anywhere else always closes, pinned or not."""

        if not self.open:
            return None
        self.open = False
        self.pinned = False
        self.close_pending = False
        return "close"

    def escaped(self) -> str | None:
        return self.clicked_outside()

    def focus_left(self) -> str | None:
        """Focus moved to another window. Same meaning as a click outside."""

        return self.clicked_outside()

    def chose(self) -> str | None:
        """A row was picked. The popup has done its job."""

        return self.clicked_outside()

    def dismissed(self, reason: str) -> str | None:
        """The view is closing its popup, and says why.

        X-540: the one close path an adapter offers a view. "escape", "focus",
        "chose" and "outside" are the dismissals above by name, so a view hands
        over the reason it already knows instead of choosing a method; any
        other reason ("destroyed", "failed") means the popup is already gone
        and there is nothing left to close, only flags to clear.
        """

        if reason == "escape":
            return self.escaped()
        if reason == "focus":
            return self.focus_left()
        if reason == "chose":
            return self.chose()
        if reason == "outside":
            return self.clicked_outside()
        return self.popup_gone()

    def popup_gone(self) -> None:
        """The popup no longer exists, by a path this machine did not decide.

        A host teardown, a build that failed halfway, a fade that finished: the
        view is closed whatever the flags say, so the flags follow the view.
        This is what X-537's adapter had no way to hear, and why a menu closed
        by Escape took two or three clicks to reopen: the machine still held
        ``open`` (and, after a click-open, ``pinned``), so the next click
        "pinned" or "closed" a menu that was not there.

        Left alone on purpose: ``pointer_in_trigger``, because a menu that was
        just dismissed must not pop straight back while the hand has not
        moved; and ``open_pending``, because a hover intent that is already
        counting belongs to the next popup, not to this one.
        """

        self.open = False
        self.pinned = False
        self.close_pending = False
        self.pointer_in_popup = False
        return None

    # -- drafts ----------------------------------------------------------

    def remember(self, key: str, text: str, *, committed: bool = False) -> None:
        """Hold what was typed into ``key`` so closing does not destroy it.

        Called as the popup closes, for every field inside it. An empty,
        uncommitted value is not worth keeping and is dropped, so a reopened
        popup does not carry a stale blank around forever.
        """

        value = str(text)
        if not value and not committed:
            self.drafts.pop(key, None)
            return
        self.drafts[key] = Draft(text=value, committed=bool(committed))

    def restore(self, key: str) -> str:
        """What to put back into ``key`` when the popup reopens.

        Empty once they have pressed Enter: a committed value has already been
        applied, and re-offering it would look like the app failed to take it.
        """

        draft = self.drafts.get(key)
        if draft is None or draft.committed:
            return ""
        return draft.text

    def commit(self, key: str) -> None:
        """Enter was pressed. The draft is spent."""

        draft = self.drafts.get(key)
        if draft is not None:
            draft.committed = True

    def forget(self, key: str) -> None:
        self.drafts.pop(key, None)


@dataclass
class Wiring:
    """What an adapter hands back to the view that owns the trigger.

    X-540. ``state`` is the machine above, for reading. ``close(reason, *,
    on_complete=None)`` is the ONE way a view closes its popup: the state is
    reconciled first, then the popup is dismissed, then the action runs; a
    second call, or a call with no popup, does nothing more. ``retire()``
    cancels every timer and makes the wiring inert, for when the trigger
    itself is going away.
    """

    state: Flyout
    close: Callable[..., None]
    retire: Callable[[], None]


__all__ = ["CLOSE_GRACE_MS", "OPEN_DELAY_MS", "Draft", "Flyout", "Wiring"]
