import copy,unittest
from types import SimpleNamespace
from unittest.mock import Mock
from knight_flow.web_shell.feedback_workspace import FeedbackWorkspace


class FeedbackWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.work=[];self.queue=[];self.clock=[100.0]
        self.sender=Mock(return_value=True);self.logs=Mock(return_value='Synthetic log 日本語')
        self.clipboard=Mock();self.mail=Mock(return_value=True)
        self.service=FeedbackWorkspace(self.queue.append,self.sender,self.logs,self.clipboard,self.mail,
            thread_factory=lambda target:SimpleNamespace(start=lambda:self.work.append(target)),clock=lambda:self.clock[0])
    def call(self,operation,kind='feature',**values):return self.service.handle(dict(operation=operation,kind=kind,**values))
    def draft(self,kind='feature',title='Synthetic idea',details='The complete message. 日本語',contact=''):
        return self.call('draft',kind,revision=self.call('state',kind)['revision'],record=dict(title=title,details=details,contact=contact))
    def send(self,kind='feature',**changes):
        values=dict(revision=self.call('state',kind)['revision'],confirmed=True,include_logs=False,log_token='');values.update(changes)
        return self.call('send',kind,**values)
    def complete(self):
        self.work.pop(0)()
        while self.queue:self.queue.pop(0)()
    def test_a_draft_survives_navigation_and_other_request_types(self):
        self.draft();self.draft('language',title='Yoruba (Nigeria)',details='Regional examples')
        self.assertEqual(self.call('state')['record']['title'],'Synthetic idea')
        self.assertEqual(self.call('state','language')['record']['title'],'Yoruba (Nigeria)')
        self.sender.assert_not_called();self.logs.assert_not_called()
    def test_send_uses_a_worker_and_completes_only_on_the_ui_queue(self):
        self.draft();result=self.send();self.assertTrue(result['sending']);self.sender.assert_not_called()
        self.work.pop(0)();self.assertTrue(self.call('state')['sending'])
        self.queue.pop(0)();self.assertEqual(self.call('state')['status'],'received')
        self.sender.assert_called_once();self.logs.assert_not_called();self.assertNotIn('logs',self.sender.call_args.args[0])
    def test_a_send_requires_the_explicit_action(self):
        self.draft()
        with self.assertRaises(ValueError):self.send(confirmed=False)
        self.assertEqual(self.work,[]);self.sender.assert_not_called()
    def test_pending_and_received_messages_cannot_be_sent_twice(self):
        self.draft();self.send()
        with self.assertRaises(ValueError):self.send()
        with self.assertRaises(ValueError):self.draft(details='Changed during send')
        self.complete()
        with self.assertRaisesRegex(ValueError,'already has a receipt'):self.send()
        self.assertEqual(self.sender.call_count,1)
    def test_unconfirmed_delivery_retains_the_complete_draft_and_can_retry(self):
        self.draft();self.sender.return_value=False;self.send();self.complete()
        state=self.call('state');self.assertEqual(state['status'],'unconfirmed');self.assertIn('日本語',state['record']['details'])
        self.sender.return_value=True;self.send();self.complete();self.assertEqual(self.call('state')['status'],'received')
    def test_only_a_real_boolean_confirmation_becomes_received(self):
        self.draft();self.sender.return_value='true';self.send();self.complete()
        self.assertEqual(self.call('state')['status'],'unconfirmed')
    def test_attachment_is_the_exact_previewed_snapshot(self):
        self.draft();preview=self.call('logs');self.logs.return_value='Newer unreviewed text'
        self.send(include_logs=True,log_token=preview['token']);self.complete()
        self.assertEqual(self.sender.call_args.args[0]['logs'],preview['text']);self.assertEqual(self.logs.call_count,1)
    def test_a_log_cannot_be_attached_without_a_current_preview(self):
        self.draft()
        with self.assertRaisesRegex(ValueError,'Preview'):self.send(include_logs=True,log_token='made up')
        preview=self.call('logs');self.clock[0]+=301
        with self.assertRaisesRegex(ValueError,'Preview'):self.send(include_logs=True,log_token=preview['token'])
        self.assertEqual(self.work,[])
    def test_a_new_send_needs_new_attachment_consent_after_a_failed_attempt(self):
        self.draft();preview=self.call('logs');self.sender.return_value=False;self.send(include_logs=True,log_token=preview['token']);self.complete()
        with self.assertRaises(ValueError):self.send(include_logs=True,log_token=preview['token'])
    def test_oversized_draft_can_be_kept_and_copied_but_not_silently_truncated(self):
        self.draft(title='',details='🦉'*1100)
        self.assertEqual(self.call('state')['message_length'],2200)
        with self.assertRaisesRegex(ValueError,'2,000'):self.send()
        self.call('copy',record=self.call('state')['record']);self.clipboard.assert_called_once_with('🦉'*1100)
        self.assertEqual(self.work,[])
    def test_language_prefix_counts_toward_the_server_limit(self):
        self.draft('language',title='Yoruba',details='a'*1980)
        with self.assertRaisesRegex(ValueError,'2,000'):self.send('language')
        self.sender.assert_not_called()
    def test_opening_an_email_draft_does_not_claim_delivery(self):
        state=self.draft();self.call('email',revision=state['revision'])
        self.assertEqual(self.call('state')['status'],'idle');self.mail.assert_called_once();self.sender.assert_not_called()
        self.assertNotIn('logs=',self.mail.call_args.args[0])
    def test_thread_start_failure_leaves_retry_available(self):
        self.draft()
        def fail():raise RuntimeError('fixture thread failure')
        self.service.thread_factory=lambda target:SimpleNamespace(start=fail)
        with self.assertRaisesRegex(ValueError,'could not start'):self.send()
        self.assertFalse(self.call('state')['busy']);self.assertEqual(self.call('state')['record']['title'],'Synthetic idea')
    def test_stale_revision_cannot_send_a_changed_draft(self):
        state=self.draft();self.draft(details='A newer thought')
        with self.assertRaisesRegex(ValueError,'changed'):self.send(revision=state['revision'])
        self.assertEqual(self.work,[])
    def test_copy_preserves_an_unsaved_draft_even_if_the_kept_draft_changed(self):
        state=self.draft();self.draft(details='A newer saved draft')
        self.call('copy',record=state['record'])
        self.assertIn('The complete message.',self.clipboard.call_args.args[0])
        self.assertEqual(self.call('state')['record']['details'],'A newer saved draft')
    def test_typed_payloads_cannot_smuggle_extra_fields(self):
        for kind in [[],None,42]:
            with self.subTest(kind=kind),self.assertRaises(ValueError):self.call('state',kind)
        record=dict(title='t',details='d',contact='',logs='hidden')
        with self.assertRaises(ValueError):self.call('draft',revision=0,record=record)
        self.assertEqual(self.call('state')['record']['title'],'')

if __name__=='__main__':unittest.main()
