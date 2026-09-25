"""Generate THIRD_PARTY_LICENSES.txt for a binary distribution of Talk DAT!.

Talk DAT!'s own source is Apache-2.0 and vendors no third-party code, but the
installer, the portable zip and the Mac disk image bundle the Python runtime and
every package the app imports, plus native libraries those packages carry
(FFmpeg inside PyAV, NVIDIA cuDNN and Intel OpenMP inside CTranslate2, DirectML
inside ONNX Runtime, the WebView2 SDK inside pywebview). Every one of them has
a license whose text must travel with the binary. Before 2026-09-23 about 20
of them did.

This script writes that text from the packages' OWN metadata, at build time,
from the exact environment PyInstaller bundled -- so it cannot drift from what
shipped the way a hand-kept list does.

    python scripts/collect_licenses.py --output "dist/Talk Dat!/THIRD_PARTY_LICENSES.txt" \\
        --bundle "dist/Talk Dat!" --analysis "build/Talk Dat!/Analysis-00.toc" \\
        --spec "Talk Dat!.spec" --strict

Which packages count as bundled:

* with ``--analysis`` (PyInstaller's Analysis TOC): every installed
  distribution that owns a file PyInstaller collected. Exact.
* without it: the dependency closure of requirements.txt for this platform,
  minus the spec's excludes. What the build WOULD bundle.

``--strict`` fails (exit 1) when a bundled package has no license text and no
license identifier, when a GPL-only helper the specs exclude (mouseinfo,
pymsgbox) is found in the bundle anyway, when a GPL/LGPL component is
present but the full license text it requires cannot be found, or when PyAV's
wheel carries a native library this file has no license row for.

The Mac build (build-mac.sh) runs the same script against the .app:

    python scripts/collect_licenses.py --bundle "dist-mac/Talk DAT!.app" \\
        --analysis build-mac/work/TalkDat-mac/Analysis-00.toc --spec TalkDat-mac.spec \\
        --output "dist-mac/Talk DAT!.app/Contents/Resources/THIRD_PARTY_LICENSES.txt" --strict
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.metadata as metadata
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = ROOT / "requirements.txt"
# On macOS the build installs requirements.txt AND requirements-mac.txt (pyobjc,
# keyring); without an Analysis TOC the closure has to start from both.
REQUIREMENTS_MAC = ROOT / "requirements-mac.txt"
LICENSE_ASSETS = ROOT / "knight_flow" / "assets" / "licenses" / "pdf"
APACHE_TEXT = ROOT / "LICENSES" / "Apache-2.0.txt"

# X-760 (2026-09-24, IP audit): the 0.4.167 bundle listed about a dozen parts
# by NAME only -- ctranslate2, the WebView2 SDK, Intel OpenMP, PortAudio inside
# sounddevice and PyAudioWPatch, the Silero VAD model inside faster-whisper, the
# PyInstaller bootloader -- because their wheels carry no license file. MIT,
# BSD, Apache and Intel's terms all say the TEXT goes with the binary. These are
# the upstream texts, verbatim, and where each was read (2026-09-24).
THIRD_PARTY_TEXTS = ROOT / "knight_flow" / "assets" / "licenses" / "third_party"
VENDORED_SOURCES = {
    "CTranslate2-LICENSE.txt": "https://github.com/OpenNMT/CTranslate2/blob/master/LICENSE",
    "proxy_tools-LICENSE.txt": "https://github.com/jtushman/proxy_tools/blob/master/LICENSE.txt",
    "silero-vad-LICENSE.txt": "https://github.com/snakers4/silero-vad/blob/master/LICENSE",
    "PortAudio-LICENSE.txt": "https://github.com/PortAudio/portaudio/blob/master/LICENSE.txt",
    "PyAudio-LICENSE.txt": "the header of pyaudiowpatch/__init__.py (PyAudio by Hubert Pham)",
    "WebView2-SDK-LICENSE.txt": "LICENSE.txt in the Microsoft.Web.WebView2 NuGet package",
    "WebView2-SDK-NOTICE.txt": "NOTICE.txt in the Microsoft.Web.WebView2 NuGet package",
    "Intel-Simplified-Software-License.txt": "Intel Simplified Software License (Version October 2022), "
                                             "with the copyright line of libiomp5md.dll's version resource",
    "dotnet-MIT-LICENSE.txt": "https://github.com/dotnet/corefx/blob/master/LICENSE.TXT, the license "
                              "NETStandard.Library.NETFramework declares for these facades",
    "Tcl-Tk-license.terms": "license.terms of Tcl/Tk 8.6 (the same terms cover Tcl/Tk 9.0)",
}
# Wheels that ship no license file, and the upstream text that stands in.
PACKAGE_TEXTS = {
    "ctranslate2": ("CTranslate2-LICENSE.txt",),
    "proxy-tools": ("proxy_tools-LICENSE.txt",),
}
# Build tools whose code is EMBEDDED in every executable they produce: the
# PyInstaller bootloader (GPL-2.0-or-later with the Bootloader Exception) and
# the run-time hooks of PyInstaller and its community hooks (Apache-2.0).
EMBEDDED_BUILD_TOOLS = ("pyinstaller", "pyinstaller-hooks-contrib")


def vendored_text(name: str) -> tuple[str, str] | None:
    """(label, text) of a vendored upstream license text, or None if missing."""
    path = THIRD_PARTY_TEXTS / name
    if not path.is_file():
        return None
    label = f"knight_flow/assets/licenses/third_party/{name}, from {VENDORED_SOURCES.get(name, 'upstream')}"
    return label, path.read_text(encoding="utf-8").strip()

# Build tooling that runs during the build and never ships.
BUILD_ONLY = {
    "pyinstaller", "pyinstaller-hooks-contrib", "altgraph", "pefile", "pywin32-ctypes",
    "macholib", "pip", "setuptools", "wheel", "ruff", "dmgbuild", "ds-store", "mac-alias",
    "pytest", "iniconfig", "pluggy", "pygments",
}
# GPL-only helpers pyautogui would drag in. The specs exclude them; finding one
# in a bundle is a build defect, not a notice to write.
FORBIDDEN_IN_BUNDLE = {"mouseinfo", "pymsgbox"}

LICENSE_FILE = re.compile(
    r"(?i)^(licen[cs]e|copying|notice|copyright|authors|thirdpartynotices|third[_-]party[_-]notices|legal)"
    r"([._-].*)?$"
)
COPYLEFT = re.compile(r"(?i)\b(L?GPL|GNU (Lesser |Library )?General Public)")

# The exact sources behind the PyAV wheel a build bundles, for the written
# offer. PyAV pins its FFmpeg build (scripts/ffmpeg-latest.json at the tag) to
# a pyav-ffmpeg release, whose scripts/pkg.py names the source archive of
# every library it builds; the Windows wheel adds GNU libiconv and the MinGW
# runtime. Read from those files on 2026-09-23 and cross-checked against the
# DLL version resources of the installed wheel (FFmpeg 8.1.2, x264 0.165,
# x265 4.2, libiconv 1.19). A PyAV upgrade must add its row: --strict fails the
# build when the bundled PyAV has none, so the offer cannot silently go stale.
PYAV_SOURCES: dict[str, dict] = {
    "18.1.0": {
        "ffmpeg": "8.1.2",
        "pyav_ffmpeg": "8.1.2-1",
        "sources": (
            ("PyAV 18.1.0", "https://github.com/PyAV-Org/PyAV/tree/v18.1.0"),
            ("pyav-ffmpeg 8.1.2-1, the FFmpeg build PyAV 18.1.0 uses; scripts/pkg.py at this tag names "
             "the source archive of every library in it", "https://github.com/PyAV-Org/pyav-ffmpeg/tree/8.1.2-1"),
            ("FFmpeg 8.1.2", "https://ffmpeg.org/releases/ffmpeg-8.1.2.tar.xz"),
            ("x264 (commit b35605ace3ddf7c1a5d67a2eb553f034aef41d55)",
             "https://code.videolan.org/videolan/x264/-/archive/b35605ace3ddf7c1a5d67a2eb553f034aef41d55/x264-b35605ace3ddf7c1a5d67a2eb553f034aef41d55.tar.bz2"),
            ("x265 4.2", "https://bitbucket.org/multicoreware/x265_git/downloads/x265_4.2.tar.gz"),
            ("LAME 3.100 (libmp3lame)", "https://deb.debian.org/debian/pool/main/l/lame/lame_3.100.orig.tar.gz"),
            ("GNU libiconv 1.19", "https://ftp.gnu.org/pub/gnu/libiconv/libiconv-1.19.tar.gz"),
        ),
    },
}

# The other native libraries PyAV's wheel carries beside FFmpeg, and their
# licenses (pyav-ffmpeg's pkg.py and each project's own license file).
#
# The macOS arm64 wheel (av-18.1.0-cp311-abi3-macosx_14_0_arm64.whl, sha256
# b30a4e8d...13316, inspected 2026-09-23) names its libraries the Unix way,
# av/.dylibs/libavcodec.62.28.102.dylib rather than av.libs/avcodec-62-<hash>.dll,
# and carries: FFmpeg 8.1.2 (libavcodec, libavdevice, libavfilter, libavformat,
# libavutil, libswresample, libswscale; configured --enable-version3
# --enable-libx264 --enable-libx265), libx264.165 and libx265.216 (x265
# "4.2+1-e444744", the same string the Windows DLL carries), libmp3lame,
# libopus, libdav1d, libSvtAv1Enc, libvpx, libwebp, libwebpmux, libsharpyuv and
# libopencore-amrnb/-amrwb. No libiconv, GCC runtime, winpthreads, zlib or
# Intel VPL: macOS provides iconv and zlib, and pyav-ffmpeg's build-ffmpeg.py
# enables libvpl only on Linux and Windows. Every one of those is matched below
# or by FFMPEG_LIBRARY / X26X_LIBRARY; --strict fails on any library that is not.
FFMPEG_LIBRARY = r"(lib)?(avcodec|avformat|avutil|swresample|swscale|avfilter|avdevice)[-.]"
X26X_LIBRARY = r"libx26[45]"
PYAV_LIBRARY = re.compile(r"(^|/)(av\.libs|av/\.dylibs)/([^/]+\.(dll|dylib))$")
PYAV_COMPANIONS = (
    (r"libmp3lame", "LAME", "LGPL-2.0-or-later"),
    (r"libiconv", "GNU libiconv", "LGPL-2.1-or-later"),
    (r"libgcc_s|libstdc\+\+", "GCC runtime", "GPL-3.0-or-later WITH GCC-exception-3.1"),
    (r"libwinpthread", "mingw-w64 winpthreads", "MIT"),
    (r"libdav1d", "dav1d", "BSD-2-Clause"),
    (r"libsvtav1", "SVT-AV1", "BSD-3-Clause-Clear"),
    (r"libopus", "Opus", "BSD-3-Clause"),
    (r"libopencore-amr", "opencore-amr", "Apache-2.0"),
    (r"libvpx", "libvpx", "BSD-3-Clause"),
    (r"libwebp|libsharpyuv", "libwebp", "BSD-3-Clause"),
    (r"libvpl", "Intel VPL dispatcher", "MIT"),
    (r"zlib1", "zlib", "Zlib"),
)

# NVIDIA cuDNN, as CTranslate2's Windows wheel ships it (cudnn64_9.dll). Its
# terms are the "License Agreement for NVIDIA Software Development Kits" with
# the cuDNN Supplement: the License.txt NVIDIA ships in its own nvidia-cudnn
# wheels, published per version at this address.
CUDNN_LICENSE_NAME = ("NVIDIA Software License Agreement for NVIDIA Software Development Kits, "
                      "with the cuDNN Supplement")
CUDNN_LICENSE_URL = "https://docs.nvidia.com/deeplearning/cudnn/backend/v{version}/reference/eula.html"
CUDNN_LICENSE_LATEST = "https://docs.nvidia.com/deeplearning/cudnn/latest/reference/eula.html"


def canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", str(name or "")).lower()


@dataclass
class Component:
    name: str
    version: str
    license: str
    homepage: str
    texts: list[tuple[str, str]] = field(default_factory=list)  # (relative file, text)
    note: str = ""
    # Why this component needs no text of its own in this file (its texts are
    # the GPL/LGPL appendix, or its vendor's terms require none). Empty means
    # it needs one, and --strict fails without it (X-760).
    exempt: str = ""

    @property
    def resolved(self) -> bool:
        return bool(self.texts) or bool(self.license and self.license.upper() != "UNKNOWN")

    @property
    def has_text(self) -> bool:
        return bool(self.texts) or bool(self.exempt)


# ---------------------------------------------------------------- metadata


def license_of(dist: metadata.Distribution) -> str:
    meta = dist.metadata
    expression = (meta.get("License-Expression") or "").strip()
    if expression:
        return expression
    declared = (meta.get("License") or "").strip()
    if declared and declared.upper() != "UNKNOWN" and len(declared) <= 120 and "\n" not in declared:
        return declared
    classifiers = [
        c.split("::")[-1].strip()
        for c in (meta.get_all("Classifier") or [])
        if c.startswith("License ::") and c.strip() != "License :: OSI Approved"
    ]
    if classifiers:
        return " / ".join(dict.fromkeys(classifiers))
    if declared and declared.upper() != "UNKNOWN":
        return declared.splitlines()[0].strip()[:120] + " (see text)"
    return ""


def homepage_of(dist: metadata.Distribution) -> str:
    meta = dist.metadata
    for entry in meta.get_all("Project-URL") or []:
        label, _, url = entry.partition(",")
        if label.strip().lower() in {"source", "source code", "repository", "homepage", "home", "code"}:
            return url.strip()
    return (meta.get("Home-page") or "").strip()


def license_texts(dist: metadata.Distribution) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for entry in dist.files or []:
        name = Path(str(entry)).name
        if not LICENSE_FILE.match(name) or name.lower().endswith((".py", ".pyc", ".pyi")):
            continue
        path = Path(dist.locate_file(entry))
        try:
            if not path.is_file() or path.stat().st_size > 2_000_000:
                continue
            text = path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            continue
        if text:
            found.append((str(entry).replace("\\", "/"), text))
    return found


def component_for(dist: metadata.Distribution) -> Component:
    return Component(
        name=dist.metadata.get("Name") or "unknown",
        version=dist.version,
        license=license_of(dist),
        homepage=homepage_of(dist),
        texts=license_texts(dist),
    )


def installed() -> dict[str, metadata.Distribution]:
    table: dict[str, metadata.Distribution] = {}
    for dist in metadata.distributions():
        name = canonical(dist.metadata.get("Name") or "")
        if name and name not in table:
            table[name] = dist
    return table


# ---------------------------------------------------------------- which packages


def spec_excludes(spec: Path | None) -> set[str]:
    """The module names the spec tells PyInstaller to leave out."""
    if spec is None or not spec.exists():
        return set()
    match = re.search(r"excludes=\[([^\]]*)\]", spec.read_text(encoding="utf-8"))
    return {name.lower() for name in re.findall(r'"([^"]+)"', match.group(1))} if match else set()


def top_level_modules(dist: metadata.Distribution) -> set[str]:
    declared = dist.read_text("top_level.txt") or ""
    names = {line.strip().lower() for line in declared.splitlines() if line.strip()}
    if names:
        return names
    for entry in dist.files or []:
        first = str(entry).replace("\\", "/").split("/", 1)[0]
        if first.endswith((".dist-info", ".data")) or first.startswith(("..", "__pycache__")):
            continue
        names.add(first.removesuffix(".py").split(".", 1)[0].lower())
    return names


def excluded_distributions(excludes: set[str], table: dict[str, metadata.Distribution]) -> set[str]:
    """Distributions every one of whose top-level modules the spec excludes.

    Matched on MODULE names, because that is what PyInstaller's excludes are:
    the spec's "scikit-learn" names a distribution, not a module, and never
    kept sklearn out of the bundle.
    """
    out: set[str] = set()
    for name, dist in table.items():
        modules = top_level_modules(dist)
        if modules and modules <= excludes:
            out.add(name)
    return out


def _strings(node, out: set[str]) -> None:
    if isinstance(node, str):
        out.add(node)
    elif isinstance(node, (list, tuple, set)):
        for item in node:
            _strings(item, out)
    elif isinstance(node, dict):
        for key, value in node.items():
            _strings(key, out)
            _strings(value, out)


def bundled_by_analysis(toc: Path, table: dict[str, metadata.Distribution]) -> set[str]:
    """Distributions owning any file PyInstaller's Analysis collected."""
    strings: set[str] = set()
    _strings(ast.literal_eval(toc.read_text(encoding="utf-8")), strings)
    collected = {s.replace("/", "\\").lower() for s in strings if (":" in s or s.startswith("/")) and "." in s}
    collected |= {s.replace("\\", "/").lower() for s in strings if s.startswith("/")}
    owners: set[str] = set()
    for name, dist in table.items():
        for entry in dist.files or []:
            path = str(Path(dist.locate_file(entry)))
            if path.replace("/", "\\").lower() in collected or path.lower() in collected:
                owners.add(name)
                break
    return owners


