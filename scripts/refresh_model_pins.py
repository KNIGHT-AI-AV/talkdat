"""Re-read the current commit of every bundled Whisper repo and print the table.

Run this when a model is added to LOCAL_MODELS, or deliberately to move to a
newer upstream build. It PRINTS rather than edits: bumping a pin means shipping
different weights to everyone, which is a decision somebody should make on
purpose and see in a diff, not a thing a script does on its own.

    python scripts/refresh_model_pins.py

Paste the output over _PINNED_REVISIONS in knight_flow/local_stt.py.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from faster_whisper.utils import _MODELS  # noqa: E402

from knight_flow.local_stt import LOCAL_MODELS, _PINNED_REVISIONS  # noqa: E402


def current_sha(repo: str) -> str:
    url = f"https://huggingface.co/api/models/{repo}"
    with urllib.request.urlopen(url, timeout=30) as response:
        return json.load(response).get("sha", "")


def main() -> int:
    rows: list[str] = []
    changed: list[str] = []
    failed: list[str] = []

    for model in LOCAL_MODELS:
        if model.engine != "faster_whisper":
            continue
        repo = _MODELS.get(model.engine_id)
        if not repo:
            failed.append(f"{model.engine_id}: faster-whisper has no repo for this name")
            continue
        try:
            sha = current_sha(repo)
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            failed.append(f"{model.engine_id}: {error}")
            continue
        if not sha:
            failed.append(f"{model.engine_id}: the Hub returned no sha")
            continue
        rows.append(f'    "{model.engine_id}": "{sha}",  # {repo}')
        was = _PINNED_REVISIONS.get(model.engine_id)
        if was != sha:
            changed.append(f"  {model.engine_id}: {was or '(unpinned)'} -> {sha}")

    print("_PINNED_REVISIONS: dict[str, str] = {")
    for row in rows:
        print(row)
    print("}")

    if changed:
        print("\nCHANGED -- read these before pasting:", file=sys.stderr)
        for line in changed:
            print(line, file=sys.stderr)
    else:
        print("\nEvery pin still matches upstream.", file=sys.stderr)

    if failed:
        print("\nCOULD NOT RESOLVE -- the table above is incomplete:", file=sys.stderr)
        for line in failed:
            print(f"  {line}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
