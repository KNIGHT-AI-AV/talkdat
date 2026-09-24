"""Saving or resetting a test profile must not construct a real OS vault."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tests.credential_sandbox import isolated_store
from knight_flow import credentials, licensing

class CredentialSandboxTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="talkdat-vault-proof-")
        self.addCleanup(self.temp.cleanup)
        patcher = patch.dict(os.environ, TALK_DAT_HOME=self.temp.name)
        patcher.start(); self.addCleanup(patcher.stop)

    def test_default_and_early_imported_factories_are_isolated(self):
        with patch.object(credentials, "WindowsCredentialStore", side_effect=AssertionError("real vault")), \
             patch.object(credentials, "MacKeychainStore", side_effect=AssertionError("real vault")):
            self.assertIs(credentials.credential_store(), isolated_store())
            self.assertIs(licensing.credential_store(), isolated_store())

    def test_synthetic_homes_do_not_share_credentials(self):
        isolated_store().write("TalkDat/STT/example", "synthetic")
        with patch.dict(os.environ, TALK_DAT_HOME=str(Path(self.temp.name) / "second")):
            self.assertEqual(isolated_store().read("TalkDat/STT/example"), "")
        self.assertEqual(isolated_store().read("TalkDat/STT/example"), "synthetic")

    def test_default_reset_deletes_only_synthetic_provider_keys(self):
        from knight_flow.reset import perform
        target = credentials.credential_target("STT", "deepgram")
        license_target = credentials.credential_target("License", "entitlement")
        isolated_store().write(target, "synthetic")
        isolated_store().write(license_target, "synthetic-license")
        with patch.object(credentials, "WindowsCredentialStore", side_effect=AssertionError("real vault")), \
             patch.object(credentials, "MacKeychainStore", side_effect=AssertionError("real vault")):
            perform(["settings"], Path(self.temp.name), read_config=dict, write_config=lambda *_: None)
        self.assertEqual(isolated_store().read(target), "")
        self.assertEqual(isolated_store().read(license_target), "synthetic-license")

    def test_default_persistence_and_hydration_use_synthetic_vault(self):
        config = {"deepgram": {"api_key": "synthetic-key"}}
        with patch.object(credentials, "WindowsCredentialStore", side_effect=AssertionError("real vault")), \
             patch.object(credentials, "MacKeychainStore", side_effect=AssertionError("real vault")):
            saved = credentials.config_for_persistence(config)
            self.assertEqual(saved["deepgram"]["api_key"], "")
            hydrated = credentials.hydrate_config_secrets(saved)
            self.assertEqual(hydrated["deepgram"]["api_key"], "synthetic-key")

if __name__ == "__main__":
    unittest.main()
