"""Usage and cost estimates for the Stats window.

Saved history does not include measured audio durations to add up.
Minutes are derived from word count at a normal speaking rate, which makes every
figure here an estimate -- and the UI says so rather than presenting a derived
number as a measurement.

Rates are list prices per minute of audio, read from OpenRouter's catalogue on
2026-08-04. They are deliberately a small explicit table rather than a live
lookup: this renders in a settings window and must not depend on the network or
on an API key. A model that is not in the table reports None, which the UI shows
as a dash -- an honest "unknown" beats a confident $0.00.
"""

from __future__ import annotations

from typing import Any

# Words per minute of ordinary speech. Dictation runs a little slower than
# conversation because people self-correct, so this is the conservative end of
# the usual 140-160 range.
WORDS_PER_MINUTE = 150.0

DAYS_PER_MONTH = 30

# OpenRouter list price per minute of audio, 2026-08-04.
CLOUD_RATES_PER_MINUTE: dict[str, float] = {
    "microsoft/mai-transcribe-1.5": 0.006,
    "x-ai/grok-stt-1.0": 0.00167,
    "deepgram/nova-3": 0.0043,
    "mistralai/voxtral-mini-transcribe": 0.003,
    "google/chirp-3": 0.016,
    "nvidia/parakeet-tdt-0.6b-v3": 0.0015,
    "qwen/qwen3-asr-flash-2026-02-10": 0.0021,
    "fish-audio/transcribe-1": 0.006,
    "openai/whisper-large-v3": 0.0015,
    "openai/whisper-1": 0.006,
}

# Providers that run entirely on the user's machine, so cost is genuinely zero
# rather than merely unknown.
LOCAL_PROVIDERS = frozenset({"local"})


def spoken_minutes(words: float) -> float:
    """Approximate minutes of speech for a word count."""
    if words <= 0:
        return 0.0
    return float(words) / WORDS_PER_MINUTE


def estimated_monthly_cost(provider: str, model: str, minutes_per_day: float) -> float | None:
    """Projected monthly spend, or None when there is no rate for the model.

    Returning None rather than 0.0 for an unpriced model matters: a confident
    zero would tell someone a paid model is free.
    """
    if str(provider) in LOCAL_PROVIDERS:
        return 0.0
    rate = CLOUD_RATES_PER_MINUTE.get(str(model))
    if rate is None:
        return None
    return max(0.0, float(minutes_per_day)) * rate * DAYS_PER_MONTH


def usage_summary(config: dict[str, Any], words: int, days_active: int) -> dict[str, Any]:
    """Everything the Stats window needs about usage and cost.

    Never raises: it renders inside a settings window, and an exception there
    leaves a blank panel rather than a missing row.
    """
    stt = config.get("stt") if isinstance(config, dict) else None
    stt = stt if isinstance(stt, dict) else {}
    provider = str(stt.get("provider") or "local")
    providers = stt.get("providers")
    providers = providers if isinstance(providers, dict) else {}
    settings = providers.get(provider)
    settings = settings if isinstance(settings, dict) else {}
    model = str(settings.get("model") or "")

    total_minutes = spoken_minutes(words)
    # Divide by the days actually used, not the calendar. Someone who dictates
    # twice a week would otherwise appear to average almost nothing per day,
    # which understates their real sessions and their real spend.
    per_active_day = total_minutes / days_active if days_active > 0 else 0.0
    is_cloud = provider not in LOCAL_PROVIDERS

    return {
        "provider": provider,
        "model": model,
        "is_cloud": is_cloud,
        "total_minutes": round(total_minutes, 1),
        "minutes_per_active_day": round(per_active_day, 2),
        "estimated_monthly_cost": estimated_monthly_cost(provider, model, per_active_day),
        "rate_per_minute": CLOUD_RATES_PER_MINUTE.get(model) if is_cloud else 0.0,
    }
