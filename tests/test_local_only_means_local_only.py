"""X-465: local only, and never a silent fall back to the cloud.

His order, 2026-09-05: every capability runs on the device. Sign-in, licence
and update checks are the whole permitted list.

The reason this is enforced in the resolvers rather than at each caller is
what his own machine was doing that morning. His SPEECH was local on every
dictation (Parakeet, no account, the log says so). His TEXT went to Talk DAT!
Cloud on every rewrite, because the route his config NAMES is cloud, the door
reads that name, and the local formatter could not answer anyway: Ollama was
not running. Nothing told him. The rule the code stated -- "text may go where
the speech already goes" -- was true of the configured route and false of the
actual one.
"""
from __future__ import annotations

import copy
import threading
import unittest
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT_DIR = Path(__file__).resolve().parents[1]

from knight_flow import llm, net_fence, text_pipeline
from knight_flow.config import DEFAULT_CONFIG
from knight_flow.llm import resolved_llm_provider
from knight_flow.stt_registry import local_only, resolve_route


def a_config(**privacy: object) -> dict:
    """A config that WANTS the cloud in every way it can express it."""
    config = copy.deepcopy(DEFAULT_CONFIG)
    config.setdefault("stt", {})["route_mode"] = "cloud"
    config["stt"]["provider"] = "openrouter"
    # X-480: a real key, because "wants the cloud" now means bring-your-own.
    # Without one there is nothing for the switch to restore, and the
    # reversibility test would pass on a fixture that could never route
    # anywhere but home.
    config["stt"].setdefault("providers", {})["openrouter"] = {"api_key": "sk-or-abcdefghijkl"}
    config.setdefault("llm", {})["provider"] = "talk_dat_cloud"
    config.setdefault("translation", {})["engine"] = "managed"
    config.setdefault("privacy", {}).update(privacy)
    return config


class TheSwitchIsOnByDefaultTests(unittest.TestCase):
    def test_a_fresh_install_is_local_only(self) -> None:
        self.assertIs(DEFAULT_CONFIG["privacy"]["local_only"], True)
        self.assertTrue(local_only(DEFAULT_CONFIG))

    def test_a_config_that_has_never_heard_of_the_flag_is_local_only(self) -> None:
        """An install upgrading from an older version must not be quietly
        left on the cloud because its file predates the flag."""
        self.assertTrue(local_only({"privacy": {"save_audio": False}}))
        self.assertTrue(local_only({}))
        self.assertTrue(local_only({"privacy": "not a dict"}))


class EveryDoorClosesTogetherTests(unittest.TestCase):
    """One switch, read by all three resolvers, so it cannot be true in one
    and false in another."""

    def setUp(self) -> None:
        self.local = a_config(local_only=True)
        self.cloud = a_config(local_only=False)

    def test_speech_stays_on_the_machine_whatever_the_switch_says(self) -> None:
        self.assertEqual(resolve_route(self.local, True), "local")
        self.assertEqual(resolve_route(self.local, False), "local")

    def test_the_formatter_is_the_local_engine(self) -> None:
        self.assertEqual(resolved_llm_provider(self.local), "ollama")

    def test_no_managed_text_path_exists_to_leave_through(self) -> None:
        """X-516: this used to assert a predicate returned False.

        A predicate is one edit away from returning True. The managed module
        that carried text off the machine is gone from disk instead, which is
        a stronger thing to be able to say and a harder one to undo by
        accident.
        """
        self.assertFalse((ROOT_DIR / "knight_flow" / "managed_cloud.py").exists())
        for name in ("llm.py", "translation.py", "app.py", "stt_sessions.py", "mac_services.py"):
            source = (ROOT_DIR / "knight_flow" / name).read_text(encoding="utf-8")
            with self.subTest(module=name):
                self.assertNotIn("import managed_cloud", source)
                self.assertNotIn("from .managed_cloud", source)

    def test_an_explicit_cloud_provider_does_not_beat_the_switch(self) -> None:
        """The config above asks for the managed cloud by name in three
        different places. The switch outranks all three."""
        self.assertEqual(resolved_llm_provider(self.local), "ollama")
        self.assertEqual(resolve_route(self.local, True), "local")

    def test_turning_it_off_restores_exactly_what_was_there_before(self) -> None:
        """This is a switch, not a demolition: someone who turns it off gets
        their other route back.

        X-480 changed WHAT that other route is. There are two now, this
        machine and the person's own key, so turning the switch off restores
        bring-your-own-key rather than a managed service that no longer
        exists. The property being defended is unchanged: the switch is
        reversible, and off means off."""
        self.assertEqual(resolve_route(self.cloud, True), "openrouter")
        # X-480: their key formats their text. The formatter follows the
        # speech route, so restoring bring-your-own-key restores it for both
        # halves rather than leaving formatting on a managed service the
        # speech route no longer uses.
        self.assertEqual(resolved_llm_provider(self.cloud), "openrouter")
        # X-516 cut the formatter, which is what that last comment said
        # should happen: the managed door is not shut, it is gone. Text
        # reaching the person's OWN provider is a different thing entirely,
        # and the resolvers above are what govern it.


