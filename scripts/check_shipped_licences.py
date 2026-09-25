"""Release gate: the licence texts are IN the thing people download.

X-763 (IP audit, 2026-09-24). The build inputs can be right while the
artifact is wrong: a packager can drop a file (D-REC's Mac build lost
Electron's and Chromium's), and a generated file can name a component without
its text (Talk DAT! 0.4.167 did, X-760). So this reads the BUILT artifact, not
the config, and fails when any required notice is missing from it.

    python scripts/check_shipped_licences.py "dist/Talk Dat!"              # the app folder
    python scripts/check_shipped_licences.py release/Talk-Dat.msix          # the Store package
    python scripts/check_shipped_licences.py dist/release/Talk-Dat-Windows-Portable.zip
    python scripts/check_shipped_licences.py "dist/Talk Dat! Installer.exe" # the installer
    python scripts/check_shipped_licences.py "dist-mac/Talk DAT!.app"      # the Mac app

Exit 0 when everything required is there, 1 with one line per gap.

What it requires:
  * LICENSE (the Apache-2.0 text), NOTICE (Talk DAT!'s own notice with the
    Parakeet CC BY 4.0 attribution, the change note and the Silero credit) and
    THIRD_PARTY_LICENSES.txt, beside the program;
  * in THIRD_PARTY_LICENSES.txt, the texts every build needs (Python's PSF
    license, the PyInstaller Bootloader Exception, the LGPL-3.0 and GPL-3.0
    texts for pynput and pystray, the Apache text, the written offer), plus
    the text of every part whose FILE is in the artifact (Tcl/Tk, FFmpeg,
    Silero VAD, PortAudio, the WebView2 SDK, Intel OpenMP, cuDNN, the .NET
    facades, CTranslate2, ONNX Runtime, onnx-asr, numpy, Pillow, pywebview);
  * no component listed by name only ("ships no license file");
  * the OFL text for any font other than Talk DAT!'s own Knight Display;
  * no PortAudio ASIO build (X-761).
"""
from __future__ import annotations

import re
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable

# Every build, whatever it carries.
LICENSE_MARKERS = ("Apache License", "Version 2.0, January 2004",
                   "TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION", "END OF TERMS AND CONDITIONS")
