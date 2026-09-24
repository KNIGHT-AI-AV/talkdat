"""Settings and action adapter, called only on the existing application UI thread."""
from __future__ import annotations
import copy
import json
import logging
from pathlib import Path

from knight_flow.config import DEFAULT_CONFIG
from knight_flow.local_stt import available_local_models
from knight_flow.stt_registry import PROVIDERS, provider_is_ready, sync_legacy_deepgram
from knight_flow.themes import SETTINGS_THEME_FAMILIES
from .shell_state import SettingsStore
from .theme_assets import material_metadata

PAGES = (
    # X-172, his order 2026-09-21: a launch opens HERE. Home is first in this
    # tuple because the tuple is also the search and navigation order.
    ('home','Home','Welcome back','Your shortcut, your words, and what changed in this version.'),
    ('setup','Getting started','Getting started','Set up your microphone, shortcut and speech.'),
    ('general', 'General', 'General', 'Everyday settings: your name, updates, sounds and pasting.'),
    ('dictation', 'Dictation', 'Dictation', 'Your microphone, capture controls and text delivery.'),
    ('speech', 'Speech', 'Speech', 'Choose on-device speech or a provider you hold a key for.'),
    ('formatting', 'Formatting', 'Formatting', 'Choose how your text is cleaned up.'),
    ('translation', 'Translation', 'Translation', 'Translate, compare and copy in one place.'),
    ('words', 'Words', 'Words and phrases', 'Personal spellings, replacements and voice snippets.'),
    ('ramble', 'Ramble', 'Ramble', 'Record a longer thought and save it as a document.'),
    ('scribe','Scribe','Scribe','Record a conversation and keep a transcript.'),
    ('app-profiles', 'App preferences', 'App preferences', 'Different writing settings for different apps.'),
    ('appearance', 'Appearance', 'Appearance', 'Colors, text, motion and Pill preferences.'),
    ('reset','Clear local data','Clear local data','Choose what to delete from this computer.'),
    ('privacy', 'Privacy', 'Privacy', 'Choose where speech is processed and what is saved.'),
    ('tools', 'Tools', 'Tools', 'Tools that work with your dictation.'),
    ('stats', 'Stats', 'Stats', 'Your dictation activity on this computer.'),
    ('mic-doctor','Mic Doctor','Mic Doctor','Get your microphone ready.'),
    ('speech-check','Speech check','Speech check','Review what your local model hears.'),
    ('history', 'History', 'History', 'Your words, saved on this computer.'),
    ('scratchpad', 'Scratchpad', 'Scratchpad', 'Notes, saved on this computer.'),
    ('recovery', 'Recovery', 'Recovery', 'Your recent recordings, so you can recover what you said.'),
    ('account', 'Account', 'Your Talk DAT account', 'Manage your existing account and access.'),
    ('help', 'Help', 'Help', 'Guides, diagnostics and support.'),
    ('feedback','Share an idea','Share an idea','Tell us what would make Talk DAT better.'),
    ('language-request','Request a language','Request a language','Tell us which language and region matter to you.'),
    ('models', 'Local models', 'Local models', 'Download models once, then use them on this computer.'),
    ('model-guide', 'Model guide', 'Model guide', 'Which speech models are available now, and which are still being tested.'),
    ('menu-order', 'Menu layout', 'Menu layout', 'Move daily actions into your preferred order. App controls stay together at the bottom.'),
)

