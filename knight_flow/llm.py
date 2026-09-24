"""BYOK LLM rewrite backend for transforms and dictation formatting.

Providers share one config shape under transforms.llm:
{"provider": "none|ollama|openai|anthropic|gemini|groq|custom",
 "model": "...", "api_key": "", "api_base": "", "timeout": 8}

API keys may also come from the matching environment variable. All requests
use stdlib urllib so no new dependencies are required.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

from . import platform_copy
from .translation import OLLAMA_DEFAULT_BASE
from . import mac_support
from .config import LOCAL_FORMATTER_MODEL
from .licensing import DEFAULT_COMMERCE_API_URL
from .local_finish import (
    LOCAL_GPU_MODEL,
    LOCAL_FINISH_SCHEMA,
    LOCAL_FINISH_SYSTEM,
    WARMUP_DICTATIONS,
    MachineSpeed,
    build_local_request,
    choose_local_model,
    context_window,
    estimate_tokens,
    machine_is_too_slow,
    parse_finish_envelope,
    predicted_finish_ms,
    relevant_vocabulary,
    reply_budget,
    vocabulary_terms,
)


log = logging.getLogger(__name__)

PROVIDER_DEFAULTS: dict[str, dict[str, str]] = {
    "openai": {"api_base": "https://api.openai.com", "model": "gpt-5.2", "env_key": "OPENAI_API_KEY"},
    # Haiku 4.5 stays here on purpose: it is still Anthropic's only fast
    # tier, and Sonnet 5 is a mid-tier model that cannot answer inside the
    # formatter's budget. This route only runs for someone who brought
    # their own Anthropic key, so the choice is "best Anthropic option",
    # not "best option" -- that one is the OpenRouter default below.
    "anthropic": {"api_base": "https://api.anthropic.com", "model": "claude-haiku-4-5", "env_key": "ANTHROPIC_API_KEY"},
    "gemini": {
        "api_base": "https://generativelanguage.googleapis.com",
        "model": "gemini-3.5-flash-lite",
        "env_key": "GEMINI_API_KEY",
    },
    "groq": {"api_base": "https://api.groq.com/openai", "model": "llama-3.3-70b-versatile", "env_key": "GROQ_API_KEY"},
    # One key for both halves of the pipeline: the same OpenRouter key that
    # serves transcription also serves the cleanup pass.
    #
    # This was anthropic/claude-haiku-4.5 for three days and that was a bad
    # pick made from memory rather than measurement -- the exact trap the
    # openrouter-keys-and-models skill exists to prevent. Artificial Analysis
    # measures the two head to head, and Haiku 4.5 loses on every axis that
    # matters here:
    #
    #                        intelligence   output tok/s   TTFT     $/task
    #   claude-haiku-4.5          30             96       10.06ms   $0.22
    #   gemini-3.5-flash-lite     37            379        9.33ms   $0.10
    #
    # Output speed is the one that decides whether this feature works at all.
    # The app gives the model a ~1.2s budget (max_ai_format_ms) before the
    # rules path answers instead, and at 96 tok/s a 100-token formatted
    # paragraph needs ~1.04s of generation alone -- the entire budget, before
    # the network. At 379 tok/s the same output takes ~0.26s. Haiku was
    # timing out into the fallback on anything longer than a sentence, which
    # is why "the AI formatter" kept looking like it did nothing.
    #
    # Smarter, four times faster, half the price. There was no trade.
    "openrouter": {
        "api_base": "https://openrouter.ai/api",
        "model": "google/gemini-3.5-flash-lite",
        "env_key": "OPENROUTER_API_KEY",
    },
    "ollama": {"api_base": "http://localhost:11434", "model": LOCAL_FORMATTER_MODEL, "env_key": ""},
    "custom": {"api_base": "", "model": "", "env_key": "CUSTOM_LLM_API_KEY"},
}

REWRITE_SYSTEM_PROMPT = (
    "You rewrite dictated text. Follow the instruction exactly. "
    "Return only the rewritten text with no preamble, labels, or quotes."
)

_OLLAMA_READY_CACHE: dict[tuple[str, str], tuple[float, bool]] = {}
_OLLAMA_PREPARE_LOCK = threading.Lock()
_OLLAMA_PREPARE_IN_FLIGHT: set[tuple[str, str]] = set()
_OLLAMA_PREPARED: set[tuple[str, str]] = set()

# X-412: what this PC measured itself doing, per engine and model. Written by
# the warm-up and by every finish; read before a finish is attempted, so a
# machine that cannot answer inside the budget says so instead of spending the
# budget finding out again on every single dictation.
_LOCAL_SPEED: dict[tuple[str, str], MachineSpeed] = {}
# The last refusal, so Settings can name the reason rather than showing a
# working formatter that never runs.
_LOCAL_REFUSED: dict[tuple[str, str], str] = {}


def _ollama_prepare_key(api_base: str, model: str) -> tuple[str, str]:
    return api_base.rstrip("/").lower(), model.strip().lower()


def _ollama_prepare_pending(api_base: str, model: str) -> bool:
    key = _ollama_prepare_key(api_base, model)
    with _OLLAMA_PREPARE_LOCK:
        return key in _OLLAMA_PREPARE_IN_FLIGHT and key not in _OLLAMA_PREPARED


def llm_settings(config: dict[str, Any]) -> dict[str, Any]:
    settings = config.get("transforms", {}).get("llm", {})
    return settings if isinstance(settings, dict) else {}


def resolved_llm_provider(config: dict[str, Any]) -> str:
    """The provider that will actually serve this request.

    "auto" is the shipped default. It follows the speech route: the local
    engine, or the person's own provider and key. There is no managed
    formatter and nothing here depends on an account or a plan (2026-09-22).

    History, kept because the guards below exist for it. X-114 once sent an
    activated PC's text to the retired managed formatter.

    X-192: its justification -- "the same place its speech already goes" -- was
    an ASSERTION, not a check. "auto" asked only whether the PC was activated, so
    someone who tapped Local, or who brought their own Deepgram key, kept their
    audio off our servers and then POSTed the entire transcript to the
    retired managed rewrite endpoint, which forwarded it to Google or
    OpenRouter. The pill said Local. The privacy notice said nothing leaves the machine. Both were false,
    and nothing in the product could have told them otherwise.

    So the premise is now enforced rather than assumed: the formatter follows
    the speech route.

    X-481: and there is no managed cloud left for it to follow anything to.
    X-480 cut the speech route to two, local or the person's own key, so this
    resolves to the local engine or to the SAME provider and the SAME key the
    audio already went to. Knight is not in the path either way, which is what
    X-192 was reaching for and can now simply be true rather than enforced.
    """
    settings = llm_settings(config)
    provider = str(settings.get("provider", "none")).strip().lower()
    # X-465: on a local-only install the formatter is the local engine, and
    # an explicitly configured cloud provider does not override that. The one
    # exception is another LOCAL engine, which is still this machine.
    from .stt_registry import local_only

    if local_only(config):
        return "ollama"
    if provider != "auto":
        return provider
    from .stt_registry import resolve_route

    # Deliberately resolve_route and not route_mode: Local is not the only way
    # to keep text off our servers. A BYOK leg -- the user's own key, their own
    # provider -- is equally a promise that Knight is not in the path.
    route = resolve_route(config)
    # X-481: no `if route != "talk_dat_cloud"` any more, because that value
    # can no longer occur. X-480 cut the speech route to two, local or the
    # person's own key, and byok_provider excludes the managed service by
    # name, so resolve_route cannot return it for any config.
    #
    # The condition and its else branch are removed rather than left to rot.
    # Dead code in a privacy path is worse than dead code anywhere else:
    # somebody reading this should not have to trace two modules to learn
    # whether the managed branch can still fire, and that exact uncertainty is
    # how X-192 happened.
    # X-365: a BYOK route that CAN finish text should finish it.
    #
    # Before this, every non-managed route fell to the local engine, and
    # the local engine needs Ollama installed with a model pulled --
    # which almost nobody has. So somebody who brought their own
    # OpenRouter or OpenAI key got speech from their key and then
    # rules-only cleanup, and never learned why Chill and Executive did
    # nothing. The finishing they paid for was simply absent.
    #
    # X-192's rule is honoured rather than bent: the formatter still
    # follows the speech route. It is the SAME provider and the SAME key
    # the audio already went to, so nothing reaches a party the person
    # had not already chosen, and Knight is still not in the path.
    #
    # Local stays local. A local speech route means the text never
    # leaves either, which is also what net_fence would enforce.
    byok = byok_text_provider(config, route)
    if byok:
        return byok
    return "ollama"


# X-365: BYOK speech providers that also serve text, mapped to the formatter
# provider that speaks their API. Deepgram is deliberately ABSENT: it has no
# text model at all, so a Deepgram key cannot finish a transcript no matter
# how the routing is arranged. That is why Deepgram BYOK users see rules-only
# output, and why the app has to say so rather than degrade in silence.
TEXT_CAPABLE_SPEECH_PROVIDERS: dict[str, str] = {
    "openrouter": "openrouter",
    "openai": "openai",
    "groq": "groq",
    "google_gemini": "gemini",
}


def byok_text_provider(config: dict[str, Any], route: str) -> str:
    """The formatter provider a BYOK speech route can also finish text with.

    Empty when the route is local, when the provider has no text model, or
    when no key is stored for it -- every one of which means the local engine
    is the only honest option.
    """
    if route in {"local", ""}:
        return ""
    target = TEXT_CAPABLE_SPEECH_PROVIDERS.get(route, "")
    if not target:
        return ""
    return target if byok_text_key(config, route) else ""


def byok_text_key(config: dict[str, Any], route: str) -> str:
    """The user's own key for that speech provider, reused for text.

    The import is local because stt_sessions pulls in the audio stack, which
    this module has no other reason to load. It is NOT wrapped in a bare
    except: an earlier draft caught everything here, so when the function was
    imported from the wrong module the failure looked exactly like "no key
    configured" and BYOK formatting stayed silently off. A missing key is a
    fact about configuration; a missing function is a bug, and the two must
    not be reported identically.
    """
    from .stt_sessions import selected_stt_api_key

    return str(selected_stt_api_key(config, route) or "").strip()


def llm_configured(config: dict[str, Any]) -> bool:
    """True when a usable AI rewrite backend is configured."""
    settings = llm_settings(config)
    provider = resolved_llm_provider(config)
    if provider in {"", "none"}:
        return False
    if provider == "ollama":
        return True  # local, no key needed
    # X-491: a legacy config can still NAME the managed provider. There is
    # nothing behind that name now, so it is not a usable backend. Saying so
    # sends the person to pick a lane instead of at a service that will refuse.
    if provider == "talk_dat_cloud":
        return False
    return bool(_api_key(settings, provider))


def _api_key(settings: dict[str, Any], provider: str) -> str:
    key = str(settings.get("api_key", "")).strip()
    if key:
        return key
    env_key = PROVIDER_DEFAULTS.get(provider, {}).get("env_key", "")
    return os.environ.get(env_key, "").strip() if env_key else ""


def _post_json(url: str, body: dict[str, Any], headers: dict[str, str], timeout: float) -> dict[str, Any]:
    # X-338: the local-route fence. A localhost Ollama passes; any cloud
    # formatter refuses while Local is selected.
    from .net_fence import assert_cloud_allowed, loopback_ipv4
    assert_cloud_allowed(url, "The formatter")
    request = urllib.request.Request(
        loopback_ipv4(url),
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


# Set by the test package so no unit test reaches whatever Ollama happens to be
# running on the machine: with every non-trivial take offered to the model,
# an unmocked test would otherwise answer differently per PC. The parity
# battery and the benchmarks clear it to measure the real engine on purpose.
LOCAL_ENGINE_OFFLINE_ENV = "TALK_DAT_LOCAL_ENGINE_OFFLINE"


def _ollama_models(api_base: str, *, timeout: float = 0.35) -> set[str] | None:
    if os.environ.get(LOCAL_ENGINE_OFFLINE_ENV) == "1":
        return None
    from .net_fence import loopback_ipv4

    request = urllib.request.Request(loopback_ipv4(api_base.rstrip("/") + "/api/tags"), method="GET")
    try:
        with urllib.request.urlopen(request, timeout=max(0.05, timeout)) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError, ValueError):
        return None
    models: set[str] = set()
    for item in payload.get("models", []):
        if not isinstance(item, dict):
            continue
        for key in ("name", "model"):
            value = str(item.get(key, "")).strip().lower()
            if value:
                models.add(value)
    return models


def _ollama_ready(
    api_base: str,
    model: str,
    *,
    timeout: float = 0.35,
    cache_ttl: float = 3.0,
) -> bool:
    """Return quickly when the local formatter is unavailable or not installed."""
    key = (api_base.rstrip("/").lower(), model.strip().lower())
    now = time.monotonic()
    cached = _OLLAMA_READY_CACHE.get(key)
    if cached is not None and now - cached[0] < max(0.0, cache_ttl):
        return cached[1]
    models = _ollama_models(api_base, timeout=timeout)
    wanted = model.strip().lower()
    ready = models is not None and (
        wanted in models
        or (":" not in wanted and f"{wanted}:latest" in models)
    )
    _OLLAMA_READY_CACHE[key] = (now, ready)
    return ready


def _complete_openai(system: str, user: str, *, api_base: str, api_key: str, model: str, timeout: float) -> str:
    body: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0.2,
    }
    if "openrouter.ai" in api_base:
        # OpenRouter fans a model out across several hosts and picks one. The
        # default balances price and availability; sorting by latency asks for
        # the host that answers soonest, which is the only thing that matters
        # when someone is waiting to see their own words.
        #
        # Deliberately not ":nitro". Nitro optimises tokens per second, which
        # pays off over long generations -- these outputs are a sentence, so
        # time-to-first-token dominates and Nitro trades it away. Measured on
        # this prompt: plain 718ms, :nitro 1020ms, sort=throughput 646ms,
        # sort=latency 546ms.
        body["provider"] = {"sort": "latency"}
    payload = _post_json(
        api_base.rstrip("/") + "/v1/chat/completions",
        body,
        {"Authorization": f"Bearer {api_key}"},
        timeout,
    )
    choices = payload.get("choices", [])
    if choices and isinstance(choices[0], dict):
        return str(choices[0].get("message", {}).get("content", "")).strip()
    return ""


def _complete_anthropic(system: str, user: str, *, api_base: str, api_key: str, model: str, timeout: float) -> str:
    payload = _post_json(
        api_base.rstrip("/") + "/v1/messages",
        {
            "model": model,
            "max_tokens": 2048,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        },
        {"x-api-key": api_key, "anthropic-version": "2023-06-01"},
        timeout,
    )
    content = payload.get("content", [])
    parts = [str(item.get("text", "")) for item in content if isinstance(item, dict) and item.get("type") == "text"]
    return "\n".join(parts).strip()


def _complete_gemini(system: str, user: str, *, api_base: str, api_key: str, model: str, timeout: float) -> str:
    payload = _post_json(
        f"{api_base.rstrip('/')}/v1beta/models/{model}:generateContent?key={api_key}",
        {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
        },
        {},
        timeout,
    )
    texts: list[str] = []
    for candidate in payload.get("candidates", []):
        parts = candidate.get("content", {}).get("parts", []) if isinstance(candidate, dict) else []
        for part in parts:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                texts.append(part["text"])
    return "\n".join(texts).strip()


def _complete_ollama(system: str, user: str, *, api_base: str, model: str, timeout: float) -> str:
    payload = _post_json(
        api_base.rstrip("/") + "/api/chat",
        {
            "model": model,
            "stream": False,
            "think": False,
            "keep_alive": KEEP_ALIVE,
            "options": {
                "temperature": 0.0,
                "top_p": 0.8,
                "repeat_penalty": 1.08,
                # X-114: 2048/512 silently truncated long dictations -- the
                # model neither saw the end of a long transcript nor was
                # allowed to finish writing it back.
                # X-410: 4096 still truncated. The Executive prompt alone is
                # about 4,360 tokens with a 200-word dictation, and Ollama's
                # log read "truncating input prompt limit=2050 prompt=4360":
                # the model never saw the instructions, echoed the text or
                # wrote nonsense, and the prefix cache never matched. 8192
                # holds the prompt, the dictation and the answer.
                # X-412: 8192 is now the FLOOR rather than the value. A long
                # dictation can still pass it, and a window under what the
                # prompt needs is X-410's bug with a bigger number in it.
                "num_ctx": context_window(len(system) + len(user), num_predict=1024),
                "num_predict": 1024,
            },
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        },
        {},
        timeout,
    )
    message = payload.get("message", {})
    if isinstance(message, dict):
        return str(message.get("content", "")).strip()
    return ""


# --------------------------------------------------------------------------
# X-412: the local finishing path.
#
# Everything below serves the on-device route only. The cloud and BYOK routes
# go through llm_complete with the full rulebook and are not touched by any of
# it -- a local model needs a different prompt, a different window, a measured
# opinion about whether it can answer in time, and none of that improves a
# frontier model reached over a socket.
# --------------------------------------------------------------------------

# What the model has to beat to be worth calling at all. Below this a machine
# is honest about needing a GPU rather than spending the whole budget on a
# prefill and pasting the rules output anyway.
_LOCAL_FINISH_SLACK = 1.15


def local_finish_key(api_base: str, model: str) -> tuple[str, str]:
    return _ollama_prepare_key(api_base, model)


def _ollama_loaded_on_gpu(api_base: str, model: str, *, timeout: float = 0.35) -> bool | None:
    """Did Ollama put this model on the GPU, or is it running on the CPU.

    `/api/ps` reports `size` and `size_vram` per loaded model -- the same pair
    behind `ollama ps`'s PROCESSOR column. It answers only for a model that is
    already loaded, which is exactly when the answer is wanted: the warm-up
    loads it, then asks.

    None means "not loaded, so unknown", which is a different thing from "on
    the CPU" and must not be reported as one.
    """
    from .net_fence import loopback_ipv4

    request = urllib.request.Request(loopback_ipv4(api_base.rstrip("/") + "/api/ps"), method="GET")
    try:
        with urllib.request.urlopen(request, timeout=max(0.05, timeout)) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError, ValueError):
        return None
    wanted = model.strip().lower()
    for item in payload.get("models", []):
        if not isinstance(item, dict):
            continue
        names = {str(item.get(key, "")).strip().lower() for key in ("name", "model")}
        if wanted not in names and f"{wanted}:latest" not in names:
            continue
        total = float(item.get("size") or 0)
        on_gpu = float(item.get("size_vram") or 0)
        if total <= 0:
            return None
        # Half is the line between "the GPU is doing this" and "the GPU is
        # holding a few layers while the CPU does the work". A partial offload
        # runs at CPU speed, so it must not read as a GPU.
        return on_gpu >= total * 0.5
    return None


def _ollama_chat(
    system: str,
    user: str,
    *,
    api_base: str,
    model: str,
    timeout: float,
    num_ctx: int,
    num_predict: int,
    schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": model,
        "stream": False,
        "think": False,
        "keep_alive": KEEP_ALIVE,
        "options": {
            "temperature": 0.0,
            "top_p": 0.8,
            "repeat_penalty": 1.08,
            "num_ctx": int(num_ctx),
            "num_predict": int(num_predict),
        },
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }
    if schema is not None:
        body["format"] = schema
    return _post_json(api_base.rstrip("/") + "/api/chat", body, {}, timeout)


def _record_local_speed(
    api_base: str,
    model: str,
    payload: dict[str, Any],
    *,
    on_gpu: bool | None = None,
    prefill_tokens: int | None = None,
) -> MachineSpeed | None:
    """Turn one Ollama reply into this machine's measured rates.

    Ollama reports durations in nanoseconds, and it reports
    `prompt_eval_count` as the WHOLE prompt while `prompt_eval_duration`
    covers only the part it actually had to evaluate. Divide one by the other
    on a warm request and the prefill rate comes out two to three times too
    fast -- measured here, 258 tok/s claimed against 110 tok/s real. So the
    caller passes the number of tokens it knows were NEW, and prefill is
    measured only when it can say. Generation speed is always reported
    honestly and is taken from every reply.
    """
    key = local_finish_key(api_base, model)
    previous = _LOCAL_SPEED.get(key)
    prompt_ns = float(payload.get("prompt_eval_duration") or 0)
    eval_tokens = int(payload.get("eval_count") or 0)
    eval_ns = float(payload.get("eval_duration") or 0)

    prefill = previous.prefill_tps if previous else 0.0
    generation = previous.generation_tps if previous else 0.0
    if prefill_tokens is not None and prefill_tokens >= 32 and prompt_ns > 0:
        prefill = prefill_tokens / (prompt_ns / 1e9)
    if eval_tokens >= 8 and eval_ns > 0:
        generation = eval_tokens / (eval_ns / 1e9)
    if prefill <= 0 or generation <= 0:
        return previous
    resolved = on_gpu if on_gpu is not None else (previous.on_gpu if previous else None)
    speed = MachineSpeed(prefill_tps=prefill, generation_tps=generation, on_gpu=resolved)
    _LOCAL_SPEED[key] = speed
    return speed


def local_finish_speed(api_base: str, model: str) -> MachineSpeed | None:
    return _LOCAL_SPEED.get(local_finish_key(api_base, model))


def local_finish_target(config: dict[str, Any], *, executive: bool) -> tuple[str, str]:
    """The engine and model this install will finish with, right now."""
    settings = llm_settings(config)
    chosen = str(settings.get("provider", "none")).strip().lower()
    defaults = PROVIDER_DEFAULTS["ollama"]
    if chosen == "auto":
        api_base = defaults["api_base"]
        configured = defaults["model"]
    else:
        api_base = str(settings.get("api_base", "")).strip() or defaults["api_base"]
        configured = str(settings.get("model", "")).strip() or defaults["model"]
    # The GPU verdict belongs to the model the warm-up actually loaded, which
    # is the configured one. Reading it off some other model's key would report
    # "unknown" on every install that changed the model.
    measured = _LOCAL_SPEED.get(local_finish_key(api_base, configured))
    on_gpu = bool(measured.on_gpu) if measured is not None else False
    # A GPU machine set up with the 4B alone never has a 1.7B to measure. The
    # 4B's own warm-up is the same measurement (same prompt, same /api/ps
    # check), so a 4B that measured itself on the GPU is evidence enough.
    if not on_gpu and configured.lower() == LOCAL_FORMATTER_MODEL.lower():
        gpu_measured = _LOCAL_SPEED.get(local_finish_key(api_base, LOCAL_GPU_MODEL))
        on_gpu = bool(gpu_measured is not None and gpu_measured.on_gpu is True)
    # The inventory is only consulted when an upgrade is actually on the table.
    # Asking otherwise put a 0.35 s /api/tags timeout in front of every
    # dictation on a machine with no engine running, to answer a question whose
    # answer could not have changed the model.
    # 2026-09-22: the GPU model serves BOTH finishes, not Executive alone, so
    # a capable GPU keeps one model resident and every take gets the better one.
    # A Mac under 16 GB keeps the 1.7B even with the 4B pulled: its GPU shares
    # the memory the apps being dictated into need (mac_support.gpu_model_fits).
    upgradeable = (
        on_gpu and configured.lower() == LOCAL_FORMATTER_MODEL.lower() and mac_support.gpu_model_fits()
    )
    installed = (_ollama_models(api_base) or set()) if upgradeable else set()
    chosen = choose_local_model(
        configured, executive=executive, installed=installed, on_gpu=on_gpu
    )
    if chosen.lower() != configured.lower():
        # The bigger model must itself have landed on the GPU. A card with
        # room for 1.7B but not for 4B would spill the 4B to the CPU, where it
        # is thirty times slower, so its own warm-up has the last word.
        upgraded = _LOCAL_SPEED.get(local_finish_key(api_base, chosen))
        if upgraded is not None and upgraded.on_gpu is False:
            chosen = configured
    return api_base, chosen


def local_finish_refusal(config: dict[str, Any]) -> str:
    """Why the local finisher declined, if it did. Empty when it is fine."""
    for executive in (True, False):
        api_base, model = local_finish_target(config, executive=executive)
        reason = _LOCAL_REFUSED.get(local_finish_key(api_base, model), "")
        if reason:
            return reason
    return ""


_WARMUP_PREDICT = 32


def warm_local_finish(api_base: str, model: str, *, timeout: float = 60.0) -> MachineSpeed | None:
    """Load the model, put the fixed block in its KV cache, and time the machine.

    This runs on a background thread at launch, so it is the one place the app
    can afford to find out how fast this PC is. It sends the byte-identical
    fixed block a dictation will send -- that is the entire point, because a
    warm-up with a different prompt warms nothing that a dictation can reuse.

    Two calls, not one. The first loads the weights and compiles the graph and
    is thrown away; timing it reported an RTX 3090 at 94 tok/s of generation
    against a real 152, which was pessimistic enough to make the card refuse
    its own work. The second call reuses the cached fixed block and sends a
    different tail, which is exactly the shape of a real dictation and the
    only shape worth timing.

    Returns the measured speed, or None when the engine never answered.
    """
    speed: MachineSpeed | None = None
    on_gpu: bool | None = None
    for index, dictation in enumerate(WARMUP_DICTATIONS):
        request = build_local_request(dictation, executive=False)
        window = context_window(
            len(LOCAL_FINISH_SYSTEM) + len(request), num_predict=_WARMUP_PREDICT
        )
        try:
            payload = _ollama_chat(
                LOCAL_FINISH_SYSTEM,
                request,
                api_base=api_base,
                model=model,
                timeout=max(1.0, timeout),
                num_ctx=window,
                num_predict=_WARMUP_PREDICT,
                schema=LOCAL_FINISH_SCHEMA,
            )
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError, KeyError, ValueError):
            return speed
        if index == 0:
            # Loaded, not measured. Ask where it landed while it is resident.
            on_gpu = _ollama_loaded_on_gpu(api_base, model, timeout=1.0)
            continue
        # Only the tail was new, so only the tail may be the numerator.
        speed = _record_local_speed(
            api_base, model, payload,
            on_gpu=on_gpu,
            prefill_tokens=estimate_tokens(request),
        )
    return speed


_RESIDENCY_LOCK = threading.Lock()
_RESIDENCY_CHECKED: dict[tuple[str, str], float] = {}
_RESIDENCY_IN_FLIGHT: set[tuple[str, str]] = set()
_RESIDENCY_INTERVAL_S = 20.0
# Every request asks Ollama to keep the model loaded indefinitely.
KEEP_ALIVE = -1


def keep_local_finisher_resident(config: dict[str, Any], *, force: bool = False) -> None:
    """Make sure the finishing model is loaded before somebody needs it.

    Every request already asks Ollama for keep_alive -1, and the launch warms
    the model. That was not enough on the owner's PC: something else unloaded
    it (an Ollama restart, another model taking the VRAM), /api/ps listed
    nothing, and every take for an evening timed out on a cold load and pasted
    rules. So the app now asks where a dictation begins -- the speaker is
    still talking, which is exactly where a 1-2 s load can hide -- and after
    any timeout. It never blocks the caller: one background thread, at most
    one check per model every twenty seconds unless forced.
    """
    started = time.monotonic()

    def worker() -> None:
        try:
            if resolved_llm_provider(config) != "ollama":
                return
            cleanup = config.get("cleanup", {})
            cleanup = cleanup if isinstance(cleanup, dict) else {}
            if str(cleanup.get("format_mode", "auto")).lower() == "off" or not cleanup.get("smart_format", True):
                return
            executive = str(cleanup.get("format_intensity", "standard")).strip().lower() == "executive"
            api_base, model = local_finish_target(config, executive=executive)
            key = local_finish_key(api_base, model)
            with _RESIDENCY_LOCK:
                if key in _RESIDENCY_IN_FLIGHT:
                    return
                if not force and started - _RESIDENCY_CHECKED.get(key, -1e9) < _RESIDENCY_INTERVAL_S:
                    return
                _RESIDENCY_CHECKED[key] = started
                _RESIDENCY_IN_FLIGHT.add(key)
            try:
                if _ollama_prepare_pending(api_base, model):
                    return
                if _ollama_loaded_on_gpu(api_base, model, timeout=0.5) is not None:
                    return  # resident
                if not _ollama_ready(api_base, model, cache_ttl=0.0):
                    return  # engine down or model not pulled: prepare owns that
                log.info("local finisher %s was not resident; loading it", model)
                warm_local_finish(api_base, model)
            finally:
                with _RESIDENCY_LOCK:
                    _RESIDENCY_IN_FLIGHT.discard(key)
        except Exception:
            log.debug("local finisher residency check failed", exc_info=True)

    threading.Thread(target=worker, name="TalkDatFinisherResident", daemon=True).start()


def local_finish(
    text: str,
    config: dict[str, Any],
    *,
    executive: bool,
    tone: str = "",
    budget_seconds: float,
) -> str | None:
    """Finish a dictation on this PC with the compact prompt.

    Returns None whenever the rules formatter should answer instead, which
    covers four different situations and records the honest one:
    the engine is not there, the model is not pulled, the model is still being
    prepared, or this machine has measured itself too slow for the budget.
    """
    api_base, model = local_finish_target(config, executive=executive)
    key = local_finish_key(api_base, model)
    if _ollama_prepare_pending(api_base, model) or not _ollama_ready(api_base, model):
        return None

    request = build_local_request(
        text, executive=executive, vocabulary=relevant_vocabulary(vocabulary_terms(config), text), tone=tone
    )
    budget_ms = max(100.0, float(budget_seconds) * 1000.0)
    speed = _LOCAL_SPEED.get(key)
    # The answer is about as long as the dictation. Charging it for the whole
    # request -- header, and a vocabulary line of up to thirty terms -- made
    # the owner's 3090 predict 1.4 to 1.9 s for takes it finished in 0.6.
    predicted = predicted_finish_ms(speed, request, answer_tokens=estimate_tokens(text))
    if predicted is not None and predicted > budget_ms * _LOCAL_FINISH_SLACK:
        # Measured, not guessed, and measured on THIS machine. Spending the
        # budget again to rediscover it would delay every dictation by the
        # whole budget and still paste the rules output.
        #
        # Settings is only told when an ORDINARY dictation is out of reach.
        # One long ramble missing the budget on a working GPU is a fact about
        # that dictation, and reporting it as a hardware verdict would be
        # false on the machine it appeared on.
        if machine_is_too_slow(speed, budget_ms, slack=_LOCAL_FINISH_SLACK):
            _LOCAL_REFUSED[key] = "too_slow"
        log.info(
            "local finishing needs about %.0fms against a %.0fms budget; using the rules formatter",
            predicted,
            budget_ms,
        )
        return None

    predict = reply_budget(request)
    window = context_window(len(LOCAL_FINISH_SYSTEM) + len(request), num_predict=predict)
    try:
        payload = _ollama_chat(
            LOCAL_FINISH_SYSTEM,
            request,
            api_base=api_base,
            model=model,
            timeout=max(0.1, float(budget_seconds)),
            num_ctx=window,
            num_predict=predict,
            schema=LOCAL_FINISH_SCHEMA,
        )
    except urllib.error.HTTPError as exc:
        if exc.code not in {400, 404, 422, 500}:
            log.warning("local finishing unavailable (HTTP %s); using the rules formatter", exc.code)
            return None
        # A refused schema is a property of the engine or the weights, not of
        # this dictation, so retry once unconstrained rather than losing the
        # finish. `parse_finish_envelope` reads plain text too.
        try:
            payload = _ollama_chat(
                LOCAL_FINISH_SYSTEM,
                request,
                api_base=api_base,
                model=model,
                timeout=max(0.1, float(budget_seconds)),
                num_ctx=window,
                num_predict=predict,
            )
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError, ValueError) as retry_exc:
            log.warning("local finishing unavailable (%s); using the rules formatter",
                        type(retry_exc).__name__)
            return None
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError, ValueError) as exc:
        log.warning("local finishing unavailable (%s); using the rules formatter", type(exc).__name__)
        if isinstance(exc, (urllib.error.URLError, TimeoutError, OSError)):
            # Measured 2026-09-22 on the owner's PC: /api/ps listed nothing
            # loaded and every take timed out on a cold load. The next take
            # should find the model warm, so load it now, off this thread.
            keep_local_finisher_resident(config, force=True)
        return None

    _record_local_speed(api_base, model, payload)
    sent = int(payload.get("prompt_eval_count") or 0)
    if sent and sent < estimate_tokens(LOCAL_FINISH_SYSTEM + request) * 0.6:
        # X-410's failure, watched for rather than assumed gone: Ollama
        # truncates a prompt that does not fit and says so only in its own log.
        log.warning("the local finisher read %s prompt tokens; the window is too small", sent)
    message = payload.get("message", {})
    content = str(message.get("content", "")) if isinstance(message, dict) else ""
    answer = parse_finish_envelope(_clean_llm_output(content))
    if answer and "\\n" in answer and "\\n" not in text:
        # Measured on the 4B: a JSON string escaped twice, so the line
        # breaks it meant arrived as a literal backslash and n.
        answer = answer.replace("\\n", "\n")
    if answer:
        _LOCAL_REFUSED.pop(key, None)
    return answer or None


def finishing_status(
    config: dict[str, Any], local_status: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Can this install actually finish text right now, and if not, why.

    `local_status` lets a caller that has ALREADY run `local_formatter_status`
    hand it in. Settings does exactly that, and without this it probed the
    local engine twice every time the Formatting page opened -- the page-owned
    dependency contract is "start once", and the second probe broke it.

    X-366, from the founder using his own product: "full Local formatting
    needed for when on Local... it does not format on deepgram BYOK either".

    The capability was never missing. A Deepgram user can name a finishing
    provider and paste their own key today and get Chill and Executive
    immediately. What was missing is that NOTHING SAYS SO. The text still
    lands -- correctly, a dictation must never fail because a model did --
    so the product simply writes worse than it can, forever, and reads as
    "this is how well it writes" rather than as a setting nobody set.

    That is the same defect class as the Store submission that never
    submitted and the privacy promise nothing enforced: quality drops and
    the only trace is a log line no customer will ever read.

    Returns a verdict the UI can act on rather than a boolean:
      ok            -- finishing will run
      reason        -- a stable code for tests and telemetry
      message       -- one honest sentence for a person
      offer_key     -- True when pasting a finishing key is the actual fix
    """
    from .stt_registry import resolve_route

    settings = llm_settings(config)
    chosen = str(settings.get("provider", "none")).strip().lower()
    provider = resolved_llm_provider(config)

    def verdict(ok: bool, reason: str, message: str, offer_key: bool = False) -> dict[str, Any]:
        return {"ok": ok, "reason": reason, "message": message,
                "offer_key": offer_key, "provider": provider}

    if chosen in {"", "none"} or provider in {"", "none"}:
        return verdict(False, "turned_off",
                       "AI finishing is turned off, so dictation uses the built-in rules.")

    if provider == "talk_dat_cloud":
        # X-516: a stored config can still NAME the managed finisher, but
        # there is nothing behind the name. This used to answer "sign in",
        # which sent people to an account page to fix something no account
        # can fix. Name the two lanes that actually exist instead.
        return verdict(False, "no_managed_finisher",
                       "Talk DAT! no longer finishes text on our servers. Install the "
                       "local AI formatter, or add your own finishing key.",
                       offer_key=True)

    if provider != "ollama":
        # A named cloud or BYOK finisher. The only thing that can stop it is a
        # missing key -- except on Local, where the route fence refuses any
        # cloud finisher at the socket no matter what is configured.
        try:
            entitled_route = resolve_route(config, False)
        except Exception:
            entitled_route = ""
        if entitled_route == "local":
            return verdict(False, "local_route_blocks_cloud",
                           f"The Local route keeps everything on {platform_copy.THIS_COMPUTER}, so the cloud "
                           "finisher is not used. Install the local AI formatter for "
                           "Chill on Local; Executive needs a model.")
        return verdict(True, "", "")

    # Resolved to the local engine. Two very different reasons land here.
    local = local_status if local_status is not None else local_formatter_status(config)
    try:
        route = resolve_route(config, False)
    except Exception:
        route = ""
    speech_cannot_finish = bool(
        route and route != "local"
        and route not in TEXT_CAPABLE_SPEECH_PROVIDERS
    )
    if local.get("ready"):
        # X-412: installed, running, model pulled -- and still unable to
        # answer. A 200-word rewrite is 40 seconds on six CPU threads against
        # a 1.2 second budget, so on a machine with no usable GPU the local
        # finisher times out into the rules on every single dictation and
        # nothing says why. That reads as "this is how well it writes", which
        # is the same silent-degradation failure this function exists for.
        if local_finish_refusal(config) == "too_slow":
            return verdict(
                False, "local_too_slow",
                f"{platform_copy.THIS_COMPUTER_SENTENCE} finishes text slower than dictation can wait, so the built-in "
                "rules are used instead. Local finishing needs a GPU or a smaller model.",
                offer_key=route != "local",
            )
        return verdict(True, "", "")
    if speech_cannot_finish:
        # The Deepgram case, and thirteen others. Their key transcribes and
        # cannot finish text; a finishing key is the whole fix.
        return verdict(
            False, "speech_provider_has_no_text_model",
            f"{_provider_label(route)} transcribes but cannot finish text, so dictation "
            "is using the built-in rules. Add a finishing key -- OpenRouter, OpenAI, "
            "Groq or Gemini -- to turn on Chill and Executive. Your key, your provider.",
            offer_key=True,
        )
    # Three distinct local faults, and they need three different sentences.
    # Reporting "no model downloaded" at a machine with no Ollama at all sends
    # somebody looking for a download button that cannot help them.
    if not local.get("engine_installed"):
        return verdict(False, "local_engine_missing",
                       "The local AI formatter is not installed, so dictation uses the "
                       "built-in rules. Install Ollama, or add your own finishing key.",
                       offer_key=route != "local")
    if not local.get("engine_running"):
        return verdict(False, "local_engine_not_running",
                       "Ollama is installed but not running, so dictation uses the "
                       "built-in rules. Start Ollama to turn the AI finisher back on.")
    return verdict(False, "local_model_missing",
                   "The local AI formatter has no model downloaded yet, so dictation "
                   "uses the built-in rules.")


