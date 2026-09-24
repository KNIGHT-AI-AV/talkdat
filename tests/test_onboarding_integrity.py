import copy,sys,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch

from knight_flow.config import DEFAULT_CONFIG
from knight_flow import onboarding
from knight_flow.ui import onboarding as ui
from knight_flow.stt_registry import resolve_route,model_label,selected_model_id
from tests import test_onboarding_redesign_safety as fixtures


class OnboardingIntegrityTests(unittest.TestCase):
    def wizard(self,route='local'):
        w=object.__new__(ui.OnboardingWizard);w.config=copy.deepcopy(DEFAULT_CONFIG)
        w.config['privacy']['local_only']=False
        for name,value in [('route_var',route),('language_var','en-US'),('key_var','synthetic-test-key'),('model_var',model_label('deepgram',selected_model_id(w.config,'deepgram'))),('writing_var','fast'),('status_var',''),('practice_status_var','')]:setattr(w,name,fixtures._Variable(value))
        w.provider_holder={'id':'deepgram'};w.host=SimpleNamespace(callbacks={'save_settings':Mock()},apply_runtime_config=Mock(),set_state=Mock())
        w.window=SimpleNamespace(after=Mock(),destroy=Mock());w.destroyed=False
        w.microphone_tested=w.hotkey_rehearsed=w.dictation_tested=False;w.access_choice='private'
        w.step_index=next(i for i,step in enumerate(onboarding.ONBOARDING_STEPS) if step.id=='test')
        w._set_practice_text=Mock();w._offer_finish_choice=Mock();w._store_resume_receipt=Mock()
        return w

    def test_byok_choice_reaches_the_actual_speech_resolver(self):
        w=self.wizard('byok')
        with patch('knight_flow.net_fence.set_local_only'):
            self.assertTrue(w._commit_voice_route())
        self.assertEqual(resolve_route(w.config),'deepgram')
        self.assertEqual(w.config['stt']['route_mode'],'byok')

    def test_local_choice_updates_the_route_and_fence(self):
        w=self.wizard();w.config['stt'].update(route_mode='byok',provider='deepgram')
        with patch('knight_flow.net_fence.set_local_only') as fence:
            self.assertTrue(w._commit_voice_route())
        self.assertEqual(w.config['stt']['route_mode'],'local');fence.assert_called_with(True)

    def test_byok_does_not_claim_to_override_local_only_privacy(self):
        w=self.wizard('byok');w.config['privacy']['local_only']=True;original=copy.deepcopy(w.config)
        self.assertFalse(w._commit_voice_route());self.assertEqual(w.config,original)
        self.assertIn('local-only',w.status_var.get().lower())

    def test_retired_or_invalid_route_is_not_interpreted_as_byok(self):
        w=self.wizard('managed');original=copy.deepcopy(w.config)
        self.assertFalse(w._commit_voice_route());self.assertEqual(w.config,original)

    def test_failed_route_save_restores_the_previous_settings(self):
        w=self.wizard('byok');original=copy.deepcopy(w.config)
        w.host.callbacks['save_settings'].side_effect=OSError('synthetic disk failure')
        with patch('knight_flow.net_fence.set_local_only'):
            self.assertFalse(w._commit_voice_route())
        self.assertEqual(w.config,original);self.assertTrue(w.status_var.get())

    def test_failed_finish_does_not_mark_setup_complete_or_close(self):
        w=self.wizard();w._commit_voice_route=Mock(return_value=True);original=copy.deepcopy(w.config)
        w.host.callbacks['save_settings'].side_effect=OSError('synthetic disk failure')
        w.finish()
        self.assertEqual(w.config,original);w.window.destroy.assert_not_called();w.host.set_state.assert_not_called()
        self.assertTrue(w.status_var.get())

    def test_an_unknown_finishing_check_cannot_claim_success(self):
        w=self.wizard()
        with patch('knight_flow.llm.finishing_status',side_effect=RuntimeError('unavailable')):
            self.assertIs(w._finishing_verdict()['ok'],False)

    def test_empty_practice_result_does_not_say_success(self):
        w=self.wizard();w.window.after.side_effect=lambda delay,callback:callback()
        w._receive_test_result('   ')
        self.assertFalse(w.dictation_tested);self.assertNotIn('Success',w.practice_status_var.get())
        w._offer_finish_choice.assert_not_called()

    def test_queued_practice_result_cannot_paint_a_later_page(self):
        w=self.wizard();pending=[];w.window.after.side_effect=lambda delay,callback:pending.append(callback)
        w._receive_test_result('Synthetic old result')
        w.step_index=next(i for i,step in enumerate(onboarding.ONBOARDING_STEPS) if step.id=='writing')
        pending.pop()()
        w._set_practice_text.assert_not_called();self.assertFalse(w.dictation_tested)

    def test_refresh_keeps_a_disconnected_selected_microphone(self):
        w=fixtures.OnboardingMicrophoneRegistryTests._meter_wizard([],fixtures._ImmediateWindow())
        w._microphone_query_generation=0;w.mic_refresh_button=None
        with patch.object(ui,'list_input_devices',return_value=['Other microphone']),patch.object(ui.threading,'Thread',fixtures._ImmediateThread),patch.object(ui.main_thread,'post',side_effect=lambda callback:callback()):
            w._refresh_microphones(initial=True)
        self.assertEqual(w.audio_device_var.get(),'Studio microphone')
        self.assertIn('unavailable',w.mic_status_var.get().lower())

    def test_missing_explicit_microphone_is_not_opened_as_system_default(self):
        events=[];w=fixtures.OnboardingMicrophoneRegistryTests._meter_wizard(events,fixtures._ImmediateWindow())
        registry=fixtures._Registry(events)
        with patch.object(ui,'resolve_input_device',return_value=None),patch.object(ui,'open_raw_input_stream') as opened,patch.object(ui,'microphone_registry',return_value=registry),patch.object(ui.threading,'Thread',fixtures._ImmediateThread),patch.object(ui.main_thread,'post',side_effect=lambda callback:callback()):
            w._start_meter()
        opened.assert_not_called();self.assertIn('unavailable',w.mic_status_var.get().lower())

    def test_microphone_driver_cannot_fall_back_to_a_different_input(self):
        events=[];w=fixtures.OnboardingMicrophoneRegistryTests._meter_wizard(events,fixtures._ImmediateWindow())
        stream=fixtures._Stream(events);registry=fixtures._Registry(events)
        with patch.object(ui,'resolve_input_device',return_value=4),patch.object(ui,'open_raw_input_stream',return_value=(stream,16000,1,4)) as opened,patch.object(ui,'microphone_registry',return_value=registry),patch.object(ui.threading,'Thread',fixtures._ImmediateThread),patch.object(ui.main_thread,'post',side_effect=lambda callback:callback()):
            w._start_meter();w._stop_meter()
        self.assertIs(opened.call_args.kwargs.get('allow_device_fallback'),False)

    def test_resume_receipt_does_not_turn_false_text_into_earned_proof(self):
        w=fixtures._bare_wizard({'onboarding':{'resume_step_id':'test','resume_flags':{'microphone_tested':'false','hotkey_rehearsed':1,'dictation_tested':'no'}}})
        w._resume_step_index()
        self.assertFalse(w.microphone_tested);self.assertFalse(w.hotkey_rehearsed);self.assertFalse(w.dictation_tested)

    def test_malformed_completion_state_does_not_crash_startup(self):
        for state in [None,[],False,'damaged']:
            with self.subTest(state=state):self.assertFalse(onboarding.onboarding_is_complete({'onboarding':state}))

    def test_false_text_is_not_a_completed_setup(self):
        self.assertFalse(onboarding.onboarding_is_complete({'onboarding':{'completed':'false','version':onboarding.ONBOARDING_VERSION}}))

    def test_polling_a_completed_test_never_probes_the_formatter_on_the_ui_thread(self):
        w=self.wizard();w.dictation_tested=True;w.test_button=Mock();w._draw_test_visual=Mock()
        w._status_snapshot=Mock(return_value={'session_active':False,'overlay_state':'idle'})
        w._finishing_verdict=Mock(return_value={'ok':True})
        w._poll_test()
        w._finishing_verdict.assert_not_called()
        self.assertNotIn('formatting all completed',w.practice_status_var.get())

    def test_editing_a_provider_keeps_the_key_out_of_live_settings_until_save(self):
        w=self.wizard('byok');original=copy.deepcopy(w.config)
        w._remember_provider('deepgram')
        self.assertEqual(w.config,original)

    def test_failed_microphone_change_keeps_the_previous_input(self):
        w=self.wizard();w.config['audio']['input_device']='Previous microphone'
        w.audio_device_var=fixtures._Variable('New microphone');w.mic_status_var=fixtures._Variable()
        w.meter_state={'stream':None,'opening':False};w._restart_meter=Mock()
        w.host.callbacks['save_settings'].side_effect=OSError('synthetic disk failure')
        w._microphone_changed()
        self.assertEqual(w.config['audio']['input_device'],'Previous microphone')
        self.assertEqual(w.audio_device_var.get(),'Previous microphone');w._restart_meter.assert_not_called()

    def test_failed_resume_save_keeps_the_previous_receipt(self):
        w=self.wizard();original=copy.deepcopy(w.config)
        w.host.callbacks['save_settings'].side_effect=OSError('synthetic disk failure')
        ui.OnboardingWizard._store_resume_receipt(w)
        self.assertEqual(w.config,original);self.assertIn('could not be saved',w.status_var.get())


if __name__=='__main__':unittest.main()
