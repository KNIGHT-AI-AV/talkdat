"""Bounded history data for the shared writing workspace.

The engine owns the store and clipboard. The renderer receives opaque row ids,
short previews and a requested text chunk, never local paths or arbitrary files.
"""
import hashlib
from knight_flow.history import _activity_datetime
from collections import OrderedDict


class HistoryWorkspace:
    PAGE_SIZE = 30
    TEXT_CHUNK = 16000

    def __init__(self, store, pins, pin, unpin, copy_text, *, utility=None, preferences=None, exports=None):
        self.store, self.pins = store, pins
        self.pin, self.unpin, self.copy_text = pin, unpin, copy_text
        self.contexts = OrderedDict()
        self.utility = utility
        self.exports = exports
        self.preferences = preferences or (lambda: {'clock':'12h','report_design':'boardroom'})

    @staticmethod
    def identifier(entry):
        value = str(entry.get('created_at', '')) + '\0' + str(entry.get('type', '')) + '\0' + str(entry.get('text', ''))
        return hashlib.sha256(value.encode('utf-8')).hexdigest()[:32]

    @staticmethod
    def query(value):
        if type(value) is not str or len(value) > 256 or '\0' in value:
            raise ValueError('Enter a shorter search.')
        return value.strip()

    @staticmethod
    def offset(value):
        if type(value) is not int or not 0 <= value <= 2_000_000:
            raise ValueError('That history page is unavailable.')
        return value

    def entries(self, query='', pinned=False):
        if pinned:
            rows = self.pins()
            if query:
                rows = [row for row in rows if query.casefold() in str(row.get('text', '')).casefold()]
        else:
            rows = self.store.search(query, 300) if query else self.store.recent(300)
        def timestamp(row):
            value=row.get('created_at')
            return value if _activity_datetime(value) is not None else 0
        return sorted((row for row in rows if str(row.get('text') or '').strip()), key=timestamp, reverse=True)

    def row(self, identifier, pinned=False):
        if type(identifier) is not str or len(identifier) != 32:
            raise ValueError('That entry is unavailable. Refresh History.')
        key = (identifier, pinned)
        if key not in self.contexts:
            raise ValueError('That entry is unavailable. Refresh History.')
        for row in self.entries(self.contexts[key], pinned=pinned):
            if self.identifier(row) == identifier:
                return row
        raise ValueError('That entry is unavailable. Refresh History.')

    def handle(self, payload):
        if type(payload) is not dict:
            raise ValueError('That history action is unavailable.')
        operation=payload.get('operation')
        if operation == 'export':
            if self.exports is None:
                raise ValueError('Reopen History before exporting.')
            return self.exports.handle({key:value for key,value in payload.items() if key!='operation'})
        if operation == 'utility':
            if set(payload) != {'operation','action','value'} or self.utility is None:
                raise ValueError('That history action is unavailable.')
            allowed={'export_txt','export_md','export_srt','export_report','report_design','clock',
                     'open_history','clear_text','clear_audio','stats','open_recordings'}
            if payload['action'] not in allowed:
                raise ValueError('That history action is unavailable.')
            return self.utility(payload['action'],payload['value'])
        if operation == 'copy_results':
            if set(payload) != {'operation','query','pinned'} or type(payload['pinned']) is not bool:
                raise ValueError('That history action is unavailable.')
            rows=self.entries(self.query(payload['query']),payload['pinned'])
            if not rows:raise ValueError('There are no matching dictations to copy.')
            self.copy_text('\n\n'.join(str(row['text']) for row in rows))
            return {'message':f'Copied {len(rows)} complete entries.'}
        if operation == 'list' and set(payload) == {'operation','query','offset','pinned'}:
            query=self.query(payload['query'])
            offset=self.offset(payload['offset'])
            if type(payload['pinned']) is not bool: raise ValueError('Choose a history view.')
            rows=self.entries(query,payload['pinned'])
            pins={str(row.get('text','')).strip() for row in self.pins()}
            result=[]
            for row in rows[offset:offset+self.PAGE_SIZE]:
                text=str(row.get('text') or '')
                identifier=self.identifier(row)
                key=(identifier,payload['pinned'])
                self.contexts[key]=query
                self.contexts.move_to_end(key)
                while len(self.contexts)>300:
                    self.contexts.popitem(last=False)
                timestamp=row.get('created_at')
                if _activity_datetime(timestamp) is None: timestamp=None
                result.append({'id':identifier,'preview':text[:240], 'characters':len(text),
                    'created_at':timestamp,'type':str(row.get('type') or 'dictation')[:40],
                    'pinned':text.strip() in pins})
            return {'entries':result,'total':len(rows),'offset':offset,'preferences':self.preferences(),
                    'next':offset+self.PAGE_SIZE if offset+self.PAGE_SIZE<len(rows) else None}
        if operation in {'read','copy','pin','unpin'}:
            expected={'operation','id','pinned'} | ({'offset'} if operation=='read' else set())
            if set(payload) != expected or type(payload['pinned']) is not bool:
                raise ValueError('That history action is unavailable.')
            row=self.row(payload['id'],payload['pinned'])
            text=str(row['text'])
            if operation == 'read':
                offset=self.offset(payload['offset'])
                end=min(len(text),offset+self.TEXT_CHUNK)
                return {'id':payload['id'],'text':text[offset:end],'offset':offset,
                        'characters':len(text),'next':end if end<len(text) else None}
            if operation == 'copy': self.copy_text(text)
            elif operation == 'pin': self.pin(text)
            else: self.unpin(text.strip())
            return {'message':{'copy':'Copied the full entry.','pin':'Entry pinned.','unpin':'Entry unpinned.'}[operation]}
        raise ValueError('That history action is unavailable.')
