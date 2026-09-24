"""Explicit system-output capture. It never substitutes a microphone."""
from __future__ import annotations
import sys,threading


class WindowsLoopbackStream:
    def __init__(self,callback):
        import pyaudiowpatch as audio
        self.manager=audio.PyAudio();self.stream=None;self._closed=False;self._lock=threading.RLock();self.error=''
        try:
            device=self.manager.get_default_wasapi_loopback()
            if not device.get('isLoopbackDevice'):raise RuntimeError('The default output has no loopback capture device.')
            self.samplerate=int(device['defaultSampleRate']);self.channels=int(device['maxInputChannels'])
            if self.samplerate<=0 or not 1<=self.channels<=8:raise RuntimeError('The output capture format is unavailable.')
            self.device=str(device.get('name','System output'))
            def receive(data,frames,timing,status):
                if self._closed:return (None,audio.paComplete)
                try:callback(data,frames,timing,status)
                except Exception:
                    self.error='System audio could not be kept. Recording stopped.'
                    return (None,audio.paAbort)
                return (None,audio.paContinue)
            self.stream=self.manager.open(format=audio.paInt16,channels=self.channels,rate=self.samplerate,
                input=True,input_device_index=device['index'],frames_per_buffer=1024,stream_callback=receive,start=False)
        except Exception:
            self.manager.terminate();self._closed=True;raise
    @property
    def active(self):return not self._closed and bool(self.stream and self.stream.is_active())
    def start(self):
        try:self.stream.start_stream()
        except Exception:
            self.close();raise
        return self
    def stop(self):
        if not self._closed and self.stream:self.stream.stop_stream()
    def close(self):
        with self._lock:
            if self._closed:return
            if self.stream:self.stream.close()
            self.manager.terminate();self._closed=True
    def __enter__(self):return self.start()
    def __exit__(self,*_):
        try:self.stop()
        finally:self.close()


def open_loopback_stream(callback):
    if sys.platform=='darwin':
        from .mac_system_audio import MacLoopbackStream
        return MacLoopbackStream(callback)
    if sys.platform!='win32':raise RuntimeError('System-output capture is not available on this platform yet. Choose microphone notes explicitly.')
    try:return WindowsLoopbackStream(callback)
    except ImportError:raise RuntimeError('System-output capture needs the bundled Windows audio component. Repair or update Talk DAT.') from None
