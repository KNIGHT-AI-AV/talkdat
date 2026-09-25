"""Existing engine operations used by the shared document workspaces."""
from pathlib import Path
import copy
import os
import re
import subprocess
import sys

from .history_workspace import HistoryWorkspace
from .history_exports import HistoryExports
from .notes_workspace import NotesWorkspace
from .recovery_workspace import RecoveryWorkspace
from .words_workspace import WordsWorkspace
from .profiles_workspace import ProfilesWorkspace
from .feedback_workspace import FeedbackWorkspace
from .setup_workspace import SetupWorkspace
from .setup_adapter import SetupActions
from .translation_workspace import TranslationWorkspace
from .translation_adapter import TranslationActions
from .ramble_workspace import RambleWorkspace
from .ramble_adapter import RambleActions
from .scribe_workspace import ScribeWorkspace
from .scribe_adapter import ScribeActions
from .stats_workspace import StatsWorkspace
from .mic_check_workspace import MicCheckWorkspace


class Workspaces:
    def __init__(self, app, persist, busy):
        self.app, self.config, self.persist, self.busy = app, app.config, persist, busy
        self.services = {}

    @staticmethod
    def copy(text):
        from knight_flow.paste import copy_text
        if not copy_text(text):raise ValueError('The clipboard is busy. Your words are still here. Try Copy again.')

    @staticmethod
    def open_path(path):
        path=Path(path)
        if not path.exists():raise ValueError('That saved file is no longer available.')
        if sys.platform=='darwin':subprocess.Popen(['open',str(path)])
        elif sys.platform=='win32':os.startfile(str(path))
        else:subprocess.Popen(['xdg-open',str(path)])

    def guard_request(self, method, payload):
        if getattr(self.app, "_reset_in_progress", False) is True:
            if method == "workspace" and type(payload) is dict and payload.get("area") == "reset":
                return
            if method == "state":
                return
            raise ValueError("The reset is confirmed. Wait for its result, then close Talk DAT.")

    def handle(self, payload):
        if type(payload) is not dict or payload.get('area') not in {'home','history','scratchpad','recovery','words','translation','ramble','stats','mic-check','app-profiles','feedback','setup','scribe','plugins','reset','account'}:
            raise ValueError('That workspace is unavailable.')
        area=payload['area']
        if area not in self.services:self.services[area]=self.create(area)
        return self.services[area].handle({key:value for key,value in payload.items() if key!='area'})

    def create(self, area):
        if area == "account":
            # X-612: signing in on the web Account page.
            from .account_workspace import AccountActions, AccountWorkspace
            return AccountWorkspace(AccountActions(self.app))
        if area == "reset":
            from knight_flow.config import app_dir
            from .reset_workspace import ResetWorkspace
            actions = self.reset_actions
            return ResetWorkspace(self.config, app_dir(), self.app._cross_thread_calls.put,
                                  actions.busy, actions.execute, actions.finish)
        if area == "plugins":
            from .plugins_workspace import PluginsWorkspace
            return PluginsWorkspace(self.config,self.busy,self.open_path)
        if area == 'setup':
            save = self.app.save_onboarding_settings
            microphone = MicCheckWorkspace(self.config, save, self.app.start_microphone_check, self.copy)
            from knight_flow.smart_formatting import shared
            return SetupWorkspace(self.config, save, SetupActions(self.app, self.copy, self.busy), microphone, shared(self.config))
        if area == "feedback":
            import webbrowser
            from knight_flow.feedback import submit_feedback
            from knight_flow.format_journal import journal_tail
            return FeedbackWorkspace(self.app._cross_thread_calls.put,submit_feedback,journal_tail,self.copy,webbrowser.open)
        if area == "app-profiles":
            return ProfilesWorkspace(self.config, self.persist)
        if area=="mic-check":
            return MicCheckWorkspace(self.config,self.persist,self.app.start_microphone_check,self.copy)

        if area=="home":
            from .home_workspace import HomeUpdates, HomeWorkspace
            return HomeWorkspace(self.config,self.app._cross_thread_calls.put,updates=HomeUpdates(self.app))
        if area=="stats":
            return StatsWorkspace(self.config,self.app._cross_thread_calls.put)
        if area=='scribe':
            return ScribeWorkspace(self.config,self.persist,ScribeActions(self.app,self.copy,self.open_path,self.busy),self.app._cross_thread_calls.put)
        if area=='ramble':
            return RambleWorkspace(self.config,RambleActions(self.app,self.copy,self.open_path,self.busy),self.app._cross_thread_calls.put)
        if area=='translation':
            return TranslationWorkspace(self.config,TranslationActions(self.app,self.copy,self.busy),self.app._cross_thread_calls.put)
        if area=='words':
            return WordsWorkspace(self.config,self.persist,utility=self.words_utility)
        if area=='history':
            from knight_flow.history import create_history_store, pinned_entries, pin_text, unpin_text
            config=self.config
            class CurrentHistoryStore:
                def recent(self,limit):return create_history_store(config).recent(limit)
                def search(self,query,limit):return create_history_store(config).search(query,limit)
            return HistoryWorkspace(CurrentHistoryStore(),pinned_entries,pin_text,unpin_text,self.copy,
                utility=self.history_utility,preferences=lambda:{'clock':self.config.get('ui',{}).get('history_clock','12h'),
                    'report_design':self.config.get('export',{}).get('report_design','boardroom')},exports=self.history_exports())
        if area=='scratchpad':
            from knight_flow.config import scratchpad_tabs_path,scratchpad_path
            return NotesWorkspace(scratchpad_tabs_path(),scratchpad_path(),self.copy,
                import_file=self.import_note,export_file=self.export_note,fonts=self.fonts,set_font=self.set_font)
        return RecoveryWorkspace(self.sessions,self.recover,self.play_recording,self.copy)

    def close(self):
        for service in self.services.values():
            close=getattr(service,'close',None)
            if callable(close):close()

    def words_utility(self, action, value):
        from tkinter import filedialog
        from knight_flow.packs import export_pack, import_pack
        if action=='suggestions':
            from knight_flow.history import suggest_vocabulary
            return suggest_vocabulary(self.config,value)
        if action=='export':
            filename=filedialog.asksaveasfilename(parent=self.app.overlay.root,title='Export vocabulary pack',
                initialfile='Talk DAT vocabulary.json',defaultextension='.json',filetypes=[('Talk DAT pack','*.json')])
            if not filename:return {'message':'Export cancelled.'}
            export_pack(value,filename);return {'message':'Vocabulary pack exported.'}
        if action=='import':
            candidate=copy.deepcopy(self.config)
            if value=='file':
                filename=filedialog.askopenfilename(parent=self.app.overlay.root,title='Import vocabulary pack',filetypes=[('Talk DAT pack','*.json')])
                if not filename:return None
                counts=import_pack(candidate,filename)
            else:
                import json
                if value not in {'medical','legal','aviation','military'}:raise ValueError('Choose an available vocabulary pack.')
                source=Path(__file__).resolve().parent.parent/'assets'/'vocab_packs'/(value+'.json')
                terms=json.loads(source.read_text(encoding='utf-8'))['terms']
                known={row['label'].strip().casefold() for row in self.services['words'].rows('vocabulary')}
                fresh=[]
                for term in terms:
                    if term.strip().casefold() not in known:
                        fresh.append(term);known.add(term.strip().casefold())
                if len(known)>5000:raise ValueError('This pack would exceed 5,000 words. Remove unused entries first.')
                dictionary=candidate.setdefault('dictionary',{})
                dictionary.setdefault('words',[]).extend(fresh)
                dictionary.setdefault('terms',[]);dictionary.setdefault('replacements',[]);candidate.setdefault('snippets',[])
                counts={'words':len(fresh),'replacements':0,'snippets':0}
            return candidate,counts
        if action.startswith('practice_'):
            if action=='practice_start':
                if self.busy():raise ValueError('Finish the current dictation before pronunciation practice.')
                self._word_practice={'active':True,'message':'Preparing pronunciation practice…','aliases':[]}
                def progress(message, done, aliases):
                    self._word_practice={'active':not done,'message':message,'aliases':list(aliases)}
                try:self.app.record_pronunciation(value,progress)
                except Exception:
                    self._word_practice={'active':False,'message':'Practice could not start.','aliases':[]};raise
            elif action=='practice_cancel':
                self.app.cancel_pronunciation()
            elif action!='practice_status':raise ValueError('That pronunciation action is unavailable.')
            return getattr(self,'_word_practice',{'active':False,'message':'Ready to practise.','aliases':[]})
        raise ValueError('That vocabulary action is unavailable.')

    def sessions(self):
        # Find-more P0-3: a failed take kept past the newest few is listed too.
        from knight_flow.audio_spool import recovery_sessions
        try:limit=max(5,int(self.config.get('dictation',{}).get('safety_recording_limit',5)))
        except (ValueError,TypeError):limit=5
        return recovery_sessions(min(limit,1000))

    def recover(self, identifier):
        if self.busy():raise ValueError('Finish the current dictation before recovering a recording.')
        self.app.recover_audio_session(identifier)

    def play_recording(self, row):
        from knight_flow.audio_spool import audio_spool_dir
        path=Path(str(row.get('audio_path',''))).resolve()
        if path.parent!=audio_spool_dir().resolve() or path.suffix.lower()!='.wav':
            raise ValueError('That protected recording is unavailable.')
        self.open_path(path)

    def fonts(self):
        from tkinter import font
        available=sorted(set(str(name) for name in font.families(self.app.overlay.root)),key=str.casefold)
        selected=str(self.config.get('ui',{}).get('scratchpad_font') or 'Georgia')
        if selected not in available:available.append(selected)
        return {'available':available,'selected':selected}

    def set_font(self,family):
        self.preference('ui','scratchpad_font',family)

    def preference(self,section,key,value):
        candidate=copy.deepcopy(self.config)
        candidate.setdefault(section,{})[key]=value
        self.persist(candidate)
        self.config.setdefault(section,{})[key]=value

    def import_note(self):
        from tkinter import filedialog
        filename=filedialog.askopenfilename(parent=self.app.overlay.root,title='Import a note',
            filetypes=[('Text and Markdown','*.txt *.md'),('All files','*.*')])
        if not filename:return None
        path=Path(filename)
        if path.stat().st_size>16*1024*1024:raise ValueError('Choose a text file smaller than 16 MB. Your original file stays unchanged.')
        try:text=path.read_text(encoding='utf-8-sig')
        except UnicodeError as error:raise ValueError('Choose a UTF-8 text or Markdown file.') from error
        return path.stem,text

    def export_note(self,title,text,format):
        from tkinter import filedialog
        filename=filedialog.asksaveasfilename(parent=self.app.overlay.root,title='Export note',
            initialfile=(re.sub(r'[^\w .-]','',title).strip() or 'Note')+'.'+format,
            defaultextension='.'+format,filetypes=[('Markdown' if format=='md' else 'Text','*.'+format)])
        if not filename:return None
        Path(filename).write_text(text,encoding='utf-8')
        return Path(filename).name

    def history_exports(self):
        if not hasattr(self, '_history_exports'):
            self._history_exports = HistoryExports(self.config,
                lambda callback: self.app._cross_thread_calls.put(callback), self.open_path)
        return self._history_exports

    def history_utility(self,action,value):
        from knight_flow import history
        from knight_flow.config import full_history_path,live_draft_path,recovered_draft_path,history_db_path
        from knight_flow.audio_spool import audio_spool_dir
        from knight_flow.export_report import REPORT_DESIGNS
        if action in {'clock','report_design'}:
            if value not in ({'12h','24h'} if action=='clock' else REPORT_DESIGNS):raise ValueError('Choose an available preference.')
            section,key=('ui','history_clock') if action=='clock' else ('export','report_design')
            self.preference(section,key,value)
            return {'message':'Preference saved.'}
        if action.startswith('clear_'):
            if action == 'clear_text' and getattr(self, '_history_exports', None) is not None and self._history_exports.active:
                raise ValueError('Wait for the history export to finish before clearing saved text.')
            if value is not True:raise ValueError('Confirm what you want to clear first.')
            if self.busy():raise ValueError('Finish the current dictation before clearing saved material.')
            if action=='clear_text':
                # Find-more P0-6: one list of every text store (history.clear_saved_text),
                # including the formatting journal and the words kept with each
                # recording, plus Paste Last's source, which kept the cleared words.
                failed=history.clear_saved_text()
                forget=getattr(self.app,'forget_last_take',None)
                if callable(forget):forget()
                if failed:
                    raise ValueError('Some saved text could not be deleted: '+', '.join(failed)+'. Close any program using those files and try again.')
                return {'message':'Saved text cleared: history, drafts, the formatting journal and the words kept with recordings. Pins, notes and the recordings themselves are kept.'}
            if action=='clear_audio':
                root=audio_spool_dir()
                for pattern in ('*.wav','*.json'):
                    for path in root.glob(pattern):path.unlink()
                return {'message':'Protected recordings cleared. Saved text, pins and notes are kept.'}
        if value!='':raise ValueError('That history action is unavailable.')
        formats={'export_txt':'txt','export_md':'md','export_srt':'srt','export_report':'pdf'}
        if action in formats:
            return self.history_exports().handle({'command':'start','format':formats[action]})
        if action=='open_history':self.open_path(full_history_path());return {}
        if action=='open_recordings':self.open_path(audio_spool_dir());return {}
        if action=='stats':return {'page':'stats'}
        raise ValueError('That history action is unavailable.')
