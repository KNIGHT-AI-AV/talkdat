from __future__ import annotations

import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path

from knight_flow.config import app_dir, config_path
from knight_flow.packs import (
    BACKUP_FILES,
    PACK_VERSION,
    export_backup,
    export_diagnostics,
    export_pack,
    import_pack,
    is_secret_field,
    restore_backup,
)


SOURCE_CONFIG = {
    "dictionary": {
        "words": ["Knightsbridge", "Mayowa"],
        "replacements": [{"from": "teh", "to": "the"}],
    },
    "snippets": [{"trigger": "sig", "text": "Best, M", "enabled": True}],
}


class SecretFieldTests(unittest.TestCase):
    def test_credential_shaped_names_are_secret(self) -> None:
        for name in (
            "api_key",
            "API_KEY",
            "token",
            "remote_token",
            "password",
            "passphrase",
            "client_secret",
            "credential",
            "authorization",
            "bearer_token",
            "signature",
            "private_key_pem",
        ):
            self.assertTrue(is_secret_field(name), name)

    def test_hotkeys_and_keyterms_stay_visible_for_support(self) -> None:
        for name in ("hotkeys", "hotkey", "keyboard", "keyterms", "keyterm", "keys", "author"):
            self.assertFalse(is_secret_field(name), name)

    def test_ordinary_settings_are_not_secret(self) -> None:
        for name in ("provider", "language", "cleanup", "port", "enabled", "theme"):
            self.assertFalse(is_secret_field(name), name)


class PackTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        previous = os.environ.get("TALK_DAT_HOME")
        os.environ["TALK_DAT_HOME"] = self.home.name

        def restore() -> None:
            if previous is None:
                os.environ.pop("TALK_DAT_HOME", None)
            else:
                os.environ["TALK_DAT_HOME"] = previous

        self.addCleanup(restore)
        self.workdir = Path(self.home.name)


class ExportPackTests(PackTestCase):
    def test_a_pack_carries_vocabulary_and_snippets(self) -> None:
        path = export_pack(SOURCE_CONFIG, self.workdir / "team.json")
        pack = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(pack["talkdat_pack"], PACK_VERSION)
        self.assertEqual(pack["name"], "team")
        self.assertEqual(pack["dictionary"]["words"], ["Knightsbridge", "Mayowa"])
        self.assertEqual(pack["snippets"][0]["trigger"], "sig")

    def test_a_pack_never_carries_credentials(self) -> None:
        config = dict(SOURCE_CONFIG, deepgram={"api_key": "should-not-travel"}, remote={"token": "nope"})
        body = export_pack(config, self.workdir / "team.json").read_text(encoding="utf-8")
        self.assertNotIn("should-not-travel", body)
        self.assertNotIn("nope", body)
        self.assertNotIn("api_key", body)

    def test_an_empty_config_still_produces_a_valid_pack(self) -> None:
        pack = json.loads(export_pack({}, self.workdir / "empty.json").read_text(encoding="utf-8"))
        self.assertEqual(pack["dictionary"]["words"], [])
        self.assertEqual(pack["snippets"], [])


class ImportPackTests(PackTestCase):
    def pack_file(self, payload: dict, name: str = "incoming.json", encoding: str = "utf-8") -> Path:
        path = self.workdir / name
        path.write_text(json.dumps(payload), encoding=encoding)
        return path

    def test_new_entries_are_added_and_counted(self) -> None:
        config: dict = {}
        added = import_pack(config, self.pack_file({
            "talkdat_pack": 1,
            "dictionary": {"words": ["Xylophone"], "replacements": [{"from": "adn", "to": "and"}]},
            "snippets": [{"trigger": "addr", "text": "1 High St"}],
        }))
        self.assertEqual(added, {"words": 1, "replacements": 1, "snippets": 1})
        self.assertEqual(config["dictionary"]["words"], ["Xylophone"])
        self.assertEqual(config["snippets"][0]["trigger"], "addr")

    def test_existing_entries_are_not_duplicated(self) -> None:
        config = json.loads(json.dumps(SOURCE_CONFIG))
        added = import_pack(config, self.pack_file({
            "talkdat_pack": 1,
            "dictionary": {"words": ["mayowa", "MAYOWA"], "replacements": [{"from": "TEH", "to": "the"}]},
            "snippets": [{"trigger": "SIG", "text": "different"}],
        }))
        self.assertEqual(added, {"words": 0, "replacements": 0, "snippets": 0})
        self.assertEqual(config["dictionary"]["words"], ["Knightsbridge", "Mayowa"])
        self.assertEqual(config["snippets"][0]["text"], "Best, M", "an import must not overwrite local text")

    def test_blank_and_malformed_entries_are_skipped(self) -> None:
        config: dict = {}
        added = import_pack(config, self.pack_file({
            "talkdat_pack": 1,
            "dictionary": {"words": ["  ", ""], "replacements": ["not-a-dict", {"from": "  "}]},
            "snippets": ["not-a-dict", {"trigger": ""}],
        }))
        self.assertEqual(added, {"words": 0, "replacements": 0, "snippets": 0})

    def test_a_file_that_is_not_a_pack_is_rejected(self) -> None:
        for payload in ({"words": ["nope"]}, [1, 2, 3]):
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    import_pack({}, self.pack_file(payload))

    def test_a_pack_saved_with_a_byte_order_mark_still_imports(self) -> None:
        path = self.pack_file(
            {"talkdat_pack": 1, "dictionary": {"words": ["Bom"]}}, encoding="utf-8-sig"
        )
        self.assertEqual(import_pack({}, path)["words"], 1)

    def test_snippets_default_to_enabled(self) -> None:
        config: dict = {}
        import_pack(config, self.pack_file({"talkdat_pack": 1, "snippets": [{"trigger": "x", "text": "y"}]}))
        self.assertTrue(config["snippets"][0]["enabled"])


