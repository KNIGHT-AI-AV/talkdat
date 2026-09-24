# Every connection Talk DAT! makes

Talk DAT! dictates on your computer. Speech recognition, formatting and
translation run locally, and none of them needs the internet once the model
is downloaded. This page lists every connection the desktop app can open, who
it goes to, and how to turn it off.

## Official builds and builds from source

The same open-source code builds two kinds of app.

- **Official builds** are the signed downloads from https://www.talkdat.app/
  (Windows installer, portable zip, Mac disk image). They use Knight AI+AV's
  services, listed below.
- **Builds from source** are everything else: running from a checkout, an app
  you built yourself, a fork. **By default they contact none of Knight AI+AV's
  services.** Sign-in, feedback upload, preference sync, the anonymous counts
  and the update check are all off.

The switch is baked in at build time: `scripts/write_build_flags.py` writes
`knight_flow/_build_flags.py` before PyInstaller runs, and
`knight_flow/official_build.py` is the one module every call site asks. Set
`TALKDAT_OFFICIAL_BUILD=1` or `=0` to choose explicitly; otherwise only a
checkout carrying Knight AI+AV's private release tooling builds as official.

## Knight AI+AV's services (official builds only)

| Connection | Where | When | Carries |
|---|---|---|---|
| Anonymous usage counts | `POST api.talkdat.app/v1/activation` | first open (once), first dictation (once), still in use (at most daily), day 7 (once); only while **Settings > Privacy > Share anonymous usage counts** is on, which is the default | a random install id, version, platform, dates, an internal-machine flag; never audio or text. Details: [TELEMETRY.md](TELEMETRY.md) |
| Optional sign-in | `api.talkdat.app/v1/device/*`, `/v1/auth/email/*`, `/v1/handoff/exchange` | only when you sign in | your email address, a random device id and a device name |
| Preference sync | `POST api.talkdat.app/v1/prefs` | only while signed in, when you change the theme or the Pill menu order | the theme name or the menu order |
| Feedback | `POST api.talkdat.app/v1/feedback` | only when you send the in-app form | what you typed, an optional reply address, version, platform, and a formatting log only if you tick the box |
| Update check | `api.github.com/repos/KNIGHT-AI-AV/talk-dat-releases/releases` and the release's download | at launch and every 24 hours (Settings can turn it off), and when you click Check for updates | an ordinary GitHub API request; nothing about you |

A Microsoft Store copy updates only through the Store and makes no update
check of its own.

## Third parties, in every build

| Connection | Where | When |
|---|---|---|
| Speech model download | `huggingface.co`, pinned revisions | the first time you pick a local model (the default model is prepared on first launch) |
| NVIDIA CUDA runtime | `files.pythonhosted.org` | only if you ask for GPU acceleration on an NVIDIA card |
| Ollama | `ollama.com` (opened in your browser) and the local Ollama server on `127.0.0.1` | only if you set up local formatting or translation |
| Your own provider | the provider whose key you added (Deepgram, OpenAI and others) | only on that route, and never while the Local route is on: `knight_flow/net_fence.py` refuses the connection |
| Links | talkdat.app pages, provider sign-up pages | opened in your browser when you click them |

The local control API listens on `127.0.0.1:4670` only (see
[LOCAL_CONTROL_API.md](LOCAL_CONTROL_API.md)).

## Turning things off

- **Share anonymous usage counts** (Settings > Privacy, on by default in
  official builds, mentioned once in first-run setup) stops the four anonymous
  counts. It is a separate switch from Local-only privacy.
- **Local-only privacy** (Settings, on by default) keeps your audio and text on
  the computer and blocks your own provider keys. It does not decide the
  counts, which carry neither.
- **`TALKDAT_NO_PHONE_HOME=1`** in the environment turns off every connection
  to Knight AI+AV's services in any build: sign-in, feedback upload, preference
  sync, counts and the update check. Dictation is unaffected.
- **Settings > Updates** turns off the automatic update check.

## Pointing a build at your own endpoints

A build from source uses an endpoint only when you give it one.

At run time:

```text
TALKDAT_API_BASE=https://accounts.example.com       account, feedback, prefs
TALKDAT_UPDATE_REPOSITORY=your-org/your-releases    GitHub releases the updater reads
```

A build from source never sends the anonymous usage counts, even to a server
you point it at. A fork that wants counts of its own builds as official
(`TALKDAT_OFFICIAL_BUILD=1`) with its own baked endpoint; the person using it
then gets the same Share anonymous usage counts switch.

or, in `config.json`, `"licensing": {"api_base": "https://accounts.example.com"}`.
A source build ignores a `licensing.api_base` that names talkdat.app, because
every official install wrote that value into its config file and a fork on the
same computer reads the same file.

At build time, bake them in instead:

```powershell
$env:TALKDAT_BUILD_API_BASE = "https://accounts.example.com"
$env:TALKDAT_BUILD_UPDATE_REPOSITORY = "your-org/your-releases"
.\build-exe.ps1
```

Your server has to speak the same small JSON API (`/v1/activation`,
`/v1/feedback`, `/v1/prefs`, `/v1/device/*`, `/v1/auth/email/*`). The updater
also verifies each release against a `RELEASE-RECEIPT.json` naming your
repository and, once it has seen a signed release, an Authenticode signature;
see [RELEASE_INTEGRITY.md](RELEASE_INTEGRITY.md). Sign-in tokens are verified
against `knight_flow/assets/license_public_key.pem`, so a server of your own
needs its own key pair and that file replaced.