NOTICE_MARKERS = (
    "Copyright 2026 Knight AI+AV LLC",
    "Parakeet TDT 0.6B v3",
    "Creative Commons Attribution 4.0 International License",
    "https://creativecommons.org/licenses/by/4.0/",
    "https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3",
    "Changes:",
    "Silero VAD",
)
ALWAYS = (
    ("the licence file's own header", "Talk DAT! -- third-party software licenses"),
    ("Python (PSF license text)", "PYTHON SOFTWARE FOUNDATION LICENSE VERSION 2"),
    ("the PyInstaller bootloader (Bootloader Exception)", "Bootloader Exception"),
    ("pynput and pystray (LGPL-3.0 text)", "GNU LESSER GENERAL PUBLIC LICENSE"),
    ("pynput and pystray (GPL-3.0 text the LGPL builds on)", "Version 3, 29 June 2007"),
    ("Apache-2.0 components (license text)", "Version 2.0, January 2004"),
    ("the written offer for GPL/LGPL source", "WRITTEN OFFER FOR SOURCE CODE"),
)
# (part, a file pattern in the artifact, lines its text must bring along)
BY_FILE = (
    ("Tcl/Tk", r"(^|/)(tcl86t\.dll|tk86t\.dll|_tk_data/|_tcl_data/|libtcl[89][^/]*\.dylib|libtcl9tk)",
     ("This software is copyrighted by the Regents of the University of",)),
    ("FFmpeg inside PyAV", r"(^|/)(av\.libs|av/\.dylibs)/[^/]*(avcodec|avformat)",
     ("GNU LESSER GENERAL PUBLIC LICENSE", "Version 2, June 1991", "WRITTEN OFFER FOR SOURCE CODE")),
    ("LAME and GNU libiconv inside PyAV", r"(^|/)(av\.libs|av/\.dylibs)/(libmp3lame|libiconv)",
     ("Version 2.1, February 1999",)),
    ("the Silero VAD model", r"(^|/)silero_vad[^/]*\.onnx$", ("Copyright (c) 2020-present Silero Team",)),
    ("PortAudio", r"(^|/)(_sounddevice_data/portaudio-binaries/[^/]*\.(dll|dylib)|_portaudiowpatch[^/]*\.(pyd|so))$",
     ("PortAudio Portable Real-Time Audio Library", "Ross Bencina and Phil Burk")),
    ("PyAudio (inside PyAudioWPatch)", r"(^|/)_portaudiowpatch[^/]*\.(pyd|so)$", ("Copyright (c) 2006 Hubert Pham",)),
    ("the Microsoft WebView2 SDK", r"(?i)(^|/)(microsoft\.web\.webview2\.[^/]*|webview2loader)\.dll$",
     ("The name of Microsoft Corporation, or the names of its contributors",)),
    # Named by file: ONNX Runtime's notices already carry Intel MKL's copy of
    # the same license, which says nothing about libiomp5md.dll.
    ("Intel OpenMP", r"(?i)(^|/)libiomp5md\.dll$", ("Intel(R) OpenMP* Runtime Library (libiomp5md.dll)",
                                                   "No reverse engineering, decompilation, or disassembly")),
    ("NVIDIA cuDNN", r"(?i)(^|/)cudnn[^/]*\.dll$", ("cuDNN Supplement",)),
    ("the .NET Standard facades", r"(?i)(^|/)pythonnet/runtime/netstandard\.dll$",
     ("Copyright (c) .NET Foundation and Contributors",)),
    ("CTranslate2", r"(?i)(^|/)(ctranslate2/ctranslate2\.dll|libctranslate2[^/]*\.dylib)$",
     ("Copyright (c) 2018-     SYSTRAN.",)),
    ("ONNX Runtime", r"(?i)(^|/)(onnxruntime\.dll|libonnxruntime[^/]*\.dylib)$", ("Copyright (c) Microsoft Corporation",)),
    ("onnx-asr", r"(^|/)onnx_asr/", ("Copyright (c) 2025 Ilya Stupakov",)),
    ("numpy", r"(^|/)numpy/", ("NumPy Developers",)),
    ("Pillow", r"(^|/)PIL/", ("Secret Labs AB",)),
    ("pywebview", r"(^|/)webview/", ("Roman Sirokov",)),
)
OWN_FONTS = re.compile(r"(?i)(^|/)(KnightDisplay\.ttf|knight-display\.woff2)$")
FONT = re.compile(r"(?i)\.(ttf|otf|woff2?)$")
ASIO_BUILD = re.compile(r"(?i)-asio\.(dll|dylib)$")
NAME_ONLY = "This package ships no license file"
DOC_NAMES = {
    "license": ("LICENSE.txt", "LICENSE"),
    "notice": ("NOTICE.txt", "NOTICE"),
    "third_party": ("THIRD_PARTY_LICENSES.txt",),
}


@dataclass
class Artifact:
    """What a built artifact holds: its file names (POSIX, relative to the
    app's root) and a way to read one of them as text."""

    kind: str
    files: list[str]
    read: Callable[[str], str]


def _doc(artifact: Artifact, key: str) -> tuple[str, str] | None:
    """The shallowest LICENSE / NOTICE / THIRD_PARTY_LICENSES file, beside the
    program (Windows), in Contents/Resources (Mac) or in docs/ (installer)."""
    names = DOC_NAMES[key]
    candidates = [f for f in artifact.files if PurePosixPath(f).name in names
                  and ("/" not in f or f.startswith(("docs/", "Contents/Resources/")))]
    if not candidates:
        return None
    best = sorted(candidates, key=lambda f: (f.count("/"), names.index(PurePosixPath(f).name)))[0]
    return best, artifact.read(best)


