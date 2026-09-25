# -*- mode: python ; coding: utf-8 -*-
# CURATED SPEC -- do not regenerate with the PyInstaller CLI. A CLI run on
# 2026-08-08 silently replaced this file and dropped both guards below; the
# repo now tracks it and tests/test_build_bundles_what_the_app_needs.py
# fails the suite if either guard goes missing again.
from pathlib import Path
import sys

from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.hooks import collect_all
from PyInstaller.utils.hooks import copy_metadata

ROOT = Path(SPECPATH)


def _write_version_resource() -> str:
    """Generate the Windows VERSIONINFO from APP_VERSION at build time.

    The stamp is derived, never hand-edited: a stale hand-written resource is
    a quieter version of the shipped-but-wrong-version bug. Non-numeric tags
    (like -beta) ride in the string fields; the numeric quadruple comes from
    the digits alone.
    """
    import re
    import sys

    sys.path.insert(0, str(ROOT))
    from knight_flow.version import APP_VERSION

    numbers = [int(part) for part in re.findall(r"\d+", APP_VERSION)][:3]
    while len(numbers) < 3:
        numbers.append(0)
    quad = ", ".join(str(n) for n in (*numbers, 0))
    out = ROOT / "build" / "talk-dat-version-info.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({quad}),
    prodvers=({quad}),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable('040904B0', [
        StringStruct('CompanyName', 'Knight AI+AV'),
        StringStruct('FileDescription', 'Talk DAT! dictation overlay'),
        StringStruct('FileVersion', '{APP_VERSION}'),
        StringStruct('ProductName', 'Talk DAT!'),
        StringStruct('ProductVersion', '{APP_VERSION}'),
        StringStruct('LegalCopyright', 'Copyright Knight AI+AV'),
        StringStruct('OriginalFilename', 'Talk Dat!.exe'),
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
""",
        encoding="utf-8",
    )
    return str(out)


_ASSETS = ROOT / "knight_flow" / "assets"
_ONBOARDING_ASSETS = (
    "01-arrival-stone.png",
    "02-access-continuity.png",
    "03-route-engine.png",
    "04-voice-instrument.png",
    "05-command-deck.png",
    "06-finish-engine.png",
)
datas = [
    # X-70: the What's New tab's offline floor -- the build carries its own
    # changelog so release notes exist even with no network.
    (str(ROOT / "CHANGELOG.md"), "."),
    (str(_ASSETS / "fonts" / "KnightDisplay.ttf"), "knight_flow/assets/fonts"),
    (str(_ASSETS / "app_icon.ico"), "knight_flow/assets"),
    (str(_ASSETS / "app_icon.png"), "knight_flow/assets"),
    (str(_ASSETS / "favicon.ico"), "knight_flow/assets"),
    (str(_ASSETS / "favicon.png"), "knight_flow/assets"),
    (str(_ASSETS / "flow_pill_240.png"), "knight_flow/assets"),
    (str(_ASSETS / "flow_pill_240.json"), "knight_flow/assets"),
    (str(_ASSETS / "loading_pill_240.png"), "knight_flow/assets"),
    (str(_ASSETS / "loading_pill_240.json"), "knight_flow/assets"),
    (str(_ASSETS / "logo.ico"), "knight_flow/assets"),
    (str(_ASSETS / "logo.png"), "knight_flow/assets"),
    (str(_ASSETS / "license_public_key.pem"), "knight_flow/assets"),
    (str(_ASSETS / "ui" / "flow-console-material.png"), "knight_flow/assets/ui"),
    (str(_ASSETS / "ui" / "processing-spectrum-loop-4k.png"), "knight_flow/assets/ui"),
]
# X-352: the generated theme-material strips. A glob, not a hand list --
# fifty files that must never drift from the theme catalog one by one.
datas += [
    (str(path), "knight_flow/assets/materials")
    for path in sorted((_ASSETS / "materials").glob("*.png"))
]
datas += [
    (str(_ASSETS / "onboarding" / filename), "knight_flow/assets/onboarding")
    for filename in _ONBOARDING_ASSETS
]
datas += [
    (
        str(path),
        "knight_flow/assets/ui/icons/imagegen-v1/runtime",
    )
    for path in sorted(
        (_ASSETS / "ui" / "icons" / "imagegen-v1" / "runtime").glob("*.png")
    )
]
binaries = []
# Explicit WASAPI loopback extension and its bundled native component.
_loopback_data, _loopback_binaries, _loopback_imports = collect_all("pyaudiowpatch")
datas += _loopback_data
binaries += _loopback_binaries
# The module the 0.4.38 crash actually named. Naming it is belt and braces on
# top of collect_all below -- PyInstaller drops native extensions silently,
# and a build that loses this one starts to nothing but a traceback dialog.
hiddenimports = ["pystray._win32", "PIL._tkinter_finder", "cryptography.hazmat.bindings._rust"] + _loopback_imports
datas += collect_data_files("webview")
datas += [(str(ROOT / "knight_flow" / "web_shell" / "shell_assets"), "knight_flow/web_shell/shell_assets")]
datas += [(str(_ASSETS / "materials" / "shared"), "knight_flow/assets/materials/shared")]
datas += [(str(_ASSETS / "materials" / "original-v2"), "knight_flow/assets/materials/original-v2")]
datas += [(str(_ASSETS / "materials" / "enhanced"), "knight_flow/assets/materials/enhanced")]
hiddenimports += ["webview.platforms.winforms", "webview.platforms.edgechromium", "clr_loader.netfx", "pythonnet"]

# Generate the accessibility typelib during the build, so the installed app
# needs neither a writable installation directory nor runtime code generation.
from comtypes.client import GetModule
_uia_module = GetModule("UIAutomationCore.dll")
hiddenimports += [_uia_module.__name__, _uia_module.__wrapper_module__.__name__]

datas += collect_data_files("faster_whisper")
datas += collect_data_files("onnx_asr")
datas += copy_metadata("onnx-asr")
datas += copy_metadata("faster-whisper")
datas += copy_metadata("ctranslate2")
tmp_ret = collect_all('ctranslate2')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('onnxruntime')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('cryptography')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

sys.path.insert(0, str(ROOT))
from scripts.pdf_bundle import collect_pdf_runtime
pdf_datas, pdf_binaries, pdf_imports = collect_pdf_runtime(ROOT)
datas += pdf_datas; binaries += pdf_binaries; hiddenimports += pdf_imports

_VERSION_RESOURCE = _write_version_resource()

a = Analysis(
    [str(ROOT / "talk_dat.py")],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(ROOT / "scripts" / "pyi_pdf_runtime.py")],
    # X-475: "nvidia" is the CUDA wheels (nvidia-cublas-cu12,
    # nvidia-cudnn-cu12). They are 1.2 GB and MUST NOT be bundled: the
    # installer is 465 MB and they only help NVIDIA machines. The build
    # installs into the same .venv a developer tests in, so one
    # "pip install" while measuring would otherwise triple the download
    # for every user on earth. make_cuda_libraries_reachable() finds them
    # at RUNTIME if a machine has them; nothing ships them.
    # openwakeword imports its verifier module during package initialization;
    # that import requires scipy and sklearn even for ordinary inference.
    # Open source (2026-09-23): pyautogui's optional helpers stay out. The app
    # only presses keys through pyautogui, which imports every one of these
    # inside try/except ImportError. mouseinfo is GPL-3.0-or-later and pymsgbox
    # is classified GPLv3+; tests/test_third_party_licenses.py pins the list.
    excludes=[
        "scikit-learn", "cv2", "nvidia",
        "mouseinfo", "pymsgbox", "pyscreeze", "pygetwindow", "pyrect",
    ],
    noarchive=False,
    optimize=0,
)
# X-761 (IP audit 2026-09-24): sounddevice's wheel carries PortAudio twice, a
# plain build and one compiled with Steinberg's ASIO SDK (the *-asio.dll
# files). sounddevice loads the ASIO build only when SD_ENABLE_ASIO is set,
# which Talk DAT! never does, and Steinberg's SDK comes under Steinberg's own
# license, not PortAudio's MIT one. Shipping unused code under terms nobody
# signed buys nothing, so the ASIO builds stay out.
_ASIO_BUILD = r"(?i)-asio\.(dll|dylib)$"
import re as _re
a.binaries = [entry for entry in a.binaries if not _re.search(_ASIO_BUILD, entry[0])]
a.datas = [entry for entry in a.datas if not _re.search(_ASIO_BUILD, entry[0])]
pyz = PYZ(a.pure)

# X-108: ONEDIR, deliberately. Onefile extracted 1,653 files into %TEMP% on
# EVERY launch, and anything racing that extraction (AV scans, temp sweepers)
# tore it mid-write -- two of four launches on 2026-08-15 died at
# "numpy._core not found" with 29 of 1,653 files extracted, and 131 orphaned
# _MEI dirs (37.8 GB) were squatting in temp from force-killed instances.
# Onedir installs the files once and launches touch nothing in %TEMP%:
# nothing to extract, nothing to tear, nothing to sweep, instant starts.
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Talk Dat!",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=_VERSION_RESOURCE,
    icon=[str(_ASSETS / "app_icon.ico")],
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="Talk Dat!",
)
