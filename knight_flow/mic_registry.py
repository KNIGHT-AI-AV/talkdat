"""X-175: one place that tracks microphone owners which explicitly opt in.

Talk DAT! opens the microphone from more surfaces than the dictation session:
live captions, the Settings level meter, Mic Doctor, Race, pronunciation
practice, Translation's Speak, and onboarding's rehearsal. Each one managed its
own stream and its own stop, and the app-level answers were written as though
only the dictation session existed.

Two consequences, both found by the 0.4.104 UI/UX audit and both confirmed by
reading the source:

    panic_stop() is `self.cancel()` and nothing else, so Panic silences the one
    owner and leaves every other surface recording.

    The diagnostics pane says, verbatim, "Mic/Deepgram are active only when
    session_active is true." That sentence is FALSE whenever another surface
    holds the microphone, and it is exactly the sentence a person reads when
    they want to know whether they are being listened to.

A false "the microphone is off" is worse than no claim at all. This registry
therefore reports only its explicit participants; callers must not present an
empty registry as proof that every capture engine in the process is closed.

Design notes that are not obvious:

* Owners register their OWN stopper. Panic therefore does not need to know what
  captions or Mic Doctor are, and a surface added later cannot be forgotten by
  Panic. It can only be forgotten by never registering, which is the one failure
  a reviewer can actually see.

* Tokens are monotonic and never reused. A late release() from a torn-down page
  has to be a harmless no-op; with recycled ids it would instead free whichever
  owner inherited the number, silently marking a live microphone as closed. That
  is precisely the bug this module exists to prevent, so it must not contain it.

* stop_all() never holds the lock while calling a stopper. Stoppers call
  release(), which takes the same lock, so holding it across the call would
  deadlock the panic path, and a deadlocked panic button is worse than none.

No audio dependency and no tkinter dependency, so all of it is testable without
a microphone or a display.
"""

from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable

log = logging.getLogger(__name__)

# Owner names are stable strings because a person reads them in the diagnostics
# pane. "settings-meter" tells someone what is listening; an object repr does not.
DICTATION = "dictation"
CAPTIONS = "live-captions"
SETTINGS_METER = "settings-meter"
MIC_DOCTOR = "mic-doctor"
TRANSLATION = "translation-speak"
ONBOARDING = "onboarding-rehearsal"
RACE = "race"
PRONUNCIATION = "pronunciation-practice"
MEETING = "meeting-scribe"

# A stopper normally gives the registry a second, idempotent release after it
# returns. Drivers that close on a worker must keep their owner visible until
# that worker has actually stopped and closed the handle. Returning this exact
# sentinel transfers final release ownership to that asynchronous closer.
DEFERRED_MICROPHONE_RELEASE = object()


@dataclass(frozen=True)
class MicOwner:
    """One live microphone holder, in the terms a person would want."""

    token: int
    name: str
    device: str
    phase: str
    started_at: float

    def held_seconds(self, now: float | None = None) -> float:
        return max(0.0, (time.time() if now is None else now) - self.started_at)


