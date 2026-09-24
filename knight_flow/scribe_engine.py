"""One Scribe recording/processing owner with retained review and save receipts."""
from __future__ import annotations
import copy,datetime,json,threading
from .scribe import ScribeRecorder,notes_folder
from .scribe_transcription import transcribe_tracks,notes_body
from .export_files import save_new_export


def prepare(config):
    from .caption_stream import prepare_local_captions
    prepare_local_captions(config)


def recognize(config, pcm):
    from .stt_sessions import transcribe_pcm
    return transcribe_pcm(config,pcm,16000,1,provider_id='local')


def summarize(config, text):
    from .llm import llm_configured,llm_rewrite
    if not llm_configured(config):
        raise ValueError('No writing model is ready.')
    return llm_rewrite(text,'Summarize this conversation into at most 6 concise action-oriented bullet points. Preserve names, amounts and deadlines. Return only the bullets, one per line, no markers.',config)


class ScribeEngine:
    def __init__(self, config, *, dispatch, on_state):
        self.config=copy.deepcopy(config)
        self.dispatch,self.on_state=dispatch,on_state
        self.phase='idle';self.message='';self.body='';self.saved_path=None
        self.recorder=None;self.result=None;self.when=datetime.datetime.now()
        self.finished=threading.Event();self.stop_event=threading.Event();self.cancelled=threading.Event()
        self._lock=threading.RLock();self._thread=None
        self.review_edited=False;self.draft_saved=False;self.review_warning='';self.retry_empty=False

    def _state(self, phase, message):
        with self._lock:
            self.phase,self.message=phase,message
        def deliver():
            if self.phase==phase and self.message==message:
                self.on_state(self,phase,message)
        self.dispatch(deliver)

    def start(self):
        with self._lock:
            if self._thread is not None:
                raise ValueError('Finish this recording before starting another.')
            self._state('preparing','Preparing the local speech model. Microphone and system audio are off.')
            self._thread=threading.Thread(target=self._run,name='TalkDatScribe',daemon=True)
            try:
                self._thread.start()
            except Exception:
                self.finished.set();self._state('error','Scribe could not start. Try again.')

    def finish(self):
        if self.finished.is_set():
            if self.recorder is not None and not self.recorder.closed.is_set():
                self.recorder.request_stop()
            return
        self.stop_event.set()
        self._state('stopping','Closing the audio devices before making your notes.')
        if self.recorder is not None:
            self.recorder.request_stop()

    def cancel(self):
        self.cancelled.set()
        self.finish()

    def _identity(self):
        from .stt_registry import selected_model_id,provider_settings
        settings=provider_settings(self.config,'local')
        language=str(settings.get('language') or self.config.get('deepgram',{}).get('language','en-US'))
        return json.dumps({'model':selected_model_id(self.config,'local'),'language':language},sort_keys=True)

    def _transcribe(self):
        recorder=self.recorder
        self._state('transcribing','Transcribing locally. Original audio and completed sections are kept for retry.')
        def progress(result):
            with self._lock:
                self.result=result
                self.body=notes_body(result,self.when,recording_issues=recorder.errors)
        result=transcribe_tracks(recorder.tracks(),lambda pcm:recognize(self.config,pcm),
            folder=recorder.folder,identity=self._identity(),offsets=recorder.offsets,
            cancelled=self.cancelled,progress=progress,retry_empty=self.retry_empty)
        body=notes_body(result,self.when,recording_issues=recorder.errors,
            summarize=None if self.cancelled.is_set() else lambda text:summarize(self.config,text))
        with self._lock:
            self.result=result
            self.body=body
        empty = not any(chunk.text.strip() for chunk in result.chunks) and not result.issues and not recorder.errors
        if empty:
            with self._lock:self.body=''
        self._save_review()
        if self.cancelled.is_set():
            self._state('paused','Transcription paused. Available words, saved progress and original audio are kept.')
            return
        if empty:
            self._state('empty','No words were recognized. The original recording is kept for review or retry.')
            return
        self._publish()

    def _save_review(self):
        from .scribe_library import save_review
        if self.recorder is None:return
        try:
            save_review(self.recorder.folder,self.body,self.when,edited=self.review_edited,saved_path=self.saved_path)
            self.draft_saved=True;self.review_warning=''
        except Exception:
            self.draft_saved=False;self.review_warning='Recovery notes could not be saved. Copy or save the full draft before quitting.'

    def _publish(self):
        if not self.body:
            raise ValueError('There are no notes to save yet.')
        try:
            path=save_new_export(notes_folder(),f'{self.when:%Y-%m-%d %H.%M} notes.md',self.body.encode('utf-8'))
        except Exception:
            self._state('save-failed','Notes could not be saved. The full draft remains available to copy or save again.')
            return
        with self._lock:
            self.saved_path=path
        self._save_review()
        incomplete=bool((self.result and self.result.issues) or (self.recorder and self.recorder.errors))
        self._state('review' if incomplete else 'ready',
            'Notes saved with gaps or recording warnings. Review the marked sections.' if incomplete else 'Notes saved. Ready to review.')

    def _run(self):
        try:
            prepare(self.config)
            if self.stop_event.is_set():
                self._state('paused','Scribe stopped before recording. No audio was captured.')
                return
            self.recorder=ScribeRecorder(self.config)
            if self.stop_event.is_set():
                self._state('paused','Scribe stopped before recording. No audio was captured.')
                return
            self.recorder.start()
            source=self.config.get('scribe',{}).get('source','both')
            self._state('recording',{'both':'Recording microphone and system audio.','microphone':'Recording your selected microphone.','system':'Recording system audio.'}[source])
            while not self.stop_event.wait(.1) and not self.recorder.closed.is_set():
                pass
            self.recorder.stop()
            if self.cancelled.is_set():
                self._state('paused','Recording stopped. Original audio is kept for review or transcription later.')
                return
            self._transcribe()
        except Exception as error:
            from .mac_system_audio import ERRORS
            known = set(ERRORS.values()) | {
                'Prepare a local speech model in Settings first.',
                'The selected microphone is unavailable. Reconnect it or choose another input.',
                'System-output capture needs the bundled Windows audio component. Repair or update Talk DAT.',
                'The Mac system-audio component is missing. Repair or update Talk DAT.',
                'Mac system audio did not start in time. Check its permission in System Settings.',
            }
            message=str(error)
            if self.cancelled.is_set():
                self._state('paused','Recording stopped. Available words and original audio are kept.')
            else:
                self._state('error', message if message in known else 'Scribe could not finish. Available words, saved progress and original audio are kept.')
        finally:
            if self.recorder is not None:
                try:
                    self.recorder.stop()
                except Exception:
                    self._state('close-failed','An audio device has not closed. Use Stop or Panic Stop to retry.')
            self.finished.set()

    def retry(self,config=None):
        with self._lock:
            if not self.finished.is_set() or self.recorder is None or not self.recorder.closed.is_set():
                raise ValueError('Wait for the current operation and audio devices to finish.')
            if self.phase=='save-failed':
                work=self._publish
            else:
                self.cancelled.clear();self.retry_empty=True
                if config is not None:
                    source=self.config.get('scribe',{}).get('source','both')
                    self.config=copy.deepcopy(config);self.config.setdefault('scribe',{})['source']=source
                self.saved_path=None;self.review_edited=False
                previous_body=self.body
                def work():
                    if previous_body.strip():
                        save_new_export(self.recorder.folder,'Earlier notes.md',previous_body.encode('utf-8'))
                    self._state('preparing','Preparing local speech for the retained recording. Audio devices are off.')
                    prepare(self.config)
                    if not self.cancelled.is_set():self._transcribe()
                    else:self._state('paused','Transcription paused. Your original recording and available notes are kept.')
            self.finished.clear()
            def run():
                try:work()
                except Exception:self._state('error','Scribe could not finish. Available words and original audio are kept.')
                finally:self.finished.set()
            self._thread=threading.Thread(target=run,name='TalkDatScribeRetry',daemon=True)
            try:self._thread.start()
            except Exception:
                self.finished.set();self._state('error','Retry could not start. Your words are still here.')

    def snapshot(self):
        with self._lock:
            recorder=self.recorder
            return {'phase':self.phase,'message':self.message,'body':self.body,
                'saved_path':str(self.saved_path or ''),'recording_folder':str(recorder.folder) if recorder else '',
                'finished':self.finished.is_set(),'audio_closed':recorder is None or recorder.closed.is_set(),
                'issues':(list(recorder.errors) if recorder else [])+([self.review_warning] if self.review_warning else []),
                'completed':self.result.completed if self.result else 0,'gaps':len(self.result.gaps) if self.result else 0}
