"""T6: choose a speech model by what it does on THIS machine, accuracy included.

model_picker.py (X-478) already times every model on disk against one
synthetic clip and recommends the fastest that runs, and it says plainly why
it measures speed only: there is no ground truth in a synthetic tone. This
adds the ground truth. A fixed passage is turned into audio on this machine --
the operating system's own text-to-speech written to a FILE, never played --
so every installed engine hears the same words, and its answer can be scored.

For each installed, compatible engine the bench records:
* cold time (the first call, which loads the weights) and warm times,
* the peak memory the process reached while that engine ran,
* the word error rate on the known passage.

The recommendation is the FASTEST model whose error rate meets the declared
threshold, with the observed range shown, not a ranking from RAM alone. A
model that failed is a result, not a crash. Synthetic speech is cleaner than a
person in a room, so these numbers rank engines on one machine; they are not a
promise of accuracy on anyone's voice, and the report says so.

What it never does: download a model, upload anything, or run while a take is
in progress or the person's audio work is active -- the caller decides when,
and only on the person's request. Pure over injected callables, so the tests
use fakes and no engine is loaded to test the arithmetic.
"""

from __future__ import annotations

import re
import statistics
import time
from dataclasses import dataclass, field
from typing import Callable, Iterable

#: The passage every engine hears. Ordinary dictation: numbers, a name, a list.
PASSAGE = (
    "Please send the quarterly report to the whole team by Friday afternoon. "
    "We need three copies for the board, and the budget review moves to next Tuesday. "
    "Thanks for checking the numbers twice."
)

#: Declared accuracy gate: a model must get at least 90 words in 100 right here.
DEFAULT_MAX_WER = 0.10


def _words(text: str) -> list[str]:
    text = str(text or "").lower()
    text = re.sub(r"[^a-z0-9' ]+", " ", text.replace("-", " "))
    return [word.strip("'") for word in text.split() if word.strip("'")]


def word_error_rate(reference: str, hypothesis: str) -> float:
    """(substitutions + deletions + insertions) / reference words."""
    ref, hyp = _words(reference), _words(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0
    previous = list(range(len(hyp) + 1))
    for i, word in enumerate(ref, start=1):
        current = [i] + [0] * len(hyp)
        for j, other in enumerate(hyp, start=1):
            current[j] = min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (word != other))
        previous = current
    return previous[-1] / len(ref)


@dataclass
class EngineResult:
    model_id: str
    failed: bool = False
    detail: str = ""
    cold_ms: float = 0.0
    warm_ms: list[float] = field(default_factory=list)
    peak_memory_mb: float = 0.0
    wer: float = 1.0
    transcript: str = ""

    @property
    def warm_median_ms(self) -> float:
        return statistics.median(self.warm_ms) if self.warm_ms else float("inf")

    @property
    def warm_range_ms(self) -> tuple[float, float]:
        return (min(self.warm_ms), max(self.warm_ms)) if self.warm_ms else (float("inf"), float("inf"))


def bench_engine(model_id: str, transcribe: Callable[[], str], *, reference: str = PASSAGE, warm_runs: int = 3,
                 memory: Callable[[], float] | None = None, clock: Callable[[], float] = time.perf_counter) -> EngineResult:
    """Run one engine: a cold call, then ``warm_runs`` warm calls, on the same audio."""
    result = EngineResult(model_id)
    peak = memory() if memory else 0.0
    try:
        started = clock()
        text = transcribe()
        result.cold_ms = (clock() - started) * 1000.0
        if memory:
            peak = max(peak, memory())
        for _ in range(max(1, warm_runs)):
            started = clock()
            text = transcribe()
            result.warm_ms.append((clock() - started) * 1000.0)
            if memory:
                peak = max(peak, memory())
    except Exception as error:  # noqa: BLE001 - an engine that cannot run here is a result
        result.failed, result.detail = True, f"{type(error).__name__}: {error}"[:160]
        return result
    result.transcript = text
    result.wer = word_error_rate(reference, text)
    result.peak_memory_mb = peak
    return result


@dataclass(frozen=True)
class Recommendation:
    model_id: str
    reason: str
    meets: tuple[str, ...]
    misses: tuple[str, ...]
    failed: tuple[str, ...]


def recommend(results: Iterable[EngineResult], *, max_wer: float = DEFAULT_MAX_WER) -> Recommendation:
    """The fastest model (median warm time) whose error rate meets the gate.
    None meeting it: no recommendation, and the report says which came closest."""
    results = list(results)
    failed = tuple(result.model_id for result in results if result.failed)
    working = [result for result in results if not result.failed]
    meets = sorted((result for result in working if result.wer <= max_wer), key=lambda r: r.warm_median_ms)
    misses = tuple(result.model_id for result in sorted(working, key=lambda r: r.wer) if result.wer > max_wer)
    if not meets:
        return Recommendation("", "no installed model met the accuracy gate", (), misses, failed)
    best = meets[0]
    return Recommendation(best.model_id, "fastest model that met the accuracy gate",
                          tuple(result.model_id for result in meets), misses, failed)


def may_run(*, take_active: bool, person_requested: bool, audio_work_active: bool) -> str:
    """"" when the bench may run now, otherwise why not. It runs only because
    the person asked, never during a take, never over someone's audio work."""
    if not person_requested:
        return "the bench runs only when you start it"
    if take_active:
        return "a dictation is in progress"
    if audio_work_active:
        return "another app is using audio heavily right now"
    return ""


