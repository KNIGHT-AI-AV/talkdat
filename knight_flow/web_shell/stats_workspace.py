"""Read-only activity snapshots, computed away from the native UI queue."""
from __future__ import annotations
import copy
import logging
import threading

log = logging.getLogger(__name__)


def load_statistics(config):
    from knight_flow.history import history_stats
    from knight_flow.usage import usage_summary
    from knight_flow.stt_registry import PROVIDER_BY_ID

    stats = history_stats(config)
    usage = usage_summary(config, stats['dictated_words'], stats.get('dictation_active_days', stats['active_days']))
    provider = PROVIDER_BY_ID.get(usage['provider'])
    types = {'dictation': 'Dictation', 'recovered_dictation': 'Recovered dictation',
             'entry': 'Earlier entry', 'translation': 'Translation', 'transform': 'Rewrite',
             'command_transform': 'Voice rewrite', 'command_search': 'Voice search', 'command': 'Command'}
    counts = {}
    for kind, count in stats['by_type'].items():
        label = types.get(kind, 'Other')
        counts[label] = counts.get(label, 0) + count
    stats['by_type'] = [{'label': label, 'entries': count} for label, count in sorted(counts.items())]
    usage['provider_label'] = provider.label if provider else 'Current provider'
    usage['model_label'] = next((model.label for model in provider.models if model.id == usage['model']), usage['model'] or 'Automatic') if provider else usage['model'] or 'Automatic'
    return {'activity': stats, 'speech': usage,
            'history_enabled': config.get('privacy', {}).get('save_history', True) is not False}


class StatsWorkspace:
    def __init__(self, config, dispatch, loader=load_statistics):
        self.config, self.dispatch, self.loader = config, dispatch, loader
        self.data = None
        self.phase = 'idle'
        self.message = ''
        self.closed = False
        self.revision = 0

    def handle(self, payload):
        if type(payload) is not dict or set(payload) != {'operation'} or payload['operation'] not in {'status', 'refresh'}:
            raise ValueError('That activity action is unavailable.')
        if self.closed:
            raise ValueError('Activity is closed. Open it again to refresh.')
        if payload['operation'] == 'refresh' and self.phase != 'loading':
            self.revision += 1
            revision = self.revision
            snapshot = copy.deepcopy(self.config)
            self.phase, self.message = 'loading', ''
            def work():
                try:
                    data, error = self.loader(snapshot), ''
                except Exception:
                    log.exception('saved activity could not load')
                    data, error = None, 'Saved activity could not load. Try Refresh again.'
                def finish():
                    if self.closed or revision != self.revision:
                        return
                    if not error:
                        self.data = data
                    self.phase, self.message = ('error', error) if error else ('ready', '')
                self.dispatch(finish)
            try:
                threading.Thread(target=work, name='TalkDatActivity', daemon=True).start()
            except Exception:
                self.phase, self.message = 'error', 'Saved activity could not load. Try Refresh again.'
        return {'phase': self.phase, 'message': self.message,
                'revision': self.revision, 'data': copy.deepcopy(self.data)}

    def close(self):
        self.closed = True
        self.revision += 1
