from __future__ import annotations

import math
import threading
import wave
from pathlib import Path

from . import mac_support
from .config import app_dir


SAMPLE_RATE = 48000
CHIME_VERSION = 5
OUTPUT_GAIN = 0.5


def _clamp(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _smoothstep(edge0: float, edge1: float, value: float) -> float:
    x = _clamp((value - edge0) / max(0.0001, edge1 - edge0), 0.0, 1.0)
    return x * x * (3.0 - 2.0 * x)


def _soft_clip(value: float) -> float:
    return math.tanh(value * 1.35) / math.tanh(1.35)


def _noise(seed: int) -> float:
    # Deterministic pseudo-random in [-1, 1] so cached sounds are stable.
    value = math.sin(seed * 12.9898) * 43758.5453
    return (value - math.floor(value)) * 2.0 - 1.0


def _pan_gains(pan: float) -> tuple[float, float]:
    pan = _clamp(pan, -1.0, 1.0)
    return math.cos((pan + 1.0) * math.pi / 4.0), math.sin((pan + 1.0) * math.pi / 4.0)


# --- Voice generators: each adds a short element to a stereo buffer ---------

def _voice_bell(samples, freq, start, dur, gain, pan, attack=0.012):
    """A soft, felted sine bell with gentle inharmonic partials."""
    left_gain, right_gain = _pan_gains(pan)
    start_index = int(start * SAMPLE_RATE)
    end_index = min(len(samples), start_index + int(dur * SAMPLE_RATE))
    for index in range(start_index, end_index):
        local = (index - start_index) / SAMPLE_RATE
        up = _smoothstep(0.0, attack, local)
        down = math.exp(-local * (3.4 / dur))
        env = up * down
        tone = math.sin(2.0 * math.pi * freq * local)
        tone += 0.16 * math.sin(2.0 * math.pi * freq * 2.01 * local + 0.3)
        tone += 0.04 * math.sin(2.0 * math.pi * freq * 3.02 * local + 1.0)
        value = tone * env * gain
        left, right = samples[index]
        samples[index] = (left + value * left_gain, right + value * right_gain)


def _voice_wood(samples, freq, start, dur, gain, pan):
    """A struck wooden block: fast attack, quick exponential decay, slight pitch
    drop, and a short noise transient at the strike for the 'clunk'."""
    left_gain, right_gain = _pan_gains(pan)
    start_index = int(start * SAMPLE_RATE)
    end_index = min(len(samples), start_index + int(dur * SAMPLE_RATE))
    for index in range(start_index, end_index):
        local = (index - start_index) / SAMPLE_RATE
        env = math.exp(-local * (6.5 / dur))
        bend = 1.0 + 0.10 * math.exp(-local * 90.0)  # tiny downward pitch tick
        body = math.sin(2.0 * math.pi * freq * bend * local)
        body += 0.5 * math.sin(2.0 * math.pi * freq * 1.47 * local)  # woody overtone
        body += 0.18 * math.sin(2.0 * math.pi * freq * 2.09 * local)
        transient = _noise(index * 7 + 3) * math.exp(-local * 420.0) * 0.6
        value = (body * env + transient) * gain
        left, right = samples[index]
        samples[index] = (left + value * left_gain, right + value * right_gain)


def _voice_sine(samples, freq, start, dur, gain, pan, attack=0.004):
    """A clean sine ping / ding."""
    left_gain, right_gain = _pan_gains(pan)
    start_index = int(start * SAMPLE_RATE)
    end_index = min(len(samples), start_index + int(dur * SAMPLE_RATE))
    for index in range(start_index, end_index):
        local = (index - start_index) / SAMPLE_RATE
        env = _smoothstep(0.0, attack, local) * math.exp(-local * (4.0 / dur))
        value = math.sin(2.0 * math.pi * freq * local) * env * gain
        left, right = samples[index]
        samples[index] = (left + value * left_gain, right + value * right_gain)


def _voice_click(samples, start, dur, gain, pan, tone=2600.0):
    """A light, felted click: filtered noise burst with a soft body."""
    left_gain, right_gain = _pan_gains(pan)
    start_index = int(start * SAMPLE_RATE)
    end_index = min(len(samples), start_index + int(dur * SAMPLE_RATE))
    previous = 0.0
    for index in range(start_index, end_index):
        local = (index - start_index) / SAMPLE_RATE
        env = math.exp(-local * (60.0 / max(0.01, dur)))
        raw = _noise(index * 5 + 11)
        # one-pole lowpass to take the edge off -> "felted"
        alpha = min(1.0, tone / SAMPLE_RATE)
        previous += alpha * (raw - previous)
        value = previous * env * gain
        left, right = samples[index]
        samples[index] = (left + value * left_gain, right + value * right_gain)


def _voice_pluck(samples, freq, start, dur, gain, pan):
    """A short plucked string-ish tone (decaying filtered tone)."""
    left_gain, right_gain = _pan_gains(pan)
    start_index = int(start * SAMPLE_RATE)
    end_index = min(len(samples), start_index + int(dur * SAMPLE_RATE))
    for index in range(start_index, end_index):
        local = (index - start_index) / SAMPLE_RATE
        env = math.exp(-local * (5.0 / dur)) * _smoothstep(0.0, 0.002, local)
        tone = math.sin(2.0 * math.pi * freq * local)
        tone += 0.3 * math.sin(2.0 * math.pi * freq * 2.0 * local) * math.exp(-local * 12.0)
        value = tone * env * gain
        left, right = samples[index]
        samples[index] = (left + value * left_gain, right + value * right_gain)


_VOICE_FUNCS = {
    "bell": _voice_bell,
    "wood": _voice_wood,
    "sine": _voice_sine,
    "click": _voice_click,
    "pluck": _voice_pluck,
}


# --- The 20-sound bank ------------------------------------------------------
# Each entry: (label, duration_seconds, [voices]). A voice is a dict with a
# "type" plus its parameters. All are short and tuned to the same loudness.

SOUND_BANK: dict[str, tuple[str, float, tuple[dict, ...]]] = {
    "felted_halo": ("Felted Halo", 0.20, (
        {"type": "click", "start": 0.0, "dur": 0.05, "gain": 0.30, "pan": 0.0, "tone": 2200.0},
        {"type": "bell", "start": 0.01, "dur": 0.16, "freq": 587.33, "gain": 0.5, "pan": -0.1},
        {"type": "bell", "start": 0.05, "dur": 0.15, "freq": 880.0, "gain": 0.42, "pan": 0.12},
    )),
    "wood_block": ("Wood Block", 0.13, (
        {"type": "wood", "start": 0.0, "dur": 0.11, "freq": 900.0, "gain": 0.62, "pan": 0.0},
    )),
    "wood_double": ("Wood Block Double", 0.20, (
        {"type": "wood", "start": 0.0, "dur": 0.09, "freq": 940.0, "gain": 0.55, "pan": -0.12},
        {"type": "wood", "start": 0.085, "dur": 0.10, "freq": 720.0, "gain": 0.6, "pan": 0.12},
    )),
    "soft_click": ("Soft Click", 0.08, (
        {"type": "click", "start": 0.0, "dur": 0.06, "gain": 0.6, "pan": 0.0, "tone": 1800.0},
    )),
    "click_ding": ("Click + Ding", 0.22, (
        {"type": "click", "start": 0.0, "dur": 0.04, "gain": 0.4, "pan": 0.0, "tone": 3000.0},
        {"type": "sine", "start": 0.02, "dur": 0.18, "freq": 1046.5, "gain": 0.4, "pan": 0.0},
    )),
    "ding": ("Ding", 0.26, (
        {"type": "sine", "start": 0.0, "dur": 0.24, "freq": 987.77, "gain": 0.5, "pan": 0.0},
    )),
    "snap": ("Snap", 0.10, (
        {"type": "click", "start": 0.0, "dur": 0.03, "gain": 0.7, "pan": 0.0, "tone": 4200.0},
        {"type": "wood", "start": 0.0, "dur": 0.06, "freq": 1500.0, "gain": 0.3, "pan": 0.0},
    )),
    "soft_snap": ("Soft Snap", 0.12, (
        {"type": "click", "start": 0.0, "dur": 0.05, "gain": 0.45, "pan": 0.0, "tone": 2400.0},
        {"type": "sine", "start": 0.01, "dur": 0.10, "freq": 1320.0, "gain": 0.22, "pan": 0.0},
    )),
    "marimba": ("Marimba", 0.30, (
        {"type": "bell", "start": 0.0, "dur": 0.28, "freq": 523.25, "gain": 0.5, "pan": 0.0},
        {"type": "sine", "start": 0.0, "dur": 0.10, "freq": 2093.0, "gain": 0.10, "pan": 0.0},
    )),
    "kalimba": ("Kalimba", 0.34, (
        {"type": "pluck", "start": 0.0, "dur": 0.32, "freq": 659.25, "gain": 0.5, "pan": 0.0},
    )),
    "harp_pluck": ("Harp Pluck", 0.36, (
        {"type": "pluck", "start": 0.0, "dur": 0.34, "freq": 440.0, "gain": 0.45, "pan": -0.1},
        {"type": "pluck", "start": 0.02, "dur": 0.30, "freq": 659.25, "gain": 0.32, "pan": 0.12},
    )),
    "glass_tap": ("Glass Tap", 0.22, (
        {"type": "sine", "start": 0.0, "dur": 0.20, "freq": 1567.98, "gain": 0.32, "pan": 0.0},
        {"type": "click", "start": 0.0, "dur": 0.02, "gain": 0.3, "pan": 0.0, "tone": 5000.0},
    )),
    "pebble_pop": ("Pebble Pop", 0.12, (
        {"type": "wood", "start": 0.0, "dur": 0.08, "freq": 1200.0, "gain": 0.45, "pan": 0.0},
        {"type": "sine", "start": 0.0, "dur": 0.06, "freq": 2400.0, "gain": 0.12, "pan": 0.0},
    )),
    "bubble": ("Bubble", 0.18, (
        {"type": "sine", "start": 0.0, "dur": 0.16, "freq": 500.0, "gain": 0.4, "pan": 0.0},
        {"type": "sine", "start": 0.05, "dur": 0.10, "freq": 900.0, "gain": 0.2, "pan": 0.0},
    )),
    "tick": ("Tick", 0.06, (
        {"type": "click", "start": 0.0, "dur": 0.03, "gain": 0.55, "pan": 0.0, "tone": 3500.0},
    )),
    "knock": ("Knock", 0.14, (
        {"type": "wood", "start": 0.0, "dur": 0.12, "freq": 380.0, "gain": 0.6, "pan": 0.0},
    )),
    "felt_tap": ("Felt Tap", 0.16, (
        {"type": "click", "start": 0.0, "dur": 0.06, "gain": 0.35, "pan": 0.0, "tone": 1400.0},
        {"type": "bell", "start": 0.0, "dur": 0.14, "freq": 392.0, "gain": 0.3, "pan": 0.0},
    )),
    "chime_up": ("Chime Up", 0.30, (
        {"type": "bell", "start": 0.0, "dur": 0.16, "freq": 523.25, "gain": 0.4, "pan": -0.1},
        {"type": "bell", "start": 0.10, "dur": 0.18, "freq": 783.99, "gain": 0.4, "pan": 0.12},
    )),
    "chime_down": ("Chime Down", 0.30, (
        {"type": "bell", "start": 0.0, "dur": 0.16, "freq": 783.99, "gain": 0.4, "pan": 0.1},
        {"type": "bell", "start": 0.10, "dur": 0.18, "freq": 523.25, "gain": 0.4, "pan": -0.12},
    )),
    "sine_ping": ("Sine Ping", 0.20, (
        {"type": "sine", "start": 0.0, "dur": 0.18, "freq": 740.0, "gain": 0.5, "pan": 0.0},
    )),
}

DEFAULT_ON_SOUND = "felted_halo"
DEFAULT_OFF_SOUND = "wood_block"


def sound_names() -> list[str]:
    return list(SOUND_BANK.keys())


def sound_label(name: str) -> str:
    entry = SOUND_BANK.get(name)
    return entry[0] if entry else name


def resolve_sound_name(name: str, fallback: str) -> str:
    return name if name in SOUND_BANK else fallback


def render_sound(name: str) -> list[tuple[float, float]]:
    _label, duration, voices = SOUND_BANK[name]
    total = int(SAMPLE_RATE * duration)
    samples: list[tuple[float, float]] = [(0.0, 0.0) for _ in range(total)]
    for voice in voices:
        func = _VOICE_FUNCS.get(str(voice.get("type")))
        if func is None:
            continue
        params = {key: value for key, value in voice.items() if key != "type"}
        func(samples, **params)
    # Normalize so every sound in the bank lands at a consistent loudness.
    peak = max((max(abs(left), abs(right)) for left, right in samples), default=0.0)
    if peak > 0.0001:
        scale = 0.9 / peak
        samples = [(left * scale, right * scale) for left, right in samples]
    return samples


def _write_wav(path: Path, samples: list[tuple[float, float]]) -> Path:
    frames = bytearray()
    for left, right in samples:
        left_sample = int(_clamp(_soft_clip(left * OUTPUT_GAIN)) * 32767)
        right_sample = int(_clamp(_soft_clip(right * OUTPUT_GAIN)) * 32767)
        frames.extend(left_sample.to_bytes(2, "little", signed=True))
        frames.extend(right_sample.to_bytes(2, "little", signed=True))
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(bytes(frames))
    return path


def ensure_sound(name: str) -> Path | None:
    if name not in SOUND_BANK:
        return None
    path = app_dir() / f"talk_dat_sound_{name}_v{CHIME_VERSION}.wav"
    if path.exists():
        return path
    try:
        return _write_wav(path, render_sound(name))
    except OSError:
        return None


def prewarm_sounds(names: list[str]) -> None:
    def worker() -> None:
        for name in names:
            ensure_sound(resolve_sound_name(name, DEFAULT_ON_SOUND))

    threading.Thread(target=worker, name="TalkDatSoundWarm", daemon=True).start()


def play_sound_named(name: str, *, enabled: bool = True) -> None:
    if not enabled:
        return

    def worker() -> None:
        try:
            path = ensure_sound(name)
            if path is None:
                return
            if mac_support.IS_MAC:
                # winsound does not exist here, and the `except Exception` below
                # swallowed the ImportError -- so start and stop chimes were on
                # by default, had working preview buttons in Settings, rendered
                # their WAVs to disk, and made no sound at all.
                mac_support.play_sound_file(str(path))
                return
            import winsound

            winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC)
        except Exception:
            return

    threading.Thread(target=worker, name="TalkDatChime", daemon=True).start()


def play_chime(kind: str, *, enabled: bool = True, name: str = "") -> None:
    if not enabled:
        return
    fallback = DEFAULT_OFF_SOUND if kind == "off" else DEFAULT_ON_SOUND
    play_sound_named(resolve_sound_name(name, fallback), enabled=True)