def requirement_closure(requirements: Path, table: dict[str, metadata.Distribution]) -> set[str]:
    """requirements.txt for this platform, then every Requires-Dist, transitively."""
    try:
        from packaging.requirements import Requirement
    except ImportError:  # pragma: no cover - packaging ships with every build venv
        Requirement = None  # type: ignore[assignment]
    pending: list[tuple[str, set[str]]] = []
    for line in requirements.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        if Requirement is None:
            pending.append((canonical(re.split(r"[\[<>=!~; ]", line, 1)[0]), set()))
            continue
        req = Requirement(line)
        if req.marker is None or req.marker.evaluate():
            pending.append((canonical(req.name), set(req.extras)))
    seen: set[str] = set()
    while pending:
        name, extras = pending.pop()
        if name in seen or name not in table:
            continue
        seen.add(name)
        for raw in table[name].requires or []:
            if Requirement is None:
                continue
            req = Requirement(raw)
            wanted = [{"extra": extra} for extra in extras] or [{"extra": ""}]
            if req.marker is None or any(req.marker.evaluate(env) for env in wanted):
                pending.append((canonical(req.name), set(req.extras)))
    return seen


# ---------------------------------------------------------------- native parts


def _files(bundle: Path | None, table: dict[str, metadata.Distribution]) -> list[str]:
    if bundle is not None and bundle.exists():
        return [str(p.relative_to(bundle)).replace("\\", "/") for p in bundle.rglob("*") if p.is_file()]
    names: list[str] = []
    for dist in table.values():
        names.extend(str(entry).replace("\\", "/") for entry in dist.files or [])
    return names


