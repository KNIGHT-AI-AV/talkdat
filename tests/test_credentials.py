from __future__ import annotations

import json
import os
import time
import unittest
import uuid

from knight_flow.credentials import (
    UnavailableCredentialStore,
    WindowsCredentialStore,
    config_for_persistence,
    credential_target,
    delete_all_credentials,
    hydrate_config_secrets,
)


class MemoryCredentialStore:
    def __init__(self, values: dict[str, str] | None = None, *, fail_writes: bool = False) -> None:
        self.values = dict(values or {})
        self.fail_writes = fail_writes
        self.available = True
        self.description = "test vault"

    def read(self, target: str) -> str:
        return self.values.get(target, "")

    def write(self, target: str, secret: str) -> bool:
        if self.fail_writes:
            return False
        self.values[target] = secret
        return True

    def delete(self, target: str) -> bool:
        self.values.pop(target, None)
        return True


def sample_config() -> dict:
    return {
        "deepgram": {"api_key": "deepgram-secret"},
        "stt": {
            "providers": {
                "deepgram": {"api_key": ""},
                "openai": {"api_key": "openai-stt-secret"},
                "local": {"api_key": ""},
            }
        },
        "transforms": {
            "llm": {"provider": "openai", "api_key": "openai-llm-secret"},
        },
        "remote": {"token": "control-secret"},
    }


class CredentialPersistenceTests(unittest.TestCase):
    def test_plaintext_secrets_migrate_and_persisted_copy_is_redacted(self) -> None:
        store = MemoryCredentialStore()
        config = sample_config()

        hydrate_config_secrets(config, store=store)
        persisted = config_for_persistence(config, store=store)

        self.assertEqual(config["deepgram"]["api_key"], "deepgram-secret")
        self.assertEqual(config["stt"]["providers"]["deepgram"]["api_key"], "deepgram-secret")
        self.assertEqual(persisted["deepgram"]["api_key"], "")
        self.assertEqual(persisted["stt"]["providers"]["deepgram"]["api_key"], "")
        self.assertEqual(persisted["stt"]["providers"]["openai"]["api_key"], "")
        self.assertEqual(persisted["transforms"]["llm"]["api_key"], "")
        self.assertEqual(persisted["remote"]["token"], "")
        self.assertEqual(store.values[credential_target("STT", "deepgram")], "deepgram-secret")
        self.assertEqual(store.values[credential_target("STT", "openai")], "openai-stt-secret")
        self.assertEqual(store.values[credential_target("LLM", "openai")], "openai-llm-secret")
        self.assertEqual(store.values[credential_target("Remote", "control-token")], "control-secret")

    def test_vault_values_hydrate_blank_runtime_config(self) -> None:
        store = MemoryCredentialStore(
            {
                credential_target("STT", "deepgram"): "vault-deepgram",
                credential_target("LLM", "anthropic"): "vault-anthropic",
            }
        )
        config = {
            "deepgram": {"api_key": ""},
            "stt": {"providers": {"deepgram": {"api_key": ""}}},
            "transforms": {"llm": {"provider": "anthropic", "api_key": ""}},
            "remote": {"token": ""},
        }

        hydrate_config_secrets(config, store=store)

        self.assertEqual(config["deepgram"]["api_key"], "vault-deepgram")
        self.assertEqual(config["stt"]["providers"]["deepgram"]["api_key"], "vault-deepgram")
        self.assertEqual(config["transforms"]["llm"]["api_key"], "vault-anthropic")

    def test_a_refused_vault_write_never_falls_back_to_plaintext(self) -> None:
        """X-202: this used to assert the opposite, and the opposite was a leak.

        A store that is PRESENT but refuses a particular secret is not the same
        as no store at all. The absent-store case is handled above this loop by
        `if backend.available` and is a disclosed, deliberate fallback for
        platforms with no keyring. This case is different: Settings has told
        the user their key is protected by Windows, and on a refusal the key
        was written into config.json in plain text anyway.

        It is not hypothetical. The Windows store rejects any secret whose
        UTF-16 encoding exceeds 2560 bytes, and a Google service-account JSON
        or a long-lived JWT clears that easily.

        The trade is deliberate and it is not free: a key that cannot be stored
        is now lost and has to be pasted again. That is recoverable in thirty
        seconds. A credential sitting in plain text on a machine that later
        changes hands, under a UI that says it is protected, is not recoverable
        at all -- and the user would never know to try.

        It is only safe because the refusal is REPORTED, which the next test
        pins. Blanking silently would trade a leak for a key that vanished for
        no stated reason.
        """
        config = sample_config()
        persisted = config_for_persistence(config, store=MemoryCredentialStore(fail_writes=True))

        self.assertEqual(persisted["deepgram"]["api_key"], "")
        self.assertEqual(persisted["stt"]["providers"]["openai"]["api_key"], "")
        self.assertEqual(persisted["transforms"]["llm"]["api_key"], "")
        self.assertEqual(persisted["remote"]["token"], "")
        for secret in ("deepgram-secret", "openai-stt-secret", "openai-llm-secret", "control-secret"):
            with self.subTest(secret=secret):
                self.assertNotIn(secret, json.dumps(persisted))

    def test_the_user_is_told_when_a_key_could_not_be_stored(self) -> None:
        """Otherwise the fix above is just a key disappearing in silence."""
        import knight_flow.credentials as credentials

        credentials._VAULT_FAILURES.clear()
        self.addCleanup(credentials._VAULT_FAILURES.clear)
        config_for_persistence(sample_config(), store=MemoryCredentialStore(fail_writes=True))
        status = credentials.credential_storage_status()
        self.assertIn("refused to store", status)
        self.assertIn("NOT written to disk", status)

    def test_an_absent_store_still_falls_back_as_designed(self) -> None:
        """The platform case the change must NOT touch: with no keyring at all
        the app is documented to keep keys in config.json, and breaking that
        would leave macOS and Linux unable to hold a key anywhere."""
        config = sample_config()
        persisted = config_for_persistence(config, store=UnavailableCredentialStore())
        self.assertEqual(persisted["deepgram"]["api_key"], "deepgram-secret")

    def test_clearing_runtime_secret_deletes_vault_entry(self) -> None:
        target = credential_target("STT", "openai")
        store = MemoryCredentialStore({target: "old-secret"})
        config = sample_config()
        hydrate_config_secrets(config, store=store)
        config["stt"]["providers"]["openai"]["api_key"] = ""

        persisted = config_for_persistence(config, store=store)

        self.assertEqual(persisted["stt"]["providers"]["openai"]["api_key"], "")
        self.assertNotIn(target, store.values)

    def test_private_data_removal_deletes_all_known_vault_entries(self) -> None:
        store = MemoryCredentialStore(
            {
                credential_target("STT", "deepgram"): "dg",
                credential_target("STT", "xai"): "xai",
                credential_target("LLM", "openai"): "llm",
                credential_target("LLM", "anthropic"): "old-llm",
                credential_target("Remote", "control-token"): "remote",
                credential_target("License", "entitlement"): "signed-license",
            }
        )

        self.assertTrue(delete_all_credentials(sample_config(), store=store))
        self.assertEqual(store.values, {})

    def test_private_data_removal_attempts_every_target_after_one_delete_fails(self) -> None:
        store = MemoryCredentialStore()
        calls: list[str] = []

        def delete(target: str) -> bool:
            calls.append(target)
            return len(calls) != 1

        store.delete = delete  # type: ignore[method-assign]

        self.assertFalse(delete_all_credentials(sample_config(), store=store))
        self.assertGreater(len(calls), 5)


