"""UI-owned acceptance and microphone routing for the translation workspace."""
import time


class TranslationActions:
    def __init__(self, app, copy_text, busy):
        self.app, self.copy_text, self.busy = app, copy_text, busy
        self.speech = None

    def __call__(self, action, value):
        from knight_flow import translation
        app = self.app
        if action == 'capture_busy':
            return self.busy()
        if action == 'available':
            if self.busy():
                raise ValueError('Finish the current dictation before starting translation or engine setup.')
            return True
        if action == 'translate':
            config = value['config']
            options = value['options']
            config.setdefault('translation', {}).update(formality=options['formality'], preserve_formatting=options['preserve_formatting'])
            return translation.translate_text(value['text'],config,source_value=options['source'],
                target_value=options['target'],model_value=options['model'],
                progress=value['progress'],cancelled=value['cancel'].is_set).as_dict()
        if action in {'check','start_engine','install_engine','download_model'}:
            config, model = value['config'], value['options']['model']
            success, message = True, ''
            if action == 'start_engine':
                success, message = translation._ensure_ollama_running(config.get('translation',{}).get('api_base') or translation.OLLAMA_DEFAULT_BASE)
            elif action == 'install_engine':
                success, message = translation.install_ollama_runtime()
            elif action == 'download_model':
                success, message = translation.install_translation_model(config, model)
            status = translation.translation_model_status(config, model)
            if not message:
                message = ('Ready on this computer.' if status['ready'] else
                    'Install Ollama to translate on this computer.' if not status['engine_installed'] else
                    'Start Ollama, then check again.' if not status['engine_running'] else
                    'Download the selected translation model to get started.')
            return {'status':status,'success':success,'message':message}
        if action == 'download_page':
            import webbrowser
            webbrowser.open(translation.OLLAMA_DOWNLOAD_URL)
            return
        if action == 'copy':
            self.copy_text(value)
            return
        if action == 'accept':
            # A manual result must not replace a newer dictation's Paste Last.
            # Acceptance is on the UI queue, after revision/cancellation checks.
            if app.config.get('privacy',{}).get('save_history',True):
                app.add_history({'type':'translation','original':value['original'],'text':value['text'],
                    'source_language':value['source_code'],'target_language':value['target_code'],
                    'model':value['model'],'created_at':time.time()})
            return
        if action == 'speech_start':
            from knight_flow.mic_registry import microphone_registry
            with app.lock:
                if self.busy() or microphone_registry().is_active() or app.overlay.onboarding_test_sink is not None:
                    raise ValueError('Finish the current recording or guided setup before speaking here.')
                entry = {'sink':None, 'token':None}
                def finish(text):
                    if self.speech is not entry:
                        return
                    if app.overlay.onboarding_test_sink is finish:
                        app.overlay.onboarding_test_sink = None
                    self.speech = None
                    value(text)
                entry['sink'] = finish
                self.speech = entry
                app.overlay.onboarding_test_sink = finish
                try:
                    app.start_push_to_talk()
                    entry['token'] = app.session_token
                    if entry['token'] is None:
                        raise ValueError('Recording could not start. Check the microphone and resume Talk DAT if it is paused.')
                except Exception:
                    if app.overlay.onboarding_test_sink is finish:
                        app.overlay.onboarding_test_sink = None
                    self.speech = None
                    raise
            return
        if action == 'speech_active':
            with app.lock:
                entry = self.speech
                return bool(entry and app.overlay.onboarding_test_sink is entry['sink'] and
                    (app.session_token is entry['token'] or getattr(app,'_guided_delivery_token',None) is entry['token']))
        if action in {'speech_stop','speech_cancel'}:
            with app.lock:
                entry = self.speech
                if entry is None:
                    return
                owns = entry['token'] is not None and (app.session_token is entry['token'] or getattr(app,'_guided_delivery_token',None) is entry['token'])
                if action == 'speech_stop':
                    if owns:
                        app.stop_session()
                else:
                    # Cancel the exact owned capture BEFORE releasing its sink.
                    # A newer recording or another surface's sink is untouched.
                    if owns:
                        app.cancel()
                    if app.overlay.onboarding_test_sink is entry['sink']:
                        app.overlay.onboarding_test_sink = None
                    self.speech = None
            return
        raise ValueError('That translation action is unavailable.')