def gpl2_text() -> str:
    """The GPL-2.0 text: the verbatim copy in the repository, or else the one in
    PyInstaller's own COPYING.txt (the same FSF text)."""
    bundled = ROOT / "knight_flow" / "assets" / "licenses" / "GPL-2.0.txt"
    if bundled.exists():
        return bundled.read_text(encoding="utf-8").strip()
    try:
        dist = metadata.distribution("pyinstaller")
    except metadata.PackageNotFoundError:
        return ""
    for entry in dist.files or []:
        if Path(str(entry)).name.upper().startswith("COPYING"):
            text = Path(dist.locate_file(entry)).read_text(encoding="utf-8", errors="replace")
            start = text.find("GNU GENERAL PUBLIC LICENSE\n\t\t       Version 2, June 1991")
            if start < 0:
                match = re.search(r"GNU GENERAL PUBLIC LICENSE\s+Version 2, June 1991", text)
                start = match.start() if match else -1
            end = text.find("END OF TERMS AND CONDITIONS", start)
            if start >= 0 and end > start:
                return text[start:end + len("END OF TERMS AND CONDITIONS")].strip()
    return ""


def windows_file_version(path: Path) -> str:
    """The FileVersion string of a Windows DLL, or "" anywhere else."""
    if sys.platform != "win32" or not path.is_file():
        return ""
    try:
        import ctypes

        version = ctypes.windll.version  # type: ignore[attr-defined]
        size = version.GetFileVersionInfoSizeW(str(path), None)
        if not size:
            return ""
        buffer = ctypes.create_string_buffer(size)
        if not version.GetFileVersionInfoW(str(path), 0, size, buffer):
            return ""
        separator = chr(92)
        for codepage in ("040904b0", "040904e4", "000004b0"):
            pointer, length = ctypes.c_void_p(), ctypes.c_uint()
            key = separator + "StringFileInfo" + separator + codepage + separator + "FileVersion"
            if version.VerQueryValueW(buffer, key, ctypes.byref(pointer), ctypes.byref(length)) and length.value:
                return ctypes.wstring_at(pointer.value, length.value - 1).strip()
    except Exception:
        return ""
    return ""


