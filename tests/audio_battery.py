"""The commandment cases that need a voice (docs/DICTATION-COMMANDMENTS.md 6.1).

tests/commandment_battery.py runs every case whose input is text and skips the
ones whose input is SOUND: silence and keyboard noise, one short word, a
31-second take, an 8-second pause, a hesitation, a name said aloud, a name the
person taught. This lane runs those, the way the app does:

    Windows voice (System.Speech, on this machine) -> a real BatchSTTSession fed
    by a fake microphone -> the real local model (Parakeet) -> the pipeline with
    the take's word confidence -> the battery's own verdict.

It is local and manual like the parity battery: Windows only, needs the local
model installed, never downloads, never leaves the machine. A synthetic voice is
not a person, so a pass here is evidence and a fail is a lead to check by ear;
cases that depend on hardware timing (a headset waking, speech before the
hotkey) stay out of it and remain in the skip list.

    python -m tests.audio_battery
    python -m tests.audio_battery --only C004-pos,C007-pos --json out.json
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import random
import re
import subprocess
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path
from typing import Any

RATE = 16000
CHUNK_MS = 100
#: Fed four times faster than real time: the session's decisions here are
#: byte-counted (segments) or far longer than any case (timeouts).
PACE_SECONDS = 0.025
CACHE = Path(tempfile.gettempdir()) / "talkdat-audio-battery"

# How each case is voiced. ("say", text[, rate]) is the Windows voice; an
# SSML string is spoken as SSML (a name's pronunciation); ("pause", s) is room
# tone; ("typing", s) is keyboard clicks over room noise and no speech.
SCRIPTS: dict[str, list[tuple]] = {
    "C001-pos": [("typing", 3.0)],
    "C001-neg": [("say", "Thanks.")],
    "C004-pos": [("say", "Before we close the quarter we still need the bank reconciliation report from "
                  "finance, the signed vendor contracts from legal, and the final headcount numbers from "
                  "people ops. I'd like all of it in the shared folder by Thursday at noon so we have "
                  "Friday to review it before the board call.", -2)],
    "C004-neg": [("say", "We can ship on Friday"), ("pause", 8.0), ("say", "and the release notes are done.")],
    "C005-pos": [("say", "The build passed"), ("pause", 1.1), ("say", "I will deploy after lunch")],
    "C005-neg": [("say", "We need the"), ("pause", 0.9), ("say", "quarterly numbers by Friday")],
    "C007-pos": [("ssml", '<phoneme alphabet="ipa" ph="ʃɪˈvɔːn">Siobhan</phoneme> approved the budget.')],
    "C007-neg": [("say", "Sheila approved the budget.")],
    # Spelled "Kaelin" because that is what makes this voice come out as the
    # "Kaylin" the case's history describes ("Kaylin" itself is heard "Kalen").
    "C099-pos": [("say", "Kaelin approved it.")],
    "C099-neg": [("say", "Kaelin approved it.")],
}

# What the app holds after the history a case describes (learned_words.py).
HISTORY = {
    "C099-pos": {"terms": [{"text": "Kaelyn", "sounds_like": ["kaylin"], "learned": True}]},
    "C099-neg": {"learn_tombstones": ["kaelyn"]},
}


def _voice_wav(kind: str, text: str, rate: int) -> bytes:
    """16 kHz mono PCM of the Windows voice saying `text`, cached by content."""
    CACHE.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(f"{kind}|{rate}|{text}".encode("utf-8")).hexdigest()[:16]
    path = CACHE / f"{key}.wav"
    if not path.exists():
        body = (f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="en-US">{text}</speak>'
                if kind == "ssml" else text)
        source = CACHE / f"{key}.txt"
        source.write_text(body, encoding="utf-8")
        script = (
            "Add-Type -AssemblyName System.Speech;"
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
            f"$s.Rate = {int(rate)};"
            "$f = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, "
            "[System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono);"
            f"$s.SetOutputToWaveFile('{path}', $f);"
            f"$t = [IO.File]::ReadAllText('{source}');"
            + ("$s.SpeakSsml($t);" if kind == "ssml" else "$s.Speak($t);")
            + "$s.Dispose()"
        )
        subprocess.run(["powershell.exe", "-NoProfile", "-Command", script], check=True, capture_output=True)
    with wave.open(str(path), "rb") as source_wav:
        return source_wav.readframes(source_wav.getnframes())


def _pcm(samples: list[float]) -> bytes:
    return b"".join(int(max(-1.0, min(1.0, s)) * 32767).to_bytes(2, "little", signed=True) for s in samples)


def _room(seconds: float, rng: random.Random, level: float = 0.002) -> list[float]:
    return [rng.gauss(0.0, level) for _ in range(int(seconds * RATE))]


def _typing(seconds: float, rng: random.Random) -> list[float]:
    """Key clicks (short broadband bursts) every 110-260 ms over room noise."""
    samples = _room(seconds, rng, 0.004)
    at = int(0.15 * RATE)
    while at < len(samples):
        for i in range(int(0.006 * RATE)):
            if at + i < len(samples):
                samples[at + i] += rng.uniform(-0.25, 0.25) * math.exp(-i / (0.0015 * RATE))
        at += int(rng.uniform(0.11, 0.26) * RATE)
    return samples


def compose(case_id: str) -> bytes:
    """The whole take: a little room before and after, as a real press has."""
    rng = random.Random(case_id)
    parts = [_pcm(_room(0.3, rng))]
    for part in SCRIPTS[case_id]:
        if part[0] in {"say", "ssml"}:
            parts.append(_voice_wav(part[0], part[1], part[2] if len(part) > 2 else 0))
        elif part[0] == "pause":
            parts.append(_pcm(_room(part[1], rng)))
        elif part[0] == "typing":
            parts.append(_pcm(_typing(part[1], rng)))
    parts.append(_pcm(_room(0.4, rng)))
    return b"".join(parts)


class _Microphone:
    def __init__(self, callback, pcm: bytes) -> None:
        step = 2 * RATE * CHUNK_MS // 1000
        self._chunks = [pcm[i:i + step] for i in range(0, len(pcm), step)]
        self._callback, self.done = callback, threading.Event()

    def __enter__(self):
        def feed() -> None:
            for chunk in self._chunks:
                self._callback(chunk, len(chunk) // 2, None, None)
                time.sleep(PACE_SECONDS)
            self.done.set()
        threading.Thread(target=feed, daemon=True).start()
        return self

    def __exit__(self, *exc) -> None:
        self.done.set()


def hear(pcm: bytes, config: dict[str, Any]) -> tuple[str, dict[str, float]]:
    """The take through a real session and the real local model."""
    from unittest.mock import patch

    from knight_flow import stt_sessions
    from knight_flow.config import engine_recording_ceiling

    done: list = []
    microphone: list[_Microphone] = []
    session = stt_sessions.BatchSTTSession(
        provider_id="local", api_key="", api_base="", model="parakeet-tdt-0.6b-v3", variant="",
        language="en-US", sample_rate=RATE, channels=1, max_seconds=engine_recording_ceiling(False),
        no_speech_timeout_seconds=120, silence_timeout_seconds=300, tail_capture_ms=520, min_capture_ms=900,
        extra={"config": config}, on_update=lambda *_: None, on_status=lambda *_: None,
        on_level=lambda *_: None, on_done=done.append, on_error=lambda error: done.append(("error", error)),
    )

    def open_stream(**kwargs):
        microphone.append(_Microphone(kwargs["callback"], pcm))
        return microphone[-1], RATE, 1, None

    with patch.object(stt_sessions, "open_raw_input_stream", open_stream), \
         patch.object(stt_sessions, "input_stream_active", lambda stream: True):
        session.start()
        while not microphone or not microphone[0].done.is_set():
            time.sleep(0.05)
        session.stop()  # the key is released when the words are out
        session.join(timeout=300)
    result = done[0] if done else ("error", "no result")
    if isinstance(result, tuple):
        raise RuntimeError(str(result[1]))
    return str(result), dict(session.word_confidence)


def run_case(case: dict[str, Any], base: dict[str, Any]) -> dict[str, Any]:
    from knight_flow.name_repair import unsure_words
    from knight_flow.text_pipeline import process_dictation
    from tests.commandment_battery import case_config, classify

    config = case_config({**case, "context": {k: v for k, v in (case.get("context") or {}).items()
                                              if k not in {"audio", "history"}}}, base)
    dictionary = config.setdefault("dictionary", {})
    for key, value in HISTORY.get(case["id"], {}).items():
        dictionary[key] = list(dictionary.get(key) or []) + copy.deepcopy(value)
    started = time.perf_counter()
    raw, confidence = hear(compose(case["id"]), config)
    unsure = {word: value for word, value in confidence.items() if word in unsure_words(confidence)}
    if unsure:
        config["_asr_confidence"] = unsure
    produced = process_dictation(raw, config).text if raw.strip() else ""
    verdict = classify(case, produced, False)
    # Commandment 4 is about losing words, so count them apart from the
    # verdict: a synthetic voice's casing ("PeopleOps") is not a lost word.
    said = re.findall(r"[a-z0-9']+", case["expected"].lower())
    kept = re.findall(r"[a-z0-9']+", produced.lower())
    lost = [word for word in said if word not in kept]
    return {"id": case["id"], "critical": bool(case["critical"]), "heard": raw, "unsure": unsure,
            "produced": produced, "expected": case["expected"], "verdict": verdict, "lost": lost,
            "seconds": round(time.perf_counter() - started, 1)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--only", help="comma-separated case ids")
    parser.add_argument("--json", metavar="PATH", help="write every row here")
    args = parser.parse_args(argv)
    if sys.platform != "win32":
        print("the audio battery needs the Windows voice (System.Speech)")
        return 2
    os.environ.setdefault("TALK_DAT_PLAIN_CLIPBOARD", "1")
    from tests.commandment_battery import FAILING_HARD, PASSING, load_cases
    from tests.parity_battery import local_config

    wanted = set(args.only.split(",")) if args.only else set(SCRIPTS)
    cases = [case for case in load_cases() if case["id"] in wanted and case["id"] in SCRIPTS]
    base = local_config(None)
    rows = []
    for case in cases:
        row = run_case(case, base)
        rows.append(row)
        mark = "PASS" if row["verdict"] in PASSING else row["verdict"].upper()
        print(f"{row['id']:9} {mark:10} {row['seconds']:5.1f}s  heard={row['heard']!r}  produced={row['produced']!r}"
              + (f"  unsure={row['unsure']}" if row["unsure"] else "")
              + (f"  LOST={row['lost']}" if row["lost"] else ""))
    passed = sum(row["verdict"] in PASSING for row in rows)
    # The main battery's rule: a critical case fails on words, keys or an error.
    critical = [row["id"] for row in rows if row["critical"] and row["verdict"] in FAILING_HARD]
    print(f"\n{passed}/{len(rows)} pass; critical failures: {critical or 'none'}")
    if args.json:
        Path(args.json).write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")
    return 1 if critical else 0


if __name__ == "__main__":
    raise SystemExit(main())
