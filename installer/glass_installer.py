from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import traceback
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Callable

import tkinter as tk
from tkinter import filedialog
from tkinter import font as tkfont

try:
    import winreg
except ImportError:  # pragma: no cover - this installer is Windows-only.
    winreg = None  # type: ignore[assignment]

from PIL import Image, ImageDraw, ImageFilter, ImageTk
from knight_flow.credentials import delete_all_credentials


def _load_brand_family() -> str:
    """The Knight AI+AV face, from the installer's own bundle. The installer
    is the FIRST thing a customer sees; it dresses like the app. Registration
    is process-private and falls back to Segoe when anything is off."""
    try:
        import ctypes

        base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
        candidates = [
            base / "payload" / "fonts" / "KnightDisplay.ttf",
            base / "KnightDisplay.ttf",
        ]
        for path in candidates:
            if path.exists():
                if ctypes.windll.gdi32.AddFontResourceExW(str(path), 0x10, 0) > 0:
                    return "Knight AI+AV"
    except Exception:
        pass
    return "Segoe UI"


BRAND_UI_FAMILY = _load_brand_family()

try:
    from knight_flow.version import APP_VERSION
except Exception:  # pragma: no cover - standalone installer fallback.
    APP_VERSION = "0.4.8-beta"

APP_NAME = "Talk DAT!"
PUBLISHER = "Knight AI+AV"
APP_EXE_NAME = "Talk Dat!.exe"
UNINSTALL_EXE_NAME = "Talk Dat! Uninstaller.exe"
MANIFEST_NAME = "install-manifest.json"
UNINSTALL_REGISTRY_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\TalkDat"
LEGACY_SUFFIX = "".join(chr(value) for value in (83, 104, 105))
LEGACY_APP_NAME = f"Talk Dat {LEGACY_SUFFIX}"
LEGACY_APP_EXE_NAME = f"{LEGACY_APP_NAME}.exe"
LEGACY_UNINSTALL_REGISTRY_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\TalkDat" + LEGACY_SUFFIX
TRANSPARENT_COLOR = "#010203"
INSTALLER_LOG_NAME = "installer.log"

# Round 2 "Premium Simple" palette -- warm gold and cream on the oxblood clay.
# All teal is gone: the old widget set mixed two colour families and every
# embedded control carried its own dark box, which together read as cheap.
CREAM = "#fff5d8"   # headings
BODY = "#e9d9c8"    # toggle labels
MUTED = "#c9b3a3"   # quiet text, status default
GOLD = "#ffd477"    # accent, links, progress fill
HAIR = "#4a2a30"    # hairlines, outlines-off
CHIP = "#1d0e12"    # control fill (rows, trough, ghost)
CHIP_H = "#271419"  # control fill hover
FIELD = "#170a0e"   # entry bg
WARN = "#ffcf9e"    # validation messages
ERR = "#ff9d8a"     # failure messages
INK = "#07191a"     # text on gold

Report = Callable[[float, str], None]


def _creation_flags() -> int:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return int(flags)


def _detached_flags() -> int:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    flags |= getattr(subprocess, "DETACHED_PROCESS", 0)
    return int(flags)


def resource_path(*parts: str) -> Path:
    roots: list[Path] = []
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        roots.append(Path(bundle_root))
    here = Path(__file__).resolve().parent
    roots.extend([here, here.parent, Path.cwd()])
    for root in roots:
        candidate = root.joinpath(*parts)
        if candidate.exists():
            return candidate
    return roots[0].joinpath(*parts)


def payload_path(name: str) -> Path:
    return resource_path("payload", name)


def payload_candidates(name: str) -> list[Path]:
    candidates = [payload_path(name)]
    project_root = Path(__file__).resolve().parent.parent
    candidates.extend(
        [
            project_root / "dist" / name,
            Path.cwd() / "dist" / name,
            Path.cwd() / "payload" / name,
        ]
    )
    seen: set[str] = set()
    unique: list[Path] = []
    for candidate in candidates:
        key = norm_path(candidate)
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


def asset_path(name: str) -> Path:
    return resource_path("knight_flow", "assets", name)


def default_install_dir() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "Programs" / APP_NAME
    return Path.home() / "AppData" / "Local" / "Programs" / APP_NAME


def user_data_dir() -> Path:
    app_data = os.environ.get("APPDATA")
    if app_data:
        return Path(app_data) / "TalkDat"
    return Path.home() / "AppData" / "Roaming" / "TalkDat"


def installer_log_path() -> Path:
    return user_data_dir() / INSTALLER_LOG_NAME


def write_installer_log(message: str) -> None:
    try:
        path = installer_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        stamp = dt.datetime.now(dt.timezone.utc).isoformat()
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"[{stamp}] {message}\n")
    except OSError:
        pass


def legacy_user_data_dir() -> Path:
    app_data = os.environ.get("APPDATA")
    if app_data:
        return Path(app_data) / ("TalkDat" + LEGACY_SUFFIX)
    return Path.home() / "AppData" / "Roaming" / ("TalkDat" + LEGACY_SUFFIX)


def copy_missing_items(source_root: Path, destination_root: Path) -> None:
    destination_root.mkdir(parents=True, exist_ok=True)
    for item in source_root.iterdir():
        destination = destination_root / item.name
        if destination.exists():
            continue
        try:
            if item.is_dir():
                shutil.copytree(item, destination)
            else:
                shutil.copy2(item, destination)
        except OSError:
            pass


def rename_legacy_user_data(legacy_root: Path) -> None:
    backup = legacy_root.with_name("TalkDatLegacyBackup")
    candidate = backup
    index = 2
    while candidate.exists():
        candidate = backup.with_name(f"{backup.name}{index}")
        index += 1
    try:
        legacy_root.rename(candidate)
    except OSError:
        pass


def migrate_legacy_user_data() -> None:
    root = user_data_dir()
    legacy_root = legacy_user_data_dir()
    if not legacy_root.exists():
        return
    if not root.exists():
        try:
            legacy_root.rename(root)
            return
        except OSError:
            pass
    copy_missing_items(legacy_root, root)
    rename_legacy_user_data(legacy_root)


def desktop_shortcut_path() -> Path:
    return Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop" / f"{APP_NAME}.lnk"


def start_menu_shortcut_path() -> Path:
    app_data = Path(os.environ.get("APPDATA", str(Path.home())))
    return app_data / "Microsoft" / "Windows" / "Start Menu" / "Programs" / f"{APP_NAME}.lnk"


def startup_shortcut_path() -> Path:
    app_data = Path(os.environ.get("APPDATA", str(Path.home())))
    return app_data / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / f"{APP_NAME}.lnk"


def legacy_shortcut_paths() -> list[Path]:
    app_data = Path(os.environ.get("APPDATA", str(Path.home())))
    user_profile = Path(os.environ.get("USERPROFILE", str(Path.home())))
    return [
        user_profile / "Desktop" / f"{LEGACY_APP_NAME}.lnk",
        app_data / "Microsoft" / "Windows" / "Start Menu" / "Programs" / f"{LEGACY_APP_NAME}.lnk",
        app_data / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / f"{LEGACY_APP_NAME}.lnk",
    ]