def _provider_label(provider_id: str) -> str:
    """The provider's own name, not our internal id. "deepgram transcribes"
    reads like a typo in a sentence a customer sees."""
    try:
        from .stt_registry import PROVIDER_BY_ID

        found = PROVIDER_BY_ID.get(provider_id)
        return str(getattr(found, "label", "") or provider_id)
    except Exception:
        return provider_id


def local_formatter_status(config: dict[str, Any]) -> dict[str, Any]:
    """Whether the local AI formatter can actually run, and if not, why.

    Translation has had this since it shipped -- ready, engine missing, engine
    not running -- and the formatter never did, which is the wrong way round.
    Translation is occasional; formatting runs on every single dictation.

    Without it, choosing the local formatter and not having Ollama installed
    produces rule-formatted text forever with nothing said. The rules are good,
    so it does not look broken. It looks like this is how well the product
    writes, which is a worse outcome than an error.

    Cheap enough to call from a settings panel: `_ollama_models` gives up after
    0.35 seconds and caches, so an absent engine costs one timeout rather than
    one per query.
    """
    settings = llm_settings(config)
    provider = resolved_llm_provider(config)
    model = str(settings.get("model", "")).strip() or LOCAL_FORMATTER_MODEL
    api_base = str(settings.get("api_base", "")).strip() or OLLAMA_DEFAULT_BASE

    if provider and provider != "ollama":
        # A cloud or BYOK backend serves this install; Ollama is not in the picture.
        return {"provider": provider, "model": model, "local": False, "ready": True,
                "engine_installed": True, "engine_running": True, "model_installed": True}

    models = _ollama_models(api_base)
    engine_running = models is not None
    installed = bool(models and {model, model.split(":")[0]} & {m.split(":")[0] for m in models} )
    return {
        "provider": "ollama",
        "model": model,
        "local": True,
        "engine_installed": bool(_local_ollama_executable()),
        "engine_running": engine_running,
        "model_installed": installed,
        "ready": engine_running and installed,
    }


