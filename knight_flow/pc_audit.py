"""X-59.C-2: the install-time PC audit. One honest look at the machine.

Mayowa's spec: "a PC scan assortment of which model defaults to is needed
as part of installation... if their system is not good enough to run the
best local model it should just automatically put them on the cloud model."

The scan reads only what decides local-model comfort -- logical cores,
physical memory, and whether a CUDA GPU is present -- and never touches the
network. The tier mapping is deliberately conservative: recommending a
model the machine chokes on is the crash reports we are digging out of;
recommending one tier low costs a little accuracy and nothing else.

Pure functions over one dataclass. No config writes here -- onboarding owns
what to DO with the recommendation.
"""

from __future__ import annotations

import ctypes
import sys
import os
import shutil
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class PcAudit:
    logical_cores: int
    ram_gb: float
    has_cuda_gpu: bool

    @property
    def summary(self) -> str:
        gpu = "CUDA GPU" if self.has_cuda_gpu else "no GPU"
        return f"{self.logical_cores} cores · {self.ram_gb:.0f} GB RAM · {gpu}"


def _mac_ram_gb() -> float:
    """sysctl hw.memsize: the one honest answer on macOS.

    The Windows path reads GlobalMemoryStatusEx, which does not exist here, so
    the audit reported 0 GB and the model-tier recommendation collapsed to the
    most conservative rung on every Mac -- including Apple Silicon machines
    that run the largest local models happily.
    """
    try:
        out = subprocess.run(
            ["/usr/sbin/sysctl", "-n", "hw.memsize"],
            capture_output=True, timeout=3, check=False,
        )
        return int(out.stdout.strip() or 0) / (1024 ** 3)
    except Exception:
        return 0.0


def _ram_gb() -> float:
    if sys.platform == "darwin":
        return _mac_ram_gb()
    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_uint32), ("dwMemoryLoad", ctypes.c_uint32),
            ("ullTotalPhys", ctypes.c_uint64), ("ullAvailPhys", ctypes.c_uint64),
            ("ullTotalPageFile", ctypes.c_uint64), ("ullAvailPageFile", ctypes.c_uint64),
            ("ullTotalVirtual", ctypes.c_uint64), ("ullAvailVirtual", ctypes.c_uint64),
            ("ullAvailExtendedVirtual", ctypes.c_uint64),
        ]
    status = MEMORYSTATUSEX()
    status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    try:
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return status.ullTotalPhys / (1024 ** 3)
    except Exception:
        pass
    return 0.0


def _has_cuda_gpu() -> bool:
    """nvidia-smi existing AND answering is the one signal that does not
    false-positive on laptops with long-dead drivers."""
    if not shutil.which("nvidia-smi"):
        return False
    try:
        result = subprocess.run(
            ["nvidia-smi", "-L"], capture_output=True, text=True, timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return result.returncode == 0 and "GPU" in (result.stdout or "")
    except Exception:
        return False


def audit_pc() -> PcAudit:
    return PcAudit(
        logical_cores=os.cpu_count() or 1,
        ram_gb=_ram_gb(),
        has_cuda_gpu=_has_cuda_gpu(),
    )


# Tier thresholds, set from the 2026-08-10 soak on the founder's i7-8700 /
# 32 GB (6C/12T, no CUDA): parakeet-tdt-0.6b-v3 runs comfortably there, so
# machines at or above that shape get the packaged default; the large
# whisper tiers want either a CUDA GPU or a genuinely big CPU box; below
# 8 GB RAM the honest recommendation is the cloud with a small local spare.
def recommended_local_model(audit: PcAudit) -> str:
    if audit.has_cuda_gpu and audit.ram_gb >= 12:
        return "whisper-large-v3-turbo"
    if audit.logical_cores >= 8 and audit.ram_gb >= 12:
        return "parakeet-tdt-0.6b-v3"
    if audit.ram_gb >= 8:
        return "whisper-small.en"
    return "whisper-base.en"


def cloud_is_the_kind_default(audit: PcAudit) -> bool:
    """True when this machine should start life on the cloud route.

    The doctrine (X-59): every NEW user starts on cloud during trial
    anyway; this flag marks machines where even the fallback local model
    will feel rough, so onboarding can say so honestly instead of letting
    the first offline dictation be the discovery."""
    return audit.ram_gb < 8 or audit.logical_cores < 4
