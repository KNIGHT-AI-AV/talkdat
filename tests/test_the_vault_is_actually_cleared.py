"""X-194 / X-195 / X-196: three ways "start over" did nothing, all reported OK.

These are grouped because they share one shape: an operation whose success was
INFERRED from a return value that never described the disk.

1. Sign out (X-194) erased the entitlement by writing an EMPTY STRING. The
   credential store refuses an empty secret before it ever reaches CredWriteW,
   so the write returned False, the token stayed in the vault, and the app told
   the user "Windows Credential Manager was unavailable" while the vault was
   working perfectly. On every Windows machine, every time. Whoever got the PC
   next inherited a paid entitlement and the account identity inside it.

2. Reset (X-195) never touched the vault at all -- delete_all_credentials was
   reachable only from the uninstaller. "Everything, start completely over"
   left every live Deepgram and OpenAI key on the machine, and the next
   install rehydrates them into config on first launch and can spend the
   previous owner's balance.

3. Reset (X-196) also failed to remove any CONFIG section, for an unrelated
   reason that happened to be invisible in the same way. X-140 added
   carry-forward -- a section on disk but absent from memory is restored,
   because a stale process must not erase a newer file. prune_config deletes
   the section, so absence was exactly what it produced, and save_config
   dutifully put it back. Custom words, snippets, settings and onboarding all
   survived a full factory reset, which reported success and a byte count.

The fakes are what let all three live: every existing test stubs the store with
a lambda or a dict that accepts anything. So the fake here deliberately
reproduces the REAL refusal rule, and the config tests write a real file.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import knight_flow.config as config_module
from knight_flow.credentials import credential_target, delete_all_credentials
from knight_flow.licensing import LICENSE_TARGET, LicenseManager
from knight_flow.reset import PRESETS, perform, prune_config


class HonestStore:
    """A fake that refuses what the real Windows store refuses.

    The one line that matters is the empty-secret guard. Every fake in the
    suite before this accepted write(target, "") and returned True, which is
    why three tests covered forget_license and all three certified the bug.
    """

    available = True

    def __init__(self, **initial: str) -> None:
        self.items = dict(initial)

    def read(self, target: str) -> str:
        return self.items.get(target, "")

    def write(self, target: str, secret: str) -> bool:
        if not target or not secret:
            return False
        self.items[target] = secret
        return True

    def delete(self, target: str) -> bool:
        self.items.pop(target, None)
        return True  # the real store treats ERROR_NOT_FOUND as success


class SigningOutSignsOutTests(unittest.TestCase):
    def manager(self, store: HonestStore) -> LicenseManager:
        manager = LicenseManager.__new__(LicenseManager)
        manager.store = store
        return manager

    def test_the_token_is_gone_from_the_vault_afterwards(self) -> None:
        store = HonestStore(**{LICENSE_TARGET: "signed.jwt.value"})
        self.assertTrue(self.manager(store).forget_license())
        self.assertNotIn(LICENSE_TARGET, store.items, "the entitlement survived sign out")

    def test_it_reports_success_rather_than_a_false_alarm(self) -> None:
        """The user-visible half. Before the fix this returned False and the
        app blamed Credential Manager for a bug in its own call."""
        self.assertTrue(self.manager(HonestStore(**{LICENSE_TARGET: "x"})).forget_license())

    def test_signing_out_twice_is_not_an_error(self) -> None:
        self.assertTrue(self.manager(HonestStore()).forget_license())

    def test_the_trial_start_is_still_left_alone(self) -> None:
        """Deliberate: signing out must not double as a fresh fourteen days.
        This is why the fix is delete(LICENSE_TARGET) and not a full wipe."""
        trial = credential_target("License", "trial")
        store = HonestStore(**{LICENSE_TARGET: "x", trial: "2026-01-01"})
        self.manager(store).forget_license()
        self.assertEqual(store.items.get(trial), "2026-01-01")


class ResettingClearsTheVaultTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = Path(tempfile.mkdtemp())
        self.config = {
            "stt": {"providers": {"deepgram": {"api_key": "dg-live-key"}}},
            "transforms": {"llm": {"provider": "gemini", "api_key": "gm-live-key"}},
            "remote": {"token": "control-token"},
        }
        self.store = HonestStore(
            **{
                credential_target("STT", "deepgram"): "dg-live-key",
                credential_target("LLM", "gemini"): "gm-live-key",
                credential_target("Remote", "control-token"): "control-token",
                LICENSE_TARGET: "signed.jwt.value",
            }
        )
        patcher = patch("knight_flow.credentials.credential_store", lambda: self.store)
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_reset(self, preset: str) -> dict:
        return perform(
            list(PRESETS[preset]),
            self.dir,
            read_config=lambda: self.config,
            write_config=lambda _c, _f=(): None,
            forget_license=lambda: True,
        )

    def test_everything_leaves_no_provider_key_behind(self) -> None:
        self.run_reset("everything")
        left = [t for t in self.store.items if t != LICENSE_TARGET]
        self.assertEqual(left, [], f"live API keys survived a full reset: {left}")

    def test_a_settings_reset_does_not_sign_a_paying_customer_out(self) -> None:
        """The reason delete_all_credentials grew include_license. Clearing
        settings must clear keys without silently deactivating the machine."""
        self.run_reset("settings_only")
        self.assertIn(LICENSE_TARGET, self.store.items, "a settings reset signed the user out")

    def test_the_deletion_reads_the_config_before_it_is_pruned(self) -> None:
        """The subtle half of the bug, and the reason ORDER is load-bearing.

        A user's own provider targets are enumerated FROM the config. Prune
        first and there is nothing left to enumerate, so the delete runs, finds
        nothing, and returns success -- indistinguishable from having worked.
        """
        seen: list[dict] = []
        real = delete_all_credentials

        def spy(config=None, **kwargs):
            seen.append(json.loads(json.dumps(config)) if config else {})
            return real(config, **kwargs)

        with patch("knight_flow.reset.delete_all_credentials", spy):
            self.run_reset("everything")
        self.assertTrue(seen, "the reset never tried to clear the vault")
        self.assertIn("stt", seen[0], "the vault was cleared from an already-pruned config")


class ResettingActuallyRemovesConfigSectionsTests(unittest.TestCase):
    """X-196. Written against a real file because the defect lived entirely in
    the write path -- every in-memory assertion about prune_config passed."""

    def setUp(self) -> None:
        self.path = Path(tempfile.mkdtemp()) / "config.json"
        patcher = patch.object(config_module, "config_path", lambda: self.path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write(self, payload: dict) -> None:
        self.path.write_text(json.dumps(payload), encoding="utf-8")

    def on_disk(self) -> dict:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def test_a_reset_section_does_not_come_back(self) -> None:
        self.write({"dictionary": {"words": ["Mayowa"]}, "snippets": {"a": "b"}})
        pruned = prune_config(self.on_disk(), ("dictionary", "snippets"))
        config_module.save_config(pruned, forget_sections=("dictionary", "snippets"))
        after = self.on_disk()
        self.assertNotIn("dictionary", after, "months of taught words survived a factory reset")
        self.assertNotIn("snippets", after)

    def test_an_ordinary_save_still_cannot_erase_a_section_it_never_loaded(self) -> None:
        """X-140 must survive the fix. It exists because the founder's own
        diagnostics flag was wiped twice by a stale in-memory flush."""
        self.write({"dictionary": {"words": ["Mayowa"]}, "diagnostics": True})
        config_module.save_config({"snippets": {}})
        after = self.on_disk()
        self.assertEqual(after["dictionary"], {"words": ["Mayowa"]})
        self.assertTrue(after["diagnostics"])

    def test_forgetting_is_opt_in(self) -> None:
        """A caller that says nothing gets the protective behaviour. Deletion
        has to be STATED -- inferring it from absence is the entire bug."""
        self.write({"dictionary": {"words": ["Mayowa"]}})
        config_module.save_config({})
        self.assertIn("dictionary", self.on_disk())


class ARefusedVaultWriteNeverFallsBackToDiskTests(unittest.TestCase):
    """X-202: the refusal path wrote the secret to config.json in plaintext.

    The Windows store refuses any secret whose UTF-16 encoding exceeds 2560
    bytes. `config_for_persistence` only blanked the in-memory field when the
    write SUCCEEDED, so on a refusal the key fell through and was serialised
    straight into config.json -- while Settings went on telling the user the
    key was protected by Windows Credential Manager.

    Not hypothetical: a Google service-account JSON is comfortably over the
    limit, and so is any long-lived JWT.
    """

    def setUp(self) -> None:
        import knight_flow.credentials as credentials

        self.credentials = credentials
        credentials._VAULT_FAILURES.clear()
        self.addCleanup(credentials._VAULT_FAILURES.clear)

    def refusing_store(self) -> HonestStore:
        class TooBig(HonestStore):
            def write(self, target: str, secret: str) -> bool:
                if len(secret.encode("utf-16-le")) > 2560:
                    return False
                return super().write(target, secret)

        return TooBig()

    def config_with(self, secret: str) -> dict:
        return {"transforms": {"llm": {"provider": "gemini", "api_key": secret}}}

    def test_an_oversized_key_does_not_reach_the_file(self) -> None:
        oversized = "k" * 4000
        persisted = self.credentials.config_for_persistence(
            self.config_with(oversized), store=self.refusing_store()
        )
        self.assertNotIn(
            oversized, json.dumps(persisted),
            "a credential the vault refused was written to config.json in plaintext",
        )

    def test_the_refusal_is_recorded_rather_than_swallowed(self) -> None:
        """Blanking the field silently is the second-worst outcome: the key
        vanishes and nothing anywhere says why."""
        self.credentials.config_for_persistence(
            self.config_with("k" * 4000), store=self.refusing_store()
        )
        self.assertTrue(
            self.credentials.vault_failures(),
            "the vault refused a secret and nothing recorded it",
        )

    def test_a_normal_key_still_round_trips(self) -> None:
        store = self.refusing_store()
        persisted = self.credentials.config_for_persistence(
            self.config_with("sk-normal-length-key"), store=store
        )
        self.assertEqual(persisted["transforms"]["llm"]["api_key"], "")
        self.assertEqual(
            store.items[credential_target("LLM", "gemini")], "sk-normal-length-key"
        )
        self.assertEqual(self.credentials.vault_failures(), ())


class NoProviderKeyCanOutliveAFullResetTests(unittest.TestCase):
    """X-213: a live key surviving "Everything, start completely over".

    delete_all_credentials removes a fixed list of targets when it is not
    handed the config that names them. That list was maintained by hand beside
    two registries that grow, and it had drifted: "openrouter" and
    "talk_dat_cloud" were missing from STT, "auto" and "talk_dat_cloud" from
    LLM.

    "auto" is the one that bites, because it is the SHIPPED DEFAULT for AI
    rewrite. Paste a key, later switch the provider to anything else, then run
    the strongest reset: TalkDat/LLM/auto is no longer named by the config, is
    not in the hand-written list, and stays in Credential Manager for whoever
    gets the machine next -- while the dialog reports a clean wipe.

    The lists are derived from the registries now, so this is about keeping
    them derived.
    """

    def test_every_provider_the_app_offers_is_a_removable_target(self) -> None:
        from knight_flow.credentials import _vaultable_stt_ids
        from knight_flow.stt_registry import PROVIDER_BY_ID

        missing = sorted((set(PROVIDER_BY_ID) - {"local"}) - set(_vaultable_stt_ids()))
        self.assertEqual(
            missing, [],
            f"these STT providers can hold a key that no reset removes: {missing}",
        )

    def test_every_formatter_the_app_offers_is_a_removable_target(self) -> None:
        from knight_flow.credentials import _vaultable_llm_ids
        from knight_flow.llm import PROVIDER_DEFAULTS

        missing = sorted((set(PROVIDER_DEFAULTS) - {"ollama"}) - set(_vaultable_llm_ids()))
        self.assertEqual(missing, [], f"these formatters can orphan a key: {missing}")

    def test_the_shipped_default_provider_is_covered(self) -> None:
        """"auto" is not in either registry as a key -- it is the value the
        default config writes -- so it has to be named explicitly, and this is
        what says so."""
        from knight_flow.credentials import _vaultable_llm_ids

        self.assertIn("auto", _vaultable_llm_ids())

    def test_an_orphaned_auto_key_is_removed_by_a_full_reset(self) -> None:
        """The reproduction, end to end."""
        directory = Path(tempfile.mkdtemp())
        store = HonestStore(**{credential_target("LLM", "auto"): "sk-LIVE-KEY"})
        # The config no longer names it: the user moved on to ollama.
        config = {"transforms": {"llm": {"provider": "ollama"}}}
        with patch("knight_flow.credentials.credential_store", lambda: store):
            perform(
                list(PRESETS["everything"]), directory,
                read_config=lambda: config,
                write_config=lambda _c, _f=(): None,
                forget_license=lambda: True,
            )
        self.assertEqual(
            store.items, {},
            f"a live provider key survived a full factory reset: {list(store.items)}",
        )


class ResetOnlyTakesWhatWasTickedTests(unittest.TestCase):
    """X-212, and it was mine.

    The vault wipe was gated on "this plan touches any config key", which is
    true for Snippets, Onboarding and Custom words as well as Settings. So
    ticking only "Custom words and phrases" -- a category whose whole promise
    is that it forgets WORDS -- deleted every saved API key on the machine.

    It hid well: keys still named in the live config are rewritten to the vault
    on the next save, so only ORPHANED entries stayed gone. This module's own
    docstring is built on the asymmetry it broke: failing to delete costs a
    second attempt, deleting too much costs work nobody can get back.
    """

    def test_clearing_custom_words_leaves_saved_keys_alone(self) -> None:
        directory = Path(tempfile.mkdtemp())
        store = HonestStore(**{credential_target("LLM", "openai"): "sk-LIVE-KEY"})
        with patch("knight_flow.credentials.credential_store", lambda: store):
            perform(
                ["dictionary"], directory,
                read_config=lambda: {"dictionary": {"words": ["Mayowa"]}},
                write_config=lambda _c, _f=(): None,
                forget_license=lambda: True,
            )
        self.assertIn(
            credential_target("LLM", "openai"), store.items,
            "clearing the dictionary deleted the user's provider keys",
        )

    def test_clearing_settings_still_does_clear_them(self) -> None:
        directory = Path(tempfile.mkdtemp())
        store = HonestStore(**{credential_target("LLM", "openai"): "sk-LIVE-KEY"})
        with patch("knight_flow.credentials.credential_store", lambda: store):
            perform(
                ["settings"], directory,
                read_config=lambda: {"transforms": {"llm": {"provider": "openai", "api_key": "sk-LIVE-KEY"}}},
                write_config=lambda _c, _f=(): None,
                forget_license=lambda: True,
            )
        self.assertNotIn(credential_target("LLM", "openai"), store.items)


if __name__ == "__main__":
    unittest.main()
