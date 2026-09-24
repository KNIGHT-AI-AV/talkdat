"""Setup owns its practice session and its renewable keyboard-check lease."""
from __future__ import annotations
import sys,time
from knight_flow.onboarding import primary_hotkey,TERMS_URL,PRIVACY_URL


def physical_key_down(key):
    if sys.platform=='darwin':
        from knight_flow.mac_support import physical_key_down as read
    else:
        from knight_flow.hotkeys import physical_key_down as read
    return read(key)


class SetupActions:
    def __init__(self,app,copy_text,busy):
        self.app,self.copy_text,self.busy=app,copy_text,busy
        self.speech=None;self.lease=None;self.rehearsal_until=0;self.rehearsal_matched=False

    def __call__(self,action,value):
        app=self.app
        if action=='copy':return self.copy_text(value)
        if action=='document':
            if type(value) is not str or value not in {'terms','privacy'}:raise ValueError('Choose Terms or Privacy.')
            import webbrowser
            if not webbrowser.open(TERMS_URL if value=='terms' else PRIVACY_URL):raise ValueError('The page could not open in your browser. Try again.')
            return
        if action=='permissions':
            if sys.platform!='darwin':return []
            from knight_flow import mac_support
            try:report=mac_support.permission_report()
            except Exception:report={}
            labels={'microphone':'Microphone','accessibility':'Typing into other apps','input_monitoring':'Trigger keys'}
            return [{'id':key,'label':labels.get(key,key.replace('_',' ').title()),
                     'state':report.get(key) if report.get(key) in {'granted','denied','not asked'} else 'unknown'} for key in mac_support.PERMISSION_ORDER]
        if action=='permission':
            if sys.platform!='darwin':raise ValueError('Permission controls are available on Mac.')
            from knight_flow import mac_support
            if type(value) is not str or value not in mac_support.PERMISSION_ORDER:raise ValueError('Choose an available permission.')
            if not mac_support.request_permission(value):raise ValueError('System Settings could not open. Review Privacy & Security on your Mac.')
            return
        if action.startswith('rehearsal_'):
            hotkeys=app.hotkeys
            if action=='rehearsal_start':
                with app.lock:
                    from knight_flow.mic_registry import microphone_registry
                    if self.busy() or microphone_registry().is_active():raise ValueError('Finish recording before checking the trigger.')
                    with hotkeys.lock:
                        if hotkeys._shortcut_recording_until>time.monotonic():raise ValueError('Finish the other shortcut check first.')
                        hotkeys.record_shortcut(True);self.lease=hotkeys._shortcut_recording_until
                    self.rehearsal_until=time.monotonic()+30;self.rehearsal_matched=False
                return
            with hotkeys.lock:
                owned=self.lease is not None and hotkeys._shortcut_recording_until==self.lease
                if action=='rehearsal_stop':
                    if owned:hotkeys.record_shortcut(False)
                    self.lease=None;return
                if action!='rehearsal_status':raise ValueError('That trigger action is unavailable.')
                if not owned or time.monotonic()>=self.rehearsal_until:
                    if owned:hotkeys.record_shortcut(False)
                    self.lease=None;return {'active':False,'matched':False}
                pressed=set(hotkeys.pressed)
                states=[]
                for key in primary_hotkey(app.config):
                    state=physical_key_down(key)
                    states.append(key in pressed if state is None else state is True)
                matched=bool(states) and all(states)
                self.rehearsal_matched=self.rehearsal_matched or matched
                released=self.rehearsal_matched and not any(states)
                if released:
                    hotkeys.record_shortcut(False);self.lease=None
                else:
                    hotkeys.record_shortcut(True);self.lease=hotkeys._shortcut_recording_until
                return {'active':not released,'matched':self.rehearsal_matched}
        if action=='speech_start':
            from knight_flow.mic_registry import microphone_registry
            with app.lock:
                if self.busy() or microphone_registry().is_active() or app.overlay.onboarding_test_sink is not None:
                    raise ValueError('Finish the current recording or guided check before practice.')
                entry={'token':None,'sink':None,'complete':value,'done':False}
                def receive(text):
                    if self.speech is not entry or app.overlay.onboarding_test_sink is not entry['sink'] or app.session_token is not entry['token']:return
                    entry['done']=True;entry['complete'](text)
                    if app.overlay.onboarding_test_sink is entry['sink']:app.overlay.onboarding_test_sink=None
                    self.speech=None
                entry['sink']=receive;self.speech=entry;app.overlay.onboarding_test_sink=receive
                try:
                    app.start_session('dictation','Setup practice. Speak, then choose Finish recording.',control='hands_free')
                    entry['token']=app.session_token
                    if entry['token'] is None:raise ValueError('Practice could not start. Check your microphone and speech settings, and resume Talk DAT if paused.')
                except Exception:
                    if app.overlay.onboarding_test_sink is entry['sink']:app.overlay.onboarding_test_sink=None
                    self.speech=None;raise
            return
        if action in {'speech_status','speech_stop','speech_cancel'}:
            with app.lock:
                entry=self.speech
                owned=bool(entry and entry['token'] is not None and app.session_token is entry['token'])
                sink_owned=bool(entry and app.overlay.onboarding_test_sink is entry['sink'])
                if action=='speech_status':
                    return {'active':owned and sink_owned,'processing':owned and str(app.overlay.state)=='processing'}
                if action=='speech_stop':
                    if owned and sink_owned:app.stop_session()
                else:
                    if owned:app.cancel()
                    if sink_owned and app.overlay.onboarding_test_sink is entry['sink']:app.overlay.onboarding_test_sink=None
                    self.speech=None
            return
        raise ValueError('That setup action is unavailable.')
