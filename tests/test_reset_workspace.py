import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
from knight_flow import reset
from knight_flow.web_shell.reset_workspace import ResetWorkspace

class ResetWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix="talkdat-reset-workspace-");self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.config={"dictionary":{"words":["Keep"]},"licensing":{"device_id":"keep"}}
        self.busy=Mock(return_value=False);self.finish=Mock();self.jobs=[];self.posts=[];self.now=10
        self.executions=[]
        def execute(intended,revision,complete):
            self.executions.append((intended,revision))
            try:
                result=reset.perform([c.key for c in intended.categories],self.root,expected=intended,
                    read_config=lambda:self.config,write_config=self.write)
                complete(result)
            except Exception as error:complete(error=error)
        self.service=ResetWorkspace(self.config,self.root,self.posts.append,self.busy,execute,self.finish,
                                    launch=self.jobs.append,clock=lambda:self.now)
        vault=patch.object(reset,"delete_all_credentials",return_value=True);vault.start();self.addCleanup(vault.stop)

    def write(self,value,_):
        self.config.clear();self.config.update(value)

    def call(self,command,**payload):return self.service.handle({"command":command,**payload})
    def settle(self):
        while self.jobs:self.jobs.pop(0)()
        while self.posts:self.posts.pop(0)()
    def preview(self,selected=None):
        self.call("preview",selected=selected or ["history"]);self.settle()
        return self.call("state")["preview"]
    def confirm(self,preview,phrase="ERASE"):return self.call("confirm",token=preview["token"],phrase=phrase)

    def test_opening_and_previewing_do_not_delete(self):
        path=self.root/"history.jsonl";path.write_text("keep")
        self.call("state");self.preview()
        self.assertEqual(path.read_text(),"keep")
        self.assertFalse(self.executions)

    def test_preview_runs_off_the_request_path(self):
        with patch("knight_flow.web_shell.reset_workspace.plan",side_effect=AssertionError):
            state=self.call("preview",selected=["history"])
        self.assertEqual(state["phase"],"scanning")
        self.assertEqual(len(self.jobs),1)

    def test_cancel_discards_a_pending_worker_result(self):
        self.call("preview",selected=["history"]);self.call("cancel");self.settle()
        self.assertEqual(self.call("state")["phase"],"choose")
        self.assertIsNone(self.call("state")["preview"])

    def test_new_preview_replaces_old_worker_result(self):
        self.call("preview",selected=["history"]);self.call("preview",selected=["dictionary"])
        self.settle()
        self.assertEqual(self.call("state")["preview"]["categories"],["dictionary"])

    def test_confirmation_needs_owned_token(self):
        self.preview()
        with self.assertRaises(ValueError):self.call("confirm",token="not-the-token",phrase="ERASE")
        self.assertFalse(self.executions)

    def test_personal_data_requires_exact_typed_confirmation(self):
        preview=self.preview()
        for phrase in ("","erase"," ERASE",True):
            with self.subTest(phrase=phrase),self.assertRaises(ValueError):self.confirm(preview,phrase)
        self.assertFalse(self.executions)

    def test_expired_preview_cannot_erase(self):
        preview=self.preview();self.now=311
        with self.assertRaisesRegex(ValueError,"expired"):self.confirm(preview)
        self.assertFalse(self.executions)

    def test_active_work_refuses_preview(self):
        self.busy.return_value=True
        with self.assertRaises(ValueError):self.preview()
        self.assertFalse(self.jobs)

    def test_new_active_work_refuses_confirmation(self):
        preview=self.preview();self.busy.return_value=True
        with self.assertRaises(ValueError):self.confirm(preview)
        self.assertFalse(self.executions)

    def test_changed_selected_config_requires_new_preview(self):
        preview=self.preview(["dictionary"]);self.config["dictionary"]["words"].append("New")
        with self.assertRaisesRegex(ValueError,"changed"):self.confirm(preview)
        self.assertEqual(self.config["dictionary"]["words"],["Keep","New"])

    def test_unrelated_config_does_not_invalidate_preview(self):
        preview=self.preview(["dictionary"]);self.config["licensing"]["device_id"]="still-keep"
        state=self.confirm(preview)
        self.assertEqual(state["phase"],"done")
        self.assertNotIn("dictionary",self.config)
        self.assertEqual(self.config["licensing"]["device_id"],"still-keep")

    def test_changed_file_is_retained_and_new_preview_required(self):
        path=self.root/"history.jsonl";path.write_text("old")
        preview=self.preview();path.write_text("new contents")
        state=self.confirm(preview)
        self.assertEqual(path.read_text(),"new contents")
        self.assertEqual(state["phase"],"choose")
        self.assertTrue(state["error"])

    def test_token_can_only_execute_once(self):
        preview=self.preview();self.confirm(preview)
        with self.assertRaises(ValueError):self.confirm(preview)
        self.assertEqual(len(self.executions),1)

    def test_settings_only_confirmation_has_no_personal_phrase(self):
        preview=self.preview(["settings"])
        self.assertFalse(preview["personal"])
        self.assertEqual(self.confirm(preview,"")["phase"],"done")

    def test_renderer_cannot_supply_paths_or_categories_at_confirm(self):
        preview=self.preview()
        with self.assertRaises(ValueError):
            self.call("confirm",token=preview["token"],phrase="ERASE",selected=["models"])
        with self.assertRaises(ValueError):self.call("preview",selected=["history"],path=str(self.root))
        self.assertFalse(self.executions)

    def test_unknown_or_nonstring_selection_is_refused(self):
        for selected in ([],["bad"],[True],"history"):
            with self.subTest(selected=selected),self.assertRaises(ValueError):self.call("preview",selected=selected)
        self.assertFalse(self.jobs)

    def test_finish_only_after_an_actual_result(self):
        with self.assertRaises(ValueError):self.call("finish")
        self.confirm(self.preview());self.call("finish")
        self.finish.assert_called_once()

    def test_confirmation_reports_partial_failure(self):
        path=self.root/"history.jsonl";path.write_text("keep")
        preview=self.preview()
        with patch.object(Path,"unlink",side_effect=PermissionError):state=self.confirm(preview)
        self.assertTrue(state["error"])
        self.assertEqual(state["result"]["bytes_freed"],0)
        self.assertIn("history.jsonl",state["result"]["failed"])

    def test_startup_failure_leaves_preview_available_to_retry(self):
        self.service.launch=Mock(side_effect=RuntimeError)
        state=self.call("preview",selected=["history"])
        self.assertEqual(state["phase"],"choose")
        self.assertTrue(state["error"])

if __name__=="__main__":unittest.main()

