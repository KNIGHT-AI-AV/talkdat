"""Opt-in wake recognition with bounded callbacks and visible audio ownership."""

from __future__ import annotations
import copy, math, queue, threading, time
from collections.abc import Callable
from typing import Any
from .mic_registry import DEFERRED_MICROPHONE_RELEASE


class WakeWordListener:
    MAX_PENDING = 8
    MAX_BLOCK = 65536

    def __init__(
        self, config, *, on_wake: Callable[[], None], on_status: Callable[[str], None]
    ):
        self.config = copy.deepcopy(config)
        self.on_wake = on_wake
        self.on_status = on_status
        self._stop_event = threading.Event()
        self._thread = None
        self._decoder = None
        self._lock = threading.RLock()
        self._close_lock = threading.Lock()
        self._restart = None
        self._stream = None
        self._token = None
        self._registry = None
        self._desired = False
        self._cancelled = False
        self._detected = False
        self.closed = threading.Event()
        self.closed.set()
        self.failed = False
        self.phase = "idle"
        self.message = ""
        self._pending = queue.Queue(maxsize=self.MAX_PENDING)
        self.sample_rate = 16000
        self.generation = 0
        self._retry_active = False

    @property
    def running(self):
        return bool(self._thread and self._thread.is_alive())

    def _status(self, phase, message):
        self.phase, self.message = phase, message
        try:
            self.on_status(message)
        except Exception:
            pass

    def start(self):
        with self._lock:
            self._desired = True
            if self.running and not self._stop_event.is_set():
                return
            previous = self._thread
            if (previous and previous.is_alive()) or (
                self._decoder and self._decoder.is_alive()
            ):
                if self._restart and self._restart.is_alive():
                    return

                def restart():
                    while self._desired:
                        threads = (previous, self._decoder)
                        if not any(item and item.is_alive() for item in threads):
                            self.start()
                            return
                        for item in threads:
                            if item and item is not threading.current_thread():
                                item.join(0.1)

                self._restart = threading.Thread(
                    target=restart, name="TalkDatWakeRestart", daemon=True
                )
                self._restart.start()
                return
            if self._stream is not None:
                self._status(
                    "close-failed",
                    "Wake microphone is still closing. Use Panic Stop to retry.",
                )
                return
            self._stop_event.clear()
            self._cancelled = False
            self._detected = False
            self.failed = False
            self.generation += 1
            self._pending = queue.Queue(maxsize=self.MAX_PENDING)
            self._thread = threading.Thread(
                target=self._run, name="TalkDatWakeWord", daemon=True
            )
            try:
                self._thread.start()
            except Exception:
                self.failed = True
                self._status(
                    "error", "Wake word could not start. Turn it off and on to retry."
                )

    def stop(self):
        with self._lock:
            self._desired = False
            self._cancelled = True
            self._stop_event.set()
            if self._token is not None and self._registry is not None:
                self._registry.set_phase(self._token, "closing")
            # The capture worker normally owns close. A failed close can be
            # retried independently of a decoder that is still unwinding.
            if self._stream is not None and not self.running and not self._retry_active:
                self._retry_active = True

                def retry_close():
                    try:
                        self._close()
                    finally:
                        self._retry_active = False

                worker = threading.Thread(
                    target=retry_close, name="TalkDatWakeClose", daemon=True
                )
                try:
                    worker.start()
                except Exception:
                    self._retry_active = False
                    self._status(
                        "close-failed",
                        "Wake microphone could not close. Use Panic Stop to retry.",
                    )
        return DEFERRED_MICROPHONE_RELEASE

    def _problem(self, message):
        self.failed = True
        self.message = message
        self._stop_event.set()

    def _callback(self, indata, frames, time_info, status):
        if self._stop_event.is_set():
            return
        if status:
            self._problem(
                "Wake word stopped after an audio interruption. Turn it off and on to retry."
            )
            return
        try:
            size = len(indata)
            if size > self.MAX_BLOCK or size % 2:
                self._problem(
                    "Wake word received an unsupported audio block. Turn it off and on to retry."
                )
                return
            raw = bytes(indata)
            self._pending.put_nowait(raw)
        except queue.Full:
            self._problem(
                "Wake word could not keep up with audio. Turn it off and on to retry."
            )
        except Exception:
            self._problem(
                "Wake word audio stopped unexpectedly. Turn it off and on to retry."
            )

    def _decode(self, model, threshold, rate):
        import numpy as np

        pending = bytearray()
        resampler = None
        try:
            if rate != 16000:
                import av

                resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
            while not self._stop_event.is_set():
                try:
                    raw = self._pending.get(timeout=0.1)
                except queue.Empty:
                    continue
                if self._stop_event.is_set():
                    return
                if resampler is not None:
                    frame = av.AudioFrame.from_ndarray(
                        np.frombuffer(raw, dtype="<i2").reshape(1, -1),
                        format="s16",
                        layout="mono",
                    )
                    frame.sample_rate = rate
                    raw = b"".join(
                        item.to_ndarray().tobytes()
                        for item in resampler.resample(frame)
                    )
                pending.extend(raw)
                while len(pending) >= 2560 and not self._stop_event.is_set():
                    block = bytes(pending[:2560])
                    del pending[:2560]
                    scores = model.predict(np.frombuffer(block, dtype="<i2"))
                    if self._stop_event.is_set():
                        return
                    values = [
                        float(value)
                        for value in scores.values()
                        if math.isfinite(float(value))
                    ]
                    if max(values, default=0) >= threshold:
                        self._detected = True
                        self._stop_event.set()
                        return
        except Exception:
            self._problem("Wake recognition stopped. Turn it off and on to retry.")

    def _close(self):
        with self._close_lock:
            stream = self._stream
            if stream is not None:
                if self._token is not None:
                    self._registry.set_phase(self._token, "closing")
                try:
                    stream.stop()
                except Exception:
                    pass
                try:
                    stream.close()
                except Exception:
                    self.failed = True
                    if self._token is not None:
                        self._registry.set_phase(self._token, "stop-failed")
                    self._status(
                        "close-failed",
                        "Wake microphone has not closed. Use Panic Stop to retry.",
                    )
                    return False
                self._stream = None
            if self._registry is not None:
                self._registry.release(self._token)
            self._token = None
            self.closed.set()
            return True

    def _run(self):
        from .audio_input import open_raw_input_stream, resolve_input_device
        from .mic_registry import microphone_registry

        try:
            settings = self.config.get("wake_word", {})
            threshold = settings.get("threshold", 0.55)
            if (
                type(threshold) not in (int, float)
                or not math.isfinite(threshold)
                or not 0.05 <= threshold <= 1
            ):
                self._problem("Choose a wake sensitivity between 0.05 and 1.")
                return
            model_name = settings.get("model", "hey_jarvis")
            if (
                type(model_name) is not str
                or not model_name.strip()
                or len(model_name) > 4096
            ):
                self._problem("Choose an installed wake-word model.")
                return
            self._status("preparing", "Preparing wake word. The microphone is off.")
            try:
                from .wake_models import local_model_options
                options = local_model_options(model_name)
            except ValueError as error:
                self._problem(str(error))
                return
            try:
                from openwakeword.model import Model

                model = Model(**options)
            except Exception:
                self._problem(
                    "The wake-word model is unavailable. Prepare a compatible local model before enabling wake word."
                )
                return
            if self._stop_event.is_set():
                return
            selected = self.config.get("audio", {}).get("input_device", "")
            device = resolve_input_device(selected)
            if str(selected or "").strip() and device is None:
                self._problem(
                    "The selected microphone is unavailable. Reconnect it or choose another input."
                )
                return
            # Reserve ownership under the same lock as stop(), so a stop during
            # model/device preparation cannot be followed by a late open.
            with self._lock:
                if self._stop_event.is_set():
                    return
                self._registry = microphone_registry()
                self.closed.clear()
                self._token = self._registry.acquire(
                    "wake-word",
                    device=str(selected or "System default microphone"),
                    stop=self.stop,
                )
            stream, rate, channels, _ = open_raw_input_stream(
                samplerate=16000,
                channels=1,
                blocksize=1280,
                device=device,
                callback=self._callback,
                allow_device_fallback=False,
            )
            self._stream = stream
            self.sample_rate = rate
            if self._stop_event.is_set():
                return
            self._decoder = threading.Thread(
                target=self._decode,
                args=(model, float(threshold), rate),
                name="TalkDatWakePredict",
                daemon=True,
            )
            self._decoder.start()
            stream.start()
            self._registry.set_phase(self._token, "listening")
            self._status(
                "listening", "Wake word is listening on your selected microphone."
            )
            while not self._stop_event.wait(0.05):
                if getattr(stream, "active", None) is False:
                    self._problem(
                        "Wake microphone stopped unexpectedly. Turn it off and on to retry."
                    )
        except Exception:
            self._problem(
                "Wake word could not open the selected microphone. Check the input and its permissions."
            )
        finally:
            closed = self._close()
            if closed:
                if self._detected and not self._cancelled and not self.failed:
                    self._status(
                        "detected",
                        "Wake phrase detected. Wake microphone closed before dictation.",
                    )
                    try:
                        self.on_wake()
                    except Exception:
                        self._status(
                            "error",
                            "Wake phrase was detected, but dictation could not start.",
                        )
                elif self.failed:
                    self._status("error", self.message)
                else:
                    self._status(
                        "stopped", "Wake word stopped. Its microphone is closed."
                    )
