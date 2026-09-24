"""Local Scribe receipts and explicit recovery without opening audio devices."""
from __future__ import annotations
import datetime, json, math, re, threading, wave
from pathlib import Path
from .audio_spool import _atomic_write_json
from .scribe import Chunk
from .scribe_transcription import TranscriptResult, notes_body, LABELS

MAX_REVIEW_BYTES=24_000_000


def safe_file(folder, name):
    path=Path(folder)/name
    if path.resolve().parent!=Path(folder).resolve() or path.is_symlink():
        raise ValueError('This recording contains an unsupported linked file. Its originals are kept.')
    return path


def read_json(folder, name, limit):
    path=safe_file(folder,name)
    if not path.exists():return None
    with path.open('rb') as stream:raw=stream.read(limit+1)
    if len(raw)>limit:raise ValueError('This recovery file is too large. Its originals are kept.')
    try:value=json.loads(raw)
    except (ValueError,UnicodeError):raise ValueError('This recovery file could not be read. Its originals are kept.') from None
    if type(value) is not dict or value.get('version')!=1:
        raise ValueError('This recovery format is unavailable. Its originals are kept.')
    return value


def save_review(folder, body, when, *, edited=False, saved_path=None):
    if type(body) is not str or len(body)>4_000_000 or '\x00' in body or any(0xD800<=ord(c)<=0xDFFF for c in body):
        raise ValueError('These notes exceed the recoverable text limit. Copy or save the original recording.')
    target=safe_file(folder,'review-v1.json')
    value={'version':1,'when':when.isoformat(),'body':body,'edited':bool(edited),'saved_path':str(saved_path or '')}
    if len(json.dumps(value,ensure_ascii=False).encode())>MAX_REVIEW_BYTES:
        raise ValueError('These notes exceed the recovery-file limit. Your earlier draft is kept.')
    _atomic_write_json(target,value)


class RecoveredRecording:
    """A closed, read-only recording owner. No microphone or output handles."""
    def __init__(self,folder):
        self.folder=Path(folder);self.closed=threading.Event();self.closed.set();self.started_at=0
        value=read_json(self.folder,'recording.json',64000)
        if value is None:raise ValueError('Recording details are missing. Its original files are kept.')
        self.source=value.get('source')
        if self.source not in {'microphone','system','both'}:raise ValueError('This recording source is unavailable.')
        errors=value.get('errors',[])
        self.errors=[str(item)[:500] for item in errors[:30]] if type(errors) is list else ['Recording details need review.']
        if value.get('closed') is not True:self.errors.append('This recording ended without a complete close receipt. Review its retained audio and transcript.')
        self.rates={};self.channels={};self.offsets={};self.written_bytes={};self._tracks={}
        offsets=value.get('offsets',{});offsets=offsets if type(offsets) is dict else {}
        for track in ('you','them'):
            path=safe_file(folder,track+'.wav')
            if not path.exists() or path.stat().st_size<=44:continue
            try:
                with wave.open(str(path),'rb') as source:
                    rate,channels=source.getframerate(),source.getnchannels()
                    if source.getsampwidth()!=2 or not 8000<=rate<=384000 or not 1<=channels<=8:raise ValueError()
                    self.rates[track]=rate;self.channels[track]=channels
                    self.written_bytes[track]=min(source.getnframes()*channels*2,path.stat().st_size-44)
            except (ValueError,OSError,EOFError,wave.Error):
                self.errors.append(LABELS[track]+' audio could not be read. Its original file is kept.');continue
            offset=offsets.get(track,0)
            self.offsets[track]=float(offset) if type(offset) in (int,float) and math.isfinite(offset) and 0<=offset<604800 else 0
            self._tracks[track]=path

    def tracks(self):return dict(self._tracks)
    def request_stop(self):return None
    def stop(self):return self.tracks()


