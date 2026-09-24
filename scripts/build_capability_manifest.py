"""Freeze the app's reachable surface into tests/capability_manifest.json.

X-157. The manifest is the "nothing gets lost" contract for the menu and
onboarding rework: the test compares today's source against it and fails on
anything that DISAPPEARS. Additions are free; removals must be deliberate.

Run this ONLY when a capability is intentionally retired or renamed, and say
which one in the commit. Running it to make a red test go green defeats the
entire mechanism -- that is the one thing this file must never be used for.

    python scripts/build_capability_manifest.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from capability_crosswalk import snapshot  # noqa: E402

MANIFEST = ROOT / "tests" / "capability_manifest.json"


def main() -> int:
    current = snapshot()
    previous: dict[str, list[str]] = {}
    if MANIFEST.exists():
        previous = json.loads(MANIFEST.read_text(encoding="utf-8")).get("capabilities", {})

    removed: dict[str, list[str]] = {}
    for group, items in previous.items():
        gone = [item for item in items if item not in set(current.get(group, []))]
        if gone:
            removed[group] = gone

    if removed:
        print("This rewrite DROPS capabilities. Confirm every line is intended:")
        for group, gone in sorted(removed.items()):
            for item in gone:
                print(f"  - {group}: {item}")
        print()

    payload = {
        "note": (
            "Frozen surface of the desktop app. tests/test_capability_crosswalk.py "
            "fails if anything here stops being reachable. Regenerate ONLY when a "
            "capability is deliberately retired, and name it in the commit."
        ),
        "capabilities": current,
    }
    MANIFEST.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    total = sum(len(v) for v in current.values())
    print(f"wrote {MANIFEST.relative_to(ROOT)} with {total} capabilities across {len(current)} groups")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
