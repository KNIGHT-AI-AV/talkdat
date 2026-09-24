"""Synthetic recording fixtures. Never opens an audio device or sends text."""
from pathlib import Path
import copy,datetime,json,queue,tempfile,time,wave
from knight_flow.config import DEFAULT_CONFIG
from knight_flow.scribe_engine import ScribeEngine
from knight_flow.scribe_library import ScribeLibrary,RecoveredRecording,save_review
from knight_flow.web_shell.scribe_workspace import ScribeWorkspace
from knight_flow.export_files import save_new_export

SAMPLE='# Conversation notes\n\n## Selected lines\n\n- Confirm the release date on Friday.\n- Keep every original recording until the notes have been reviewed.\n\n## Transcript\n\n**Microphone:** Let’s keep the release simple. The team will review the new keyboard on Thursday.\n\n**System audio:** Agreed. 日本語 👩🏽‍💻 We will confirm the date together on Friday.\n'

class ScribeFixture:
    def __init__(self):
        self.temp=tempfile.TemporaryDirectory(prefix='talkdat-scribe-fixture-');self.folder=Path(self.temp.name)
        self.config=copy.deepcopy(DEFAULT_CONFIG);self.config['scribe']={'source':'both'}
        self.library=ScribeLibrary(self.folder/'recordings');self.queue=queue.Queue();self.engine=None
        self.flags={'copied':[],'opened':[],'starts':0,'fail_save':False,'fail_checkpoint':False,'empty':False,'permission':False,'save_delay':0}
        self.service=ScribeWorkspace(self.config,self.persist,self.utility,self.queue.put)
    def persist(self,config):return None
    def drain(self):
        while not self.queue.empty():self.queue.get_nowait()()
    def new_engine(self):
        self.library.root.mkdir(exist_ok=True);folder=Path(tempfile.mkdtemp(prefix='recording-',dir=self.library.root))
        (folder/'recording.json').write_text(json.dumps({'version':1,'source':self.config['scribe']['source'],'closed':True,'offsets':{},'errors':[]}))
        for name in ('you','them'):
            with wave.open(str(folder/(name+'.wav')),'wb') as audio:
                audio.setnchannels(1);audio.setsampwidth(2);audio.setframerate(16000);audio.writeframes(b'\x00\x01'*16000)
        engine=ScribeEngine(self.config,dispatch=self.queue.put,on_state=lambda *a:None)
        engine.recorder=RecoveredRecording(folder);engine.recorder.started_at=time.monotonic();engine.recorder.closed.clear()
        engine.phase='recording';engine.message='Recording microphone and system audio.'
        self.engine=engine;return engine
    def utility(self,action,value):
        if action=='current':return self.engine
        if action=='platform':return 'darwin' if self.flags['permission'] else 'win32'
        if action=='start':self.flags['starts']+=1;self.new_engine()
        elif action in {'finish','stop','retry'}:
            if value is not self.engine:raise ValueError('Changed recording')
            value.recorder.closed.set();value.finished.set()
            if action=='stop':value.phase='paused';value.message='Recording stopped. Original audio is kept.';return
            value.body='' if self.flags['empty'] else SAMPLE
            if not value.body:value.phase='empty';value.message='No words were recognized. Original audio is kept.';return
            value._save_review()
            if self.flags['fail_save']:value.phase='save-failed';value.message='Notes could not be saved. Your draft is kept.'
            else:
                value.saved_path=save_new_export(self.folder,'Conversation notes.md',value.body.encode());value._save_review()
                value.phase='ready';value.message='Notes saved. Ready to review.'
        elif action=='copy':self.flags['copied'].append(value)
        elif action=='open':self.flags['opened'].append(str(value))
        elif action=='permission':self.flags['opened'].append('permissions')
        elif action=='save':
            time.sleep(self.flags['save_delay'])
            if self.flags.get('save_failures',0):
                self.flags['save_failures']-=1;raise OSError('fixture first save failure')
            if self.flags['fail_save']:raise OSError('fixture disk failure')
            return save_new_export(self.folder,'Conversation notes.md',value.encode())
        elif action=='checkpoint':
            if self.flags['fail_checkpoint']:raise OSError('fixture checkpoint failure')
            item=value['engine'];save_review(item.recorder.folder,value['text'],item.when,edited=value['edited'],saved_path=value.get('path'))
        elif action=='catalog':return self.library.catalog()
        elif action=='restore':return self.library.restore(value['id'],value['config'],dispatch=self.queue.put,on_state=lambda *a:None)
        elif action=='adopt':
            if value['previous'] is not self.engine:raise ValueError('Changed recording')
            self.engine=value['engine']
        elif action=='library_folder':self.flags['opened'].append(str(self.library.root))
    def restart(self):
        self.engine=None;self.service=ScribeWorkspace(self.config,self.persist,self.utility,self.queue.put)