def norm_path(path: Path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


def is_under(path: Path, parent: Path) -> bool:
    child_value = norm_path(path)
    parent_value = norm_path(parent)
    return child_value == parent_value or child_value.startswith(parent_value + os.sep)


def is_dangerous_install_dir(path: Path) -> bool:
    resolved = Path(os.path.abspath(os.path.expanduser(str(path))))
    if len(resolved.parts) <= 2:
        return True
    sensitive = {
        norm_path(Path.home()),
        norm_path(Path(os.environ.get("LOCALAPPDATA", str(Path.home())))),
        norm_path(Path(os.environ.get("APPDATA", str(Path.home())))),
        norm_path(Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop"),
    }
    return norm_path(resolved) in sensitive


def ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def run_powershell(script: str) -> None:
    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True,
        text=True,
        creationflags=_creation_flags(),
    )
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or "PowerShell command failed."
        raise RuntimeError(detail)


def create_shortcut(shortcut_path: Path, target_path: Path, description: str) -> None:
    shortcut_path.parent.mkdir(parents=True, exist_ok=True)
    script = f"""
$shortcutPath = {ps_quote(str(shortcut_path))}
$targetPath = {ps_quote(str(target_path))}
$workingDirectory = {ps_quote(str(target_path.parent))}
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $targetPath
$shortcut.WorkingDirectory = $workingDirectory
$shortcut.IconLocation = "$targetPath,0"
$shortcut.Description = {ps_quote(description)}
$shortcut.Save()
"""
    run_powershell(script)


def remove_shortcut(shortcut_path: Path) -> None:
    try:
        if shortcut_path.exists():
            shortcut_path.unlink()
    except OSError:
        pass


def directory_size_kb(path: Path) -> int:
    total = 0
    if path.exists():
        for item in path.rglob("*"):
            if item.is_file():
                try:
                    total += item.stat().st_size
                except OSError:
                    pass
    return max(1, math.ceil(total / 1024))


def register_uninstaller(install_dir: Path, app_exe: Path, uninstaller: Path) -> None:
    if winreg is None:
        raise RuntimeError("Windows registry is not available.")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, UNINSTALL_REGISTRY_KEY) as key:
        winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, APP_NAME)
        winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, APP_VERSION)
        winreg.SetValueEx(key, "Publisher", 0, winreg.REG_SZ, PUBLISHER)
        winreg.SetValueEx(key, "InstallLocation", 0, winreg.REG_SZ, str(install_dir))
        winreg.SetValueEx(key, "DisplayIcon", 0, winreg.REG_SZ, f"{app_exe},0")
        winreg.SetValueEx(key, "UninstallString", 0, winreg.REG_SZ, f'"{uninstaller}"')
        winreg.SetValueEx(key, "NoModify", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(key, "NoRepair", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(key, "EstimatedSize", 0, winreg.REG_DWORD, directory_size_kb(install_dir))


def unregister_uninstaller() -> None:
    if winreg is None:
        return
    for key_name in (UNINSTALL_REGISTRY_KEY, LEGACY_UNINSTALL_REGISTRY_KEY):
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key_name)
        except OSError:
            pass


def installed_location() -> Path:
    if winreg is not None:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_REGISTRY_KEY) as key:
                value, _kind = winreg.QueryValueEx(key, "InstallLocation")
                if isinstance(value, str) and value.strip():
                    return Path(value)
        except OSError:
            pass
    return default_install_dir()


def load_manifest(install_dir: Path) -> dict[str, Any]:
    path = install_dir / MANIFEST_NAME
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def write_manifest(install_dir: Path, files: list[Path], shortcuts: list[Path]) -> None:
    manifest_path = install_dir / MANIFEST_NAME
    all_files = [*files, manifest_path]
    file_receipts = [
        {
            "path": str(path),
            "size_bytes": path.stat().st_size,
            "sha256": file_sha256(path),
        }
        for path in files
        if is_under(path, install_dir) and path.is_file()
    ]
    data = {
        "app": APP_NAME,
        "version": APP_VERSION,
        "publisher": PUBLISHER,
        "installed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "install_dir": str(install_dir),
        "user_data_dir": str(user_data_dir()),
        "files": [str(path) for path in all_files],
        "file_receipts": file_receipts,
        "shortcuts": [str(path) for path in shortcuts],
        "keeps_private_data_by_default": True,
    }
    manifest_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def verify_installed_payload(install_dir: Path, manifest: dict[str, Any] | None = None) -> list[str]:
    """Return non-content integrity failures for a receipt-enabled install."""

    manifest = load_manifest(install_dir) if manifest is None else manifest
    receipts = manifest.get("file_receipts") if isinstance(manifest, dict) else None
    if not isinstance(receipts, list):
        return ["install manifest has no file receipts"]
    failures: list[str] = []
    for receipt in receipts:
        if not isinstance(receipt, dict):
            failures.append("install manifest contains an invalid file receipt")
            continue
        path = Path(str(receipt.get("path") or ""))
        if not is_under(path, install_dir):
            failures.append(f"unsafe receipt path: {path}")
            continue
        if not path.is_file():
            failures.append(f"missing file: {path.name}")
            continue
        # `or -1` here once turned a legitimate 0 into "unreadable": onedir
        # payloads ship ~a dozen zero-byte files (py.typed, dist-info
        # REQUESTED markers, empty __init__.py) and every one failed size
        # verification because 0 is falsy. Only ABSENCE means unreadable.
        raw_size = receipt.get("size_bytes")
        try:
            expected_size = int(raw_size) if raw_size is not None else -1
        except (TypeError, ValueError):
            expected_size = -1
        expected_sha256 = str(receipt.get("sha256") or "").strip().lower()
        if expected_size < 0 or path.stat().st_size != expected_size:
            failures.append(f"size mismatch: {path.name}")
            continue
        if len(expected_sha256) != 64 or file_sha256(path).lower() != expected_sha256:
            failures.append(f"SHA256 mismatch: {path.name}")
    return failures


