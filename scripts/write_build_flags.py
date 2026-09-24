"""Write knight_flow/_build_flags.py: is this build OFFICIAL or from SOURCE?

Run by build-exe.ps1 (and build-mac.sh) immediately before PyInstaller, so the
answer is baked into the app. See knight_flow/official_build.py for what the
flag switches.

    python scripts/write_build_flags.py            # write, print the decision
    python scripts/write_build_flags.py --show     # print it, write nothing
    python scripts/write_build_flags.py --clean    # delete the generated module
    python scripts/write_build_flags.py --require-official [--not-before EPOCH]
                                                   # exit 1 unless the receipt is an
                                                   # OFFICIAL build of this version

The decision, in order:

1. ``TALKDAT_OFFICIAL_BUILD=1`` or ``=0`` in the environment decides outright.
2. Otherwise a checkout that carries Knight AI+AV's private release tooling
   (``scripts/publish_release.py``) builds OFFICIAL, and every other checkout,
   including the public open-source repository, builds from SOURCE.

A fork can bake endpoints of its own with ``TALKDAT_BUILD_API_BASE`` and
``TALKDAT_BUILD_UPDATE_REPOSITORY``.

It also writes ``build/talk-dat-build-flags.json``, a receipt the publish step
reads: ``publish_release.py`` refuses to ship a build whose receipt does not
say official, because a release that silently lost sign-in and updates would
reach every customer before anyone noticed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FLAGS_PATH = ROOT / "knight_flow" / "_build_flags.py"
RECEIPT_PATH = ROOT / "build" / "talk-dat-build-flags.json"
PRIVATE_RELEASE_TOOL = ROOT / "scripts" / "publish_release.py"

sys.path.insert(0, str(ROOT))


def decide(env: dict[str, str] | None = None, root: Path = ROOT) -> tuple[bool, str]:
    """(official, reason). Pure, so the rule is testable without a build."""
    env = dict(os.environ if env is None else env)
    raw = str(env.get("TALKDAT_OFFICIAL_BUILD", "")).strip().lower()
    if raw in {"1", "true", "yes", "official"}:
        return True, "TALKDAT_OFFICIAL_BUILD=1"
    if raw in {"0", "false", "no", "source"}:
        return False, "TALKDAT_OFFICIAL_BUILD=0"
    if (root / "scripts" / "publish_release.py").exists():
        return True, "this checkout carries Knight AI+AV's release tooling"
    return False, "a build from source (no release tooling in this checkout)"


def write(env: dict[str, str] | None = None, root: Path = ROOT) -> dict[str, object]:
    from knight_flow.official_build import render_build_flags
    from knight_flow.version import APP_VERSION

    env = dict(os.environ if env is None else env)
    official, reason = decide(env, root)
    api_base = str(env.get("TALKDAT_BUILD_API_BASE", "")).strip()
    repository = str(env.get("TALKDAT_BUILD_UPDATE_REPOSITORY", "")).strip()
    flags_path = root / "knight_flow" / "_build_flags.py"
    flags_path.write_text(
        render_build_flags(official=official, api_base=api_base, update_repository=repository),
        encoding="utf-8",
        newline="\n",
    )
    receipt = {
        "official": official,
        "reason": reason,
        "version": APP_VERSION,
        "api_base": api_base,
        "update_repository": repository,
        "written_at": int(time.time()),
    }
    receipt_path = root / "build" / "talk-dat-build-flags.json"
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt


def receipt_problem(receipt: object, version: str, *, not_before: int = 0) -> str:
    """Why this receipt is NOT an official build of ``version``, or "" when it is.

    The Mac release path asks this (build-mac.sh --notarize, and
    scripts/build_mac_remote.py before it notarizes or brings a dmg home), the
    counterpart of publish_release.require_official_build on Windows. Pure, so
    tests/test_mac_release_refuses_a_source_build.py can hold the two rules
    together. ``not_before`` is the moment the build started: a receipt written
    earlier belongs to some other build and says nothing about this one.
    """
    if not isinstance(receipt, dict):
        return "there is no readable build-flags receipt"
    if receipt.get("official") is not True:
        return (f"the app was built as a SOURCE build ({receipt.get('reason', 'unknown reason')}); "
                "sign-in, updates and counts are switched off in it")
    if str(receipt.get("version") or "") != str(version):
        return f"the build-flags receipt is for {receipt.get('version')!r}, not {version}"
    try:
        written = int(receipt.get("written_at") or 0)
    except (TypeError, ValueError):
        written = 0
    if not_before and written < int(not_before):
        return "the build-flags receipt predates this build; it describes an earlier one"
    return ""


def endpoint_override_problem(receipt: object) -> str:
    """Knight's own releases never carry build-time endpoint overrides (the same
    rule publish_release.require_official_build applies). A fork's official
    build may; that is why this is separate from receipt_problem()."""
    if isinstance(receipt, dict) and (receipt.get("api_base") or receipt.get("update_repository")):
        return ("this official build had endpoints overridden at build time "
                "(TALKDAT_BUILD_API_BASE / TALKDAT_BUILD_UPDATE_REPOSITORY)")
    return ""


def clean(root: Path = ROOT) -> bool:
    path = root / "knight_flow" / "_build_flags.py"
    if path.exists():
        path.unlink()
        return True
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--show", action="store_true", help="print official or source; write nothing")
    group.add_argument("--clean", action="store_true", help="delete knight_flow/_build_flags.py")
    group.add_argument("--require-official", action="store_true",
                       help="exit 1 unless the last build's receipt is an OFFICIAL build of this version")
    parser.add_argument("--not-before", type=int, default=0,
                        help="with --require-official: the build's start time (epoch seconds)")
    args = parser.parse_args(argv)
    if args.clean:
        clean()
        return 0
    if args.require_official:
        from knight_flow.version import APP_VERSION

        try:
            receipt = json.loads(RECEIPT_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            receipt = None
        problem = receipt_problem(receipt, APP_VERSION, not_before=args.not_before)
        if problem:
            print(f"REFUSED: {problem}.", file=sys.stderr)
            print("A release must be an OFFICIAL build. Build from the private release checkout, "
                  "or with TALKDAT_OFFICIAL_BUILD=1.", file=sys.stderr)
            return 1
        print(f"build flags: OFFICIAL build of {APP_VERSION} ({RECEIPT_PATH.name})")
        return 0
    if args.show:
        # The receipt of the last build wins: it says what the payload on disk
        # actually carries, which is what signing decisions are about.
        if RECEIPT_PATH.exists():
            try:
                official = bool(json.loads(RECEIPT_PATH.read_text(encoding="utf-8")).get("official"))
                print("official" if official else "source")
                return 0
            except (OSError, ValueError):
                pass
        official, _reason = decide()
        print("official" if official else "source")
        return 0
    receipt = write()
    kind = "OFFICIAL" if receipt["official"] else "SOURCE"
    print(f"build flags: {kind} build ({receipt['reason']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
