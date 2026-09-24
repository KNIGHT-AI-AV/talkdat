"""Never lose a dictation to the network.

Talk DAT! is sold on the promise that it runs on your own machine. That promise
was only true if you had chosen a local model in advance. Anyone dictating
through a cloud provider -- which is the faster default, and what a trial hands
you -- got nothing at all the moment the Wi-Fi dropped, the provider had an
outage, the key expired, or the quota ran out. The audio was saved and the
person was told to check the provider and retry from History.

That is the wrong answer to every one of those failures. The machine is holding
a speech model that needs no network, and the audio has already been captured.
There is nothing to ask the person about.

Two mechanisms, because they catch different things:

**Before the microphone opens** -- if there is plainly no network, use the local
model for this dictation and never attempt the cloud. This is not about
correctness, it is about the wait. Attempting a cloud provider with no route
costs a DNS timeout plus an HTTP timeout, several seconds, all of it after the
person has finished speaking and is watching an empty caret.

**After a cloud attempt fails** -- transcribe the audio that was already
captured, locally, and paste it. This is the one that matters, because most
cloud failures are invisible in advance: a captive portal answers DNS, an outage
looks like a healthy connection, a revoked key looks like a working one.

The fallback deliberately does NOT change what the person selected. It rescues a
single dictation and says so. Silently rewriting the configured provider would
mean somebody who paid for a cloud tier quietly stops using it after one flaky
minute on hotel Wi-Fi, and never finds out why their transcripts changed.
"""
from __future__ import annotations

from . import mac_support

import copy
import logging
from typing import Any

from . import platform_copy
from .connectivity import network_is_available
from .local_stt import (
    DEFAULT_LOCAL_MODEL_ID,
    LOCAL_MODELS,
    LocalModel,
    available_local_models,
    is_downloaded,
    local_model_for_id,
)
log = logging.getLogger(__name__)

# Best first. Used only to break ties when the configured model is absent and
# more than one other model happens to be on disk; ordering by accuracy rather
# than by whatever `rglob` returned means the rescue is not arbitrary.
# X-474: Canary is deliberately absent. The rescue runs at the worst possible
# moment -- the configured model is gone and the words are already waiting --
# so reaching for something that cannot run turns a recoverable moment into a
# lost dictation. A rescue that fails is worse than no rescue.
_PREFERENCE: tuple[str, ...] = (
    DEFAULT_LOCAL_MODEL_ID,
    "parakeet-tdt-0.6b-v2",
    "whisper-large-v3-turbo",
    "distil-large-v3.5",
    "whisper-small",
    "whisper-base",
)


def fallback_model(config: dict[str, Any] | None = None) -> LocalModel | None:
    """The local model to rescue a dictation with, or None if there is none.

    Order of preference:

    1. The local model the person has configured. Even when they are dictating
       through the cloud today, that choice is the best available statement of
       which model they want on this machine.
    2. The recommended default.
    3. Anything else already downloaded, best first.

    Only models that are actually on disk qualify. Downloading several hundred
    megabytes in the middle of a failed dictation is not a rescue.
    """
    config = config or {}
    seen: set[str] = set()
    candidates: list[str] = []

    stt = config.get("stt", {}) if isinstance(config.get("stt"), dict) else {}
    providers = stt.get("providers", {}) if isinstance(stt.get("providers"), dict) else {}
    local_settings = providers.get("local", {}) if isinstance(providers.get("local"), dict) else {}
    configured = str(local_settings.get("model") or "").strip()
    if configured:
        candidates.append(configured)

    candidates.extend(_PREFERENCE)
    candidates.extend(model.id for model in available_local_models(config))

    for model_id in candidates:
        if model_id in seen:
            continue
        seen.add(model_id)
        try:
            model = local_model_for_id(model_id, config)
        except Exception:
            continue
        if is_downloaded(model):
            return model
    return None


def is_cloud_provider(provider_id: str) -> bool:
    return str(provider_id).strip().lower() != "local"


def enabled(config: dict[str, Any] | None = None) -> bool:
    """Whether local rescue is switched on. Default yes.

    Defaulted on because the alternative is losing what somebody just said. It
    is settable because a person testing a cloud provider wants its failures to
    be visible rather than papered over.
    """
    config = config or {}
    stt = config.get("stt", {}) if isinstance(config.get("stt"), dict) else {}
    return bool(stt.get("local_fallback", True))


def preflight_model(config: dict[str, Any], provider_id: str) -> LocalModel | None:
    """The local model to use *instead of* the cloud, before recording starts.

    Returns None unless every one of these holds: rescue is enabled, the
    configured provider is a cloud one, the network is plainly unavailable, and
    a local model is on disk. Anything less certain is left to the cloud
    attempt, because a false offline reading would quietly downgrade a machine
    that is working perfectly well.
    """
    if not enabled(config) or not is_cloud_provider(provider_id):
        return None
    if network_is_available():
        return None
    model = fallback_model(config)
    if model is None:
        log.warning(
            "no network and no local model on disk; attempting %s anyway", provider_id
        )
        return None
    log.info("no network: using local model %s instead of %s", model.id, provider_id)
    return model


def rescue_model(config: dict[str, Any], provider_id: str) -> LocalModel | None:
    """The local model to retry a *failed* cloud dictation with.

    Unlike the preflight this does not consult the network at all. The cloud
    attempt already failed, which is stronger evidence than any connectivity
    API can offer, and the reasons that are invisible to that API -- outage,
    revoked key, spent quota, captive portal -- are exactly the ones that land
    here.
    """
    if not enabled(config) or not is_cloud_provider(provider_id):
        return None
    return fallback_model(config)


def config_using(config: dict[str, Any], model: LocalModel) -> dict[str, Any]:
    """A copy of the config that dictates with `model`, for one session.

    A copy rather than a mutation, so the person's actual choice survives. The
    copy is deep because the provider settings are nested dictionaries and a
    shallow copy would write the override straight back into the live config.
    """
    switched = copy.deepcopy(config)
    stt = switched.setdefault("stt", {})
    if not isinstance(stt, dict):
        stt = {}
        switched["stt"] = stt
    stt["provider"] = "local"
    providers = stt.setdefault("providers", {})
    if not isinstance(providers, dict):
        providers = {}
        stt["providers"] = providers
    local = providers.setdefault("local", {})
    if not isinstance(local, dict):
        local = {}
        providers["local"] = local
    local["model"] = model.id
    return switched


def describe(model: LocalModel) -> str:
    """What to tell the person, once. Short enough for the overlay's detail line."""
    return f"No connection. Transcribed on {platform_copy.THIS_COMPUTER} with {model.label.split(' (')[0]}."


__all__ = [
    "config_using",
    "describe",
    "enabled",
    "fallback_model",
    "is_cloud_provider",
    "preflight_model",
    "rescue_model",
    "LOCAL_MODELS",
]
