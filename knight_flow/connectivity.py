"""Is there a network right now, cheaply enough to ask before every dictation.

This exists so a cloud provider is not attempted when there is obviously
nowhere to send the audio. Without it, dictating on a plane means holding a key,
speaking, and then waiting out a DNS timeout and an HTTP timeout before being
told it failed -- several seconds of a person watching nothing happen, for an
answer that was knowable before the microphone opened.

**Why not just try and see.** Because the cost of being wrong is asymmetric. A
wrong "offline" answer costs one dictation transcribed on-device, which is a
tenth of a second slower and still correct. A wrong "online" answer costs the
full timeout, and it lands on the person mid-sentence.

**Why the Windows API rather than a probe request.** `InternetGetConnectedState`
reads the connectivity state the OS already tracks; it performs no network I/O
and returns in microseconds. A probe request to a known host would be more
accurate and would cost a round trip on the exact path we are trying not to
block. Accuracy is not the goal here -- this only needs to catch the obvious
case, because every subtler failure is caught by the fallback that runs after a
provider actually errors.

Deliberately NOT treated as authoritative:

  * It reports "connected" for a LAN with no internet, and for a captive portal.
  * It cannot know the provider is down, the key is wrong, or the quota is
    spent.

All of those are real and none of them are detectable here. They are handled the
only way they can be: by transcribing locally after the cloud attempt fails,
using audio that was already captured. This module removes the wait in the one
case that is knowable in advance; it is not the safety net.
"""
from __future__ import annotations

import logging
import sys
import threading
import time

log = logging.getLogger(__name__)

# Long enough that a burst of dictations asks once, short enough that unplugging
# the Wi-Fi is noticed within a sentence or two. The call is nearly free, so
# this is about avoiding log noise rather than avoiding cost.
_CACHE_SECONDS = 5.0

_lock = threading.Lock()
_cached: tuple[float, bool] | None = None


def _query_windows() -> bool | None:
    """Ask Windows. None means the question could not be asked."""
    if not sys.platform.startswith("win"):
        return None
    try:
        import ctypes

        flags = ctypes.c_ulong(0)
        connected = ctypes.windll.wininet.InternetGetConnectedState(ctypes.byref(flags), 0)
        return bool(connected)
    except Exception:
        # Any failure here means we do not know, and "we do not know" must
        # never read as "offline" -- that would route every dictation to a
        # local model on a machine where the API is simply unavailable.
        return None


def network_is_available(*, force: bool = False) -> bool:
    """Whether a cloud request is worth attempting.

    Returns True when unknown. An unanswerable question must not disable the
    cloud path: the failure-driven fallback already covers a wrong yes, while a
    wrong no would silently downgrade every dictation on a healthy machine.
    """
    global _cached
    now = time.monotonic()
    if not force:
        with _lock:
            if _cached is not None and now - _cached[0] < _CACHE_SECONDS:
                return _cached[1]

    answer = _query_windows()
    available = True if answer is None else answer
    with _lock:
        previous = _cached[1] if _cached is not None else None
        _cached = (now, available)
    if previous is not None and previous != available:
        log.info("network state changed: available=%s", available)
    return available


def reset_cache() -> None:
    """Forget the cached answer. For tests, and after a known network change."""
    global _cached
    with _lock:
        _cached = None
