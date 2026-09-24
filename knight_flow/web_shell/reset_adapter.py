"""Quiesce the application before applying a reset, and retain a close receipt."""
from __future__ import annotations
import contextlib
import threading
from types import SimpleNamespace

from knight_flow.config import save_config, _SAVE_LOCK
from knight_flow.history import _sqlite_lock
from knight_flow.mic_registry import microphone_registry
from knight_flow.reset import perform
from .reset_workspace import config_revision

_WRITERS = frozenset({"TalkDatPronunciationRefresh","TalkDatWarmLocal","TalkDatPcAudit",
    "TalkDatAudioRecovery","TalkDatUpdater","TalkDatUpdateInstall","TalkDatLicenseActivation",
    "TalkDatEmailSignIn","TalkDatEmailVerify","TalkDatCodeRedemption","TalkDatRamble","TalkDatTranslateLast"})

def actions_for_app(app):
    shell = getattr(app, "web_shell", None)
    if shell is not None:
        return shell.reset_actions
    actions = getattr(app, "_legacy_reset_actions", None)
    if actions is None:
        def capture_busy():
            with app.lock:
                check = getattr(app, "_microphone_check", None)
                return (app.session is not None or app.session_token is not None
                        or app._scribe_busy()
                        or (check is not None and not check.finished.is_set()))
        shell = SimpleNamespace(app=app, _capture_busy=capture_busy,
            models=SimpleNamespace(lock=threading.RLock(), status={}),
            workspaces=SimpleNamespace(services={}))
        actions = app._legacy_reset_actions = ResetActions(shell)
    return actions

class ResetActions:
    def __init__(self, shell, *, launch=None, threads=threading.enumerate):
        self.shell,self.app=shell,shell.app
        self.launch=launch or (lambda work:threading.Thread(target=work,name="TalkDatReset",daemon=True).start())
        self.threads=threads

    def _other_work(self):
        if any(thread.is_alive() and (thread.name in _WRITERS or thread.name.startswith("TalkDatPrefetch-"))
               for thread in self.threads()):
            return True
        models=self.shell.models
        with models.lock:
            if any(item.get("state")=="working" for item in models.status.values()):return True
        workspaces=self.shell.workspaces
        if bool(getattr(getattr(workspaces,"_history_exports",None),"active",False)):return True
        for service in workspaces.services.values():
            if any(bool(getattr(service,key,False)) for key in ("job","recording","stopping","dictating")):
                return True
        for key,window in getattr(self.app.overlay,"utility_windows",{}).items():
            if key in {"reset","reset_confirm","settings"}:continue
            try:
                if window is not None and window.winfo_exists():return True
            except Exception:pass
        return False

    def busy(self):
        if getattr(self.app,"_reset_in_progress",False) or getattr(self.app,"_quitting",False):
            return True
        if self.shell._capture_busy() or self._other_work():return True
        return bool(set(microphone_registry().names())-{"wake-word"})

    def execute(self, intended, revision, complete):
        if self.busy():raise ValueError("Finish recording, background work and other open tools before erasing.")
        if config_revision(self.app.config,intended.config_keys)!=revision:
            raise ValueError("The selected settings changed. Preview again.")
        was_paused=bool(self.app.paused)
        self.app._reset_in_progress=True;self.app._reset_finished=False
        self.app._quitting=True;self.app.paused=True

        closed_services = []
        def release(error):
            for key in closed_services:
                self.shell.workspaces.services.pop(key, None)
            self.app._reset_in_progress=False;self.app._quitting=False;self.app.paused=was_paused
            self.app._plugin_quit_close=None
            with contextlib.suppress(Exception):self.app.refresh_wake_word()
            complete(error=error)

        def prepare():
            try:
                ready=self.app._auxiliary_audio_exit(prepare)
                if not ready:
                    if not self.app._quitting:release(ValueError("An audio device could not close. Nothing was erased."))
                    return
                if self._other_work():
                    release(ValueError("Background work started. Nothing was erased. Preview again when it finishes."));return
                # Legacy editors were refused above. Shared editors cannot have
                # a pending export here, and incoming mutations are now blocked.
                for key,service in list(self.shell.workspaces.services.items()):
                    if service.__class__.__name__=="ResetWorkspace":continue
                    close=getattr(service,"close",None)
                    if callable(close):
                        close()
                        closed_services.append(key)

                def work():
                    try:
                        with self.app.lock,_SAVE_LOCK,_sqlite_lock:
                            if config_revision(self.app.config,intended.config_keys)!=revision:
                                raise ValueError("The selected settings changed. Nothing was erased. Preview again.")
                            def write(value,forgotten):
                                save_config(value,forget_sections=forgotten)
                                self.app.config.clear();self.app.config.update(value)
                            manager=getattr(self.app,"license_manager",None)
                            result=perform([category.key for category in intended.categories],intended.root,
                                expected=intended,read_config=lambda:self.app.config,write_config=write,
                                forget_license=getattr(manager,"forget_license",None))
                        failure=None
                    except Exception as error:
                        result=None
                        failure=error if isinstance(error,ValueError) else ValueError("The reset could not finish. Preview the remaining data again.")
                    def done():
                        if failure:
                            release(failure);return
                        self.app._reset_finished=True
                        if any(category.key=="history" for category in intended.categories):
                            self.app.last_transcript=""
                        complete(result=result)
                    self.app._cross_thread_calls.put(done)
                self.launch(work)
            except Exception as error:
                release(error if isinstance(error,ValueError) else ValueError("Background activity could not close. Nothing was erased."))
        self.app.overlay.root.after(50,prepare)

    def finish(self):
        if not getattr(self.app,"_reset_finished",False):
            raise ValueError("Wait for the reset to finish.")
        self.app._cross_thread_calls.put(lambda:self.app.quit(settings_confirmed=True))

