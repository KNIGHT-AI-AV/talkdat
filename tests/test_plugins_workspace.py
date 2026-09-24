import os,tempfile,time,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from knight_flow import plugins
from knight_flow.web_shell.plugins_workspace import PluginsWorkspace

class PluginsWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        env=patch.dict(os.environ,{'TALK_DAT_HOME':self.temp.name});env.start();self.addCleanup(env.stop)
        plugins.request_reload(None).wait(4);self.addCleanup(lambda:plugins.request_reload(None).wait(4))
        self.config={'plugins':{'enabled':True}};self.busy=Mock(return_value=False);self.open=Mock()
        self.service=PluginsWorkspace(self.config,self.busy,self.open)
    def test_status_never_loads_or_executes_a_plugin(self):
        marker=Path(self.temp.name)/'executed'
        (plugins.plugins_dir()/'test.py').write_text('from pathlib import Path\nPath('+repr(str(marker))+').touch()\n')
        self.assertEqual(self.service.handle({'command':'status'})['phase'],'unloaded');self.assertFalse(marker.exists())
    def test_only_explicit_folder_action_opens_a_folder(self):
        self.service.handle({'command':'status'});self.open.assert_not_called()
        self.service.handle({'command':'folder'});self.open.assert_called_once_with(plugins.plugins_dir())
    def test_reload_is_refused_during_capture(self):
        self.busy.return_value=True
        with self.assertRaisesRegex(ValueError,'recording'):self.service.handle({'command':'reload'})
    def test_disabled_plugins_cannot_be_loaded_from_the_view(self):
        self.config['plugins']['enabled']=False
        with self.assertRaisesRegex(ValueError,'Enable'):self.service.handle({'command':'reload'})
    def test_unknown_or_extra_payload_is_refused(self):
        for payload in ({'command':'load_all'},{'command':'status','path':'private.py'},[]):
            with self.assertRaises(ValueError):self.service.handle(payload)
    def test_reload_returns_before_slow_import_then_shows_failure(self):
        (plugins.plugins_dir()/'slow.py').write_text('import time\ntime.sleep(20)\n')
        started=time.perf_counter();state=self.service.handle({'command':'reload'})
        self.assertLess(time.perf_counter()-started,.15);self.assertEqual(state['phase'],'loading')
        self.assertTrue(plugins._reload_done.wait(3))
        self.assertEqual(self.service.handle({'command':'status'})['phase'],'warning')
    def test_disabling_during_reload_retires_the_new_hosts_too(self):
        marker=Path(self.temp.name)/'started'
        (plugins.plugins_dir()/'slow.py').write_text('from pathlib import Path\nimport time\nPath('+repr(str(marker))+').touch()\ntime.sleep(.2)\ndef register(api):api.add_text_filter(lambda t,c:t)\n')
        done=plugins.request_reload(self.config);deadline=time.monotonic()+2
        while not marker.exists() and time.monotonic()<deadline:time.sleep(.01)
        self.assertTrue(marker.exists());latest=plugins.request_reload(None)
        self.assertIs(done,latest);self.assertTrue(done.wait(3));self.assertEqual(plugins._hosts,[])
    def test_empty_shutdown_does_not_schedule_unnecessary_work(self):
        with patch('knight_flow.plugins.threading.Thread') as worker:
            self.assertTrue(plugins.request_reload(None).is_set());worker.assert_not_called()
