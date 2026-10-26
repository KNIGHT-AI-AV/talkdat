"""X-338: the local-route network fence.

The founder's guarantee, verbatim intent: "when local is activated ...
100% confirmed and guaranteed to not be uploading anything. It needs to
be locked down." Route resolution already keeps speech and finishing on
this PC when Local is selected (X-192) -- this module makes that a
GUARANTEE instead of a convention: while the fence is up, every
cloud-bound helper refuses at the socket boundary, so even a future bug
that mis-resolves a provider cannot quietly ship audio or text off the
machine.

Localhost is exempt on purpose: a local Ollama formatter and any
on-device HTTP loopback ARE this machine.

Pure stdlib, no tkinter, importable by tests.
"""

from __future__ import annotations

import threading
from urllib.parse import urlparse


class LocalOnlyBlocked(RuntimeError):
    """A cloud call was attempted while the Local route was active."""


_LOCAL_ONLY = threading.Event()

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


def loopback_ipv4(url: str) -> str:
    """The same URL with a "localhost" host spelled 127.0.0.1.

    X-605, measured on the owner's PC 2026-09-23: Ollama listens on
    127.0.0.1 only, and Python resolves "localhost" to ::1 first. On Windows a
    refused loopback connect is retried for about a second before the IPv4
    address is tried, so every formatting request paid 1.2 to 1.8 s before
    Ollama saw it (format_ms 2.3-3.3 s for a 0.2-0.6 s answer), and the 0.35 s
    readiness check could give up first and send the take to the rules
    formatter. Saved settings keep saying "localhost"; requests go to 127.0.0.1.
    """
    from urllib.parse import urlsplit, urlunsplit

    try:
        parts = urlsplit(str(url))
        if (parts.hostname or "").lower() != "localhost" or parts.username or parts.password:
            return url
        netloc = "127.0.0.1" + (f":{parts.port}" if parts.port else "")
    except ValueError:
        return url
    return urlunsplit(parts._replace(netloc=netloc))


def set_local_only(on: bool) -> None:
    if on:
        _LOCAL_ONLY.set()
    else:
        _LOCAL_ONLY.clear()


def local_only() -> bool:
    return _LOCAL_ONLY.is_set()


class TakeNet:
    """T7: one take's view of the fence. ``locked`` holds the fence up for this
    take whatever the global route says; ``attempts`` records every outbound
    connection a content helper asked for while the take was open -- the host,
    which helper, and whether it was refused -- for the take's receipt."""

    def __init__(self, locked: bool) -> None:
        self.locked = bool(locked)
        self.attempts: list[dict[str, object]] = []


_TAKES: list[TakeNet] = []
_TAKES_LOCK = threading.Lock()


def begin_take(*, locked: bool) -> TakeNet:
    """Open a take's fence view. Takes are sequential, but a cancelled take can
    still be finishing while the next one starts, so every open view counts:
    the fence holds while ANY open take is locked."""
    take = TakeNet(locked)
    with _TAKES_LOCK:
        _TAKES.append(take)
    return take


def end_take(take: TakeNet) -> None:
    with _TAKES_LOCK:
        if take in _TAKES:
            _TAKES.remove(take)


def take_locked() -> bool:
    with _TAKES_LOCK:
        return any(take.locked for take in _TAKES)


def _is_this_machine(host: str) -> bool:
    return host in _LOCAL_HOSTS or host.endswith(".localhost")


def assert_cloud_allowed(target: str, what: str) -> None:
    """Raise unless the fence is down or ``target`` is this machine.

    ``target`` may be a full URL or a bare host. Call this at the entry of
    every helper that opens an outbound connection carrying user content.
    The fence is up when the Local route is on OR an open take is locked
    (T7), and every open take records the attempt either way.
    """
    host = (urlparse(str(target)).hostname or str(target) or "").lower()
    local = _is_this_machine(host)
    fenced = _LOCAL_ONLY.is_set() or take_locked()
    refused = fenced and not local
    if not local:
        with _TAKES_LOCK:
            for take in _TAKES:
                take.attempts.append({"host": host, "what": what, "refused": refused})
    if refused:
        raise LocalOnlyBlocked(
            f"{what} was blocked: this take is local only, and {host or 'that host'} is not this machine."
            if take_locked() and not _LOCAL_ONLY.is_set() else
            f"{what} was blocked: the Local route is on, and {host or 'that host'} is not this machine."
        )
