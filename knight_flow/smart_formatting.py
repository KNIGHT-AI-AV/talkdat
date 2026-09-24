"""Smart formatting setup: get the local writing model onto a fresh install.

Talk DAT! is free and local, so the formatting that makes a take read well
comes from a model running in Ollama on this machine (X-600). Until this
module existed, the only thing in the app that could INSTALL Ollama was the
Translation page, so a fresh install without it got rules-only formatting
forever, and the owner's top complaint ("not seeing the genius formatting")
was the default experience for every new user.

Nothing here downloads anything by itself. It sequences machinery that
already shipped:

    translation.install_ollama_runtime   the engine on Windows (winget)
    mac_ollama_install.install_ollama    the engine on a Mac (Homebrew, or
                                         Ollama's own signed app)
    translation._ensure_ollama_running   start it
    llm.pull_local_formatter_model       the model, with byte progress
    llm.prepare_local_formatter          warm it, measure the GPU, keep it resident

so there is one engine installer per platform and one model download path in
the product. Both installers run only inside the worker that start() begins,
which is a click: Set up smart formatting, in setup or in Settings.

State lives in one process-wide object because two surfaces show it: the
Getting started page and Settings > Formatting. A download started in one must
read as downloading in the other.
"""
from __future__ import annotations

import os
import platform
import shutil
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

from . import mac_support, platform_copy

# Measured from the engine's own /api/tags on the owner's PC, 2026-09-22.
# Sizes in copy come from here, never from memory.
MODEL_BYTES: dict[str, int] = {
    "qwen3:1.7b": 1_359_293_444,
    "qwen3:4b-instruct-2507-q4_K_M": 2_497_293_803,
}
# Ollama 0.33.2's installed folder on Windows, measured the same day. The
# installer download is smaller; this is what the disk has to hold. A Mac
# needs less (Ollama's Mac zip was 0.2 GB on 2026-09-23), so this over-counts
# there until the unpacked app is measured on a Mac.
ENGINE_INSTALLED_BYTES = 2_800_000_000
DISK_MARGIN_BYTES = 1_000_000_000

READY_PROBE_TTL_S = 3.0
WARM_WAIT_S = 240.0

STATES = ("checking", "ready", "not_set_up", "downloading", "failed", "needs_engine", "not_needed")

LABELS = {
    "checking": "Checking",
    "ready": "Ready",
    "not_set_up": "Not set up",
    "downloading": "Downloading",
    "failed": "Failed",
    "needs_engine": "Needs the Ollama app",
    "not_needed": "Handled by your provider",
}


def gigabytes(value: int) -> str:
    return f"{value / 1e9:.1f} GB"


def _models_path() -> Path:
    configured = os.environ.get("OLLAMA_MODELS", "").strip()
    path = Path(configured) if configured else Path.home() / ".ollama" / "models"
    while not path.exists() and path.parent != path:
        path = path.parent
    return path


def free_disk_bytes() -> int | None:
    try:
        return int(shutil.disk_usage(_models_path()).free)
    except OSError:
        return None


def capable_gpu() -> bool:
    """A GPU Ollama will actually run the writing model on.

    NVIDIA on Windows (the same nvidia-smi check the speech runtime uses) and
    Apple silicon on a Mac, where Ollama runs on Metal. Anything else is
    treated as the CPU, which is the honest default: the final word is still
    the warm-up, which measures where the model landed and keeps the 1.7B if
    the 4B spills off the card. Which model a capable GPU gets is
    wanted_models' question: on a Mac it also depends on memory
    (mac_support.gpu_model_fits).
    """
    if mac_support.IS_MAC:
        return platform.machine().lower() in {"arm64", "aarch64"}
    if sys.platform == "win32":
        from .cuda_runtime import nvidia_gpu_present

        return bool(nvidia_gpu_present())
    return False


def engine_installed() -> bool:
    from .llm import _local_ollama_executable

    return bool(_local_ollama_executable())


def engine_installer_available() -> bool:
    """Whether setup can put the engine here itself, once the person clicks.

    Windows: install_ollama_runtime's winget. A Mac: mac_ollama_install, with
    Homebrew when this user can run it, otherwise Ollama's own signed app.
    """
    if mac_support.IS_MAC:
        from . import mac_ollama_install

        return mac_ollama_install.available()
    return sys.platform == "win32" and bool(shutil.which("winget"))


