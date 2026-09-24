# Installer

This folder contains the custom glass Windows installer and uninstaller entrypoints.

Build from the repo root:

```powershell
powershell -ExecutionPolicy Bypass -File .\build-custom-installer.ps1
```

Compatibility command:

```powershell
powershell -ExecutionPolicy Bypass -File .\build-installer.ps1
```

Output:

```text
release\Talk-Dat-Setup.exe
```

The installer is per-user and defaults to:

```text
%LOCALAPPDATA%\Programs\Talk DAT!
```

It copies the app EXE, local help docs, a matching custom uninstaller, Start/Desktop shortcuts, an optional Startup shortcut, and a Windows Apps uninstall registry entry.

The installer never includes API keys, user config, transcript history, local logs, dictionaries, snippets, or scratchpad content. The uninstaller keeps `%APPDATA%\TalkDat` by default and only removes it when the user selects the private-data removal option.

`TalkDat.iss` is kept only as a legacy Inno Setup reference. Public release builds use `glass_installer.py`.
