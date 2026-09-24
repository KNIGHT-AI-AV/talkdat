# Talk DAT! on macOS

How the Mac build works, what it needs, and what is still missing before it can
be given to anyone. Written 2026-08-08 alongside the port, from the machine it
was built on: macOS 26.4.1, Apple Silicon.

## What works

The whole product, apart from distribution. Dictation, the Pill, every settings
window, local transcription, licensing, translation, history, the menu bar item
and per-app profiles all run natively. The 1,190 tests pass on macOS.

Local speech runs on the Apple Neural Engine. ONNX Runtime picks up
`CoreMLExecutionProvider` without configuration and puts 1,528 of Parakeet's
3,249 graph nodes on it. Measured on this machine: **1.7s to transcribe 6.9s of
speech once the model is warm, about 4x realtime**. First load costs ~13s, which
is why the app warms the model in the background at startup.

## Prerequisites

```bash
brew install python@3.13 python-tk@3.13 portaudio
```

`python-tk` is not optional and is easy to miss: Homebrew's Python ships without
tkinter, the entire interface is tkinter, and a build made without it succeeds
and then produces an app that dies on launch. `build-mac.sh` checks for it.

Then, in a virtualenv on that Python:

```bash
pip install -r requirements.txt pyinstaller keyring
```

`keyring` is macOS-only and is what puts provider keys in the Keychain.

## Building

```bash
./build-mac.sh              # dist-mac/Talk DAT!.app
./build-mac.sh --install    # also replaces /Applications/Talk DAT!.app
./build-mac.sh --dmg        # also builds dist-mac/Talk-DAT-<version>.dmg
```

Set `TALK_DAT_PYTHON` if the interpreter with PyInstaller is not `python3`:

```bash
TALK_DAT_PYTHON=/path/to/venv/bin/python ./build-mac.sh --install
```

The script generates the `.icns` from `knight_flow/assets/app_icon.png`, builds
through `TalkDat-mac.spec`, and then **probe-launches the result and requires it
to still be alive twenty seconds later**. 0.4.35 shipped a Windows build that
exited immediately because PyInstaller dropped cryptography's compiled binding
and the build reported success; the probe is the answer to that. It runs against
a temporary app directory so it neither collides with the single-instance lock
of a running copy nor writes to real config.

`TalkDat-mac.spec` is committed, unlike the Windows spec. The guard test for
that cryptography failure reads the spec, and a gitignored spec makes the test
error on a clean checkout instead of guarding anything.

Like `build-exe.ps1`, the script bakes OFFICIAL or SOURCE into the app with
`scripts/write_build_flags.py` just before PyInstaller and deletes the generated
`knight_flow/_build_flags.py` afterwards. A checkout without Knight AI+AV's
release tooling builds SOURCE, which contacts none of Knight's services (see
[NETWORK.md](NETWORK.md)); `TALKDAT_OFFICIAL_BUILD=1` or `=0` decides outright.

Every build carries its licences: `scripts/collect_licenses.py --strict` writes
`THIRD_PARTY_LICENSES.txt` from the packages and native libraries PyInstaller
actually bundled, and it goes into `Contents/Resources` beside `LICENSE.txt` and
`NOTICE.txt` before anything signs the bundle. The disk image carries the same
three files at its root.

## Permissions

macOS gates the two things dictation depends on. Neither can be granted by the
installer; both are the user's decision, and the app cannot work around either.

| Permission | Needed for | Symptom when missing |
|---|---|---|
| **Accessibility** | seeing the trigger key, and pasting | Holding the trigger does nothing at all |
| **Microphone** | recording | macOS prompts on first capture |

Accessibility is the one that looks like a broken app rather than a permission:
pynput's listener starts, logs "this process is not trusted" where nobody sees
it, and then never reports a key. The app checks at startup, asks once, and puts
the reason on the Pill.

Grant it at **System Settings > Privacy & Security > Accessibility**.

**macOS ties that grant to the code signature.** This build is ad-hoc signed, so
the signature changes on every build and the permission has to be granted again
after each one. A Developer ID certificate makes it stable.

### The signature also owns your Keychain items

The same rebuild that invalidates the Accessibility grant invalidates the
Keychain ACL on anything the app has already stored. macOS then asks permission
before handing the item over -- and that question arrives while the
configuration is loading, before any window exists, so the app sits frozen with
no Pill and an empty log until it is answered. It looks broken rather than
blocked.

`KeychainCredentialStore` now gives a read four seconds and continues without
it, logging why. A missing key surfaces as "this provider needs its key", which
someone can see and act on; a frozen launch cannot be diagnosed at all.

If a build starts behaving as though its stored keys vanished, look for
`keychain read for ... did not finish` in the log. Answering the dialog and
restarting picks them up. A Developer ID signature stops the ACL changing in the
first place.

## What is not done: signing and notarisation