def engine_name() -> str:
    """What setup calls the engine in copy: the app a Mac user will see."""
    return mac_support.OLLAMA_APP_NAME if mac_support.IS_MAC else "the Ollama engine"


def wanted_models(config: dict[str, Any], gpu: bool) -> list[str]:
    from .config import LOCAL_FORMATTER_MODEL
    from .llm import llm_settings
    from .local_finish import LOCAL_GPU_MODEL

    configured = str(llm_settings(config).get("model", "")).strip() or LOCAL_FORMATTER_MODEL
    # A capable GPU gets the 4B alone: prepare_local_formatter warms and
    # measures it directly, and pulls the 1.7B only if the 4B turns out not to
    # fit on the card. A Mac also needs the memory for it (16 GB; below that
    # it keeps the 1.7B). A chosen model other than the default is left alone.
    if gpu and configured.lower() == LOCAL_FORMATTER_MODEL.lower() and mac_support.gpu_model_fits():
        return [LOCAL_GPU_MODEL]
    return [configured]


def _installed(tag: str, names: set[str]) -> bool:
    wanted = tag.strip().lower()
    return wanted in names or f"{wanted}:latest" in names or (":" not in wanted and wanted in {n.split(":")[0] for n in names})


def download_bytes(models: list[str]) -> int | None:
    sizes = [MODEL_BYTES.get(tag) for tag in models]
    return None if any(size is None for size in sizes) else sum(sizes)  # type: ignore[arg-type]


def speech_stays_here(config: dict[str, Any]) -> bool:
    from .stt_registry import local_only, resolve_route

    return bool(local_only(config)) or resolve_route(config) == "local"


def explain(config: dict[str, Any], *, gpu: bool, engine: bool) -> str:
    """One or two plain sentences, true for this machine and this route."""
    here = platform_copy.THIS_COMPUTER
    first = f"Formatting runs on {here}."
    first += " Nothing you say leaves it." if speech_stays_here(config) else " Your speech still goes to the provider you chose."
    models = wanted_models(config, gpu)
    size = download_bytes(models)
    what = f"a writing model (about {gigabytes(size)})" if size else "a writing model"
    engine_part = "" if engine else f"{engine_name()} and "
    return f"{first} Setup downloads {engine_part}{what} once."