class TheOnlyThingsAllowedOnTheNetworkTests(unittest.TestCase):
    def test_sign_in_licence_and_updates_are_not_gated_by_this(self) -> None:
        """They carry an email and a version number, never what was said or
        written, so the switch does not touch them -- and a local-only install
        that could not check its licence would be a worse product for no
        privacy gain."""
        import inspect

        from knight_flow import licensing

        source = inspect.getsource(licensing)
        self.assertNotIn("local_only", source, "licensing must not be gated by the local switch")


class ACommandSearchStaysOnThisComputerTests(unittest.TestCase):
    """A spoken command with nothing selected opens a web search with the command in its address. With local-only
    privacy on, the words stay on this computer: no search opens, and the Pill says why."""

    def command(self, local: bool):
        from knight_flow.app import TalkDatApp

        token = object()
        app = TalkDatApp.__new__(TalkDatApp)
        app.lock = threading.RLock()
        app.session_token = token
        app._deferred_delivery_owner = None
        app.config = {"privacy": {"local_only": local}}
        states: list[tuple] = []
        app.overlay = SimpleNamespace(set_state=lambda *args, **_kwargs: states.append(args))
        history: list[dict] = []
        app.add_history = history.append
        with mock.patch("knight_flow.app.foreground_window_id", return_value=0), \
                mock.patch("knight_flow.app.foreground_focus_window_id", return_value=0), \
                mock.patch("knight_flow.app.foreground_edit_target_signature", return_value=()), \
                mock.patch("knight_flow.app.foreground_input_generation", return_value=31), \
                mock.patch("knight_flow.app.webbrowser.open") as opened:
            app.handle_command("best pizza near me", delivery_token=token)
        return opened, states, history

    def test_local_only_opens_no_search_and_says_so(self) -> None:
        opened, states, history = self.command(True)
        opened.assert_not_called()
        self.assertEqual(states[-1][:2], ("error", "Command search is off."))
        self.assertEqual(history, [])

    def test_with_local_only_off_the_search_still_opens(self) -> None:
        """The control: the same command opens the search once local-only privacy is off."""
        opened, _states, history = self.command(False)
        opened.assert_called_once_with("https://www.perplexity.ai/search?q=best+pizza+near+me")
        self.assertEqual([entry["type"] for entry in history], ["command_search"])


class NoOllamaOnAnotherMachineTests(unittest.TestCase):
    """While the local-only fence is up, a command's Ollama rewrite, the one Ollama request with the person's words
    that skipped it, sends nothing to an Ollama address that is not this machine, the same check every other path
    makes (net_fence.assert_cloud_allowed). This machine's Ollama is still reached."""

    def setUp(self) -> None:
        previous = net_fence.local_only()
        net_fence.set_local_only(True)
        self.addCleanup(net_fence.set_local_only, previous)

    def rewrite(self, url: str) -> list[str]:
        config = {"transforms": {"ollama": {"enabled": True, "url": url}}}
        with mock.patch.object(text_pipeline.urllib.request, "urlopen",
                               side_effect=urllib.error.URLError("offline")) as urlopen:
            self.assertIsNone(text_pipeline.transform_with_ollama("hello there", "Make it formal.", config))
        return [call.args[0].full_url for call in urlopen.call_args_list]

    def test_a_rewrite_never_reaches_an_ollama_on_another_machine(self) -> None:
        self.assertEqual(self.rewrite("http://192.168.1.50:11434/api/generate"), [])

    def test_a_rewrite_still_reaches_the_ollama_on_this_machine(self) -> None:
        self.assertEqual(self.rewrite("http://localhost:11434/api/generate"), ["http://127.0.0.1:11434/api/generate"])


