"""Bounded microphone diagnostics with explicit ownership and worker shutdown."""
from __future__ import annotations
import copy
import logging
import threading
import time
from dataclasses import asdict

from knight_flow.mic_registry import MIC_DOCTOR, RACE, DEFERRED_MICROPHONE_RELEASE

log = logging.getLogger(__name__)


def check_local_model(config):
    from knight_flow.local_stt import is_downloaded, local_model_for_id
    from knight_flow.stt_registry import selected_model_id
    if not is_downloaded(local_model_for_id(selected_model_id(config, 'local'), config)):
        raise ValueError('Download a local speech model in Settings before running Speech check.')


def recognize_sample(config, pcm, rate, channels):
    from knight_flow.stt_sessions import transcribe_pcm
    return transcribe_pcm(config, pcm, rate, channels, provider_id='local')


class MicrophoneCheck:
    """One capture, never reused. All audio stays in memory and is discarded."""
    def __init__(self, config, *, registry, dispatch, mode='mic', on_done=None,
                 recognize=recognize_sample, prepare=check_local_model):
        if mode not in {'mic', 'speech'}:
            raise ValueError('Choose a microphone or speech check.')
        self.config = copy.deepcopy(config)
        self.registry, self.dispatch, self.mode = registry, dispatch, mode
        self.on_done, self.recognize, self.prepare = on_done, recognize, prepare
        self.seconds = 3 if mode == 'mic' else 8
        self.cancelled = threading.Event()
        self.finished = threading.Event()
        self.capture_done = threading.Event()
        self._lock = threading.RLock()
        self._close_lock = threading.Lock()
        self._token = None
        self._stream = None
        self._retrying = False
        self._started = False
        self._data = {'phase':'idle', 'mode':mode, 'message':'Ready when you are.',
            'level':0.0, 'elapsed':0.0, 'seconds':self.seconds, 'report':None,
            'text':'', 'recognition_ms':None, 'sample_rate':None, 'channels':None,
            'device':str(config.get('audio', {}).get('input_device', '') or 'System default')}

    def snapshot(self):
        with self._lock:
            return {**copy.deepcopy(self._data), 'active':self._started and not self.finished.is_set(),
                    'microphone_open':self._token is not None}

    def _state(self, phase, message):
        with self._lock:
            self._data.update(phase=phase, message=message)
            if phase != 'listening':self._data['level'] = 0.0

    def start(self):
        with self._lock:
            if self._started:raise ValueError('This check has already started.')
            self._started = True
            self._state('starting', 'Preparing the selected microphone…')
            self._token = self.registry.acquire(MIC_DOCTOR if self.mode == 'mic' else RACE,
                device=self._data['device'], phase='starting', stop=self.stop)
        try:
            threading.Thread(target=self._work, name='TalkDatMicrophoneCheck', daemon=True).start()
        except Exception:
            self.registry.release(self._token);self._token = None
            self.capture_done.set();self.finished.set()
            self._state('error', 'The check could not start. Try again.')
            raise

    def stop(self):
        with self._lock:
            self.cancelled.set()
            if self._token is not None:self.registry.set_phase(self._token, 'closing')
            if not self.finished.is_set():self._state('stopping', 'Stopping the check…')
            retry = self.capture_done.is_set() and self._stream is not None and not self._retrying
            if retry:self._retrying = True
        if retry:
            def close_again():
                try:
                    if self._close_stream():
                        self._state('cancelled', 'Check stopped. Test audio discarded.')
                        self.finished.set()
                finally:
                    with self._lock:self._retrying = False
            try:threading.Thread(target=close_again, name='TalkDatCheckClose', daemon=True).start()
            except Exception:
                self._retrying = False
                self.registry.set_phase(self._token, 'stop-failed')
        return DEFERRED_MICROPHONE_RELEASE

    def _close_stream(self):
        with self._close_lock:
            stream = self._stream
            if stream is not None:
                try:stream.stop()
                except Exception:log.debug('microphone check stop failed; closing handle', exc_info=True)
                try:stream.close()
                except Exception:
                    log.exception('microphone check could not close')
                    self.registry.set_phase(self._token, 'stop-failed')
                    self._state('error', 'The microphone did not close. Use Panic Stop to retry.')
                    return False
                self._stream = None
            self.registry.release(self._token);self._token = None
            return True

    def _work(self):
        pcm = bytearray()
        complete = threading.Event()
        limit = 0
        failure = ''
        started = time.monotonic()
        def receive(data, frames, timing, status):
            nonlocal failure
            if self.cancelled.is_set() or complete.is_set():return
            if input_callback_problem(status):
                failure = 'Audio was interrupted. Check your microphone and try again.'
                complete.set();return
            if not limit:return
            raw = bytes(data)
            remaining = limit-len(pcm)
            pcm.extend(raw[:remaining])
            with self._lock:
                self._data['level'] = pcm_rms_level(raw)
                self._data['elapsed'] = min(self.seconds, max(0, time.monotonic()-started))
            if len(pcm) >= limit:complete.set()
        try:
            from knight_flow.audio_input import (open_raw_input_stream, resolve_input_device,
                pcm_rms_level, input_callback_problem)
            if self.cancelled.is_set():return
            if self.mode == 'speech':self.prepare(self.config)
            if self.cancelled.is_set():return
            selection = self.config.get('audio', {}).get('input_device', '')
            device = resolve_input_device(selection)
            if str(selection or '').strip() and device is None:
                raise ValueError('The selected microphone is unavailable. Refresh the input list and choose it again.')
            stream, rate, channels, actual = open_raw_input_stream(samplerate=16000, channels=1,
                device=device, callback=receive, allow_device_fallback=False)
            self._stream = stream
            if not (8000 <= rate <= 192000 and 1 <= channels <= 8):
                raise ValueError('The microphone returned an unsupported audio format.')
            if actual != device:
                raise ValueError('The selected microphone could not be tested. Choose another input explicitly.')
            limit = int(self.seconds*rate)*channels*2
            with self._lock:self._data.update(sample_rate=rate, channels=channels)
            if self.cancelled.is_set():return
            started = time.monotonic()
            stream.start()
            if not self.cancelled.is_set():
                self.registry.set_phase(self._token, 'listening')
                self._state('listening', f'Speak naturally for {self.seconds} seconds, with a short pause.')
            while not self.cancelled.is_set() and not complete.is_set():
                elapsed = time.monotonic()-started
                if elapsed >= self.seconds:break
                with self._lock:self._data['elapsed'] = elapsed
                self.cancelled.wait(min(.02, self.seconds-elapsed))
            self.registry.set_phase(self._token, 'closing')
            self._state('closing', 'Closing the microphone…')
            if not self._close_stream():return
            self.capture_done.set()
            if self.cancelled.is_set():return
            if failure:raise ValueError(failure)
            if not pcm:raise ValueError('No audio arrived. Check your selected microphone and try again.')
            if self.mode == 'mic':
                from knight_flow.mic_doctor import analyze_sample
                report = analyze_sample(bytes(pcm), sample_rate=rate*channels)
                with self._lock:self._data['report'] = {**asdict(report), 'snr_db':report.snr_db}
                self._state('ready', report.advice)
            else:
                self._state('processing', 'Microphone closed. Checking the local speech model…')
                before = time.perf_counter()
                text = str(self.recognize(self.config, bytes(pcm), rate, channels) or '').strip()
                elapsed = (time.perf_counter()-before)*1000
                if self.cancelled.is_set():return
                with self._lock:self._data.update(text=text, recognition_ms=round(elapsed, 2))
                self._state('ready', 'Local speech check complete.' if text else 'The model returned no words. Try a clearer sample.')
        except ValueError as error:
            self._state('error', str(error))
        except Exception:
            log.exception('microphone check failed')
            self._state('error', 'The check could not finish. Check your selected microphone and local speech model, then try again.')
        finally:
            pcm.clear()
            # A failed close retains both the handle and registry owner for Panic.
            if self._data['phase'] != 'error' or self._stream is None:
                closed = self._close_stream()
            else:
                # Opening/start failures still own a handle; only a recorded
                # stop-failed state means a close was already attempted.
                failed = any(owner.token == self._token and owner.phase == 'stop-failed' for owner in self.registry.owners())
                closed = False if failed else self._close_stream()
            self.capture_done.set()
            if closed:
                if self.cancelled.is_set():
                    with self._lock:self._data.update(report=None, text='', recognition_ms=None)
                    self._state('cancelled', 'Check stopped. Test audio discarded.')
                self.finished.set()
            if self.on_done is not None:
                def deliver():
                    if not self.cancelled.is_set():self.on_done(self.snapshot())
                self.dispatch(deliver)
