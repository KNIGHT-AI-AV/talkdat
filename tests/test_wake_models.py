from pathlib import Path
import tempfile
import unittest

from knight_flow.wake_models import local_model_options


class WakeModelPathsTests(unittest.TestCase):
    def test_custom_model_uses_its_own_feature_models(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('my wake.onnx', 'melspectrogram.onnx', 'embedding_model.onnx'):
                (root / name).write_bytes(b'fixture, not an actual neural model')
            options = local_model_options(str(root / 'my wake.onnx'))
            self.assertEqual(options['wakeword_models'], [str(root / 'my wake.onnx')])
            self.assertEqual(options['melspec_model_path'], str(root / 'melspectrogram.onnx'))
            self.assertEqual(options['embedding_model_path'], str(root / 'embedding_model.onnx'))

    def test_missing_companion_is_reported_before_microphone_or_model_load(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'wake.onnx'
            path.write_bytes(b'fixture')
            with self.assertRaisesRegex(ValueError, 'melspectrogram.onnx and embedding_model.onnx'):
                local_model_options(str(path))

    def test_named_installed_models_keep_upstream_resolution(self):
        self.assertEqual(local_model_options('hey_jarvis'),
                         {'wakeword_models': ['hey_jarvis'], 'inference_framework': 'onnx'})
