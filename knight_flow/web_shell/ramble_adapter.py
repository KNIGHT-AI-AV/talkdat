"""Ramble keeps the existing capture ceilings and owns only its microphone."""
from __future__ import annotations


class RambleActions:
    def __init__(self, app, copy_text, open_path, busy):
        self.app, self.copy_text, self.open_path, self.busy = app, copy_text, open_path, busy
        self.speech = None

    def receive(self, token, text):
        """Called by the engine before its session token is retired."""
        app = self.app
        with app.lock:
            entry = self.speech
            if (entry is None or entry['token'] is not token or app.session_token is not token
                    or app._ramble_workspace_sink is not entry['sink']):
                return False
            entry['pending'] = True

        def complete():
            if self.speech is not entry:
                return
            if app._ramble_workspace_sink is entry['sink']:
                app._ramble_workspace_sink = None
            self.speech = None
            app.overlay.hide_ramble_indicator()
            entry['complete'](text)
            # This draft never changes Paste Last or another recording's Pill.
            with app.lock:
                if app.session_token is None:
                    app.overlay.set_state('captured','Ramble is ready to review.','Open Writing > Ramble to edit and save your document.',say=True)

        app._cross_thread_calls.put(complete)
        return True

    def __call__(self, action, value):
        app = self.app
        if action == 'writing_ready':
            return app._has_a_writing_model()
        if action == 'finish_available':
            if self.busy():
                raise ValueError('Finish the current dictation before finishing this draft.')
            if not app._has_a_writing_model():
                raise ValueError('Choose a local writing model or your own provider key in Writing > Formatting. You can still edit or save this draft.')
            return
        if action == 'finish':
            from knight_flow.text_pipeline import process_dictation
            return process_dictation(value['text'],value['config']).text
        if action == 'export':
            from knight_flow.ramble_export import save_ramble
            return save_ramble(value['text'],value['format'])
        if action == 'copy':
            self.copy_text(value)
            return
        if action == 'open':
            self.open_path(value)
            return
        if action == 'speech_start':
            from knight_flow.mic_registry import microphone_registry
            with app.lock:
                if self.busy() or microphone_registry().is_active() or app.overlay.onboarding_test_sink is not None:
                    raise ValueError('Finish the current recording or guided setup before recording a Ramble.')
                if not app._has_a_writing_model():
                    raise ValueError('Ramble needs a writing model. Choose a local model or your own provider key in Writing > Formatting.')
                if self.speech is not None or getattr(app,'_ramble_workspace_sink',None) is not None:
                    raise ValueError('Finish the current Ramble before starting another.')
                entry = dict(token=None,pending=False,complete=value,sink=self.receive)
                self.speech = entry
                app._ramble_workspace_sink = entry['sink']
                try:
                    app.start_session('ramble','Ramble: speak your thought. Click the Pill or Finish recording when you are ready.',control='hands_free')
                    entry['token'] = app.session_token
                    if entry['token'] is None:
                        raise ValueError('Recording could not start. Check the microphone and resume Talk DAT if it is paused.')
                    app.overlay.show_ramble_indicator()
                except Exception:
                    if app._ramble_workspace_sink is entry['sink']:
                        app._ramble_workspace_sink = None
                    self.speech = None
                    raise
            return
        if action == 'speech_active':
            with app.lock:
                entry = self.speech
                return bool(entry and app._ramble_workspace_sink is entry['sink']
                    and (entry['pending'] or app.session_token is entry['token']))
        if action in {'speech_stop','speech_cancel'}:
            with app.lock:
                entry = self.speech
                if entry is None:
                    return
                owns = entry['token'] is not None and app.session_token is entry['token']
                if action == 'speech_stop':
                    if owns and not entry['pending']:
                        app.stop_session()
                else:
                    if owns and not entry['pending']:
                        app.cancel()
                    if app._ramble_workspace_sink is entry['sink']:
                        app._ramble_workspace_sink = None
                    self.speech = None
                    app.overlay.hide_ramble_indicator()
            return
        raise ValueError('That Ramble action is unavailable.')