@unittest.skipUnless(os.name == "nt", "Windows Credential Manager integration")
class WindowsCredentialStoreIntegrationTests(unittest.TestCase):
    def test_generic_credential_round_trip(self) -> None:
        store = WindowsCredentialStore()
        target = f"TalkDat/Test/{uuid.uuid4()}"
        secret = f"temporary-{uuid.uuid4()}"
        try:
            self.assertTrue(store.write(target, secret))
            self.assertEqual(store.read(target), secret)
        finally:
            store.delete(target)
        self.assertEqual(store.read(target), "")


if __name__ == "__main__":
    unittest.main()


class TheKeychainReadCannotFreezeStartupTests(unittest.TestCase):
    """A blocked Keychain read used to take the whole application with it.

    Secrets are hydrated while the configuration loads, before any window
    exists. macOS asks permission before handing an item to a binary whose
    signature it does not recognise, and the read then sits inside
    SecItemCopyMatching until somebody answers -- with no window, no Pill and an
    empty log, because the freeze happens before the first line is written.

    Seen for real on this port: each rebuild changed the ad-hoc signature, the
    stored item's ACL stopped matching, and every launch hung.
    """

    def _store_with_keyring(self, fake: object) -> object:
        from knight_flow.credentials import KeychainCredentialStore

        store = KeychainCredentialStore.__new__(KeychainCredentialStore)
        store.available = True
        store._keyring = fake
        return store

    def test_a_read_that_never_returns_is_abandoned(self) -> None:
        import threading as _threading

        release = _threading.Event()
        self.addCleanup(release.set)

        class HangingKeyring:
            def get_password(self, service: str, account: str) -> str:
                release.wait(30)
                return "too late"

        store = self._store_with_keyring(HangingKeyring())
        started = time.monotonic()
        value = store._read_without_hanging("TalkDat/deepgram/api_key", timeout=0.4)
        elapsed = time.monotonic() - started

        self.assertEqual(value, "", "a blocked read must not return a value")
        self.assertLess(elapsed, 5, "the read did not give up; startup would freeze")

    def test_a_read_that_answers_is_returned_unchanged(self) -> None:
        class WorkingKeyring:
            def get_password(self, service: str, account: str) -> str:
                return "sk-live-value"

        store = self._store_with_keyring(WorkingKeyring())
        self.assertEqual(
            store._read_without_hanging("TalkDat/deepgram/api_key"), "sk-live-value"
        )

    def test_a_read_that_raises_is_reported_as_absent(self) -> None:
        class BrokenKeyring:
            def get_password(self, service: str, account: str) -> str:
                raise RuntimeError("keychain unavailable")

        store = self._store_with_keyring(BrokenKeyring())
        self.assertEqual(store._read_without_hanging("TalkDat/x/y"), "")


