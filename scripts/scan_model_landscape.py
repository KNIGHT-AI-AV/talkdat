"""X-479: watch the model landscape weekly and hand development a queue.

His ask: a weekly scan for new models, for OAuth and key plans that improve
what people can bring their own key to, and for local models worth adding, all
researched and written down so a later version can implement them.

Talk DAT! is local first, and after his call it is local or bring your own key
with nothing in between. That makes this scan the thing that keeps both halves
current: which local engines are worth shipping, and which providers are worth
letting somebody point their own key at.

WHAT IT CAN SEE, and it only reports what it actually read:

  * OpenRouter's catalogue, which is the single best view of what a
    bring-your-own-key user could reach, with prices and modalities. Free to
    list, and this account already has a key.
  * Hugging Face, for speech models. Filtered to ONNX, because that is the
    runtime Talk DAT! actually has: a PyTorch-only model is not a candidate
    however good it is, and saying otherwise would waste the next person's
    week. That lesson is X-474 and X-476, both learned the hard way.

WHAT IT CANNOT SEE, and says so rather than inventing:

  * Artificial Analysis. Its API returns 401 without a key and this machine
    has none. The scan prints exactly which variable to set rather than
    scraping a page whose shape will change, because a silently wrong
    accuracy number is worse than an absent one.

NEW MEANS NEW. State is kept between runs, so the report is a diff and not a
catalogue dump nobody reads twice.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

STATE = ROOT / "docs" / "model-watch-state.json"
REPORT = ROOT / "docs" / "MODEL_WATCH.md"

# What Talk DAT! can actually load today. A candidate outside these is
# research, not a shipping option, and the report says which is which.
RUNNABLE_LOCALLY = ("onnx",)


def fetch(url: str, token: str = "", timeout: int = 60) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": "talk-dat-model-watch"})
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def openrouter_catalogue() -> tuple[list[dict], str]:
    """Everything a bring-your-own-key user could point at."""
    try:
        data = fetch("https://openrouter.ai/api/v1/models")
    except Exception as error:  # noqa: BLE001
        return [], f"{type(error).__name__}: {error}"
    return data.get("data", []), ""


def huggingface_speech(limit: int = 60) -> tuple[list[dict], str]:
    """Speech recognition models, most downloaded first, ONNX only.

    Filtered to the runtime we HAVE. X-474 spent a day on two models that were
    in our own catalogue and could not load; shipping a list of candidates the
    app cannot run would repeat that at scale.
    """
    url = (
        "https://huggingface.co/api/models"
        "?filter=automatic-speech-recognition&filter=onnx"
        f"&sort=downloads&direction=-1&limit={limit}"
    )
    try:
        return fetch(url), ""
    except Exception as error:  # noqa: BLE001
        return [], f"{type(error).__name__}: {error}"


def artificial_analysis() -> tuple[list[dict], str]:
    """Independent accuracy and speed measurements, if we have a key.

    Deliberately not scraped. A number here would be used to choose what to
    ship, and a wrong one taken from a page whose markup changed is worse than
    no number at all.
    """
    token = os.environ.get("ARTIFICIAL_ANALYSIS_API_KEY", "").strip()
    if not token:
        return [], (
            "no key. Set ARTIFICIAL_ANALYSIS_API_KEY to include independent "
            "accuracy and speed rankings; without it this scan reports what is "
            "AVAILABLE but not what is BEST."
        )
    try:
        data = fetch("https://artificialanalysis.ai/api/v2/data/llms/models", token=token)
    except urllib.error.HTTPError as error:
        return [], f"HTTP {error.code} from Artificial Analysis"
    except Exception as error:  # noqa: BLE001
        return [], f"{type(error).__name__}: {error}"
    return data.get("data", data if isinstance(data, list) else []), ""


def our_byok_providers() -> set[str]:
    from knight_flow.stt_registry import PROVIDERS
    return {p.id for p in PROVIDERS}


def our_local_models() -> set[str]:
    from knight_flow.local_stt import LOCAL_MODELS
    return {m.engine_id for m in LOCAL_MODELS}


def main() -> int:
    state = load_state()
    seen_models = set(state.get("openrouter_ids", []))
    seen_speech = set(state.get("hf_speech_ids", []))

    models, models_error = openrouter_catalogue()
    speech, speech_error = huggingface_speech()
    rankings, rankings_error = artificial_analysis()

    transcription = [
        m for m in models
        if "transcription" in (m.get("architecture", {}).get("output_modalities") or [])
        or "audio" in (m.get("architecture", {}).get("input_modalities") or [])
    ]
    new_models = [m for m in models if m.get("id") not in seen_models]
    new_speech = [m for m in speech if m.get("id") not in seen_speech]

    ours_local = our_local_models()
    candidates = [m for m in speech if m.get("id") not in ours_local]

    lines: list[str] = []
    add = lines.append
    add("# Model watch")
    add("")
    add(f"Scanned {time.strftime('%Y-%m-%d %H:%M')}. Talk DAT! is local first, and "
        "local or bring your own key with nothing in between, so this watches "
        "both halves: what to ship on device, and what a person could point "
        "their own key at.")
    add("")
    add("## What this scan could reach")
    add("")
    add(f"- OpenRouter catalogue: **{len(models)} models**"
        + (f"  \n  FAILED: {models_error}" if models_error else ""))
    add(f"- Hugging Face speech, ONNX only: **{len(speech)} models**"
        + (f"  \n  FAILED: {speech_error}" if speech_error else ""))
    add(f"- Artificial Analysis rankings: **{len(rankings)}**"
        + (f"  \n  NOT READ: {rankings_error}" if rankings_error else ""))
    add("")
    if rankings_error:
        add("> Without Artificial Analysis this scan can say what EXISTS and what "
            "we could run, but not what is most accurate. That is the one gap "
            "worth closing, and it costs a key rather than any work.")
        add("")

    add("## New since the last scan")
    add("")
    add(f"- {len(new_models)} new on OpenRouter")
    add(f"- {len(new_speech)} new ONNX speech models on Hugging Face")
    add("")
    if new_speech:
        add("### Local speech candidates, newly seen")
        add("")
        add("ONNX only, because that is the runtime the app has. A PyTorch model "
            "is research, not a shipping option.")
        add("")
        for model in new_speech[:15]:
            add(f"- `{model.get('id')}` "
                f"({model.get('downloads', 0):,} downloads)")
        add("")

    add("## Bring your own key: what people could reach")
    add("")
    add(f"We wire **{len(our_byok_providers())} providers**. OpenRouter alone "
        f"exposes **{len(models)}** models behind one key, of which "
        f"**{len(transcription)}** handle audio.")
    add("")
    add("The interesting ones for us are audio-capable, since dictation is the "
        "product. Cheapest first, so the list is about what a person would "
        "actually turn on:")
    add("")
    priced = []
    for model in transcription:
        pricing = model.get("pricing", {}) or {}
        try:
            cost = float(pricing.get("prompt") or 0)
        except (TypeError, ValueError):
            cost = 0.0
        priced.append((cost, model.get("id", "?")))
    priced.sort()
    for cost, model_id in priced[:12]:
        add(f"- `{model_id}`" + (f"  ({cost})" if cost else "  (no listed prompt price)"))
    add("")
    add("> Prices are NOT comparable across models without normalising: "
        "OpenRouter's prompt field means per minute for one model, per hour or "
        "per token for another. Read the unit before quoting any of these.")
    add("")

    add("## What to hand development")
    add("")
    add("1. **Measure before adding.** Every candidate above is unproven on our "
        "runtime. The picker (X-478) already measures what is on disk; adding a "
        "model means downloading it once and letting the probe rank it.")
    add("2. **ONNX or it does not ship.** X-474 retired two catalogue models "
        "that could not load. Nothing joins the local list without a run.")
    add("3. **A key gets the accuracy half.** Set ARTIFICIAL_ANALYSIS_API_KEY "
        "and this report starts saying which of these is actually better, "
        "rather than only which exist.")
    add("")

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")

    save_state({
        "scanned_at": int(time.time()),
        "openrouter_ids": sorted({m.get("id", "") for m in models if m.get("id")}),
        "hf_speech_ids": sorted({m.get("id", "") for m in speech if m.get("id")}),
    })

    print(f"wrote {REPORT.relative_to(ROOT)}")
    print(f"  openrouter {len(models)} ({len(new_models)} new), "
          f"hf speech {len(speech)} ({len(new_speech)} new), "
          f"rankings {len(rankings)}")
    if rankings_error:
        print(f"  artificial analysis NOT READ: {rankings_error}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
