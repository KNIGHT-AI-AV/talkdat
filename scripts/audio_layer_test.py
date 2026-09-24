"""X-68 part two: the 100-clip audio test, runnable end to end.

One hundred synthetic vocal clips (Windows TTS, two voices, five speaking
rates -- ground truth exact by construction) go through the top two funded
cloud STT lanes -- Deepgram nova-3 direct and MAI-Transcribe over
OpenRouter -- and every transcript is scored twice against the truth:
RAW, and through the app's own deterministic adjustment layer
(`smart_format(..., local_only=True)`, the rules that always run).

The question his order asked -- "do we even need the adjustment layer" --
is answered as delta-WER per lane. Keys are read from the app's own BYOK
config and never printed.

Usage:
    python scripts/audio_layer_test.py --clips-dir <dir> [--generate]
"""
from __future__ import annotations

import argparse
import io
import json
import statistics
import subprocess
import sys
import urllib.request
import uuid
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from knight_flow.config import load_config  # noqa: E402
from knight_flow.formatting import smart_format  # noqa: E402

SENTENCES = [
    "The quarterly numbers land on Friday at nine thirty.",
    "Send the invoice to build at knight A I A V dot com.",
    "Talk DAT takes dictation on this machine without the internet.",
    "I am going to need three copies by tomorrow morning.",
    "The launch moved from March seventh to April twelfth.",
    "Our revenue grew twenty two percent quarter over quarter.",
    "Pack my box with five dozen liquor jugs.",
    "She sells seashells by the seashore every summer.",
    "The meeting starts at half past two in conference room B.",
    "Please schedule a follow up call for next Thursday.",
    "He paid forty nine dollars and ninety nine cents for it.",
    "The password reset link expires in fifteen minutes.",
    "Turn the volume down to about one third of maximum.",
    "The recipe calls for two cups of flour and one egg.",
    "Flight two two seven departs from gate fourteen at noon.",
    "The temperature dropped to minus five degrees overnight.",
    "Their new office is at one twenty five Market Street.",
    "I will forward the contract after legal signs off.",
    "The update rolls out to ten percent of users first.",
    "Remember to back up the database before the migration.",
]
RATES = (-3, -1, 0, 1, 3)


def generate_clips(clips_dir: Path) -> list[dict]:
    clips_dir.mkdir(parents=True, exist_ok=True)
    manifest: list[dict] = []
    script_lines = [
        "Add-Type -AssemblyName System.Speech",
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer",
        "$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)",
        "$voices = $s.GetInstalledVoices() | ForEach-Object { $_.VoiceInfo.Name }",
    ]
    index = 0
    for sentence_index, sentence in enumerate(SENTENCES):
        for rate in RATES:
            index += 1
            name = f"clip{index:03d}.wav"
            voice_pick = sentence_index % 2
            manifest.append({"file": name, "truth": sentence})
            escaped = sentence.replace("'", "''")
            script_lines += [
                f"$s.SelectVoice($voices[{voice_pick} % $voices.Count])",
                f"$s.Rate = {rate}",
                f"$s.SetOutputToWaveFile('{clips_dir / name}', $fmt)",
                f"$s.Speak('{escaped}')",
            ]
    script_lines.append("$s.Dispose()")
    script = clips_dir / "generate.ps1"
    script.write_text("\n".join(script_lines), encoding="utf-8")
    subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
        check=True, capture_output=True, timeout=900,
    )
    (clips_dir / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return manifest


def wer(truth: str, hypothesis: str) -> float:
    def tokens(value: str) -> list[str]:
        return [t for t in "".join(c.lower() if c.isalnum() or c.isspace() else " " for c in value).split() if t]

    reference, candidate = tokens(truth), tokens(hypothesis)
    if not reference:
        return 0.0
    previous = list(range(len(candidate) + 1))
    for row, ref_token in enumerate(reference, 1):
        current = [row] + [0] * len(candidate)
        for column, cand_token in enumerate(candidate, 1):
            cost = 0 if ref_token == cand_token else 1
            current[column] = min(previous[column] + 1, current[column - 1] + 1, previous[column - 1] + cost)
        previous = current
    return previous[-1] / len(reference)


def deepgram_transcribe(key: str, audio: bytes) -> str:
    request = urllib.request.Request(
        "https://api.deepgram.com/v1/listen?model=nova-3&smart_format=false",
        data=audio,
    )
    request.add_header("Authorization", f"Token {key}")
    request.add_header("Content-Type", "audio/wav")
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.load(response)
    return str(payload["results"]["channels"][0]["alternatives"][0]["transcript"])


def openrouter_transcribe(key: str, audio: bytes, model: str) -> str:
    boundary = uuid.uuid4().hex
    body = io.BytesIO()
    for field_name, value in (("model", model),):
        body.write(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field_name}\"\r\n\r\n{value}\r\n".encode())
    body.write(f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"clip.wav\"\r\nContent-Type: audio/wav\r\n\r\n".encode())
    body.write(audio)
    body.write(f"\r\n--{boundary}--\r\n".encode())
    request = urllib.request.Request("https://openrouter.ai/api/v1/audio/transcriptions", data=body.getvalue())
    request.add_header("Authorization", f"Bearer {key}")
    request.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    with urllib.request.urlopen(request, timeout=90) as response:
        payload = json.load(response)
    return str(payload.get("text", ""))


