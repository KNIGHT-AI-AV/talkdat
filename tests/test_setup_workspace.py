import copy,json,unittest
from unittest.mock import Mock
from knight_flow.config import DEFAULT_CONFIG
from knight_flow.web_shell.setup_workspace import SetupWorkspace


class SetupWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.config=copy.deepcopy(DEFAULT_CONFIG);self.saved=[];self.calls=[];self.callback=None
        self.mic=Mock();self.mic.snapshot.return_value={'check':{'phase':'idle','mode':'mic'},'devices':{'status':'ready','devices':[],'message':''},'selected':''}
        def save(value):self.saved.append(copy.deepcopy(value));return {'saved':True,'runtime_refreshed':True}
        self.service=SetupWorkspace(self.config,save,self.action,self.mic)

    def action(self,name,value):
        self.calls.append((name,value))
        if name=='permissions':return []
        if name=='speech_start':self.callback=value;self.active=True
        if name=='speech_cancel':self.active=False
        if name=='speech_status':return {'active':self.active,'processing':False}
        if name=='rehearsal_status':return {'active':True,'matched':False}

    def call(self,operation,**values):return self.service.handle({'operation':operation,**values})
    def change(self,operation,**values):return self.call(operation,revision=self.service.revision(),**values)

    def test_open_does_not_record_download_or_write(self):
        self.call('state');self.assertEqual([x[0] for x in self.calls],['permissions']);self.assertFalse(self.saved);self.mic.handle.assert_not_called()
    def test_snapshot_has_no_credentials(self):
        self.config['stt']['providers']['deepgram']['api_key']='SYNTHETIC_SECRET'
        self.assertNotIn('SYNTHETIC_SECRET',json.dumps(self.call('state')))
    def test_malformed_saved_progress_is_tolerated(self):
        for value in (None,[],True,'bad'):
            self.config['onboarding']=value
            service=SetupWorkspace(self.config,self.service.save,self.action,self.mic)
            self.assertEqual(service.snapshot()['chapter'],'welcome');self.assertFalse(service.snapshot()['completed'])
    def test_old_resume_step_maps_to_short_chapter(self):
        self.config['onboarding']={'resume_step_id':'test','resume_flags':{'dictation_tested':'true'}}
        service=SetupWorkspace(self.config,self.service.save,self.action,self.mic)
        self.assertEqual(service.snapshot()['chapter'],'practice');self.assertFalse(service.flags['dictation_tested'])
    def test_stale_revision_cannot_overwrite_other_settings(self):
        revision=self.service.revision();self.config['ui']['theme']='light'
        with self.assertRaisesRegex(ValueError,'changed elsewhere'):self.call('route',revision=revision,value='local')
        self.assertFalse(self.saved)
    def test_failed_save_keeps_previous_config_and_chapter(self):
        original=copy.deepcopy(self.config);self.service.save=Mock(side_effect=OSError('private detail'))
        with self.assertRaisesRegex(ValueError,'previous settings'):self.change('chapter',value='voice')
        self.assertEqual(self.config,original);self.assertEqual(self.service.chapter,'welcome')
    def test_non_receipt_is_not_save_success(self):
        self.service.save=Mock(return_value={'saved':'true'})
        with self.assertRaises(ValueError):self.change('chapter',value='voice')
        self.assertEqual(self.service.chapter,'welcome')
    def test_runtime_refresh_failure_keeps_saved_state(self):
        self.service.save=Mock(return_value={'saved':True,'runtime_refreshed':False})
        result=self.change('chapter',value='voice')
        self.assertEqual(result['chapter'],'voice');self.assertIn('Restart',result['message'])
    def test_local_route_and_provider_change_together(self):
        self.config['stt'].update(provider='deepgram',route_mode='byok')
        self.change('route',value='local')
        self.assertEqual(self.config['stt']['route_mode'],'local');self.assertEqual(self.config['stt']['provider'],'local')
        self.assertEqual(self.config['stt']['cloud_provider'],'deepgram')
    def test_byok_cannot_disable_local_only(self):
        self.config.setdefault('privacy',{})['local_only']=True
        with self.assertRaisesRegex(ValueError,'Local-only'):self.change('route',value='byok')
        self.assertTrue(self.config['privacy']['local_only']);self.assertFalse(self.saved)
    def test_byok_needs_configured_provider_key(self):
        self.config.setdefault('privacy',{})['local_only']=False;self.config['stt']['cloud_provider']='deepgram'
        self.config['stt']['providers']['deepgram']['api_key']=''
        with self.assertRaisesRegex(ValueError,'provider key'):self.change('route',value='byok')
        self.config['stt']['providers']['deepgram']['api_key']='fixture'
        self.change('route',value='byok');self.assertEqual(self.config['stt']['provider'],'deepgram')
    def test_unknown_route_and_extra_fields_are_rejected(self):
        for payload in ({'operation':'state','extra':True},{'operation':'route','revision':self.service.revision(),'value':'managed'}, {'operation':'finish','revision':self.service.revision(),'accepted':'true'}):
            with self.assertRaises(ValueError):self.service.handle(payload)
        self.assertFalse(self.saved)
    def test_preset_uses_existing_writing_controls(self):
        self.change('preset',value='fast');self.assertEqual(self.config['cleanup']['format_mode'],'off')
    def test_empty_practice_is_not_completed_proof(self):
        self.call('practice');self.callback('  ')
        result=self.call('state');self.assertEqual(result['practice']['phase'],'empty');self.assertFalse(result['flags']['dictation_tested'])
    def test_nonempty_practice_is_earned_and_copy_is_explicit(self):
        self.call('practice');self.callback('A real result 日本語')
        self.assertTrue(self.call('state')['flags']['dictation_tested']);self.assertFalse(any(x[0]=='copy' for x in self.calls))
        self.call('copy');self.assertIn(('copy','A real result 日本語'),self.calls)
    def test_cancel_discards_delayed_result(self):
        self.call('practice');callback=self.callback;self.call('cancel');callback('Late words')
        self.assertEqual(self.call('state')['practice']['text'],'');self.assertFalse(self.service.flags['dictation_tested'])
    def test_redo_discards_previous_flight_callback(self):
        self.call('practice');old=self.callback;self.call('practice');old('Wrong flight');self.callback('New words')
        self.assertEqual(self.call('state')['practice']['text'],'New words')
    def test_finish_requires_click_and_does_not_invent_checks(self):
        result=self.change('finish',accepted=True)
        self.assertTrue(result['completed']);self.assertFalse(any(result['flags'].values()))
        self.assertTrue(self.config['onboarding']['terms_version']);self.assertNotIn('resume_flags',self.config['onboarding'])
    def test_failed_finish_does_not_record_terms(self):
        self.service.save=Mock(side_effect=OSError())
        with self.assertRaises(ValueError):self.change('finish',accepted=True)
        self.assertFalse(self.call('state')['completed']);self.assertNotIn('terms_accepted_at',self.config['onboarding'])
    def test_microphone_proof_requires_completed_level_report(self):
        self.mic.snapshot.return_value['check'].update(phase='ready',mode='speech',report={})
        self.assertFalse(self.call('state')['flags']['microphone_tested'])
        self.mic.snapshot.return_value['check']['mode']='mic'
        self.assertTrue(self.call('state')['flags']['microphone_tested'])
    def test_microphone_cannot_be_switched_to_speech_mode(self):
        with self.assertRaises(ValueError):self.call('mic',request={'operation':'open','mode':'speech'})
        self.mic.handle.assert_not_called()
    def test_close_stops_owned_activity_and_late_result(self):
        self.call('practice');callback=self.callback;self.service.close();callback('Late')
        self.assertEqual(self.service.practice['text'],'');self.mic.handle.assert_called_with({'operation':'stop'})


if __name__=='__main__':unittest.main()
