import copy
from pathlib import Path
import queue
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from knight_flow.web_shell.ramble_workspace import RambleWorkspace
from knight_flow.web_shell.ramble_adapter import RambleActions


class RambleWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.calls, self.jobs, self.callbacks = [], [], []
        self.recording = False
        self.failure = ''
        self.config = {'privacy':{'save_history':False},'cleanup':{'tone':'formal'}}
        self.workspace = RambleWorkspace(self.config,self.utility,self.callbacks.append,self.jobs.append)

    def utility(self, action, value):
        self.calls.append((action,value))
        if action == 'writing_ready':return True
        if action == 'speech_start':self.sink=value;self.recording=True
        if action == 'speech_active':return self.recording
        if action == 'speech_cancel':self.recording=False
        if action == 'finish':
            if self.failure:raise OSError(self.failure)
            return 'Finished: '+value['text']
        if action == 'export':
            if self.failure:raise OSError(self.failure)
            return Path('/private-fixture/document.pdf')

    def call(self, operation, **extra):
        return self.workspace.handle({'operation':operation,**extra})

    def edit(self, text):
        token=self.call('begin_edit',revision=self.workspace.revision)['token']
        offset=0
        for start in range(0,len(text),16000):
            offset=self.call('append_edit',token=token,offset=offset,text=text[start:start+16000])['offset']
        return self.call('commit_edit',token=token)

    def complete(self):
        self.jobs.pop(0)()
        self.callbacks.pop(0)()

    def test_open_never_writes_history_files_or_starts_a_model(self):
        state=self.call('open')
        self.assertEqual(len(state['styles']),10)
        self.assertEqual([action for action,_ in self.calls],['writing_ready'])
        self.assertEqual(self.jobs,[])

    def test_long_unicode_draft_uses_atomic_bounded_chunks(self):
        source=('  美和 👨‍👩‍👧‍👦 coût 3 425,75 €.\n'*7000)
        self.edit(source)
        copied='';offset=0
        while offset is not None:
            row=self.call('read',revision=self.workspace.revision,offset=offset)
            self.assertLessEqual(len(row['text']),16000)
            copied+=row['text'];offset=row['next']
        self.assertEqual(copied,source)

    def test_incomplete_transfer_preserves_the_existing_draft(self):
        self.edit('Keep me')
        token=self.call('begin_edit',revision=self.workspace.revision)['token']
        self.call('append_edit',token=token,offset=0,text='Incomplete replacement')
        self.assertEqual(self.workspace.text,'Keep me')
        with self.assertRaises(ValueError):self.call('append_edit',token=token,offset=0,text='wrong order')
        self.assertEqual(self.workspace.text,'Keep me')

    def test_expired_transfer_does_not_erase_draft(self):
        self.edit('Keep me')
        token=self.call('begin_edit',revision=self.workspace.revision)['token']
        self.workspace.pending['updated']-=121
        with self.assertRaises(ValueError):self.call('commit_edit',token=token)
        self.assertEqual(self.workspace.text,'Keep me')

    def test_other_transfer_and_stale_revision_cannot_replace_new_text(self):
        token=self.call('begin_edit',revision=0)['token']
        self.edit('Newer')
        with self.assertRaises(ValueError):self.call('commit_edit',token=token)
        with self.assertRaises(ValueError):self.call('begin_edit',revision=0)
        self.assertEqual(self.workspace.text,'Newer')

    def test_null_surrogate_oversize_and_non_text_are_rejected(self):
        for text in ('a\x00b','a\ud800b','a'*1_000_001,None):
            with self.subTest(text=str(type(text))), self.assertRaises(ValueError):RambleWorkspace._text(text)

    def test_options_are_explicit_and_do_not_change_the_text(self):
        self.edit('Body')
        self.call('options',format='pdf',style='midnight')
        self.call('export',revision=self.workspace.revision)
        self.assertEqual(self.workspace.job['format'],'pdf:midnight')
        self.assertEqual(self.workspace.text,'Body')

    def test_invalid_options_do_not_silently_choose_a_different_document(self):
        for format,style in [('docx','executive'),('pdf','missing'),([],{}),(True,'executive')]:
            with self.subTest(format=format),self.assertRaises(ValueError):self.call('options',format=format,style=style)

    def test_finishing_and_exports_run_off_the_request_thread(self):
        self.edit('Original')
        self.call('finish',revision=self.workspace.revision)
        self.assertEqual(len(self.jobs),1)
        self.assertNotIn('finish',[action for action,_ in self.calls])
        self.jobs.pop(0)()
        self.assertEqual(self.workspace.text,'Original')
        self.callbacks.pop(0)()
        self.assertEqual(self.workspace.text,'Finished: Original')

    def test_finish_preserves_original_and_waits_for_an_explicit_save(self):
        self.edit('Original')
        self.call('finish',revision=self.workspace.revision)
        self.complete()
        self.assertEqual(self.workspace.original,'Original')
        self.assertEqual(self.workspace.text,'Finished: Original')
        self.assertNotIn('export',[action for action,_ in self.calls])
        self.assertNotIn('open',[action for action,_ in self.calls])

    def test_failed_finish_keeps_both_versions_with_history_disabled(self):
        self.edit('Original')
        self.failure='Model unavailable.'
        self.call('finish',revision=self.workspace.revision);self.complete()
        self.assertEqual(self.workspace.text,'Original')
        self.assertEqual(self.workspace.original,'Original')
        self.assertTrue(self.workspace.error)
        self.assertNotIn('history',[action for action,_ in self.calls])

    def test_failed_export_keeps_the_finished_text_and_original(self):
        self.edit('Original');self.call('finish',revision=self.workspace.revision);self.complete()
        self.failure='Disk full.'
        self.call('export',revision=self.workspace.revision);self.complete()
        self.assertEqual(self.workspace.text,'Finished: Original')
        self.assertEqual(self.workspace.original,'Original')
        self.assertEqual(self.workspace.exports,[])
        self.assertIn('Disk full',self.workspace.message)

    def test_cancelled_finish_cannot_apply_a_late_result(self):
        self.edit('Original');self.call('finish',revision=self.workspace.revision)
        self.call('cancel_finish');self.complete()
        self.assertEqual(self.workspace.text,'Original')

    def test_typing_during_finishing_preserves_the_new_draft(self):
        self.edit('Original');self.call('finish',revision=self.workspace.revision)
        self.edit('Newer edit');self.complete()
        self.assertEqual(self.workspace.text,'Newer edit')
        self.assertEqual(self.workspace.original,'Original')

    def test_worker_uses_the_config_snapshot_it_started_with(self):
        self.edit('Original');self.call('finish',revision=self.workspace.revision)
        self.config['cleanup']['tone']='new'
        self.assertEqual(self.workspace.job['config']['cleanup']['tone'],'formal')

    def test_blank_model_result_never_empties_the_draft(self):
        self.edit('Original');self.call('finish',revision=self.workspace.revision)
        self.workspace._complete(self.workspace.job,'',None)
        self.assertEqual(self.workspace.text,'Original')
        self.assertTrue(self.workspace.error)

    def test_export_receipts_do_not_expose_paths_and_open_only_known_files(self):
        self.edit('Original');self.call('export',revision=self.workspace.revision);self.complete()
        row=self.call('status')['exports'][0]
        self.assertNotIn('path',row)
        self.call('open_export',id=row['id'])
        self.assertEqual(self.calls[-1],('open',Path('/private-fixture/document.pdf')))
        self.call('show_folder',id=row['id'])
        self.assertEqual(self.calls[-1],('open',Path('/private-fixture')))
        with self.assertRaises(ValueError):self.call('open_export',id='C:/other/file')

    def test_export_cannot_clear_or_edit_its_in_flight_draft(self):
        self.edit('Original');self.call('export',revision=self.workspace.revision)
        with self.assertRaises(ValueError):self.call('clear',revision=self.workspace.revision,confirmed=True)
        with self.assertRaises(ValueError):self.call('begin_edit',revision=self.workspace.revision)

    def test_recording_appends_without_replacing_the_prior_draft(self):
        self.edit('Prior')
        self.call('speech_start',revision=self.workspace.revision)
        self.call('speech_stop')
        self.assertTrue(self.workspace.recording)
        self.sink('New recording')
        self.assertEqual(self.workspace.text,'Prior\n\nNew recording')
        self.assertFalse(self.workspace.recording)
        self.assertEqual(self.jobs,[])

    def test_stale_recording_cannot_land_after_cancel(self):
        self.edit('Prior');self.call('speech_start',revision=self.workspace.revision)
        self.call('speech_cancel');self.sink('Discarded')
        self.assertEqual(self.workspace.text,'Prior')

    def test_missing_recording_retains_prior_draft_and_cleans_capture(self):
        self.edit('Prior');self.call('speech_start',revision=self.workspace.revision)
        self.recording=False
        self.assertFalse(self.call('status')['recording'])
        self.assertEqual(self.workspace.text,'Prior')
        self.assertIn('Recovery',self.workspace.message)

    def test_full_editor_keeps_the_new_recording_in_original(self):
        self.edit('a'*1_000_000)
        self.call('speech_start',revision=self.workspace.revision);self.sink('New recording')
        self.assertEqual(self.workspace.original,'New recording')
        self.assertEqual(len(self.workspace.text),1_000_000)
        self.assertTrue(self.workspace.error)

    def test_original_identity_changes_when_a_new_finish_starts(self):
        self.edit('One');self.call('finish',revision=self.workspace.revision);self.complete()
        old=self.workspace.original_id
        self.edit('Two');self.call('finish',revision=self.workspace.revision)
        self.assertNotEqual(old,self.workspace.original_id)
        with self.assertRaises(ValueError):self.call('read',part='original',revision=self.workspace.revision,id=old)

    def test_clear_needs_confirmation_and_keeps_saved_files(self):
        self.edit('One');self.call('export',revision=self.workspace.revision);self.complete()
        with self.assertRaises(ValueError):self.call('clear',revision=self.workspace.revision)
        self.call('clear',revision=self.workspace.revision,confirmed=True)
        self.assertEqual(self.workspace.text,'')
        self.assertEqual(len(self.workspace.exports),1)

    def test_copy_original_rejects_the_previous_finish_identity(self):
        self.edit('One');self.call('finish',revision=self.workspace.revision);self.complete()
        old=self.workspace.original_id
        self.edit('Two');self.call('finish',revision=self.workspace.revision)
        with self.assertRaises(ValueError):self.call('copy',part='original',revision=self.workspace.revision,id=old)
        self.call('copy',part='original',revision=self.workspace.revision,id=self.workspace.original_id)
        self.assertEqual(self.calls[-1],('copy','Two'))

    def test_close_invalidates_model_work_and_keeps_session_draft_on_reopen(self):
        self.edit('Keep me');self.call('finish',revision=self.workspace.revision)
        self.workspace.close();self.complete()
        self.call('open')
        self.assertEqual(self.workspace.text,'Keep me')


class RambleOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.app=SimpleNamespace(lock=threading.RLock(),session_token=None,_ramble_workspace_sink=None,
            _cross_thread_calls=queue.Queue(),overlay=Mock(onboarding_test_sink=None),
            _has_a_writing_model=Mock(return_value=True),stop_session=Mock(),cancel=Mock(),last_transcript='Other dictation')
        self.app.start_session=Mock(side_effect=lambda *_args,**_kwargs:setattr(self.app,'session_token',object()))
        self.actions=RambleActions(self.app,Mock(),Mock(),lambda:self.app.session_token is not None)
        self.registry=patch('knight_flow.mic_registry.microphone_registry',return_value=Mock(is_active=lambda:False))
        self.registry.start();self.addCleanup(self.registry.stop)

    def test_capture_uses_the_existing_ramble_mode_and_hands_free_ceiling(self):
        self.actions('speech_start',Mock())
        self.assertEqual(self.app.start_session.call_args.args[0],'ramble')
        self.assertEqual(self.app.start_session.call_args.kwargs,{'control':'hands_free'})

    def test_missing_writing_model_blocks_capture_and_finishing(self):
        self.app._has_a_writing_model.return_value=False
        for operation in ('speech_start','finish_available'):
            with self.assertRaises(ValueError):self.actions(operation,Mock())
        self.app.start_session.assert_not_called()

    def test_existing_recording_is_never_cancelled_to_start_ramble(self):
        self.app.session_token=object()
        with self.assertRaises(ValueError):self.actions('speech_start',Mock())
        self.app.start_session.assert_not_called();self.app.cancel.assert_not_called()

    def test_failed_start_removes_only_its_own_sink(self):
        self.app.start_session.side_effect=lambda *_a,**_k:None
        with self.assertRaises(ValueError):self.actions('speech_start',Mock())
        self.assertIsNone(self.app._ramble_workspace_sink)
        self.assertIsNone(self.actions.speech)

    def test_completed_capture_waits_for_ui_delivery_after_engine_retires_token(self):
        completed=Mock();self.actions('speech_start',completed);token=self.app.session_token
        self.assertTrue(self.actions.receive(token,'Words'))
        self.app.session_token=None
        self.assertTrue(self.actions('speech_active',None));completed.assert_not_called()
        self.app._cross_thread_calls.get_nowait()()
        completed.assert_called_once_with('Words')
        self.assertFalse(self.actions('speech_active',None))
        self.assertEqual(self.app.last_transcript,'Other dictation')

    def test_cancelling_pending_delivery_rejects_the_late_callback(self):
        completed=Mock();self.actions('speech_start',completed);self.actions.receive(self.app.session_token,'Words')
        self.app.session_token=None;self.actions('speech_cancel',None)
        self.app._cross_thread_calls.get_nowait()()
        completed.assert_not_called();self.app.cancel.assert_not_called()

    def test_cancel_or_stop_cannot_touch_a_newer_microphone(self):
        self.actions('speech_start',Mock());self.app.session_token=object()
        self.actions('speech_stop',None);self.actions('speech_cancel',None)
        self.app.stop_session.assert_not_called();self.app.cancel.assert_not_called()

    def test_foreign_sink_is_not_cleared_by_ramble_cancel(self):
        self.actions('speech_start',Mock());other=Mock();self.app._ramble_workspace_sink=other
        self.app.session_token=object();self.actions('speech_cancel',None)
        self.assertIs(self.app._ramble_workspace_sink,other)

    def test_result_does_not_repaint_a_newer_recording(self):
        self.actions('speech_start',Mock());self.actions.receive(self.app.session_token,'Words')
        self.app.session_token=object();self.app._cross_thread_calls.get_nowait()()
        self.app.overlay.set_state.assert_not_called()

    def test_old_token_cannot_deliver_into_a_new_ramble(self):
        completed=Mock();self.actions('speech_start',completed);old=self.app.session_token
        self.actions('speech_cancel',None);self.app.session_token=None;self.actions('speech_start',completed)
        self.assertFalse(self.actions.receive(old,'Old words'));completed.assert_not_called()


