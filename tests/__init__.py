"""Point the whole suite at a scratch data directory before any test imports.

A test run must not be able to change the machine it runs on. That sounds
obvious and the suite violated it anyway: a test that mocked the Authenticode
signature check, but not the REMEMBERING of it, wrote the ratchet marker into
the developer's own Talk DAT! install. Nothing failed at the time. What failed
was the next run -- two checksum tests that say nothing about signing went red,
because that machine had now permanently promised to demand a signature.

`app_dir()` honours TALK_DAT_HOME ahead of APPDATA, and unittest imports this
package before it imports any test module, so setting it here is the earliest
and widest point at which the guarantee can be made. Individual tests may still
redirect app_dir to somewhere of their own; this is the floor, not a ceiling.

Deliberately NOT deleted at the end of the run: if a test writes something
surprising, it should be there to look at. It lives under the system temp
directory and the OS reclaims it.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

_SCRATCH = Path(tempfile.gettempdir()) / "talk-dat-test-home"
_SCRATCH.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("TALK_DAT_HOME", str(_SCRATCH))
# 2026-09-22: every non-trivial dictation is now offered to the local model.
# A unit test must not depend on whether this PC has Ollama running, so the
# engine reads as absent unless a test mocks it; the parity battery and the
# benchmarks clear this deliberately to measure the real engine.
os.environ.setdefault("TALK_DAT_LOCAL_ENGINE_OFFLINE", "1")

# A separate data folder does not isolate Windows Credential Manager or the
# Mac keychain. Reset and save tests must never use the person's actual vault.
from tests.credential_sandbox import install as _isolate_credentials
_isolate_credentials()
