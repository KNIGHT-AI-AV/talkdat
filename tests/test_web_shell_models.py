import copy
import unittest
from unittest.mock import Mock, patch
from knight_flow.config import DEFAULT_CONFIG
from knight_flow.local_stt import LocalModel
from knight_flow.web_shell.shell_models import ModelManager


class WebModelManagerTests(unittest.TestCase):
    def setUp(self):
        self.model = LocalModel('synthetic', 'Synthetic model', 'onnx_asr', 'synthetic', 12, 'English')
        self.config = copy.deepcopy(DEFAULT_CONFIG)
        self.worker = []
        self.manager = ModelManager(self.config, lambda: False, start_worker=self.worker.append)

    def test_unknown_model_never_reaches_disk_or_network(self):
        with patch('knight_flow.web_shell.shell_models.available_local_models', return_value=(self.model,)), patch('knight_flow.web_shell.shell_models.delete_model') as delete:
            with self.assertRaises(ValueError):self.manager.request('delete', '../outside')
            self.assertEqual(self.worker, [])
            delete.assert_not_called()

    def test_busy_capture_refuses_model_removal(self):
        self.manager.capture_busy = lambda: True
        with patch('knight_flow.web_shell.shell_models.available_local_models', return_value=(self.model,)), patch('knight_flow.web_shell.shell_models.delete_model') as delete:
            with self.assertRaises(ValueError):self.manager.request('delete','synthetic')
            delete.assert_not_called()

    def test_download_is_off_the_ui_thread_and_cannot_start_twice(self):
        with patch('knight_flow.web_shell.shell_models.available_local_models', return_value=(self.model,)), patch('knight_flow.web_shell.shell_models.download_model') as download:
            self.manager.request('download', 'synthetic')
            self.manager.request('download', 'synthetic')
            self.assertEqual(len(self.worker), 1)
            download.assert_not_called()
            self.worker[0]()
            download.assert_called_once()
            self.assertEqual(self.manager.status['synthetic']['state'], 'ready')

    def test_failed_download_reports_failure_and_allows_retry(self):
        with patch('knight_flow.web_shell.shell_models.available_local_models', return_value=(self.model,)), patch('knight_flow.web_shell.shell_models.download_model', side_effect=OSError('synthetic')):
            self.manager.request('download', 'synthetic');self.worker[0]()
            self.assertEqual(self.manager.status['synthetic']['state'], 'error')
            self.manager.request('download', 'synthetic')
            self.assertEqual(len(self.worker),2)


if __name__ == '__main__':unittest.main()
