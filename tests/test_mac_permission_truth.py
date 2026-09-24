"""Fallback permission UI must distinguish granted, denied and unverified."""
from contextlib import ExitStack
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from knight_flow import mac_support, onboarding
from knight_flow.ui import onboarding as ui


class MacPermissionTruthTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(mac_support, 'IS_MAC', True))
        self.report = {page.key: 'unknown' for page in onboarding.MAC_PERMISSION_PAGES}
        self.stack.enter_context(patch.object(mac_support, 'permission_report', side_effect=lambda: dict(self.report)))
        self.prompts = self.stack.enter_context(patch.object(mac_support, 'fire_permission_prompts_via_helper', return_value=True))
        self.palette = {'panel': '#111111', 'text': '#ffffff', 'muted': '#aaaaaa',
                        'stroke': '#555555', 'accent2': '#33bb77'}

    def render_page(self):
        for name in ('Frame', 'Label', 'Canvas'):
            self.stack.enter_context(patch.object(ui.tk, name, side_effect=lambda *args, **kwargs: MagicMock()))
        wizard = SimpleNamespace(content=object(), palette=self.palette, px=lambda value: value,
                                 host_px=lambda value: value, wrap=lambda value: value,
                                 permission_index=0, _show_permission=MagicMock(),
                                 _poll_permissions=MagicMock(), status_var=MagicMock())
        ui.OnboardingWizard._render_permissions(wizard)
        return wizard.status_var.set.call_args.args[0]

    def test_unknown_is_neither_verified_nor_a_denial(self):
        self.assertFalse(onboarding.permission_is_satisfied('unknown'))
        self.assertEqual(onboarding.permissions_outstanding(self.report), ())

    def test_missing_and_unrecognized_states_are_not_verified(self):
        for state in ('', 'unavailable', None):
            with self.subTest(state=state):
                self.assertFalse(onboarding.permission_is_satisfied(state))
        self.assertEqual(onboarding.permissions_outstanding({}), ())

    def test_unknown_checklist_has_no_green_tick(self):
        tick, label = MagicMock(), MagicMock()
        wizard = SimpleNamespace(_permission_rows={'microphone': (tick, object(), label)},
                                 palette=self.palette, px=lambda value: value)
        ui.OnboardingWizard._refresh_permission_states(wizard)
        tick.create_line.assert_not_called()
        self.assertEqual(label.configure.call_args.kwargs['fg'], self.palette['muted'])
        self.assertIn('Cannot be checked', label.configure.call_args.kwargs['text'])

    def test_granted_checklist_has_verified_tick(self):
        self.report['microphone'] = 'granted'
        tick, label = MagicMock(), MagicMock()
        wizard = SimpleNamespace(_permission_rows={'microphone': (tick, object(), label)},
                                 palette=self.palette, px=lambda value: value)
        ui.OnboardingWizard._refresh_permission_states(wizard)
        tick.create_line.assert_called_once()
        self.assertEqual(label.configure.call_args.kwargs['text'], 'Allowed')

    def test_unknown_page_does_not_claim_all_granted_or_prompt(self):
        status = self.render_page()
        self.assertIn('could not be checked', status)
        self.assertNotIn('already allowed', status)
        self.prompts.assert_not_called()

    def test_partial_unknown_page_preserves_uncertainty(self):
        self.report['microphone'] = 'granted'
        self.assertIn('could not be checked', self.render_page())
        self.prompts.assert_not_called()

    def test_all_granted_needs_no_prompt(self):
        self.report = dict.fromkeys(self.report, 'granted')
        self.assertIn('already allowed', self.render_page())
        self.prompts.assert_not_called()

    def test_known_denial_remains_actionable(self):
        self.report['input_monitoring'] = 'denied'
        self.assertEqual(onboarding.permissions_outstanding(self.report), ('input_monitoring',))
        self.render_page()
        self.prompts.assert_called_once()


if __name__ == '__main__':
    unittest.main()
