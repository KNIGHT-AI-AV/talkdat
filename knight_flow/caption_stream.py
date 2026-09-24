"""Bounded local captions with explicit microphone ownership and UI delivery."""
from __future__ import annotations

import copy
import logging
import queue
import threading
from typing import Callable

from .mic_registry import CAPTIONS, DEFERRED_MICROPHONE_RELEASE

log = logging.getLogger(__name__)


def prepare_local_captions(config) -> None:
    """Warm the exact local path before opening a microphone; discard silence."""
    from .local_stt import is_downloaded, local_model_for_id
    from .stt_registry import selected_model_id
    from .stt_sessions import transcribe_pcm

    model = local_model_for_id(selected_model_id(config, "local"), config)
    if not is_downloaded(model):
        raise RuntimeError("Prepare a local speech model in Settings first.")
    transcribe_pcm(config, bytes(57600), 16000, 1, provider_id="local")


class LocalCaptionStream:
    CHUNK_SECONDS = 1.8
    MAX_PENDING_CHUNKS = 2

    def __init__(self, config, *, registry, dispatch: Callable, on_text: Callable,
                 on_state: Callable) -> None:
        self.config = copy.deepcopy(config)
        self.registry = registry
        self.dispatch = dispatch
        self.on_text = on_text
        self.on_state = on_state
        self.phase = "preparing"
        self.error = ""
        self.stop_event = threading.Event()
        self.capture_done = threading.Event()
        self.decoder_done = threading.Event()
        self.finished = threading.Event()
        self.chunks = queue.Queue(maxsize=self.MAX_PENDING_CHUNKS)
        self._lock = threading.RLock()
        self._close_lock = threading.Lock()
        self._stream = None
        self._closed = False
        self._token = None
        self._started = False
        self._retry_active = False
        self.sample_rate = 16000
        self.channels = 1

    def _notify(self) -> None:
        phase, error = self.phase, self.error

        def deliver():
            # A queued Starting/Listening callback must not repaint after Stop.
            if self.phase == phase and self.error == error:
                self.on_state(self, phase, error)

        self.dispatch(deliver)

    def start(self) -> None:
        with self._lock:
            if self._started:
                raise RuntimeError("This caption stream has already started.")
            self._started = True
        self._notify()
        decoder = threading.Thread(target=self._decode, name="captions-transcribe", daemon=True)
        capture = threading.Thread(target=self._capture, name="captions-capture", daemon=True)
        try:
            decoder.start()
        except Exception:
            self.decoder_done.set()
            self.capture_done.set()
            self._closed = True
            self._fail("Live captions could not start. Please try again.")
            self.registry.release(self._token)
            self._finish_if_ready()
            return
        try:
            capture.start()
        except Exception:
            self.capture_done.set()
            self._closed = True
            self.registry.release(self._token)
            self._fail("The captions microphone could not start. Please try again.")
            self._finish_if_ready()

    def stop(self):
        """Signal promptly; the owner remains registered until driver close."""
        with self._lock:
            self.stop_event.set()
            if not self.finished.is_set():
                self.phase = "stopping"
                if self._token is not None and not self._closed:
                    self.registry.set_phase(self._token, "closing")
                self._notify()
            retry = self.capture_done.is_set() and not self._closed and not self._retry_active
            if retry:
                self._retry_active = True
        self._discard_pending()
        if retry:
            try:
                threading.Thread(target=self._retry_close, name="captions-close", daemon=True).start()
            except Exception:
                self._retry_active = False
                self.registry.set_phase(self._token, "stop-failed")
        return DEFERRED_MICROPHONE_RELEASE

    def _fail(self, message: str) -> None:
        with self._lock:
            if not self.error:
                self.error = message
        self.stop()

    def _discard_pending(self) -> None:
        while True:
            try:
                self.chunks.get_nowait()
            except queue.Empty:
                return

    def _capture(self) -> None:
        buffer = bytearray()
        target = 0

        def on_audio(indata, _frames, _time_info, status):
            if self.stop_event.is_set():
                return
            if input_callback_problem(status):
                self._fail("Captions stopped because microphone audio was interrupted. Check the microphone and try again.")
                return
            buffer.extend(bytes(indata))
            while target and len(buffer) >= target and not self.stop_event.is_set():
                chunk = bytes(buffer[:target])
                del buffer[:target]
                try:
                    self.chunks.put_nowait(chunk)
                except queue.Full:
                    # Never silently drop words or accumulate minutes of delay.
                    self._fail("Captions stopped because the speech model could not keep up. Choose a faster local speech model.")
                    return

        try:
            from .audio_input import open_raw_input_stream, resolve_input_device, input_callback_problem

            if self.stop_event.is_set():
                return
            try:
                prepare_local_captions(self.config)
            except Exception:
                log.exception("captions local model preparation failed")
                self._fail("Live captions could not prepare the speech model. Check your downloaded local model in Settings.")
                return
            with self._lock:
                if self.stop_event.is_set():
                    return
                self.phase = "starting"
                self._token = self.registry.acquire(
                    CAPTIONS, device=str(self.config.get("audio", {}).get("input_device", "")),
                    phase="starting", stop=self.stop,
                )
                self._notify()
            if self.stop_event.is_set():
                return
            stream, rate, channels, _device = open_raw_input_stream(
                samplerate=16000, channels=1,
                device=resolve_input_device(self.config.get("audio", {}).get("input_device", "")),
                callback=on_audio,
            )
            self._stream = stream
            self.sample_rate, self.channels = int(rate), int(channels)
            if self.sample_rate <= 0 or self.channels <= 0:
                raise ValueError("Invalid microphone format")
            target = int(self.sample_rate * self.CHUNK_SECONDS) * self.channels * 2
            if self.stop_event.is_set():
                return
            with stream:
                with self._lock:
                    if not self.stop_event.is_set():
                        self.phase = "listening"
                        self.registry.set_phase(self._token, "listening")
                        self._notify()
                self.stop_event.wait()
        except Exception:
            log.exception("captions capture failed")
            self._fail("The captions microphone could not open or stopped unexpectedly. Check your input in Settings.")
        finally:
            self.stop_event.set()
            self._discard_pending()
            self._close_stream()
            self.capture_done.set()
            self._finish_if_ready()

    def _close_stream(self) -> None:
        with self._close_lock:
            if self._closed:
                return
            try:
                if self._stream is not None:
                    self._stream.close()
            except Exception:
                log.exception("captions microphone close failed")
                self.error = "The captions microphone has not closed. Use Panic Stop to retry."
                self.phase = "stopping"
                self.registry.set_phase(self._token, "stop-failed")
                self._notify()
                return
            self._closed = True
            self.registry.release(self._token)

    def _retry_close(self) -> None:
        try:
            self._close_stream()
            self._finish_if_ready()
        finally:
            self._retry_active = False

    def _decode(self) -> None:
        try:
            from .stt_sessions import transcribe_pcm

            while not self.stop_event.is_set():
                try:
                    chunk = self.chunks.get(timeout=.1)
                except queue.Empty:
                    continue
                if self.stop_event.is_set():
                    break
                try:
                    text = transcribe_pcm(self.config, chunk, self.sample_rate,
                                          self.channels, provider_id="local").strip()
                except Exception:
                    log.exception("captions transcription failed")
                    self._fail("Live captions could not transcribe the audio. Check your local speech model and try again.")
                    break
                if text and not self.stop_event.is_set():
                    def deliver(value=text):
                        if not self.stop_event.is_set():
                            self.on_text(self, value)
                    self.dispatch(deliver)
        except Exception:
            log.exception("captions decoder could not run")
            self._fail("Live captions could not run the speech model. Check your local model in Settings.")
        finally:
            self.decoder_done.set()
            self._finish_if_ready()

    def _finish_if_ready(self) -> None:
        with self._lock:
            if (self.finished.is_set() or not self.capture_done.is_set()
                    or not self.decoder_done.is_set() or not self._closed):
                return
            self.phase = "error" if self.error else "stopped"
            self.finished.set()
            self._notify()