class SmartFormattingSetup:
    def __init__(
        self,
        config: dict[str, Any],
        *,
        start_worker: Callable[[Callable[[], None]], None] | None = None,
        probe_gpu: Callable[[], bool] | None = None,
        free_disk: Callable[[], int | None] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config = config
        self.lock = threading.Lock()
        self.start_worker = start_worker or (
            lambda work: threading.Thread(target=work, name="TalkDatSmartFormatting", daemon=True).start()
        )
        self.probe_gpu = probe_gpu or capable_gpu
        self.free_disk = free_disk or free_disk_bytes
        self.sleep = sleep
        self.gpu: bool | None = None
        self.probing = False
        self.job: dict[str, Any] | None = None  # {'state','stage','percent','message'}
        self._ready_probe: tuple[float, set[str] | None] | None = None

    # ------------------------------------------------------------------ probes
    def _ensure_probe(self) -> None:
        with self.lock:
            if self.gpu is not None or self.probing:
                return
            self.probing = True

        def work() -> None:
            try:
                found = bool(self.probe_gpu())
            except Exception:
                found = False
            with self.lock:
                self.gpu, self.probing = found, False

        try:
            self.start_worker(work)
        except Exception:
            with self.lock:
                self.gpu, self.probing = False, False

    def _engine_models(self, *, fresh: bool = False) -> set[str] | None:
        from . import llm

        now = time.monotonic()
        if not fresh and self._ready_probe and now - self._ready_probe[0] < READY_PROBE_TTL_S:
            return self._ready_probe[1]
        names = llm._ollama_models(self._api_base(), timeout=0.35)
        self._ready_probe = (now, names)
        return names

    def _api_base(self) -> str:
        from .llm import llm_settings
        from .translation import OLLAMA_DEFAULT_BASE

        return str(llm_settings(self.config).get("api_base", "")).strip() or OLLAMA_DEFAULT_BASE

    def applies(self) -> bool:
        """False when a provider key or a remote engine does the formatting."""
        from .llm import _is_local_ollama_base, resolved_llm_provider

        return resolved_llm_provider(self.config) == "ollama" and _is_local_ollama_base(self._api_base())

    # ---------------------------------------------------------------- snapshot
    def snapshot(self) -> dict[str, Any]:
        self._ensure_probe()
        with self.lock:
            gpu, job = self.gpu, dict(self.job) if self.job else None
        engine = engine_installed()
        models = wanted_models(self.config, bool(gpu))
        size = download_bytes(models)
        free = self.free_disk()
        needed = (size or 0) + (0 if engine else ENGINE_INSTALLED_BYTES) + DISK_MARGIN_BYTES
        disk_ok = free is None or free >= needed
        result: dict[str, Any] = {
            "gpu": gpu, "engine_installed": engine, "models": models,
            "download_bytes": size, "download_size": gigabytes(size) if size else "",
            "free_bytes": free, "needed_bytes": needed, "disk_ok": disk_ok,
            "recommended": bool(gpu) and disk_ok,
            "percent": None, "stage": "", "message": "",
            "offer_in_setup": False, "can_start": False, "download_page": False,
            "title": "Smart formatting",
            "recommended_label": f"Recommended for {platform_copy.THIS_COMPUTER}",
            "explanation": explain(self.config, gpu=bool(gpu), engine=engine),
            "note": "",
        }
        if job is not None and job["state"] == "downloading":
            state = "downloading"
            result.update(percent=job.get("percent"), stage=job.get("stage", ""), message=job.get("message", ""))
        elif not self.applies():
            state = "not_needed"
            result["message"] = "Your chosen provider formats your writing, so there is nothing to download here."
        else:
            names = self._engine_models()
            if names is not None and all(_installed(tag, names) for tag in models):
                state = "ready"
                result["message"] = f"Formatting uses the writing model on {platform_copy.THIS_COMPUTER}."
            elif job is not None and job["state"] == "failed":
                state = "failed"
                result["message"] = job.get("message", "") or "Setup did not finish. Choose Retry to try again."
            elif not engine and not engine_installer_available():
                state = "needs_engine"
                result["message"] = (
                    "Install the Ollama app, open it once, then choose Check again."
                    if mac_support.IS_MAC else
                    "Windows Package Manager is unavailable here. Install the Ollama app, then choose Check again."
                )
            elif gpu is None:
                state = "checking"
            else:
                state = "not_set_up"
        result["state"] = state
        result["label"] = LABELS[state]
        if state == "downloading":
            percent = result["percent"]
            installing = f"Installing {mac_support.OLLAMA_APP_NAME}" if mac_support.IS_MAC else "Installing the engine"
            result["label"] = f"Downloading {percent}%" if isinstance(percent, int) else (
                installing if result["stage"] == "engine" else "Getting ready")
        result["can_start"] = state in {"not_set_up", "failed"}
        result["download_page"] = state == "needs_engine" or (state == "failed" and not engine)
        # The setup step appears where setup can finish the job itself: Windows
        # with winget, a Mac (Homebrew or Ollama's signed app), or any machine
        # that already has the engine.
        result["offer_in_setup"] = state in {"not_set_up", "failed", "downloading", "ready", "checking"}
        if state in {"not_set_up", "failed", "checking"}:
            if gpu is False:
                result["note"] = (
                    f"{platform_copy.THIS_COMPUTER_SENTENCE} has no supported graphics card, so the model runs on the "
                    "processor and may be too slow to use. Talk DAT checks after setup and keeps its built-in rules if it is."
                )
            if not disk_ok and free is not None:
                result["note"] = (result["note"] + " " if result["note"] else "") + (
                    f"Setup needs about {gigabytes(needed)} free and this drive has {gigabytes(free)}."
                )
        return result

    # -------------------------------------------------------------------- job
    def _set(self, **values: Any) -> None:
        with self.lock:
            self.job = {**(self.job or {}), **values}

    def start(self) -> dict[str, Any]:
        """Begin setup in the background. Returns at once; never raises for a failed download."""
        if not self.applies():
            raise ValueError("Your chosen provider formats your writing, so there is nothing to set up here.")
        with self.lock:
            if self.job and self.job.get("state") == "downloading":
                return {"message": "Smart formatting is already being set up."}
            self.job = {"state": "downloading", "stage": "preparing", "percent": None, "message": "Getting ready."}
        try:
            self.start_worker(self._run)
        except Exception:
            self._set(state="failed", message="Setup could not start. Choose Retry to try again.")
            raise ValueError("Smart formatting setup could not start.") from None
        return {"message": "Smart formatting setup started. You can keep using Talk DAT while it downloads."}

    def check_again(self) -> dict[str, Any]:
        """Forget cached answers, so an engine installed by hand is seen."""
        with self.lock:
            if self.job and self.job.get("state") != "downloading":
                self.job = None
        self._ready_probe = None
        return {"message": "Checked again."}

    def open_download_page(self) -> dict[str, Any]:
        """The Ollama page the Translation setup already sends people to."""
        import webbrowser

        from .translation import OLLAMA_DOWNLOAD_URL

        if not webbrowser.open(OLLAMA_DOWNLOAD_URL):
            raise ValueError("The page could not open in your browser. Try again.")
        return {"message": "Install Ollama, open it once, then choose Check again."}

    def _fail(self, message: str) -> None:
        self._set(state="failed", stage="", percent=None, message=message)

    def _install_engine(self) -> tuple[bool, str]:
        """This platform's one engine installer. Reached only from _run, after a click."""
        from . import llm, translation

        if not mac_support.IS_MAC:
            return translation.install_ollama_runtime()
        from . import mac_ollama_install

        def progress(message: str, percent: int | None = None) -> None:
            self._set(stage="engine", percent=percent, message=message)

        # The app starts its own engine; setup waits for it to answer rather
        # than starting a second one beside it.
        return mac_ollama_install.install_ollama(
            progress, engine_ready=lambda: llm._ollama_models(self._api_base(), timeout=0.5) is not None)

    def _run(self) -> None:
        from . import llm, translation

        try:
            with self.lock:
                gpu = self.gpu
            if gpu is None:
                try:
                    gpu = bool(self.probe_gpu())
                except Exception:
                    gpu = False
                with self.lock:
                    self.gpu = gpu
            if not engine_installed():
                self._set(stage="engine", percent=None, message=f"Installing {engine_name()}.")
                ok, message = self._install_engine()
                if not ok:
                    return self._fail(message or "The engine could not be installed.")
            self._set(stage="engine", percent=None, message="Starting the engine.")
            ok, message = translation._ensure_ollama_running(self._api_base())
            if not ok:
                return self._fail(message or "The engine did not start.")
            names = llm._ollama_models(self._api_base(), timeout=2.0) or set()
            missing = [tag for tag in wanted_models(self.config, gpu) if not _installed(tag, names)]
            total = sum(MODEL_BYTES.get(tag, 1) for tag in missing) or 1
            done = 0
            for tag in missing:
                weight = MODEL_BYTES.get(tag, 1)
                best = [0]

                def progress(_stage: str, percent: int, done: int = done, weight: int = weight, best: list[int] = best) -> None:
                    best[0] = max(best[0], min(100, max(0, int(percent))))
                    overall = int((done + weight * best[0] / 100) * 100 / total)
                    with self.lock:
                        previous = (self.job or {}).get("percent") or 0
                    self._set(stage="model", percent=max(previous, min(99, overall)),
                              message="Downloading the writing model.")

                self._set(stage="model", percent=int(done * 100 / total), message="Downloading the writing model.")
                ok, message = llm.pull_local_formatter_model(self.config, progress, model=tag)
                if not ok:
                    return self._fail(message or "The model download did not finish.")
                done += weight
            # Warm it with the launch's own warm-up, so the next take uses it
            # without a restart and without paying a cold load.
            self._set(stage="warming", percent=None, message="Getting the model ready.")
            llm._OLLAMA_READY_CACHE.clear()
            llm.prepare_local_formatter(self.config)
            deadline = time.monotonic() + WARM_WAIT_S
            while llm.local_formatter_preparing(self.config) and time.monotonic() < deadline:
                self.sleep(0.25)
            api_base, target = llm.local_finish_target(self.config, executive=False)
            if llm.local_finish_speed(api_base, target) is None:
                llm.warm_local_finish(api_base, target)
            self._ready_probe = None
            self._set(state="done", stage="", percent=100, message="Smart formatting is ready.")
        except Exception as exc:  # a button's worker must never die silently
            self._fail(f"Setup did not finish: {type(exc).__name__}.")


_SHARED: SmartFormattingSetup | None = None
_SHARED_LOCK = threading.Lock()


def shared(config: dict[str, Any]) -> SmartFormattingSetup:
    """The one setup object for this process, shared by every surface."""
    global _SHARED
    with _SHARED_LOCK:
        if _SHARED is None or _SHARED.config is not config:
            _SHARED = SmartFormattingSetup(config)
        return _SHARED
