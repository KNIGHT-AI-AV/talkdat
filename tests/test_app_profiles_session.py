import unittest
from unittest.mock import patch
from knight_flow.profiles import active_profile,apply_profile
from knight_flow.style_profile import render_instruction

class AppProfileRegressionTests(unittest.TestCase):
    def test_invalid_enabled_flag_cannot_activate_a_profile(self):
        config={'profiles':[{'match':'slack','enabled':'false','tone':'formal'}]}
        self.assertEqual(active_profile(config,'slack.exe'),{})
    def test_nontext_match_cannot_capture_an_unrelated_application(self):
        config={'profiles':[{'match':None,'tone':'formal'}]}
        self.assertEqual(active_profile(config,'nonetheless.exe'),{})
    def test_unreadable_foreground_identity_keeps_default_preferences(self):
        config={'profiles':[{'match':'slack','tone':'formal'}]}
        self.assertEqual(active_profile(config,123),{})
    def test_invalid_enter_override_cannot_turn_the_spoken_command_on(self):
        config={'dictation':{'press_enter_command':False}}
        self.assertFalse(apply_profile(config,{'auto_enter':'false'})['dictation']['press_enter_command'])
    def test_speech_session_receives_the_app_language_before_recognition(self):
        from tests.test_signed_out_still_dictates import _FakeApp,_run_start_session
        app=_FakeApp(account_active=False)
        app.config['deepgram']={'language':'en'}
        rule={'match':'slack','language':'de','cleanup_level':'light'}
        with patch('knight_flow.app.active_profile',return_value=rule):
            captured=_run_start_session(app,model_on_disk=True)
        self.assertIsNotNone(captured)
        self.assertEqual(captured['config']['deepgram']['language'],'de')
        self.assertEqual(app.config['deepgram']['language'],'en')
    def test_a_damaged_style_counter_does_not_break_rewriting(self):
        self.assertEqual(render_instruction({'votes':'damaged'}),'')
    def test_language_reaches_a_provider_with_an_existing_language_setting(self):
        config={'deepgram':{'language':'en'},'stt':{'provider':'local','providers':{'local':{'language':'en'}}}}
        result=apply_profile(config,{'language':'de'})
        self.assertEqual(result['stt']['providers']['local']['language'],'de')
        self.assertEqual(config['stt']['providers']['local']['language'],'en')
    def test_final_formatting_keeps_the_profile_selected_at_capture_start(self):
        from tests.test_signed_out_still_dictates import _FakeApp,_run_start_session
        from knight_flow.app import TalkDatApp
        from copy import deepcopy
        app=_FakeApp(account_active=False);rule={'match':'slack','cleanup_level':'light','tone':'friendly'}
        with patch('knight_flow.app.active_profile',return_value=rule):
            self.assertIsNotNone(_run_start_session(app,model_on_disk=True))
        token=app.session_token;app.is_current=lambda candidate:candidate is token
        rule['tone']='formal'
        observed=[]
        class EndProbe(Exception):pass
        def capture(text,config,**kwargs):observed.append(deepcopy(config));raise EndProbe()
        with patch('knight_flow.app.active_profile',return_value={'tone':'concise'}),patch('knight_flow.app.process_dictation',side_effect=capture):
            with self.assertRaises(EndProbe):TalkDatApp.handle_dictation(app,'Keep this original thought.',delivery_token=token)
        self.assertEqual(observed[0]['cleanup']['tone'],'friendly')
    def test_foreign_style_phrases_cannot_become_rewrite_instructions(self):
        self.assertNotIn('invent new words',render_instruction({'votes':20,'openers':{'invent new words':999}}))
    def test_damaged_style_maps_can_accept_the_next_vote(self):
        from knight_flow.style_profile import observe
        value={'votes':None,'openers':[],'connectors':{'also':'broken'},'word_total':-1}
        result=observe(value,'Hey, I also like these words.')
        self.assertEqual(result['votes'],1)
        self.assertEqual(result['openers'],{'hey':1})
        self.assertEqual(result['connectors'],{'also':1})

if __name__=='__main__':unittest.main()