TOOLS = (
    ('history', 'History', 'Read, search, pin and export saved dictations.'),
    ('scratchpad', 'Scratchpad', 'Keep your notes, tabs, titles and exports together.'),
    ('words', 'Words & Phrases', 'Train pronunciations and review suggested vocabulary.'),
    ('local_models', 'Local models', 'Download, compare and manage speech models.'),
    ('translation', 'Translate', 'Translate text and choose a local model.'),
    ('ramble', 'Ramble', 'Turn a longer recording into a document.'),
    ('captions', 'Live Captions', 'Read a live transcript while you speak.'),
    ('mic_doctor', 'Mic Doctor', 'Find and test your microphone.'),
    ('race', 'Speech check', 'Record a sample and review your local speech model.'),
    ('recovery', 'Recovery', 'Recover a protected voice session.'),
    ('stats', 'Your stats', 'See the activity saved on this computer.'),
    ('backup', 'Back up your data', 'Save settings, vocabulary, notes, pins and text history in a local ZIP.'),
    ('reset', 'Clear local data', 'Preview selected settings and files before clearing them.'),
    ('restore_backup', 'Restore a backup', 'Preview saved items before replacing them and restarting Talk DAT.'),
    ('language_request', 'Request a language', 'Tell us which language you would like to use.'),
)


def read_path(config, identifier, default=None):
    current = config
    for part in identifier.split('.'):
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current


def declared_fields(assets):
    """settings-fields.json, minus what this build cannot honour.

    A field marked "official_only" (today: privacy.share_usage_counts) exists
    only where official_build says the thing it switches can happen at all. A
    source build never sends the anonymous counts, so it shows no switch for
    them rather than one that does nothing.
    """
    from knight_flow import official_build
    fields = json.loads((Path(assets)/'settings-fields.json').read_text(encoding='utf-8'))
    available = official_build.usage_counts_available()
    kept = []
    missing = object()
    for field in fields:
        if field.pop('official_only', False) and not available:
            continue
        # The default a field shows is the app's real default, read from
        # DEFAULT_CONFIG, never a second copy typed into the JSON. The copy
        # went stale: X-602 moved new installs to Chill and the JSON kept
        # saying Executive (owner's audit, 2026-09-23).
        real = read_path(DEFAULT_CONFIG, field['id'], missing)
        if real is not missing and field.get('type') != 'secret':
            field['default'] = copy.deepcopy(real)
        kept.append(field)
    return kept


def local_model_options(config):
    """The Speech page's local model choices, by name.

    2026-09-23: the closed select cut the recommended model to "Parakeet TDT
    0.6B v3 (reco...". The option now carries the name alone; the full catalogue
    label rides along as the option's title (a tooltip), and the field's help
    text says which model is recommended, in a sentence.
    """
    from knight_flow.local_stt import model_display_name
    return [{'value': model.id, 'label': model_display_name(model.label), 'title': model.label}
            for model in available_local_models(config)]


def local_model_advice(config):
    from knight_flow.local_stt import model_display_name
    recommended = next((model for model in available_local_models(config) if getattr(model, 'recommended', False)), None)
    if recommended is None:
        return ''
    return (f'Recommended: {model_display_name(recommended.label)}, the best balance of speed and '
            f'accuracy on most computers.')


