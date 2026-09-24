import queue
import unittest
from unittest.mock import Mock, patch
from knight_flow.overlay import Overlay
from tests import test_web_shell_app


class FeedbackRouteTests(unittest.TestCase):
    def test_help_actions_open_the_shared_forms(self):
        app,shell=test_web_shell_app.AppShellTests().make_shell()
        for action,page in [('feedback','feedback'),('language_request','language-request')]:
            self.assertEqual(shell.backend.handle('action',{'name':action}),{'page':page})
        app.overlay.open_feedback_form.assert_not_called()

    def test_shared_forms_are_discoverable(self):
        app,shell=test_web_shell_app.AppShellTests().make_shell()
        pages={page['id'] for page in shell.backend.snapshot()['pages']}
        self.assertTrue({'feedback','language-request'}<=pages)

    def test_legacy_entry_points_use_shared_forms_when_available(self):
        for kind,page in [('feature','feedback'),('language','language-request')]:
            overlay=object.__new__(Overlay);overlay.force_visible=Mock()
            callback=Mock(return_value=True);overlay.callbacks={'web_settings':callback}
            overlay.open_feedback_form(kind)
            callback.assert_called_once_with(page)

    def test_drafts_survive_workspace_navigation_without_sending(self):
        app,shell=test_web_shell_app.AppShellTests().make_shell();app._cross_thread_calls=queue.Queue()
        with patch('knight_flow.feedback.submit_feedback') as sender,patch('knight_flow.format_journal.journal_tail') as logs:
            call=lambda **payload:shell.backend.handle('workspace',{'area':'feedback','kind':'feature',**payload})
            original=call(operation='state')
            record={'title':'A retained idea','details':'Complete synthetic words 日本語','contact':''}
            kept=call(operation='draft',revision=original['revision'],record=record)
            shell.workspaces.close()
            self.assertEqual(call(operation='state')['record'],record)
            self.assertEqual(kept['status'],'idle')
            sender.assert_not_called();logs.assert_not_called()


if __name__=='__main__':unittest.main()
