"""X-96: does a new install reach a first successful dictation, and how fast?

The one funnel number nothing measured. Downloads exist and accounts exist,
but between them -- did the app ever actually work for this person? -- was
dark, and that gap is where dictation products die: a person who installs
and never completes one dictation uninstalls quietly and appears in no
metric anywhere.

Privacy shape, deliberately narrower than everything else in the product:
  * a random install id, generated here, tied to nothing -- not the machine,
    not an email, not a licence;
  * two timestamps and their difference, the app version, and "windows";
  * never any text, ever (X-37), and never anything that identifies a person.

Sent once. If the network is down it retries on later launches until the
server has confirmed receipt, then never again.

2026-09-23, open source: whether these are sent at all is decided by
official_build.activation_api_base(config), which the app passes in as
api_base. It is "" in a build from source, with TALKDAT_NO_PHONE_HOME=1, and
when the person turned off Settings > Privacy > "Share anonymous usage counts"
(privacy.share_usage_counts, on by default in official builds). Local-only
privacy does not decide them: it governs audio and text, which no report here
carries. Every sender here does nothing on "".

The four reports, and the words the setting uses for them: install ("first
open"), first dictation, heartbeat ("still in use") and day 7.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
import urllib.request
import uuid
from typing import Any

log = logging.getLogger("knight_flow.activation_metrics")


def _metrics(config: dict[str, Any]) -> dict[str, Any]:
    return config.setdefault("metrics", {})


def stamp_first_run(config: dict[str, Any], save) -> None:
    """Called at every startup; writes only the first time."""
    metrics = _metrics(config)
    changed = False
    if not metrics.get("install_id"):
        metrics["install_id"] = uuid.uuid4().hex
        changed = True
    if not metrics.get("first_run_at"):
        metrics["first_run_at"] = int(time.time())
        changed = True
    if changed:
        save(config)


def is_internal(config: dict[str, Any]) -> bool:
    """X-357: is this one of OUR machines rather than a customer's?

    Every install beacon is anonymous by design, which is right, and which
    also means the counters cannot tell a real adopter from the founder's
    own PC, the build Mac, or a release smoke test that installs and
    uninstalls the product on every publish. On 2026-08-23 the live numbers
    read 64 installs against 10 active machines, and a large share of both
    was us measuring ourselves. A metric that flatters you is worse than no
    metric: it is a decision made on a lie.

    A single boolean, carrying no identity, decided three ways:
      * TALKDAT_INTERNAL in the environment, for CI and release scripts;
      * metrics.internal in the config, for a machine marked once by hand;
      * running unfrozen, which means a source checkout and never a customer.

    It is reported rather than used to suppress the beacon, so internal
    machines stay visible for debugging and are simply excluded from the
    counts that describe adoption.
    """
    if str(os.environ.get("TALKDAT_INTERNAL", "")).strip().lower() in {"1", "true", "yes"}:
        return True
    if bool(_metrics(config).get("internal")):
        return True
    return not getattr(sys, "frozen", False)


def report_install(config: dict[str, Any], save, api_base: str) -> None:
    """X-132: the count-only install ping, sent once per install id.

    Same privacy budget as the activation beacon -- the random id, a
    version, a platform, nothing else -- so "how many machines installed
    this" stops being guessed from downloads. Retries on later launches
    until acked, then never again."""
    metrics = _metrics(config)
    if not api_base or metrics.get("install_acked"):
        return
    payload = {
        "installId": str(metrics.get("install_id") or ""),
        "stage": "install",
        "firstRunAt": int(metrics.get("first_run_at") or 0),
        "version": _app_version(),
        "platform": "windows",
        "internal": is_internal(config),
    }
    if not payload["installId"]:
        return

    def run() -> None:
        try:
            request = urllib.request.Request(
                api_base.rstrip("/") + "/v1/activation",
                data=json.dumps(payload).encode("utf-8"),
                headers={"content-type": "application/json", "user-agent": "TalkDat-Windows"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=8) as response:
                response.read()
            metrics["install_acked"] = True
            save(config)
        except Exception as error:
            log.debug("install ping not delivered yet: %s", error)

    threading.Thread(target=run, name="TalkDatInstallPing", daemon=True).start()


HEARTBEAT_INTERVAL_SECONDS = 24 * 60 * 60


def report_heartbeat(config: dict[str, Any], save, api_base: str) -> None:
    """X-167: "how many are ACTIVE", which installs alone cannot answer.

    report_install fires once and never again, so it counts machines that ever
    installed, not machines still in use. Without a recurring signal there is no
    honest way to say how many people are using Talk DAT! this week, and no way
    to tell which versions are still in the wild when a forced update goes out.

    Same privacy budget as everything else in this module, deliberately: the
    random install id, the version, the platform. No text (X-37), no account, no
    machine identifier, nothing that names a person. It answers "a copy of
    version X was running today" and nothing more.

    At most once a day, on startup, in a daemon thread. A failure is silent and
    simply retried tomorrow -- a metric must never cost a dictation, and must
    never be the reason the app feels slow to start.
    """
    if not api_base:
        return
    metrics = _metrics(config)
    now = int(time.time())
    last = int(metrics.get("last_heartbeat_at") or 0)
    if last and now - last < HEARTBEAT_INTERVAL_SECONDS:
        return
    install_id = str(metrics.get("install_id") or "")
    if not install_id:
        return
    payload = {
        "installId": install_id,
        "stage": "heartbeat",
        "version": _app_version(),
        "platform": _platform_name(),
        "internal": is_internal(config),
    }

    def run() -> None:
        try:
            request = urllib.request.Request(
                api_base.rstrip("/") + "/v1/activation",
                data=json.dumps(payload).encode("utf-8"),
                headers={"content-type": "application/json", "user-agent": "TalkDat-Heartbeat"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=8) as response:
                response.read()
            # Stamped only on success, so a week offline does not look like a
            # week of activity, and the next launch tries again.
            metrics["last_heartbeat_at"] = int(time.time())
            save(config)
        except Exception as error:
            log.debug("heartbeat not delivered: %s", error)

    threading.Thread(target=run, name="TalkDatHeartbeat", daemon=True).start()


def _platform_name() -> str:
    """"windows" or "mac". The Mac build shares this module."""
    import sys

    return "mac" if sys.platform == "darwin" else "windows"


def record_first_dictation(config: dict[str, Any], save, api_base: str) -> None:
    """Called after every DELIVERED dictation. Stamps and reports the first;
    on a later one retries an unconfirmed first report and, a week in,
    sends day 7 (report_day7)."""
    metrics = _metrics(config)
    if metrics.get("first_dictation_at"):
        _retry_unacked(config, save, api_base)
        report_day7(config, save, api_base)
        return
    now = int(time.time())
    metrics["first_dictation_at"] = now
    first_run = int(metrics.get("first_run_at") or now)
    metrics["seconds_to_first_dictation"] = max(0, now - first_run)
    save(config)
    _send(config, save, api_base)


DAY7_SECONDS = 7 * 24 * 60 * 60
DAY7_RETRY_SECONDS = 24 * 60 * 60


def report_day7(config: dict[str, Any], save, api_base: str) -> None:
    """Day 7: "a copy was still being used a week after it was first opened".

    The server (commerce recordDay7Active) counts it only for an install id
    that already has a first open and a first delivered dictation, and only
    when this arrives seven full days after the first open it saw. So it is
    sent from the delivered-dictation path, never from a launch alone, and
    only once both earlier reports are confirmed.

    Same privacy budget as the heartbeat: the random install id, a stage word,
    the version, the platform and the internal flag. No text (X-37).

    Sent until the server confirms it, then never again. A refusal (the
    server's first open is later than ours, say, because the counts were off
    at install) is retried at most once a day, so a dictation never pays for
    a request that is bound to fail.
    """
    if not api_base:
        return
    metrics = _metrics(config)
    if metrics.get("day7_acked"):
        return
    install_id = str(metrics.get("install_id") or "")
    first_run = int(metrics.get("first_run_at") or 0)
    if not install_id or not first_run or not metrics.get("first_dictation_at"):
        return
    if not (metrics.get("install_acked") and metrics.get("activation_acked")):
        return
    now = int(time.time())
    if now - first_run < DAY7_SECONDS:
        return
    last_try = int(metrics.get("last_day7_attempt_at") or 0)
    if last_try and now - last_try < DAY7_RETRY_SECONDS:
        return
    # In memory only: one attempt a day per session is enough, and a failed
    # attempt must not cost a config write.
    metrics["last_day7_attempt_at"] = now
    payload = {
        "installId": install_id,
        "stage": "day7",
        "version": _app_version(),
        "platform": _platform_name(),
        "internal": is_internal(config),
    }

    def run() -> None:
        try:
            request = urllib.request.Request(
                api_base.rstrip("/") + "/v1/activation",
                data=json.dumps(payload).encode("utf-8"),
                headers={"content-type": "application/json", "user-agent": "TalkDat-Day7"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=8) as response:
                response.read()
            metrics["day7_acked"] = True
            save(config)
        except Exception as error:
            log.debug("day-7 report not delivered yet: %s", error)

    threading.Thread(target=run, name="TalkDatDay7", daemon=True).start()


def _retry_unacked(config: dict[str, Any], save, api_base: str) -> None:
    metrics = _metrics(config)
    if metrics.get("first_dictation_at") and not metrics.get("activation_acked"):
        _send(config, save, api_base)


def _send(config: dict[str, Any], save, api_base: str) -> None:
    if not api_base:
        return
    metrics = _metrics(config)
    payload = {
        "installId": str(metrics.get("install_id") or ""),
        "secondsToFirstDictation": int(metrics.get("seconds_to_first_dictation") or 0),
        "firstRunAt": int(metrics.get("first_run_at") or 0),
        "version": _app_version(),
        "platform": "windows",
    }
    if not payload["installId"]:
        return

    def run() -> None:
        try:
            request = urllib.request.Request(
                api_base.rstrip("/") + "/v1/activation",
                data=json.dumps(payload).encode("utf-8"),
                headers={"content-type": "application/json", "user-agent": "TalkDat-Windows"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=8) as response:
                response.read()
            metrics["activation_acked"] = True
            save(config)
        except Exception as error:
            # Not an error state for the user: the app already worked. The
            # unacked flag makes a later launch try again.
            log.debug("activation beacon not delivered yet: %s", error)

    threading.Thread(target=run, name="TalkDatActivation", daemon=True).start()


def _app_version() -> str:
    try:
        from .version import APP_VERSION

        return str(APP_VERSION)
    except Exception:
        return "unknown"
