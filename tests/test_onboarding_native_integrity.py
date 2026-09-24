"""Real setup controls on the isolated Windows desktop, with synthetic devices."""
import copy,ctypes,json,os,sys,tempfile,time,tkinter as tk,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from knight_flow import main_thread
from knight_flow.app import TalkDatApp
from knight_flow.config import config_path
from knight_flow.onboarding import ONBOARDING_STEPS
from knight_flow.ui import onboarding as ui
from scripts.capture_onboarding_gallery import CaptureHost


@unittest.skipUnless(sys.platform=='win32','Isolated Windows setup acceptance')
class NativeSetupIntegrityTests(unittest.TestCase):
    def test_route_privacy_selected_input_and_failed_finish_use_real_controls(self):
        from ctypes import wintypes
        user=ctypes.windll.user32;user.GetThreadDesktop.restype=wintypes.HANDLE
        desktop=user.GetThreadDesktop(ctypes.windll.kernel32.GetCurrentThreadId())
        name=ctypes.create_unicode_buffer(256);needed=wintypes.DWORD()
        self.assertTrue(user.GetUserObjectInformationW(desktop,2,name,ctypes.sizeof(name),ctypes.byref(needed)))
        self.assertTrue(name.value.startswith('talkdat-tests-'),'Setup probe must use the isolated desktop')
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'TALK_DAT_HOME':folder}),patch.object(ui,'list_input_devices',return_value=['Synthetic connected microphone']),patch('knight_flow.net_fence.set_local_only'):
            root=tk.Tk();root.withdraw();main_thread.bind(root)
            try:
                host=CaptureHost(root,'Flow Dark');host.config['audio']['input_device']='Synthetic disconnected microphone'
                app=object.__new__(TalkDatApp);app.config=host.config;app.overlay=host;app.save_settings=Mock()
                host.refresh_route_paint=Mock();host.callbacks['onboarding_save']=app.save_onboarding_settings
                wizard=ui.OnboardingWizard(host)
                def settle(predicate=lambda:True):
                    deadline=time.monotonic()+4
                    while time.monotonic()<deadline:
                        root.update()
                        if predicate():return
                        time.sleep(.01)
                    self.fail('Setup did not settle')
                def page(name):wizard.render_step(next(i for i,step in enumerate(ONBOARDING_STEPS) if step.id==name));settle()
                page('voice');wizard.route_var.set('byok');wizard.next_button.invoke()
                self.assertIn('Local-only',wizard.status_var.get());self.assertEqual(ONBOARDING_STEPS[wizard.step_index].id,'voice')
                wizard.route_var.set('local');wizard.next_button.invoke()
                self.assertEqual(json.loads(config_path().read_text(encoding='utf-8'))['stt']['route_mode'],'local')
                settle(lambda:'unavailable' in wizard.mic_status_var.get())
                self.assertEqual(wizard.audio_device_var.get(),'Synthetic disconnected microphone')
                with patch.object(ui,'resolve_input_device',return_value=None),patch.object(ui,'open_raw_input_stream') as opened:
                    wizard.mic_test_button.invoke();settle(lambda:not wizard.meter_state.get('opening'))
                    opened.assert_not_called();self.assertIn('unavailable',wizard.mic_status_var.get())
                page('test');wizard._receive_test_result('');settle()
                self.assertFalse(wizard.dictation_tested);self.assertNotIn('Success',wizard.practice_status_var.get())
                before=copy.deepcopy(host.config)
                with patch('knight_flow.web_shell.shell_persistence.save_settings_config',side_effect=OSError('synthetic disk full')):
                    wizard.next_button.invoke();settle()
                self.assertTrue(wizard.window.winfo_exists());self.assertEqual(host.config,before)
                self.assertIn('could not be saved',wizard.status_var.get())
                wizard.next_button.invoke();settle()
                self.assertFalse(wizard.window.winfo_exists())
                saved=json.loads(config_path().read_text(encoding='utf-8'))
                self.assertIs(saved['onboarding']['completed'],True)
                self.assertIs(saved['onboarding']['dictation_tested'],False)
                self.assertEqual(saved['audio']['input_device'],'Synthetic disconnected microphone')
                print('Native setup privacy, selected-input refusal, empty-result copy and failed-save retry passed on',name.value)
            finally:
                main_thread.stop(root);root.destroy()


if __name__=='__main__':unittest.main()
