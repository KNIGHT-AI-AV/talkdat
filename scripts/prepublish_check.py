from __future__ import annotations

import os
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

BANNED_TOP_LEVEL = {
    ".playwright-cli",
    ".serena",
    ".uv-cache",
    ".uv-python",
    ".venv",
    "build",
    "build-mac",
    "dist",
    "dist-mac",
    ".expo",
    "node_modules",
    "release",
}

SKIP_DIRS = {
    ".git",
    ".idea",
    ".mypy_cache",
    ".pytest_cache",
    ".playwright-cli",
    ".ruff_cache",
    ".serena",
    ".uv-cache",
    ".uv-python",
    ".venv",
    ".vscode",
    "__pycache__",
    "build",
    "build-mac",
    "dist",
    "dist-mac",
    ".expo",
    "node_modules",
    "release",
}

# X-205: this list decides what the secret scanner can SEE, and what it could
# not see was the entire payment backend.
#
# Every source file of the commerce service is .mjs -- server, service,
# license, cloud, firestore-store, funnel, captions-stream -- and ".mjs" was
# absent, so the scan walked past all of them and reported a clean tree. 53
# tracked files were skipped in total, including the web demo's server, the
# mobile app, the iOS keyboard's Swift, the website deploy script, and
# firestore.rules.
#
# The ".env" entry was dead code for the same reason it looked correct:
# Path(".env").suffix is "" , not ".env", so a real .env on disk was never
# scanned despite the obvious intent. Name-matched below instead.
TEXT_EXTENSIONS = {
    ".cfg",
    ".cjs",
    ".css",
    ".example",
    ".gitattributes",
    ".gitignore",
    ".html",
    ".ini",
    ".iss",
    ".js",
    ".json",
    ".md",
    ".mjs",
    ".p8",
    ".pem",
    ".plist",
    ".ps1",
    ".py",
    ".rules",
    ".sh",
    ".swift",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".xml",
    ".yml",
    ".yaml",
}

# Public identifiers that look like credentials but are not (a browser API key
# that every client embeds, say), allowed by EXACT match in the scan below.
#
# 2026-09-23, open source: this used to be a literal Firebase web key. Nothing
# in the tree carries that key any more, and a project identifier has no
# business in a file that is published, so the allow-list now comes from the
# environment: TALKDAT_PREPUBLISH_ALLOW="value1,value2". Empty by default.
PUBLIC_IDENTIFIERS = tuple(
    value.strip()
    for value in os.environ.get("TALKDAT_PREPUBLISH_ALLOW", "").split(",")
    if value.strip()
)

# X-205: a credential has ENTROPY. A placeholder is words joined by hyphens.
#
# Widening the scanner to the backend (above) also pointed it at the test
# suites, which are full of deliberately fake values -- "inference-key-test",
# "token-secret-which-is-at-least-thirty-two-bytes-long" -- and at constants
# whose VALUE is a key NAME, like "talkdat.licenseToken" or the GitHub secret
# id FIREBASE_SERVICE_ACCOUNT_KNIGHT_AI_AV_SITE.
#
# The tempting fix is to skip test directories. That would re-blind the scanner
# to most of the code it was just taught to see, and a leaked key committed
# into a fixture is a leaked key.
#
# So discriminate on shape instead. Every real credential this project can leak
# -- an OpenRouter sk-or-v1, a 40-char Deepgram key, a Google AIza..., a Stripe
# sk_live_, a JWT segment -- contains an unbroken run of 16+ alphanumerics.
# Placeholders are readable words, and readable words are short. The two other
# patterns below still catch long hex and bearer tokens regardless of shape.
PLACEHOLDER_RUN = 16
UNBROKEN_RUN = re.compile(r"[A-Za-z0-9]{%d,}" % PLACEHOLDER_RUN)


def looks_like_a_placeholder(value: str) -> bool:
    """True when a quoted value has no run long enough to be a real secret."""
    return UNBROKEN_RUN.search(value) is None


SECRET_PATTERNS = (
    ("non-placeholder api key assignment", re.compile(r'(?i)(api[_ -]?key|secret|token|password)\s*[:=]\s*["\'](?!your-|put-your|<|$)([^"\']{12,})["\']')),
    ("long hex token", re.compile(r"(?<![a-fA-F0-9])[a-fA-F0-9]{40,128}(?![a-fA-F0-9])")),
    ("bearer token", re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]{20,}")),
)


# X-237: a pinned Hugging Face commit is not a credential.
#
# A git commit sha is a content address on a PUBLIC repository -- it is
# published, it identifies rather than authorises, and it is worthless to
# anyone who steals it. By shape alone it is indistinguishable from a 40-char
# hex API key, so "long hex token" flags it and is right to.
#
# The exemption is deliberately matched on the whole LINE, not on a file path.
# Allowlisting knight_flow/local_stt.py would exempt every hex string anyone
# ever puts in that file, including a real key pasted there next year. This
# matches only the pin table's exact shape:
#
#     "large-v3": "edaa852...478",  # Systran/faster-whisper-large-v3
#
# 40 lowercase hex (git's length, not the 32 or 64 typical of keys), quoted as
# a dict value, with a trailing comment naming the repo it came from.
PUBLIC_COMMIT_PIN = re.compile(
    r'^\s*"[\w.\-]+"\s*:\s*"[0-9a-f]{40}"\s*,\s*#\s*[\w.\-]+/[\w.\-]+\s*$'
)


