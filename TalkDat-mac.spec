# -*- mode: python ; coding: utf-8 -*-
"""macOS app bundle for Talk DAT!.

Unlike the Windows spec this file is in version control on purpose. The Windows
one is gitignored, and the guard test for the cryptography landmine reads it, so
on a clean checkout that test errors instead of guarding anything -- the exact
failure it exists to prevent could ship again unnoticed. This spec is committed
so the same guard means something on macOS.

Build:  pyinstaller --noconfirm --clean TalkDat-mac.spec
Result: dist/Talk DAT!.app
"""

import plistlib
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, copy_metadata

ROOT = Path(SPECPATH)


def _app_version() -> str:
    """Read APP_VERSION out of version.py without importing the package.

    Importing knight_flow here would drag tkinter and the whole dependency tree
    into the build process. The file is two assignments; reading it is enough.
    """
    text = (ROOT / "knight_flow" / "version.py").read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.startswith("APP_VERSION"):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("APP_VERSION not found in knight_flow/version.py")


APP_VERSION = _app_version()
# CFBundleVersion must be dot-separated digits only, so "0.4.39-beta" becomes
# "0.4.39". CFBundleShortVersionString keeps the full label the user sees.
NUMERIC_VERSION = APP_VERSION.split("-", 1)[0]


def _write_version_resource() -> dict:
    """Generate the Info.plist version keys from APP_VERSION at build time.

    The Windows build generates its version resource the same way, after a
    release reported 0.4.34 in its file properties because the stamp in build/
    was reused. Deriving both from one constant is what stops the binary and the
    number a user reads from drifting apart.
    """
    return {
        "CFBundleShortVersionString": APP_VERSION,
        "CFBundleVersion": NUMERIC_VERSION,
    }


_VERSION_RESOURCE = _write_version_resource()

# cryptography's real work is in a compiled extension reached through dynamic
# imports, which PyInstaller's static analysis can miss -- and when it does the
# build still reports success. 0.4.35 shipped that way and died before a line of
# our own code ran. Named explicitly here, both ways.
crypto_datas, crypto_binaries, crypto_hidden = collect_all('cryptography')
ct2_datas, ct2_binaries, ct2_hidden = collect_all('ctranslate2')
ort_datas, ort_binaries, ort_hidden = collect_all('onnxruntime')

datas = []
datas += crypto_datas + ct2_datas + ort_datas
datas += collect_data_files("webview")
datas += [(str(ROOT / "knight_flow" / "web_shell" / "shell_assets"), "knight_flow/web_shell/shell_assets")]
datas += collect_data_files("faster_whisper")
datas += collect_data_files("onnx_asr")
datas += copy_metadata("onnx-asr")
datas += copy_metadata("faster-whisper")
datas += copy_metadata("ctranslate2")

# Runtime assets. The pill animation frames and the licence public key are read
# from disk at startup; a bundle without them starts and then cannot verify a
# licence or draw itself.
for asset in (
    "app_icon.png",
    "app_icon.ico",
    "logo.png",
    "flow_pill_240.json",
    "flow_pill_240.png",
    "loading_pill_240.json",
    "loading_pill_240.png",
    "license_public_key.pem",
):
    path = ROOT / "knight_flow" / "assets" / asset
    if path.exists():
        datas.append((str(path), "knight_flow/assets"))

ui_assets = ROOT / "knight_flow" / "assets" / "ui"
if ui_assets.is_dir():
    for path in sorted(ui_assets.iterdir()):
        if path.is_file():
            datas.append((str(path), "knight_flow/assets/ui"))

# Setup's six generated art panels are read by name at runtime, and
# PyInstaller does not infer image files: a bundle without them shows blank
# artwork. Same manifest as the Windows spec, pinned on both platforms by
# tests/test_build_bundles_what_the_app_needs.py.
_ASSETS = ROOT / "knight_flow" / "assets"
_ONBOARDING_ASSETS = (
    "01-arrival-stone.png",
    "02-access-continuity.png",
    "03-route-engine.png",
    "04-voice-instrument.png",
    "05-command-deck.png",
    "06-finish-engine.png",
)
datas += [
    (str(_ASSETS / "onboarding" / filename), "knight_flow/assets/onboarding")
    for filename in _ONBOARDING_ASSETS
]

# X-381: parity with the Windows spec. The theme material strips, the brand
# font, the runtime icon set and the offline changelog were never bundled
# here. Every loader falls back quietly -- flat colour, the system font, no
# icon, no offline release notes -- which is how four Mac releases shipped
# plainer than Windows without a single error. Guarded on both platforms by
# tests/test_build_bundles_what_the_app_needs.py.
datas += [
    # X-70: the What's New tab's offline floor -- the build carries its own
    # changelog so release notes exist even with no network.
    (str(ROOT / "CHANGELOG.md"), "."),
    (str(_ASSETS / "fonts" / "KnightDisplay.ttf"), "knight_flow/assets/fonts"),
    (str(_ASSETS / "favicon.ico"), "knight_flow/assets"),
    (str(_ASSETS / "favicon.png"), "knight_flow/assets"),
]
# X-352: the generated theme-material strips. A glob, not a hand list --
# fifty files that must never drift from the theme catalog one by one.
datas += [
    (str(path), "knight_flow/assets/materials")
    for path in sorted((_ASSETS / "materials").glob("*.png"))
]
datas += [(str(_ASSETS / "materials" / name), "knight_flow/assets/materials/" + name)
          for name in ("shared", "original-v2", "enhanced")]
datas += [
    (
        str(path),
        "knight_flow/assets/ui/icons/imagegen-v1/runtime",
    )
    for path in sorted(
        (_ASSETS / "ui" / "icons" / "imagegen-v1" / "runtime").glob("*.png")
    )
]

