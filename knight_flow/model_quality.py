"""Accuracy and speed ratings for the speech models, for the model picker.

Someone choosing between twenty-five models has no way to judge them from names
alone, and the honest signal is not marketing copy -- it is measurement. Accuracy
comes from Artificial Analysis AA-WER and speed from its speed factor, both read
2026-08-04, converted to a five-point scale in half steps.

Two rules keep this defensible. A model that has not been measured shows no
rating at all rather than a flattering guess. And the ratings are derived from
the numbers by a function, so a model cannot be presented as better than it
measures without changing the measurement.

Rendered as a filled bar rather than stars: stars read as a review score, and
this is not an opinion.
"""

from __future__ import annotations

FULL = "▰"
HALF = "▨"
EMPTY = "▱"

# AA-WER percentage -> rating. Lower error is better.
_ACCURACY_BANDS = (
    (2.3, 5.0),
    (2.6, 4.5),
    (3.1, 4.0),
    (3.6, 3.5),
    (4.3, 3.0),
    (4.9, 2.5),
    (5.6, 2.0),
    (7.0, 1.5),
    (12.0, 1.0),
)

# Speed factor (x real time) -> rating. Higher is better.
_SPEED_BANDS = (
    (400, 5.0),
    (200, 4.5),
    (110, 4.0),
    (65, 3.5),
    (35, 3.0),
    (18, 2.5),
    (8, 2.0),
    (3, 1.5),
)


def accuracy_rating(word_error_rate: float) -> float:
    """Five-point accuracy rating from a measured AA-WER percentage."""
    for threshold, rating in _ACCURACY_BANDS:
        if word_error_rate <= threshold:
            return rating
    return 0.5


def speed_rating(speed_factor: float) -> float:
    """Five-point speed rating from a measured multiple of real time."""
    for threshold, rating in _SPEED_BANDS:
        if speed_factor >= threshold:
            return rating
    return 0.5


def meter(rating: float) -> str:
    """A five-slot bar. Always five characters so columns line up."""
    rating = max(0.5, min(5.0, float(rating)))
    full = int(rating)
    half = 1 if rating - full >= 0.5 else 0
    return (FULL * full + HALF * half + EMPTY * (5 - full - half))[:5]


# model id -> measured AA-WER and speed factor.
# Local ids are the Talk DAT! catalogue names; cloud ids are OpenRouter slugs.
_MEASURED: dict[str, tuple[float, float]] = {
    # Cloud, via OpenRouter
    "microsoft/mai-transcribe-1.5": (2.4, 190.0),
    "mistralai/voxtral-mini-transcribe": (3.6, 77.3),
    "openai/gpt-4o-transcribe": (4.0, 36.7),
    "x-ai/grok-stt-1.0": (4.0, 225.0),
    "openai/whisper-large-v3": (4.1, 48.4),
    "openai/gpt-4o-mini-transcribe": (4.5, 40.8),
    "nvidia/parakeet-tdt-0.6b-v3": (4.5, 885.0),
    "openai/whisper-large-v3-turbo": (4.6, 113.9),
    "deepgram/nova-3": (5.2, 505.4),
    "google/chirp-3": (5.1, 69.4),
    "qwen/qwen3-asr-flash-2026-02-10": (3.5, 95.6),
    "fish-audio/transcribe-1": (4.7, 204.0),
    "openai/whisper-1": (4.1, 27.6),
    # Local, on this machine. Speed factors are the hosted measurements for the
    # same weights and will be lower on a plain CPU, so they are damped rather
    # than quoted directly -- promising 885x on a laptop would be a lie.
    "parakeet-tdt-0.6b-v3": (4.5, 45.0),
    "parakeet-tdt-0.6b-v2": (6.4, 45.0),
    "whisper-large-v3": (4.1, 8.0),
    "whisper-large-v3-turbo": (4.6, 20.0),
    "canary-1b-v2": (4.3, 6.0),
    "canary-180m-flash": (5.4, 60.0),
    "distil-large-v3.5": (4.8, 22.0),
    "whisper-medium": (6.1, 12.0),
    "whisper-small": (8.2, 30.0),
    "whisper-base": (11.0, 60.0),
    "whisper-tiny": (14.5, 90.0),
}

MODEL_RATINGS: dict[str, dict[str, float]] = {
    model_id: {
        "accuracy": accuracy_rating(wer),
        "speed": speed_rating(factor),
        "word_error_rate": wer,
        "speed_factor": factor,
    }
    for model_id, (wer, factor) in _MEASURED.items()
}


def quality_line(model_id: str) -> str:
    """One-line rating for the picker, or "" when the model is unmeasured."""
    rating = MODEL_RATINGS.get(str(model_id))
    if not rating:
        return ""
    return (
        f"Accuracy {meter(rating['accuracy'])}  "
        f"Speed {meter(rating['speed'])}"
    )


def quality_detail(model_id: str) -> str:
    """Longer form with the underlying numbers, for tooltips and detail rows."""
    rating = MODEL_RATINGS.get(str(model_id))
    if not rating:
        return ""
    return (
        f"{rating['word_error_rate']:.1f}% word error rate, "
        f"{rating['speed_factor']:.0f}x real time (measured)"
    )