def cudnn_version(bundle: Path | None, table: dict[str, metadata.Distribution]) -> str:
    """major.minor.patch of the cuDNN DLL the build bundles, or ""."""
    candidates: list[Path] = []
    if bundle is not None and bundle.exists():
        candidates = sorted(bundle.rglob("cudnn64_*.dll"))
    elif "ctranslate2" in table:
        dist = table["ctranslate2"]
        candidates = [Path(dist.locate_file(f)) for f in dist.files or []
                      if re.search(r"(^|/)cudnn64_\d+\.dll$", str(f).replace(chr(92), "/"))]
    for path in candidates:
        found = re.match(r"(\d+)\.(\d+)\.(\d+)", windows_file_version(path))
        if found:
            return ".".join(found.groups())
    return ""


def cudnn_license_url(bundle: Path | None, table: dict[str, metadata.Distribution]) -> str:
    version = cudnn_version(bundle, table)
    return CUDNN_LICENSE_URL.format(version=version) if version else CUDNN_LICENSE_LATEST


def python_license_file() -> Path | None:
    """CPython's LICENSE.txt: at the root of a Windows install, in the standard
    library directory (lib/python3.X) of a macOS or other POSIX one."""
    import sysconfig

    candidates = [Path(sys.base_prefix) / "LICENSE.txt"]
    with_stdlib = sysconfig.get_paths().get("stdlib")
    if with_stdlib:
        candidates.append(Path(with_stdlib) / "LICENSE.txt")
    return next((path for path in candidates if path.is_file()), None)


def tk_version() -> str:
    """The Tk this interpreter bundles: 8.6 on Windows, 9.0 on Homebrew's macOS
    Python since tcl-tk 9."""
    try:
        import tkinter

        return str(tkinter.TkVersion)
    except Exception:
        return "8.6"


def unaccounted_pyav_libraries(files: list[str]) -> list[str]:
    """Native libraries in PyAV's wheel directory (av.libs on Windows,
    av/.dylibs on macOS) that no row here names a license for.

    A new PyAV, or the other platform's wheel, can carry a library the
    written offer and the FFmpeg note know nothing about. --strict fails on
    it rather than shipping a binary whose license is not in the bundle.
    """
    known = [re.compile(pattern) for pattern in
             (FFMPEG_LIBRARY, X26X_LIBRARY, *(pattern for pattern, _label, _license in PYAV_COMPANIONS))]
    missing: set[str] = set()
    for entry in files:
        found = PYAV_LIBRARY.search(entry.replace("\\", "/"))
        if not found:
            continue
        name = found.group(3)
        if not any(pattern.match(name.lower()) for pattern in known):
            missing.add(name)
    return sorted(missing)


