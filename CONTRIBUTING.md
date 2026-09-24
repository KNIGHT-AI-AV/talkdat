# Contributing to Talk DAT!

Thank you for helping. Talk DAT! is open source under the
[Apache License 2.0](LICENSE). Contributions are accepted under the same
license: by the terms of section 5 of the Apache License, anything you submit
for inclusion is licensed under Apache-2.0, with no additional terms.

## Sign your commits (DCO)

We use the [Developer Certificate of Origin 1.1](https://developercertificate.org/),
not a Contributor License Agreement. There is no CLA to sign.

Every commit must carry a `Signed-off-by` line with your real name and an email
address you can be reached at, certifying that you wrote the change or have the
right to submit it under the project's license:

```text
Signed-off-by: Your Name <you@example.com>
```

`git commit -s` adds it for you. Pull requests with unsigned commits cannot be
merged; `git rebase --signoff main` fixes a branch after the fact.

## Ground rules

- Never commit API keys, signing material, private config files, transcripts,
  history, logs, screenshots that show private text, or built binaries.
- Run `python scripts/prepublish_check.py` before opening a pull request.
- Keep provider adapters small and explicit. Each provider documents its
  authentication, request shape, supported modes and failure behavior.
- Never log a secret. Error messages name the provider and model, never a
  token.
- The overlay stays idle until a trigger starts recording. Check microphone
  activation, cancel, panic stop and the no-speech timeout when you touch
  capture.
- A new network connection needs a line in [docs/NETWORK.md](docs/NETWORK.md),
  and any call to Knight AI+AV's services goes through
  `knight_flow/official_build.py`.
- New binary assets (images, fonts, sounds, models) need their provenance and
  license in the pull request, and brand assets stay as they are: see
  [TRADEMARKS.md](TRADEMARKS.md).

## Development setup

Windows (Python 3.13):

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install --require-hashes --no-deps -r requirements.lock
.venv\Scripts\python.exe -m pip install -r requirements-test.txt
powershell -ExecutionPolicy Bypass -File .\run.ps1
```

macOS: see the build section of [README.md](README.md).

## Tests

```powershell
# the whole suite, on a hidden Windows desktop so no windows pop up on yours
.venv\Scripts\python.exe scripts\run_tests_offscreen.py
# one module
.venv\Scripts\python.exe scripts\run_tests_offscreen.py tests.test_official_build
```

On macOS and Linux, run `python -m unittest discover -s tests` directly.

## Pull requests

Include what changed and why, the provider and model you tested with if
relevant, and whether microphone activation, cancel, panic stop and the
no-speech timeout were checked. Keep screenshots free of private text and keys.

Talk DAT! is also developed in a private repository at Knight AI+AV. Merged
pull requests are mirrored into it with their authorship and sign-off intact,
and each official release is published back here.

## Conduct

Everyone taking part follows the [Code of Conduct](CODE_OF_CONDUCT.md).
Security problems go to [SECURITY.md](SECURITY.md), not to public issues.