class OneKeychainPromptMustNotCostFiftySecondsTests(unittest.TestCase):
    """Thirteen secret groups are hydrated while the configuration loads.

    Waiting the full timeout for each of them turned a four second delay into
    fifty-two. Measured before this guard: forty seconds from launch to the
    first log line, with no window on screen for any of it.

    One timeout means a dialog is up, and it will still be up for the next read,
    so the rest are skipped. Whatever the user answers applies on the next
    launch either way.
    """

    class _Hanging:
        def __init__(self, release) -> None:
            self.calls = 0
            self._release = release

        def get_password(self, service: str, account: str) -> str:
            self.calls += 1
            self._release.wait(60)
            return "too late"

    def test_only_the_first_read_waits(self) -> None:
        import threading as _threading

        from knight_flow.credentials import KeychainCredentialStore

        release = _threading.Event()
        self.addCleanup(release.set)
        fake = self._Hanging(release)

        store = KeychainCredentialStore.__new__(KeychainCredentialStore)
        store.available = True
        store._keyring = fake
        store._prompt_blocked = False

        started = time.monotonic()
        for index in range(13):
            self.assertEqual(store.read(f"TalkDat/provider{index}/api_key"), "")
        elapsed = time.monotonic() - started

        self.assertLess(elapsed, 15, "every read waited; startup would take most of a minute")
        self.assertEqual(fake.calls, 1, "the keychain was asked more than once while blocked")


class WritesAndDeletesMustBeBoundedTooTests(unittest.TestCase):
    """Guarding only `read` made the freeze worse, not better.

    A read that gives up returns "", the caller concludes the secret is absent
    and immediately writes or deletes it, and that call blocks on the very same
    dialog. Startup hung inside SecItemDelete instead of SecItemCopyMatching --
    a different stack, the same frozen app with no window on screen.
    """

    def _blocked_store(self, release):
        from knight_flow.credentials import KeychainCredentialStore

        class Hanging:
            def get_password(self, service, account):
                release.wait(60)
                return "x"

            def set_password(self, service, account, value):
                release.wait(60)

            def delete_password(self, service, account):
                release.wait(60)

        store = KeychainCredentialStore.__new__(KeychainCredentialStore)
        store.available = True
        store._keyring = Hanging()
        store._prompt_blocked = False
        return store

    def test_a_blocked_write_gives_up(self) -> None:
        import threading as _threading

        release = _threading.Event()
        self.addCleanup(release.set)
        store = self._blocked_store(release)

        started = time.monotonic()
        self.assertFalse(store.write("TalkDat/x/y", "secret"))
        self.assertLess(time.monotonic() - started, 15)

    def test_a_blocked_delete_gives_up(self) -> None:
        import threading as _threading

        release = _threading.Event()
        self.addCleanup(release.set)
        store = self._blocked_store(release)

        started = time.monotonic()
        self.assertFalse(store.delete("TalkDat/x/y"))
        self.assertLess(time.monotonic() - started, 15)

    def test_one_block_stops_every_kind_of_call(self) -> None:
        """The real startup mixes all three. Whichever blocks first must stop
        the others, or the delay is still counted in tens of seconds."""
        import threading as _threading

        release = _threading.Event()
        self.addCleanup(release.set)
        store = self._blocked_store(release)

        started = time.monotonic()
        store.read("first")
        for index in range(12):
            store.read(f"r{index}")
            store.write(f"w{index}", "x")
            store.delete(f"d{index}")
        self.assertLess(
            time.monotonic() - started, 15,
            "later calls kept waiting; startup would stall for most of a minute",
        )
