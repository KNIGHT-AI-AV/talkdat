"""Session-owned Ramble drafts, bounded text transfers and worker exports."""
from __future__ import annotations

import copy
import secrets
import threading
import time
from pathlib import Path

from knight_flow.ramble_export import PDF_TEMPLATES


class RambleWorkspace:
    CHUNK = 16_000
    MAX_TEXT = 1_000_000

    def __init__(self, config, utility, dispatch, launch=None):
        self.config, self.utility, self.dispatch = config, utility, dispatch
        self.launch = launch or self._launch
        self.lock = threading.RLock()
        self.text = self.original = ''
        self.original_id = ''
        self.revision = 0
        self.format, self.style = 'pdf', 'executive'
        self.pending = self.job = None
        self.recording = self.stopping = self.closed = False
        self.exports = []
        self.message, self.error = 'Choose a format, then record or add your draft.', False

    @staticmethod
    def _launch(work):
        threading.Thread(target=work, name='TalkDatRambleWorkspace', daemon=True).start()

    def _current(self, revision):
        if type(revision) is not int or revision != self.revision:
            raise ValueError('This draft changed elsewhere. Copy your edits before reopening Ramble.')

    @classmethod
    def _text(cls, value):
        if (type(value) is not str or len(value) > cls.MAX_TEXT or '\x00' in value
                or any(0xD800 <= ord(c) <= 0xDFFF for c in value)):
            raise ValueError('Use up to 1,000,000 characters without null or incomplete characters. Your draft is kept.')
        return value

    def _idle(self):
        if self.recording or self.job:
            raise ValueError('Finish the current recording or document operation first.')

    def snapshot(self, catalog=False):
        if self.recording and not self.utility('speech_active', None):
            self.utility('speech_cancel', None)
            self.recording = self.stopping = False
            self.message = 'Recording ended without new text. Your draft is kept; protected audio is available in Recovery.'
        result = dict(revision=self.revision, length=len(self.text), original_length=len(self.original), original_id=self.original_id,
            format=self.format, style=self.style, recording=self.recording, stopping=self.stopping,
            active=self.job is not None, kind=self.job['kind'] if self.job else '',
            cancelling=bool(self.job and self.job['cancel'].is_set()), message=self.message, error=self.error,
            exports=[{key:row[key] for key in ('id','name','revision','format')} for row in self.exports],
            limit=self.MAX_TEXT)
        if catalog:
            result.update(formats=[{'value':value,'label':label} for value,label in
                (('pdf','PDF'),('word','Word'),('markdown','Markdown'),('text','Plain text'))],
                styles=[{'value':key,'label':value['label'],
                    'paper':value['bg'] or (1,1,1),'ink':value['ink'],'accent':value['accent'],
                    'title_font':('monospace' if value['title_font'].startswith('Courier') else 'serif' if value['title_font'].startswith('Times') else 'sans-serif'),
                    'center':value['center_title'],'rule':value['rule'],'caps':value['caps_title'],
                    'title_size':value['title_size'],'margin':value['margin']} for key,value in PDF_TEMPLATES.items()],
                writing_ready=bool(self.utility('writing_ready',None)))
        return result

    def handle(self, payload):
        if type(payload) is not dict or type(payload.get('operation')) is not str:
            raise ValueError('That Ramble action is unavailable.')
        with self.lock:
            operation = payload['operation']
            if operation == 'open':
                self.closed = False
            elif self.closed:
                raise ValueError('Reopen Ramble before continuing.')
            if operation in {'open','status'}:
                return self.snapshot(operation == 'open')
            if operation == 'read':
                self._current(payload.get('revision'))
                offset, part = payload.get('offset',0), payload.get('part','draft')
                if type(offset) is not int or offset < 0 or part not in {'draft','original'}:
                    raise ValueError('Choose a valid draft position.')
                if part == 'original' and payload.get('id') != self.original_id:
                    raise ValueError('The original text changed. Refresh before reading it.')
                text = self.text if part == 'draft' else self.original
                end = min(len(text), offset + self.CHUNK)
                return {'text':text[offset:end], 'next':end if end < len(text) else None}
            if operation == 'begin_edit':
                self._current(payload.get('revision'))
                if self.recording or (self.job and self.job['kind'] == 'export'):
                    raise ValueError('Finish recording or saving before editing this draft.')
                token = secrets.token_hex(16)
                self.pending = dict(token=token, revision=self.revision, parts=[], length=0, updated=time.monotonic())
                return {'token':token}
            if operation in {'append_edit','commit_edit'}:
                pending = self.pending
                if not pending or payload.get('token') != pending['token'] or time.monotonic()-pending['updated'] > 120:
                    raise ValueError('The draft transfer expired. Your edits are still here. Try again.')
                self._current(pending['revision'])
                if operation == 'append_edit':
                    text, offset = self._text(payload.get('text')), payload.get('offset')
                    if type(offset) is not int or offset != pending['length'] or len(text) > self.CHUNK or pending['length']+len(text) > self.MAX_TEXT:
                        raise ValueError('The draft transfer is incomplete. Your earlier draft is kept.')
                    pending['parts'].append(text)
                    pending['length'] += len(text)
                    pending['updated'] = time.monotonic()
                    return {'offset':pending['length']}
                self._idle_for_edit()
                text = ''.join(pending['parts'])
                if text != self.text:
                    if self.job:
                        self.job['cancel'].set()
                    self.text = text
                    self.revision += 1
                self.pending = None
                self.message, self.error = 'Draft kept for this app session.', False
                return self.snapshot()
            if operation == 'options':
                format, style = payload.get('format'), payload.get('style')
                if type(format) is not str or format not in {'pdf','word','markdown','text'} or type(style) is not str or style not in PDF_TEMPLATES:
                    raise ValueError('Choose an available document format and style.')
                self._idle()
                self.format, self.style = format, style
                return self.snapshot()
            if operation == 'speech_start':
                self._current(payload.get('revision'))
                self._idle()
                self.recording = True
                try:
                    self.utility('speech_start', self._spoken)
                except Exception:
                    self.recording = False
                    raise
                self.message, self.error = 'Listening. Finish recording when your thought is complete.', False
                return self.snapshot()
            if operation == 'speech_stop':
                if self.recording and not self.stopping:
                    self.utility('speech_stop', None)
                    self.stopping = True
                    self.message = 'Finishing the recording. Your draft stays available here.'
                return self.snapshot()
            if operation == 'speech_cancel':
                self.utility('speech_cancel', None)
                self.recording = self.stopping = False
                self.message, self.error = 'Recording cancelled. Your previous draft is kept.', False
                return self.snapshot()
            if operation in {'finish','export'}:
                self._current(payload.get('revision'))
                return self.start(operation)
            if operation == 'cancel_finish':
                if self.job and self.job['kind'] == 'finish':
                    self.job['cancel'].set()
                    self.message = 'Finishing cancelled. Your draft is kept while the current request ends.'
                return self.snapshot()
            if operation == 'clear':
                self._current(payload.get('revision'))
                self._idle()
                if payload.get('confirmed') is not True:
                    raise ValueError('Confirm before clearing the draft and its original text.')
                self.text = self.original = ''
                self.original_id = ''
                self.pending = None
                self.revision += 1
                self.message, self.error = 'Draft cleared. Saved documents are kept.', False
                return self.snapshot()
            if operation == 'restore_original':
                self._current(payload.get('revision'))
                self._idle()
                if self.original:
                    self.text = self.original
                    self.revision += 1
                    self.message, self.error = 'Original text restored. You can edit or save it.', False
                return self.snapshot()
            if operation == 'copy':
                self._current(payload.get('revision'))
                part = payload.get('part','draft')
                if part not in {'draft','original'}:
                    raise ValueError('Choose the draft or original text.')
                if part == 'original' and payload.get('id') != self.original_id:
                    raise ValueError('The original text changed. Refresh before copying it.')
                text = self.text if part == 'draft' else self.original
                if not text:
                    raise ValueError('Add or record text before copying.')
                self.utility('copy', text)
                return {'message':'Text copied. Return to your destination and paste it.'}
            if operation in {'open_export','show_folder'}:
                row = next((row for row in self.exports if row['id'] == payload.get('id')), None)
                if row is None:
                    raise ValueError('Choose a document saved in this Ramble session.')
                self.utility('open', row['path'] if operation == 'open_export' else row['path'].parent)
                return {'message':'Opened the saved document.' if operation == 'open_export' else 'Opened the document folder.'}
            raise ValueError('That Ramble action is unavailable.')

    def _idle_for_edit(self):
        if self.recording or (self.job and self.job['kind'] == 'export'):
            raise ValueError('Finish recording or saving before editing this draft.')

    def _spoken(self, text):
        with self.lock:
            if self.closed or not self.recording:
                return
            self.recording = self.stopping = False
            text = self._text(text)
            if not text.strip():
                self.message = 'No new words were captured. Your draft is kept.'
                return
            joined = self.text + ('\n\n' if self.text else '') + text
            # Never discard a new recording because the existing editor is full.
            # Keep it as the original and leave the prior draft available to save.
            if len(joined) > self.MAX_TEXT:
                self.original = text
                self.original_id = secrets.token_hex(12)
                self.revision += 1
                self.message, self.error = 'The combined draft is too large. Your new recording is in Original text; copy or restore it after saving this draft.', True
                return
            self.text = joined
            self.original = joined
            self.original_id = secrets.token_hex(12)
            self.revision += 1
            self.message, self.error = 'Recording captured. Review your words, finish the writing, or save now.', False

    def start(self, kind):
        self._idle()
        if not self.text.strip():
            raise ValueError('Add or record a draft before continuing.')
        if kind == 'finish':
            self.utility('finish_available',None)
            self.original = self.text
            self.original_id = secrets.token_hex(12)
        job = dict(id=secrets.token_hex(12), kind=kind, revision=self.revision,
            text=self.text, config=copy.deepcopy(self.config),
            format=('pdf:'+self.style if self.format == 'pdf' else self.format), cancel=threading.Event())
        self.job = job
        self.message, self.error = ('Finishing your writing…' if kind == 'finish' else 'Saving your document…'), False

        def work():
            value, error = None, None
            try:
                value = self.utility(kind, job)
            except Exception as failure:
                error = str(failure)
            self.dispatch(lambda: self._complete(job, value, error))

        try:
            self.launch(work)
        except Exception:
            self.job = None
            raise
        return self.snapshot()

    def _complete(self, job, value, error):
        with self.lock:
            if self.job is not job:
                return
            self.job = None
            if self.closed:
                return
            if job['cancel'].is_set() or job['revision'] != self.revision:
                self.message, self.error = 'Earlier finishing stopped. Your current draft is kept.', False
                return
            if error:
                self.message, self.error = f'{error} Your draft and original text are still here.', True
                return
            if job['kind'] == 'finish':
                try:
                    text = self._text(value)
                    if not text.strip():
                        raise ValueError('The writing model returned no text.')
                except ValueError as failure:
                    self.message, self.error = f'{failure} Your original draft is kept.', True
                    return
                self.text = text
                self.revision += 1
                self.message, self.error = 'Writing finished. Review or edit it before saving.', False
            else:
                path = Path(value)
                self.exports.insert(0, dict(id=job['id'], name=path.name, path=path,
                    revision=job['revision'], format=job['format']))
                self.exports = self.exports[:10]
                self.message, self.error = f'Saved {path.name}.', False

    def close(self):
        with self.lock:
            self.utility('speech_cancel',None)
            self.recording = self.stopping = False
            self.closed = True
            if self.job:
                self.job['cancel'].set()
