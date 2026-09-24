"""X-478: pick the speech model by measuring this machine, not by guessing.

Today proved why guessing loses. Three things were believed and all three were
wrong on the machine in front of us:

  * Parakeet was assumed fastest because it is smallest. On real dictation with
    a working GPU it was the SLOWEST of three (1104 ms against 717 ms).
  * Whisper was assumed unusable on the GPU. It was unusable only because a DLL
    directory was not on PATH, which is a five-line fix (X-475).
  * Canary was advertised as the higher-accuracy option and does not run at all
    (X-474).

No static ranking survives contact with a particular machine. A laptop with no
discrete GPU, a 3090 with the CUDA runtime, and a Mac all order these models
differently, and the only honest way to know is to run them here.

So this measures, on a short fixed clip, once, and remembers.

WHAT IT DELIBERATELY IS NOT. Not automatic in the sense of overriding a person.
Handy's approach is right: measure, recommend, and let them pick anything they
like. The measurement makes the default trustworthy; it does not take the
choice away. An explicit choice is never second-guessed.

WHAT IT NEVER DOES. It never runs during a dictation, never downloads anything
to find out, and never blocks the first word. A model that is not on disk is
not a candidate, because "let me fetch a gigabyte to see if it is faster" is
not a thing to do to someone who just wants to talk.
"""

from __future__ import annotations

import json
import logging
import math
import struct
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .config import app_dir

log = logging.getLogger(__name__)

# Bumped when anything that could change a measurement changes: the clip, the
# scoring, or a fix like X-475 that alters what the hardware can reach. A stale
# verdict is worse than none, because it is trusted.
PROBE_VERSION = 3

RESULT_FILE = "model-speed.json"

# Four seconds. Long enough that per-call overhead is not the whole reading,
# short enough that probing a handful of models is seconds rather than a wait.
PROBE_SECONDS = 4.0
PROBE_RATE = 16000


@dataclass(frozen=True)
class Measurement:
    model_id: str
    milliseconds: float
    realtime: float
    failed: bool
    detail: str = ""


def _probe_audio() -> bytes:
    """A deterministic clip, generated rather than shipped.

    Speech-shaped enough that a model does real work: a moving formant over a
    voiced fundamental, gated into syllable-length bursts with gaps. It is not
    speech and no transcript is read from it, because this measures SPEED and
    nothing else. Accuracy cannot be measured without ground truth, and
    inventing a number for it would be worse than admitting that.
    """
    total = int(PROBE_SECONDS * PROBE_RATE)
    samples = bytearray()
    for index in range(total):
        seconds = index / PROBE_RATE
        # Syllables: roughly four a second, with real silence between them.
        gate = 1.0 if (seconds * 4.0) % 1.0 < 0.62 else 0.0
        fundamental = 118.0 + 26.0 * math.sin(seconds * 2.4)
        formant = 640.0 + 380.0 * math.sin(seconds * 1.7)
        value = (
            0.42 * math.sin(2 * math.pi * fundamental * seconds)
            + 0.28 * math.sin(2 * math.pi * formant * seconds)
            + 0.14 * math.sin(2 * math.pi * (formant * 2.1) * seconds)
        )
        samples += struct.pack("<h", int(max(-1.0, min(1.0, value * gate)) * 12000))
    return bytes(samples)


def results_path() -> Path:
    return Path(app_dir()) / RESULT_FILE


def _fingerprint(model_ids: list[str]) -> str:
    """What the stored verdict was measured against.

    A verdict is only valid for the same probe, the same candidates and the
    same machine capability. Installing the CUDA runtime changes the answer
    completely, which is exactly the case X-475 created, so it is part of this.
    """
    try:
        from . import cuda_runtime
        cuda = "cuda" if cuda_runtime.is_installed() else "nocuda"
    except Exception:
        cuda = "nocuda"
    return f"v{PROBE_VERSION}:{cuda}:" + ",".join(sorted(model_ids))


