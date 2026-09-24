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


def assert_cloud_allowed(target: str, what: str) -> None:
    """Raise unless the fence is down or ``target`` is this machine.

    ``target`` may be a full URL or a bare host. Call this at the entry of
    every helper that opens an outbound connection carrying user content.
    """
    if not _LOCAL_ONLY.is_set():
        return
    host = (urlparse(str(target)).hostname or str(target) or "").lower()
    if host in _LOCAL_HOSTS or host.endswith(".localhost"):
        return
    raise LocalOnlyBlocked(
        f"{what} was blocked: the Local route is on, and {host or 'that host'} is not this machine."
    )
