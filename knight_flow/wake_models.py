"""Resolve an explicitly installed wake model without downloading anything."""
from pathlib import Path


def local_model_options(model: str) -> dict:
    options = {'wakeword_models': [model], 'inference_framework': 'onnx'}
    path = Path(model).expanduser()
    if path.suffix.lower() != '.onnx':
        return options  # Built-in names are resolved by openwakeword itself.
    required = {
        'melspec_model_path': path.parent / 'melspectrogram.onnx',
        'embedding_model_path': path.parent / 'embedding_model.onnx',
    }
    if not path.is_file() or not all(p.is_file() for p in required.values()):
        raise ValueError('Choose a local ONNX wake model beside melspectrogram.onnx and embedding_model.onnx.')
    options['wakeword_models'] = [str(path)]
    options.update({key: str(value) for key, value in required.items()})
    return options
