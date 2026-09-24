"""Existing local model operations, with bounded UI actions and async progress."""
from __future__ import annotations
import threading

from knight_flow.local_stt import available_local_models, delete_model, download_model, is_downloaded, model_dir, models_dir, CUSTOM_MODEL_PREFIX


class ModelManager:
    def __init__(self, config, capture_busy, *, start_worker=None, serialize_delete=None):
        self.config, self.capture_busy = config, capture_busy
        self.status = {}
        self.lock = threading.Lock()
        self.start_worker = start_worker or (lambda work: threading.Thread(target=work, name='TalkDatModelDownload', daemon=True).start())
        self.serialize_delete = serialize_delete or (lambda operation: operation())

    def snapshot(self):
        with self.lock:
            statuses = {key:dict(value) for key,value in self.status.items()}
        active = self.config.get('stt', {}).get('providers', {}).get('local', {}).get('model')
        return [{'id':model.id, 'label':model.label, 'languages':model.languages, 'notes':model.notes,
                 'size_mb':model.size_mb, 'downloaded':is_downloaded(model), 'active':model.id==active,
                 'custom':model.id.startswith(CUSTOM_MODEL_PREFIX),
                 **statuses.get(model.id, {'state':'idle', 'message':''})}
                for model in available_local_models(self.config)]

    def request(self, operation, identifier):
        model = next((model for model in available_local_models(self.config) if model.id == identifier), None)
        if model is None or operation not in {'download','delete'}:
            raise ValueError('That model action is not available.')
        with self.lock:
            if self.status.get(identifier, {}).get('state') == 'working':
                return {'message':'This model is already being prepared.'}
        if operation == 'delete':
            if model.id.startswith(CUSTOM_MODEL_PREFIX):
                raise ValueError('Remove a custom model from your list in Advanced model settings. Its source files are kept.')
            if self.capture_busy():
                raise ValueError('Finish the current dictation before removing a speech model.')
            root, target = models_dir().resolve(), model_dir(model).resolve()
            if target == root or not target.is_relative_to(root):
                raise ValueError('This model is outside Talk DAT storage and cannot be removed here.')
            self.serialize_delete(lambda: delete_model(model))
            if target.exists():
                raise ValueError('Some model files are still in use. Restart Talk DAT, then try removing the download again.')
            with self.lock:
                self.status[identifier] = {'state':'idle', 'message':'Removed from local storage. Choose Download to install it again.'}
            return {'message':'Model removed from local storage.'}
        with self.lock:
            self.status[identifier] = {'state':'working', 'message':'Preparing download...'}
        def update(message):
            labels = {'downloading_model':'Downloading...', 'loading_model':'Loading...',
                      'verifying_model':'Verifying...', 'model_ready':'Ready.'}
            with self.lock:
                self.status[identifier] = {'state':'working', 'message':labels.get(message,'Preparing model...')}
        def worker():
            try:
                download_model(model, update)
                result = {'state':'ready', 'message':'Downloaded and ready to use.'}
            except Exception:
                result = {'state':'error', 'message':'Download failed. Choose Download to retry; partial downloads can resume.'}
            with self.lock:
                self.status[identifier] = result
        try:
            self.start_worker(worker)
        except Exception:
            with self.lock:
                self.status[identifier] = {'state':'error', 'message':'Download could not start. Choose Download to try again.'}
            raise ValueError('The model download could not start.') from None
        return {'message':'Model download started.'}
