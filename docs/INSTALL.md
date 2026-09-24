# Installation

## Official download

1. Open [talkdat.knightaiav.com](https://talkdat.knightaiav.com/).
2. Download one Windows asset:
   - Recommended: `Talk-Dat-Setup.exe`
   - Portable/no installer: `Talk-Dat-Windows-Portable.zip`
3. Optional manual check: compare the download with `SHA256SUMS.txt`. The in-app updater performs this SHA256 check automatically before launching a downloaded setup EXE.

The release assets do not contain API keys, dictionaries, snippets, private config, or transcript history.

## Recommended: Windows Installer

1. Download `Talk-Dat-Setup.exe` from a release.
2. Run the custom glass installer.
3. Keep the default install location unless you have a reason to move it.
4. Leave "Start with Windows" off unless you want Talk DAT! to launch when Windows signs in.
5. Click Install. Leave "Launch after install" enabled for the fastest first run.
6. Complete the guided setup:
   - Review the trigger-only privacy and protected-hold safety model.
   - Keep **Private on-device** for the no-account default, choose a wired
     **Bring your own** provider, or use Talk DAT! Managed after activating a
     trial or Pro account.
   - Select a microphone and confirm its level on the private local meter.
   - Press the displayed trigger keys and watch each key respond.
   - Choose a writing style and complete the protected in-window dictation test.

The installer does not contain API keys. It installs the app executable, local help docs, Start/Desktop shortcuts, optional startup shortcut, and a matching custom glass uninstaller registered in Windows Apps.

On Windows, saved STT/LLM keys and the optional local-control token are migrated into Windows Credential Manager for the current user. `config.json` keeps non-secret preferences and is redacted only after the vault write succeeds. If Credential Manager is unavailable, Talk DAT! keeps the existing local config value so an upgrade cannot destroy access.

## Updates

The installed app records its current version in local config. Use Settings > Core, Status, or the tray menu to check the official Knight AI+AV binary release channel. When a newer version exists, Talk DAT! downloads the official `Talk-Dat-Setup.exe` to:

```text
%APPDATA%\TalkDat\updates
```

Then it verifies the setup EXE against the release SHA256 checksum and launches the installer in silent update mode. The installer stages and verifies the complete new payload before closing the old app, swaps the files as one recoverable transaction, restores the previous app automatically if replacement fails, and relaunches Talk DAT! only after a successful commit. Startup update checks are on by default; automatic installer download can be enabled in Settings > Core.

Release CI runs the same silent path twice: once against the freshly packaged installer before publication, and again by downloading the public release through Talk DAT!'s own updater. Both runs verify install metadata, same-version replacement, uninstall registration, and preservation of private AppData.

Unsigned builds may still trigger Microsoft Defender SmartScreen before Windows allows the downloaded installer to run. That warning is caused by unsigned/low-reputation binaries. Code signing is required for the publisher to show as verified.

Settings > Dictation includes the protected-session safety net. Talk DAT! writes
each accepted trigger hold to `%APPDATA%\TalkDat\audio-spool` while the
microphone is live and retains at least five sessions. If a provider returns no
transcript after speech was detected, it retries from that local capture.
History can play or recover any retained session, and Clear recordings removes
the local WAVs explicitly.

Settings > Audio includes paste method controls. `auto` is the recommended default: clipboard paste for normal apps and direct typing when the foreground app is a remote desktop client such as RDP, VNC, Jump Desktop, AnyDesk, or Parsec.

## Portable EXE

1. Download `Talk-Dat-Windows-Portable.zip`.
2. Extract it somewhere you trust, such as `%LOCALAPPDATA%\Programs\Talk DAT!`.
3. Open `START-HERE.md`.
4. Run `Talk Dat!.exe`.
5. Complete onboarding.

Optional startup registration from source:

```powershell
powershell -ExecutionPolicy Bypass -File .\install-startup.ps1
```

Remove startup registration:

```powershell
powershell -ExecutionPolicy Bypass -File .\uninstall-startup.ps1
```

## Internal source checkout

Authorized Knight AI+AV maintainers can run `powershell -ExecutionPolicy Bypass -File .\run.ps1` from the private product repository.

## Build A Release Locally

Build the EXE:

```powershell
powershell -ExecutionPolicy Bypass -File .\build-exe.ps1
```

Build the custom glass installer:

```powershell
powershell -ExecutionPolicy Bypass -File .\build-custom-installer.ps1
```

The compatibility command also works:

```powershell
powershell -ExecutionPolicy Bypass -File .\build-installer.ps1
```

The installer builder uses PyInstaller and does not require Inno Setup.

Maintainer-only silent switches used by release CI and the in-app updater:

```powershell
.\Talk-Dat-Setup.exe --silent-install --no-launch
& "$env:LOCALAPPDATA\Programs\Talk DAT!\Talk Dat! Uninstaller.exe" --silent-uninstall
```

Silent uninstall preserves `%APPDATA%\TalkDat` by default. Add `--remove-user-data` only for an explicit full-data removal.

## First-Run Onboarding

On a fresh config, Talk DAT! opens a seven-step visual setup:

1. **Access** offers account creation and a no-card trial, existing-account
   sign-in and restore, plan comparison, or private local/BYOK setup. Browser
   activation is recognized automatically through the signed device entitlement.
2. **Welcome** explains trigger-only recording, protected local holds, and open
   model choice.
3. **Voice** offers private on-device speech, ten wired BYOK providers, and the
   account-gated managed route. BYOK setup includes official sign-in, key, and
   documentation links.
4. **Microphone** selects the Windows input and shows a real local waveform and
   quality level only while that page is open. Meter audio is neither saved nor
   sent.
5. **Controls** displays the configured trigger as reactive keycaps. Each key
   lights independently and the chord confirms when all keys are held.
6. **Writing** chooses Smart & faithful, Fast clean, or Near verbatim behavior.
7. **Test** performs real transcription and formatting into an in-window
   practice box. It deliberately does not paste into the previously focused app.

Provider keys are stored for the current Windows user in Credential Manager;
`config.json` contains only non-secret settings after a successful vault write.
The setup receipt contains route and completion checks, never an API key or
transcript. Reopen the walkthrough from `Settings > Home > Run setup guide`.

## Uninstall

If installed through the setup EXE, uninstall from Windows Apps or run `Talk Dat! Uninstaller.exe` from the install folder. The custom uninstaller removes installed app files, shortcuts, startup entry, and Windows registration.

Private local user data is kept by default. Select the uninstaller option to remove it only when you truly want to delete:

```text
%APPDATA%\TalkDat
```

Deleting that folder removes local config and transcript history.
