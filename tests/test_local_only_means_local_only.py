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
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]

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


if __name__ == "__main__":
    unittest.main()