def pull_local_formatter_model(
    config: dict[str, Any],
    progress: "Callable[[str, int], None] | None" = None,
    *,
    timeout: float = 1800.0,
    model: str | None = None,
) -> tuple[bool, str]:
    """Download the local formatter model through the running Ollama engine.

    The last hole in this path. Settings could already tell somebody that the
    engine was installed, running, and missing the model -- and then offered
    nothing to do about it, which is a diagnosis rather than a fix. The model is
    about 1.4 GB and the alternative was a terminal and a command nobody was
    given.

    Uses the engine's own HTTP API rather than shelling out to `ollama pull`.
    The engine has to be running for this state to be reachable at all, the API
    reports byte progress where the executable reports a redrawing progress bar,
    and it does not depend on PATH -- which on Windows frequently does not
    contain Ollama even when Ollama is installed and running.

    Returns (ok, message). Never raises: it is called from a button.

    `model` pulls a named tag instead of the configured one. Smart formatting
    setup uses it for the GPU model, which is never the configured value.
    """
    settings = llm_settings(config)
    model = str(model or "").strip() or str(settings.get("model", "")).strip() or LOCAL_FORMATTER_MODEL
    api_base = str(settings.get("api_base", "")).strip() or OLLAMA_DEFAULT_BASE
    if not _is_local_ollama_base(api_base):
        return False, "The formatter is pointed at a remote engine, so there is nothing to download here."

    body = json.dumps({"model": model, "stream": True}).encode("utf-8")
    from .net_fence import loopback_ipv4

    request = urllib.request.Request(
        loopback_ipv4(api_base.rstrip("/") + "/api/pull"),
        data=body,
        headers={"content-type": "application/json"},
        method="POST",
    )
    seen_total = 0
    from .net_fence import assert_cloud_allowed
    assert_cloud_allowed(getattr(request, "full_url", ""), "The formatter stream")
    try:
        with urllib.request.urlopen(request, timeout=max(5.0, timeout)) as response:
            for raw in response:
                line = raw.decode("utf-8", "replace").strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("error"):
                    return False, str(event["error"])[:200]
                status = str(event.get("status", "")).strip()
                total = int(event.get("total") or 0)
                completed = int(event.get("completed") or 0)
                seen_total = total or seen_total
                percent = int(completed * 100 / total) if total else 0
                if progress:
                    progress(status or "downloading", percent)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        return False, f"The download did not finish: {exc}"

    # Trust the engine's own inventory rather than the stream ending, because a
    # stream can end for reasons other than success.
    _ollama_models.cache_clear() if hasattr(_ollama_models, "cache_clear") else None
    models = _ollama_models(api_base, timeout=2.0) or set()
    installed = bool({model, model.split(":")[0]} & {name.split(":")[0] for name in models})
    if installed:
        return True, f"{model} is ready. Dictation will use the AI formatter from now on."
    return False, f"{model} still is not listed by the engine after downloading."


