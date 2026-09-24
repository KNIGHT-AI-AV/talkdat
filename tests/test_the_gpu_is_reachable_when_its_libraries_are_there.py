"""X-475: the CUDA libraries were present and unreachable.

X-473 stopped a machine with no CUDA runtime from failing every Whisper
dictation. This is the other half: a machine that HAS the runtime could not use
it either, for a reason that is pure Windows.

`nvidia-cublas-cu12` and `nvidia-cudnn-cu12` are ordinary pip wheels. They put
`cublas64_12.dll` and friends in `site-packages/nvidia/*/bin`, which is not on
any DLL search path. Registering those directories with
`os.add_dll_directory()` is the obvious move and IT DOES NOT WORK: that call
only helps a loader that opts into user directories via
`LOAD_LIBRARY_SEARCH_USER_DIRS`, and CTranslate2 loads cuBLAS by bare name. So
the DLL sits on disk, 98 MB of it, while the error says "not found or cannot be
loaded". Putting the directories on PATH works, and was verified on the real
engine before this was written.

Why it is worth the trouble, measured on his own five spooled dictations,
75.7 s of real speech rather than a synthetic clip:

    parakeet-tdt-0.6b-v3     1104 ms avg   13.7x realtime
    whisper-large-v3-turbo    854 ms avg   17.7x realtime
    distil-large-v3.5         717 ms avg   21.1x realtime

Whisper on CUDA is FASTER than Parakeet on real dictation, not slower, and it
is the more accurate model class. A synthetic text-to-speech clip said the
opposite, which is its own lesson: all three scored an identical 19.6% word
error on it, and three different architectures agreeing to one decimal place
is a broken measurement rather than a result.

What this pins:

  * the wheel directories go on PATH, not merely into add_dll_directory,
    because only one of those two actually works here;
  * it happens before the engine loads, since CTranslate2 resolves cuBLAS on
    first inference and PATH is read at that moment;
  * a machine without the wheels is untouched and silent. Most installs will
    never have them, and this must not warn, slow down, or change behaviour
    there;
  * DirectML is not disturbed. Parakeet stays the universal default and the
    only engine that needs no vendor runtime at all.

WHAT THIS CANNOT PROVE: that CUDA then works. The libraries can be present and
still mismatched against the driver, which is exactly what X-473's fallback is
for. This makes them reachable; that one catches them failing anyway.
"""

from __future__ import annotations

import os
import unittest
from unittest import mock

from knight_flow import local_stt


class TheWheelDirectoriesReachThePathTests(unittest.TestCase):
    def setUp(self) -> None:
        self._path = os.environ.get("PATH", "")
        self.addCleanup(lambda: os.environ.__setitem__("PATH", self._path))

    def test_a_machine_without_the_wheels_is_untouched(self) -> None:
        """Most installs will never carry them. Nothing may change there: no
        warning, no delay, no altered PATH."""
        with mock.patch.object(local_stt, "_nvidia_library_dirs", return_value=[]):
            before = os.environ.get("PATH", "")
            local_stt.make_cuda_libraries_reachable()
            self.assertEqual(os.environ.get("PATH", ""), before)

    def test_the_directories_are_put_on_path(self) -> None:
        """os.add_dll_directory alone leaves the DLL unreachable: it only helps
        a loader that opts into user directories, and CTranslate2 does not.
        PATH is the thing that works."""
        # No drive letter: os.pathsep is ":" on macOS/Linux, and "X:" would
        # itself be split apart by the very separator this test checks.
        fake = [os.path.join(os.sep + "wheels", "site-packages", "nvidia", "cublas", "bin")]
        with mock.patch.object(local_stt, "_nvidia_library_dirs", return_value=fake):
            local_stt.make_cuda_libraries_reachable()
        self.assertIn(fake[0], os.environ["PATH"].split(os.pathsep))

    def test_it_does_not_grow_path_without_end(self) -> None:
        """It runs before every GPU load. Appending each time would push PATH
        past the length Windows will accept after enough dictations."""
        fake = [os.path.join(os.sep + "wheels", "site-packages", "nvidia", "cublas", "bin")]
        with mock.patch.object(local_stt, "_nvidia_library_dirs", return_value=fake):
            for _ in range(5):
                local_stt.make_cuda_libraries_reachable()
        self.assertEqual(os.environ["PATH"].split(os.pathsep).count(fake[0]), 1)

    def test_the_existing_path_survives(self) -> None:
        """Everything else on PATH still has to work. This adds, never replaces."""
        os.environ["PATH"] = os.sep + "keep"
        fake = [os.path.join(os.sep + "wheels", "nvidia", "cublas", "bin")]
        with mock.patch.object(local_stt, "_nvidia_library_dirs", return_value=fake):
            local_stt.make_cuda_libraries_reachable()
        self.assertIn(os.sep + "keep", os.environ["PATH"].split(os.pathsep))


class ItRunsBeforeTheEngineLoadsTests(unittest.TestCase):
    def test_the_gpu_loader_asks_first(self) -> None:
        """CTranslate2 resolves cuBLAS on first inference and reads PATH then,
        so this has to happen before the model is built, not after."""
        import inspect

        source = inspect.getsource(local_stt._load_faster_whisper)
        self.assertIn("make_cuda_libraries_reachable", source,
                      "the whisper loader never makes the CUDA libraries reachable")

    def test_directml_is_left_alone(self) -> None:
        """Parakeet runs on onnx-asr through DirectML and needs no vendor
        runtime. It is the universal default and must not be routed through
        any of this."""
        import inspect

        source = inspect.getsource(local_stt._load_onnx_asr)
        self.assertNotIn("make_cuda_libraries_reachable", source,
                         "the DirectML path was made to depend on CUDA")


if __name__ == "__main__":
    unittest.main()
