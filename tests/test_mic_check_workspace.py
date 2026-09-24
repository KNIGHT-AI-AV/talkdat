import copy
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from knight_flow.web_shell.mic_check_workspace import MicCheckWorkspace


class MicCheckWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.config={'audio':{'input_device':'7: Studio'},'dictionary':{'words':['preserve']}}
        self.persist=Mock();self.copy=Mock();self.state={'active':False,'phase':'idle','text':''}
        self.stop=Mock(side_effect=lambda:self.state.update(active=False))
        self.check=SimpleNamespace(snapshot=lambda:copy.deepcopy(self.state),stop=self.stop)
        self.start=Mock(return_value=self.check)
        self.devices=SimpleNamespace(snapshot=lambda:{'status':'ready','devices':['7: Studio','9: Other'],'message':''},refresh=Mock())
        self.service=MicCheckWorkspace(self.config,self.persist,self.start,self.copy,self.devices)
    def call(self,operation,**kw):return self.service.handle({'operation':operation,**kw})
    def test_open_and_device_refresh_never_open_input(self):
        self.call('open',mode='mic');self.call('refresh');self.start.assert_not_called()
    def test_device_selection_persists_before_changing_config(self):
        def persist(candidate):
            self.assertEqual(self.config['audio']['input_device'],'7: Studio')
            self.assertEqual(candidate['audio']['input_device'],'9: Other')
        self.persist.side_effect=persist;self.call('select',value='9: Other')
        self.assertEqual(self.config['audio']['input_device'],'9: Other')
        self.assertEqual(self.config['dictionary']['words'],['preserve'])
    def test_failed_device_save_keeps_the_previous_input(self):
        self.persist.side_effect=OSError('private path')
        with self.assertRaisesRegex(ValueError,'previous choice'):self.call('select',value='9: Other')
        self.assertEqual(self.config['audio']['input_device'],'7: Studio')
    def test_unknown_device_and_extra_parameters_are_rejected(self):
        for value in ['10: Phantom',False,{}]:
            with self.assertRaises(ValueError):self.call('select',value=value)
        with self.assertRaises(ValueError):self.call('start',code='anything')
        self.persist.assert_not_called();self.start.assert_not_called()
    def test_start_uses_the_opened_tool_mode(self):
        self.call('open',mode='speech');self.call('start');self.start.assert_called_once_with('speech')
    def test_live_check_rejects_device_and_mode_changes_and_duplicate_start(self):
        self.call('start');self.state['active']=True
        for operation,kw in [('select',{'value':'9: Other'}),('open',{'mode':'speech'}),('start',{})]:
            with self.assertRaises(ValueError):self.call(operation,**kw)
        self.persist.assert_not_called();self.assertEqual(self.start.call_count,1)
    def test_stop_and_close_cancel_only_the_owned_check(self):
        self.call('start');self.call('stop');self.service.close()
        self.assertEqual(self.stop.call_count,2)
        with self.assertRaises(ValueError):self.call('status')
    def test_copy_uses_only_completed_test_text(self):
        self.call('start')
        with self.assertRaises(ValueError):self.call('copy')
        self.state.update(phase='ready',text='Words actually recognized.')
        self.call('copy');self.copy.assert_called_once_with('Words actually recognized.')
    def test_switching_tools_discards_the_other_result_after_it_finishes(self):
        self.call('start');self.state.update(phase='ready',text='Old')
        result=self.call('open',mode='speech');self.assertEqual(result['check']['text'],'')
    def test_system_default_is_an_explicit_saved_choice(self):
        self.call('select',value='');self.assertEqual(self.config['audio']['input_device'],'')


if __name__=='__main__':unittest.main()