def native_components(files: list[str], bundle: Path | None = None,
                      table: dict[str, metadata.Distribution] | None = None) -> list[Component]:
    lower = [f.lower() for f in files]

    def has(pattern: str) -> list[str]:
        rx = re.compile(pattern)
        return sorted({files[i].rsplit("/", 1)[-1] for i, f in enumerate(lower) if rx.search(f)})

    out: list[Component] = []
    ffmpeg = has(r"(^|/)" + FFMPEG_LIBRARY + r"[^/]*\.(dll|dylib|so)")
    if ffmpeg:
        gpl_libs = has(r"(^|/)" + X26X_LIBRARY + r"[^/]*\.(dll|dylib|so)")
        companions = []
        for pattern, label, license_name in PYAV_COMPANIONS:
            hits = has(r"(^|/)(av\.libs|av/\.dylibs)/(" + pattern + r")[^/]*\.(dll|dylib)$")
            if hits:
                companions.append(f"{label} ({license_name}): {', '.join(hits)}")
        av_dist = (table or {}).get("av")
        row = PYAV_SOURCES.get(av_dist.version) if av_dist is not None else None
        out.append(Component(
            name="FFmpeg (bundled inside PyAV)",
            version=f"{row['ffmpeg']} (PyAV {av_dist.version})" if row else "as built by PyAV",
            homepage="https://ffmpeg.org/",
            license="LGPL-3.0-or-later" + (" with GPL-2.0-or-later libraries (x264, x265)" if gpl_libs else ""),
            note=(
                "Libraries: " + ", ".join(ffmpeg + gpl_libs) + ".\n"
                "Talk DAT! uses FFmpeg only through PyAV to resample audio; it does not encode video.\n"
                "FFmpeg is licensed under the GNU LGPL version 3 or later as configured by PyAV "
                "(https://github.com/PyAV-Org/pyav-ffmpeg). "
                + ("libx264 (https://www.videolan.org/developers/x264.html) and libx265 "
                   "(https://www.x265.org/) are licensed under the GNU GPL version 2 or later. "
                   if gpl_libs else "")
                + "Full texts: GPL-2.0, GPL-3.0 and LGPL-3.0 below. The written offer for "
                "their source code is at the end of this file. You may replace these libraries "
                "with your own builds; the application loads them from its runtime folder."
                + ("\nOther libraries PyAV's wheel ships with FFmpeg, as built by pyav-ffmpeg "
                   "(https://github.com/PyAV-Org/pyav-ffmpeg):\n  " + "\n  ".join(companions)
                   if companions else "")
            ),
            exempt="Its license texts are the GPL-2.0, GPL-3.0 and LGPL-3.0 (and, for LAME and libiconv, "
                   "LGPL-2.1) texts in the appendix below.",
        ))
    # (pattern, name, license, url, note, vendored texts, exempt reason)
    extra = [
        (r"(^|/)cudnn[^/]*\.dll$", "NVIDIA cuDNN (bundled inside CTranslate2)",
         CUDNN_LICENSE_NAME + " (proprietary, redistributable as part of an application)",
         cudnn_license_url(bundle, table or {}),
         "Copyright NVIDIA Corporation. Redistributed unmodified, as shipped in the CTranslate2 "
         "wheel, under NVIDIA's license at the URL above (the same text NVIDIA ships as "
         "License.txt in its nvidia-cudnn wheels). It is not licensed under Apache-2.0. It may "
         "be used only as part of Talk DAT!, and may not be separately redistributed, reverse "
         "engineered or modified, to the extent NVIDIA's terms require (EULA.md, \"NVIDIA "
         "components\").", (),
         "NVIDIA's license is the document at the URL above; its terms reach the person through EULA.md."),
        (r"(^|/)libiomp5md\.dll$", "Intel OpenMP runtime (bundled inside CTranslate2)",
         "Intel Simplified Software License (redistributable)",
         "https://www.intel.com/content/www/us/en/developer/articles/license/onemkl-license-faq.html",
         "Copyright Intel Corporation. Redistributed unmodified, as shipped in the CTranslate2 "
         "wheel, under Intel's redistribution terms, reproduced below as they require.",
         ("Intel-Simplified-Software-License.txt",), ""),
        (r"(^|/)directml\.dll$", "Microsoft DirectML (bundled inside ONNX Runtime DirectML)",
         "Microsoft DirectML redistributable license",
         "https://www.nuget.org/packages/Microsoft.AI.DirectML/",
         "Copyright Microsoft Corporation. Redistributed unmodified, as shipped in the "
         "onnxruntime-directml wheel; see also ONNX Runtime's ThirdPartyNotices below.", (),
         "Microsoft's DirectML license terms are at the URL above."),
        (r"(^|/)(microsoft\.web\.webview2\.[^/]*|webview2loader)\.dll$",
         "Microsoft WebView2 SDK (bundled inside pywebview)",
         "Microsoft WebView2 SDK license (BSD-style)",
         "https://www.nuget.org/packages/Microsoft.Web.WebView2/",
         "Copyright Microsoft Corporation. Redistributed unmodified, as shipped in the "
         "pywebview package. The WebView2 Runtime itself is not redistributed: Windows provides it.",
         ("WebView2-SDK-LICENSE.txt", "WebView2-SDK-NOTICE.txt"), ""),
        (r"(^|/)(vcruntime140[^/]*|msvcp140[^/]*|vcomp140)\.dll$", "Microsoft Visual C++ runtime",
         "Microsoft Visual C++ Redistributable license",
         "https://learn.microsoft.com/cpp/windows/redistributing-visual-cpp-files",
         "Copyright Microsoft Corporation. Redistributable files, unmodified.", (),
         "Microsoft's redistribution terms for these files are at the URL above."),
        # libcrypto-3.dll on Windows, libcrypto.3.dylib on macOS.
        (r"(^|/)lib(crypto|ssl)[-.]3[^/]*\.(dll|dylib)$", "OpenSSL 3", "Apache-2.0",
         "https://www.openssl.org/source/license.html",
         "Bundled with CPython and cryptography.", (), ""),
        # X-760: the parts the 0.4.167 bundle carried with no license text.
        (r"(^|/)silero_vad[^/]*\.onnx$", "Silero VAD model (bundled inside faster-whisper)", "MIT",
         "https://github.com/snakers4/silero-vad",
         "A small voice-activity model faster-whisper ships in its assets folder. Redistributed "
         "unmodified. It is the only model file in the app; the speech models are downloaded.",
         ("silero-vad-LICENSE.txt",), ""),
        (r"(^|/)(_sounddevice_data/portaudio-binaries/[^/]*\.(dll|dylib)|_portaudiowpatch[^/]*\.(pyd|so))$",
         "PortAudio (bundled inside sounddevice and PyAudioWPatch)", "MIT",
         "http://www.portaudio.com/",
         "The audio input library. sounddevice ships it as prebuilt libraries "
         "(https://github.com/spatialaudio/portaudio-binaries); PyAudioWPatch links its own "
         "PortAudio fork (https://github.com/s0d3s/PyAudioWPatch). The ASIO builds of PortAudio, "
         "which contain Steinberg's ASIO SDK, are left out of the app.",
         ("PortAudio-LICENSE.txt",), ""),
        (r"(^|/)_portaudiowpatch[^/]*\.(pyd|so)$", "PyAudio (the base of PyAudioWPatch)", "MIT",
         "https://people.csail.mit.edu/hubert/pyaudio/",
         "PyAudioWPatch is a fork of PyAudio; PyAudio's own notice travels with it.",
         ("PyAudio-LICENSE.txt",), ""),
        (r"(^|/)pythonnet/runtime/(netstandard|system\.[^/]*|microsoft\.win32\.primitives)\.dll$",
         ".NET Standard facade assemblies (bundled inside pythonnet)", "MIT",
         "https://www.nuget.org/packages/NETStandard.Library.NETFramework/",
         "Copyright .NET Foundation and Contributors. Redistributed unmodified, as shipped in the "
         "pythonnet package.",
         ("dotnet-MIT-LICENSE.txt",), ""),
    ]
    for pattern, name, license_name, url, note, vendored, exempt in extra:
        hits = has(pattern)
        if hits:
            texts = [text for text in (vendored_text(n) for n in vendored) if text]
            if "Apache" in license_name and not texts and APACHE_TEXT.is_file():
                texts = [("LICENSES/Apache-2.0.txt", APACHE_TEXT.read_text(encoding="utf-8").strip())]
            listed = hits if len(hits) <= 12 else hits[:12] + [f"and {len(hits) - 12} more"]
            out.append(Component(name=name, version="bundled", license=license_name, homepage=url,
                                 note="Files: " + ", ".join(listed) + ".\n" + note, texts=texts, exempt=exempt))
    python_license = python_license_file()
    python_texts = []
    if python_license is not None:
        python_texts.append(("LICENSE.txt (CPython)", python_license.read_text(encoding="utf-8", errors="replace").strip()))
    out.append(Component(
        name="Python", version=".".join(map(str, sys.version_info[:3])), license="PSF-2.0",
        homepage="https://www.python.org/", texts=python_texts,
        note="The Python interpreter and standard library, including the components listed in its license.",
    ))
    # Windows: tcl86t.dll / tk86t.dll. macOS (Homebrew tcl-tk): libtcl9.0.dylib
    # and libtcl9tk9.0.dylib, or libtcl8.6 / libtk8.6 on an older Tk.
    if (has(r"(^|/)(tcl|tk)8[^/]*\.dll$") or has(r"(^|/)_tk_data/")
            or has(r"(^|/)lib(tcl|tk)[89][^/]*\.dylib$")):
        terms = tcl_license_text(bundle)
        out.append(Component(
            name="Tcl/Tk", version=tk_version(), license="TCL (BSD-style)", homepage="https://www.tcl-lang.org/",
            texts=[terms] if terms else [],
        ))
    return out


