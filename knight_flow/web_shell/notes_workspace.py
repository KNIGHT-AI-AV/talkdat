"""Revision-aware local notes. A save replaces one note in the latest document."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import secrets
import threading
import time


class NotesConflict(ValueError):
    """The saved note changed while this draft was being written."""


class NotesWorkspace:
    CHUNK = 16000
    MAX_TEXT = 1_000_000

    def __init__(self, path, legacy_path, copy_text, *, import_file=None, export_file=None, fonts=None, set_font=None):
        self.path, self.legacy_path = Path(path), Path(legacy_path)
        self.copy_text = copy_text
        self.lock = threading.RLock()
        self.pending = None
        self.import_file, self.export_file = import_file, export_file
        self.fonts, self.set_font = fonts, set_font

    @staticmethod
    def now():
        return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())

    @classmethod
    def new_note(cls, title='Untitled', text=''):
        stamp = cls.now()
        return {'id': 'note-' + secrets.token_hex(12), 'title': title, 'text': text,
                'created_at': stamp, 'updated_at': stamp}

    @staticmethod
    def revision(note):
        value = json.dumps([note.get('title', ''), note.get('text', '')], ensure_ascii=True)
        return hashlib.sha256(value.encode()).hexdigest()

    def load(self):
        if not self.path.exists():
            text = self.legacy_path.read_text(encoding='utf-8') if self.legacy_path.exists() else ''
            # Stable until the first mutation, without writing just to open a page.
            note = self.new_note('Note 1', text)
            note['id'] = 'note-legacy'
            return {'version': 1, 'last_tab_id': note['id'], 'tabs': [note]}
        try:
            document = json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ValueError('Your notes could not be read. The saved file has not been changed.') from error
        if (type(document) is not dict or type(document.get('tabs')) is not list
                or not document['tabs'] or len(document['tabs']) > 99):
            raise ValueError('Your notes need recovery. The saved file has not been changed.')
        ids = set()
        for note in document['tabs']:
            if (type(note) is not dict or type(note.get('id')) is not str or not note['id']
                    or note['id'] in ids or type(note.get('text')) is not str
                    or type(note.get('title')) is not str):
                raise ValueError('Your notes need recovery. The saved file has not been changed.')
            ids.add(note['id'])
        return document

    def write(self, document):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + '.' + secrets.token_hex(8) + '.tmp')
        try:
            with temporary.open('x', encoding='utf-8', newline='\n') as output:
                json.dump(document, output, ensure_ascii=False, indent=2)
                output.flush()
                os.fsync(output.fileno())
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def find(document, identifier):
        if type(identifier) is not str:
            raise ValueError('Choose a saved note.')
        for note in document['tabs']:
            if note['id'] == identifier:
                return note
        raise NotesConflict('This note changed or was removed elsewhere. Your draft is still here. Save a copy to keep it.')

    def metadata(self, note):
        return {key: note.get(key, '') for key in ('id', 'title', 'created_at', 'updated_at')} | {
            'revision': self.revision(note), 'preview': note['text'][:180],
            'characters': len(note['text']), 'editable': len(note['text']) <= self.MAX_TEXT}

    @staticmethod
    def require(payload, keys):
        if set(payload) != {'operation', *keys}:
            raise ValueError('That note action is unavailable.')

    def handle(self, payload):
        if type(payload) is not dict:
            raise ValueError('That note action is unavailable.')
        with self.lock:
            return self._handle(payload)

    def _handle(self, payload):
        operation = payload.get('operation')
        if operation == 'list':
            if set(payload) not in ({'operation'}, {'operation', 'query'}):
                raise ValueError('That note action is unavailable.')
            query=payload.get('query','')
            if type(query) is not str or len(query)>256:raise ValueError('Enter a shorter search.')
            document = self.load()
            result={'notes': [self.metadata(note) for note in document['tabs']
                             if query.casefold() in (note['title']+' '+note['text']).casefold()],
                    'selected': document.get('last_tab_id'), 'total':len(document['tabs'])}
            if self.fonts is not None:result['fonts']=self.fonts()
            return result
        if operation == 'font':
            self.require(payload,['family'])
            if self.fonts is None or self.set_font is None or payload['family'] not in self.fonts()['available']:
                raise ValueError('Choose an available font.')
            self.set_font(payload['family'])
            return {'message':'Note font saved.'}
        if operation == 'import':
            self.require(payload,[])
            if self.import_file is None:raise ValueError('File import is unavailable.')
            if len(self.load()['tabs'])>=99:raise ValueError('Scratchpad holds up to 99 notes.')
            imported=self.import_file()
            if imported is None:return {'cancelled':True}
            title,text=imported
            # Re-read after the file picker: another surface may have saved meanwhile.
            document=self.load()
            if len(document['tabs'])>=99:raise ValueError('Scratchpad is full. The imported file has not been changed.')
            note=self.new_note(str(title)[:64] or 'Imported note',str(text))
            document['tabs'].append(note);document['last_tab_id']=note['id'];self.write(document)
            return self.metadata(note)
        if operation == 'export':
            self.require(payload,['id','format'])
            if self.export_file is None or payload['format'] not in {'txt','md'}:
                raise ValueError('Choose a text or Markdown export.')
            note=self.find(self.load(),payload['id'])
            name=self.export_file(note['title'],note['text'],payload['format'])
            return {'cancelled':name is None,'message':f'Exported {name}.' if name else ''}
        if operation in {'read', 'copy', 'delete'}:
            keys = ['id'] + (['offset', 'revision'] if operation == 'read' else ['revision'] if operation == 'delete' else [])
            self.require(payload, keys)
            document = self.load()
            note = self.find(document, payload['id'])
            if operation in {'read', 'delete'} and payload['revision'] != self.revision(note):
                raise NotesConflict('This note changed elsewhere. Your draft is still here. Save a copy to keep both versions.')
            if operation == 'read':
                offset = payload['offset']
                if type(offset) is not int or offset < 0 or offset > len(note['text']):
                    raise ValueError('That note section is unavailable.')
                end = min(len(note['text']), offset + self.CHUNK)
                return self.metadata(note) | {'text': note['text'][offset:end], 'next': end if end < len(note['text']) else None}
            if operation == 'copy':
                self.copy_text(note['text'])
                return {'message': 'Copied the full note.'}
            document['tabs'].remove(note)
            if not document['tabs']: document['tabs'].append(self.new_note('Note 1'))
            if document.get('last_tab_id') == note['id']: document['last_tab_id'] = document['tabs'][0]['id']
            self.write(document)
            return {'message': 'Note deleted.'}
        if operation == 'new':
            self.require(payload, [])
            document = self.load()
            if len(document['tabs']) >= 99: raise ValueError('Scratchpad holds up to 99 notes. Export or remove a note before adding another.')
            note = self.new_note('Note ' + str(len(document['tabs']) + 1))
            document['tabs'].append(note)
            document['last_tab_id'] = note['id']
            self.write(document)
            return self.metadata(note)
        if operation == 'begin_save':
            self.require(payload, ['id', 'revision', 'title', 'as_copy'])
            title, as_copy = payload['title'], payload['as_copy']
            if type(title) is not str or len(title) > 64 or '\0' in title or type(as_copy) is not bool:
                raise ValueError('Give this note a title of at most 64 characters.')
            document = self.load()
            if as_copy:
                if len(document['tabs']) >= 99: raise ValueError('Scratchpad is full. Your draft is still here.')
            else:
                note = self.find(document, payload['id'])
                if self.revision(note) != payload['revision']:
                    raise NotesConflict('This note changed elsewhere. Your draft is still here. Save a copy to keep both versions.')
            token = secrets.token_hex(16)
            self.pending = {'token': token, 'request': copy.deepcopy(payload), 'parts': [], 'length': 0,
                            'updated': time.monotonic()}
            return {'token': token}
        if operation in {'append_save', 'finish_save', 'cancel_save'}:
            self.require(payload, ['token'] + (['offset', 'text'] if operation == 'append_save' else []))
            pending = self.pending
            if pending is None or pending['token'] != payload['token'] or time.monotonic() - pending['updated'] > 120:
                raise ValueError('The save expired. Your draft is still here. Try Save again.')
            if operation == 'cancel_save':
                self.pending = None
                return {}
            if operation == 'append_save':
                text, offset = payload['text'], payload['offset']
                if (type(text) is not str or len(text) > self.CHUNK or type(offset) is not int
                        or offset != pending['length'] or pending['length'] + len(text) > self.MAX_TEXT):
                    raise ValueError('This note could not be saved. Your draft is still here.')
                pending['parts'].append(text)
                pending['length'] += len(text)
                pending['updated'] = time.monotonic()
                return {'offset': pending['length']}
            document = self.load()
            request = pending['request']
            if request['as_copy']:
                if len(document['tabs']) >= 99: raise ValueError('Scratchpad is full. Your draft is still here.')
                note = self.new_note()
                document['tabs'].append(note)
            else:
                note = self.find(document, request['id'])
                if self.revision(note) != request['revision']:
                    raise NotesConflict('This note changed while saving. Your draft is still here. Save a copy to keep both versions.')
            note['title'] = request['title'].strip() or 'Untitled'
            note['text'] = ''.join(pending['parts'])
            note['updated_at'] = self.now()
            document['last_tab_id'] = note['id']
            self.write(document)
            self.pending = None
            return self.metadata(note) | {'message': 'Saved on this computer.'}
        raise ValueError('That note action is unavailable.')
