"""Explicit Scribe actions, confined to the current recording owner."""
from __future__ import annotations
import copy,sys


class ScribeActions:
    def __init__(self,app,copy_text,open_path,busy,library=None):
        from knight_flow.scribe_library import ScribeLibrary
        self.app,self.copy_text,self.open_path,self.busy=app,copy_text,open_path,busy
        self.library=library or ScribeLibrary()

    def __call__(self,action,value):
        app=self.app
        if action=='current':return getattr(app,'_scribe_engine',None)
        if action=='platform':return sys.platform
        if action=='copy':return self.copy_text(value)
        if action=='open':return self.open_path(value)
        if action=='permission':
            if sys.platform!='darwin':raise ValueError('These recording permissions are available on Mac.')
            import subprocess
            subprocess.Popen(['open','x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture'])
            return
        if action=='start':
            if self.busy():raise ValueError('Finish the current recording or operation before starting Scribe.')
            previous=getattr(app,'_scribe_engine',None)
            if previous is not None and previous.body and previous.saved_path is None:
                raise ValueError('Save a copy of the current notes before starting another recording.')
            app.toggle_scribe()
            if getattr(app,'_scribe_engine',None) is previous:
                raise ValueError('Recording could not start. Finish other audio tasks and choose a writing model in Writing > Formatting.')
            return
        if action in {'finish','stop','retry'}:
            if value is not getattr(app,'_scribe_engine',None):
                raise ValueError('This recording changed elsewhere. Reopen Scribe to continue.')
            if action=='finish':value.finish()
            elif action=='stop':value.cancel()
            else:
                if self.busy():raise ValueError('Finish other recording or processing before retrying these notes.')
                value.retry(config=copy.deepcopy(app.config))
            return
        if action=='save':
            from knight_flow.scribe import notes_folder
            from knight_flow.export_files import save_new_export
            import datetime
            return save_new_export(notes_folder(),f'{datetime.datetime.now():%Y-%m-%d %H.%M} notes.md',value.encode('utf-8'))
        if action=='checkpoint':
            from knight_flow.scribe_library import save_review
            engine=value['engine']
            if engine is None or engine.recorder is None:
                raise ValueError('No recording folder is available for this draft. Save a copy to keep it.')
            save_review(engine.recorder.folder,value['text'],engine.when,edited=value['edited'],saved_path=value.get('path'))
            return
        if action=='catalog':return self.library.catalog()
        if action=='restore':
            return self.library.restore(value['id'],value['config'],dispatch=app._cross_thread_calls.put,on_state=app._on_scribe_state)
        if action=='adopt':
            previous=value['previous']
            if getattr(app,'_scribe_engine',None) is not previous or self.busy():
                raise ValueError('Another recording started. Finish it before reopening these notes.')
            app._scribe_engine=value['engine'];return
        if action=='library_folder':
            if not self.library.root.exists():raise ValueError('No recordings have been saved yet.')
            return self.open_path(self.library.root)
        raise ValueError('That Scribe action is unavailable.')
