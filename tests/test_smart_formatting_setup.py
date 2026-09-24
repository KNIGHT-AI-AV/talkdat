"""Smart formatting setup: a fresh install can get the local writing model.

Before this, only the Translation page could install Ollama, so a new install
without it got rules-only formatting forever. These tests pin the four things
that make the setup trustworthy:

- it reuses the shipped installer and model pull, never a download of its own;
- the default follows the machine (a capable GPU and room on the disk);
- every state the Settings row can show maps to the right words and action;
- it never stands between a person and Finish setup.

No test reaches the network or a real engine: every engine call is mocked, and
urlopen is replaced with a tripwire.
"""
from __future__ import annotations

import copy
import re
import unittest
from pathlib import Path
from unittest import mock

from knight_flow import platform_copy, smart_formatting
from knight_flow.config import DEFAULT_CONFIG, LOCAL_FORMATTER_MODEL
from knight_flow.local_finish import LOCAL_GPU_MODEL
from knight_flow.smart_formatting import SmartFormattingSetup
from knight_flow.web_shell.setup_workspace import SetupWorkspace

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "knight_flow" / "smart_formatting.py"
TB = 10**12


def no_network(*_args, **_kwargs):
    raise AssertionError("a smart formatting test reached the network")


def config():
    return copy.deepcopy(DEFAULT_CONFIG)


def setup(cfg=None, *, gpu=True, free=TB):
    return SmartFormattingSetup(cfg or config(), start_worker=lambda work: work(),
                                probe_gpu=lambda: gpu, free_disk=lambda: free, sleep=lambda _s: None)