def tcl_license_text(bundle: Path | None) -> tuple[str, str] | None:
    """Tcl/Tk's license.terms: the bundle's own copy, else the interpreter's,
    else the vendored copy.

    X-760: the Mac 0.4.158 bundle listed Tcl/Tk 9.0 with no text, because
    Homebrew's Python has no tcl/*/license.terms under sys.base_prefix (Tcl 9
    keeps its library inside the dylib). Windows found the file only by luck of
    the glob.
    """
    candidates: list[Path] = []
    if bundle is not None and bundle.exists():
        candidates += sorted(bundle.rglob("_tcl_data/license.terms")) + sorted(bundle.rglob("_tk_data/license.terms"))
    candidates += sorted(Path(sys.base_prefix).glob("tcl/*/license.terms"))
    try:
        import tkinter

        library = Path(str(tkinter.Tcl().eval("info library")))
        candidates += [library / "license.terms", library.parent / f"tk{tk_version()}" / "license.terms"]
    except Exception:
        pass
    for path in candidates:
        if path.is_file():
            return "license.terms", path.read_text(encoding="utf-8", errors="replace").strip()
    return vendored_text("Tcl-Tk-license.terms")


def embedded_build_tools(table: dict[str, metadata.Distribution]) -> list[Component]:
    """PyInstaller and its community hooks, which are build tools but leave
    their bootloader and run-time hooks inside every executable (X-760)."""
    out: list[Component] = []
    for name in EMBEDDED_BUILD_TOOLS:
        dist = table.get(name)
        if dist is None:
            out.append(Component(name=name, version="unknown", license="", homepage=""))
            continue
        component = component_for(dist)
        component.note = (
            "Embedded in every Talk DAT! executable: the PyInstaller bootloader (GPL-2.0-or-later with the "
            "Bootloader Exception, which permits distributing it inside other programs without GPL "
            "restrictions) and the run-time hooks (Apache-2.0). The license below states both."
        )
        out.append(component)
    return out


