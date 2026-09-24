"""Shared Scribe review with owned actions, retained edits and save receipts."""
from __future__ import annotations
import copy,hashlib,hmac,json,secrets,threading,time
from pathlib import Path


class ScribeWorkspace:
    CHUNK=8000
    MAX_TEXT=4_000_000
    SOURCES={'microphone','system','both'}

    def __init__(self,config,persist,utility,dispatch,launch=None):
        self.config,self.persist,self.utility,self.dispatch=config,persist,utility,dispatch
        self.launch=launch or self._launch
        self.lock=threading.RLock();self.key=secrets.token_bytes(32)
        self.engine=None;self.text='';self.revision=0;self.edited=False
        self.pending=None;self.job=None;self.receipts=[];self.message='';self.closed=False
        self.draft_saved=False;self.library_job=None;self.library=[];self.library_message='';self.library_limited=False

    @staticmethod
    def _launch(work):
        threading.Thread(target=work,name='TalkDatScribeDocument',daemon=True).start()

    def config_revision(self):
        raw=json.dumps(self.config,sort_keys=True,ensure_ascii=True,separators=(',',':')).encode()
        return hmac.new(self.key,raw,hashlib.sha256).hexdigest()

    def current(self,revision):
        if type(revision) is not int or revision!=self.revision:
            raise ValueError('These notes changed. Copy your edits before refreshing.')

    @staticmethod
    def require(payload,fields=()):
        if type(payload) is not dict or set(payload)!={'operation',*fields}:
            raise ValueError('That Scribe action is unavailable.')

    @classmethod
    def valid_text(cls,value):
        if type(value) is not str or len(value)>cls.MAX_TEXT or '\x00' in value or any(0xD800<=ord(c)<=0xDFFF for c in value):
            raise ValueError('Use up to 4,000,000 complete characters. Your earlier notes are kept.')
        return value

    def sync(self):
        engine=self.utility('current',None)
        if engine is not self.engine:
            if self.edited or self.job:
                return
            self.engine=engine;self.text='';self.revision+=1;self.pending=None
            self.edited=bool(getattr(engine,'review_edited',False));self.draft_saved=bool(getattr(engine,'draft_saved',False))
            if engine is not None:self.text=engine.snapshot()['body']
        if self.engine is not None:
            state=self.engine.snapshot()
            if not self.edited and self.text!=state['body']:
                self.text=state['body'];self.revision+=1
            if state['saved_path']:
                path=Path(state['saved_path'])
                if not any(row['path']==path for row in self.receipts):
                    self.receipts.insert(0,{'id':secrets.token_hex(12),'path':path,'revision':self.revision})
                    self.receipts=self.receipts[:12]

    def state(self):
        self.sync()
        engine=self.engine.snapshot() if self.engine else {}
        capture=self.engine.recorder if self.engine else None
        started=getattr(capture,'started_at',0)
        seconds=max(0,time.monotonic()-started) if started and engine.get('phase')=='recording' else 0
        if capture is not None and not seconds:
            counts=getattr(capture,'written_bytes',{});rates=getattr(capture,'rates',{});channels=getattr(capture,'channels',{})
            seconds=max((count/(rates.get(name,16000)*channels.get(name,1)*2) for name,count in counts.items()),default=0)
        options=self.config.get('scribe',{});source=options.get('source','both') if type(options) is dict else ''
        return {'revision':self.revision,'config_revision':self.config_revision(),'source':source,
            'recorded_source':self.engine.config.get('scribe',{}).get('source','') if self.engine and hasattr(self.engine,'config') else '',
            'input':str((self.engine.config if self.engine and hasattr(self.engine,'config') and not engine.get('finished') else self.config).get('audio',{}).get('input_device','') or 'System default microphone'),
            'phase':engine.get('phase','idle'),'message':self.message or engine.get('message','Choose what to record. Your microphone and system audio are off.'),
            'active':bool(self.job or (engine and (not engine.get('finished') or not engine.get('audio_closed')))),
            'job':self.job['kind'] if self.job else '', 'audio_open':bool(engine and not engine.get('audio_closed')),
            'saving':bool(self.job and self.job['kind']=='save'),'edited':self.edited,'draft_saved':self.draft_saved,
            'library':list(self.library),'refreshing':self.library_job is not None,'library_message':self.library_message,'library_limited':self.library_limited,'length':len(self.text),'seconds':round(seconds),
            'completed':engine.get('completed',0),'gaps':engine.get('gaps',0),'issues':engine.get('issues',[]),
            'originals':bool(engine.get('recording_folder')),'limit':self.MAX_TEXT,
            'other_recording':self.utility('current',None) is not self.engine,
            'platform':self.utility('platform',None),
            'receipts':[{'id':row['id'],'name':row['path'].name,'current':row['revision']==self.revision} for row in self.receipts]}

    def idle(self):
        state=self.state()
        if state['active'] or state['other_recording']:
            raise ValueError('Finish or stop the current recording and processing first.')

    def handle(self,payload):
        if type(payload) is not dict or type(payload.get('operation')) is not str:
            raise ValueError('That Scribe action is unavailable.')
        with self.lock:
            operation=payload['operation'];self.sync()
            if operation in {'open','status'}:
                self.require(payload);self.closed=False
                if operation=='open':self.refresh_library()
                return self.state()
            if self.closed:
                raise ValueError('Reopen Scribe before continuing.')
            if operation=='source':
                self.require(payload,('source','config_revision'));self.idle()
                source=payload['source'];revision=payload['config_revision']
                if type(source) is not str or source not in self.SOURCES:
                    raise ValueError('Choose microphone, system audio or both.')
                if type(revision) is not str or not hmac.compare_digest(revision,self.config_revision()):
                    raise ValueError('Settings changed elsewhere. Refresh before choosing a source.')
                candidate=copy.deepcopy(self.config)
                if type(candidate.get('scribe')) is not dict:candidate['scribe']={}
                candidate['scribe']['source']=source
                try:self.persist(candidate)
                except Exception:raise ValueError('The source could not be saved. Your previous choice is kept.') from None
                self.config.clear();self.config.update(candidate);self.message='Recording source saved.'
                return self.state()
            if operation=='read':
                self.require(payload,('revision','offset'));self.current(payload['revision'])
                offset=payload['offset']
                if type(offset) is not int or not 0<=offset<=len(self.text):
                    raise ValueError('Choose a valid note position.')
                end=min(len(self.text),offset+self.CHUNK)
                return {'text':self.text[offset:end],'next':end if end<len(self.text) else None}
            if operation=='begin_edit':
                self.require(payload,('revision',));self.current(payload['revision']);self.idle()
                self.pending={'token':secrets.token_hex(16),'revision':self.revision,'length':0,'parts':[],'updated':time.monotonic()}
                return {'token':self.pending['token']}
            if operation in {'append_edit','commit_edit'}:
                self.require(payload,('token','offset','text') if operation=='append_edit' else ('token',))
                pending=self.pending
                if not pending or payload['token']!=pending['token'] or time.monotonic()-pending['updated']>120:
                    raise ValueError('The edit transfer expired. Your edits are still in the editor; try again.')
                self.current(pending['revision']);self.idle()
                if operation=='append_edit':
                    text=self.valid_text(payload['text']);offset=payload['offset']
                    if type(offset) is not int or offset!=pending['length'] or len(text)>self.CHUNK or offset+len(text)>self.MAX_TEXT:
                        raise ValueError('The edit transfer is incomplete. Your previous notes are kept.')
                    pending['parts'].append(text);pending['length']+=len(text);pending['updated']=time.monotonic()
                    return {'offset':pending['length']}
                text=''.join(pending['parts']);self.pending=None
                if text!=self.text:
                    self.text=text;self.revision+=1;self.edited=True;self.draft_saved=False
                    if self.engine is not None:
                        with self.engine._lock:
                            self.engine.body=text;self.engine.saved_path=None
                self.checkpoint()
                return self.state()
            if operation=='start':
                self.require(payload,('revision',));self.current(payload['revision']);self.idle()
                if self.edited:
                    raise ValueError('Save the current notes before starting a new recording.')
                self.utility('start',None);self.message='';self.sync()
                return self.state()
            if operation in {'finish','stop'}:
                self.require(payload)
                if self.engine is not None:self.utility(operation,self.engine)
                self.message='';return self.state()
            if operation=='retry':
                self.require(payload,('revision',));self.current(payload['revision']);self.idle()
                if self.edited:
                    raise ValueError('Save your edits before retrying the original transcription.')
                if self.engine is None:raise ValueError('Record something before retrying.')
                self.utility('retry',self.engine);self.message='';return self.state()
            if operation=='copy':
                self.require(payload,('revision',));self.current(payload['revision'])
                if not self.text:raise ValueError('There are no notes to copy yet.')
                self.utility('copy',self.text);return {'message':'Full notes copied.'}
            if operation=='save':
                self.require(payload,('revision',));self.current(payload['revision']);self.idle()
                if not self.text.strip():raise ValueError('Add or record notes before saving.')
                job={'kind':'save','text':self.text,'revision':self.revision,'engine':self.engine};self.job=job;self.message='Saving a new copy...'
                def work():
                    path=error=None
                    try:
                        path=self.utility('save',job['text'])
                        try:self.utility('checkpoint',{**job,'edited':False,'path':path})
                        except Exception:pass  # The new Markdown file is already a durable receipt.
                    except Exception:error='The notes could not be saved. Your full draft is kept; try again or copy it.'
                    def complete():
                        with self.lock:
                            if self.job is not job:return
                            self.job=None
                            if error:self.message=error;return
                            self.receipts.insert(0,{'id':secrets.token_hex(12),'path':Path(path),'revision':job['revision']});self.receipts=self.receipts[:12]
                            if self.revision==job['revision']:
                                self.edited=False;self.draft_saved=True
                                if self.engine is job['engine'] and self.engine is not None:
                                    with self.engine._lock:
                                        self.engine.saved_path=Path(path);self.engine.review_edited=False;self.engine.draft_saved=True
                                        if self.engine.phase=='save-failed':self.engine.phase='review' if self.engine.snapshot()['issues'] else 'ready'
                            self.message='A new copy is saved. Earlier notes are kept.'
                    self.dispatch(complete)
                try:self.launch(work)
                except Exception:self.job=None;self.message='Saving could not start. Your full draft is kept.'
                return self.state()
            if operation=='library':
                self.require(payload);self.refresh_library();return self.state()
            if operation=='library_folder':
                self.require(payload);self.utility('library_folder',None);return {'message':'Opened the recording library.'}
            if operation=='restore':
                self.require(payload,('id','revision'));self.current(payload['revision']);self.idle()
                if self.edited and not self.draft_saved:
                    raise ValueError('Save or copy these edits before opening another recording.')
                if not any(row['id']==payload['id'] for row in self.library):
                    raise ValueError('Refresh and choose a recording from the saved list.')
                job={'kind':'restore','id':payload['id'],'config':copy.deepcopy(self.config),'previous':self.engine};self.job=job
                self.message='Opening saved notes. Audio devices remain off.'
                def restore():
                    value=error=None
                    try:value=self.utility('restore',job)
                    except Exception as problem:error=str(problem)
                    def complete():
                        with self.lock:
                            if self.job is not job:return
                            self.job=None
                            if error:self.message=error;return
                            try:self.utility('adopt',{'previous':job['previous'],'engine':value})
                            except Exception as problem:self.message=str(problem);return
                            self.edited=False;self.message='';self.sync()
                    self.dispatch(complete)
                try:self.launch(restore)
                except Exception:self.job=None;self.message='Saved notes could not open. Your current draft is kept.'
                return self.state()
            if operation in {'open_file','show_folder'}:
                self.require(payload,('id',));row=next((row for row in self.receipts if row['id']==payload['id']),None)
                if row is None:raise ValueError('Choose one of the notes saved here.')
                self.utility('open',row['path'] if operation=='open_file' else row['path'].parent)
                return {'message':'Opened the saved notes.' if operation=='open_file' else 'Opened the notes folder.'}
            if operation=='originals':
                self.require(payload)
                if self.engine is None or self.engine.recorder is None:
                    raise ValueError('No original recording is available yet.')
                self.utility('open',self.engine.recorder.folder);return {'message':'Opened the original recordings.'}
            if operation=='permission':
                self.require(payload);self.utility('permission',None);return {'message':'Opened Mac recording permissions.'}
            raise ValueError('That Scribe action is unavailable.')

    def checkpoint(self):
        job={'kind':'draft','engine':self.engine,'text':self.text,'revision':self.revision,'edited':self.edited}
        self.job=job;self.message='Saving your draft for recovery...'
        def work():
            error=None
            try:self.utility('checkpoint',job)
            except Exception:error='The recovery draft could not be saved. Your edits remain here; save a copy or copy them before leaving.'
            def complete():
                with self.lock:
                    if self.job is not job:return
                    self.job=None
                    if error:self.message=error;return
                    if self.revision==job['revision']:
                        self.draft_saved=True
                        if self.engine is job['engine'] and self.engine is not None:
                            self.engine.review_edited=self.edited;self.engine.draft_saved=True
                    self.message='Draft saved on this computer. Save a copy when you want a separate file.'
            self.dispatch(complete)
        try:self.launch(work)
        except Exception:self.job=None;self.message='Recovery saving could not start. Your edits remain here; save a copy or copy them.'

    def refresh_library(self):
        if self.library_job:return
        job=object();self.library_job=job;self.library_message='Looking for saved recordings...'
        def work():
            result=error=None
            try:result=self.utility('catalog',None)
            except Exception:error='Saved recordings could not be listed. Earlier files are kept; try Refresh.'
            def complete():
                with self.lock:
                    if self.library_job is not job:return
                    self.library_job=None
                    if error:self.library_message=error;return
                    self.library=result['entries'];self.library_limited=result['limited']
                    self.library_message=('Recent recordings are shown. Open the folder to see all retained files.' if self.library_limited
                        else 'Choose a recording to review without activating audio.' if self.library else 'Your saved recordings will appear here.')
            self.dispatch(complete)
        try:self.launch(work)
        except Exception:self.library_job=None;self.library_message='The library could not open. Try Refresh.'

    def close(self):
        self.closed=True
        if self.engine is not None and not self.engine.finished.is_set():self.utility('stop',self.engine)