def read_results() -> dict[str, Any]:
    try:
        return json.loads(results_path().read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_results(payload: dict[str, Any]) -> None:
    try:
        results_path().parent.mkdir(parents=True, exist_ok=True)
        results_path().write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except Exception:
        log.debug("could not store the speed probe", exc_info=True)


def candidates(config: dict[str, Any]) -> list[str]:
    """Models already on disk. Nothing is downloaded to be measured."""
    from . import local_stt

    ready: list[str] = []
    for model in local_stt.available_models(config) if hasattr(local_stt, "available_models") \
            else local_stt.LOCAL_MODELS:
        try:
            if local_stt.is_downloaded(model):
                ready.append(model.id)
        except Exception:
            log.debug("could not check %s", getattr(model, "id", "?"), exc_info=True)
    return ready


def measure(model_ids: list[str], gpu: bool = True) -> list[Measurement]:
    """Time each candidate on the same clip. A failure is a result, not a raise.

    A model that raises here is a model that would have raised on a real
    dictation, so recording it keeps the picker from ever recommending it. That
    is the Canary case (X-474) caught automatically rather than by hand.
    """
    from . import local_stt

    pcm = _probe_audio()
    out: list[Measurement] = []
    for model_id in model_ids:
        try:
            # Warm first and throw it away: the first call loads the weights,
            # and a cold reading has been wrong by 20x on this machine before.
            local_stt.transcribe(model_id=model_id, pcm16=pcm, sample_rate=PROBE_RATE,
                                 channels=1, language="en", gpu=gpu)
            started = time.perf_counter()
            local_stt.transcribe(model_id=model_id, pcm16=pcm, sample_rate=PROBE_RATE,
                                 channels=1, language="en", gpu=gpu)
            elapsed = time.perf_counter() - started
            out.append(Measurement(model_id, elapsed * 1000.0,
                                   PROBE_SECONDS / max(elapsed, 1e-6), False))
        except Exception as error:  # noqa: BLE001
            out.append(Measurement(model_id, float("inf"), 0.0, True,
                                   f"{type(error).__name__}: {error}"[:160]))
            log.info("speed probe: %s cannot run here (%s)", model_id, type(error).__name__)
    return out


def run_probe(config: dict[str, Any], gpu: bool = True) -> dict[str, Any]:
    ready = candidates(config)
    if not ready:
        return {}
    measurements = measure(ready, gpu=gpu)
    payload = {
        "fingerprint": _fingerprint(ready),
        "measured_at": int(time.time()),
        "results": [asdict(m) for m in measurements],
    }
    _write_results(payload)
    return payload


def is_current(config: dict[str, Any]) -> bool:
    """Is the stored verdict still about this machine and these models?"""
    stored = read_results()
    if not stored:
        return False
    return stored.get("fingerprint") == _fingerprint(candidates(config))


def recommended_model(config: dict[str, Any]) -> str:
    """The fastest model that actually ran, or "" if nothing has been measured.

    Speed only, and the docstring on `_probe_audio` says why: accuracy needs
    ground truth this does not have. Where two models are within a few percent
    the tie is broken by the catalogue's own recommendation, so a measurement
    that cannot really tell them apart does not churn the default.
    """
    stored = read_results()
    if not stored or stored.get("fingerprint") != _fingerprint(candidates(config)):
        return ""
    working = [r for r in stored.get("results", []) if not r.get("failed")]
    if not working:
        return ""
    working.sort(key=lambda r: r.get("milliseconds", float("inf")))
    best = working[0]
    from . import local_stt

    default_id = getattr(local_stt, "DEFAULT_LOCAL_MODEL_ID", "")
    for row in working:
        if row["model_id"] == default_id and \
                row["milliseconds"] <= best["milliseconds"] * 1.05:
            return default_id
    return str(best["model_id"])


def unusable_models(config: dict[str, Any]) -> list[str]:
    """Everything the probe found cannot run here. The UI should not offer these."""
    stored = read_results()
    if not stored or stored.get("fingerprint") != _fingerprint(candidates(config)):
        return []
    return [r["model_id"] for r in stored.get("results", []) if r.get("failed")]