def apply_text_fallbacks(components: list[Component]) -> None:
    """Give a license TEXT to the wheels that ship none (X-760).

    * a vendored upstream text named in PACKAGE_TEXTS;
    * the Apache-2.0 text for an Apache-licensed wheel (Apache 2.0 section 4(a)
      asks for a copy of the License, not a per-package one);
    * pyobjc-core's text for the pyobjc framework wrappers, which are the same
      project under the same license and ship no file of their own.
    """
    core = next((c for c in components if canonical(c.name) == "pyobjc-core"), None)
    for c in components:
        if c.texts or c.exempt:
            continue
        name = canonical(c.name)
        if name in PACKAGE_TEXTS:
            c.texts = [text for text in (vendored_text(n) for n in PACKAGE_TEXTS[name]) if text]
            if c.texts:
                c.note = (c.note + "\n" if c.note else "") + (
                    "The wheel ships no license file; the text below is the project's own, from its repository.")
        elif re.search(r"(?i)\bapache\b", c.license) and APACHE_TEXT.is_file():
            c.texts = [("LICENSES/Apache-2.0.txt", APACHE_TEXT.read_text(encoding="utf-8").strip())]
        elif name.startswith("pyobjc-framework-") and core is not None and core.texts:
            c.texts = list(core.texts)
            c.note = (c.note + "\n" if c.note else "") + "Part of PyObjC; the license is pyobjc-core's."


def asio_builds(bundle: Path | None) -> list[str]:
    """PortAudio builds compiled with Steinberg's ASIO SDK inside a BUILT
    bundle (X-761). Only a real bundle is checked: the wheel itself still
    carries them, and the spec is what keeps them out."""
    if bundle is None or not bundle.exists():
        return []
    return sorted(p.name for p in bundle.rglob("*") if re.search(r"(?i)-asio\.(dll|dylib)$", p.name))


def textless(components: list[Component]) -> list[str]:
    """Components that carry neither a license text nor a reason to need none."""
    return [f"{c.name} {c.version}".strip() for c in components if not c.has_text]


# ---------------------------------------------------------------- writing


def written_offer(version: str, pyav_version: str = "") -> str:
    """The offer for GPL/LGPL source, naming the exact upstream sources of the
    PyAV build this binary bundles (PYAV_SOURCES)."""
    lines = [
        "WRITTEN OFFER FOR SOURCE CODE",
        "",
        "Some components above are licensed under the GNU GPL or LGPL: FFmpeg inside PyAV and the",
        "libraries PyAV builds it with (the GPL x264 and x265, the LGPL LAME and GNU libiconv), and",
        "pynput, pystray and fpdf2. For at least three years after Knight AI+AV LLC last distributes",
        f"this version of Talk DAT! ({version}), Knight AI+AV LLC will give anyone who asks a",
        "complete machine-readable copy of the corresponding source code of those components, as",
        "used in this distribution, for no more than the cost of physically performing the",
        "transfer. Write to security@knightaiav.com or Build@KnightAIAV.com with the subject",
        '"Source request" and the version.',
        "",
    ]
    row = PYAV_SOURCES.get(pyav_version)
    if row:
        lines += [
            f"The same sources are published upstream. This build bundles PyAV {pyav_version} with "
            f"FFmpeg {row['ffmpeg']} (pyav-ffmpeg {row['pyav_ffmpeg']}):",
        ]
        for label, url in row["sources"]:
            lines += [f"  {label}:", f"    {url}"]
    else:
        lines += [
            "The same sources are published upstream:",
            "  PyAV and its FFmpeg build scripts: https://github.com/PyAV-Org/PyAV",
            "                                     https://github.com/PyAV-Org/pyav-ffmpeg",
            "  FFmpeg: https://ffmpeg.org/download.html",
            "  x264:   https://code.videolan.org/videolan/x264",
            "  x265:   https://bitbucket.org/multicoreware/x265_git",
        ]
    lines += [
        "  pynput:  https://github.com/moses-palmer/pynput",
        "  pystray: https://github.com/moses-palmer/pystray",
        "  fpdf2:   https://github.com/py-pdf/fpdf2 (also shipped as source in pdf_runtime)",
        "Talk DAT!'s own source code is published under the Apache License 2.0.",
    ]
    return "\n".join(lines) + "\n"


