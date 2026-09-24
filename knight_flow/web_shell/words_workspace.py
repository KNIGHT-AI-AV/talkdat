"""Typed, revision-aware editors for the existing local vocabulary collections."""
from __future__ import annotations
import copy
import hashlib
import hmac
import json
import secrets
import time

from knight_flow.config import _SAVE_LOCK


class WordsWorkspace:
    PAGE_SIZE = 40
    MAX_ENTRIES = 5000
    MAX_TEXT = 32000

    def __init__(self, config, persist, applied=lambda: None, utility=None):
        self.config, self.persist, self.applied, self.utility = config, persist, applied, utility
        self.key = secrets.token_bytes(32)
        self.pending_pack = None

    def data(self):
        dictionary = self.config.get('dictionary', {})
        result = {name: dictionary.get(name, []) for name in ('words', 'terms', 'replacements')}
        result['snippets'] = self.config.get('snippets', [])
        if any(type(value) is not list for value in result.values()):
            raise ValueError('A vocabulary collection needs recovery. Export a backup before editing it.')
        return result

    def sign(self, data):
        encoded = json.dumps(data, ensure_ascii=True, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
        return hmac.new(self.key, encoded, hashlib.sha256).hexdigest()

    def revision(self):
        dictionary = self.config.get('dictionary', {})
        return self.sign([self.data(), dictionary.get('auto_learn', True), dictionary.get('auto_learn_mode', 'auto-on-second')])

    @staticmethod
    def collection(value):
        if value not in ('vocabulary', 'replacements', 'snippets'):
            raise ValueError('Choose Words, Replacements or Snippets.')
        return value

    def rows(self, collection):
        data = self.data()
        keys = ('words', 'terms') if collection == 'vocabulary' else (collection,)
        for key in keys:
            for index, original in enumerate(data[key]):
                if key == 'words' and type(original) is str:
                    record = {'text': original, 'sounds_like': []}
                elif type(original) is dict:
                    if key == 'terms' and type(original.get('text')) is str:
                        aliases = original.get('sounds_like', [])
                        if type(aliases) is str: aliases = [aliases]
                        if type(aliases) is not list or any(type(alias) is not str for alias in aliases): continue
                        record = {'text': original['text'], 'sounds_like': aliases}
                    elif key == 'replacements' and type(original.get('from')) is str and type(original.get('to')) is str:
                        record = {'from': original['from'], 'to': original['to']}
                    elif key == 'snippets' and type(original.get('trigger')) is str and type(original.get('text')) is str:
                        record = {'trigger': original['trigger'], 'text': original['text'], 'enabled': bool(original.get('enabled', True))}
                    else: continue
                else: continue
                label = record.get('trigger', record.get('from', record.get('text', '')))
                detail = ', '.join(record['sounds_like']) if key in ('words', 'terms') else record.get('to', record.get('text', ''))
                yield {'id': self.sign([key, index, original])[:24], 'label': label[:512], 'detail': detail[:160],
                       'learned': bool(type(original) is dict and original.get('learned')),
                       'enabled': record.get('enabled', True), 'key': key, 'index': index,
                       'record': record, 'original': original}

    @staticmethod
    def require(payload, fields):
        if set(payload) != {'operation', *fields}:
            raise ValueError('That vocabulary action is unavailable.')

    @staticmethod
    def text(value, label, limit, *, empty=False):
        if type(value) is not str or '\x00' in value or len(value) > limit or (not empty and not value.strip()):
            raise ValueError(f'{label}: enter valid text up to {limit} characters.')
        return value

    def validate(self, collection, record):
        if type(record) is not dict:
            raise ValueError('Complete the fields before saving.')
        expected = {'text', 'sounds_like'} if collection == 'vocabulary' else {'from', 'to'} if collection == 'replacements' else {'trigger', 'text', 'enabled'}
        if set(record) != expected:
            raise ValueError('Complete the fields before saving.')
        if collection == 'vocabulary':
            text = self.text(record['text'], 'Word or phrase', 512).strip()
            aliases = record['sounds_like']
            if type(aliases) is not list or len(aliases) > 8:
                raise ValueError('Add up to eight sounds-like spellings.')
            return {'text': text, 'sounds_like': list(dict.fromkeys(self.text(alias, 'Sounds like', 512).strip() for alias in aliases))}
        if collection == 'replacements':
            return {'from': self.text(record['from'], 'Heard as', 512).strip(), 'to': self.text(record['to'], 'Replace with', self.MAX_TEXT, empty=True)}
        if type(record['enabled']) is not bool:
            raise ValueError('Choose whether the snippet is enabled.')
        return {'trigger': self.text(record['trigger'], 'Spoken trigger', 512).strip(),
                'text': self.text(record['text'], 'Saved text', self.MAX_TEXT), 'enabled': record['enabled']}

    def find(self, collection, identifier):
        if type(identifier) is not str:
            raise ValueError('Choose a saved entry.')
        for row in self.rows(collection):
            if row['id'] == identifier: return row
        raise ValueError('This entry changed elsewhere. Your draft is still here; refresh the list before saving.')

    def save(self, candidate):
        self.persist(candidate)
        self.config.clear(); self.config.update(candidate)
        message = 'Saved. It applies to your next dictation.'
        try: self.applied()
        except Exception: message = 'Saved. Restart Talk DAT to apply the remaining changes.'
        return {'revision': self.revision(), 'message': message}

    def handle(self, payload):
        if type(payload) is not dict: raise ValueError('That vocabulary action is unavailable.')
        with _SAVE_LOCK:
            return self._handle(payload)

    def _handle(self, payload):
        operation = payload.get('operation')
        if operation == 'options':
            self.require(payload, set())
            from knight_flow.learned_words import auto_learn_mode
            return {'mode':auto_learn_mode(self.config), 'revision':self.revision(),
                    'packs':[{'id':name,'label':name.title()} for name in ('medical','legal','aviation','military')]}
        if operation == 'learning':
            self.require(payload, {'mode','revision'})
            if payload['revision'] != self.revision(): raise ValueError('Your vocabulary changed. Refresh before changing learning.')
            if payload['mode'] not in ('off','offer','auto-on-second'): raise ValueError('Choose an available learning option.')
            candidate = copy.deepcopy(self.config)
            dictionary = candidate.setdefault('dictionary', {})
            dictionary.update(auto_learn=payload['mode']!='off', auto_learn_mode=payload['mode'])
            return self.save(candidate)
        if operation == 'suggestions':
            self.require(payload, set())
            from knight_flow.learned_words import tombstoned
            values = self.utility('suggestions', [row['label'] for row in self.rows('vocabulary')])
            return {'words':[word for word in values if not tombstoned(word,self.config)], 'revision':self.revision()}
        if operation == 'export':
            self.require(payload, set())
            return self.utility('export', copy.deepcopy(self.config))
        if operation == 'pack_preview':
            self.require(payload, {'source'})
            if payload['source'] not in ('file','medical','legal','aviation','military'):
                raise ValueError('Choose an available vocabulary pack.')
            revision = self.revision()
            result = self.utility('import', payload['source'])
            if result is None: self.pending_pack=None; return {'cancelled':True}
            if self.revision() != revision:
                self.pending_pack=None
                raise ValueError('Your vocabulary changed while choosing the pack. Preview it again.')
            candidate, counts = result
            token = secrets.token_urlsafe(24)
            self.pending_pack = (token, revision, time.monotonic(), candidate)
            return {'token':token, 'counts':counts}
        if operation == 'pack_cancel':
            self.require(payload, set()); self.pending_pack=None; return {}
        if operation == 'pack_apply':
            self.require(payload, {'token','confirmed'})
            pending = self.pending_pack
            if not pending or payload['token'] != pending[0] or payload['confirmed'] is not True:
                raise ValueError('Preview a vocabulary pack before adding it.')
            if not 0 <= time.monotonic()-pending[2] <= 300 or pending[1] != self.revision():
                self.pending_pack=None
                raise ValueError('Your vocabulary changed or the preview expired. Preview the pack again.')
            # The staged candidate holds vocabulary only; preserve unrelated
            # configuration that may have changed since the file picker closed.
            candidate = copy.deepcopy(self.config)
            for key in ('words','terms','replacements'):
                candidate.setdefault('dictionary', {})[key] = copy.deepcopy(pending[3]['dictionary'][key])
            candidate['snippets'] = copy.deepcopy(pending[3]['snippets'])
            result = self.save(candidate); self.pending_pack=None; return result
        if operation in ('practice_start','practice_status','practice_cancel'):
            self.require(payload, {'id','revision'} if operation == 'practice_start' else set())
            if operation == 'practice_start':
                if payload['revision'] != self.revision(): raise ValueError('Refresh your saved word before pronunciation practice.')
                row = self.find('vocabulary',payload['id'])
                return self.utility(operation,row['record']['text'])
            return self.utility(operation,None)
        if operation == 'list':
            self.require(payload, {'collection', 'query', 'offset'})
            collection = self.collection(payload['collection'])
            query = self.text(payload['query'], 'Search', 256, empty=True).strip().casefold()
            offset = payload['offset']
            if type(offset) is not int or offset < 0: raise ValueError('Choose an available page.')
            all_rows = list(self.rows(collection))
            rows = [row for row in all_rows if query in json.dumps(row['record'], ensure_ascii=False).casefold()]
            page = rows[offset:offset + self.PAGE_SIZE]
            keys = ('words','terms') if collection == 'vocabulary' else (collection,)
            skipped = sum(len(self.data()[key]) for key in keys) - len(all_rows)
            return {'revision': self.revision(), 'entries': [{key: row[key] for key in ('id','label','detail','learned','enabled')} for row in page],
                    'total': len(rows), 'offset': offset, 'next': offset + len(page) if offset + len(page) < len(rows) else None,
                    'uneditable': skipped}
        if operation == 'read':
            self.require(payload, {'collection', 'id', 'revision'})
            if payload['revision'] != self.revision(): raise ValueError('Your vocabulary changed. Refresh the list to open the latest entry.')
            row = self.find(self.collection(payload['collection']), payload['id'])
            if len(json.dumps(row['record'], ensure_ascii=True)) > 240000:
                raise ValueError('This entry is too large for this editor. Export your vocabulary pack to keep its full text.')
            return {'record': copy.deepcopy(row['record']), 'revision': self.revision(), 'id': row['id']}
        if operation in ('put', 'delete'):
            self.require(payload, {'collection','id','revision','record'} if operation == 'put' else {'collection','id','revision','confirmed'})
            collection = self.collection(payload['collection'])
            if payload['revision'] != self.revision(): raise ValueError('Your vocabulary changed elsewhere. Your draft is still here; refresh before saving.')
            row = self.find(collection, payload['id']) if payload['id'] else None
            candidate = copy.deepcopy(self.config)
            dictionary = candidate.setdefault('dictionary', {})
            if operation == 'delete':
                if row is None or payload['confirmed'] is not True: raise ValueError('Confirm which entry you want to remove.')
                target = candidate if row['key'] == 'snippets' else dictionary
                target[row['key']].pop(row['index'])
                if collection == 'vocabulary':
                    from knight_flow.learned_words import add_tombstone
                    add_tombstone(row['record']['text'], candidate)
            else:
                record = self.validate(collection, payload['record'])
                label = record.get('trigger', record.get('from', record.get('text')))
                renamed = row is None or row['label'].strip().casefold() != label.strip().casefold()
                if renamed and any(other['id'] != payload['id'] and other['label'].strip().casefold() == label.strip().casefold() for other in self.rows(collection)):
                    raise ValueError('That entry already exists. Select it to edit its saved text.')
                if row is None and len(list(self.rows(collection))) >= self.MAX_ENTRIES:
                    raise ValueError('This collection is full. Remove an unused entry before adding another.')
                key = row['key'] if row else 'terms' if collection == 'vocabulary' else collection
                target = candidate if key == 'snippets' else dictionary
                if key == 'words' and record['sounds_like']:
                    target[key].pop(row['index']); key = 'terms'; row = None
                entry = record['text'] if key == 'words' else {**(row['original'] if row and type(row['original']) is dict else {}), **record}
                if row:
                    saved_index = row['index']; target[key][saved_index] = entry
                else:
                    target.setdefault(key, []).append(entry); saved_index = len(target[key]) - 1
                if collection == 'vocabulary':
                    # A deliberate hand-add overrides a previous dismissal.
                    dictionary['learn_tombstones'] = [term for term in dictionary.get('learn_tombstones', []) if str(term).casefold() != record['text'].casefold()]
            result = self.save(candidate)
            if operation == 'put':
                saved = next(saved for saved in self.rows(collection) if saved['key'] == key and saved['index'] == saved_index)
                result['id'] = saved['id']
                result['record'] = copy.deepcopy(saved['record'])
            return result
        raise ValueError('That vocabulary action is unavailable.')
