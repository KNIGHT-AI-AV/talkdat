import queue,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from knight_flow.web_shell.workspace_adapter import Workspaces

class HistoryExportAdapterTests(unittest.TestCase):
    def setUp(self):
        self.app=SimpleNamespace(config={},_cross_thread_calls=queue.Queue())
        self.service=Workspaces(self.app,Mock(),lambda:False);self.service.open_path=Mock()
    def test_history_protocol_schedules_export_instead_of_working_on_ui_queue(self):
        with patch('threading.Thread') as worker:
            result=self.service.handle({'area':'history','operation':'export','command':'start','format':'txt'})
        self.assertTrue(result['active']);worker.return_value.start.assert_called_once();self.service.open_path.assert_not_called()
    def test_legacy_export_command_uses_the_same_owned_job_and_no_auto_open(self):
        with patch('threading.Thread') as worker,patch('knight_flow.history.export_history',return_value=Path('fixture.txt')) as exporter:
            result=self.service.history_utility('export_txt','')
        self.assertTrue(result.get('active'));worker.return_value.start.assert_called_once()
        exporter.assert_not_called();self.service.open_path.assert_not_called()
    def test_clearing_text_cannot_race_the_history_export_read(self):
        with patch('threading.Thread'):
            self.service.handle({'area':'history','operation':'export','command':'start','format':'md'})
        with patch('knight_flow.history.JsonlHistoryStore.clear') as clear:
            with self.assertRaisesRegex(ValueError,'export'):self.service.history_utility('clear_text',True)
            clear.assert_not_called()

if __name__=='__main__':unittest.main()