def _ollama_executable_candidates() -> list[str]:
    """Where an installed Ollama lives when it is not on PATH.

    A Mac app launched from Finder or the Dock inherits launchd's short PATH
    (/usr/bin:/bin:/usr/sbin:/sbin), so neither the Ollama app's bundled binary
    nor a Homebrew install is found by `which` there, and the launch-time
    start and pull silently did nothing on a Mac with Ollama installed.
    """
    import sys

    if sys.platform == "darwin":
        return [
            "/Applications/Ollama.app/Contents/Resources/ollama",
            os.path.expanduser("~/Applications/Ollama.app/Contents/Resources/ollama"),
            "/opt/homebrew/bin/ollama",
            "/usr/local/bin/ollama",
        ]
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    return [os.path.join(local_app_data, "Programs", "Ollama", "ollama.exe")] if local_app_data else []


def _local_ollama_executable() -> str:
    """The Ollama executable, or "". Translation and smart formatting use this too."""
    discovered = shutil.which("ollama")
    if discovered:
        return discovered
    for candidate in _ollama_executable_candidates():
        if os.path.isfile(candidate):
            return candidate
    if mac_support.IS_MAC:
        # A .app launched from Finder inherits launchd's PATH, so fall back to
        # the Mac port's own search when the shared candidates found nothing.
        return mac_support.find_ollama() or ""
    return ""