binaries = crypto_binaries + ct2_binaries + ort_binaries

hiddenimports = crypto_hidden + ct2_hidden + ort_hidden
hiddenimports += ["webview.platforms.cocoa", "WebKit", "AppKit", "Foundation", "objc"]
hiddenimports += [
    "cryptography.hazmat.bindings._rust",
    # pystray picks its backend at import time; the macOS one is never reached
    # by static analysis because the choice is made from sys.platform.
    "pystray._darwin",
    "PIL._tkinter_finder",
    # pynput does the same thing for its listener backends.
    "pynput.keyboard._darwin",
    "pynput.mouse._darwin",
    # X-23. Every AVFoundation call in this codebase sits inside a function
    # behind a try, so that a machine without the framework degrades instead of
    # crashing. That same shape means a bundle which drops it raises nothing:
    # microphone_permission just answers "unknown" forever, the permission
    # checklist can never tick, and the one signal that separates a refused
    # microphone from a quiet room is gone. Named explicitly for that reason.
    "AVFoundation",
    "CoreMedia",
    # X-451: keyring picks its backend at import time through entry points, so
    # static analysis never sees the macOS one. Without these the bundle ships
    # no credential store and the signed licence has nowhere to live.
    "keyring.backends.macOS",
    "keyring.backends.macOS.api",
    "keyring.backends",
    "keyring.backends.chainer",
    "keyring.backends.fail",
    "keyring.backends.null",
]
try:
    from PyInstaller.utils.hooks import copy_metadata as _copy_metadata
    datas += _copy_metadata("keyring")  # backend discovery reads the dist metadata
except Exception:
    pass

sys.path.insert(0, str(ROOT))
from scripts.pdf_bundle import collect_pdf_runtime
from scripts.mac_bundle import collect_system_audio

pdf_datas, pdf_binaries, pdf_imports = collect_pdf_runtime(ROOT)
datas += pdf_datas
binaries += pdf_binaries + collect_system_audio(ROOT)
hiddenimports += pdf_imports

a = Analysis(
    [str(ROOT / "talk_dat.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(ROOT / "scripts" / "pyi_pdf_runtime.py")],
    # cv2 would arrive through pyautogui -> pyscreeze for image matching this
    # product never performs. X-476: the CUDA wheels are 1.2 GB and help
    # only NVIDIA machines, which a Mac never is; the runtime fetches them on
    # request and nothing here bundles them.
    # openwakeword imports scipy and sklearn during package initialization,
    # including inference. Excluding either makes installed wake models fail.
    # Open source (2026-09-23), the same five as "Talk Dat!.spec": pyautogui's
    # optional helpers stay out. knight_flow/paste.py uses pyautogui for key
    # presses only; pyautogui imports each of these inside try/except
    # ImportError, and its macOS backend (_pyautogui_osx) imports none of them.
    # mouseinfo is GPL-3.0-or-later and pymsgbox is classified GPLv3+, so
    # neither may ride along in a binary by accident.
    # tests/test_mac_build_ships_the_licenses.py pins the list.
    excludes=[
        "scikit-learn", "cv2", "nvidia",
        "mouseinfo", "pymsgbox", "pyscreeze", "pygetwindow", "pyrect",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Talk DAT!",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    # X-11: macOS delivers a talkdat:// open as an Apple Event, not argv.
    # argv_emulation turns the COLD-START event into argv, which is what
    # talk_dat.py's second-instance branch reads. The already-running case is
    # handled by mac_support.watch_url_scheme, because the system sends that
    # one to the live process and never starts a second.
    argv_emulation=True,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Talk DAT!",
)

app = BUNDLE(
    coll,
    name="Talk DAT!.app",
    icon=str(ROOT / "build-mac" / "TalkDat.icns"),
    bundle_identifier="com.knightaiav.talkdat",
    version=_VERSION_RESOURCE["CFBundleShortVersionString"],
    info_plist={
        **_VERSION_RESOURCE,
        "CFBundleName": "Talk DAT!",
        "CFBundleDisplayName": "Talk DAT!",
        # Without this key macOS kills the process the moment it opens an input
        # device, with no prompt and no error the app can catch.
        "NSMicrophoneUsageDescription": (
            "Talk DAT! records your voice only while you hold the dictation key, "
            "and transcribes it on this Mac unless you choose a cloud provider."
        ),
        # The Pill is the interface. A Dock icon and an application menu would be
        # a second, emptier copy of it, so the app lives in the menu bar instead.
        "LSUIElement": True,
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "14.0",
        "NSHumanReadableCopyright": "Knight AI+AV",
        # The scheme is declared here rather than registered at runtime; macOS
        # has no per-user equivalent of the HKCU key Windows writes.
        # X-351: Talk DAT! in every app's right-click menu -- the native
        # Services extension point. Selectors live in
        # knight_flow/mac_services.py; returning a string on the pasteboard
        # is what makes macOS replace the selection in place.
        "NSServices": [
            {
                "NSMenuItem": {"default": "Talk DAT!: Rewrite"},
                "NSMessage": "rewriteSelection",
                "NSPortName": "Talk Dat!",
                "NSSendTypes": ["NSStringPboardType"],
                "NSReturnTypes": ["NSStringPboardType"],
            },
            {
                "NSMenuItem": {"default": "Talk DAT!: Rewrite with prompt"},
                "NSMessage": "promptedRewriteSelection",
                "NSPortName": "Talk Dat!",
                "NSSendTypes": ["NSStringPboardType"],
                "NSReturnTypes": ["NSStringPboardType"],
            },
        ],
        "CFBundleURLTypes": [
            {
                "CFBundleURLName": "com.knightaiav.talkdat.signin",
                "CFBundleURLSchemes": ["talkdat"],
            }
        ],
    },
)
