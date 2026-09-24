"""Setup describes received words without treating readiness as execution proof."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from knight_flow.onboarding import ONBOARDING_STEPS
from knight_flow.ui import onboarding as ui


class TheTestStepAsksBeforeItClaimsTests(unittest.TestCase):
    def wizard(self):
        wizard=object.__new__(ui.OnboardingWizard)
        wizard.destroyed=False
        wizard.step_index=next(i for i,step in enumerate(ONBOARDING_STEPS) if step.id=='test')
        wizard._finishing_verdict=Mock(return_value={'ok':True})
        return wizard

    def test_a_readiness_probe_cannot_become_proof_that_this_take_was_formatted(self):
        wizard=self.wizard();wizard.dictation_tested=True
        wizard.host=SimpleNamespace(last_preview='')
        wizard._status_snapshot=lambda:{'session_active':False,'overlay_state':'idle'}
        wizard.practice_status_var=Mock();wizard.test_button=Mock();wizard.window=Mock();wizard._draw_test_visual=Mock()
        wizard._poll_test()
        wizard._finishing_verdict.assert_not_called()
        message=wizard.practice_status_var.set.call_args.args[0]
        self.assertIn('Review the words',message)
        self.assertNotIn('formatting all completed',message)

    def test_an_unavailable_readiness_check_stays_unconfirmed(self):
        wizard=object.__new__(ui.OnboardingWizard);wizard.config={}
        with patch('knight_flow.llm.finishing_status',side_effect=RuntimeError('fixture unavailable')):
            self.assertIs(wizard._finishing_verdict()['ok'],False)

    def test_identical_previews_do_not_invent_a_reason_for_their_similarity(self):
        wizard=self.wizard();wizard.practice_text=Mock();wizard.px=lambda n:n
        wizard.palette={key:'#101010' for key in ('panel','stroke','surface','text','warm','accent2')}
        wizard._detail_button=Mock()
        wizard.host=SimpleNamespace(callbacks={'last_raw_text':lambda:'A synthetic sample.',
            'format_both':lambda raw,done:done(raw,raw)})
        with patch.object(ui.tk,'Frame'),patch.object(ui.tk,'Label') as label,patch.object(ui.tk,'Text'),patch.object(ui.ttk,'Scrollbar'),patch.object(ui.leading,'apply'):
            wizard._offer_finish_choice()
        wizard._finishing_verdict.assert_not_called()
        descriptions=[str(call.kwargs.get('text','')) for call in label.call_args_list]
        self.assertTrue(any('Identical text means there was no visible difference' in text for text in descriptions))
        self.assertFalse(any('AI finishing is off' in text for text in descriptions))


if __name__ == "__main__":
    unittest.main()
