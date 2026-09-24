"""Typed settings boundary shared by the native host and its web renderer.

No Tk or webview imports. A snapshot contains only explicitly listed fields.
Validation completes before any persistence or in-memory change.
"""
from __future__ import annotations
import copy
import hashlib
import hmac
import json
import math
import re
import secrets
import threading


class SettingsConflict(ValueError):
    pass


def _value(config, field):
    if field['type'] == 'secret':
        return ''
    current = config
    for part in field['id'].split('.'):
        if not isinstance(current, dict) or part not in current:
            current = copy.deepcopy(field.get('default'))
            break
        current = current[part]
    codec = field.get('codec')
    if field['type'] == 'hotkey':
        return copy.deepcopy(current if isinstance(current, list) else field.get('default', []))
    if codec in ('json-list', 'json-object'):
        return json.dumps(current if current is not None else ([] if codec == 'json-list' else {}), ensure_ascii=False, indent=2, allow_nan=False)
    if codec == 'words':
        return '\n'.join(str(word) for word in current or [])
    if codec == 'hotkey':
        return '; '.join('+'.join(chord) for chord in current or [])
    if codec == 'endpointing':
        return 'false' if current is False else str(current if current is not None else 300)
    # Only the scalar field types supported by this boundary may leave it.
    if current is None or isinstance(current, (str, bool, int)):
        return current
    if isinstance(current, float) and math.isfinite(current):
        return current
    return copy.deepcopy(field.get('default'))


def validate_value(field, value):
    kind = field['type']
    label = field['label']
    if kind == 'hotkey':
        from knight_flow.hotkeys import ALIASES
        named = {'ctrl','alt','shift','cmd','fn','alt_gr','space','esc','enter','tab','backspace','delete',
                 'home','end','page_up','page_down','left','right','up','down','insert','caps_lock',
                 'num_lock','scroll_lock','print_screen','pause','menu','mouse4','mouse5','middle'}
        if not isinstance(value, list) or len(value) > 8:
            raise ValueError(f'{label}: record up to eight shortcuts.')
        result = []
        for chord in value:
            if not isinstance(chord, list) or not 1 <= len(chord) <= 8:
                raise ValueError(f'{label}: record a valid key combination.')
            normalized = []
            for key in chord:
                if not isinstance(key, str):
                    raise ValueError(f'{label}: record a valid key.')
                key = ALIASES.get(key.lower(), key.lower())
                valid = (key in named or (len(key) == 1 and key.isprintable() and not key.isspace())
                         or re.fullmatch(r'f(?:[1-9]|1[0-9]|2[0-4])', key)
                         or re.fullmatch(r'pad_(?:a|b|x|y|lb|rb|back|start|ls|rs|up|down|left|right)', key)
                         or re.fullmatch(r'midi_note_(?:[0-9]|[1-9][0-9]|1[01][0-9]|12[0-7])', key))
                if not valid:
                    raise ValueError(f'{label}: record a supported keyboard, mouse or controller key.')
                if key not in normalized:
                    normalized.append(key)
            result.append(normalized)
        return result
    if kind == 'secret':
        if value is None:
            return ''
        if not isinstance(value, str) or not value.strip() or len(value) > 4096 or any(ord(char) < 32 for char in value):
            raise ValueError(f'{label}: enter a key or explicitly remove the saved key.')
        return value.strip()
    if kind == 'toggle':
        if type(value) is not bool:
            raise ValueError(f'{label}: choose on or off.')
    elif kind == 'number':
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError(f'{label}: enter a finite number.')
        if not field['min'] <= value <= field['max']:
            raise ValueError(f"{label}: enter a value from {field['min']} to {field['max']}.")
        if field.get('step', 1) == 1 and value != int(value):
            raise ValueError(f'{label}: enter a whole number.')
    elif kind in ('select', 'choice'):
        options = [option['value'] for option in field['options']]
        if type(value) is not str or value not in options:
            raise ValueError(f'{label}: choose an available option.')
    elif kind in ('text', 'textarea'):
        if not isinstance(value, str) or len(value) > field.get('max_length', 2048) or '\x00' in value:
            raise ValueError(f'{label}: the text is not valid or is too long.')
    else:
        raise ValueError('This setting cannot be edited.')
    codec = field.get('codec')
    if codec in ('json-list', 'json-object'):
        try:
            def reject_constant(_):
                raise ValueError('Non-finite JSON number')
            decoded = json.loads(value, parse_constant=reject_constant)
        except (ValueError, TypeError):
            raise ValueError(f'{label}: enter valid JSON.') from None
        if not isinstance(decoded, list if codec == 'json-list' else dict):
            raise ValueError(f'{label}: use a JSON {"list" if codec == "json-list" else "object"}.')
        return decoded
    if codec == 'words':
        result, seen = [], set()
        for word in re.split(r'[,\n]', value):
            word = word.strip()
            if word and word.casefold() not in seen:
                result.append(word)
                seen.add(word.casefold())
        return result
    if codec == 'hotkey':
        chords = [[key.strip().lower() for key in chord.split('+') if key.strip()] for chord in value.split(';') if chord.strip()]
        if any(len(chord) > 8 or any(not re.fullmatch(r'[a-z0-9_ -]{1,32}', key) for key in chord) for chord in chords) or len(chords) > 8:
            raise ValueError(f'{label}: use keys separated by + and alternatives separated by ;.')
        return chords
    if codec == 'endpointing':
        if value.strip().lower() == 'false':
            return False
        if not value.strip().isdecimal() or not 0 <= int(value) <= 10000:
            raise ValueError(f'{label}: enter 0 to 10000, or false to disable endpointing.')
        return int(value)
    return value