def _is_local_ollama_base(api_base: str) -> bool:
    try:
        host = (urllib.parse.urlparse(api_base).hostname or "").lower()
    except ValueError:
        return False
    return host in {"127.0.0.1", "localhost", "::1"}


def local_formatter_preparing(config: dict[str, Any]) -> bool:
    """Whether a prepare_local_formatter worker is still running for this config.

    Smart formatting setup waits on this so "Ready" means warm, not merely
    downloaded.
    """
    settings = llm_settings(config)
    api_base = str(settings.get("api_base", "")).strip() or PROVIDER_DEFAULTS["ollama"]["api_base"]
    model = str(settings.get("model", "")).strip() or LOCAL_FORMATTER_MODEL
    with _OLLAMA_PREPARE_LOCK:
        return _ollama_prepare_key(api_base, model) in _OLLAMA_PREPARE_IN_FLIGHT


def prepare_local_formatter(config: dict[str, Any]) -> None:
    """Start, install, and warm the selected local formatter without blocking paste."""
    settings = llm_settings(config)
    if resolved_llm_provider(config) != "ollama":
        return
    api_base = str(settings.get("api_base", "")).strip() or PROVIDER_DEFAULTS["ollama"]["api_base"]
    model = str(settings.get("model", "")).strip() or LOCAL_FORMATTER_MODEL
    auto_install = bool(settings.get("auto_install", True))
    prepare_key = _ollama_prepare_key(api_base, model)
    with _OLLAMA_PREPARE_LOCK:
        if prepare_key in _OLLAMA_PREPARE_IN_FLIGHT or prepare_key in _OLLAMA_PREPARED:
            return
        _OLLAMA_PREPARE_IN_FLIGHT.add(prepare_key)

    def worker() -> None:
        prepared = False
        try:
            executable = _local_ollama_executable()
            models = _ollama_models(api_base, timeout=0.35)
            if models is None and executable and _is_local_ollama_base(api_base):
                creation_flags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
                try:
                    subprocess.Popen(
                        [executable, "serve"],
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        creationflags=creation_flags,
                    )
                except OSError:
                    return
                for _ in range(20):
                    time.sleep(0.15)
                    models = _ollama_models(api_base, timeout=0.2)
                    if models is not None:
                        break
            if models is None:
                return

            # A GPU machine may hold only the 4B (smart formatting setup pulls
            # it alone there). Warm and measure it directly; it is the model
            # that will answer. Only if it did not land on the GPU does this
            # fall through to the 1.7B, pulling it when auto_install allows.
            # A Mac under 16 GB never warms the 4B, even one already pulled.
            if model.lower() == LOCAL_FORMATTER_MODEL.lower() and mac_support.gpu_model_fits():
                gpu_tag = LOCAL_GPU_MODEL.lower()
                if gpu_tag in models or f"{gpu_tag}:latest" in models:
                    _OLLAMA_READY_CACHE.clear()
                    gpu_speed = warm_local_finish(api_base, LOCAL_GPU_MODEL)
                    if gpu_speed is not None and gpu_speed.on_gpu is True:
                        prepared = True
                        return

            wanted = model.lower()
            installed = wanted in models or (":" not in wanted and f"{wanted}:latest" in models)
            if not installed and auto_install and executable:
                creation_flags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
                try:
                    subprocess.run(
                        [executable, "pull", model],
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=1800,
                        check=False,
                        creationflags=creation_flags,
                    )
                except (OSError, subprocess.TimeoutExpired):
                    return
                models = _ollama_models(api_base, timeout=0.5)
                installed = models is not None and (
                    wanted in models or (":" not in wanted and f"{wanted}:latest" in models)
                )
            if not installed:
                return

            _OLLAMA_READY_CACHE.clear()
            speed = warm_local_finish(api_base, model)
            if speed is None:
                return
            prepared = True
            # The small model is warm, so finishing works from here on. Mark
            # it prepared NOW: the GPU model below may be a 2.5 GB download,
            # and a prepare still "in flight" refuses every finish meanwhile.
            with _OLLAMA_PREPARE_LOCK:
                _OLLAMA_PREPARED.add(prepare_key)
            # X-412, widened 2026-09-22: a machine that runs models on its GPU
            # finishes BOTH Chill and Executive with the 4B instruct model, and
            # it has to be warm before somebody dictates or the first finish
            # pays a 2.5 GB load. A CPU machine is not offered it at all: the
            # 1.7B alone costs 37 s there, so loading a bigger one would be
            # pure waste. With auto_install on, the GPU model is pulled the
            # same way the 1.7B was; a 4B that spills off the GPU measures
            # itself on_gpu=False and local_finish_target keeps the 1.7B. A Mac
            # under 16 GB is not offered it: its 1.7B measures on_gpu (Metal)
            # too, so without this the launch would pull the 2.5 GB model.
            if speed.on_gpu and model.lower() == LOCAL_FORMATTER_MODEL.lower() and mac_support.gpu_model_fits():
                installed_now = _ollama_models(api_base, timeout=1.0) or set()
                upgrade = choose_local_model(
                    model, executive=True, installed=installed_now, on_gpu=True
                )
                if (
                    upgrade.lower() == model.lower()
                    and auto_install
                    and executable
                    and _is_local_ollama_base(api_base)
                ):
                    creation_flags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
                    try:
                        subprocess.run(
                            [executable, "pull", LOCAL_GPU_MODEL],
                            stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            timeout=3600,
                            check=False,
                            creationflags=creation_flags,
                        )
                    except (OSError, subprocess.TimeoutExpired):
                        return
                    _OLLAMA_READY_CACHE.clear()
                    upgrade = choose_local_model(
                        model,
                        executive=True,
                        installed=_ollama_models(api_base, timeout=1.0) or set(),
                        on_gpu=True,
                    )
                if upgrade.lower() != model.lower():
                    warm_local_finish(api_base, upgrade)
        finally:
            with _OLLAMA_PREPARE_LOCK:
                _OLLAMA_PREPARE_IN_FLIGHT.discard(prepare_key)
                if prepared:
                    _OLLAMA_PREPARED.add(prepare_key)

    threading.Thread(target=worker, name="TalkDatLocalFormatter", daemon=True).start()


