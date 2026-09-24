"""Enumerate microphone names without blocking the application UI or opening a stream."""
import threading


class InputDevices:
    def __init__(self):
        self._lock = threading.Lock()
        self._state = {'status':'idle', 'devices':[], 'message':''}

    def snapshot(self):
        with self._lock:
            return {**self._state, 'devices':list(self._state['devices'])}

    def refresh(self):
        with self._lock:
            if self._state['status'] == 'loading':
                return {**self._state, 'devices':list(self._state['devices'])}
            self._state['status'] = 'loading'
        def load():
            try:
                from knight_flow.audio_input import list_input_devices
                devices = list_input_devices()
                result = {'status':'ready', 'devices':devices,
                          'message':'' if devices else 'No microphones were found. Mic Doctor can help check your input.'}
            except Exception:
                result = {'status':'error', 'devices':[], 'message':'Microphones could not be listed. Try Refresh or Mic Doctor.'}
            with self._lock:
                self._state = result
        threading.Thread(target=load, name='TalkDatMicrophones', daemon=True).start()
        return self.snapshot()
