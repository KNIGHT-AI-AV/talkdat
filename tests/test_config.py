from __future__ import annotations

import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from knight_flow.config import LOCAL_FORMATTER_MODEL, load_config
from knight_flow.local_stt import DEFAULT_LOCAL_MODEL_ID
from knight_flow.stt_registry import models_for_provider, provider_id_for_label, provider_label, selected_provider_id


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


class ConfigDefaultsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_home = os.environ.get("TALK_DAT_HOME")
        self._old_deepgram = os.environ.get("DEEPGRAM_API_KEY")
        self._old_sounddevice = sys.modules.get("sounddevice")
        self._credential_store = MemoryCredentialStore()
        self._credential_patch = patch(
            "knight_flow.credentials.credential_store", return_value=self._credential_store
        )
        self._credential_patch.start()
        os.environ.pop("DEEPGRAM_API_KEY", None)

    def tearDown(self) -> None:
        self._credential_patch.stop()
        if self._old_home is None:
            os.environ.pop("TALK_DAT_HOME", None)
        else:
            os.environ["TALK_DAT_HOME"] = self._old_home
        if self._old_deepgram is None:
            os.environ.pop("DEEPGRAM_API_KEY", None)
        else:
            os.environ["DEEPGRAM_API_KEY"] = self._old_deepgram
        if self._old_sounddevice is None:
            sys.modules.pop("sounddevice", None)
        else:
            sys.modules["sounddevice"] = self._old_sounddevice

    def test_fresh_config_starts_local_with_everything_armed(self) -> None:
        """X-85 flipped this deliberately.

        A new install used to start on the on-device engine, which meant the
        first thing a person experienced was the slowest path -- while they
        were still deciding whether to keep the app. Every account now has a
        free weekly cloud allowance, so the cloud is the honest default. The
        local stack stays fully configured and auto-downloading underneath:
        the moment the allowance or the network runs out, it takes over with
        no setup and no interruption.
        """
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["TALK_DAT_HOME"] = tmp
            config = load_config(Path(tmp))
        # X-480: reversed deliberately. X-85 started new installs on the
        # managed cloud and called it "the faster and more accurate path".
        # Both halves were measured afterwards and neither survived: local
        # formatting at 880 ms against the cloud's 978, and the speed probe
        # at 8.8x realtime. There is also no managed cloud to start on now.
        self.assertEqual(config["stt"]["provider"], "local")
        self.assertEqual(config["stt"]["providers"]["local"]["model"], DEFAULT_LOCAL_MODEL_ID)
        self.assertTrue(config["stt"]["auto_download_local_model"])
        self.assertEqual(config["transforms"]["llm"]["provider"], "auto")
        self.assertEqual(config["transforms"]["llm"]["model"], LOCAL_FORMATTER_MODEL)
        self.assertEqual(config["transforms"]["llm"]["model"], "qwen3:1.7b")
        self.assertEqual(config["dictation"]["clipboard_paste_delay_ms"], 10)
        self.assertEqual(config["cleanup"]["max_ai_format_ms"], 1200)
        self.assertTrue(config["overlay"]["show_session_over_fullscreen"])
        self.assertEqual(config["overlay"]["resize_frame_ms"], 8)
        self.assertEqual(config["overlay"]["resize_steps"], 22)
        self.assertEqual((config["overlay"]["active_width"], config["overlay"]["active_height"]), (192, 35))
        self.assertEqual((config["overlay"]["compact_width"], config["overlay"]["compact_height"]), (92, 26))
        self.assertTrue(config["dictation"]["safety_recordings_enabled"])
        self.assertEqual(config["dictation"]["safety_recording_limit"], 5)

    def test_audio_safety_migrates_to_an_always_on_five_session_floor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["TALK_DAT_HOME"] = tmp
            Path(tmp, "config.json").write_text(
                json.dumps(
                    {
                        "dictation": {
                            "safety_recordings_enabled": False,
                            "safety_recording_limit": 1,
                        }
                    }
                ),
                encoding="utf-8",
            )
            config = load_config(Path(tmp))
        self.assertTrue(config["dictation"]["safety_recordings_enabled"])
        self.assertEqual(config["dictation"]["safety_recording_limit"], 5)

    def test_missing_provider_fallback_is_local(self) -> None:
        self.assertEqual(selected_provider_id({}), "local")
        self.assertEqual(provider_id_for_label(""), "local")
        self.assertEqual(provider_label("unknown-provider"), "Local / On-Device")
        self.assertEqual(models_for_provider("unknown-provider")[0].id, DEFAULT_LOCAL_MODEL_ID)

    def test_blank_legacy_deepgram_config_migrates_to_local(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["TALK_DAT_HOME"] = tmp
            Path(tmp, "config.json").write_text(
                json.dumps({"stt": {"provider": "deepgram"}, "deepgram": {"api_key": ""}}),
                encoding="utf-8",
            )
            config = load_config(Path(tmp))
        self.assertEqual(config["stt"]["provider"], "local")

    def test_deepgram_key_preserves_deepgram_route(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["TALK_DAT_HOME"] = tmp
            Path(tmp, "config.json").write_text(
                json.dumps({"stt": {"provider": "deepgram"}, "deepgram": {"api_key": "dg-test"}}),
                encoding="utf-8",
            )
            config = load_config(Path(tmp))
        self.assertEqual(config["stt"]["provider"], "deepgram")

    def test_vaulted_deepgram_key_preserves_deepgram_route(self) -> None:
        from knight_flow.credentials import credential_target

        store = MemoryCredentialStore()
        store.values[credential_target("STT", "deepgram")] = "vaulted-dg-test"
        with tempfile.TemporaryDirectory() as tmp, patch(
            "knight_flow.credentials.credential_store", return_value=store
        ):
            os.environ["TALK_DAT_HOME"] = tmp
            Path(tmp, "config.json").write_text(
                json.dumps({"stt": {"provider": "deepgram"}, "deepgram": {"api_key": ""}}),
                encoding="utf-8",
            )
            config = load_config(Path(tmp))

        self.assertEqual(config["stt"]["provider"], "deepgram")
        self.assertEqual(config["deepgram"]["api_key"], "vaulted-dg-test")

    def test_legacy_paste_delay_default_migrates_faster(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["TALK_DAT_HOME"] = tmp
            Path(tmp, "config.json").write_text(
                json.dumps({"dictation": {"clipboard_paste_delay_ms": 80}}), encoding="utf-8"
            )
            config = load_config(Path(tmp))
        self.assertEqual(config["dictation"]["clipboard_paste_delay_ms"], 10)

    def test_previous_fast_paste_default_migrates_to_current_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["TALK_DAT_HOME"] = tmp
            Path(tmp, "config.json").write_text(
                json.dumps({"dictation": {"clipboard_paste_delay_ms": 30}}), encoding="utf-8"
            )
            config = load_config(Path(tmp))
        self.assertEqual(config["dictation"]["clipboard_paste_delay_ms"], 10)

    def test_previous_motion_defaults_migrate_to_quicker_timeline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["TALK_DAT_HOME"] = tmp
            Path(tmp, "config.json").write_text(
                json.dumps({"overlay": {"resize_frame_ms": 10, "resize_steps": 28}}),
                encoding="utf-8",
            )
            config = load_config(Path(tmp))
        self.assertEqual(config["overlay"]["resize_frame_ms"], 8)
        self.assertEqual(config["overlay"]["resize_steps"], 22)

    def test_previous_default_pill_geometry_migrates_to_half_scale_and_lower_anchor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["TALK_DAT_HOME"] = tmp
            Path(tmp, "config.json").write_text(
                json.dumps(
                    {
                        "overlay": {
                            "width": 320,
                            "height": 58,
                            "active_pill_width": 320,
                            "active_pill_height": 58,
                            "active_width": 320,
                            "active_height": 58,
                            "compact_width": 150,
                            "compact_height": 44,
                            "bottom_margin": 68,
                        }
                    }
                ),
                encoding="utf-8",
            )
            config = load_config(Path(tmp))

        overlay = config["overlay"]
        self.assertEqual((overlay["active_width"], overlay["active_height"]), (192, 35))
        self.assertEqual((overlay["compact_width"], overlay["compact_height"]), (92, 26))
        self.assertEqual(overlay["bottom_margin"], 24)
        self.assertTrue(overlay["half_scale_migrated"])
        self.assertTrue(overlay["balanced_scale_migrated"])

    def test_previous_half_scale_defaults_migrate_to_balanced_scale(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["TALK_DAT_HOME"] = tmp
            Path(tmp, "config.json").write_text(
                json.dumps(
                    {
                        "overlay": {
                            "width": 160,
                            "height": 29,
                            "active_pill_width": 160,
                            "active_pill_height": 29,
                            "active_width": 160,
                            "active_height": 29,
                            "compact_width": 75,
                            "compact_height": 22,
                            "bottom_margin": 24,
                            "half_scale_migrated": True,
                        }
                    }
                ),
                encoding="utf-8",
            )
            config = load_config(Path(tmp))

        overlay = config["overlay"]
        self.assertEqual((overlay["active_width"], overlay["active_height"]), (192, 35))
        self.assertEqual((overlay["compact_width"], overlay["compact_height"]), (92, 26))
        self.assertEqual(overlay["bottom_margin"], 24)
        self.assertTrue(overlay["balanced_scale_migrated"])

    def test_explicit_custom_geometry_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["TALK_DAT_HOME"] = tmp
            Path(tmp, "config.json").write_text(
                json.dumps(
                    {
                        "overlay": {
                            "active_width": 210,
                            "active_height": 36,
                            "compact_width": 92,
                            "compact_height": 24,
                            "bottom_margin": 14,
                            "half_scale_migrated": True,
                        }
                    }
                ),
                encoding="utf-8",
            )
            config = load_config(Path(tmp))

        overlay = config["overlay"]
        self.assertEqual((overlay["active_width"], overlay["active_height"]), (210, 36))
        self.assertEqual((overlay["compact_width"], overlay["compact_height"]), (92, 24))
        self.assertEqual(overlay["bottom_margin"], 14)

    def test_legacy_fullscreen_default_shows_only_active_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["TALK_DAT_HOME"] = tmp
            Path(tmp, "config.json").write_text(
                json.dumps({"overlay": {"show_session_over_fullscreen": False}}),
                encoding="utf-8",
            )
            config = load_config(Path(tmp))

        self.assertTrue(config["overlay"]["show_session_over_fullscreen"])
        self.assertTrue(config["overlay"]["fullscreen_activation_visibility_migrated"])

    def test_explicit_fullscreen_activation_preference_is_preserved_after_migration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["TALK_DAT_HOME"] = tmp
            Path(tmp, "config.json").write_text(
                json.dumps(
                    {
                        "overlay": {
                            "show_session_over_fullscreen": False,
                            "fullscreen_activation_visibility_migrated": True,
                        }
                    }
                ),
                encoding="utf-8",
            )
            config = load_config(Path(tmp))

        self.assertFalse(config["overlay"]["show_session_over_fullscreen"])

    def test_custom_motion_values_are_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["TALK_DAT_HOME"] = tmp
            Path(tmp, "config.json").write_text(
                json.dumps({"overlay": {"resize_frame_ms": 9, "resize_steps": 25}}),
                encoding="utf-8",
            )
            config = load_config(Path(tmp))
        self.assertEqual(config["overlay"]["resize_frame_ms"], 9)
        self.assertEqual(config["overlay"]["resize_steps"], 25)

    def test_previous_local_formatter_default_migrates_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["TALK_DAT_HOME"] = tmp
            Path(tmp, "config.json").write_text(
                json.dumps(
                    {
                        "transforms": {
                            "llm": {
                                "provider": "ollama",
                                "model": "qwen3:0.6b",
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            config = load_config(Path(tmp))
        self.assertEqual(config["transforms"]["llm"]["model"], "qwen3:1.7b")
        self.assertTrue(config["transforms"]["llm"]["balanced_default_migrated"])

    def test_custom_local_formatter_model_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["TALK_DAT_HOME"] = tmp
            Path(tmp, "config.json").write_text(
                json.dumps(
                    {
                        "transforms": {
                            "llm": {
                                "provider": "ollama",
                                "model": "gemma3:4b",
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            config = load_config(Path(tmp))
        self.assertEqual(config["transforms"]["llm"]["model"], "gemma3:4b")

    def test_beta_install_migrates_legacy_stable_channel_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["TALK_DAT_HOME"] = tmp
            Path(tmp, "config.json").write_text(
                json.dumps(
                    {
                        "updates": {
                            "channel": "stable",
                            "current_version": "0.3.18-beta",
                        }
                    }
                ),
                encoding="utf-8",
            )
            config = load_config(Path(tmp))

        self.assertEqual(config["updates"]["channel"], "beta")
        self.assertTrue(config["updates"]["prerelease_channel_migrated"])

    def test_save_moves_plaintext_provider_key_out_of_config_json(self) -> None:
        from knight_flow.config import save_config

        store = MemoryCredentialStore()
        with tempfile.TemporaryDirectory() as tmp, patch(
            "knight_flow.credentials.credential_store", return_value=store
        ):
            os.environ["TALK_DAT_HOME"] = tmp
            config = load_config(Path(tmp))
            config["deepgram"]["api_key"] = "private-deepgram-key"
            config["stt"]["providers"]["deepgram"]["api_key"] = "private-deepgram-key"
            save_config(config)
            persisted = json.loads(Path(tmp, "config.json").read_text(encoding="utf-8"))

        self.assertEqual(config["deepgram"]["api_key"], "private-deepgram-key")
        self.assertEqual(persisted["deepgram"]["api_key"], "")
        self.assertEqual(persisted["stt"]["providers"]["deepgram"]["api_key"], "")

    def test_numeric_audio_device_migrates_to_labeled_selection(self) -> None:
        sys.modules["sounddevice"] = types.SimpleNamespace(
            query_devices=lambda: [
                {"name": "Speakers", "max_input_channels": 0},
                {"name": "Studio Mic", "max_input_channels": 1},
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["TALK_DAT_HOME"] = tmp
            Path(tmp, "config.json").write_text(json.dumps({"audio": {"input_device": "1"}}), encoding="utf-8")
            config = load_config(Path(tmp))
        self.assertEqual(config["audio"]["input_device"], "1: Studio Mic")

    def test_numeric_audio_device_does_not_pin_low_confidence_device(self) -> None:
        sys.modules["sounddevice"] = types.SimpleNamespace(
            query_devices=lambda: [
                {"name": "Speakers", "max_input_channels": 0},
                {"name": "Headset Microphone (DualSense Controller)", "max_input_channels": 1},
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["TALK_DAT_HOME"] = tmp
            Path(tmp, "config.json").write_text(json.dumps({"audio": {"input_device": "1"}}), encoding="utf-8")
            config = load_config(Path(tmp))
        self.assertEqual(config["audio"]["input_device"], "")


if __name__ == "__main__":
    unittest.main()


class InstantCorrectionReachesInstallationsThatAlreadyExistTests(unittest.TestCase):
    """Changing a default is not enough when the old value is already on disk.

    `save_config` writes the whole merged config, so every installation that
    has ever opened Settings has a literal `false` for undo_replacement.
    Changing DEFAULT_CONFIG alone would deliver the faster correction to people
    who have not installed yet and to nobody who is currently waiting for a
    paragraph to delete itself -- which is the wrong half of the audience for a
    complaint that came from using the product.

    Rewriting a saved setting is normally wrong. It is safe here only because
    the setting had no UI until this release, so a `false` on disk is the old
    default rather than a decision. That justification stops being true now
    that Settings can write it, which is why the migration matches `False`
    exactly and leaves the string forms alone.
    """

    def migrated(self, loaded: dict) -> object:
        from knight_flow.config import _migrate_undo_replacement_default
        saved = loaded.get("dictation")
        config = {"dictation": dict(saved) if isinstance(saved, dict) else {}}
        _migrate_undo_replacement_default(config, loaded)
        return config["dictation"].get("undo_replacement")

    def test_the_old_always_off_value_becomes_per_application(self) -> None:
        self.assertEqual(self.migrated({"dictation": {"undo_replacement": False}}), "auto")

    def test_a_deliberate_never_is_left_alone(self) -> None:
        """What the Settings toggle writes for "Never", and the escape hatch
        for anyone who edited the file by hand and wants it to stay off."""
        self.assertEqual(self.migrated({"dictation": {"undo_replacement": "never"}}), "never")

    def test_a_deliberate_always_is_left_alone(self) -> None:
        self.assertIs(self.migrated({"dictation": {"undo_replacement": True}}), True)

    def test_an_already_migrated_config_is_not_touched_again(self) -> None:
        self.assertEqual(self.migrated({"dictation": {"undo_replacement": "auto"}}), "auto")

    def test_a_config_that_never_mentioned_it_inherits_the_new_default(self) -> None:
        """Nothing to migrate -- deep_merge supplies "auto" from DEFAULT_CONFIG."""
        for loaded in ({}, {"dictation": {}}, {"dictation": "not-a-dict"}):
            with self.subTest(loaded=loaded):
                self.assertIsNone(self.migrated(loaded))

    def test_it_runs_during_load(self) -> None:
        """A migration nobody calls is worse than none, because it reads as done."""
        from pathlib import Path
        source = (Path(__file__).resolve().parents[1] / "knight_flow" / "config.py").read_text(encoding="utf-8")
        load = source[source.index("def load_config("):]
        self.assertIn("_migrate_undo_replacement_default(config,", load)