class SettingsStore:
    def __init__(self, config, fields, persist, *, normalize=None):
        self.config = config
        self.persist = persist
        self.normalize = normalize
        self.fields = {}
        self.lock = threading.RLock()
        self._revision_key = secrets.token_bytes(32)
        for field in fields:
            field = copy.deepcopy(field)
            identifier = field['id']
            if not re.fullmatch(r'[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*', identifier):
                raise ValueError('Invalid setting identifier')
            parts = identifier.split('.')
            write_only_key = field['type'] == 'secret' and parts[-1] == 'api_key'
            if any(part in {'token', 'password', 'license', 'licensing', 'credentials'} or (part == 'api_key' and not write_only_key) for part in parts):
                raise ValueError('Credentials do not belong in the renderer schema')
            if identifier in self.fields:
                raise ValueError('Duplicate setting identifier')
            self.fields[identifier] = field

    def snapshot(self):
        with self.lock:
            values = {identifier: _value(self.config, field) for identifier, field in self.fields.items()}
            revision_values = dict(values)
            for identifier, field in self.fields.items():
                if field['type'] == 'secret':
                    revision_values[identifier] = _value(self.config, {**field, 'type':'text'})
            serialized = json.dumps(revision_values, sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(',', ':'))
            return {'revision': hmac.new(self._revision_key, serialized.encode(), hashlib.sha256).hexdigest(), 'values': values}

    def save(self, payload):
        if not isinstance(payload, dict) or set(payload) != {'revision', 'changes'}:
            raise ValueError('The settings request is incomplete.')
        changes = payload['changes']
        if not isinstance(changes, dict) or len(changes) > len(self.fields):
            raise ValueError('The settings request is invalid.')
        with self.lock:
            current = self.snapshot()
            if payload['revision'] != current['revision']:
                raise SettingsConflict('Settings changed elsewhere. Your draft is still here; review the latest settings before saving.')
            validated = {}
            for identifier, value in changes.items():
                if identifier not in self.fields:
                    raise ValueError('This setting cannot be changed from this window.')
                validated[identifier] = validate_value(self.fields[identifier], value)
            if not changes:
                return current
            candidate = copy.deepcopy(self.config)
            for identifier, value in validated.items():
                parts = identifier.split('.')
                parent = candidate
                for part in parts[:-1]:
                    if not isinstance(parent.get(part), dict):
                        parent[part] = {}
                    parent = parent[part]
                parent[parts[-1]] = value
            if self.normalize is not None:
                self.normalize(candidate, set(changes))
            # The app supplies its atomic config writer. Runtime preferences
            # change only after that succeeds, so a disk error preserves state.
            self.persist(candidate)
            self.config.clear()
            self.config.update(candidate)
            return self.snapshot()