# X-500: the model answered the person instead of doing the work.
#
# He asked for a reformat, spoke, and got back "Certainly. Here is the
# rewritten text:" sitting above his own words. His words: "almost like it went
# to ask ChatGPT. It just needs to do it."
#
# X-491 is why. Rewrite and Fix That used to go to the managed service, which
# never chatted; they go to a LOCAL model or the person's own provider now, and
# those talk back. The old rule stripped a bare "rewritten text:" label and was
# anchored to exactly that, so a conversational opener walked straight past it.
#
# DELIBERATELY NARROW. An opener is removed only when a give-away phrase is
# present -- "here is ...:" or a "<something> text:" label -- with an optional
# courtesy word in front. A courtesy word alone is not enough, or "Certainly a
# good idea." loses its first word. A line merely ending in a colon is not
# enough either, or "Dear Sarah:" and "Note:" get eaten. Both directions are
# pinned in tests/test_the_rewrite_does_not_talk_back.py.
_COURTESY = r"(?:certainly|sure|of\s+course|absolutely|got\s+it|okay|ok|no\s+problem|happy\s+to)"

_PREAMBLE = re.compile(
    r"^\s*"
    + _COURTESY
    + r"?\s*[.,!:;\u2014-]*\s*"
    r"(?:here(?:\s+is|\s*'s|\s+you\s+go)[^:\n]{0,60}:"
    r"|(?:formatted|rewritten|corrected|revised|updated|polished|edited)"
    r"\s+(?:text|version|copy)\s*:"
    r"|output\s*:)"
    r"[ \t]*\n?",
    re.IGNORECASE,
)


