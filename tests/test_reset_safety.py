import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from knight_flow import reset

class ResetSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="talkdat-reset-safety-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "profile"; self.root.mkdir()
        self.external = Path(self.temp.name) / "external"; self.external.mkdir()
        self.saved = {"dictionary": {"words": ["Name"]}, "translation": {"glossary": [{"source":"term"}], "enabled":True}}
        self.writes = []
        vault=patch.object(reset,"delete_all_credentials",return_value=True)
        self.vault=vault.start();self.addCleanup(vault.stop)

    def erase(self, chosen, **kwargs):
        return reset.perform(chosen,self.root,read_config=lambda:self.saved,
                             write_config=lambda value,_:self.writes.append(value),**kwargs)

    def link(self, path, target, directory=False):
        try: path.symlink_to(target,target_is_directory=directory)
        except OSError as error: self.skipTest("Link creation unavailable: "+type(error).__name__)

    def test_linked_file_is_refused_and_external_text_kept(self):
        outside=self.external/"words.txt";outside.write_text("keep")
        self.link(self.root/"history.jsonl",outside)
        with self.assertRaises(ValueError):self.erase(["history"])
        self.assertEqual(outside.read_text(),"keep")

    def test_linked_folder_is_refused(self):
        self.link(self.root/"audio-spool",self.external,True)
        with self.assertRaises(ValueError):self.erase(["voice_sessions"])
        self.assertTrue(self.external.exists())

    def test_nested_link_is_refused_before_any_delete(self):
        folder=self.root/"audio-spool";folder.mkdir()
        original=folder/"first.wav";original.write_bytes(b"keep")
        self.link(folder/"second.wav",self.external/"missing")
        with self.assertRaises(ValueError):self.erase(["voice_sessions"])
        self.assertEqual(original.read_bytes(),b"keep")

    def test_linked_app_root_is_refused(self):
        linked=Path(self.temp.name)/"linked";self.link(linked,self.root,True)
        with self.assertRaises(ValueError):reset.plan(["history"],linked)

    def test_replaced_file_requires_new_preview(self):
        file=self.root/"history.jsonl";file.write_bytes(b"old")
        before=reset.plan(["history"],self.root)
        other=self.root/"new";other.write_bytes(b"new");other.replace(file)
        with self.assertRaisesRegex(ValueError,"changed"):self.erase(["history"],expected=before)
        self.assertEqual(file.read_bytes(),b"new")

    def test_new_folder_child_requires_new_preview(self):
        folder=self.root/"audio-spool";folder.mkdir()
        (folder/"first.wav").write_bytes(b"old")
        before=reset.plan(["voice_sessions"],self.root)
        (folder/"second.wav").write_bytes(b"new")
        with self.assertRaisesRegex(ValueError,"changed"):self.erase(["voice_sessions"],expected=before)
        self.assertTrue((folder/"first.wav").exists())

    def test_wrong_preview_categories_are_refused(self):
        before=reset.plan(["dictionary"],self.root)
        with self.assertRaisesRegex(ValueError,"changed"):self.erase(["settings"],expected=before)
        self.assertFalse(self.writes)
        self.vault.assert_not_called()

    def test_late_new_child_is_never_recursively_deleted(self):
        folder=self.root/"audio-spool";folder.mkdir()
        (folder/"old.wav").write_bytes(b"123")
        original=Path.unlink
        def unlink(path,*args,**kwargs):
            result=original(path,*args,**kwargs)
            if path.name=="old.wav":(folder/"late.wav").write_bytes(b"keep")
            return result
        with patch.object(Path,"unlink",unlink):result=self.erase(["voice_sessions"])
        self.assertEqual((folder/"late.wav").read_bytes(),b"keep")
        self.assertIn("audio-spool",result["failed"])
        self.assertEqual(result["bytes_freed"],3)

    def test_partial_directory_delete_reports_only_removed_bytes(self):
        folder=self.root/"audio-spool";folder.mkdir()
        (folder/"good.wav").write_bytes(b"123");(folder/"locked.wav").write_bytes(b"12345")
        original=Path.unlink
        def unlink(path,*args,**kwargs):
            if path.name=="locked.wav":raise PermissionError()
            return original(path,*args,**kwargs)
        with patch.object(Path,"unlink",unlink):result=self.erase(["voice_sessions"])
        self.assertEqual(result["bytes_freed"],3)
        self.assertIn("audio-spool",result["failed"])
        self.assertNotIn("audio-spool",result["removed"])

    def test_unexpected_directory_at_file_path_is_refused(self):
        (self.root/"history.jsonl").mkdir()
        (self.root/"history.jsonl"/"keep.txt").write_text("keep")
        with self.assertRaises(ValueError):self.erase(["history"])
        self.assertTrue((self.root/"history.jsonl"/"keep.txt").exists())

    def test_bounded_preview_refuses_overlarge_tree(self):
        folder=self.root/"models";folder.mkdir()
        for i in range(4):(folder/str(i)).write_bytes(b"x")
        with patch.object(reset,"_MAX_ENTRIES",2),self.assertRaises(ValueError):
            self.erase(["models"])
        self.assertEqual(len(list(folder.iterdir())),4)

    def test_failed_config_write_preserves_provider_keys(self):
        with patch.object(reset,"prune_config",side_effect=OSError("fixture")):
            result=self.erase(["settings"])
        self.assertIn("cleanup",result["failed"])
        self.vault.assert_not_called()

    def test_settings_keep_personal_translation_glossary(self):
        self.erase(["settings"])
        self.assertEqual(self.writes[0]["translation"]["glossary"],self.saved["translation"]["glossary"])
        self.assertNotIn("enabled",self.writes[0]["translation"])

    def test_dictionary_clear_removes_glossary_without_changing_route(self):
        self.erase(["dictionary"])
        self.assertNotIn("glossary",self.writes[0]["translation"])
        self.assertTrue(self.writes[0]["translation"]["enabled"])

    def test_unlisted_data_is_kept(self):
        (self.root/"unknown-document.txt").write_text("keep")
        (self.root/"plugins").mkdir()
        (self.root/"plugins"/"custom.py").write_text("keep")
        self.erase(["history","dictionary"])
        self.assertTrue((self.root/"unknown-document.txt").exists())
        self.assertTrue((self.root/"plugins"/"custom.py").exists())

if __name__=="__main__":unittest.main()

