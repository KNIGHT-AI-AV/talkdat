# Talk DAT!

**Free, local dictation for Windows and macOS.** Hold a key, talk, let go: Talk
DAT! turns your speech into clean, formatted text on your own computer and
pastes it into whatever app you are typing in.

- **Local.** Speech recognition runs on your computer, with NVIDIA Parakeet TDT
  0.6B v3 by default. Your audio never leaves the machine. Once the model is
  downloaded, unplug the network and it still dictates.
- **Free.** No plan, no trial, no subscription, no account needed.
- **Yours.** Open source under the Apache License 2.0.

Official downloads (signed, with automatic updates): https://www.talkdat.app/

## What it does

- Push-to-talk (`Ctrl+Win` on Windows) and hands-free dictation, with a small
  animated overlay, The Pill, that stays idle until you trigger it.
- Pastes the result into the active app, or types it where pasting is blocked.
- Formats as you speak: punctuation, numbers, dates, addresses, lists, spoken
  commands, a personal dictionary and learned words.
- Optional local formatting and translation through [Ollama](https://ollama.com/)
  (Qwen3 1.7B, TranslateGemma), still on your computer.
- More than a dozen downloadable speech models (Parakeet, Canary, Whisper,
  Distil-Whisper, GigaAM), managed from Settings.
- Optional bring-your-own-key routes to cloud speech providers, for people who
  want them. Local-only privacy, on by default, fences them off.
- History, stats, meeting recordings, live captions, document exports, a local
  control API on `127.0.0.1` and a Chrome companion extension.

User guides are in [docs/](docs/): start with
[START_HERE_WINDOWS.md](docs/START_HERE_WINDOWS.md), [INSTALL.md](docs/INSTALL.md)
and [PROVIDERS.md](docs/PROVIDERS.md).

## Models are downloaded, not bundled

No model weights are in this repository or in any installer. On first run the
app downloads the default speech model from Hugging Face (pinned revisions,
verified after download) into your user profile. Each model keeps its own
license: Parakeet TDT 0.6B v3 is by NVIDIA Corporation under CC BY 4.0. See
[NOTICE](NOTICE) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Privacy

Dictation, formatting and translation happen on your computer. Talk DAT! has no
cloud of its own. [docs/NETWORK.md](docs/NETWORK.md) lists every connection the
app can open; in short:

- **A build from source contacts none of Knight AI+AV's services.** No sign-in,
  no feedback upload, no preference sync, no update check unless you point it
  at endpoints of your own, and never the anonymous usage counts.
- **Official builds** additionally offer optional sign-in, send anonymous usage
  counts (first open, first dictation, still in use, day 7; never audio or
  text) unless you turn off Settings > Privacy > Share anonymous usage counts,
  and check GitHub for updates. The privacy notice is at
  https://www.talkdat.app/privacy.html.
- Model downloads come from Hugging Face; provider routes go only to the
  provider whose key you added.

## Official builds and builds from source

| | Official build | Build from source |
|---|---|---|
| Where from | https://www.talkdat.app/ | this repository |
| Signed | Windows: Azure Trusted Signing. Mac: Developer ID, notarized | unsigned unless you sign it |
| Updates | automatic, from Knight AI+AV's releases | pull and rebuild |
| Sign-in, feedback inbox, prefs sync | available | off unless configured |
| Anonymous usage counts | on by default, with their own switch in Settings > Privacy | never sent, no switch shown |
| Name and brand | Talk DAT! | please rename a fork you distribute ([TRADEMARKS.md](TRADEMARKS.md)) |

The switch is `knight_flow/official_build.py`, set at build time by
`scripts/write_build_flags.py`.

## Build from source

### Windows 10 or 11

Requires Python 3.13 (64-bit) and PowerShell.

```powershell
git clone <this repository>
cd talk-dat
# run from source (creates .venv on first run)
powershell -ExecutionPolicy Bypass -File .\run.ps1
```

Build the app (a folder with `Talk Dat!.exe`) and the installer:

```powershell
powershell -ExecutionPolicy Bypass -File .\build-exe.ps1              # dist\Talk Dat!\
powershell -ExecutionPolicy Bypass -File .\build-custom-installer.ps1 # release\Talk-Dat-Setup.exe
```

`build-exe.ps1` installs the hash-pinned `requirements.lock`, builds from the
curated `Talk Dat!.spec`, and generates `THIRD_PARTY_LICENSES.txt` from the
bundled packages. Code signing is optional: without signing credentials the
installer is built unsigned and says so, and Windows SmartScreen will warn when
it runs. `scripts/sign_windows.py` shows how official releases are signed.

### macOS

```bash
brew install python@3.13 python-tk@3.13 portaudio
python3.13 -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-mac.txt pyinstaller
./build-mac.sh            # dist-mac/Talk DAT!.app, ad-hoc signed
./build-mac.sh --dmg      # also a disk image
```

`python-tk` is required: the interface is Tk, and Homebrew's Python ships
without it. An ad-hoc signed app runs on the Mac that built it; macOS asks for
Microphone and Accessibility permission on first use. Distributing to other
Macs needs your own Developer ID and notarization (`TALK_DAT_SIGN_IDENTITY`,
`TALK_DAT_NOTARY_PROFILE`; see [docs/MAC_BUILD.md](docs/MAC_BUILD.md)).

### Tests

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-test.txt
.venv\Scripts\python.exe scripts\run_tests_offscreen.py     # Windows: on a hidden desktop
```

```bash
python -m unittest discover -s tests                        # macOS and Linux
```

## Layout

| Path | What |
|---|---|
| `knight_flow/` | the app: capture, speech engines, formatting, the overlay, settings, updater |
| `knight_flow/web_shell/` | the settings and setup windows (WebView2 / WKWebView) |
| `installer/` | the Windows installer and uninstaller |
| `extension/` | the Chrome companion extension (talks only to `127.0.0.1`) |
| `scripts/` | build, license, asset and developer tools |
| `tests/` | the test suite |
| `docs/` | user guides, [NETWORK.md](docs/NETWORK.md), [TELEMETRY.md](docs/TELEMETRY.md) |

## Contributing, security, conduct

- [CONTRIBUTING.md](CONTRIBUTING.md): pull requests welcome; sign off your
  commits (DCO), no CLA.
- [SECURITY.md](SECURITY.md): report vulnerabilities privately to
  security@knightaiav.com.
- [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md): Contributor Covenant 2.1.

## License

Talk DAT! is licensed under the [Apache License 2.0](LICENSE), with the notices
in [NOTICE](NOTICE). The Talk DAT! name, logo, Pill artwork, Knight Display
typeface and other brand assets are not covered by that license; see
[TRADEMARKS.md](TRADEMARKS.md) and [REUSE.toml](REUSE.toml). Official binaries
also carry the end-user terms in [EULA.md](EULA.md) and the third-party
licenses of everything they bundle.

Licensing history: versions up to v0.3.39-beta were released under the GNU GPL
version 3, and recipients of those versions keep the rights it granted.
Versions 0.4.x were proprietary until this release. From this release on, the
source is Apache-2.0.

Talk DAT! is made by Knight AI+AV LLC. It is an independent project and is not
affiliated with any speech or AI provider it can connect to.