def _clean_llm_output(text: str) -> str:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.IGNORECASE | re.DOTALL).strip()
    stripped = _PREAMBLE.sub("", text, count=1).strip()
    # Never hand back nothing. If the whole reply WAS a preamble, the reply is
    # all we have, and returning empty would silently wipe his selection --
    # a worse failure than the chatty line this exists to remove.
    return (stripped or text).strip()


def llm_complete(
    system: str,
    user: str,
    config: dict[str, Any],
    *,
    timeout_override: float | None = None,
) -> str | None:
    """Low-level model-agnostic completion. Returns None when unavailable or on error."""
    settings = llm_settings(config)
    chosen = str(settings.get("provider", "none")).strip().lower()
    provider = resolved_llm_provider(config)
    if provider in {"", "none"}:
        return None
    defaults = PROVIDER_DEFAULTS.get(provider)
    if defaults is None:
        return None
    api_key = _api_key(settings, provider)
    if chosen == "auto" and provider != "ollama":
        # X-365: auto reached a BYOK provider by following the SPEECH route,
        # so the key it must use is the speech key -- the formatter settings
        # hold one key belonging to whatever provider was last chosen by
        # hand, which is usually nothing at all on a BYOK install.
        from .stt_registry import resolve_route

        speech_route = resolve_route(config)
        if TEXT_CAPABLE_SPEECH_PROVIDERS.get(speech_route) == provider:
            api_key = byok_text_key(config, speech_route) or api_key
    if chosen == "auto":
        # Auto resolves the WHOLE route: a stored model or base belongs to
        # whatever the user last had configured, not to the provider auto
        # just picked. The cloud route ignores both; the local route runs
        # the shipped local model.
        api_base = defaults["api_base"]
        model = defaults["model"]
    else:
        api_base = str(settings.get("api_base", "")).strip() or defaults["api_base"]
        model = str(settings.get("model", "")).strip() or defaults["model"]
    timeout = float(settings.get("timeout", 30))
    if timeout_override is not None:
        timeout = max(0.1, min(timeout, float(timeout_override)))
    if provider != "ollama" and not api_key:
        return None
    if not api_base or not model:
        return None
    if provider == "ollama":
        if _ollama_prepare_pending(api_base, model):
            return None
        if not _ollama_ready(api_base, model):
            return None
    try:
        if provider == "anthropic":
            output = _complete_anthropic(system, user, api_base=api_base, api_key=api_key, model=model, timeout=timeout)
        elif provider == "gemini":
            output = _complete_gemini(system, user, api_base=api_base, api_key=api_key, model=model, timeout=timeout)
        elif provider == "ollama":
            output = _complete_ollama(system, user, api_base=api_base, model=model, timeout=min(timeout, 8.0))
        else:
            output = _complete_openai(system, user, api_base=api_base, api_key=api_key, model=model, timeout=timeout)
    except (urllib.error.URLError, TimeoutError, OSError, RuntimeError, json.JSONDecodeError, KeyError, ValueError) as exc:
        # Falling back to the rules formatter is correct and deliberate -- a
        # dictation must never fail because a model did. But falling back
        # SILENTLY made a dead key undiagnosable: a 402 from an exhausted
        # OpenRouter balance produced byte-identical rules output for days and
        # looked like the formatter had quietly become worse. One log line is
        # the difference between "the app degraded" and "the key needs money".
        status = getattr(exc, "code", "")
        log.warning("model formatting unavailable (%s%s); using the rules formatter",
                    type(exc).__name__, f" HTTP {status}" if status else "")
        return None
    output = _clean_llm_output(output)
    return output or None


def llm_rewrite(
    text: str, instruction: str, config: dict[str, Any], *, system: str = ""
) -> str | None:
    """X-491: `system` carries the person's own voice profile.

    X-500 -- THE ROOT CAUSE OF THE CHATTY REWRITE. This was
    `system or REWRITE_SYSTEM_PROMPT`, so a voice profile REPLACED the standard
    prompt and took "Return only the rewritten text with no preamble, labels,
    or quotes" away with it. Anyone with a style profile was asking a local
    model to rewrite their words having never told it to keep quiet, and it
    answered them: "Certainly. Here is the rewritten text:".

    The managed service never did this because it built its own prompt server
    side, so moving to a local model exposed an instruction that had been
    carried for us. The voice profile now ADDS to the rule instead of
    standing in for it, and `_clean_llm_output` remains the safety net for a
    model that ignores both.
    """
    prompt = REWRITE_SYSTEM_PROMPT if not system.strip() else f"{system.strip()}\n\n{REWRITE_SYSTEM_PROMPT}"
    return llm_complete(
        prompt,
        f"Instruction: {instruction}\n\nText:\n{text}",
        config,
    )
