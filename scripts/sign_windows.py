"""X-321: sign Windows binaries with Azure Trusted Signing (Artifact Signing).

Official Talk DAT! releases are signed as Knight AI+AV LLC. Everything that
identifies the signing account -- tenant, client id and secret, endpoint,
account and certificate-profile names -- lives in an env file OUTSIDE every
repository (``~/.talkdat-signing/azure-signing.env`` by default, or the path in
``TALKDAT_SIGNING_ENV``), written once by the signing bootstrap and never
printed. This file names none of them.

The service principal needs the "Artifact Signing Certificate Profile Signer"
role (note the ARTIFACT rename -- the old "Trusted Signing ..." role name no
longer resolves), so signing is fully non-interactive.

The signer is the ``sign`` CLI at ``C:\\Tools\\sign\\sign.exe`` -- a
deliberately SPACE-FREE tool path. The TrustedSigning PowerShell module was
tried first and its internal tool-install breaks on a space in the Windows
user name (unquoted path); the CLI has no such bug.

Policy: FAIL CLOSED for releases. An unsigned release is the regression
SmartScreen punishes for weeks, so a missing env file or a failed signature
stops the publish (``publish_release.py`` calls ``sign_files`` directly).
``TALKDAT_SKIP_SIGNING=1`` is the documented emergency override (an Azure
outage must not strand a critical fix), and it says so loudly.

Building from source: ``build-custom-installer.ps1`` passes ``--if-configured``
for a SOURCE build, so a machine without signing credentials builds an
unsigned installer and says so, instead of failing. An OFFICIAL build never
passes it.

Trusted Signing certificates rotate daily under the hood; what persists
is the subject (the LLC) and the reputation attached to it. The RFC 3161
timestamp is what keeps a signature valid after the short-lived cert
expires -- never remove it.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ENV_FILE = Path(os.environ.get("TALKDAT_SIGNING_ENV") or Path.home() / ".talkdat-signing" / "azure-signing.env")
SIGN_CLI = Path(r"C:\Tools\sign\sign.exe")
SIGNTOOL = Path(r"C:\Program Files (x86)\Windows Kits\10\bin\10.0.26100.0\x64\signtool.exe")
TIMESTAMP_URL = "http://timestamp.acs.microsoft.com"


def _signing_env() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in ENV_FILE.read_text(encoding="ascii").splitlines():
        line = line.strip()
        if line and "=" in line and not line.startswith("#"):
            key, _, value = line.partition("=")
            values[key] = value
    missing = [k for k in ("AZURE_TENANT_ID", "AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET",
                           "TS_ENDPOINT", "TS_ACCOUNT", "TS_PROFILE") if not values.get(k)]
    if missing:
        raise SystemExit(f"signing env incomplete, missing: {', '.join(missing)} in {ENV_FILE}")
    return values


def sign_files(paths: list[Path]) -> bool:
    """Sign every path in place, then verify each with signtool.

    Raises SystemExit on any failure. Honours TALKDAT_SKIP_SIGNING=1.

    Returns True when the files were actually signed and False when signing
    was skipped, so the release receipt can state what happened instead of
    asserting a constant. The receipt used to hardcode "not signed" from
    before Trusted Signing existed, which made a provenance file wrong about
    the one thing it exists to record.
    """
    if os.environ.get("TALKDAT_SKIP_SIGNING") == "1":
        print("!! SIGNING SKIPPED by TALKDAT_SKIP_SIGNING=1 -- this release ships UNSIGNED", flush=True)
        return False
    if not ENV_FILE.exists():
        raise SystemExit(
            f"signing credentials missing: {ENV_FILE}\n"
            "Run the Trusted Signing bootstrap, or set TALKDAT_SKIP_SIGNING=1 for an emergency unsigned release."
        )
    for tool in (SIGN_CLI, SIGNTOOL):
        if not tool.exists():
            raise SystemExit(f"signing tool not found: {tool}")

    values = _signing_env()
    env = {**os.environ,
           "AZURE_TENANT_ID": values["AZURE_TENANT_ID"],
           "AZURE_CLIENT_ID": values["AZURE_CLIENT_ID"],
           "AZURE_CLIENT_SECRET": values["AZURE_CLIENT_SECRET"]}

    # ONE FILE PER INVOCATION. The sign CLI's parser binds exactly one
    # file argument; a second path comes back "Unrecognized command or
    # argument" -- which is how the first production run failed. The
    # bootstrap probe passed because it signed one file.
    for path in paths:
        command = [
            str(SIGN_CLI), "code", "trusted-signing", str(path),
            "--trusted-signing-endpoint", values["TS_ENDPOINT"],
            "--trusted-signing-account", values["TS_ACCOUNT"],
            "--trusted-signing-certificate-profile", values["TS_PROFILE"],
            "--timestamp-url", TIMESTAMP_URL,
            "--file-digest", "SHA256",
            "--timestamp-digest", "SHA256",
        ]
        last = ""
        for attempt in range(3):
            result = subprocess.run(command, capture_output=True, text=True, env=env)
            if result.returncode == 0:
                break
            last = (result.stderr or result.stdout or "").strip()[-400:]
            print(f"signing {path.name} attempt {attempt + 1} failed; retrying", flush=True)
        else:
            raise SystemExit(f"Trusted Signing failed for {path.name} after 3 attempts:\n{last}")

    for path in paths:
        verify = subprocess.run(
            [str(SIGNTOOL), "verify", "/pa", str(path)],
            capture_output=True, text=True,
        )
        if verify.returncode != 0:
            raise SystemExit(
                f"signature verify FAILED for {path.name}:\n{(verify.stdout or verify.stderr)[-400:]}"
            )
        print(f"signed and verified: {path.name}", flush=True)

    return True


def signing_is_configured() -> bool:
    """Credentials and both tools present. Says nothing about whether they work."""
    return ENV_FILE.exists() and SIGN_CLI.exists() and SIGNTOOL.exists()


UNSIGNED_SOURCE_BUILD = (
    "!! No code-signing credentials on this machine ({env}).\n"
    "!! Building UNSIGNED -- expected for a build from source. Windows SmartScreen\n"
    "!! will warn when this installer runs. Official Talk DAT! releases are signed;\n"
    "!! to sign your own, see scripts/sign_windows.py."
)


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    # --if-configured: a SOURCE build's opt-in signing. Without credentials it
    # skips (loudly) instead of failing. The publish path never uses it.
    if_configured = "--if-configured" in args
    args = [arg for arg in args if arg != "--if-configured"]
    paths = [Path(arg) for arg in args]
    if not paths:
        raise SystemExit("usage: sign_windows.py [--if-configured] <file.exe> [more files]")
    for path in paths:
        if not path.exists():
            raise SystemExit(f"no such file: {path}")
    if if_configured and not signing_is_configured():
        print(UNSIGNED_SOURCE_BUILD.format(env=ENV_FILE), flush=True)
        return
    sign_files(paths)


if __name__ == "__main__":
    main()