def provider_fields(config):
    ready = [provider for provider in PROVIDERS if provider_is_ready(provider.id)]
    fields = [{'id': 'stt.provider', 'label': 'Speech provider', 'type': 'select', 'page': 'speech',
               'section': 'Speech route', 'default': 'local',
               'description': 'Provider preferences are saved here. Your speech route and local-only privacy control decide which can run.',
               'options': [{'value': provider.id, 'label': provider.label} for provider in ready]}]
    for provider in ready:
        prefix = 'stt.providers.' + provider.id + '.'
        shared = {'page': 'speech', 'section': provider.label, 'when': {'stt.provider': provider.id}}
        models = available_local_models(config) if provider.id == 'local' else provider.models
        model_options = (local_model_options(config) if provider.id == 'local'
                         else [{'value': model.id, 'label': model.label} for model in models])
        # Preserve a deliberately entered custom endpoint/model. Known choices
        # remain suggestions; a provider can publish a model between releases.
        fields.append({**shared, 'id': prefix+'model', 'label': 'Speech model',
                       'type': 'select' if provider.id == 'local' else 'text', 'suggestions': model_options,
                       **({'options': model_options, 'description': local_model_advice(config)} if provider.id == 'local' else {}),
                       'default': read_path(DEFAULT_CONFIG, prefix+'model', models[0].id), 'max_length': 256})
        variants = sorted({variant for model in provider.models for variant in model.variants})
        fields.append({**shared, 'id': prefix+'variant', 'label': 'Speech variant', 'type': 'select',
                       # Provider variant ids are API words and stay as the provider
                       # spells them, except the one every local install shows.
                       'options': [{'value': value, 'label': {'auto': 'Automatic'}.get(value, value)} for value in variants],
                       'default': read_path(DEFAULT_CONFIG, prefix+'variant', variants[0])})
        if provider.id != 'local':
            fields.extend([
                {**shared, 'id': prefix+'api_key', 'label': provider.key_label, 'type': 'secret',
                 'description': 'Saved keys stay in protected local storage. Enter a replacement only when you want to change it.'},
                {**shared, 'id': prefix+'api_base', 'label': 'Service address', 'type': 'text',
                 'default': provider.api_base, 'max_length': 2048},
                {**shared, 'id': prefix+'language', 'label': 'Speech language', 'type': 'text', 'default': 'en-US', 'max_length': 64},
            ])
        fields.append({**shared, 'id': prefix+'extra', 'label': 'Advanced provider options', 'type': 'textarea',
                       'codec': 'json-object', 'default': {}, 'max_length': 65536, 'advanced': True,
                       'description': 'Additional provider options as a JSON object.'})
    return fields


def normalize_settings(candidate, changed, previous=None):
    if 'overlay.menu_order' in changed:
        from knight_flow.overlay import Overlay
        overlay = object.__new__(Overlay)
        defaults = [row[0] for row in overlay._context_menu_default_rows()]
        order = candidate['overlay']['menu_order']
        if any(type(item) is not str or item not in defaults for item in order) or len(set(order)) != len(order):
            raise ValueError('Choose each available menu action at most once.')
        candidate['overlay']['menu_order'] = Overlay._pin_context_menu_safety_zone(order, defaults)
    if 'transforms.llm.provider' in changed and 'transforms.llm.api_key' not in changed:
        llm = candidate.setdefault('transforms', {}).setdefault('llm', {})
        provider = str(llm.get('provider', 'none'))
        if provider != read_path(previous or {}, 'transforms.llm.provider'):
            from knight_flow.credentials import credential_store, credential_target
            llm['api_key'] = '' if provider in {'none','ollama'} else credential_store().read(credential_target('LLM',provider))
    if 'stt.providers.local.custom_models' in changed:
        from knight_flow.local_stt import custom_model_from
        entries = read_path(candidate, 'stt.providers.local.custom_models', [])
        if len(entries) > 100 or any(custom_model_from(entry) is None for entry in entries):
            raise ValueError('Custom models must be a list of Hugging Face model ids or existing converted-model folders.')
    if 'ui.settings_theme' in changed:
        candidate.setdefault('ui', {})['theme'] = 'light' if candidate['ui']['settings_theme'].endswith('Light') else 'dark'
    if any(key.startswith('deepgram.') for key in changed):
        deepgram = candidate.setdefault('deepgram', {})
        provider = candidate.setdefault('stt', {}).setdefault('providers', {}).setdefault('deepgram', {})
        for key in ('api_key', 'model', 'language'):
            if 'deepgram.'+key in changed:
                provider[key] = deepgram.get(key, '')
    if any(key.startswith('stt.providers.deepgram.') for key in changed):
        sync_legacy_deepgram(candidate)
    if 'stt.provider' in changed and candidate['stt']['provider'] != 'local':
        candidate['stt']['cloud_provider'] = candidate['stt']['provider']
    if any(key.startswith('translation.') for key in changed):
        candidate.setdefault('translation', {})['engine'] = 'local'
        candidate['translation']['engine_user_chosen'] = True
    if any(key.startswith('overlay.') and ('width' in key or 'height' in key) for key in changed):
        candidate.setdefault('overlay', {})['pill_scale_chosen'] = True
    if any(key.startswith('transforms.llm.') for key in changed):
        from knight_flow.config import LOCAL_FORMATTER_MODEL
        llm = candidate.get('transforms', {}).get('llm', {})
        ollama = candidate.setdefault('ollama', {})
        ollama['enabled'] = llm.get('provider') == 'ollama'
        ollama['model'] = llm.get('model') or LOCAL_FORMATTER_MODEL
        ollama['url'] = (llm.get('api_base', '').rstrip('/') or 'http://localhost:11434') + '/api/generate'