The build is ad-hoc signed. It runs on the machine that built it and **will not
open on any other Mac** -- Gatekeeper refuses an un-notarised app that arrived
over the network, and the DMG is therefore not something to send anyone yet.

Two things are needed, both from the Apple Developer account (team
`9NB97BZDR3`, the one already used for `com.knightaiav.liftwizard` and
`com.knightaiav.knightchat`):

1. A **Developer ID Application** certificate. This is a different certificate
   type from the iOS distribution certificates already on that team; it is
   specifically for distribution outside the App Store.
2. An **App Store Connect API key** so `notarytool` can submit builds.

The build script already does the rest. `mac-entitlements.plist` is written and
the two steps are wired up, so once the credentials exist it is one command:

```bash
export TALK_DAT_SIGN_IDENTITY="Developer ID Application: ... (9NB97BZDR3)"
xcrun notarytool store-credentials talk-dat \
    --key AuthKey_XXXX.p8 --key-id <KEY_ID> --issuer <ISSUER_UUID>
export TALK_DAT_NOTARY_PROFILE=talk-dat

./build-mac.sh --notarize
```

That signs every Mach-O in the bundle individually with the hardened runtime
(innermost first, bundle last -- `--deep` is deprecated and does not produce a
layout the notary service accepts), builds the DMG, submits it, waits, staples
the ticket and prints Gatekeeper's verdict. Missing credentials are caught
before the build starts rather than after it, and so is a SOURCE build:
`--notarize` is the release path and refuses one before building.

Stapling is not optional: without it the ticket only exists on Apple's servers,
and a first launch on a Mac that is offline is refused.

The sandbox is deliberately not enabled in the entitlements. A sandboxed app
cannot post synthetic keystrokes into another application, which is how every
dictation is delivered. Developer ID distribution does not require it; the App
Store would, which is why this is not an App Store product.

Until this runs, the build is local-only.

## Platform seams

Everything above the seams is shared with Windows. The Mac side of each:

| Seam | macOS implementation |
|---|---|
| App data | `~/Library/Application Support/TalkDat` |
| Secrets | Keychain via `keyring` (not the `security` CLI, which puts the secret in argv where `ps` can read it) |
| Paste / copy / undo | Command instead of Ctrl |
| Foreground app, per-app profiles | `NSWorkspace.frontmostApplication` |
| Screen geometry | `NSScreen`, with `visibleFrame` as the work area |
| Single instance | `flock` on a file in the app directory; a second launch raises the first and exits |
| Menu bar | `NSStatusItem` built on the Tk thread (`mac_menu_bar.py`) -- pystray cannot do this, see below |
| Resize cursor | `bottom_right_corner`; Aqua rejects `size_nw_se` with a TclError |

Defaults that differ, because the Windows chord means something else here:

- **Hands-free** is `Ctrl+Cmd+D`. `Ctrl+Cmd+Space` is the macOS Character Viewer.
- **View diff** is `Cmd+Alt+D`.
- Push-to-talk stays `Ctrl+Cmd`, which is unclaimed on both platforms.

### Why the menu bar is not pystray

pystray's macOS backend builds an `NSStatusItem`, and AppKit refuses to
instantiate one off the main thread. `TrayController` runs its icon on a worker
thread because that is what Windows needs, so on macOS it raised

    NSInternalInconsistencyException - NSWindow should only be instantiated on
    the main thread!

into the `except Exception: return` at the end of `TrayController._run`, and the
menu bar item silently never appeared. `mac_menu_bar.py` builds the same menu
with AppKit directly, on the Tk thread -- Tk's mainloop on Aqua is an NSRunLoop,
so the status item can be created from it.

This matters more on macOS than the tray does on Windows: the app is
`LSUIElement`, so there is no Dock icon and no application menu, and without the
menu bar item the only way to quit is the Pill's context menu.

## The undo allowlist is empty here

Instant correction (`replace_by_undo`) is off in every Mac application, and that
is deliberate rather than unfinished. Every name on the Windows allowlist was
earned by pasting into that application and reading the field back through the
clipboard. Nothing on macOS has had that done. The asymmetry that keeps Word off
the Windows list applies unchanged: missing costs a slower correction, wrongly
present costs somebody their sentence twice over. TextEdit and Safari are the
obvious first two to measure.

## Testing

```bash
python -m unittest discover -s tests        # crashes: see below
for f in tests/test_*.py; do python -m unittest "tests.$(basename $f .py)"; done
```

Run the suite **per file** on macOS. Tk 9.0 on Aqua cannot create a second root
after destroying the first -- the next `update_idletasks` segfaults -- and
`unittest discover` runs every file in one process. `tests/tk_support.py` shares
one root and resets it between tests, which fixes it within a file; across files
a fresh process per file is simpler than making every Tk test cooperate.

The application never hits this: it builds one root and keeps it for the life of
the process.