def stop_running_app(install_dir: Path) -> None:
    script = f"""
$installDir = {ps_quote(str(install_dir))}
$appName = {ps_quote(APP_NAME)}
$legacyName = {ps_quote(LEGACY_APP_NAME)}
$names = @($appName, $legacyName)
$targets = Get-CimInstance Win32_Process |
  Where-Object {{
    $name = [System.IO.Path]::GetFileNameWithoutExtension($_.Name)
    $path = [string]$_.ExecutablePath
    ($names -contains $name) -and (
      $path.StartsWith($installDir, [System.StringComparison]::OrdinalIgnoreCase) -or
      $name -eq $legacyName
    )
  }}
foreach ($target in $targets) {{
  try {{ Stop-Process -Id $target.ProcessId -Force -ErrorAction Stop }} catch {{ }}
}}
$taskkill = Join-Path $env:WINDIR 'System32\\taskkill.exe'
if (Test-Path $taskkill) {{
  & $taskkill /F /T /IM {ps_quote(APP_EXE_NAME)} 2>$null | Out-Null
  & $taskkill /F /T /IM {ps_quote(LEGACY_APP_EXE_NAME)} 2>$null | Out-Null
}}
$deadline = (Get-Date).AddSeconds(6)
do {{
  Start-Sleep -Milliseconds 150
  $stillRunning = @(Get-CimInstance Win32_Process |
    Where-Object {{
      $name = [System.IO.Path]::GetFileNameWithoutExtension($_.Name)
      $path = [string]$_.ExecutablePath
      ($names -contains $name) -and (
        $path.StartsWith($installDir, [System.StringComparison]::OrdinalIgnoreCase) -or
        $name -eq $legacyName
      )
    }})
}} while ($stillRunning.Count -gt 0 -and (Get-Date) -lt $deadline)
"""
    try:
        run_powershell(script)
    except RuntimeError:
        pass


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def copy_payload_file(source: Path, destination: Path) -> None:
    if not source.exists():
        candidates = payload_candidates(source.name)
        source = next((candidate for candidate in candidates if candidate.exists()), source)
    if not source.exists():
        searched = ", ".join(str(candidate) for candidate in payload_candidates(source.name))
        raise RuntimeError(f"Missing installer payload: {source.name}. Searched: {searched}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    try:
        shutil.copystat(source, destination)
    except OSError:
        pass
    if source.stat().st_size != destination.stat().st_size or file_sha256(source) != file_sha256(destination):
        destination.unlink(missing_ok=True)
        raise RuntimeError(f"Installer payload verification failed: {source.name}")


@contextlib.contextmanager
def staged_install_transaction(
    install_dir: Path,
    payloads: list[tuple[Path, Path]],
    *,
    before_commit: Callable[[], None] | None = None,
) -> Iterator[list[Path]]:
    """Stage a complete payload and restore the previous install on commit failure."""
    install_dir = Path(os.path.abspath(str(install_dir)))
    install_dir.parent.mkdir(parents=True, exist_ok=True)
    transaction_root = Path(
        tempfile.mkdtemp(prefix=f".{install_dir.name}-update-", dir=str(install_dir.parent))
    )
    staging_root = transaction_root / "staging"
    backup_root = transaction_root / "backup"
    staged: list[tuple[Path, Path]] = []
    backed_up: list[tuple[Path, Path]] = []
    placed: list[Path] = []
    cleanup_transaction = True

    try:
        for source, destination in payloads:
            destination = Path(os.path.abspath(str(destination)))
            if not is_under(destination, install_dir):
                raise RuntimeError(f"Refusing to install outside the app folder: {destination}")
            relative = Path(os.path.relpath(destination, install_dir))
            staged_path = staging_root / relative
            copy_payload_file(source, staged_path)
            staged.append((staged_path, destination))

        if before_commit is not None:
            before_commit()
        install_dir.mkdir(parents=True, exist_ok=True)

        manifest = load_manifest(install_dir)
        raw_files = manifest.get("files")
        previous_files = [Path(raw) for raw in raw_files if isinstance(raw, str)] if isinstance(raw_files, list) else []
        previous_files.extend(destination for _source, destination in staged if destination.exists())

        seen: set[str] = set()
        for original in previous_files:
            key = norm_path(original)
            if key in seen or not is_under(original, install_dir) or not original.is_file():
                continue
            seen.add(key)
            relative = Path(os.path.relpath(original, install_dir))
            backup = backup_root / relative
            backup.parent.mkdir(parents=True, exist_ok=True)
            os.replace(original, backup)
            backed_up.append((original, backup))

        for staged_path, destination in staged:
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staged_path, destination)
            placed.append(destination)

        yield [destination for _source, destination in staged]
    except Exception as error:
        rollback_errors: list[str] = []
        for destination in reversed(placed):
            try:
                if destination.is_file():
                    destination.unlink()
            except OSError as rollback_error:
                rollback_errors.append(str(rollback_error))
        for original, backup in reversed(backed_up):
            try:
                if backup.is_file():
                    original.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(backup, original)
            except OSError as rollback_error:
                rollback_errors.append(str(rollback_error))
        if rollback_errors:
            cleanup_transaction = False
            raise RuntimeError(
                "Install failed and automatic rollback was incomplete. "
                f"Recovery files remain at {transaction_root}: {'; '.join(rollback_errors)}"
            ) from error
        raise
    finally:
        if cleanup_transaction:
            shutil.rmtree(transaction_root, ignore_errors=True)


def safe_delete_file(path: Path, install_dir: Path, current_exe: Path, skipped_self: list[Path]) -> None:
    if not is_under(path, install_dir):
        return
    try:
        if norm_path(path) == norm_path(current_exe):
            skipped_self.append(path)
            return
        if path.exists() and path.is_file():
            path.unlink()
    except OSError:
        pass


def remove_empty_dirs(paths: list[Path], install_dir: Path) -> None:
    for directory in sorted(set(paths), key=lambda item: len(str(item)), reverse=True):
        if not is_under(directory, install_dir):
            continue
        try:
            if directory.exists() and directory.is_dir():
                directory.rmdir()
        except OSError:
            pass


def remove_previous_install_files(install_dir: Path) -> None:
    """Remove files from the previous manifest before copying the new build.

    This gives update installs the clean-file behavior users expect from an
    uninstall/reinstall without touching private AppData config, history,
    dictionaries, snippets, scratchpad files, or Windows-vault credentials.
    """
    manifest = load_manifest(install_dir)
    raw_files = manifest.get("files")
    if not isinstance(raw_files, list):
        return
    current_exe = Path(sys.executable).resolve()
    skipped_self: list[Path] = []
    file_paths = [Path(raw) for raw in raw_files if isinstance(raw, str)]
    for path in file_paths:
        safe_delete_file(path, install_dir, current_exe, skipped_self)
    remove_empty_dirs([path.parent for path in file_paths], install_dir)


def schedule_self_cleanup(current_exe: Path, install_dir: Path) -> None:
    if not is_under(current_exe, install_dir):
        return
    cmd = (
        "ping 127.0.0.1 -n 3 > nul "
        f'& del /f /q "{current_exe}" > nul 2> nul '
        f'& rmdir "{install_dir}" > nul 2> nul'
    )
    subprocess.Popen(["cmd", "/c", cmd], creationflags=_detached_flags())


def install_app(options: dict[str, Any], report: Report) -> None:
    install_dir = Path(str(options["install_dir"])).expanduser()
    if is_dangerous_install_dir(install_dir):
        raise RuntimeError("Choose a normal app folder, not a drive, home, AppData, or Desktop root.")

    install_dir = Path(os.path.abspath(str(install_dir)))
    app_exe = install_dir / APP_EXE_NAME
    uninstaller = install_dir / UNINSTALL_EXE_NAME
    docs_dir = install_dir / "docs"
    # X-108: the app ships as an onedir folder (exe + _internal), copied file
    # by file through the same staged transaction so integrity, rollback and
    # the manifest cover every one of them. A single-exe payload is still
    # honoured so an old installer archive remains installable.
    payloads: list[tuple[Path, Path]] = []
    app_payload_root = resource_path("payload", "app")
    if app_payload_root.is_dir():
        for source in sorted(app_payload_root.rglob("*")):
            if source.is_file():
                payloads.append((source, install_dir / source.relative_to(app_payload_root)))
    else:
        payloads.append((payload_path(APP_EXE_NAME), app_exe))
    payloads.append((payload_path(UNINSTALL_EXE_NAME), uninstaller))
    for source_name, output_name in (
        ("START_HERE_WINDOWS.md", "START-HERE.md"),
        ("INSTALL.md", "INSTALL.md"),
        ("PROVIDERS.md", "PROVIDERS.md"),
        ("MODEL_CATALOG.md", "MODEL-CATALOG.md"),
        ("LICENSE", "LICENSE.txt"),
        ("NOTICE", "NOTICE.txt"),
        ("EULA.md", "EULA.md"),
        ("THIRD_PARTY_NOTICES.md", "THIRD_PARTY_NOTICES.md"),
        # Generated at build time from the bundled packages' own metadata.
        ("THIRD_PARTY_LICENSES.txt", "THIRD_PARTY_LICENSES.txt"),
    ):
        source = resource_path("payload", "docs", source_name)
        if source.exists():
            payloads.append((source, docs_dir / output_name))

    shortcuts: list[Path] = []
    if bool(options.get("start_menu", True)):
        shortcuts.append(start_menu_shortcut_path())
    if bool(options.get("desktop", True)):
        shortcuts.append(desktop_shortcut_path())
    if bool(options.get("startup", False)):
        shortcuts.append(startup_shortcut_path())

    report(0.08, "Staging verified app files...")

    def before_commit() -> None:
        report(0.16, "Stopping the current app...")
        stop_running_app(install_dir)

    try:
        with staged_install_transaction(install_dir, payloads, before_commit=before_commit) as installed_files:
            report(0.30, "Committing the update...")
            write_manifest(install_dir, installed_files, shortcuts)
            report(0.42, "Verifying installed files and repair receipts...")
            integrity_failures = verify_installed_payload(install_dir)
            if integrity_failures:
                (install_dir / MANIFEST_NAME).unlink(missing_ok=True)
                raise RuntimeError("Installed-file verification failed: " + "; ".join(integrity_failures))
    except PermissionError as error:
        raise RuntimeError("Quit Talk DAT!, then run the installer again.") from error

    migrate_legacy_user_data()

    report(0.52, "Creating shortcuts...")
    if start_menu_shortcut_path() in shortcuts:
        create_shortcut(start_menu_shortcut_path(), app_exe, "Launch Talk DAT! dictation overlay.")
    if desktop_shortcut_path() in shortcuts:
        create_shortcut(desktop_shortcut_path(), app_exe, "Launch Talk DAT! dictation overlay.")
    if startup_shortcut_path() in shortcuts:
        create_shortcut(startup_shortcut_path(), app_exe, "Start Talk DAT! when Windows signs in.")
    else:
        remove_shortcut(startup_shortcut_path())
    for legacy_shortcut in legacy_shortcut_paths():
        remove_shortcut(legacy_shortcut)

    report(0.70, "Registering Windows uninstaller...")
    register_uninstaller(install_dir, app_exe, uninstaller)

    report(0.86, "Finalizing...")
    if bool(options.get("launch", True)):
        subprocess.Popen([str(app_exe)], cwd=str(install_dir), creationflags=_detached_flags())

    # X-118: the Credential-Manager sentence was our jargon. The vault
    # behavior is unchanged; only the sentence says less.
    report(1.0, "Installed. Talk DAT! is ready.")


