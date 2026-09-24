"""Session-local translation drafts and cancellable, revision-checked jobs.

Requests and completion callbacks run on the app's UI queue. Engine work runs
in a worker and never writes history, config, clipboard or UI state directly.
"""
from __future__ import annotations

import copy
import secrets
import threading
from typing import Callable

from knight_flow.translation import (
    DEFAULT_TRANSLATION_MODEL, LANGUAGES, TRANSLATION_MODELS,
    language_from_value, normalize_translation_model, resolve_source_language,
)

MAX_SOURCE = 64_000
MAX_RESULT = 384_000
READ_SIZE = 16_000


class TranslationWorkspace:
    def __init__(self, config, utility, dispatch: Callable, launch=None):
        self.config, self.utility, self.dispatch = config, utility, dispatch
        self.launch = launch or self._launch
        self.lock = threading.RLock()
        settings = config.get('translation', {})
        self.text = ''
        self.options = {
            'source': settings.get('source_language', 'auto'),
            'target': settings.get('target_language', 'es'),
            'model': settings.get('model', DEFAULT_TRANSLATION_MODEL),
            'formality': settings.get('formality', 'natural'),
            'preserve_formatting': settings.get('preserve_formatting', True),
        }
        try:
            self.options = self.validate_options(self.options)
        except ValueError:
            self.options = {'source':'auto', 'target':'es', 'model':DEFAULT_TRANSLATION_MODEL,
                            'formality':'natural', 'preserve_formatting':True}
        self.revision = 0
        self.result = None
        self.previous_result = None
        self.job = None
        self.ready = None
        self.message = 'Add a passage, or speak it here.'
        self.error = False
        self.dictating = False
        self.auto_start = False
        self.closed = False

    @staticmethod
    def _launch(work):
        threading.Thread(target=work, name='TalkDatTranslationWorkspace', daemon=True).start()

    @staticmethod
    def validate_options(value):
        if type(value) is not dict or set(value) != {'source','target','model','formality','preserve_formatting'}:
            raise ValueError('Choose the translation languages and options again.')
        if type(value['source']) is not str or (value['source'] != 'auto' and language_from_value(value['source']) is None):
            raise ValueError('Choose a supported source language.')
        if type(value['target']) is not str or language_from_value(value['target']) is None:
            raise ValueError('Choose a supported target language.')
        if type(value['formality']) is not str or value['formality'] not in {'natural','formal','informal','literal'} or type(value['preserve_formatting']) is not bool:
            raise ValueError('Choose an available tone and formatting option.')
        try:
            model = normalize_translation_model(value['model'])
        except Exception as error:
            raise ValueError('Choose an available translation model.') from error
        return {**value, 'model':model}

    def _current(self, revision):
        if type(revision) is not int or revision != self.revision:
            raise ValueError('This passage changed elsewhere. Refresh before replacing it; copy your draft first.')

    def snapshot(self, catalog=False):
        if self.dictating and not self.utility('speech_active', None):
            self.utility('speech_cancel', None)
            self.dictating = False
            self.message = 'Recording ended without new text. Your passage is kept.'
        if self.auto_start and self.job is None and not self.utility('capture_busy', None):
            self.auto_start = False
            try:
                self.start('translate')
            except Exception as error:
                self.message, self.error = str(error), True
        result = self.result
        response = {
            'revision':self.revision, 'source_length':len(self.text), 'options':copy.deepcopy(self.options),
            'result':None if result is None else {key:result[key] for key in ('id','revision','source','target','model','length')},
            'active':self.job is not None, 'kind':self.job['kind'] if self.job else '',
            'cancelling':bool(self.job and self.job['cancel'].is_set()),
            'dictating':self.dictating, 'awaiting_speech':self.auto_start, 'message':self.message, 'error':self.error,
            'ready':copy.deepcopy(self.ready), 'limit':MAX_SOURCE,
        }
        if catalog:
            response.update(languages=[{'value':item.code,'label':item.name} for item in LANGUAGES],
                models=[{'value':key,**value} for key,value in TRANSLATION_MODELS.items()],
                auto_language=resolve_source_language(self.config,'auto').name,
                auto_code=resolve_source_language(self.config,'auto').code)
        return response

    def handle(self, payload):
        if type(payload) is not dict or type(payload.get('operation')) is not str:
            raise ValueError('That translation action is unavailable.')
        with self.lock:
            operation = payload['operation']
            if operation == 'open':
                self.closed = False
            elif self.closed:
                raise ValueError('Reopen Translation before starting another operation.')
            if operation in {'open','status'}:
                return self.snapshot(operation == 'open')
            if operation == 'read':
                offset = payload.get('offset', 0)
                if type(offset) is not int or offset < 0:
                    raise ValueError('Choose a valid text position.')
                if payload.get('part') == 'source':
                    self._current(payload.get('revision'))
                    text = self.text
                elif payload.get('part') == 'result' and self.result and payload.get('id') == self.result['id']:
                    text = self.result['text']
                else:
                    raise ValueError('That translation is no longer current. Refresh to read it.')
                end = min(len(text), offset + READ_SIZE)
                return {'text':text[offset:end], 'next':end if end < len(text) else None}
            if operation == 'edit':
                self._current(payload.get('revision'))
                if self.dictating:
                    raise ValueError('Finish speaking before editing this passage.')
                text = payload.get('text')
                if type(text) is not str or len(text) > MAX_SOURCE or '\x00' in text:
                    raise ValueError('Use a passage of up to 64,000 characters, without null characters.')
                options = self.validate_options(payload.get('options'))
                if text != self.text or options != self.options:
                    self.auto_start = False
                    if self.job and self.job['kind'] in {'translate','check'}:
                        self.job['cancel'].set()
                    if options['model'] != self.options['model']:
                        self.ready = None
                    self.text, self.options = text, options
                    self.revision += 1
                    self.message, self.error = 'Draft kept for this app session.', False
                return self.snapshot()
            if operation == 'cancel':
                if self.job:
                    if self.job['kind'] != 'translate':
                        raise ValueError('Engine setup is still running. You can leave this page and return later.')
                    self.job['cancel'].set()
                    self.message = 'Cancelling. The current local request may need a moment to finish.'
                elif self.result and not self.result['accepted']:
                    self.result, self.previous_result = self.previous_result, None
                    self.message, self.error = 'Translation cancelled. Your source and previous result are kept.', False
                return self.snapshot()
            if operation == 'clear':
                self._current(payload.get('revision'))
                if payload.get('confirmed') is not True:
                    raise ValueError('Confirm before clearing this passage and result.')
                self.stop_speech()
                if self.job and self.job['kind'] in {'translate','check'}:
                    self.job['cancel'].set()
                self.text, self.result, self.previous_result = '', None, None
                self.revision += 1
                self.message, self.error = 'Passage cleared.', False
                return self.snapshot()
            if operation == 'copy':
                if not self.result or payload.get('id') != self.result['id']:
                    raise ValueError('Translate a passage before copying its result.')
                self.utility('copy', self.result['text'])
                return {'message':'Translation copied. Return to your destination and paste it.'}
            if operation == 'accept_result':
                self._current(payload.get('revision'))
                if not self.result or payload.get('id') != self.result['id'] or self.result['revision'] != self.revision:
                    raise ValueError('The result belongs to an earlier passage.')
                if not self.result['accepted']:
                    self.utility('accept', self.result['receipt'])
                    self.result['accepted'] = True
                    self.previous_result = None
                return {'accepted':True}
            if operation == 'speech_start':
                self._current(payload.get('revision'))
                if self.job or self.dictating:
                    raise ValueError('Finish the current translation or recording first.')
                self.dictating = True
                try:
                    self.utility('speech_start', self._spoken)
                except Exception:
                    self.dictating = False
                    raise
                self.message, self.error = 'Listening. Finish when you are ready to translate.', False
                return self.snapshot()
            if operation == 'speech_stop':
                if self.dictating:
                    self.utility('speech_stop', None)
                    self.message = 'Finishing your speech…'
                return self.snapshot()
            if operation == 'speech_cancel':
                self.stop_speech()
                return self.snapshot()
            if operation == 'download_page':
                self.utility('download_page', None)
                return {'message':'Opened the official Ollama download page.'}
            if operation in {'translate','check','start_engine','install_engine','download_model'}:
                self._current(payload.get('revision'))
                if operation == 'download_model' and payload.get('confirmed') is not True:
                    raise ValueError('Confirm the model download and its size first.')
                return self.start(operation)
            raise ValueError('That translation action is unavailable.')

    def start(self, kind):
        if self.job or self.dictating:
            raise ValueError('Wait for the current operation to finish.')
        if kind == 'translate' and not self.text.strip():
            raise ValueError('Add or dictate text before translating.')
        if kind != 'check':
            self.utility('available', None)
        job = {'id':secrets.token_hex(12), 'kind':kind, 'revision':self.revision,
               'cancel':threading.Event(), 'options':copy.deepcopy(self.options),
               'text':self.text, 'config':copy.deepcopy(self.config), 'previous_result':self.result}
        self.job = job
        self.error = False
        self.message = {'translate':'Translating on this computer…','check':'Checking the local model…',
            'start_engine':'Starting the local engine…','install_engine':'Installing the local engine…',
            'download_model':'Downloading the selected model. You can leave this page and return later.'}[kind]

        def progress(index, total):
            with self.lock:
                if self.job is job and not job['cancel'].is_set():
                    self.message = f'Translating passage {index} of {total}…'

        def work():
            result, error = None, None
            try:
                result = self.utility(kind, {**job, 'progress':progress})
            except Exception as caught:
                error = str(caught)
            self.dispatch(lambda: self.complete(job, result, error))
        try:
            self.launch(work)
        except Exception:
            self.job = None
            self.message, self.error = 'The operation could not start. Try again.', True
            raise
        return self.snapshot()

    def complete(self, job, result, error):
        with self.lock:
            if self.job is not job:
                return
            self.job = None
            if self.closed or job['cancel'].is_set() or (job['kind'] in {'translate','check'} and job['revision'] != self.revision):
                self.message, self.error = 'Previous operation ended. Your latest passage is kept.', False
                return
            if error:
                self.message, self.error = error, True
                return
            if job['kind'] != 'translate':
                self.ready = result.get('status')
                self.message = result.get('message', 'Local model status updated.')
                self.error = result.get('success') is False
                return
            text = result.get('text') if type(result) is dict else None
            if type(text) is not str or not text.strip() or len(text) > MAX_RESULT:
                self.message, self.error = 'The engine returned an invalid or oversized result. Your source is kept.', True
                return
            self.previous_result = job['previous_result']
            self.result = {'id':secrets.token_hex(12), 'revision':self.revision, 'text':text,
                'source':result['source_code'], 'target':result['target_code'],
                'model':result['model'], 'length':len(text), 'accepted':False,
                'receipt':{'original':job['text'], **result}}
            self.message, self.error = 'Translation ready. Review it beside the original.', False

    def _spoken(self, text):
        with self.lock:
            if not self.dictating or self.closed:
                return
            self.dictating = False
            if not isinstance(text, str) or not text.strip():
                self.message = 'No speech text arrived. Your passage is kept.'
                return
            combined = self.text + ('\n' if self.text and not self.text.endswith('\n') else '') + text
            if len(combined) > MAX_SOURCE:
                self.message, self.error = 'That recording would exceed 64,000 characters. Your current passage is kept; find the recording in Recovery.', True
                return
            self.text = combined
            self.revision += 1
            # The speech delivery callback still owns the dictation flight.
            # Let it release that flight before a later UI poll starts inference.
            self.auto_start = True
            self.message = 'Speech captured. Waiting for dictation to finish…'

    def stop_speech(self):
        self.auto_start = False
        if self.dictating:
            self.utility('speech_cancel', None)
            self.dictating = False
            self.message, self.error = 'Recording cancelled. Your passage is kept.', False

    def close(self):
        with self.lock:
            self.stop_speech()
            self.closed = True
            if self.job and self.job['kind'] in {'translate','check'}:
                self.job['cancel'].set()
