import json,threading,unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from knight_flow.web_shell.translation_workspace import TranslationWorkspace
from knight_flow.web_shell.translation_adapter import TranslationActions


class TranslationWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.work,self.queue,self.accepted,self.copied=[],[],[],[]
        self.config={'translation':{'source_language':'en','target_language':'es','formality':'natural'},'privacy':{'save_history':False}}
        self.failure=None;self.recording=False
        self.answer={'text':'Hola','source_code':'en','target_code':'es','model':'translategemma:4b','chunks':1}
        self.service=TranslationWorkspace(self.config,self.utility,self.queue.append,launch=self.work.append)
    def utility(self,action,value):
        if action=='translate':
            if self.failure:raise ValueError(self.failure)
            self.job=value
            return dict(self.answer)
        if action=='accept':self.accepted.append(value)
        if action=='copy':self.copied.append(value)
        if action=='speech_start':self.recording=True;self.sink=value
        if action=='speech_cancel':self.recording=False
        if action=='speech_active':return self.recording
        if action in {'check','download_model','install_engine','start_engine'}:return {'success':True,'status':{'ready':True,'model':value['options']['model']},'message':'Ready.'}
    def call(self,operation,**values):return self.service.handle({'operation':operation,**values})
    def edit(self,text='Hello',**options):
        return self.call('edit',revision=self.service.revision,text=text,options={**self.service.options,**options})
    def finish(self):self.work.pop(0)();self.queue.pop(0)()
    def start(self):return self.call('translate',revision=self.service.revision)
    def test_no_history_until_current_result_is_acknowledged_after_ui_delivery(self):
        self.edit();self.start();self.work.pop(0)();self.assertFalse(self.accepted)
        self.queue.pop(0)();self.assertFalse(self.accepted)
        self.call('accept_result',revision=self.service.revision,id=self.service.result['id'])
        self.call('accept_result',revision=self.service.revision,id=self.service.result['id'])
        self.assertEqual(len(self.accepted),1);self.assertEqual(self.accepted[0]['text'],'Hola')
    def test_cancelled_result_never_enters_history(self):
        self.edit();self.start();self.call('cancel');self.finish()
        self.assertFalse(self.accepted);self.assertIsNone(self.service.result)
    def test_cancel_after_completion_before_ui_ack_restores_previous_result(self):
        self.edit();self.start();self.finish()
        self.call('accept_result',revision=self.service.revision,id=self.service.result['id'])
        old=self.service.result
        self.edit('New source');self.start();self.finish();self.call('cancel')
        self.assertIs(self.service.result,old);self.assertEqual(len(self.accepted),1)
    def test_editing_invalidates_a_queued_result(self):
        self.edit();self.start();self.work.pop(0)();self.edit('A newer source')
        self.queue.pop(0)();self.assertFalse(self.accepted);self.assertEqual(self.service.text,'A newer source')
    def test_new_job_cannot_overlap_cancelled_inference(self):
        self.edit();self.start();self.call('cancel')
        with self.assertRaises(ValueError):self.start()
        self.finish();self.start()
    def test_engine_failure_keeps_source_and_previous_result(self):
        self.edit();self.start();self.finish();old=self.service.result.copy()
        self.edit('New source');self.failure='Engine stopped';self.start();self.finish()
        self.assertEqual(self.service.result,old);self.assertEqual(self.service.text,'New source');self.assertTrue(self.service.error)
    def test_copy_uses_exact_owned_result_and_rejects_forged_id(self):
        self.answer['text']='  línea\n美和\n';self.edit();self.start();self.finish()
        self.call('copy',id=self.service.result['id']);self.assertEqual(self.copied,[self.answer['text']])
        with self.assertRaises(ValueError):self.call('copy',id='not-current')
    def test_draft_is_retained_across_open_and_close(self):
        self.edit('  draft\n');self.service.close();opened=self.call('open')
        self.assertEqual(self.call('read',part='source',revision=opened['revision'])['text'],'  draft\n')
    def test_clear_requires_confirmation_and_cannot_accept_old_result(self):
        self.edit();self.start()
        with self.assertRaises(ValueError):self.call('clear',revision=self.service.revision)
        self.call('clear',revision=self.service.revision,confirmed=True);self.finish()
        self.assertFalse(self.accepted);self.assertEqual(self.service.text,'')
    def test_stale_revision_cannot_replace_draft(self):
        self.edit('Current')
        with self.assertRaises(ValueError):self.call('edit',revision=0,text='stale',options=self.service.options)
        self.assertEqual(self.service.text,'Current')
    def test_invalid_source_limits_are_rejected_without_changes(self):
        for text in ('a'*64001,'a\x00b',[],None):
            with self.subTest(text=str(type(text))),self.assertRaises(ValueError):self.edit(text)
        self.assertEqual(self.service.revision,0)
    def test_large_unicode_text_and_results_are_read_in_bounded_messages(self):
        original='美和🙂\n'*16000;self.edit(original);self.assertEqual(len(original),64000)
        offset=0;parts=[]
        while offset is not None:
            part=self.call('read',part='source',revision=self.service.revision,offset=offset);parts.append(part['text']);offset=part['next']
            self.assertLess(len(json.dumps(part)),1048576)
        self.assertEqual(''.join(parts),original)
    def test_options_are_typed_and_unknown_languages_do_not_become_english(self):
        for options in ({'source':'unknown'},{'target':'auto'},{'formality':[]},{'preserve_formatting':'yes'},{'model':'unknown'}):
            with self.subTest(options=options),self.assertRaises(ValueError):self.edit(**options)
    def test_worker_receives_snapshot_without_changing_global_defaults(self):
        self.edit(formality='formal');self.start();self.config['translation']['target_language']='de';self.finish()
        self.assertEqual(self.job['config']['translation']['target_language'],'es');self.assertEqual(self.config['translation']['formality'],'natural')
    def test_model_download_needs_explicit_confirmation(self):
        with self.assertRaises(ValueError):self.call('download_model',revision=0)
        self.call('download_model',revision=0,confirmed=True);self.finish();self.assertTrue(self.service.ready['ready'])
    def test_edit_during_model_download_keeps_model_readiness(self):
        self.call('download_model',revision=0,confirmed=True);self.edit('draft during download');self.finish()
        self.assertTrue(self.service.ready['ready']);self.assertEqual(self.service.text,'draft during download')
    def test_owned_speech_appends_without_losing_existing_passage(self):
        self.edit('Existing');self.call('speech_start',revision=self.service.revision);self.recording=False;self.sink('Spoken')
        self.assertIsNone(self.service.job);self.call('status')
        self.assertEqual(self.service.text,'Existing\nSpoken');self.assertEqual(self.service.job['kind'],'translate')
    def test_speech_waits_for_the_dictation_delivery_flight_to_release(self):
        busy=True;original=self.service.utility
        self.service.utility=lambda action,value: busy if action=='capture_busy' else original(action,value)
        self.call('speech_start',revision=0);self.recording=False;self.sink('Spoken');self.call('status')
        self.assertIsNone(self.service.job);self.assertTrue(self.service.auto_start)
        busy=False;self.call('status');self.assertEqual(self.service.job['kind'],'translate')
    def test_leaving_capture_cancels_and_ignores_delayed_speech(self):
        self.edit('Existing');self.call('speech_start',revision=self.service.revision);self.service.close();self.sink('late')
        self.assertFalse(self.recording);self.assertEqual(self.service.text,'Existing');self.assertIsNone(self.service.job)
    def test_failed_history_does_not_lose_copyable_result(self):
        original=self.service.utility
        def utility(action,value):
            if action=='accept':raise OSError('full disk')
            return original(action,value)
        self.service.utility=utility;self.edit();self.start();self.finish()
        with self.assertRaises(OSError):self.call('accept_result',revision=self.service.revision,id=self.service.result['id'])
        self.assertEqual(self.service.result['text'],'Hola');self.assertFalse(self.service.result['accepted'])
    def test_editor_change_before_ui_acknowledgement_blocks_old_history(self):
        self.edit();self.start();self.finish();old=self.service.result['id'];self.edit('New text')
        with self.assertRaises(ValueError):self.call('accept_result',revision=self.service.revision,id=old)
        self.assertFalse(self.accepted)
    def test_close_during_translation_prevents_late_acceptance(self):
        self.edit();self.start();self.service.close();self.finish();self.assertFalse(self.accepted)


class TranslationMicrophoneOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.app=SimpleNamespace(config={},overlay=SimpleNamespace(onboarding_test_sink=None),lock=threading.RLock(),session_token=None,_guided_delivery_token=None,add_history=Mock(),last_transcript='Newer dictation')
        self.app.start_push_to_talk=lambda:setattr(self.app,'session_token',object())
        self.app.stop_session=Mock()
        self.events=[]
        def cancel():self.events.append(self.app.overlay.onboarding_test_sink);self.app.session_token=None
        self.app.cancel=Mock(side_effect=cancel)
        self.actions=TranslationActions(self.app,Mock(),lambda:False)
        self.registry=patch('knight_flow.mic_registry.microphone_registry',return_value=SimpleNamespace(is_active=lambda:False));self.registry.start();self.addCleanup(self.registry.stop)
    def test_capture_cancel_happens_before_sink_release(self):
        self.actions('speech_start',Mock());sink=self.app.overlay.onboarding_test_sink;self.actions('speech_cancel',None)
        self.assertEqual(self.events,[sink]);self.assertIsNone(self.app.overlay.onboarding_test_sink)
    def test_cancel_does_not_stop_a_newer_capture_or_clear_another_sink(self):
        self.actions('speech_start',Mock());new_sink=Mock();self.app.overlay.onboarding_test_sink=new_sink;self.app.session_token=object()
        self.actions('speech_cancel',None);self.app.cancel.assert_not_called();self.assertIs(self.app.overlay.onboarding_test_sink,new_sink)
    def test_failed_start_clears_only_owned_sink(self):
        self.app.start_push_to_talk=lambda:None
        with self.assertRaises(ValueError):self.actions('speech_start',Mock())
        self.assertIsNone(self.app.overlay.onboarding_test_sink)
    def test_existing_guided_surface_is_not_overwritten(self):
        sink=Mock();self.app.overlay.onboarding_test_sink=sink
        with self.assertRaises(ValueError):self.actions('speech_start',Mock())
        self.assertIs(self.app.overlay.onboarding_test_sink,sink)
    def test_delivered_text_releases_sink_and_calls_current_surface_once(self):
        receive=Mock();self.actions('speech_start',receive);sink=self.app.overlay.onboarding_test_sink;sink('text');sink('late')
        receive.assert_called_once_with('text');self.assertIsNone(self.app.overlay.onboarding_test_sink)
    def test_accept_does_not_replace_newer_paste_last(self):
        self.actions('accept',{'text':'Hola','original':'Hello','source_code':'en','target_code':'es','model':'local'})
        self.assertEqual(self.app.last_transcript,'Newer dictation');self.app.add_history.assert_called_once()
    def test_history_opt_out_is_honoured(self):
        self.app.config={'privacy':{'save_history':False}}
        self.actions('accept',{'text':'Hola','original':'Hello','source_code':'en','target_code':'es','model':'local'})
        self.app.add_history.assert_not_called()

if __name__=='__main__':unittest.main()