def render(components: list[Component], shared: dict[str, str], *, version: str, mode: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = [
        "Talk DAT! -- third-party software licenses",
        "=" * 44,
        "",
        f"Generated {stamp} by scripts/collect_licenses.py for Talk DAT! {version} ({sys.platform}; {mode}).",
        "",
        "Talk DAT! itself is licensed under the Apache License, Version 2.0 (LICENSE.txt), with the",
        "notices in NOTICE.txt. This binary distribution also contains the third-party software",
        "below. Each component remains under its own license, reproduced here; nothing in",
        "Talk DAT!'s license or end-user terms restricts the rights those licenses grant,",
        "including the right to modify LGPL components and reverse-engineer this program to",
        "debug such modifications.",
        "",
        "SUMMARY",
        "-------",
    ]
    for c in components:
        lines.append(f"  {c.name} {c.version}  --  {c.license or 'see text'}")
    lines.append("")
    text_ids = {digest: f"T{index}" for index, digest in enumerate(shared, start=1)}
    for c in components:
        lines += ["", "-" * 78, f"{c.name} {c.version}", f"License: {c.license or 'see text below'}"]
        if c.homepage:
            lines.append(f"Source: {c.homepage}")
        if c.note:
            lines += ["", c.note]
        if not c.texts and c.exempt:
            lines += ["", c.exempt]
        elif not c.texts:
            lines += ["", "(This package ships no license file; the license above is taken from its metadata.)"]
        for relative, text in c.texts:
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
            lines += ["", f"[{relative}] -> full text {text_ids[digest]} below"]
    lines += ["", "", "=" * 78, "LICENSE TEXTS", "=" * 78]
    for digest, text in shared.items():
        lines += ["", f"----- {text_ids[digest]} " + "-" * 60, "", text]
    return "\n".join(lines).rstrip() + "\n"


def collect(*, analysis: Path | None, bundle: Path | None, spec: Path | None,
            requirements: Path = REQUIREMENTS) -> tuple[list[Component], list[str], list[str]]:
    """(components, forbidden hits, unresolved names)."""
    table = installed()
    if analysis is not None and analysis.exists():
        names = bundled_by_analysis(analysis, table)
    else:
        names = requirement_closure(requirements, table)
        if sys.platform == "darwin" and requirements == REQUIREMENTS and REQUIREMENTS_MAC.exists():
            names |= requirement_closure(REQUIREMENTS_MAC, table)
        names -= excluded_distributions(spec_excludes(spec), table)
    forbidden = sorted(names & FORBIDDEN_IN_BUNDLE)
    names = {n for n in names if n not in BUILD_ONLY and n not in FORBIDDEN_IN_BUNDLE}
    components = [component_for(table[name]) for name in sorted(names)]
    components += native_components(_files(bundle, table), bundle, table)
    components += embedded_build_tools(table)
    apply_text_fallbacks(components)
    unresolved = [c.name for c in components if not c.resolved]
    return components, forbidden, unresolved


def required_texts(components: list[Component]) -> dict[str, str]:
    """Full GPL/LGPL texts owed by any copyleft component present."""
    owed: dict[str, str] = {}
    labels = " ".join(c.license for c in components)
    if COPYLEFT.search(labels):
        for name in ("GPL-3.0.txt", "LGPL-3.0.txt"):
            path = LICENSE_ASSETS / name
            owed[name] = path.read_text(encoding="utf-8").strip() if path.exists() else ""
    if re.search(r"GPL-2\.0", labels):
        owed["GPL-2.0.txt"] = gpl2_text()
    # LAME (LGPL-2.0-or-later) and GNU libiconv (LGPL-2.1-or-later) inside
    # PyAV's wheel are named in the FFmpeg note rather than as components.
    if re.search(r"LGPL-2\.[01]", labels + " " + " ".join(c.note for c in components)):
        path = ROOT / "knight_flow" / "assets" / "licenses" / "LGPL-2.1.txt"
        owed["LGPL-2.1.txt"] = path.read_text(encoding="utf-8").strip() if path.exists() else ""
    return owed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write THIRD_PARTY_LICENSES.txt for a Talk DAT! build.")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--bundle", type=Path, help="the built app folder, to find native libraries")
    parser.add_argument("--analysis", type=Path, help="PyInstaller Analysis-00.toc of that build")
    parser.add_argument("--spec", type=Path, default=ROOT / "Talk Dat!.spec")
    parser.add_argument("--strict", action="store_true", help="fail on anything unresolved")
    args = parser.parse_args(argv)

    sys.path.insert(0, str(ROOT))
    from knight_flow.version import APP_VERSION

    components, forbidden, unresolved = collect(analysis=args.analysis, bundle=args.bundle, spec=args.spec)
    owed = required_texts(components)
    problems: list[str] = []
    if forbidden:
        problems.append("GPL-only helpers are in the bundle and must be excluded in the spec: " + ", ".join(forbidden))
    if unresolved:
        problems.append("no license text or identifier for: " + ", ".join(unresolved))
    missing_text = textless(components)
    if missing_text:
        problems.append("a license NAME is not the license: no text for " + ", ".join(missing_text)
                        + " -- vendor the upstream text in knight_flow/assets/licenses/third_party and name it "
                        "in PACKAGE_TEXTS or the native table (X-760)")
    missing_texts = [name for name, text in owed.items() if not text]
    if missing_texts:
        problems.append("required license texts not found: " + ", ".join(missing_texts))
    pyav_version = next((c.version for c in components if canonical(c.name) == "av"), "")
    if pyav_version and pyav_version not in PYAV_SOURCES:
        problems.append(f"PyAV {pyav_version} has no row in PYAV_SOURCES: add the exact FFmpeg, x264, x265, "
                        "LAME and libiconv sources its wheel was built from, for the written offer")
    asio = asio_builds(args.bundle)
    if asio:
        problems.append("PortAudio's ASIO builds are in the bundle: " + ", ".join(asio)
                        + " -- they carry Steinberg's ASIO SDK under Steinberg's own license and the app never "
                        "loads them; Talk Dat!.spec filters them out (X-761)")
    unaccounted = unaccounted_pyav_libraries(_files(args.bundle, installed()))
    if unaccounted:
        problems.append("PyAV's wheel carries native libraries with no license row: " + ", ".join(unaccounted)
                        + " -- add them to PYAV_COMPANIONS (and the written offer if they are GPL/LGPL)")

    shared: dict[str, str] = {}
    for c in components:
        for _relative, text in c.texts:
            shared.setdefault(hashlib.sha256(text.encode("utf-8")).hexdigest(), text)
    appendix = []
    for name, text in owed.items():
        if text:
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
            shared.setdefault(digest, text)
            appendix.append(name)
    mode = "exact, from the PyInstaller analysis" if args.analysis and args.analysis.exists() else "from requirements"
    body = render(components, shared, version=APP_VERSION, mode=mode)
    if appendix:
        body = body.replace("LICENSE TEXTS\n", "LICENSE TEXTS (including " + ", ".join(appendix) + ")\n", 1)
    body += "\n" + "=" * 78 + "\n" + written_offer(APP_VERSION, pyav_version)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(body, encoding="utf-8", newline="\n")
    print(f"third-party licenses: {len(components)} components, {len(shared)} license texts -> {args.output}")
    for problem in problems:
        print(("ERROR: " if args.strict else "warning: ") + problem, file=sys.stderr)
    return 1 if (problems and args.strict) else 0


if __name__ == "__main__":
    raise SystemExit(main())