class RambleEngineDeliveryTests(unittest.TestCase):
    def test_engine_finalizes_protected_capture_and_delivers_only_to_its_workspace(self):
        from tests.test_app_session_lifecycle import _app,_SafetyCapture
        token=object();app=_app(token);capture=_SafetyCapture()
        app.safety_capture=capture;app.safety_capture_token=token
        app.recover_transcript_if_needed=lambda _session,_mode,text:text
        app._ramble_workspace_sink=Mock(return_value=True)
        app.finish_ramble=Mock();app.handle_dictation=Mock()
        app.on_session_done(token,'ramble','Captured words')
        app._ramble_workspace_sink.assert_called_once_with(token,'Captured words')
        app.finish_ramble.assert_not_called();app.handle_dictation.assert_not_called()
        self.assertEqual(capture.finalized[-1]['status'],'captured')
        self.assertEqual(capture.finalized[-1]['raw_transcript'],'Captured words')
        self.assertIsNone(app.session_token)

    def test_closed_workspace_never_falls_back_to_an_unexpected_legacy_export(self):
        from tests.test_app_session_lifecycle import _app,_SafetyCapture
        token=object();app=_app(token);capture=_SafetyCapture()
        app.safety_capture=capture;app.safety_capture_token=token
        sink=Mock(return_value=False);app._ramble_workspace_sink=sink
        def recover(_session,_mode,text):
            app._ramble_workspace_sink=None
            return text
        app.recover_transcript_if_needed=recover
        app.finish_ramble=Mock()
        app.on_session_done(token,'ramble','Captured words')
        sink.assert_called_once_with(token,'Captured words')
        app.finish_ramble.assert_not_called()
        self.assertEqual(capture.finalized[-1]['status'],'cancelled')


if __name__ == '__main__':unittest.main()
