"""Typed shared controls for local microphone and speech diagnostics."""
import copy
from knight_flow.config import _SAVE_LOCK
from knight_flow.web_shell.shell_devices import InputDevices


class MicCheckWorkspace:
    def __init__(self, config, persist, start, copy_text, devices=None):
        self.config, self.persist, self.start, self.copy_text = config, persist, start, copy_text
        self.devices = devices or InputDevices()
        self.check = None
        self.mode = 'mic'
        self.closed = False

    def snapshot(self):
        idle = {'phase':'idle', 'mode':self.mode, 'active':False, 'level':0,
                'elapsed':0, 'seconds':3 if self.mode == 'mic' else 8,
                'message':'Microphone off. Start a check when you are ready.',
                'text':'', 'report':None, 'recognition_ms':None}
        return {'check':self.check.snapshot() if self.check else idle,
                'devices':self.devices.snapshot(),
                'selected':str(self.config.get('audio', {}).get('input_device', '') or '')}

    def handle(self, payload):
        if self.closed:raise ValueError('Open the microphone tools again to continue.')
        if type(payload) is not dict:raise ValueError('That microphone action is unavailable.')
        operation = payload.get('operation')
        keys = {'operation', 'mode'} if operation == 'open' else {'operation', 'value'} if operation == 'select' else {'operation'}
        if set(payload) != keys:raise ValueError('That microphone action is unavailable.')
        if operation == 'open':
            mode = payload['mode']
            if mode not in {'mic', 'speech'}:raise ValueError('Choose a microphone or speech check.')
            if self.check and self.check.snapshot()['active'] and mode != self.mode:
                raise ValueError('Stop the current check before switching tools.')
            if mode != self.mode:self.check = None
            self.mode = mode
            if self.devices.snapshot()['status'] == 'idle':self.devices.refresh()
        elif operation == 'refresh':
            self.devices.refresh()
        elif operation == 'select':
            if self.check and self.check.snapshot()['active']:
                raise ValueError('Stop the check before changing microphones.')
            value = payload['value']
            if type(value) is not str or len(value) > 512 or (value and value not in self.devices.snapshot()['devices']):
                raise ValueError('Refresh the input list and choose an available microphone.')
            with _SAVE_LOCK:
                candidate = copy.deepcopy(self.config)
                candidate.setdefault('audio', {})['input_device'] = value
                try:self.persist(candidate)
                except Exception:raise ValueError('The microphone choice could not be saved. Your previous choice remains.') from None
                self.config.clear();self.config.update(candidate)
        elif operation == 'start':
            if self.check and self.check.snapshot()['active']:
                raise ValueError('A check is already running.')
            self.check = self.start(self.mode)
        elif operation == 'stop':
            if self.check:self.check.stop()
        elif operation == 'copy':
            snapshot = self.check.snapshot() if self.check else {}
            text = snapshot.get('text', '')
            if snapshot.get('phase') != 'ready' or not text:
                raise ValueError('There are no test words to copy yet.')
            self.copy_text(text)
        elif operation != 'status':
            raise ValueError('That microphone action is unavailable.')
        return self.snapshot()

    def close(self):
        self.closed = True
        if self.check:self.check.stop()
