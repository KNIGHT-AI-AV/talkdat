"""Opt-in product telemetry, dark until armed, private by construction.

The strategy is build-and-measure (STRATEGIC_REPORT Section 6: zero analytics is
the top blocker), and this is the measuring instrument. It ships DARK: default
off, endpoint empty, and -- deliberately -- no call sites wired yet. Arming it
is a config change plus a consent surface, both of which come with the
relaunch; landing the layer now means that day is a flip, not a build.

ARMED means BOTH `telemetry.enabled: true` AND a non-empty `telemetry.endpoint`.
One switch alone stays dark, so a stray toggle cannot start uploads and a
preconfigured endpoint cannot collect without consent.

PRIVACY IS STRUCTURAL, NOT A PROMISE. A local-first dictation product that
leaks a transcript through its own analytics has destroyed its reason to
exist, so the layer is built to make that impossible rather than forbidden:

- Event names come from ALLOWED_EVENTS, a closed table. Unknown names drop.
- Property keys come from a per-event allowlist. Unknown keys drop.
- Values are short scalars (MAX_VALUE_CHARS). An oversized value is treated as
  smuggling and the property is dropped, not truncated -- truncation would
  still carry the head of a sentence.
- The payload has exactly two top-level fields: a random install id and the
  events. There is no field for hostname, username, paths, or free text.
- The install id is uuid4, generated once and stored beside the config. It is
  not derived from hardware, so deleting `telemetry_id` makes this install a
  stranger to the backend. That file lives under app_dir(), which is already
  chmod 0700.

The transport is injectable. The default speaks a minimal JSON POST with the
api key in a header, which matches PostHog's batch shape closely enough that
the server-side choice stays a config value; a different vendor later is a new
transport function, not a rewrite. Vendor is decided at arming time, not here.

Nothing in this module may ever raise into the dictation path: record() and
flush() swallow everything. Losing an analytics event is nothing; interrupting
a dictation to report one would be absurd.
"""

from __future__ import annotations

import json
import time
import urllib.request
import uuid
from typing import Any, Callable

from .config import app_dir

# Every event this product may ever report, and the only keys each may carry.
# Growing this table is a reviewed change; record() cannot be talked into
# anything that is not already here.
ALLOWED_EVENTS: dict[str, frozenset[str]] = {
    "app_started": frozenset({"app_version", "days_since_install"}),
    "onboarding_completed": frozenset({"app_version"}),
    "first_dictation": frozenset({"app_version", "route"}),
    "dictation_completed": frozenset({"app_version", "route"}),
    "settings_opened": frozenset({"app_version"}),
}

# A legitimate value here is a version string, a route name, or a small count.
# Anything longer is not analytics.
MAX_VALUE_CHARS = 64

# The queue is a small local spool, not a database. Oldest events are the
# least interesting, so overflow drops from the front.
MAX_QUEUE_EVENTS = 500

QUEUE_FILENAME = "telemetry_queue.jsonl"
ID_FILENAME = "telemetry_id"

Transport = Callable[[str, str, dict], bool]


def _settings(config: dict[str, Any] | None) -> dict[str, Any]:
    section = (config or {}).get("telemetry") if isinstance(config, dict) else None
    return section if isinstance(section, dict) else {}


def armed(config: dict[str, Any] | None) -> bool:
    """Both switches, or dark. See the module docstring for why."""
    settings = _settings(config)
    return bool(settings.get("enabled")) and bool(str(settings.get("endpoint") or "").strip())


def install_id() -> str:
    """The random per-install identity; generated on first read."""
    path = app_dir() / ID_FILENAME
    try:
        existing = path.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    except OSError:
        pass
    fresh = uuid.uuid4().hex
    try:
        path.write_text(fresh, encoding="utf-8")
    except OSError:
        pass
    return fresh


def _clean_props(event: str, props: dict[str, Any] | None) -> dict[str, Any]:
    allowed = ALLOWED_EVENTS[event]
    clean: dict[str, Any] = {}
    for key, value in (props or {}).items():
        if key not in allowed:
            continue
        if isinstance(value, bool) or isinstance(value, (int, float)):
            clean[key] = value
            continue
        if isinstance(value, str) and len(value) <= MAX_VALUE_CHARS:
            clean[key] = value
    return clean


def record(config: dict[str, Any] | None, event: str, props: dict[str, Any] | None = None) -> None:
    """Queue one event locally. A no-op unless armed; never raises."""
    try:
        if not armed(config) or event not in ALLOWED_EVENTS:
            return
        entry = {"event": event, "props": _clean_props(event, props), "ts": int(time.time())}
        queue = app_dir() / QUEUE_FILENAME
        lines: list[str] = []
        try:
            lines = queue.read_text(encoding="utf-8").strip().splitlines()
        except OSError:
            pass
        lines.append(json.dumps(entry, ensure_ascii=True))
        if len(lines) > MAX_QUEUE_EVENTS:
            lines = lines[-MAX_QUEUE_EVENTS:]
        queue.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except Exception:
        # Telemetry must never reach the user as a failure.
        pass


def _default_transport(url: str, api_key: str, payload: dict) -> bool:
    body = json.dumps(payload, ensure_ascii=True).encode()
    request = urllib.request.Request(url, data=body, method="POST")
    request.add_header("Content-Type", "application/json")
    if api_key:
        request.add_header("Authorization", f"Bearer {api_key}")
    with urllib.request.urlopen(request, timeout=10) as response:
        return 200 <= int(getattr(response, "status", 0) or 0) < 300


def flush(config: dict[str, Any] | None, transport: Transport | None = None) -> None:
    """Deliver the queue in one batch. A no-op unless armed; never raises.

    On failure the queue is kept for the next flush -- at-most-once delivery
    would silently bias every metric toward installs with good networks.
    """
    try:
        if not armed(config):
            return
        queue = app_dir() / QUEUE_FILENAME
        try:
            lines = queue.read_text(encoding="utf-8").strip().splitlines()
        except OSError:
            return
        events = []
        for line in lines:
            try:
                events.append(json.loads(line))
            except ValueError:
                continue
        if not events:
            return
        settings = _settings(config)
        payload = {"install_id": install_id(), "events": events}
        send = transport if transport is not None else _default_transport
        if send(str(settings.get("endpoint")), str(settings.get("api_key") or ""), payload):
            try:
                queue.unlink()
            except OSError:
                pass
    except Exception:
        pass
