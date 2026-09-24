"""2026-09-22: a saved config stops naming the retired managed cloud.

The owner's own %APPDATA%\\TalkDat\\config.json still carried, after the move
to free and local:

    stt.cloud_provider = "talk_dat_cloud"
    stt.providers.talk_dat_cloud = {api_base: <the dead Cloud Run host>, ...}

The read side already routed around both, but every reader that forgets its
guard dials a service that is gone. `_migrate_retired_managed_cloud` removes
the leftovers on load. These tests pin each leftover before/after, that a
second run changes nothing, and that nothing belonging to the person -- a BYOK
key, a BYOK provider, their own server -- is touched.

tests/ is not in the shipping scan, so the dead host is spelled out here.
"""

from __future__ import annotations

import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from knight_flow.config import _migrate_retired_managed_cloud, load_config
from knight_flow.credentials import credential_target

DEAD_HOST = "https://talk-dat-retired-0000000000-uc.a.run.app"
DEAD_SUBDOMAIN = "https://api.talkdat.knightaiav.com"
BYOK_KEY = "sk-test-byok-not-a-real-key-0000"


def owner_shaped() -> dict:
    """The real shape of the owner's file, values redacted (no key is set there)."""
    return {
        "stt": {
            "provider": "local",
            "cloud_provider": "talk_dat_cloud",
            "route_mode": "local",
            "providers": {
                "local": {"api_base": "", "api_key": "", "model": "parakeet-tdt-0.6b-v3", "variant": "auto"},
                "deepgram": {"api_base": "https://api.deepgram.com", "api_key": "", "model": "nova-3"},
                "custom_openai": {"api_base": "", "api_key": "", "model": "custom-model"},
                "talk_dat_cloud": {
                    "api_base": DEAD_HOST,
                    "api_key": "",
                    "language": "en-US",
                    "model": "scribe_v2",
                    "variant": "clean-dictation",
                },
            },
        },
        "transforms": {
            "llm": {"provider": "auto", "api_base": "http://localhost:11434", "api_key": "", "model": "qwen3:1.7b"},
        },
        "translation": {"engine": "local", "api_base": "http://localhost:11434"},
        "licensing": {"api_base": "https://api.talkdat.app"},
    }


