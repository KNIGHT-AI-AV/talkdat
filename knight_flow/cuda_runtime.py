"""X-476: the CUDA runtime, fetched on demand, for the machines it helps.

Measured on his own spooled dictations, 75.7 s of real speech:

    parakeet-tdt-0.6b-v3     1104 ms avg   13.7x realtime
    whisper-large-v3-turbo    854 ms avg   17.7x realtime
    distil-large-v3.5         717 ms avg   21.1x realtime

On an NVIDIA card, Whisper is FASTER than the Parakeet we ship and it is the
more accurate model class. The only thing standing between a person and that
is two CUDA libraries that Talk DAT! must not bundle: 1.2 GB against a 465 MB
installer, useful to one vendor's hardware, and dead weight for everybody else.

So they are fetched the way models already are: only if asked, only where they
help, and never as part of the download everyone pays for.

WHY THIS IS NOT `pip install`. The shipped app is a frozen PyInstaller build.
There is no pip inside it and no site-packages to install into. A wheel is a
zip, so this takes the wheels apart and keeps only the `bin/*.dll` members in a
directory the app owns. No Python packaging, no dependency resolution, nothing
that can rewrite the running environment.

WHAT IS PINNED AND WHY. Exact versions, exact URLs, exact SHA-256. These are
528 MB and 698 MB of native code that will sit on a person's machine and be
loaded into the process, so "whatever PyPI serves today" is not good enough.
The same reasoning already pins the model revisions (X-237) and the eas-cli
version. Both wheels here were verified working end to end on his 3090 before
being written down: 0.40 s for a real dictation, no fallback to the CPU.

WHAT THIS DELIBERATELY DOES NOT DO. It does not decide to download anything.
A gigabyte is the person's bandwidth and their disk, so the choice is theirs
and this only carries it out.
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .config import app_dir

log = logging.getLogger(__name__)

ProgressCallback = Callable[[str, float], None]


@dataclass(frozen=True)
class CudaWheel:
    name: str
    version: str
    url: str
    sha256: str
    size_mb: int


# Pinned. See the module docstring: this is native code that gets loaded into
# the process, and both were verified on the real engine at these versions.
WHEELS: tuple[CudaWheel, ...] = (
    CudaWheel(
        "nvidia_cublas_cu12", "12.9.2.10",
        "https://files.pythonhosted.org/packages/20/e2/"
        "fc9a0e985249d873150276d5afb02e39a66817fedbf1a385724393e505ed/"
        "nvidia_cublas_cu12-12.9.2.10-py3-none-win_amd64.whl",
        "623f43027d40d44ceadf0043f002bd25cf353e8f13ce90b9a87057019f560661",  # sha256 nvidia_cublas_cu12
        528,
    ),
    CudaWheel(
        "nvidia_cudnn_cu12", "9.25.1.1",
        "https://files.pythonhosted.org/packages/0b/ee/"
        "b5699f1960e358ec995bb72f71c2ec06c550fd0c8280525796d6646c0299/"
        "nvidia_cudnn_cu12-9.25.1.1-py3-none-win_amd64.whl",
        "debb5f5901ae6071f34d0a2b256acecc33dc3277f1fd5a11f8249f921db8a40d",  # sha256 nvidia_cudnn_cu12
        698,
    ),
)

TOTAL_MB = sum(wheel.size_mb for wheel in WHEELS)

# The one DLL whose absence is the whole failure. If it is here, the rest is.
SENTINEL = "cublas64_12.dll"


def cuda_dir() -> Path:
    """Where the extracted DLLs live. Beside the models, not in site-packages,
    because a frozen app has no site-packages to write to."""
    return Path(app_dir()) / "cuda"


def is_installed() -> bool:
    return (cuda_dir() / SENTINEL).is_file()


def installed_size_mb() -> int:
    directory = cuda_dir()
    if not directory.is_dir():
        return 0
    return int(sum(f.stat().st_size for f in directory.glob("*.dll")) / 1048576)


def nvidia_gpu_present() -> bool:
    """Is there an NVIDIA card at all?

    Asked before offering a gigabyte, because on any other machine this
    download buys precisely nothing. `nvidia-smi` ships with the driver, so
    its presence and a clean exit is the cheapest honest answer available
    without loading a runtime we may not have.
    """
    if sys.platform != "win32":
        return False
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=8,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and bool(result.stdout.strip())


def _verify(path: Path, expected: str) -> None:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    actual = digest.hexdigest()
    if actual != expected:
        raise RuntimeError(
            f"{path.name} did not match its pinned checksum. "
            "The download was truncated or the file is not what we pinned; "
            "nothing was installed."
        )


def _extract_dlls(wheel_path: Path, into: Path) -> int:
    """Keep the bin/*.dll members and nothing else.

    A wheel carries headers, metadata and a directory tree none of which this
    needs. Flattening the DLLs into one directory is what lets a single PATH
    entry find every one of them.
    """
    kept = 0
    with zipfile.ZipFile(wheel_path) as archive:
        for member in archive.namelist():
            lowered = member.lower()
            if not lowered.endswith(".dll") or "/bin/" not in lowered:
                continue
            target = into / Path(member).name
            with archive.open(member) as source, target.open("wb") as sink:
                shutil.copyfileobj(source, sink)
            kept += 1
    return kept


def install(progress_cb: ProgressCallback | None = None) -> None:
    """Fetch, verify and unpack the pinned wheels.

    Downloads to a temporary file and only moves the DLLs into place after the
    checksum passes, so an interrupted download can never leave a half-written
    DLL that loads and then crashes the process.
    """
    destination = cuda_dir()
    destination.mkdir(parents=True, exist_ok=True)
    staging = destination / ".incoming"
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)

    try:
        done_mb = 0.0
        for wheel in WHEELS:
            if progress_cb:
                progress_cb(f"Downloading {wheel.name}", done_mb / TOTAL_MB)
            with tempfile.NamedTemporaryFile(delete=False, suffix=".whl") as handle:
                temporary = Path(handle.name)
            try:
                with urllib.request.urlopen(wheel.url, timeout=120) as response, \
                        temporary.open("wb") as sink:
                    while True:
                        block = response.read(1024 * 1024)
                        if not block:
                            break
                        sink.write(block)
                        done_mb += len(block) / 1048576
                        if progress_cb:
                            progress_cb(f"Downloading {wheel.name}",
                                        min(done_mb / TOTAL_MB, 0.99))
                _verify(temporary, wheel.sha256)
                if progress_cb:
                    progress_cb(f"Unpacking {wheel.name}", min(done_mb / TOTAL_MB, 0.99))
                _extract_dlls(temporary, staging)
            finally:
                temporary.unlink(missing_ok=True)

        # Only now, with every wheel verified and unpacked, does anything land
        # where the loader will look.
        for dll in staging.glob("*.dll"):
            shutil.move(str(dll), str(destination / dll.name))
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    if not is_installed():
        raise RuntimeError(
            "The CUDA libraries unpacked but the one we need is missing. "
            "Nothing changed; the on-device engine is unaffected."
        )
    if progress_cb:
        progress_cb("Ready", 1.0)
    log.info("CUDA runtime installed: %s MB in %s", installed_size_mb(), cuda_dir())


def remove() -> int:
    """Give the gigabyte back. Returns the megabytes freed."""
    freed = installed_size_mb()
    shutil.rmtree(cuda_dir(), ignore_errors=True)
    return freed


def library_dirs() -> list[str]:
    """The directory to put on PATH, if the runtime is here."""
    return [str(cuda_dir())] if is_installed() else []
