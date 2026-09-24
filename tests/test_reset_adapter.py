import copy
from pathlib import Path
from types import SimpleNamespace
import tempfile
import threading
import unittest
from unittest.mock import Mock,patch
from knight_flow import reset
from knight_flow.web_shell.reset_adapter import ResetActions
from knight_flow.web_shell.reset_workspace import config_revision

class ResetAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix="talkdat-reset-adapter-");self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.timers=[];self.posts=[];self.work=[]
        self.config={"dictionary":{"words":["keep"]},"licensing":{"device_id":"keep"}}
        self.app=SimpleNamespace(config=self.config,paused=False,_quitting=False,lock=threading.RLock(),
            overlay=SimpleNamespace(root=SimpleNamespace(after=lambda _ms,work:self.timers.append(work)),utility_windows={}),
            _cross_thread_calls=SimpleNamespace(put=self.posts.append),refresh_wake_word=Mock(),
            _auxiliary_audio_exit=Mock(return_value=True),quit=Mock(),last_transcript="old",
            license_manager=SimpleNamespace(forget_license=Mock(return_value=True)))
        self.shell=SimpleNamespace(app=self.app,_capture_busy=Mock(return_value=False),
            models=SimpleNamespace(lock=threading.RLock(),status={}),
            workspaces=SimpleNamespace(services={}))
        self.actions=ResetActions(self.shell,launch=self.work.append,threads=lambda:[])
        self.complete=Mock()
        registry=patch("knight_flow.web_shell.reset_adapter.microphone_registry",return_value=SimpleNamespace(names=lambda:()))
        registry.start();self.addCleanup(registry.stop)
        saver=patch("knight_flow.web_shell.reset_adapter.save_config")
        self.save=saver.start();self.addCleanup(saver.stop)

    def execute(self,keys=None):
        intended=reset.plan(keys or ["dictionary"],self.root)
        self.actions.execute(intended,config_revision(self.config,intended.config_keys),self.complete)

    def settle(self):
        while self.timers:self.timers.pop(0)()
        while self.work:self.work.pop(0)()
        while self.posts:self.posts.pop(0)()

    def test_capture_prevents_reset(self):
        self.shell._capture_busy.return_value=True
        with self.assertRaises(ValueError):self.execute()
        self.assertFalse(self.timers)

    def test_model_download_prevents_reset(self):
        self.shell.models.status["sample"]={"state":"working"}
        self.assertTrue(self.actions.busy())

    def test_export_prevents_reset(self):
        self.shell.workspaces._history_exports=SimpleNamespace(active=True)
        self.assertTrue(self.actions.busy())

    def test_writer_thread_prevents_reset(self):
        self.actions.threads=lambda:[SimpleNamespace(name="TalkDatPronunciationRefresh",is_alive=lambda:True)]
        self.assertTrue(self.actions.busy())

    def test_open_legacy_editor_prevents_reset(self):
        self.app.overlay.utility_windows["scratchpad"]=SimpleNamespace(winfo_exists=lambda:True)
        self.assertTrue(self.actions.busy())

    def test_execute_first_pauses_without_deleting(self):
        self.execute()
        self.assertTrue(self.app._reset_in_progress);self.assertTrue(self.app.paused)
        self.assertIn("dictionary",self.config)
        self.complete.assert_not_called()

    def test_audio_timeout_does_not_erase_and_restores_state(self):
        def fail(_resume):self.app._quitting=False;return False
        self.app._auxiliary_audio_exit.side_effect=fail
        self.execute();self.settle()
        self.assertIn("dictionary",self.config)
        self.assertFalse(self.app._reset_in_progress);self.assertFalse(self.app.paused)
        self.assertIn("error",self.complete.call_args.kwargs)

    def test_new_work_during_prepare_prevents_reset(self):
        self.execute()
        self.shell.workspaces._history_exports=SimpleNamespace(active=True)
        self.settle()
        self.assertIn("dictionary",self.config);self.save.assert_not_called()

    def test_selected_settings_changed_before_worker_are_kept(self):
        self.execute();self.timers.pop(0)()
        self.config["dictionary"]["words"].append("new")
        self.settle()
        self.assertEqual(self.config["dictionary"]["words"],["keep","new"])
        self.assertFalse(self.app._reset_in_progress)

    def test_failed_save_keeps_in_memory_settings(self):
        self.save.side_effect=OSError("fixture")
        before=copy.deepcopy(self.config);self.execute();self.settle()
        self.assertEqual(self.config,before)
        self.assertTrue(self.app._reset_finished)
        self.assertIn("dictionary",self.complete.call_args.kwargs["result"]["failed"])

    def test_success_persists_then_adopts_in_place_and_stays_paused(self):
        identity=id(self.config);seen=[]
        self.save.side_effect=lambda *_a,**_k:seen.append(copy.deepcopy(self.config))
        self.execute();self.settle()
        self.assertEqual(id(self.app.config),identity);self.assertNotIn("dictionary",self.config)
        self.assertIn("dictionary",seen[0]);self.assertTrue(self.app._reset_finished)
        self.assertTrue(self.app.paused);self.assertTrue(self.app._quitting)

    def test_worker_launch_failure_restores_pause_and_keeps_data(self):
        self.actions.launch=Mock(side_effect=RuntimeError("fixture"))
        self.execute();self.settle()
        self.assertFalse(self.app._reset_in_progress);self.assertFalse(self.app.paused)
        self.assertIn("dictionary",self.config)

    def test_history_reset_clears_in_memory_last_text(self):
        (self.root/"history.jsonl").write_text("old")
        self.execute(["history"]);self.settle()
        self.assertEqual(self.app.last_transcript,"")
        self.assertFalse((self.root/"history.jsonl").exists())

    def test_finish_queues_existing_clean_quit(self):
        with self.assertRaises(ValueError):self.actions.finish()
        self.execute();self.settle();self.actions.finish()
        self.app.quit.assert_not_called()
        self.posts.pop(0)();self.app.quit.assert_called_once_with(settings_confirmed=True)

    def test_shared_editor_closes_before_deletion(self):
        clip=self.root/"pronunciation"/"term.wav";clip.parent.mkdir();clip.write_bytes(b"123")
        seen=[]
        self.shell.workspaces.services["notes"]=SimpleNamespace(close=lambda:seen.append(clip.exists()))
        self.execute();self.settle()
        self.assertEqual(seen,[True]);self.assertFalse(clip.exists())

if __name__=="__main__":unittest.main()