def silent_install_options() -> dict[str, Any]:
    install_dir = installed_location()
    is_update = bool(load_manifest(install_dir))
    return {
        "install_dir": install_dir,
        "desktop": desktop_shortcut_path().exists() if is_update else True,
        "start_menu": start_menu_shortcut_path().exists() if is_update else True,
        "startup": startup_shortcut_path().exists(),
        "launch": "--no-launch" not in {arg.lower() for arg in sys.argv[1:]},
    }


def silent_uninstall_options(args: set[str]) -> dict[str, Any]:
    return {
        "remove_shortcuts": True,
        "remove_user_data": "--remove-user-data" in args,
    }


def remove_private_user_data(data_dir: Path, legacy_data_dir: Path) -> None:
    config: dict[str, Any] = {}
    config_file = data_dir / "config.json"
    try:
        loaded = json.loads(config_file.read_text(encoding="utf-8-sig"))
        if isinstance(loaded, dict):
            config = loaded
    except (OSError, json.JSONDecodeError):
        pass
    delete_all_credentials(config)
    if data_dir.name == "TalkDat" and data_dir.exists():
        shutil.rmtree(data_dir, ignore_errors=True)
    if legacy_data_dir.exists():
        shutil.rmtree(legacy_data_dir, ignore_errors=True)


def uninstall_app(options: dict[str, Any], report: Report) -> None:
    install_dir = installed_location()
    if is_dangerous_install_dir(install_dir):
        raise RuntimeError("Install folder looks unsafe. Uninstall manually from Windows Apps.")
    install_dir = Path(os.path.abspath(str(install_dir)))
    manifest = load_manifest(install_dir)
    current_exe = Path(sys.executable).resolve()
    skipped_self: list[Path] = []

    report(0.12, "Stopping Talk Dat!...")
    stop_running_app(install_dir)

    report(0.28, "Removing shortcuts...")
    if bool(options.get("remove_shortcuts", True)):
        for raw_path in manifest.get("shortcuts", []):
            if isinstance(raw_path, str):
                remove_shortcut(Path(raw_path))
        for path in (desktop_shortcut_path(), start_menu_shortcut_path(), startup_shortcut_path()):
            remove_shortcut(path)
        for path in legacy_shortcut_paths():
            remove_shortcut(path)

    report(0.48, "Removing installed app files...")
    raw_files = manifest.get("files")
    if not isinstance(raw_files, list):
        raw_files = [
            str(install_dir / APP_EXE_NAME),
            str(install_dir / UNINSTALL_EXE_NAME),
            str(install_dir / "docs" / "START-HERE.md"),
            str(install_dir / "docs" / "INSTALL.md"),
            str(install_dir / "docs" / "PROVIDERS.md"),
            str(install_dir / "docs" / "MODEL-CATALOG.md"),
            str(install_dir / "docs" / "LICENSE.txt"),
            str(install_dir / "docs" / "EULA.md"),
            str(install_dir / "docs" / "THIRD_PARTY_NOTICES.md"),
            str(install_dir / "docs" / "NOTICE.txt"),
            str(install_dir / "docs" / "THIRD_PARTY_LICENSES.txt"),
            str(install_dir / MANIFEST_NAME),
        ]
    file_paths = [Path(raw) for raw in raw_files if isinstance(raw, str)]
    for path in file_paths:
        safe_delete_file(path, install_dir, current_exe, skipped_self)

    report(0.68, "Cleaning empty folders...")
    remove_empty_dirs([path.parent for path in file_paths], install_dir)
    try:
        if install_dir.exists():
            install_dir.rmdir()
    except OSError:
        pass

    report(0.80, "Removing Windows registration...")
    unregister_uninstaller()

    if bool(options.get("remove_user_data", False)):
        report(0.90, "Removing private local user data...")
        remove_private_user_data(user_data_dir(), legacy_user_data_dir())

    if skipped_self:
        schedule_self_cleanup(current_exe, install_dir)

    report(1.0, "Uninstalled. Private user data was kept unless you selected removal.")


