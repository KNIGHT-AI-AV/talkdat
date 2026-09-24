"""Owned, cancellable pronunciation capture with UI-thread persistence."""
from __future__ import annotations
import copy
import io
import json
from pathlib import Path
import tempfile
import threading
import wave

from .config import _SAVE_LOCK, save_config
from .mic_registry import microphone_registry, PRONUNCIATION, DEFERRED_MICROPHONE_RELEASE


class CaptureCloseFailure(RuntimeError):
    def __init__(self, stream):
        super().__init__('The practice microphone did not close. Use Panic to retry stopping it.')
        self.stream = stream


def capture_take(config, cancelled):
    from .audio_input import open_raw_input_stream, resolve_input_device
    pieces = []
    byte_count = 0
    def receive(data, frames, timing, status):
        nonlocal byte_count
        if not cancelled.is_set() and byte_count < 4 * 192000 * 2:
            raw = bytes(data); pieces.append(raw); byte_count += len(raw)
    stream, rate, channels, _device = open_raw_input_stream(samplerate=16000,channels=1,
        device=resolve_input_device(config.get('audio',{}).get('input_device','')),callback=receive)
    try:
        if cancelled.is_set(): return None
        stream.start()
        cancelled.wait(2.5)
    finally:
        # Only this worker closes its stream. Panic signals cancellation and
        # keeps ownership visible until the handle has actually closed.
        try: stream.stop()
        finally:
            try:stream.close()
            except Exception as error:raise CaptureCloseFailure(stream) from error
    if cancelled.is_set(): return None
    pcm = b''.join(pieces)
    if not pcm: raise ValueError('No microphone audio arrived. Check the selected microphone and try again.')
    result = io.BytesIO()
    with wave.open(result,'wb') as output:
        output.setnchannels(channels);output.setsampwidth(2);output.setframerate(rate);output.writeframes(pcm)
    return result.getvalue()


