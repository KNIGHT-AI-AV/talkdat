from __future__ import annotations

import tempfile
import unittest

from knight_flow.config import DEFAULT_CONFIG
from knight_flow.local_stt import (
    CUSTOM_MODEL_PREFIX,
    DEFAULT_LOCAL_MODEL_ID,
    LOCAL_MODELS,
    available_local_models,
    custom_model_from,
    custom_models,
    local_model_for_id,
    model_dir,
)


def config(*entries):
    return {"stt": {"providers": {"local": {"custom_models": list(entries)}}}}


class BringingYourOwnLocalModelTests(unittest.TestCase):
    """There is a universal path, which is the only reason this feature exists.

    faster-whisper's WhisperModel accepts, in its own documentation, "a path to
    a converted model directory, or a CTranslate2-converted Whisper model ID
    from the HF Hub". Every community Whisper fine-tune already published in
    that form therefore loads with no new code -- language specialists, domain
    fine-tunes, distilled variants, anything somebody converted themselves.

    It does not cover non-Whisper architectures, and that limit is worth being
    honest about rather than implying anything on the Hub will work. Those go
    through the request path instead.
    """

    def test_a_hugging_face_repo_id_becomes_a_usable_model(self) -> None:
        model = custom_model_from("deepdml/faster-whisper-large-v3-turbo-ct2")
        self.assertIsNotNone(model)
        self.assertEqual(model.engine, "faster_whisper")
        self.assertEqual(
            model.engine_id, "deepdml/faster-whisper-large-v3-turbo-ct2",
            "the reference is handed to faster-whisper unchanged",
        )
        self.assertTrue(model.id.startswith(CUSTOM_MODEL_PREFIX))

    def test_a_folder_on_this_machine_works_too(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            model = custom_model_from(folder)
            self.assertIsNotNone(model)
            self.assertEqual(model.engine_id, folder)

    def test_a_folder_that_does_not_exist_is_refused(self) -> None:
        self.assertIsNone(custom_model_from(r"C:\definitely\not\here\at\all"))

    def test_a_label_the_person_typed_is_kept(self) -> None:
        model = custom_model_from({"id": "owner/repo", "label": "My Swedish model"})
        self.assertIn("My Swedish model", model.label)

    def test_every_custom_model_is_marked_as_theirs(self) -> None:
        """So it is never mistaken for something Talk DAT! vouches for."""
        self.assertIn("(yours)", custom_model_from("owner/repo").label)


class JunkAndHostileInputAreRefusedTests(unittest.TestCase):
    """This string reaches a downloader and a filesystem path, so a lax rule
    here is the difference between a typo and a traversal."""

    def test_a_traversal_attempt_is_not_a_repo_id(self) -> None:
        self.assertIsNone(custom_model_from("../../etc/passwd"))
        self.assertIsNone(custom_model_from("..\\..\\windows\\system32"))

    def test_malformed_references_are_refused(self) -> None:
        for junk in ("", "   ", "not a repo id", "owner/", "/repo", "owner//repo", "a" * 300):
            with self.subTest(junk=junk):
                self.assertIsNone(custom_model_from(junk))

    def test_non_string_entries_do_not_raise(self) -> None:
        """This runs while building a settings list; one bad entry must not
        take the whole list down with it."""
        for junk in (123, None, [], object()):
            with self.subTest(junk=junk):
                self.assertIsNone(custom_model_from(junk))

    def test_a_broken_entry_does_not_hide_the_good_ones(self) -> None:
        models = custom_models(config("owner/good", "!!!junk!!!", "other/alsogood"))
        self.assertEqual([m.engine_id for m in models], ["owner/good", "other/alsogood"])

    def test_duplicates_are_collapsed(self) -> None:
        self.assertEqual(len(custom_models(config("owner/repo", "owner/repo"))), 1)

    def test_a_malformed_config_returns_nothing_rather_than_raising(self) -> None:
        for broken in ({}, {"stt": None}, {"stt": {"providers": "no"}},
                       {"stt": {"providers": {"local": {"custom_models": "not a list"}}}}):
            with self.subTest(broken=broken):
                self.assertEqual(custom_models(broken), ())


class CustomModelsReachTheRestOfTheAppTests(unittest.TestCase):
    def test_they_appear_alongside_the_packaged_catalogue(self) -> None:
        models = available_local_models(config("owner/repo"))
        self.assertEqual(len(models), len(LOCAL_MODELS) + 1)
        self.assertEqual(models[: len(LOCAL_MODELS)], LOCAL_MODELS,
                         "packaged models keep their order")

    def test_selecting_one_resolves_to_it_and_not_to_the_default(self) -> None:
        """The failure this prevents is silent: an unresolvable id falls back
        to Parakeet, so the person would dictate with a model they never chose
        and nothing would say so."""
        cfg = config({"id": "owner/repo", "label": "Mine"})
        resolved = local_model_for_id(f"{CUSTOM_MODEL_PREFIX}owner/repo", cfg)
        self.assertEqual(resolved.engine_id, "owner/repo")
        self.assertIn("Mine", resolved.label)

    def test_it_still_resolves_without_the_config(self) -> None:
        """transcribe() is called with an id and no config, so the id has to
        carry enough on its own."""
        resolved = local_model_for_id(f"{CUSTOM_MODEL_PREFIX}owner/repo")
        self.assertEqual(resolved.engine_id, "owner/repo")

    def test_an_unknown_id_still_falls_back_to_the_default(self) -> None:
        self.assertEqual(local_model_for_id("something-removed").id, DEFAULT_LOCAL_MODEL_ID)

    def test_the_config_ships_the_key_so_it_is_discoverable(self) -> None:
        self.assertEqual(DEFAULT_CONFIG["stt"]["providers"]["local"]["custom_models"], [])


class TheDownloadFolderIsAValidWindowsPathTests(unittest.TestCase):
    """A custom id carries a Hugging Face reference, and those contain a slash
    and a colon. A colon in a path component is the drive separator, so the
    folder is not merely oddly named -- it cannot be created at all."""

    def test_a_custom_model_folder_has_no_illegal_characters(self) -> None:
        folder = model_dir(custom_model_from("deepdml/faster-whisper-large-v3-turbo-ct2")).name
        for character in ':/\\<>"|?*':
            with self.subTest(character=character):
                self.assertNotIn(character, folder)

    def test_packaged_models_keep_the_folder_they_already_use(self) -> None:
        """Sanitising has to be a no-op for them, or every existing download is
        orphaned and silently fetched again."""
        for model in LOCAL_MODELS:
            with self.subTest(model=model.id):
                self.assertEqual(model_dir(model).name, model.id)

    def test_two_different_custom_models_do_not_share_a_folder(self) -> None:
        first = model_dir(custom_model_from("owner/repo")).name
        second = model_dir(custom_model_from("other/repo")).name
        self.assertNotEqual(first, second)


if __name__ == "__main__":
    unittest.main()