# X-476: a pinned PyPI wheel checksum is not a credential either.
#
# Exactly the reasoning above, one artefact along. `--require-hashes` exists
# because a published sha256 is how you prove a download is the file you meant;
# it identifies rather than authorises, it is printed on PyPI, and it is
# worthless to anyone who copies it. requirements.lock is full of them and only
# escapes this scan because ".lock" is not a scanned extension.
#
# Two shapes, both matched on the whole LINE and both REQUIRING a naming
# comment, so a bare 64-char hex string pasted into that file still fails:
#
#     "623f4302...0661",  # sha256 nvidia_cublas_cu12
#     "fc9a0e98...05ed/"          <- a pypi path segment, part of a split URL
PUBLIC_WHEEL_CHECKSUM = re.compile(
    r'^\s*"[0-9a-f]{64}",\s*#\s*sha256\s+[\w.\-]+\s*$'
)
PUBLIC_PYPI_URL_SEGMENT = re.compile(
    r'^\s*"[0-9a-f]{20,64}/"\s*$'
)
# Upstream source commits the written source offer must cite exactly (GPL
# obligation for the FFmpeg build inside PyAV). Public identifiers, allowed by
# EXACT value only, so any other 40-hex string on the same line still fails.
PUBLIC_SOURCE_COMMITS = frozenset({
    "b35605ace3ddf7c1a5d67a2eb553f034aef41d55",  # x264, pinned by pyav-ffmpeg 8.1.2-1
})


def is_text_file(path: Path) -> bool:
    if path.name in {".gitignore", ".gitattributes"}:
        return True
    # ".env", ".env.local", ".env.production" -- a dotfile has no suffix, so
    # suffix matching can never reach the one family of files most likely to
    # hold a live credential.
    if path.name == ".env" or path.name.startswith(".env."):
        return True
    return path.suffix.lower() in TEXT_EXTENSIONS


def iter_repo_files() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        parts = path.relative_to(ROOT).parts[:-1]
        # .venv matched by prefix: the Mac packaging env is .venv-dmg, and any
        # future variant is still a virtualenv full of third-party hex.
        if any(part in SKIP_DIRS or part.startswith(".venv") for part in parts):
            continue
        # Raw research captures (scraped posts, ids that look like hex) are data
        # the marketing session keeps under version control, not shipped code;
        # the secret scanner has nothing to find there and everything to trip on.
        if parts[:3] == ("marketing", "research", "raw"):
            continue
        if path.is_file():
            files.append(path)
    return files


def main() -> int:
    failures: list[str] = []
    warnings: list[str] = []

    for name in sorted(BANNED_TOP_LEVEL):
        if (ROOT / name).exists():
            warnings.append(f"ignored generated/local folder exists: {name}/")

    for path in iter_repo_files():
        relative = path.relative_to(ROOT)
        if path.name.startswith("tmp-"):
            failures.append(f"temporary file exists: {relative}")
        if not is_text_file(path):
            continue
        try:
            text = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            if "PUT-YOUR-" in line or "your-key-here" in line or "your_api_key" in line:
                continue
            if re.search(r"\bCROSS_THREAD_TOKEN\s*=", line):
                # Internal Tk callback marker, not an authentication token.
                continue
            if re.match(r"\s*InstallerSha256\s*:", line):
                # WinGet requires the public installer digest in its manifest.
                continue
            if "**Source lock:**" in line:
                # The feature catalog deliberately pins a public Git commit.
                continue
            if any(identifier in line for identifier in PUBLIC_IDENTIFIERS):
                # A browser API key (Firebase's, for one) is a public project
                # identifier, not a credential: it is embedded in every client.
                # Exact-match only, so any other key-shaped string still fails.
                continue
            for label, pattern in SECRET_PATTERNS:
                found = pattern.search(line)
                if not found:
                    continue
                # Only the assignment pattern captures a value to judge; the
                # other two match the secret itself and are shape-checked
                # already by their own expressions.
                if found.lastindex == 2 and looks_like_a_placeholder(found.group(2)):
                    continue
                if label == "long hex token" and (
                    PUBLIC_COMMIT_PIN.match(line)
                    or PUBLIC_WHEEL_CHECKSUM.match(line)
                    or PUBLIC_PYPI_URL_SEGMENT.match(line)
                    or all(
                        token in PUBLIC_SOURCE_COMMITS
                        for token in re.findall(r"(?<![a-fA-F0-9])[a-fA-F0-9]{40,128}(?![a-fA-F0-9])", line)
                    )
                ):
                    continue
                failures.append(f"{label}: {relative}:{line_number}")

    if failures:
        print("Prepublish check failed:")
        for failure in failures:
            print(f"- {failure}")
        if warnings:
            print("\nWarnings:")
            for warning in warnings:
                print(f"- {warning}")
        return 1

    if warnings:
        print("Prepublish check passed with warnings:")
        for warning in warnings:
            print(f"- {warning}")
        print("These paths are ignored by git, but delete them before creating source archives by hand.")
        return 0

    print("Prepublish check passed. No obvious local artifacts or key-shaped secrets found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