class PronunciationPractice:
    def __init__(self, app, *, capture=capture_take, persist=save_config, launch=None):
        self.app, self.capture, self.persist = app, capture, persist
        self.launch = launch or (lambda worker: threading.Thread(target=worker,name='TalkDatPronunciation',daemon=True).start())
        self.cancelled = threading.Event()
        self.active = False
        self.token = None
        self.failed_stream = None
        self.retrying_close = False

    @staticmethod
    def vocabulary(config):
        dictionary=config.get('dictionary',{})
        return json.dumps({key:dictionary.get(key,[]) for key in ('words','terms','learn_tombstones')},sort_keys=True,ensure_ascii=True)

    def cancel(self):
        self.cancelled.set()
        if self.token is not None:microphone_registry().set_phase(self.token,'closing')
        if self.failed_stream is not None and not self.retrying_close:
            self.retrying_close=True
            def retry_close():
                try:
                    self.failed_stream.close()
                    microphone_registry().release(self.token)
                    self.failed_stream=None;self.token=None
                except Exception:microphone_registry().set_phase(self.token,'stop-failed')
                finally:self.retrying_close=False
            threading.Thread(target=retry_close,name='TalkDatPracticeClose',daemon=True).start()
        return DEFERRED_MICROPHONE_RELEASE

    def start(self, term, on_status):
        term=str(term).strip()
        if not term or len(term)>512 or '\x00' in term:raise ValueError('Enter a word or phrase before practising it.')
        registry=microphone_registry()
        with self.app.lock:
            if self.active or self.app.session is not None or self.app.session_token is not None or registry.is_active():
                raise ValueError('Finish the current recording before pronunciation practice.')
            self.cancelled.clear();self.active=True
            with _SAVE_LOCK:
                snapshot=copy.deepcopy(self.app.config);revision=self.vocabulary(snapshot)
            self.token=registry.acquire(PRONUNCIATION,stop=self.cancel,phase='preparing')
        def notify(message,done=False,aliases=None):
            self.app._cross_thread_calls.put(lambda:on_status(message,done,list(aliases or [])))
        def finish(takes,aliases,error=None):
            try:
                if self.cancelled.is_set():on_status('Practice cancelled. Your saved word is unchanged.',True,[]);return
                if error is not None:on_status(str(error),True,[]);return
                with _SAVE_LOCK:
                    if revision != self.vocabulary(self.app.config):
                        on_status('Your vocabulary changed during practice. Refresh and try again.',True,[]);return
                    candidate=copy.deepcopy(self.app.config)
                    dictionary=candidate.setdefault('dictionary',{})
                    terms=dictionary.setdefault('terms',[])
                    entry=next((row for row in terms if isinstance(row,dict) and str(row.get('text','')).casefold()==term.casefold()),None)
                    if entry is None:
                        entry={'text':term,'sounds_like':[]};terms.append(entry)
                        dictionary['words']=[word for word in dictionary.get('words',[]) if str(word).casefold()!=term.casefold()]
                    old=entry.get('sounds_like') or []
                    if isinstance(old,str):old=[old]
                    hand=[alias for alias in old if alias not in entry.get('trained_aliases',[])]
                    entry.update(sounds_like=list(dict.fromkeys(hand+aliases))[:8],trained_aliases=aliases)
                    dictionary['learn_tombstones']=[word for word in dictionary.get('learn_tombstones',[]) if str(word).casefold()!=term.casefold()]
                    self.persist(candidate)
                    self.app.config.clear();self.app.config.update(candidate)
                from .pronunciation import store_clip
                try:
                    for index,data in enumerate(takes,1):store_clip(self.app.config,term,index,data)
                    message='Pronunciation saved.' if aliases else 'The local model heard the spelling correctly. Your recordings are saved.'
                except OSError:
                    message='Sounds-like spellings saved, but the recordings could not be kept. Try practice again before changing models.'
                on_status(message,True,aliases)
            except Exception:
                on_status('Pronunciation could not be saved. Your existing word is unchanged; try again.',True,[])
            finally:self.active=False
        def worker():
            takes=[];aliases=[];error=None
            try:
                transcribe=self.app._local_clip_transcriber()
                for index in range(1,4):
                    if self.cancelled.is_set():break
                    registry.set_phase(self.token,'recording')
                    notify(f'Say "{term}" now ({index}/3).')
                    data=self.capture(snapshot,self.cancelled)
                    if data is None or self.cancelled.is_set():break
                    takes.append(data)
                    if index<3:
                        registry.set_phase(self.token,'between takes')
                        notify(f'Take {index} complete. Get ready for the next one.')
                        if self.cancelled.wait(.6):break
                registry.release(self.token);self.token=None
                if not self.cancelled.is_set():
                    if len(takes)!=3:raise ValueError('Practice did not finish. Your saved word is unchanged.')
                    notify('Listening back with the local speech model…')
                    with tempfile.TemporaryDirectory(prefix='talkdat-practice-') as directory:
                        from .pronunciation import MAX_ALIASES
                        for index,data in enumerate(takes,1):
                            if self.cancelled.is_set():break
                            path=Path(directory)/f'take-{index}.wav';path.write_bytes(data)
                            heard=str(transcribe(path) or '').strip().lower()
                            heard=''.join(c for c in heard if c.isalnum() or c.isspace() or c in "'-").strip()
                            if heard and heard.casefold()!=term.casefold() and heard not in aliases:aliases.append(heard)
                        aliases=aliases[:MAX_ALIASES]
            except CaptureCloseFailure as failure:
                self.failed_stream=failure.stream
                registry.set_phase(self.token,'stop-failed')
                error=failure
            except Exception:
                error=ValueError('Practice could not finish. Check your microphone and installed local speech model, then try again.')
            finally:
                if self.failed_stream is None:
                    registry.release(self.token);self.token=None
                self.app._cross_thread_calls.put(lambda:finish(takes,aliases,error))
        try:self.launch(worker)
        except Exception:
            registry.release(self.token);self.token=None;self.active=False;raise