class ShellBackend:
    def __init__(self, config, assets, persist, applied, palette, *, actions=None, menu=None, system_preferences=None, models=None, menu_layout=None, microphones=None, workspaces=None, formatting=None):
        self.config, self.assets = config, Path(assets)
        self.formatting = formatting
        self.applied, self.palette = applied, palette
        self.actions, self.menu = dict(actions or {}), menu or (lambda: [])
        self.system_preferences = system_preferences or (lambda: {})
        self.models = models
        self.workspaces = workspaces
        self.menu_layout = menu_layout
        self.microphones = microphones or (lambda: {'status':'idle','devices':[],'message':''})
        self.fields = declared_fields(self.assets) + provider_fields(config)
        self.store = SettingsStore(config, self.fields, persist,
                                   normalize=lambda candidate, changed: normalize_settings(candidate, changed, self.config))

    def snapshot(self):
        for field in self.fields:
            if field['id'] == 'stt.providers.local.model':
                field['options'] = local_model_options(self.config)
                field['description'] = local_model_advice(self.config)
                self.store.fields[field['id']]['options'] = copy.deepcopy(field['options'])
        snapshot = self.store.snapshot()
        pages = []
        for identifier, label, title, description in PAGES:
            page = {'id': identifier, 'label': label, 'title': title, 'description': description, 'sections': []}
            if identifier == 'app-profiles':
                page['keywords'] = 'per app profiles learned writing style tone language spoken enter'
            if identifier in {'models', 'model-guide', 'menu-order', 'history', 'scratchpad', 'recovery', 'reset'}:
                page['hidden'] = True
            sections = {}
            for field in self.fields:
                if field['page'] != identifier:
                    continue
                public = {key: copy.deepcopy(value) for key, value in field.items() if key not in {'default','codec','page','section'}}
                public['value'] = snapshot['values'][field['id']]
                if field['type'] == 'secret':
                    public['saved'] = bool(read_path(self.config, field['id']))
                section = sections.setdefault(field['section'], {'label': field['section'], 'fields': []})
                section['fields'].append(public)
            page['sections'] = list(sections.values())
            pages.append(page)
        theme = str(read_path(self.config, 'ui.settings_theme', 'Flow Dark'))
        themes = []
        for family in SETTINGS_THEME_FAMILIES:
            for mode in ('Dark', 'Light'):
                name = family+' '+mode
                colors = {**self.palette(name), 'name': name, 'mode': mode.lower(), **material_metadata(family)}
                colors['ring'] = colors.get('focus_ring', colors.get('accent'))
                themes.append(colors)
        palette = next((item for item in themes if item['name'] == theme), themes[0])
        preferences = self.system_preferences()
        pages.append({'id':'menu', 'label':'Menu', 'hidden':True, 'sections':[]})
        from knight_flow.model_catalog import catalog_entries, MODEL_CATALOG_STATUS_LABELS, MODEL_CATALOG_VERIFIED_ON
        return {'revision': snapshot['revision'], 'status': 'Connected', 'pages': pages,
                'theme': theme, 'palette': palette, 'themes': themes,
                'app_font': read_path(self.config, 'ui.app_font', 'system'),
                'reduce_motion': bool(read_path(self.config, 'ui.reduce_motion', False) or preferences.get('reduce_motion')),
                'high_contrast': bool(preferences.get('high_contrast')),
                'tools': [{'action': action, 'label': label, 'description': description} for action,label,description in TOOLS if action in self.actions],
                'menu': self.menu(), 'actions': sorted(self.actions),
                'microphones': self.microphones(),
                'route': read_path(self.config, 'stt.route_mode', 'local'),
                'intensity': read_path(self.config, 'cleanup.format_intensity', DEFAULT_CONFIG['cleanup']['format_intensity']),
                'models': self.models.snapshot() if self.models is not None else [],
                'smart_formatting': self.formatting_snapshot(),
                'model_catalog_date': MODEL_CATALOG_VERIFIED_ON,
                'model_guide': [{'label':entry.label,'provider':entry.provider,'mode':entry.mode,
                                 'status':MODEL_CATALOG_STATUS_LABELS[entry.status], 'status_id':entry.status, 'notes':entry.notes}
                                for entry in catalog_entries()]}

    def formatting_snapshot(self):
        if self.formatting is None:
            return None
        try:
            return self.formatting.snapshot()
        except Exception:
            logging.getLogger(__name__).warning('Smart formatting status is unavailable', exc_info=True)
            return None

    def handle(self, method, payload):
        guard = getattr(self.workspaces, 'guard_request', None)
        if callable(guard): guard(method, payload)
        if method == 'workspace':
            if self.workspaces is None:
                raise ValueError('This workspace is unavailable.')
            return self.workspaces.handle(payload)
        if method == 'menu_layout':
            if set(payload) != {'expanded'} or type(payload['expanded']) is not bool or self.menu_layout is None:
                raise ValueError('This menu layout is unavailable.')
            return self.menu_layout(payload['expanded'])
        if method == 'state':
            return self.snapshot()
        if method == 'save':
            self.store.save(payload)
            warning = ''
            try:
                self.applied()
            except Exception as error:
                # The file is already committed. Do not keep a supposedly
                # unsaved draft or replay credential changes after this point.
                logging.getLogger(__name__).warning('Saved settings need a runtime refresh (%s)', type(error).__name__)
                warning = 'Your settings are saved. Restart Talk DAT to apply the remaining changes.'
            result = self.snapshot()
            from knight_flow.hotkeys import shortcut_conflicts
            conflicts = shortcut_conflicts(self.config.get('hotkeys', {}))
            if conflicts:
                chord, actions = conflicts[0]
                result['message'] = f'Saved, but {" and ".join(actions)} share {chord}. Only one will fire.'
            if warning:
                result['message'] = warning + (' ' + result['message'] if result.get('message') else '')
            return result
        if method == 'action':
            if set(payload) != {'name'} or not isinstance(payload['name'], str):
                raise ValueError('This action is not available from this window.')
            if self.models is not None and payload['name'].startswith(('model_download:', 'model_delete:')):
                operation, identifier = payload['name'].split(':',1)
                result = self.models.request(operation.removeprefix('model_'), identifier)
                result['models'] = self.models.snapshot()
                return result
            if self.formatting is not None and payload['name'].startswith('smart_formatting:'):
                operation = payload['name'].split(':', 1)[1]
                handlers = {'start': self.formatting.start, 'check': self.formatting.check_again,
                            'download_page': self.formatting.open_download_page, 'status': lambda: {}}
                if operation not in handlers:
                    raise ValueError('This action is not available from this window.')
                result = dict(handlers[operation]())
                result['smart_formatting'] = self.formatting_snapshot()
                return result
            if payload['name'] not in self.actions:
                raise ValueError('This action is not available from this window.')
            result = self.actions[payload['name']]()
            return result if isinstance(result, dict) else {}
        raise ValueError('Unknown settings request.')
