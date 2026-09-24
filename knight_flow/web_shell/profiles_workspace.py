"""Local app preferences with explicit inheritance and revision-safe edits."""
from __future__ import annotations
import copy
import hashlib
import hmac
import json
import re
import secrets

from knight_flow.config import _SAVE_LOCK
from knight_flow.style_profile import render_instruction


class ProfilesWorkspace:
    MAX_PROFILES = 100
    FIELDS = {'match', 'enabled', 'cleanup_level', 'tone', 'language', 'auto_enter'}
    LEVELS = ('', 'none', 'light', 'medium', 'high')
    TONES = (('', 'Use default'), ('formal', 'Formal'), ('friendly', 'Friendly'), ('concise', 'Concise'))
    LANGUAGES = (('', 'Use default'), ('en-US', 'English (US)'), ('en-GB', 'English (UK)'),
                 ('es', 'Spanish'), ('fr', 'French'), ('de', 'German'), ('pt', 'Portuguese'),
                 ('it', 'Italian'), ('nl', 'Dutch'), ('pl', 'Polish'), ('uk', 'Ukrainian'),
                 ('ja', 'Japanese'), ('ko', 'Korean'), ('zh', 'Chinese'), ('hi', 'Hindi'),
                 ('ar', 'Arabic'), ('ru', 'Russian'), ('tr', 'Turkish'), ('vi', 'Vietnamese'))

    def __init__(self, config, persist):
        self.config, self.persist = config, persist
        self.key = secrets.token_bytes(32)

    def sign(self, value):
        encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(',', ':')).encode()
        return hmac.new(self.key, encoded, hashlib.sha256).hexdigest()

    def data(self):
        data = self.config.get('profiles', [])
        if type(data) is not list:
            raise ValueError('Your app preferences need recovery. Keep a backup before changing them.')
        return data

    def revision(self):
        return self.sign(self.data())

    def rows(self):
        for index, value in enumerate(self.data()[:self.MAX_PROFILES]):
            if type(value) is not dict or type(value.get('match')) is not str or not value['match'].strip():
                continue
            if any(type(value.get(key, '')) is not str or len(value.get(key, '')) > limit
                   for key, limit in [('match', 128), ('cleanup_level', 16), ('tone', 128), ('language', 64)]):
                continue
            record = {key: value.get(key, '') for key in ('match', 'cleanup_level', 'tone', 'language')}
            record['enabled'] = value.get('enabled', True) is True
            record['auto_enter'] = value.get('auto_enter') if type(value.get('auto_enter')) is bool else None
            yield {'id': self.sign([index, value])[:24], 'index': index, 'record': record, 'original': value}

    @staticmethod
    def require(payload, fields):
        if set(payload) != {'operation', *fields}:
            raise ValueError('That app-preference action is unavailable.')

    def find(self, identifier):
        if type(identifier) is str:
            for row in self.rows():
                if row['id'] == identifier:
                    return row
        raise ValueError('This app preference changed. Refresh the list before editing it.')

    def validate(self, record, original=None):
        if type(record) is not dict or set(record) != self.FIELDS:
            raise ValueError('Complete the app-preference fields before saving.')
        result = {}
        for key, limit in [('match', 128), ('cleanup_level', 16), ('tone', 128), ('language', 64)]:
            value = record[key]
            if type(value) is not str or len(value) > limit or any(ord(c) < 32 for c in value):
                raise ValueError('Use a short app name and valid preference values.')
            result[key] = value.strip()
        if not result['match']:
            raise ValueError('Enter part of the app name, such as Slack or Chrome.')
        if result['cleanup_level'] not in self.LEVELS:
            if not original or record['cleanup_level'] != original.get('cleanup_level'):
                raise ValueError('Choose an available formatting level.')
        language = result['language']
        if language and not re.fullmatch(r'[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*', language):
            if not original or record['language'] != original.get('language'):
                raise ValueError('Choose an available language hint.')
        if type(record['enabled']) is not bool or (record['auto_enter'] is not None and type(record['auto_enter']) is not bool):
            raise ValueError('Choose whether this preference and the spoken Enter command are enabled.')
        result['enabled'] = record['enabled']
        if record['auto_enter'] is not None:
            result['auto_enter'] = record['auto_enter']
        return result

    def save_profiles(self, profiles):
        candidate = copy.deepcopy(self.config)
        candidate['profiles'] = profiles
        try:
            self.persist(candidate)
        except OSError as error:
            raise ValueError('App preferences could not be saved. Your draft is still here; try Save again.') from error
        self.config['profiles'] = profiles
        return {'revision': self.revision(), 'message': 'Saved. It applies to your next dictation.'}

    def handle(self, payload):
        if type(payload) is not dict:
            raise ValueError('That app-preference action is unavailable.')
        with _SAVE_LOCK:
            return self._handle(payload)

    def _handle(self, payload):
        operation = payload.get('operation')
        if operation == 'list':
            self.require(payload, set())
            rows = list(self.rows())
            return {'revision': self.revision(), 'entries': [
                {'id': row['id'], 'position': row['index'] + 1, 'record': row['record'],
                 'can_up': row['index'] > 0, 'can_down': row['index'] < min(len(self.data()), self.MAX_PROFILES) - 1}
                for row in rows], 'uneditable': len(self.data()) - len(rows),
                'can_add': len(self.data()) < self.MAX_PROFILES,
                'tones': [{'value': v, 'label': label} for v, label in self.TONES],
                'languages': [{'value': v, 'label': label} for v, label in self.LANGUAGES]}
        if operation in ('put', 'delete', 'move'):
            self.require(payload, {'id', 'revision', 'record'} if operation == 'put' else
                         {'id', 'revision', 'confirmed'} if operation == 'delete' else {'id', 'revision', 'direction'})
            if payload['revision'] != self.revision():
                raise ValueError('App preferences changed elsewhere. Your draft is still here; refresh before saving.')
            if type(payload['id']) is not str:
                raise ValueError('Choose an app preference.')
            row = self.find(payload['id']) if payload['id'] else None
            profiles = copy.deepcopy(self.data())
            if operation == 'put':
                record = self.validate(payload['record'], row['original'] if row else None)
                if any(type(other) is dict and type(other.get('match')) is str and other['match'].strip().casefold() == record['match'].casefold()
                       for index, other in enumerate(profiles) if row is None or index != row['index']):
                    raise ValueError('That app already has a preference. Edit its existing entry.')
                if row is None:
                    if len(profiles) >= self.MAX_PROFILES:
                        raise ValueError('Keep up to 100 app preferences. Remove an unused one before adding another.')
                    index = len(profiles); profiles.append(record)
                else:
                    index = row['index']
                    profiles[index] = {key: value for key, value in profiles[index].items() if key not in self.FIELDS}
                    profiles[index].update(record)
            elif operation == 'delete':
                if row is None or payload['confirmed'] is not True:
                    raise ValueError('Confirm which app preference to remove.')
                profiles.pop(row['index'])
            else:
                if row is None or payload['direction'] not in ('up', 'down'):
                    raise ValueError('Choose where to move this app preference.')
                index = row['index'] + (-1 if payload['direction'] == 'up' else 1)
                if not 0 <= index < min(len(profiles), self.MAX_PROFILES):
                    raise ValueError('This app preference is already at the end of the list.')
                profiles[row['index']], profiles[index] = profiles[index], profiles[row['index']]
            result = self.save_profiles(profiles)
            if operation in ('put', 'move'):
                updated = next(row for row in self.rows() if row['index'] == index)
                result.update(id=updated['id'], record=updated['record'])
            return result
        if operation == 'style':
            self.require(payload, set())
            value = self.config.get('style_profile', {})
            from knight_flow.style_profile import _normalised
            counts = _normalised(value)
            return {'revision': self.sign(value), 'votes': counts['votes'], 'ready': bool(render_instruction(value))}
        if operation == 'reset_style':
            self.require(payload, {'revision', 'confirmed'})
            if payload['confirmed'] is not True:
                raise ValueError('Confirm that you want to clear the learned style counts.')
            if payload['revision'] != self.sign(self.config.get('style_profile', {})):
                raise ValueError('The style counts changed. Review them again before clearing.')
            candidate = copy.deepcopy(self.config); candidate['style_profile'] = {}
            try:
                self.persist(candidate)
            except OSError as error:
                raise ValueError('Style counts could not be cleared. The previous counts are still saved; try again.') from error
            self.config['style_profile'] = {}
            return {'message': 'Style counts cleared. New saved text can build them again.'}
        raise ValueError('That app-preference action is unavailable.')