#: Apps whose audio work a model load must never disturb, by the start of the
#: process image name in lower case: DAWs, editors that play and record, and
#: recorders. A load takes memory and the GPU for seconds at a time.
AUDIO_APP_PREFIXES = (
    "ableton", "fl64", "fl.exe", "reaper", "protools", "pro tools", "cubase", "nuendo", "studio one", "bitwig",
    "audacity", "adobe audition", "reason", "logic pro", "garageband", "resolve", "obs64", "obs32", "obs.exe",
)


def audio_work_active(process_names: Iterable[str] | None) -> bool:
    """Whether a known audio app is running. An unreadable process list counts
    as yes: the bench waits rather than guess over someone's session."""
    if process_names is None:
        return True
    return any(str(name).strip().lower().startswith(AUDIO_APP_PREFIXES) for name in process_names)


def bench_gate(*, take_active: bool, process_names: Iterable[str] | None) -> str:
    """The wired gate, as a code for the UI to word: "" (may run), "take_active"
    or "audio_work_active". It is only ever reached from the person's own request."""
    if take_active:
        return "take_active"
    if audio_work_active(process_names):
        return "audio_work_active"
    return ""


def running_process_names() -> list[str] | None:  # pragma: no cover - reads the real process list
    """The image names of running processes (Windows), or None where they
    cannot be read. Names only: nothing is opened, signalled or changed."""
    import sys

    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    class Entry(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
                    ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                    ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                    ("szExeFile", wintypes.WCHAR * 260)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
    kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)  # TH32CS_SNAPPROCESS
    if not snapshot or snapshot == wintypes.HANDLE(-1).value:
        return None
    names: list[str] = []
    try:
        entry = Entry()
        entry.dwSize = ctypes.sizeof(Entry)
        more = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while more:
            names.append(entry.szExeFile)
            more = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return names or None


def _finite(value: float) -> float | None:
    return round(value, 1) if value not in (float("inf"), float("-inf")) and value == value else None


def run_bench(model_ids: list[str], *, render, transcribe, memory=None, warm_runs: int = 3) -> dict:
    """T6's runner as the app calls it: render the passage (to a file, never
    played), run every installed engine on it, recommend. A plain summary,
    for the person's settings and for the UI to word."""
    pcm16, sample_rate, channels = render()
    results = bench_installed(model_ids, pcm16, sample_rate, channels, transcribe=transcribe,
                              warm_runs=warm_runs, memory=memory or peak_memory_mb)
    choice = recommend(results)
    return {
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "max_wer": DEFAULT_MAX_WER,
        "results": [{"model_id": result.model_id, "failed": result.failed, "wer": round(result.wer, 3),
                     "cold_ms": _finite(result.cold_ms), "warm_median_ms": _finite(result.warm_median_ms),
                     "peak_memory_mb": _finite(result.peak_memory_mb)} for result in results],
        "recommended": choice.model_id, "meets": list(choice.meets), "misses": list(choice.misses),
        "failed": list(choice.failed),
    }


def tts_command(platform: str, text_file: str, wav_file: str) -> list[str] | None:
    """The command that renders the passage to a WAV FILE (never to speakers),
    or None where there is no built-in text-to-speech to use."""
    if platform == "win32":
        script = ("Add-Type -AssemblyName System.Speech; "
                  "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                  f"$s.SetOutputToWaveFile('{wav_file}'); "
                  f"$s.Speak([IO.File]::ReadAllText('{text_file}')); $s.Dispose()")
        return ["powershell", "-NoProfile", "-NonInteractive", "-Command", script]
    if platform == "darwin":
        return ["say", "-f", text_file, "-o", wav_file, "--data-format=LEI16@16000"]
    return None


def peak_memory_mb() -> float:
    """This process's peak memory so far, in MB (Windows: peak working set)."""
    import sys

    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]

        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        psapi = ctypes.WinDLL("psapi")
        kernel32 = ctypes.WinDLL("kernel32")
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        # Declared: the pseudo-handle is (HANDLE)-1, which an undeclared call
        # would try to pass as a C int and refuse.
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        if psapi.GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            return counters.PeakWorkingSetSize / (1024 * 1024)
        return 0.0
    import resource

    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak / (1024 * 1024) if sys.platform == "darwin" else peak / 1024


def render_passage(platform: str, folder: str, *, run=None) -> tuple[bytes, int, int]:
    """The passage as audio, rendered by the OS's own text-to-speech into a file
    in ``folder`` (never played). Returns (pcm16, sample_rate, channels)."""
    import subprocess
    import wave
    from pathlib import Path

    text_file, wav_file = Path(folder) / "passage.txt", Path(folder) / "passage.wav"
    text_file.write_text(PASSAGE, encoding="utf-8")
    command = tts_command(platform, str(text_file), str(wav_file))
    if command is None:
        raise RuntimeError("This computer has no built-in text-to-speech to render the passage.")
    (run or subprocess.run)(command, check=True, capture_output=True, timeout=120)
    with wave.open(str(wav_file), "rb") as audio:
        if audio.getsampwidth() != 2:
            raise RuntimeError("The rendered passage is not 16-bit audio.")
        return audio.readframes(audio.getnframes()), audio.getframerate(), audio.getnchannels()


def bench_installed(model_ids: list[str], pcm16: bytes, sample_rate: int, channels: int, *,
                    transcribe, warm_runs: int = 3, memory=peak_memory_mb) -> list[EngineResult]:
    """Every installed engine on the same rendered passage. ``transcribe`` is
    local_stt.transcribe in the app; a fake in the tests."""
    return [bench_engine(model_id, lambda model_id=model_id: transcribe(
        model_id=model_id, pcm16=pcm16, sample_rate=sample_rate, channels=channels, language="en"),
        warm_runs=warm_runs, memory=memory) for model_id in model_ids]