def resolve_mai_slug(key: str) -> str:
    """The slug commerce ships (microsoft/mai-transcribe-1.5) is the pin;
    the catalog -- queried WITH the transcription modality, which the plain
    listing omits -- only confirms it still exists."""
    pinned = "microsoft/mai-transcribe-1.5"
    try:
        request = urllib.request.Request(
            "https://openrouter.ai/api/v1/models?output_modalities=transcription"
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            catalog = json.load(response)["data"]
        ids = {entry["id"] for entry in catalog}
        if pinned in ids:
            return pinned
        matches = sorted(entry for entry in ids if "mai-transcribe" in entry)
        if matches:
            return matches[0]
    except Exception:
        pass
    return pinned


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--clips-dir", required=True)
    parser.add_argument("--generate", action="store_true")
    parser.add_argument("--out", default="audio_layer_results.json")
    args = parser.parse_args()
    clips_dir = Path(args.clips_dir)
    if args.generate:
        manifest = generate_clips(clips_dir)
        print(f"generated {len(manifest)} clips")
    manifest = json.loads((clips_dir / "manifest.json").read_text(encoding="utf-8"))

    config = load_config()
    providers = config.get("stt", {}).get("providers", {})
    deepgram_key = str(providers.get("deepgram", {}).get("api_key", "")).strip()
    openrouter_key = str(providers.get("openrouter", {}).get("api_key", "")).strip()
    lanes: dict = {}
    if deepgram_key:
        lanes["deepgram nova-3"] = lambda audio: deepgram_transcribe(deepgram_key, audio)
    if openrouter_key:
        try:
            mai_slug = resolve_mai_slug(openrouter_key)
            print("mai slug:", mai_slug)
            lanes[f"openrouter {mai_slug}"] = lambda audio: openrouter_transcribe(openrouter_key, audio, mai_slug)
        except Exception as error:
            print("openrouter lane skipped:", error)
    if not lanes:
        raise SystemExit("no funded STT lane has a key in the app config")

    results: dict = {}
    for lane_name, transcribe in lanes.items():
        raw_wers: list[float] = []
        layered_wers: list[float] = []
        failures = 0
        for entry in manifest:
            audio = (clips_dir / entry["file"]).read_bytes()
            try:
                transcript = transcribe(audio)
            except Exception as error:
                failures += 1
                if failures <= 3:
                    print(f"  {lane_name} failed on {entry['file']}: {error}")
                continue
            layered = smart_format(transcript, config, local_only=True)
            raw_wers.append(wer(entry["truth"], transcript))
            layered_wers.append(wer(entry["truth"], layered))
        results[lane_name] = {
            "clips": len(raw_wers),
            "failures": failures,
            "wer_raw": round(statistics.mean(raw_wers), 4) if raw_wers else None,
            "wer_with_layer": round(statistics.mean(layered_wers), 4) if layered_wers else None,
        }
        print(lane_name, results[lane_name])
    Path(args.out).write_text(json.dumps(results, indent=1), encoding="utf-8")
    print("wrote", args.out)


if __name__ == "__main__":
    main()