class EachLeftoverBeforeAndAfterTests(unittest.TestCase):
    def test_the_owners_own_config(self) -> None:
        config = owner_shaped()
        changes = _migrate_retired_managed_cloud(config)
        self.assertNotIn("cloud_provider", config["stt"])
        self.assertNotIn("talk_dat_cloud", config["stt"]["providers"])
        self.assertEqual(config["stt"]["provider"], "local")
        self.assertEqual(config["stt"]["route_mode"], "local")
        self.assertEqual(sorted(changes), ["stt.cloud_provider", "stt.providers.talk_dat_cloud"])
        # Everything else is exactly as it was.
        expected = owner_shaped()
        del expected["stt"]["cloud_provider"]
        del expected["stt"]["providers"]["talk_dat_cloud"]
        self.assertEqual(config, expected)

    def test_stt_provider_naming_the_managed_service_becomes_local(self) -> None:
        config = {"stt": {"provider": "talk_dat_cloud", "providers": {}}}
        _migrate_retired_managed_cloud(config)
        self.assertEqual(config["stt"]["provider"], "local")

    def test_cloud_provider_is_removed_not_blanked(self) -> None:
        config = {"stt": {"cloud_provider": "talk_dat_cloud"}}
        self.assertEqual(_migrate_retired_managed_cloud(config), ["stt.cloud_provider"])
        self.assertEqual(config, {"stt": {}})

    def test_route_mode_auto_becomes_local(self) -> None:
        config = {"stt": {"route_mode": "auto", "provider": "local", "providers": {}}}
        _migrate_retired_managed_cloud(config)
        self.assertEqual(config["stt"]["route_mode"], "local")

    def test_route_mode_cloud_without_a_key_becomes_local(self) -> None:
        config = {"stt": {"route_mode": "cloud", "provider": "deepgram",
                          "providers": {"deepgram": {"api_key": ""}}}}
        _migrate_retired_managed_cloud(config)
        self.assertEqual(config["stt"]["route_mode"], "local")

    def test_route_mode_cloud_with_the_persons_own_key_becomes_byok(self) -> None:
        """Not "local": route_mode() already reads this as byok, so writing
        local would silently move somebody off the key they set up."""
        config = {"stt": {"route_mode": "cloud", "provider": "deepgram", "cloud_provider": "deepgram",
                          "providers": {"deepgram": {"api_key": BYOK_KEY}}}}
        _migrate_retired_managed_cloud(config)
        self.assertEqual(config["stt"]["route_mode"], "byok")
        self.assertEqual(config["stt"]["cloud_provider"], "deepgram")

    def test_a_provider_api_base_on_the_dead_host_is_cleared(self) -> None:
        for dead in (DEAD_HOST, DEAD_HOST + "/v1/stt", DEAD_SUBDOMAIN,
                     "https://talk-dat-retired-0000000000-uc.a.run.app"):
            with self.subTest(api_base=dead):
                config = {"stt": {"providers": {"openai": {"api_base": dead, "api_key": BYOK_KEY}}}}
                self.assertEqual(_migrate_retired_managed_cloud(config), ["stt.providers.openai.api_base"])
                self.assertEqual(config["stt"]["providers"]["openai"], {"api_base": "", "api_key": BYOK_KEY})

    def test_transforms_providers_entry_is_removed(self) -> None:
        config = {"transforms": {"providers": {"talk_dat_cloud": {"api_base": DEAD_HOST},
                                               "openai": {"api_key": BYOK_KEY}}}}
        _migrate_retired_managed_cloud(config)
        self.assertEqual(config["transforms"]["providers"], {"openai": {"api_key": BYOK_KEY}})

    def test_llm_provider_naming_the_managed_service_becomes_auto(self) -> None:
        config = {"transforms": {"llm": {"provider": "talk_dat_cloud", "api_key": "managed-session-token",
                                         "api_base": DEAD_HOST, "model": "qwen3:1.7b"}}}
        _migrate_retired_managed_cloud(config)
        llm = config["transforms"]["llm"]
        self.assertEqual(llm["provider"], "auto")
        # The managed service's credential, not the person's -- left, it would
        # be vaulted under the "auto" slot on the next save.
        self.assertEqual(llm["api_key"], "")
        self.assertEqual(llm["api_base"], "http://localhost:11434")
        self.assertEqual(llm["model"], "qwen3:1.7b")

    def test_a_byok_llm_on_the_dead_host_gets_its_providers_own_endpoint(self) -> None:
        config = {"transforms": {"llm": {"provider": "openai", "api_key": BYOK_KEY, "api_base": DEAD_HOST}}}
        _migrate_retired_managed_cloud(config)
        llm = config["transforms"]["llm"]
        self.assertEqual(llm, {"provider": "openai", "api_key": BYOK_KEY, "api_base": "https://api.openai.com"})

    def test_translation_engine_managed_becomes_local(self) -> None:
        for engine in ("managed", "cloud", "talk_dat_cloud"):
            with self.subTest(engine=engine):
                config = {"translation": {"engine": engine, "api_base": DEAD_HOST}}
                _migrate_retired_managed_cloud(config)
                self.assertEqual(config["translation"], {"engine": "local", "api_base": "http://localhost:11434"})

    def test_one_log_line_naming_fields_never_values(self) -> None:
        config = owner_shaped()
        config["stt"]["route_mode"] = "auto"
        with self.assertLogs("knight_flow.config", level="INFO") as captured:
            _migrate_retired_managed_cloud(config)
        self.assertEqual(len(captured.records), 1)
        line = captured.output[0]
        self.assertIn("stt.cloud_provider", line)
        self.assertIn("stt.route_mode", line)
        self.assertNotIn("run.app", line)
        self.assertNotIn("http", line)


class IdempotenceTests(unittest.TestCase):
    def worst_case(self) -> dict:
        config = owner_shaped()
        config["stt"]["provider"] = "talk_dat_cloud"
        config["stt"]["route_mode"] = "cloud"
        config["stt"]["providers"]["openai"] = {"api_base": DEAD_SUBDOMAIN, "api_key": BYOK_KEY}
        config["transforms"]["providers"] = {"talk_dat_cloud": {}}
        config["transforms"]["llm"].update(provider="talk_dat_cloud", api_base=DEAD_HOST)
        config["translation"].update(engine="managed", api_base=DEAD_HOST)
        return config

    def test_a_second_run_changes_nothing(self) -> None:
        config = self.worst_case()
        self.assertTrue(_migrate_retired_managed_cloud(config))
        once = copy.deepcopy(config)
        with self.assertNoLogs("knight_flow.config", level="INFO"):
            self.assertEqual(_migrate_retired_managed_cloud(config), [])
        self.assertEqual(config, once)

    def test_a_clean_config_is_not_touched(self) -> None:
        config = owner_shaped()
        del config["stt"]["cloud_provider"]
        del config["stt"]["providers"]["talk_dat_cloud"]
        before = copy.deepcopy(config)
        self.assertEqual(_migrate_retired_managed_cloud(config), [])
        self.assertEqual(config, before)

    def test_nothing_it_leaves_behind_names_the_managed_service(self) -> None:
        config = self.worst_case()
        _migrate_retired_managed_cloud(config)
        text = json.dumps(config)
        self.assertNotIn("talk_dat_cloud", text)
        self.assertNotIn("4r4fn23yga", text)
        self.assertNotIn("knightaiav.com", text)