def rounded_rectangle(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], radius: int, fill: Any, outline: Any = None, width: int = 1) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def make_panel_image(width: int, height: int) -> Image.Image:
    """X-04: the panel is REAL clay, never coded graphics.

    The background is baked from the same AI-generated oxblood master the
    brand's site design uses, carrying the full glaze stack (tint, gold
    bloom, vignette, grain) pre-composited at 2x. Here it only gets
    cover-fitted, rounded, and floated on a soft shadow -- the 1990s glow
    ellipses and hatch lines this replaces are gone for good.

    X-118, the tester's verdict on the cut-out window: "looks cheap not
    premium." Colour-key transparency cannot antialias, so the card's
    rounded corners rendered as ragged stair-steps over the desktop. The
    card now sits on a SOLID night backdrop -- crisp corners, real shadow,
    a rectangle the OS can composite like any first-class window."""
    image = Image.new("RGBA", (width, height), (8, 10, 11, 255))

    shadow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    rounded_rectangle(shadow_draw, (20, 24, width - 20, height - 14), 32, (0, 0, 0, 170))
    image.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(18)))

    inner = (26, 20, width - 26, height - 22)
    inner_w = inner[2] - inner[0]
    inner_h = inner[3] - inner[1]
    try:
        clay = Image.open(asset_path("ui/installer-clay.jpg")).convert("RGB")
        scale = max(inner_w / clay.width, inner_h / clay.height)
        clay = clay.resize((round(clay.width * scale), round(clay.height * scale)), Image.Resampling.LANCZOS)
        left = (clay.width - inner_w) // 2
        top = (clay.height - inner_h) // 2
        clay = clay.crop((left, top, left + inner_w, top + inner_h)).convert("RGBA")
    except Exception:
        clay = Image.new("RGBA", (inner_w, inner_h), (26, 5, 10, 255))

    mask = Image.new("L", (inner_w, inner_h), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rounded_rectangle((0, 0, inner_w - 1, inner_h - 1), radius=30, fill=255)
    panel = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    panel.paste(clay, (inner[0], inner[1]), mask)

    border = ImageDraw.Draw(panel)
    rounded_rectangle(border, inner, 30, None, (201, 165, 90, 96), 1)
    image.alpha_composite(panel)
    return image

def load_logo(size: int) -> ImageTk.PhotoImage | None:
    for name in ("app_icon.png", "logo.png"):
        path = asset_path(name)
        if path.exists():
            image = Image.open(path).convert("RGBA").resize((size, size), Image.Resampling.LANCZOS)
            return ImageTk.PhotoImage(image)
    return None


def rounded_rect_points(x1: int, y1: int, x2: int, y2: int, radius: int) -> list[int]:
    """The 24-point outline every rounded control shares. With smooth=True the
    canvas turns the doubled corner vertices into quarter-round curves, which
    is the only way plain Tk draws a rounded rectangle without images. The old
    widget classes each carried a private copy of this list; the Round 2
    controls all call this one."""
    return [
        x1 + radius, y1,
        x2 - radius, y1,
        x2, y1,
        x2, y1 + radius,
        x2, y2 - radius,
        x2, y2,
        x2 - radius, y2,
        x1 + radius, y2,
        x1, y2,
        x1, y2 - radius,
        x1, y1 + radius,
        x1, y1,
    ]


class CanvasPill:
    """A pill button drawn as items on the MAIN canvas, not an embedded
    sub-canvas.

    X-118 round 2: every embedded tk.Canvas control carried its own
    TRANSPARENT_COLOR background, and once the window went solid those read
    as near-black boxes punched into the clay. Items on the shared canvas
    have no background at all. One smooth polygon plus one text item also
    retires the dual-oval-under-rectangle trick that made the old pills read
    as cheap."""

    VARIANTS: dict[str, tuple[str, str, str, str]] = {
        # variant: (fill, hover fill, outline, text)
        "primary": ("#ffb45d", "#ffd07b", "#fff1bf", INK),
        "ghost": (CHIP, CHIP_H, "#c9a55a", BODY),
        "danger": ("#2f1215", "#57191d", "#ff735f", "#fff0dc"),
    }
    DISABLED = ("#241318", "#241318", HAIR, "#8a7466")

    def __init__(
        self,
        canvas: tk.Canvas,
        cx: int,
        cy: int,
        width: int,
        height: int,
        text: str,
        command: Callable[[], None],
        variant: str = "primary",
        font_size: int = 10,
        tag: str = "pill",
        extra_tags: tuple[str, ...] = (),
    ) -> None:
        self.canvas = canvas
        self.width = width
        self.height = height
        self.command = command
        self.variant = variant
        self.tag = tag
        self.enabled = True
        self.hovered = False
        tags = (tag, "ui", *extra_tags)
        self.rect_id = canvas.create_polygon(
            rounded_rect_points(cx - width // 2, cy - height // 2, cx + width // 2, cy + height // 2, height // 2 - 4),
            smooth=True,
            tags=tags,
        )
        self.text_id = canvas.create_text(cx, cy, text=text, font=(BRAND_UI_FAMILY, font_size, "bold"), tags=tags)
        self._apply()
        # Bindings ride the unique tag, so they survive coords and state changes.
        canvas.tag_bind(tag, "<Button-1>", self._click)
        canvas.tag_bind(tag, "<Enter>", self._enter)
        canvas.tag_bind(tag, "<Leave>", self._leave)

    def _apply(self) -> None:
        fill, hover_fill, outline, text_color = self.VARIANTS[self.variant] if self.enabled else self.DISABLED
        if self.enabled and self.hovered:
            fill = hover_fill
        self.canvas.itemconfigure(self.rect_id, fill=fill, outline=outline, width=1)
        self.canvas.itemconfigure(self.text_id, fill=text_color)

    def set_text(self, text: str) -> None:
        self.canvas.itemconfigure(self.text_id, text=text)

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = bool(enabled)
        self._apply()

    def move_center(self, cx: int, cy: int) -> None:
        self.canvas.coords(
            self.rect_id,
            *rounded_rect_points(
                cx - self.width // 2, cy - self.height // 2, cx + self.width // 2, cy + self.height // 2, self.height // 2 - 4
            ),
        )
        self.canvas.coords(self.text_id, cx, cy)

    def show(self) -> None:
        self.canvas.itemconfigure(self.tag, state="normal")

    def hide(self) -> None:
        self.canvas.itemconfigure(self.tag, state="hidden")

    def _click(self, _event: tk.Event) -> None:
        if self.enabled:
            self.command()

    def _enter(self, _event: tk.Event) -> None:
        self.hovered = True
        self._apply()
        if self.enabled:
            self.canvas.configure(cursor="hand2")

    def _leave(self, _event: tk.Event) -> None:
        self.hovered = False
        self._apply()
        self.canvas.configure(cursor="")


class CanvasToggle:
    """ToggleRow's geometry redrawn as main-canvas items in the warm palette.

    Same 42px row with radius 14, dot oval at 15..29, check polyline
    18,21 -> 22,25 -> 28,17, label anchored west at x+42 -- only the colours
    and the host changed, so the control feels identical to use."""

    def __init__(
        self,
        canvas: tk.Canvas,
        x: int,
        y: int,
        text: str,
        variable: tk.BooleanVar,
        width: int = 320,
        tag: str = "toggle",
        extra_tags: tuple[str, ...] = (),
    ) -> None:
        self.canvas = canvas
        self.variable = variable
        self.tag = tag
        self.hovered = False
        self.hidden = False
        tags = (tag, "ui", *extra_tags)
        self.row_id = canvas.create_polygon(rounded_rect_points(x + 2, y + 4, x + width - 2, y + 38, 14), smooth=True, tags=tags)
        self.dot_id = canvas.create_oval(x + 15, y + 14, x + 29, y + 28, width=1, tags=tags)
        self.check_id = canvas.create_line(x + 18, y + 21, x + 22, y + 25, x + 28, y + 17, fill=CHIP, width=2, tags=tags)
        self.label_id = canvas.create_text(x + 42, y + 21, anchor="w", text=text, fill=BODY, font=(BRAND_UI_FAMILY, 9), tags=tags)
        self.refresh()
        canvas.tag_bind(tag, "<Button-1>", self._toggle)
        canvas.tag_bind(tag, "<Enter>", self._enter)
        canvas.tag_bind(tag, "<Leave>", self._leave)

    def refresh(self) -> None:
        """Re-sync colours and check visibility with the BooleanVar. Public
        because a group-tag show() turns EVERY tagged item back to normal,
        including the check mark of a toggle that is off."""
        value = bool(self.variable.get())
        self.canvas.itemconfigure(self.row_id, fill=CHIP_H if self.hovered else CHIP, outline=GOLD if value else HAIR, width=1)
        self.canvas.itemconfigure(self.dot_id, fill=GOLD if value else "#2a171c", outline="#fff0bd" if value else "#5a3a40")
        self.canvas.itemconfigure(self.check_id, state="hidden" if self.hidden or not value else "normal")

    def show(self) -> None:
        self.hidden = False
        self.canvas.itemconfigure(self.tag, state="normal")
        self.refresh()

    def hide(self) -> None:
        self.hidden = True
        self.canvas.itemconfigure(self.tag, state="hidden")

    def _toggle(self, _event: tk.Event) -> None:
        self.variable.set(not bool(self.variable.get()))
        self.refresh()

    def _enter(self, _event: tk.Event) -> None:
        self.hovered = True
        self.refresh()

    def _leave(self, _event: tk.Event) -> None:
        self.hovered = False
        self.refresh()


class GlassInstaller:
    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.root = tk.Tk()
        self.width = 820
        self.height = 612
        self.MARGIN = 72
        self.running = False
        self.in_progress_state = False
        self.expander_open = False
        self.drag_start: tuple[int, int, int, int] | None = None

        self.root.title(f"{APP_NAME} {'Uninstaller' if mode == 'uninstall' else 'Installer'}")
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self.root.overrideredirect(True)
        # X-118: solid window, full opacity. The colour-key cut-out corners
        # antialiased against nothing and read as cheap; 0.98 alpha made the
        # whole card faintly milky. A clean opaque rectangle is what premium
        # actually looks like.
        self.root.configure(bg="#080a0b")
        icon = asset_path("app_icon.ico")
        if icon.exists():
            try:
                self.root.iconbitmap(str(icon))
            except tk.TclError:
                pass

        self._center()
        self.canvas = tk.Canvas(
            self.root,
            width=self.width,
            height=self.height,
            bg="#080a0b",
            highlightthickness=0,
            bd=0,
        )
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<ButtonPress-1>", self._start_drag)
        self.canvas.bind("<B1-Motion>", self._drag)

        self.panel_image = ImageTk.PhotoImage(make_panel_image(self.width, self.height))
        self.canvas.create_image(0, 0, image=self.panel_image, anchor="nw")

        self._build_chrome()
        if mode == "uninstall":
            self._build_uninstall()
        else:
            self._build_install()

    def _center(self) -> None:
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        x = max(0, (screen_width - self.width) // 2)
        y = max(0, (screen_height - self.height) // 2)
        self.root.geometry(f"{self.width}x{self.height}+{x}+{y}")

    def _build_chrome(self) -> None:
        # Round 2: the animated rainbow band was the first thing the tester
        # called cheap. Chrome is now just brand, a hairline, and a close chip
        # -- all items on the shared canvas so nothing floats in its own box.
        self.logo_image = load_logo(48)
        if self.logo_image:
            self.canvas.create_image(96, 64, image=self.logo_image, anchor="center")
        self.canvas.create_text(130, 64, anchor="w", text=APP_NAME, fill=CREAM, font=(BRAND_UI_FAMILY, 20, "bold"))
        if self.mode == "uninstall":
            # X-118: say what a person cares about, not our jargon.
            self.canvas.create_text(
                700, 64, anchor="e", text="Your data stays unless you choose otherwise.", fill=MUTED, font=(BRAND_UI_FAMILY, 9)
            )
        self.canvas.create_oval(714, 50, 742, 78, fill=CHIP, outline=HAIR, tags=("btn_close", "ui"))
        self.close_text_id = self.canvas.create_text(728, 64, text="✕", fill=MUTED, font=(BRAND_UI_FAMILY, 11), tags=("btn_close", "ui"))
        self.canvas.tag_bind("btn_close", "<Button-1>", lambda _event: self._close())
        self.canvas.tag_bind("btn_close", "<Enter>", lambda _event: self.canvas.itemconfigure(self.close_text_id, fill=CREAM))
        self.canvas.tag_bind("btn_close", "<Leave>", lambda _event: self.canvas.itemconfigure(self.close_text_id, fill=MUTED))
        self.canvas.create_line(72, 112, 748, 112, fill=HAIR)

    def _build_install(self) -> None:
        self.install_dir_var = tk.StringVar(value=str(default_install_dir()))
        self.desktop_var = tk.BooleanVar(value=True)
        self.start_menu_var = tk.BooleanVar(value=True)
        self.startup_var = tk.BooleanVar(value=False)
        self.launch_var = tk.BooleanVar(value=True)

        # One decision on screen: the big Install button. Everything else is
        # quiet copy, a collapsed detail, or a toggle that already has the
        # right default.
        self.canvas.create_text(410, 168, text="Install Talk DAT!", fill=CREAM, font=(BRAND_UI_FAMILY, 24, "bold"), tags=("hero",))
        self.canvas.create_text(
            410,
            202,
            text=f"Version {APP_VERSION}  ·  Takes about a minute  ·  No admin needed",
            fill=MUTED,
            font=(BRAND_UI_FAMILY, 10),
            tags=("hero",),
        )
        self.primary_button = CanvasPill(
            self.canvas, 410, 266, 240, 56, "Install", self._start_install, variant="primary", font_size=12, tag="pill_primary", extra_tags=("hero",)
        )
        # Enter fires the one decision on screen, whatever the pill currently is.
        self.root.bind("<Return>", self._fire_primary)

        # The quiet location line: prefix, middle-truncated path, Change link.
        self.loc_prefix_id = self.canvas.create_text(72, 326, anchor="w", text="Installs to  ", fill=MUTED, font=(BRAND_UI_FAMILY, 9), tags=("hero",))
        self.loc_path_id = self.canvas.create_text(72, 326, anchor="w", text="", fill=BODY, font=(BRAND_UI_FAMILY, 9), tags=("hero",))
        self.loc_link_id = self.canvas.create_text(
            72, 326, anchor="w", text="Change", fill=GOLD, font=(BRAND_UI_FAMILY, 9, "bold"), tags=("hero", "link_change", "ui")
        )
        self.canvas.tag_bind("link_change", "<Button-1>", lambda _event: self._toggle_change())
        self.canvas.tag_bind("link_change", "<Enter>", self._link_enter)
        self.canvas.tag_bind("link_change", "<Leave>", self._link_leave)

        # Hidden expander: the one real Entry in the UI, plus a ghost Browse
        # pill. The band y=352..392 is reserved whitespace while collapsed so
        # opening it never reflows anything.
        self.dir_entry = tk.Entry(
            self.root,
            textvariable=self.install_dir_var,
            bg=FIELD,
            fg="#f2e6d8",
            insertbackground=GOLD,
            relief="flat",
            font=(BRAND_UI_FAMILY, 10),
            highlightthickness=1,
            highlightbackground=HAIR,
        )
        self.canvas.create_window(72, 352, anchor="nw", width=540, height=40, window=self.dir_entry, tags=("expander",))
        self.browse_button = CanvasPill(
            self.canvas, 687, 372, 122, 40, "Browse", self._browse, variant="ghost", tag="pill_browse", extra_tags=("expander",)
        )
        self.canvas.itemconfigure("expander", state="hidden")

        self.toggles = [
            CanvasToggle(self.canvas, 72, 408, "Desktop shortcut", self.desktop_var, tag="toggle_desktop", extra_tags=("hero",)),
            CanvasToggle(self.canvas, 72, 460, "Start menu shortcut", self.start_menu_var, tag="toggle_start_menu", extra_tags=("hero",)),
            CanvasToggle(self.canvas, 428, 408, "Launch when done", self.launch_var, tag="toggle_launch", extra_tags=("hero",)),
            CanvasToggle(self.canvas, 428, 460, "Start with Windows", self.startup_var, tag="toggle_startup", extra_tags=("hero",)),
        ]

        # The ONLY reassurance line; every extra footnote dilutes it.
        self.canvas.create_text(
            410,
            528,
            text="Everything stays on this PC. Uninstall anytime from Windows Settings.",
            fill=MUTED,
            font=(BRAND_UI_FAMILY, 9),
            tags=("hero",),
        )
        self._build_progress()
        self._layout_location_line()
        # Browse or typing updates the quiet line live; the full path only
        # ever lives in the variable, truncation is display-only.
        self.install_dir_var.trace_add("write", lambda *_args: self._layout_location_line())

    def _build_uninstall(self) -> None:
        self.remove_shortcuts_var = tk.BooleanVar(value=True)
        self.remove_user_data_var = tk.BooleanVar(value=False)
        install_dir = installed_location()

        self.canvas.create_text(410, 168, text="Uninstall Talk DAT!", fill=CREAM, font=(BRAND_UI_FAMILY, 24, "bold"), tags=("hero",))
        self.canvas.create_text(
            410, 202, text=self._truncate_path(str(install_dir)), fill=MUTED, font=(BRAND_UI_FAMILY, 10), tags=("hero",)
        )
        self.primary_button = CanvasPill(
            self.canvas, 410, 266, 240, 56, "Uninstall", self._start_uninstall, variant="danger", font_size=12, tag="pill_primary", extra_tags=("hero",)
        )
        self.toggles = [
            CanvasToggle(
                self.canvas, 72, 344, "Remove shortcuts and startup entry", self.remove_shortcuts_var, width=676, tag="toggle_shortcuts", extra_tags=("hero",)
            ),
            CanvasToggle(
                self.canvas, 72, 400, "Also remove private local user data", self.remove_user_data_var, width=676, tag="toggle_user_data", extra_tags=("hero",)
            ),
        ]
        self.canvas.create_text(
            410,
            470,
            text="Your config, Windows-vault provider keys, dictionaries, snippets, and transcript history are kept unless you choose to remove them.",
            fill=MUTED,
            font=(BRAND_UI_FAMILY, 9),
            tags=("hero",),
        )
        self._build_progress()

    def _build_progress(self) -> None:
        # The whole progress state lives on the same canvas, created hidden at
        # init and swapped in via tags -- no embedded bar widget, no second
        # layout pass.
        title = "Removing Talk DAT!" if self.mode == "uninstall" else "Installing Talk DAT!"
        self.progress_title_id = self.canvas.create_text(410, 240, text=title, fill=CREAM, font=(BRAND_UI_FAMILY, 16, "bold"), tags=("progress",))
        self.canvas.create_polygon(rounded_rect_points(72, 292, 748, 302, 4), smooth=True, fill=CHIP, outline=HAIR, width=1, tags=("progress",))
        self.progress_fill = self.canvas.create_rectangle(74, 294, 74, 300, fill=GOLD, outline="", tags=("progress",))
        self.canvas.itemconfigure("progress", state="hidden")
        # The Back pill deliberately does NOT carry the "progress" tag: the
        # group-show in _enter_progress must not reveal it. Failure shows it.
        self.back_button = CanvasPill(self.canvas, 410, 484, 132, 44, "Back", self._return_to_hero, variant="ghost", tag="pill_back")
        self.back_button.hide()
        # The shared status line. Hero validation refusals and progress text
        # both land here; deliberately untagged so state swaps never touch it.
        self.status_id = self.canvas.create_text(410, 556, text="", fill=MUTED, font=(BRAND_UI_FAMILY, 9))

    def _truncate_path(self, path: str, max_px: int = 440) -> str:
        """Middle-ellipsis for DISPLAY only -- the variable always keeps the
        full path. The middle is the part nobody reads; the drive plus first
        component and the trailing components are what a person recognises."""
        measure = getattr(self, "_path_font", None)
        if measure is None:
            measure = self._path_font = tkfont.Font(root=self.root, family=BRAND_UI_FAMILY, size=9)
        if measure.measure(path) <= max_px:
            return path
        keep = len(path)
        display = path
        while keep > 6 and measure.measure(display) > max_px:
            keep -= 2
            head = keep // 2
            display = path[:head] + "…" + path[len(path) - (keep - head):]
        return display

    def _layout_location_line(self) -> None:
        """Lay prefix + path + link left-to-right with 6px gaps, then shift
        the group so it centers on x=410. Runs at build, on every
        install_dir_var write, and whenever the link text changes width."""
        if self.mode != "install":
            return
        self.canvas.itemconfigure(self.loc_path_id, text=self._truncate_path(self.install_dir_var.get()))
        items = (self.loc_prefix_id, self.loc_path_id, self.loc_link_id)
        x = 72.0
        for item in items:
            self.canvas.coords(item, x, 326)
            bbox = self.canvas.bbox(item)
            if bbox is None:  # hidden during the progress state; laid out again on return
                return
            x = bbox[2] + 6
        left = self.canvas.bbox(items[0])[0]
        right = self.canvas.bbox(items[-1])[2]
        dx = 410 - (left + right) / 2
        for item in items:
            self.canvas.move(item, dx, 0)

    def _link_enter(self, _event: tk.Event) -> None:
        self.canvas.itemconfigure(self.loc_link_id, font=(BRAND_UI_FAMILY, 9, "bold", "underline"))
        self.canvas.configure(cursor="hand2")

    def _link_leave(self, _event: tk.Event) -> None:
        self.canvas.itemconfigure(self.loc_link_id, font=(BRAND_UI_FAMILY, 9, "bold"))
        self.canvas.configure(cursor="")

    def _toggle_change(self) -> None:
        # No reflow either way: the expander band is reserved whitespace when
        # collapsed. The entry shares install_dir_var, so Install always reads
        # the current value whether this is open or closed.
        if self.expander_open:
            self.expander_open = False
            self.canvas.itemconfigure("expander", state="hidden")
            self.canvas.itemconfigure(self.loc_link_id, text="Change")
        else:
            self.expander_open = True
            self.canvas.itemconfigure("expander", state="normal")
            self.canvas.itemconfigure(self.loc_link_id, text="Done")
            self.dir_entry.focus_set()
        self._layout_location_line()

    def _browse(self) -> None:
        selected = filedialog.askdirectory(
            title="Choose Talk DAT! install folder",
            initialdir=str(Path(self.install_dir_var.get()).parent),
        )
        if selected:
            self.install_dir_var.set(selected)

    def _start_install(self) -> None:
        if self.running:
            return
        # X-118, from the field: the tester could not install anywhere but
        # Downloads and never learned why. Every refusal now says its reason
        # in the progress line, and an unwise-but-legal folder warns once
        # and then obeys.
        chosen = Path(os.path.expandvars(os.path.expanduser(self.install_dir_var.get().strip() or str(default_install_dir()))))
        if is_dangerous_install_dir(chosen):
            self._set_progress(0, "That folder holds your whole profile. Pick a folder of its own. The suggested one works for everyone.", tone="warn")
            return
        probe_root = chosen if chosen.exists() else chosen.parent
        if not os.access(str(probe_root), os.W_OK):
            self._set_progress(0, "Windows needs administrator rights for that folder. Talk DAT! installs per user, so keep the suggested location or pick any folder you own.", tone="warn")
            return
        lowered = str(chosen).lower()
        risky = any(marker in lowered for marker in (os.sep + "downloads", os.sep + "desktop", os.sep + "temp"))
        if risky and not getattr(self, "_risky_dir_confirmed", "") == str(chosen):
            self._risky_dir_confirmed = str(chosen)
            self._set_progress(0, "That folder is easy to clear out by accident. Press Install again to use it anyway, or keep the suggested location.", tone="warn")
            return
        options = {
            "install_dir": str(chosen),
            "desktop": self.desktop_var.get(),
            "start_menu": self.start_menu_var.get(),
            "startup": self.startup_var.get(),
            "launch": self.launch_var.get(),
        }
        self._enter_progress()
        self._run_worker(lambda report: install_app(options, report), success_button="Close")

    def _start_uninstall(self) -> None:
        if self.running:
            return
        options = {
            "remove_shortcuts": self.remove_shortcuts_var.get(),
            "remove_user_data": self.remove_user_data_var.get(),
        }
        self._enter_progress()
        self._run_worker(lambda report: uninstall_app(options, report), success_button="Close")

    def _enter_progress(self) -> None:
        """Swap hero -> progress. The in_progress_state guard keeps a Retry
        (which re-enters through _start_install) from re-running the swap; it
        still re-arms the title and hides the result buttons for the new
        attempt."""
        if not self.in_progress_state:
            self.in_progress_state = True
            self.canvas.itemconfigure("hero", state="hidden")
            self.canvas.itemconfigure("expander", state="hidden")
            self.canvas.itemconfigure("progress", state="normal")
            self.primary_button.move_center(410, 420)
            self.canvas.coords(self.status_id, 410, 330)
        self.canvas.itemconfigure(
            self.progress_title_id,
            text="Removing Talk DAT!" if self.mode == "uninstall" else "Installing Talk DAT!",
        )
        self.primary_button.hide()
        self.back_button.hide()

    def _return_to_hero(self) -> None:
        self.canvas.itemconfigure("progress", state="hidden")
        self.back_button.hide()
        self.canvas.itemconfigure("hero", state="normal")
        # The group-show set every hero item to normal, including check marks
        # of toggles that are off -- re-sync each with its variable.
        for toggle in self.toggles:
            toggle.refresh()
        self.expander_open = False
        if self.mode == "install":
            self.canvas.itemconfigure(self.loc_link_id, text="Change")
            self._layout_location_line()
        self.canvas.coords(self.status_id, 410, 556)
        self._set_progress(0.0, "")
        self.primary_button.set_text("Uninstall" if self.mode == "uninstall" else "Install")
        self.primary_button.command = self._start_uninstall if self.mode == "uninstall" else self._start_install
        self.primary_button.move_center(410, 266)
        self.primary_button.set_enabled(True)
        self.primary_button.show()
        self.in_progress_state = False

    def _fire_primary(self, _event: tk.Event) -> None:
        if not self.running and self.primary_button.enabled:
            self.primary_button.command()

    def _run_worker(self, work: Callable[[Report], None], success_button: str) -> None:
        self.running = True
        self.primary_button.set_enabled(False)

        def report(progress: float, text: str) -> None:
            self.root.after(0, lambda: self._set_progress(progress, text))

        def target() -> None:
            try:
                work(report)
            except Exception as error:  # noqa: BLE001 - surfaced to the installer UI.
                # Bind the text now, not inside the lambda. Python deletes the
                # name bound by `except ... as` when the block exits, and this
                # lambda is deferred through root.after, so it ran after that
                # deletion and raised NameError instead of showing the failure.
                # Every install error was reported by a callback that itself
                # crashed.
                message = str(error)
                self.root.after(0, lambda: self._finish(False, message, success_button))
                return
            self.root.after(0, lambda: self._finish(True, "Done.", success_button))

        threading.Thread(target=target, daemon=True).start()

    def _finish(self, ok: bool, message: str, success_button: str) -> None:
        self.running = False
        if ok:
            self.canvas.itemconfigure(self.progress_title_id, text="Uninstalled." if self.mode == "uninstall" else "All set.")
            self._set_progress(1.0, message, tone="done")
            self.primary_button.set_text(success_button)
            self.primary_button.command = self._close
        else:
            self.canvas.itemconfigure(self.progress_title_id, text="Something needs attention")
            self._set_progress(0.0, message, tone="error")
            self.primary_button.set_text("Retry")
            self.primary_button.command = self._start_uninstall if self.mode == "uninstall" else self._start_install
            self.primary_button.move_center(410, 420)
            self.back_button.show()
        self.primary_button.set_enabled(True)
        self.primary_button.show()

    def _set_progress(self, progress: float, text: str, tone: str = "normal") -> None:
        # The bar stays GOLD at every stage -- the old swap to teal at 100%
        # broke the palette right at the moment that should feel most
        # finished. Tone only colours the status text.
        progress = max(0.0, min(1.0, progress))
        self.canvas.coords(self.progress_fill, 74, 294, 74 + int(672 * progress), 300)
        tone_fill = {"normal": MUTED, "warn": WARN, "error": ERR, "done": GOLD}.get(tone, MUTED)
        self.canvas.itemconfigure(self.status_id, text=text, fill=tone_fill)

    def _start_drag(self, event: tk.Event) -> None:
        # Controls are canvas items now, so a press may be a click, not a
        # drag. Items tagged "ui" own their clicks; only the quiet parts of
        # the card move the window.
        current = self.canvas.find_withtag("current")
        if current and "ui" in self.canvas.gettags(current[0]):
            self.drag_start = None
            return
        self.drag_start = (event.x_root, event.y_root, self.root.winfo_x(), self.root.winfo_y())

    def _drag(self, event: tk.Event) -> None:
        if not self.drag_start:
            return
        start_x, start_y, window_x, window_y = self.drag_start
        self.root.geometry(f"+{window_x + event.x_root - start_x}+{window_y + event.y_root - start_y}")

    def run(self) -> None:
        # The PyInstaller splash carried the brand from the first millisecond
        # of the double-click; the real window is up now, so it hands over.
        try:
            import pyi_splash  # type: ignore[import-not-found]

            pyi_splash.close()
        except Exception:
            pass
        self.root.mainloop()

    def _close(self) -> None:
        if self.running:
            return
        try:
            self.root.destroy()
        except tk.TclError:
            pass


def main(default_mode: str | None = None) -> None:
    mode = default_mode
    args = {arg.lower() for arg in sys.argv[1:]}
    exe_name = Path(sys.argv[0]).stem.lower()
    silent = bool(args & {"--silent", "--silent-install", "--silent-uninstall", "/silent", "/verysilent"})
    if "--uninstall" in args or "uninstall" in exe_name:
        mode = "uninstall"
    if "--install" in args or mode is None:
        mode = mode or "install"

    if os.name != "nt":
        raise SystemExit("Talk DAT! installer is Windows-only.")
    if silent:
        # No UI is coming; the extraction splash must not outlive the click.
        try:
            import pyi_splash  # type: ignore[import-not-found]

            pyi_splash.close()
        except Exception:
            pass
    if silent and mode == "install":
        options = silent_install_options()

        def report(progress: float, text: str) -> None:
            line = f"{int(progress * 100):3d}% {text}"
            write_installer_log(line)
            try:
                print(line, flush=True)
            except OSError:
                pass

        try:
            write_installer_log(f"Starting silent install v{APP_VERSION} from {sys.executable}")
            install_app(options, report)
            write_installer_log("Silent install completed.")
        except Exception as error:
            write_installer_log(f"Silent install failed: {error}")
            write_installer_log(traceback.format_exc())
            raise SystemExit(1) from error
        return
    if silent and mode == "uninstall":
        options = silent_uninstall_options(args)

        def report(progress: float, text: str) -> None:
            line = f"{int(progress * 100):3d}% {text}"
            write_installer_log(line)
            try:
                print(line, flush=True)
            except OSError:
                pass

        try:
            write_installer_log(f"Starting silent uninstall v{APP_VERSION} from {sys.executable}")
            uninstall_app(options, report)
            write_installer_log("Silent uninstall completed.")
        except Exception as error:
            write_installer_log(f"Silent uninstall failed: {error}")
            write_installer_log(traceback.format_exc())
            raise SystemExit(1) from error
        return
    GlassInstaller(mode).run()


if __name__ == "__main__":
    main()
