# Start Here: Talk DAT! for Windows

## Fast Path

1. If you downloaded the setup EXE, run `Talk-Dat-Setup.exe` and leave "Launch after install" enabled.
2. If you downloaded the portable ZIP, run `Talk Dat!.exe`.
3. Follow the six visual setup steps: voice route, microphone, trigger keys,
   writing style, and protected in-window test.
4. Keep the recommended no-key local route, or choose a wired cloud provider
   and use its official sign-in/key links.
5. Finish setup. Open Notepad and dictate one more sentence to confirm normal
   cross-app paste.

## Controls

- Hold `Ctrl+Win` to dictate while held.
- Click the pill to toggle hands-free dictation.
- Click the pill again, or press a trigger combo, to stop.
- Right-click the pill for Settings, History, and Scratchpad.
- Settings > Core changes the glass menu theme live while the window is open.
- Settings > Home > Run setup guide reopens the complete walkthrough.
- Settings > Dictation can mute speaker output while recording, then restore it when recording stops.
- Settings > Overlay can hide the idle pill while a game or video is fullscreen.
- Settings > Core shows the installed version and can check/install the latest GitHub release.
- Use `Ctrl+Win+Esc` as panic stop.

## Privacy

This download does not include API keys or private user data.

Your keys, provider options, dictionary, snippets, transcript history, live draft, and scratchpad tabs are saved locally under:

```text
%APPDATA%\TalkDat
```

The microphone does not open until you trigger dictation.
When speaker-output muting is enabled, only Windows playback is muted; microphone input remains available for dictation.
Update installers come only from the official Knight AI+AV binary distribution channel and are saved under `%APPDATA%\TalkDat\updates`.

## Troubleshooting

- If Windows warns about an unsigned app, choose "More info" and "Run anyway" only if you downloaded it from the official GitHub release.
- If nothing pastes, check Settings > Core and make sure auto paste is enabled.
- If transcription fails, check Settings > Providers for the provider key, model, API base, and adapter status.
- If the pill blocks something, hover over it for two seconds and it fades translucent.
- If you used the installer, remove the app from Windows Apps. The custom uninstaller keeps private local data unless you select the removal option.