class ByokIsUntouchedTests(unittest.TestCase):
    def test_byok_keys_providers_and_routes_survive(self) -> None:
        config = {
            "stt": {
                "provider": "openai",
                "cloud_provider": "openai",
                "route_mode": "byok",
                "providers": {
                    "openai": {"api_key": BYOK_KEY, "api_base": "", "model": "gpt-4o-transcribe"},
                    "deepgram": {"api_key": BYOK_KEY, "api_base": "https://api.deepgram.com"},
                    # Their own server on Cloud Run: a *.run.app host that is
                    # not ours. It must survive.
                    "custom_openai": {"api_key": BYOK_KEY, "api_base": "https://my-whisper-abc123-uc.a.run.app"},
                },
            },
            "transforms": {
                "llm": {"provider": "anthropic", "api_key": BYOK_KEY, "api_base": "https://api.anthropic.com"},
                "providers": {"openai": {"api_key": BYOK_KEY}},
            },
            "translation": {"engine": "local", "api_base": "http://192.168.1.20:11434"},
        }
        before = copy.deepcopy(config)
        self.assertEqual(_migrate_retired_managed_cloud(config), [])
        self.assertEqual(config, before)

    def test_scrubbing_the_managed_entry_leaves_every_neighbour_key(self) -> None:
        config = owner_shaped()
        for provider_id in ("deepgram", "custom_openai"):
            config["stt"]["providers"][provider_id]["api_key"] = BYOK_KEY
        _migrate_retired_managed_cloud(config)
        self.assertEqual(config["stt"]["providers"]["deepgram"]["api_key"], BYOK_KEY)
        self.assertEqual(config["stt"]["providers"]["custom_openai"]["api_key"], BYOK_KEY)


class MemoryCredentialStore:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.available = True
        self.description = "test vault"

    def read(self, target: str) -> str:
        return self.values.get(target, "")

    def write(self, target: str, secret: str) -> bool:
        self.values[target] = secret
        return True

    def delete(self, target: str) -> bool:
        self.values.pop(target, None)
        return True


class LoadConfigRunsItTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_home = os.environ.get("TALK_DAT_HOME")
        self._old_deepgram = os.environ.pop("DEEPGRAM_API_KEY", None)
        self.store = MemoryCredentialStore()
        self._patch = patch("knight_flow.credentials.credential_store", return_value=self.store)
        self._patch.start()
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["TALK_DAT_HOME"] = self._tmp.name

    def tearDown(self) -> None:
        self._patch.stop()
        self._tmp.cleanup()
        if self._old_home is None:
            os.environ.pop("TALK_DAT_HOME", None)
        else:
            os.environ["TALK_DAT_HOME"] = self._old_home
        if self._old_deepgram is not None:
            os.environ["DEEPGRAM_API_KEY"] = self._old_deepgram

    def _write(self, config: dict) -> None:
        Path(self._tmp.name, "config.json").write_text(json.dumps(config), encoding="utf-8")

    def test_the_owners_file_loads_clean(self) -> None:
        self._write(owner_shaped())
        config = load_config(Path(self._tmp.name))
        self.assertNotIn("cloud_provider", config["stt"])
        self.assertNotIn("talk_dat_cloud", config["stt"]["providers"])
        self.assertEqual(config["stt"]["provider"], "local")
        self.assertEqual(config["stt"]["route_mode"], "local")

    def test_a_vault_only_byok_key_keeps_a_cloud_route_on_byok(self) -> None:
        """The key lives only in Credential Manager, as it does on Windows.
        Run before hydration, the migration would not see it and would move
        the person to local; it runs after, so they stay on their own key."""
        self.store.values[credential_target("STT", "openai")] = BYOK_KEY
        self._write({"stt": {"route_mode": "cloud", "provider": "openai", "cloud_provider": "openai",
                             "providers": {"openai": {"api_key": ""}}}})
        config = load_config(Path(self._tmp.name))
        self.assertEqual(config["stt"]["route_mode"], "byok")
        self.assertEqual(config["stt"]["providers"]["openai"]["api_key"], BYOK_KEY)

    def test_the_scrub_persists_through_a_save(self) -> None:
        """save_config carries missing TOP-LEVEL sections forward from disk.
        The scrubbed keys are nested, so a save must not bring them back."""
        from knight_flow.config import save_config

        self._write(owner_shaped())
        save_config(load_config(Path(self._tmp.name)))
        on_disk = json.loads(Path(self._tmp.name, "config.json").read_text(encoding="utf-8"))
        self.assertNotIn("cloud_provider", on_disk["stt"])
        self.assertNotIn("talk_dat_cloud", on_disk["stt"]["providers"])
        self.assertNotIn("4r4fn23yga", json.dumps(on_disk))


if __name__ == "__main__":
    unittest.main()