class TheFenceHoldsFromLaunchTests(unittest.TestCase):
    """Local-only privacy holds the fence from the first request after launch, with no settings save, whatever route
    is saved. The launch used to raise it from the route alone, in the startup warm (warm_selected_local_model), so the
    own-key route with Local-only on left every guarded path open until the first save, and the formatter prepare that
    the launch starts ran before even that."""

    def setUp(self) -> None:
        previous = net_fence.local_only()
        net_fence.set_local_only(False)  # a new process starts with the fence down
        self.addCleanup(net_fence.set_local_only, previous)

    @staticmethod
    def refused() -> bool:
        """Is a guarded request, the formatter's own POST to an Ollama on another machine, refused before it leaves?"""
        with mock.patch.object(llm.urllib.request, "urlopen", side_effect=urllib.error.URLError("offline")) as urlopen:
            try:
                llm._post_json("http://192.168.1.50:11434/api/chat", {}, {}, 1.0)
            except net_fence.LocalOnlyBlocked:
                return not urlopen.called
            except urllib.error.URLError:
                pass
        return False

    def launch(self, local: bool):
        """TalkDatApp() on the own-key route, its windows, tray, keys and disk stood in. Returns the app module, the app,
        and whether the launch's first request (the formatter prepare it starts) met a refusal."""
        from knight_flow import app as app_module

        config = copy.deepcopy(DEFAULT_CONFIG)
        config["stt"]["route_mode"] = "byok"
        config["privacy"]["local_only"] = local
        first_request: list[bool] = []
        with mock.patch.object(app_module.gc, "disable"), \
                mock.patch.object(app_module, "load_config", return_value=config), \
                mock.patch.object(app_module, "recover_interrupted_sessions", return_value=0), \
                mock.patch("knight_flow.updater.prune_stale_installers"), \
                mock.patch.object(app_module, "save_config"), \
                mock.patch.object(app_module, "prepare_local_formatter",
                                  side_effect=lambda _config: first_request.append(self.refused())), \
                mock.patch.object(app_module, "enable_dpi_awareness"), \
                mock.patch("knight_flow.brand_font.apply_app_family"), \
                mock.patch.object(app_module, "Overlay"), mock.patch.object(app_module, "TrayController"), \
                mock.patch.object(app_module, "MacMenuBar"), mock.patch.object(app_module, "HotkeyController"), \
                mock.patch("knight_flow.web_shell.shell_app.renderer_available", return_value=False):
            app = app_module.TalkDatApp()
        return app_module, app, first_request

    def warm(self, app_module, app) -> None:
        """The speech-model warm run() schedules 0.9 s after launch, its loading thread stood in."""
        with mock.patch.dict(app_module.os.environ, {}), \
                mock.patch.object(app_module, "model_to_warm", return_value=SimpleNamespace(id="parakeet")), \
                mock.patch.object(app_module.threading, "Thread"):
            app_module.os.environ.pop(app_module.NO_ENGINE_START_ENV, None)
            app.warm_selected_local_model()

    def test_local_only_holds_the_fence_from_launch_on_the_own_key_route(self) -> None:
        app_module, app, first_request = self.launch(True)
        self.assertEqual(first_request, [True], "the launch's first request went out with the fence down")
        self.assertTrue(self.refused(), "the fence was down once the launch finished")
        self.warm(app_module, app)
        self.assertTrue(self.refused(), "the startup warm lowered the fence")

    def test_with_local_only_off_the_own_key_route_stays_open(self) -> None:
        """The control: the same launch with Local-only off fences nothing on the own-key route, as before."""
        app_module, app, first_request = self.launch(False)
        self.assertEqual(first_request, [False])
        self.warm(app_module, app)
        self.assertFalse(self.refused())

    def switch(self, app_module, app, mode: str) -> None:
        """The Pill's route switch (set_route_mode), its save stood in and no model to warm."""
        with mock.patch.object(app, "save_settings"), \
                mock.patch.object(app_module, "model_to_warm", return_value=None):
            self.assertTrue(app.set_route_mode(mode))

    def test_the_route_switch_keeps_the_fence_while_local_only_is_on(self) -> None:
        """Local-only privacy outranks the switch (resolve_route), so tapping "Your key" with it on keeps the fence up,
        the same rule a launch or a save applies. The switch used to set the fence from the route alone, which opened
        every guarded path until the next save."""
        app_module, app, _ = self.launch(True)
        self.switch(app_module, app, "local")
        self.switch(app_module, app, "byok")
        self.assertTrue(self.refused(), "the switch to the own-key route lowered the fence under Local-only")

    def test_with_local_only_off_the_route_switch_raises_and_lowers_the_fence(self) -> None:
        """The control: with Local-only off the switch still raises the fence for Local and lowers it for your key."""
        app_module, app, _ = self.launch(False)
        self.switch(app_module, app, "local")
        self.assertTrue(self.refused())
        self.switch(app_module, app, "byok")
        self.assertFalse(self.refused())


if __name__ == "__main__":
    unittest.main()
