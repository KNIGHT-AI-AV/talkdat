import unittest
from unittest.mock import Mock
from tests import test_web_shell_app


class MicrophoneWorkspaceRoutesTests(unittest.TestCase):
    def test_mic_doctor_opens_the_shared_page(self):
        app,shell=test_web_shell_app.AppShellTests().make_shell()
        self.assertEqual(shell.backend.handle('action',{'name':'mic_doctor'}),{'page':'mic-doctor'})
        app.overlay.open_mic_doctor.assert_not_called()
    def test_speech_check_opens_the_shared_page(self):
        app,shell=test_web_shell_app.AppShellTests().make_shell()
        self.assertEqual(shell.backend.handle('action',{'name':'race'}),{'page':'speech-check'})
        app.overlay.open_taste_race.assert_not_called()


if __name__=='__main__':unittest.main()
