"""Background History exports with engine-owned saved-file receipts."""
from __future__ import annotations
import copy
import logging
from pathlib import Path
import secrets
import threading

log = logging.getLogger(__name__)


def create_export(config, format):
    from knight_flow.history import create_history_store, export_history_document
    if format != 'pdf':
        return export_history_document(config, format)
    from knight_flow.export_report import REPORT_DESIGNS, export_report_pdf
    entries = create_history_store(config).recent(20000)
    text = next((row['text'] for row in reversed(entries) if isinstance(row, dict)
                 and isinstance(row.get('text'), str) and row['text'].strip()), '')
    if not text:
        raise ValueError('No saved text is available to export. Refresh History and try again.')
    design = config.get('export', {}).get('report_design', 'boardroom')
    if design not in REPORT_DESIGNS:
        design = 'boardroom'
    author = str(config.get('account', {}).get('email', '')).split('@')[0]
    path = export_report_pdf(text, design=design, author=author)
    return dict(path=path, entries=1, format='pdf', capped=False, estimated_timing=False, unknown_dates=0)


class HistoryExports:
    FORMATS = {'txt', 'md', 'srt', 'pdf'}

    def __init__(self, config, dispatch, open_path, *, loader=create_export, launch=None):
        self.config, self.dispatch, self.open_path = config, dispatch, open_path
        self.loader, self.launch = loader, launch or self._launch
        self.active = False
        self.message, self.error = '', False
        self.receipts = []

    @staticmethod
    def _launch(work):
        threading.Thread(target=work, name='TalkDatHistoryExport', daemon=True).start()

    def snapshot(self):
        return {'active': self.active, 'message': self.message, 'error': self.error,
                'receipts': [{key: value for key, value in row.items() if key != 'path'} for row in self.receipts]}

    def handle(self, payload):
        if type(payload) is not dict or type(payload.get('command')) is not str:
            raise ValueError('That export action is unavailable.')
        command = payload['command']
        if command == 'status' and set(payload) == {'command'}:
            return self.snapshot()
        if command == 'start' and set(payload) == {'command', 'format'}:
            format = payload['format']
            if type(format) is not str or format not in self.FORMATS:
                raise ValueError('Choose an available export format.')
            if self.active:
                raise ValueError('A document is still saving. Wait for its saved-file receipt.')
            snapshot = copy.deepcopy(self.config)
            self.active, self.error = True, False
            self.message = 'Saving your document. You can keep using Talk DAT!'
            def work():
                try:
                    result, error = self.loader(snapshot, format), ''
                except ValueError as exception:
                    result, error = None, str(exception)
                except Exception:
                    log.exception('History export could not be saved')
                    result, error = None, 'The document could not be saved. Check free space and try again. Previous exports are kept.'
                def finish():
                    self.active, self.error = False, bool(error)
                    if error:
                        self.message = error
                        return
                    path = Path(result['path'])
                    receipt = {key: result.get(key, False) for key in ('entries', 'format', 'capped', 'estimated_timing', 'unknown_dates')}
                    receipt.update(id=secrets.token_hex(16), path=path, name=path.name)
                    self.receipts.insert(0, receipt)
                    del self.receipts[12:]
                    self.message = 'Saved a copy.'
                self.dispatch(finish)
            try:
                self.launch(work)
            except Exception:
                log.exception('History export worker could not start')
                self.active, self.error = False, True
                self.message = 'Saving could not start. Try again. Previous exports are kept.'
            return self.snapshot()
        if command in {'open', 'folder'} and set(payload) == {'command', 'id'}:
            identifier = payload['id']
            if type(identifier) is not str or len(identifier) != 32:
                raise ValueError('Choose a document saved during this app session.')
            receipt = next((row for row in self.receipts if row['id'] == identifier), None)
            if receipt is None:
                raise ValueError('That saved-file receipt is unavailable. Save the document again.')
            path = receipt['path']
            if not path.is_file():
                raise ValueError('That saved document was moved or removed. Save it again to create a new copy.')
            self.open_path(path if command == 'open' else path.parent)
            return self.snapshot()
        raise ValueError('That export action is unavailable.')