class MicrophoneRegistry:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._owners: dict[int, MicOwner] = {}
        self._stoppers: dict[int, Callable[[], object] | None] = {}
        self._next_token = 1

    def acquire(
        self,
        name: str,
        *,
        device: str = "",
        phase: str = "starting",
        stop: Callable[[], object] | None = None,
    ) -> int:
        """Register a microphone holder and return its token.

        `stop` is what Panic will call. An owner that passes None is still
        DISCLOSED; it simply cannot be stopped centrally, which is strictly
        better than being invisible.
        """
        with self._lock:
            token = self._next_token
            self._next_token += 1
            self._owners[token] = MicOwner(
                token=token,
                name=str(name),
                device=str(device),
                phase=str(phase),
                started_at=time.time(),
            )
            self._stoppers[token] = stop
        log.info("microphone acquired: %s (token %d)", name, token)
        return token

    def set_phase(self, token: int, phase: str) -> None:
        """Update what this owner is doing. Unknown tokens are ignored."""
        with self._lock:
            owner = self._owners.get(int(token))
            if owner is None:
                return
            self._owners[int(token)] = MicOwner(
                token=owner.token,
                name=owner.name,
                device=owner.device,
                phase=str(phase),
                started_at=owner.started_at,
            )

    def release(self, token: int | None) -> bool:
        """Give the microphone back. Idempotent, and safe with a stale token."""
        if token is None:
            return False
        with self._lock:
            owner = self._owners.pop(int(token), None)
            self._stoppers.pop(int(token), None)
        if owner is not None:
            log.info("microphone released: %s (token %d)", owner.name, token)
        return owner is not None

    def owners(self) -> tuple[MicOwner, ...]:
        with self._lock:
            return tuple(sorted(self._owners.values(), key=lambda owner: owner.token))

    def is_active(self) -> bool:
        with self._lock:
            return bool(self._owners)

    def names(self) -> tuple[str, ...]:
        return tuple(owner.name for owner in self.owners())

    def stop_all(self) -> tuple[str, ...]:
        """Stop every owner. Returns the names that did NOT come back.

        The lock is taken to snapshot and then RELEASED before any stopper runs,
        because a well-behaved stopper calls release(), which takes the same
        lock.

        A stopper that raises must not prevent the others from running: the whole
        point is that one broken surface cannot hold the microphone open for the
        rest.
        """
        with self._lock:
            snapshot = [
                (token, owner.name, self._stoppers.get(token))
                for token, owner in self._owners.items()
            ]

        for token, name, stop in snapshot:
            if stop is None:
                log.error("microphone owner %s has no stopper", name)
                self.set_phase(token, "stop-failed")
                continue
            try:
                stop_result = stop()
            except Exception:
                log.exception("microphone owner %s failed to stop", name)
                self.set_phase(token, "stop-failed")
                continue
            if stop_result is not DEFERRED_MICROPHONE_RELEASE:
                # Belt and braces: a synchronous stopper that forgets to release
                # must not leave a phantom owner making is_active() true forever.
                # An asynchronous closer opts out explicitly and releases only
                # after the driver handle is genuinely closed.
                self.release(token)

        remaining = self.names()
        if remaining:
            phases = {owner.phase for owner in self.owners()}
            if phases and phases <= {"closing"}:
                log.info("panic stop is waiting for microphone close: %s", remaining)
            else:
                log.error("panic stop left microphone owners behind: %s", remaining)
        return remaining

    def describe(self) -> tuple[str, ...]:
        """Lines for the diagnostics pane, written for a person."""
        owners = self.owners()
        if not owners:
            return ("Registered auxiliary microphone tests: none active.",)
        now = time.time()
        lines = [f"Registered auxiliary microphone tests: {len(owners)} active."]
        for owner in owners:
            device = owner.device or "default device"
            lines.append(
                f"  {owner.name}: {owner.phase}, {device}, held {owner.held_seconds(now):.0f}s"
            )
        return tuple(lines)


@contextmanager
def microphone_held(
    name: str,
    *,
    device: str = "",
    phase: str = "listening",
    stop: Callable[[], object] | None = None,
):
    """Hold the microphone for the duration of a block, and always give it back.

    The `finally` is the entire point. Every disclosure bug in the audit had the
    same shape: a stream that was stopped on the happy path and left open on an
    exception, an early return, or a window being navigated away from rather
    than closed. A context manager cannot forget any of those.

    Use this wherever the capture is scoped to a block. Where the stream
    genuinely outlives its function (the dictation session, the wake listener),
    call acquire/release directly and pair them in the object's own start/stop.
    """
    registry = microphone_registry()
    token = registry.acquire(name, device=device, phase=phase, stop=stop)
    try:
        yield token
    finally:
        registry.release(token)


# One registry per process. Threading it through every constructor was considered
# and rejected: the surfaces that most need to be in it are exactly the ones built
# ad hoc deep inside overlay.py, and a registry that is inconvenient to reach is a
# registry the next surface will skip.
_REGISTRY = MicrophoneRegistry()


def microphone_registry() -> MicrophoneRegistry:
    return _REGISTRY