def check(artifact: Artifact) -> list[str]:
    problems: list[str] = []
    files = artifact.files

    license_doc = _doc(artifact, "license")
    if license_doc is None:
        problems.append("LICENSE: missing (the Apache-2.0 text must ship beside the program)")
    else:
        for marker in LICENSE_MARKERS:
            if marker not in license_doc[1]:
                problems.append(f"{license_doc[0]}: not the Apache-2.0 text (no {marker!r})")

    notice_doc = _doc(artifact, "notice")
    if notice_doc is None:
        problems.append("NOTICE: missing (Apache-2.0 section 4(d), and the model attributions)")
    else:
        flat = " ".join(notice_doc[1].split())
        for marker in NOTICE_MARKERS:
            if marker not in flat:
                problems.append(f"{notice_doc[0]}: missing {marker!r}")

    third = _doc(artifact, "third_party")
    if third is None:
        problems.append("THIRD_PARTY_LICENSES.txt: missing")
        text = ""
    else:
        text = third[1]
        for part, marker in ALWAYS:
            if marker not in text:
                problems.append(f"THIRD_PARTY_LICENSES.txt: no text for {part} ({marker!r})")
        if NAME_ONLY in text:
            named = re.findall(r"-{78}\n([^\n]+)\nLicense:[^\n]*\n(?:(?!-{78}).)*?" + re.escape(NAME_ONLY), text, re.S)
            problems.append("THIRD_PARTY_LICENSES.txt: listed by name only, with no license text: "
                            + (", ".join(named) if named else "(see the file)"))

    for part, pattern, markers in BY_FILE:
        rx = re.compile(pattern)
        hits = [f for f in files if rx.search(f)]
        if not hits:
            continue
        for marker in markers:
            if marker not in text:
                problems.append(f"THIRD_PARTY_LICENSES.txt: {part} is in the artifact ({hits[0]}) but its "
                                f"text is not ({marker!r})")

    # A font needs its own credit: an OFL text some other package brought along
    # does not name this font's copyright holder or Reserved Font Name.
    lowered = text.lower()
    for font in sorted(f for f in files if FONT.search(f) and not OWN_FONTS.search(f)):
        family = PurePosixPath(font).stem.split("-")[0].lower()
        if "sil open font license" not in lowered or family not in lowered:
            problems.append(f"{font}: a font ships without its OFL notice naming {family!r}")

    asio = sorted(f for f in files if ASIO_BUILD.search(f))
    if asio:
        problems.append("PortAudio's ASIO builds ship (Steinberg's ASIO SDK, under Steinberg's own license): "
                        + ", ".join(PurePosixPath(f).name for f in asio))
    return problems


# ---------------------------------------------------------------- readers


def _strip_common_root(names: list[str]) -> tuple[list[str], str]:
    """A portable zip wraps everything in "Talk Dat!/"; a Mac zip in "X.app/"."""
    tops = {n.split("/", 1)[0] for n in names if "/" in n}
    loose = [n for n in names if "/" not in n]
    if len(tops) == 1 and not loose:
        top = tops.pop() + "/"
        return [n[len(top):] for n in names if n.startswith(top) and len(n) > len(top)], top
    return names, ""


def open_folder(path: Path) -> Artifact:
    """An app folder (dist/Talk Dat!), an installed copy, or a Mac .app, whose
    notices live in Contents/Resources."""
    files = [p.relative_to(path).as_posix() for p in path.rglob("*") if p.is_file()]
    return Artifact("folder", files, lambda name: (path / name).read_text(encoding="utf-8", errors="replace"))


def open_zip(path: Path) -> Artifact:
    archive = zipfile.ZipFile(path)
    raw = [n for n in archive.namelist() if not n.endswith("/")]
    files, top = _strip_common_root(raw)
    return Artifact("zip", files,
                    lambda name: archive.read(top + name).decode("utf-8", errors="replace"))


def installer_view(toc_names: list[str], extract: Callable[[str], bytes]) -> Artifact:
    """A PyInstaller-built installer: the app is payload/app/**, and the docs
    the installer writes to <install>/docs come from payload/docs/**."""
    normal = {n.replace("\\", "/"): n for n in toc_names}
    files: list[str] = []
    source: dict[str, str] = {}
    for posix, original in normal.items():
        if posix.startswith("payload/app/"):
            rel = posix[len("payload/app/"):]
            files.append(rel)
            source[rel] = original
        elif posix.startswith("payload/docs/"):
            rel = "docs/" + posix[len("payload/docs/"):]
            files.append(rel)
            source[rel] = original
    return Artifact("installer", files, lambda name: extract(source[name]).decode("utf-8", errors="replace"))


def open_installer(path: Path) -> Artifact:
    try:
        from PyInstaller.archive.readers import CArchiveReader
    except ImportError as exc:  # pragma: no cover - the build venv has PyInstaller
        raise SystemExit("reading an installer needs PyInstaller in this environment") from exc
    reader = CArchiveReader(str(path))
    return installer_view(list(reader.toc.keys()), reader.extract)


def open_artifact(path: Path) -> Artifact:
    path = Path(path)
    if path.is_dir():
        return open_folder(path)
    if path.suffix.lower() in {".zip", ".msix", ".appx"}:
        return open_zip(path)
    if path.suffix.lower() == ".exe":
        return open_installer(path)
    raise SystemExit(f"do not know how to read {path}")


def check_artifact(path: Path) -> list[str]:
    return check(open_artifact(path))


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args:
        print(__doc__)
        return 2
    failed = False
    for arg in args:
        path = Path(arg)
        if not path.exists():
            print(f"{path}: does not exist")
            failed = True
            continue
        problems = check_artifact(path)
        if problems:
            failed = True
            print(f"{path.name}: {len(problems)} licence gap(s)")
            for problem in problems:
                print(f"  - {problem}")
        else:
            print(f"{path.name}: every required licence text is in it")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
