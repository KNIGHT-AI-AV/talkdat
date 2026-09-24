"""Render the checked model catalog into maintainable product documentation."""

from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from knight_flow.model_catalog import (
    CLOUD_MODEL_CATALOG,
    LOCAL_MODEL_CATALOG,
    MODEL_CATALOG_VERIFIED_ON,
    ModelCatalogEntry,
)


OUTPUT = ROOT / "docs" / "MODEL_CATALOG.md"


def _table(entries: tuple[ModelCatalogEntry, ...]) -> str:
    rows = ["| # | Model | Provider | Mode | Availability | Official docs |", "| ---: | --- | --- | --- | --- | --- |"]
    for index, entry in enumerate(entries, start=1):
        availability = "Works now" if entry.status == "wired" else "Adapter pending"
        rows.append(
            f"| {index} | {entry.label} | {entry.provider} | {entry.mode} | "
            f"{availability} | [Docs]({entry.docs_url}) |"
        )
    return "\n".join(rows)


def render() -> str:
    return f"""# Current Speech Model Catalog

Verified: **{MODEL_CATALOG_VERIFIED_ON}**

This is Talk Dat!'s maintained research index, not a claim that every listed
model is bundled. **Works now** means a tested Talk Dat! adapter or packaged
Windows runtime exists. **Adapter pending** means the model is current and worth
tracking, but the app will not advertise it as runnable until its authentication,
request protocol, packaging, recovery behavior, and clean-PC tests pass.

The order is a best-first shortlist informed by current Artificial Analysis
streaming and non-streaming results, official model lifecycle documentation,
latency, language coverage, cost, and Talk Dat!'s short-form dictation workload.
It is not a universal rank: streaming and batch results are not interchangeable.

Benchmark references: [streaming](https://artificialanalysis.ai/speech-to-text/streaming)
and [non-streaming](https://artificialanalysis.ai/speech-to-text/non-streaming).

The links below point to provider-owned or model-owner documentation. Talk Dat!
does not copy entire third-party manuals into the repository because copied
documentation becomes stale and may be copyrighted.

## Cloud And Hosted Models (30)

{_table(CLOUD_MODEL_CATALOG)}

## Local And Open-Weight Models (30)

{_table(LOCAL_MODEL_CATALOG)}

## Product Defaults

- **Local speech:** Parakeet TDT 0.6B v3. It is packaged through the tested
  ONNX runtime, works well on ordinary CPUs, and downloads once for offline use.
- **Local formatting:** Qwen3 1.7B through Ollama. On Talk Dat!'s exact
  meaning-preservation suite it was faster and safer than the locally tested
  Qwen3.5 2B and 4B models, so a newer release number did not earn the default.
- **Bring your own cloud:** Deepgram Nova-3 remains the mature low-latency live
  route. ElevenLabs Scribe v2 remains the leading managed batch-quality route.

## Lifecycle Rules

1. Retired model IDs are removed from the picker, not silently rerouted.
2. Advanced users can still type a custom model ID for compatible endpoints.
3. A catalog entry becomes `wired` only after request-level tests and a real
   Windows runtime or provider smoke test pass.
4. New local runtimes must preserve protected-audio recovery and meaning-safe
   formatting before becoming a default.
5. The catalog date must change whenever any model, status, or lifecycle claim
   changes.
"""


if __name__ == "__main__":
    OUTPUT.write_text(render(), encoding="utf-8")
    print(OUTPUT)