class ScribeLibrary:
    def __init__(self,root=None):
        if root is None:
            from .config import app_dir
            root=app_dir()/'scribe-recordings'
        self.root=Path(root)

    def folder(self,id):
        if type(id) is not str or not re.fullmatch(r'recording-[a-zA-Z0-9_-]{1,80}',id):
            raise ValueError('Choose a recording from the saved list.')
        folder=self.root/id
        if not folder.is_dir() or folder.is_symlink() or folder.resolve().parent!=self.root.resolve():
            raise ValueError('That recording is no longer available in this library.')
        return folder

    def catalog(self):
        if not self.root.exists():return {'entries':[],'limited':False}
        # Directory iteration and all recovery IO run on the workspace worker.
        candidates=[];limited=False
        for index,path in enumerate(self.root.iterdir()):
            if index>=5000:limited=True;break
            try:
                folder=self.folder(path.name);metadata=(folder/'recording.json').stat()
                candidates.append((metadata.st_mtime,folder))
            except (ValueError,OSError):continue
        rows=[]
        for stamp,folder in sorted(candidates,reverse=True)[:100]:
            try:
                manifest=read_json(folder,'recording.json',64000)
                if manifest is None:continue
                rows.append({'id':folder.name,'name':datetime.datetime.fromtimestamp(stamp).strftime('%b %d, %Y · %H:%M'),
                    'source':manifest.get('source','unknown'),'draft':safe_file(folder,'review-v1.json').exists(),
                    'interrupted':manifest.get('closed') is not True})
            except (OSError,ValueError):continue
        return {'entries':rows,'limited':limited or len(candidates)>100}

    def restore(self,id,config,*,dispatch,on_state):
        from .scribe_engine import ScribeEngine
        folder=self.folder(id);recording=RecoveredRecording(folder)
        review=read_json(folder,'review-v1.json',MAX_REVIEW_BYTES)
        when=datetime.datetime.fromtimestamp((folder/'recording.json').stat().st_mtime)
        engine=ScribeEngine(config,dispatch=dispatch,on_state=on_state);engine.recorder=recording
        engine.config.setdefault('scribe',{})['source']=recording.source
        if review is not None:
            body=review.get('body')
            if type(body) is not str or len(body)>4_000_000 or '\x00' in body or any(0xD800<=ord(c)<=0xDFFF for c in body):
                raise ValueError('Saved notes could not be read. Their original recovery file is kept.')
            try:when=datetime.datetime.fromisoformat(review['when'])
            except (KeyError,TypeError,ValueError):pass
            engine.body=body;engine.review_edited=review.get('edited') is True
            # A stored path is a receipt only, never an automatic open action.
            saved=review.get('saved_path')
            if type(saved) is str and saved:
                path=Path(saved)
                if path.suffix.lower()=='.md' and path.is_file():engine.saved_path=path
        else:
            ledger=read_json(folder,'transcript-v1.json',8_000_000)
            result=TranscriptResult()
            if ledger:
                parts=ledger.get('parts')
                if type(parts) is not dict:raise ValueError('Transcription progress could not be read. Its original file is kept.')
                for key,value in parts.items():
                    match=re.fullmatch(r'(you|them):(\d+)',key)
                    if not match or type(value) is not dict:continue
                    track,offset=match[1],int(match[2]);body=value.get('text')
                    if value.get('ok') is True and type(body) is str and len(body)<=4_000_000:
                        result.chunks.append(Chunk(LABELS[track],offset+recording.offsets.get(track,0),body));result.completed+=1
                result.chunks.sort(key=lambda row:row.start)
                if result.chunks:
                    result.issues.append('Recovered completed sections. Retry transcription to check all retained audio.')
                    engine.body=notes_body(result,when,recording_issues=recording.errors);engine.result=result
            engine.review_edited=False
        engine.when=when;engine.finished.set();engine.phase='review' if engine.body else 'paused'
        engine.message='Saved recording opened. Your audio devices are off.'
        engine.draft_saved=review is not None
        return engine