class BackupTests(PackTestCase):
    def test_backup_round_trips_only_the_known_files(self) -> None:
        root = app_dir()
        (root / "config.json").write_text('{"provider": "local"}', encoding="utf-8")
        (root / "pinned.json").write_text("[]", encoding="utf-8")
        (root / "unrelated.txt").write_text("ignore me", encoding="utf-8")

        archive_path = export_backup(self.workdir / "backup.zip")
        with zipfile.ZipFile(archive_path) as archive:
            names = set(archive.namelist())
        self.assertEqual(names, {"config.json", "pinned.json"})

        (root / "config.json").write_text("{}", encoding="utf-8")
        restored = restore_backup(archive_path)
        self.assertEqual(set(restored), {"config.json", "pinned.json"})
        self.assertIn("local", (root / "config.json").read_text(encoding="utf-8"))

    def test_restore_ignores_unexpected_archive_members(self) -> None:
        stray = self.workdir / "stray.zip"
        with zipfile.ZipFile(stray, "w") as archive:
            archive.writestr("config.json", "{}")
            archive.writestr("evil.txt", "should not be extracted")
        restored = restore_backup(stray)
        self.assertEqual(restored, ["config.json"])
        self.assertFalse((app_dir() / "evil.txt").exists())

    def test_every_backup_file_name_is_a_plain_relative_name(self) -> None:
        for name in BACKUP_FILES:
            self.assertNotIn("/", name)
            self.assertNotIn("\\", name)
            self.assertNotIn("..", name)


class DiagnosticsTests(PackTestCase):
    def test_credentials_are_redacted_and_settings_are_kept(self) -> None:
        config_path().write_text(
            json.dumps(
                {
                    "provider": "deepgram",
                    "deepgram": {"api_key": "live-secret-value", "language": "en"},
                    "remote": {"enabled": True, "token": "another-secret"},
                    "hotkeys": {"trigger": "ctrl+win", "panic": "ctrl+win+esc"},
                    "snippets": [{"trigger": "sig", "text": "Best, M"}],
                }
            ),
            encoding="utf-8",
        )
        with zipfile.ZipFile(export_diagnostics()) as archive:
            redacted = archive.read("config.redacted.json").decode("utf-8")
            environment = archive.read("environment.txt").decode("utf-8")

        self.assertNotIn("live-secret-value", redacted)
        self.assertNotIn("another-secret", redacted)
        self.assertEqual(redacted.count("[redacted]"), 2)
        # The parts support actually needs must survive.
        self.assertIn("ctrl+win+esc", redacted)
        self.assertIn("deepgram", redacted)
        self.assertIn('"language": "en"', redacted)
        self.assertIn("Talk DAT!", environment)

    def test_a_missing_or_corrupt_config_still_produces_a_bundle(self) -> None:
        with zipfile.ZipFile(export_diagnostics()) as archive:
            self.assertEqual(archive.read("config.redacted.json").decode("utf-8"), "{}")

        config_path().write_text("{ not json", encoding="utf-8")
        with zipfile.ZipFile(export_diagnostics()) as archive:
            self.assertEqual(archive.read("config.redacted.json").decode("utf-8"), "{}")

    def test_nested_credentials_are_redacted_too(self) -> None:
        config_path().write_text(
            json.dumps({"providers": [{"name": "groq", "api_key": "nested-secret"}]}),
            encoding="utf-8",
        )
        with zipfile.ZipFile(export_diagnostics()) as archive:
            redacted = archive.read("config.redacted.json").decode("utf-8")
        self.assertNotIn("nested-secret", redacted)
        self.assertIn("groq", redacted)

    def test_the_bundle_lands_inside_the_app_directory(self) -> None:
        path = export_diagnostics()
        self.assertEqual(path.parent.name, "diagnostics")
        self.assertTrue(str(path).startswith(self.home.name))


if __name__ == "__main__":
    unittest.main()