class EngineFixture(unittest.TestCase):
    """Patches every engine touchpoint; `self.models` is what the engine lists."""

    def setUp(self):
        self.models: set[str] | None = set()
        self.executable = ""
        self.calls: list[tuple] = []
        patches = {
            "knight_flow.llm._local_ollama_executable": lambda: self.executable,
            "knight_flow.translation.install_ollama_runtime": self.install,
            "knight_flow.translation._ensure_ollama_running": self.run_engine,
            "knight_flow.llm._ollama_models": lambda *_a, **_k: None if self.models is None else set(self.models),
            "knight_flow.llm.pull_local_formatter_model": self.pull,
            "knight_flow.llm.prepare_local_formatter": lambda cfg: self.calls.append(("prepare",)),
            "knight_flow.llm.local_formatter_preparing": lambda cfg: False,
            "knight_flow.llm.local_finish_target": lambda cfg, executive: ("http://localhost:11434", LOCAL_GPU_MODEL),
            "knight_flow.llm.local_finish_speed": lambda base, model: None,
            "knight_flow.llm.warm_local_finish": lambda base, model: self.calls.append(("warm", model)),
            "knight_flow.smart_formatting.engine_installer_available": lambda: True,
            "knight_flow.mac_support.IS_MAC": False,
            "urllib.request.urlopen": no_network,
            "webbrowser.open": self.browser,
        }
        for target, replacement in patches.items():
            patcher = mock.patch(target, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.install_result = (True, "installed")
        self.pull_result: dict[str, tuple[bool, str]] = {}
        self.opened: list[str] = []

    def install(self):
        self.calls.append(("install",))
        if self.install_result[0]:
            self.executable = "ollama.exe"
            self.models = set() if self.models is None else self.models
        return self.install_result

    def run_engine(self, api_base="http://localhost:11434"):
        self.calls.append(("start_engine", api_base))
        if self.models is None:
            self.models = set()
        return True, "running"

    def pull(self, cfg, progress=None, *, timeout=1800.0, model=None):
        self.calls.append(("pull", model))
        if progress:
            progress("pulling", 50)
            progress("pulling", 20)  # a new layer restarts its own count
            progress("pulling", 100)
        ok, message = self.pull_result.get(model, (True, "ok"))
        if ok:
            self.models.add(model.lower())
        return ok, message

    def browser(self, url):
        self.opened.append(url)
        return True


class TheSetupReusesTheShippedInstallerTests(EngineFixture):
    def test_a_fresh_pc_installs_the_engine_pulls_the_models_and_warms(self):
        self.models = None  # no engine at all
        job = setup(gpu=True)
        job.start()
        self.assertEqual([c[0] for c in self.calls],
                         ["install", "start_engine", "pull", "prepare", "warm"])
        # A capable GPU pulls the 4B alone (2.5 GB), not the 1.7B as well.
        self.assertEqual([c[1] for c in self.calls if c[0] == "pull"], [LOCAL_GPU_MODEL])
        self.assertEqual(job.snapshot()["state"], "ready")

    def test_an_installed_engine_is_not_installed_again(self):
        self.executable = "ollama.exe"
        setup(gpu=False).start()
        self.assertNotIn(("install",), self.calls)
        self.assertEqual([c[1] for c in self.calls if c[0] == "pull"], [LOCAL_FORMATTER_MODEL])

    def test_an_installed_model_is_not_pulled_again(self):
        self.executable = "ollama.exe"
        self.models = {LOCAL_GPU_MODEL.lower()}
        job = setup(gpu=True)
        job.start()
        self.assertEqual([c for c in self.calls if c[0] == "pull"], [])
        self.assertIn(("prepare",), self.calls)
        self.assertEqual(job.snapshot()["state"], "ready")

    def test_a_gpu_pc_with_only_the_small_model_still_gets_the_4b(self):
        self.executable = "ollama.exe"
        self.models = {LOCAL_FORMATTER_MODEL}
        setup(gpu=True).start()
        self.assertEqual([c[1] for c in self.calls if c[0] == "pull"], [LOCAL_GPU_MODEL])

    def test_ready_means_warm_so_no_restart_is_needed(self):
        self.executable = "ollama.exe"
        setup(gpu=True).start()
        self.assertIn(("prepare",), self.calls)
        self.assertIn(("warm", LOCAL_GPU_MODEL), self.calls)

    def test_the_module_carries_no_download_address_of_its_own(self):
        source = SOURCE.read_text(encoding="utf-8")
        self.assertNotRegex(source, r"https?://")
        self.assertNotIn("urlopen", source)
        self.assertNotIn("subprocess", source)

    def test_progress_only_moves_forward_across_layers_and_models(self):
        self.executable = "ollama.exe"
        seen: list[int] = []
        job = setup(gpu=True)
        original = job._set

        def record(**values):
            original(**values)
            if isinstance(values.get("percent"), int) and values.get("stage") == "model":
                seen.append(values["percent"])
        job._set = record
        job.start()
        self.assertTrue(seen)
        self.assertEqual(seen, sorted(seen))
        self.assertLess(max(seen), 100)


class FailureIsAStateNotACrashTests(EngineFixture):
    def test_a_failed_engine_install_reads_failed_with_retry_and_the_download_page(self):
        self.install_result = (False, "Windows could not install the local translation engine automatically.")
        job = setup()
        job.start()
        state = job.snapshot()
        self.assertEqual(state["state"], "failed")
        self.assertTrue(state["can_start"])
        self.assertTrue(state["download_page"])
        self.assertIn("could not install", state["message"])

    def test_a_failed_pull_reads_failed_and_retry_starts_again(self):
        self.executable = "ollama.exe"
        self.pull_result[LOCAL_FORMATTER_MODEL] = (False, "The download did not finish: timed out")
        job = setup(gpu=False)
        job.start()
        self.assertEqual(job.snapshot()["state"], "failed")
        self.pull_result.clear()
        job.start()
        self.assertEqual(job.snapshot()["state"], "ready")

    def test_an_exception_in_the_worker_is_a_failed_state(self):
        self.executable = "ollama.exe"
        with mock.patch("knight_flow.llm.pull_local_formatter_model", side_effect=RuntimeError("boom")):
            job = setup(gpu=False)
            job.start()
        self.assertEqual(job.snapshot()["state"], "failed")


class TheDefaultFollowsTheMachineTests(EngineFixture):
    def test_a_capable_gpu_with_room_is_recommended_and_gets_the_4b(self):
        state = setup(gpu=True).snapshot()
        self.assertTrue(state["recommended"])
        self.assertEqual(state["models"], [LOCAL_GPU_MODEL])
        self.assertEqual(state["download_size"], "2.5 GB")
        self.assertIn("about 2.5 GB", state["explanation"])
        self.assertEqual(state["note"], "")

    def test_no_gpu_is_still_offered_but_not_recommended_and_says_why(self):
        state = setup(gpu=False).snapshot()
        self.assertFalse(state["recommended"])
        self.assertTrue(state["can_start"])
        self.assertTrue(state["offer_in_setup"])
        self.assertEqual(state["models"], [LOCAL_FORMATTER_MODEL])
        self.assertEqual(state["download_size"], "1.4 GB")
        self.assertIn("graphics card", state["note"])

    def test_a_full_disk_is_not_recommended_and_names_both_numbers(self):
        state = setup(gpu=True, free=2 * 10**9).snapshot()
        self.assertFalse(state["recommended"])
        self.assertTrue(state["can_start"])
        self.assertIn("2.0 GB", state["note"])
        self.assertIn("free", state["note"])

    def test_the_engine_counts_against_the_disk_only_when_missing(self):
        missing = setup(gpu=False).snapshot()["needed_bytes"]
        self.executable = "ollama.exe"
        present = setup(gpu=False).snapshot()["needed_bytes"]
        self.assertEqual(missing - present, smart_formatting.ENGINE_INSTALLED_BYTES)

    def test_the_gpu_probe_runs_off_the_caller(self):
        started = []
        job = SmartFormattingSetup(config(), start_worker=started.append, probe_gpu=lambda: True, free_disk=lambda: TB)
        self.assertEqual(job.snapshot()["state"], "checking")
        self.assertEqual(len(started), 1)
        started[0]()
        self.assertEqual(job.snapshot()["state"], "not_set_up")

    def test_sizes_are_the_measured_tag_sizes(self):
        self.assertEqual(set(smart_formatting.MODEL_BYTES), {LOCAL_FORMATTER_MODEL, LOCAL_GPU_MODEL})
        self.assertEqual(smart_formatting.gigabytes(smart_formatting.MODEL_BYTES[LOCAL_GPU_MODEL]), "2.5 GB")
        self.assertEqual(smart_formatting.gigabytes(smart_formatting.MODEL_BYTES[LOCAL_FORMATTER_MODEL]), "1.4 GB")


class TheSettingsRowMapsEveryStateTests(EngineFixture):
    def test_ready(self):
        self.executable = "ollama.exe"
        self.models = {LOCAL_GPU_MODEL.lower()}
        state = setup(gpu=True).snapshot()
        self.assertEqual((state["state"], state["label"], state["can_start"]), ("ready", "Ready", False))

    def test_not_set_up(self):
        state = setup().snapshot()
        self.assertEqual((state["state"], state["label"], state["can_start"]), ("not_set_up", "Not set up", True))

    def test_downloading_shows_the_percent(self):
        job = setup()
        job.job = {"state": "downloading", "stage": "model", "percent": 42, "message": ""}
        state = job.snapshot()
        self.assertEqual((state["state"], state["label"], state["can_start"]), ("downloading", "Downloading 42%", False))

    def test_installing_the_engine_has_no_invented_percent(self):
        job = setup()
        job.job = {"state": "downloading", "stage": "engine", "percent": None, "message": ""}
        self.assertEqual(job.snapshot()["label"], "Installing the engine")

    def test_failed_offers_retry(self):
        job = setup()
        job.job = {"state": "failed", "message": "The download did not finish."}
        state = job.snapshot()
        self.assertEqual((state["state"], state["label"], state["can_start"]), ("failed", "Failed", True))

    def test_no_installer_and_no_engine_sends_to_the_ollama_app(self):
        with mock.patch("knight_flow.smart_formatting.engine_installer_available", lambda: False):
            job = setup()
            state = job.snapshot()
        self.assertEqual(state["state"], "needs_engine")
        self.assertFalse(state["can_start"])
        self.assertTrue(state["download_page"])
        self.assertFalse(state["offer_in_setup"], "the setup step is gated to where the installer works")
        job.open_download_page()
        from knight_flow.translation import OLLAMA_DOWNLOAD_URL
        self.assertEqual(self.opened, [OLLAMA_DOWNLOAD_URL])

    def test_a_provider_that_formats_needs_nothing(self):
        with mock.patch("knight_flow.llm.resolved_llm_provider", lambda cfg: "openrouter"):
            job = setup()
            state = job.snapshot()
            self.assertEqual(state["state"], "not_needed")
            self.assertFalse(state["offer_in_setup"])
            with self.assertRaises(ValueError):
                job.start()


class TheCopyIsHonestTests(EngineFixture):
    PRICE = re.compile(r"\$|\bpric(e|ing)\b|\bbuy\b|\bpurchase|\bsubscri|\btrial\b|\bcost\b|\bpaid\b", re.IGNORECASE)

    def strings(self, state):
        return [value for value in state.values() if isinstance(value, str)]

    def test_no_em_dash_or_price_word_in_any_state(self):
        jobs = []
        for gpu, free in ((True, TB), (False, TB), (True, 10**9)):
            jobs.append(setup(gpu=gpu, free=free).snapshot())
        for text in (t for state in jobs for t in self.strings(state)):
            self.assertNotIn(chr(0x2014), text)
            self.assertIsNone(self.PRICE.search(text), text)

    def test_the_machine_is_named_for_its_platform(self):
        state = setup().snapshot()
        self.assertIn(platform_copy.THIS_COMPUTER, state["explanation"])
        self.assertIn(platform_copy.THIS_COMPUTER, state["recommended_label"])

    def test_nothing_leaves_is_said_only_on_the_local_route(self):
        self.assertIn("Nothing you say leaves", setup().snapshot()["explanation"])
        with mock.patch("knight_flow.smart_formatting.speech_stays_here", lambda cfg: False):
            text = setup().snapshot()["explanation"]
        self.assertNotIn("Nothing you say leaves", text)
        self.assertIn("provider", text)

    def test_the_engine_is_mentioned_only_when_it_will_be_downloaded(self):
        self.assertIn("Ollama engine", setup().snapshot()["explanation"])
        self.executable = "ollama.exe"
        self.assertNotIn("engine", setup().snapshot()["explanation"])


class TheStepNeverBlocksSetupTests(EngineFixture):
    def workspace(self, formatting):
        cfg = formatting.config
        saved = []

        def save(candidate):
            saved.append(copy.deepcopy(candidate))
            return {"saved": True, "runtime_refreshed": True}
        mic = mock.Mock()
        mic.snapshot.return_value = {"check": {"phase": "idle", "mode": "mic"}, "devices": {}, "selected": ""}
        actions = lambda name, value: [] if name == "permissions" else None  # noqa: E731
        return SetupWorkspace(cfg, save, actions, mic, formatting), saved

    def test_set_up_starts_the_shared_job_and_records_the_choice(self):
        job = setup()
        started = []
        job.start = lambda: started.append(1) or {"message": "started"}
        service, saved = self.workspace(job)
        result = service.handle({"operation": "formatting", "revision": service.revision(), "value": "start"})
        self.assertEqual(started, [1])
        self.assertEqual(saved[-1]["onboarding"]["smart_formatting"], "started")
        self.assertEqual(result["formatting"]["state"], "not_set_up")

    def test_not_now_is_remembered_and_starts_nothing(self):
        job = setup()
        job.start = mock.Mock()
        service, saved = self.workspace(job)
        result = service.handle({"operation": "formatting", "revision": service.revision(), "value": "later"})
        job.start.assert_not_called()
        self.assertEqual(result["formatting_choice"], "later")
        self.assertIn("Settings, Formatting", result["message"])

    def test_finish_setup_succeeds_while_downloading_or_failed(self):
        for state in ("downloading", "failed"):
            job = setup()
            job.job = {"state": state, "stage": "model", "percent": 10, "message": "x"}
            service, _saved = self.workspace(job)
            result = service.handle({"operation": "finish", "revision": service.revision(), "accepted": True})
            self.assertTrue(result["completed"], state)

    def test_a_broken_status_never_breaks_the_setup_page(self):
        job = setup()
        job.snapshot = mock.Mock(side_effect=RuntimeError("probe failed"))
        service, _saved = self.workspace(job)
        self.assertIsNone(service.handle({"operation": "state"})["formatting"])

    def test_the_step_is_absent_without_the_setup_object(self):
        mic = mock.Mock()
        mic.snapshot.return_value = {"check": {"phase": "idle", "mode": "mic"}, "devices": {}, "selected": ""}
        service = SetupWorkspace(config(), lambda c: {"saved": True}, lambda n, v: [], mic)
        self.assertIsNone(service.snapshot()["formatting"])
        with self.assertRaises(ValueError):
            service.handle({"operation": "formatting", "revision": service.revision(), "value": "start"})

    def test_unknown_values_are_refused(self):
        service, _saved = self.workspace(setup())
        with self.assertRaises(ValueError):
            service.handle({"operation": "formatting", "revision": service.revision(), "value": "curl"})


class TheSettingsActionTests(EngineFixture):
    def backend(self, job):
        from knight_flow.web_shell.shell_backend import ShellBackend
        backend = object.__new__(ShellBackend)
        backend.formatting, backend.workspaces, backend.models, backend.actions = job, None, None, {}
        return backend

    def test_each_action_returns_the_fresh_row(self):
        job = setup()
        job.start = mock.Mock(return_value={"message": "started"})
        backend = self.backend(job)
        result = backend.handle("action", {"name": "smart_formatting:start"})
        job.start.assert_called_once()
        self.assertEqual(result["smart_formatting"]["state"], "not_set_up")
        self.assertEqual(backend.handle("action", {"name": "smart_formatting:status"})["smart_formatting"]["label"], "Not set up")
        backend.handle("action", {"name": "smart_formatting:check"})

    def test_an_unknown_formatting_action_is_refused(self):
        with self.assertRaises(ValueError):
            self.backend(setup()).handle("action", {"name": "smart_formatting:install_from_url"})


class TheWebPagesCarryTheStepTests(unittest.TestCase):
    ASSETS = ROOT / "knight_flow" / "web_shell" / "shell_assets"

    def test_setup_page_has_the_two_buttons_and_no_finish_gate(self):
        source = (self.ASSETS / "setup.js").read_text(encoding="utf-8")
        self.assertIn('"Set up smart formatting"', source)
        self.assertIn('"Not now"', source)
        finish = source[source.index("next.onclick"):source.index("later.onclick")]
        self.assertNotIn("formatting", finish)

    def test_settings_formatting_page_renders_the_row(self):
        source = (self.ASSETS / "shell.js").read_text(encoding="utf-8")
        self.assertIn('page.id === "formatting"', source)
        self.assertIn("smart_formatting:start", source.replace('"smart_formatting:"+name', "smart_formatting:start"))
        self.assertIn('"Retry"', source)


if __name__ == "__main__":
    unittest.main()
