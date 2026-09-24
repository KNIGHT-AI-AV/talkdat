"""X-476: the CUDA runtime is fetched on request, never bundled.

Measured on his own spooled dictations, 75.7 s of real speech: on an NVIDIA
card Whisper runs FASTER than the Parakeet we ship (717 ms against 1104 ms
average) and is the more accurate model class. The only thing between a person
and that is two CUDA libraries.

They are 1.2 GB against a 465 MB installer and they help one vendor's hardware.
So they are fetched the way models already are, and the rules below are what
keep that honest.

  * NOTHING SHIPS THEM. The installer must not grow for the majority of users
    who will never benefit. That is enforced in the spec's excludes (X-475)
    and asserted here too, because the build installs into the same venv a
    developer measures in and one stray `pip install` would otherwise triple
    everyone's download.
  * Not pip. The shipped app is frozen: no pip, no site-packages to write to.
    A wheel is a zip, so only the bin/*.dll members are kept, in a directory
    the app owns.
  * Pinned by URL AND checksum. This is half a gigabyte of native code that
    gets loaded into the process. "Whatever PyPI serves today" is not a
    sufficient answer, which is the same reasoning that already pins model
    revisions.
  * Verified before anything is placed. An interrupted download must never
    leave a half-written DLL that loads and then takes the process down, so
    it stages and only moves after the checksum passes.
  * Asked for, never assumed. A gigabyte is the person's bandwidth and disk.
    This module carries out the decision; it never makes it.
"""

from __future__ import annotations

import unittest
from unittest import mock

from knight_flow import cuda_runtime


class ItIsNeverBundledTests(unittest.TestCase):
    def test_the_build_excludes_the_wheels(self) -> None:
        """The installer is 465 MB. These are 1.2 GB and help one vendor."""
        from pathlib import Path

        spec = (Path(__file__).resolve().parents[1] / "Talk Dat!.spec").read_text(encoding="utf-8")
        self.assertIn('"nvidia"', spec,
                      "the build no longer excludes the CUDA wheels, so the "
                      "installer can silently triple in size")

    def test_it_lives_beside_the_models_not_in_site_packages(self) -> None:
        """A frozen app cannot write to site-packages, and must not try."""
        self.assertNotIn("site-packages", str(cuda_runtime.cuda_dir()))
        self.assertTrue(str(cuda_runtime.cuda_dir()).endswith("cuda"))


class EveryDownloadIsPinnedTests(unittest.TestCase):
    def test_each_wheel_has_a_url_and_a_checksum(self) -> None:
        self.assertTrue(cuda_runtime.WHEELS, "there are no wheels to fetch")
        for wheel in cuda_runtime.WHEELS:
            with self.subTest(wheel=wheel.name):
                self.assertTrue(wheel.url.startswith("https://"), "not fetched over https")
                self.assertEqual(len(wheel.sha256), 64, "not a sha256")
                self.assertIn(wheel.version, wheel.url,
                              "the pinned version and the pinned URL disagree")

    def test_the_stated_size_is_honest(self) -> None:
        """The number shown to a person before they agree to spend it."""
        self.assertGreater(cuda_runtime.TOTAL_MB, 1000)
        self.assertLess(cuda_runtime.TOTAL_MB, 1600)


class ABadDownloadInstallsNothingTests(unittest.TestCase):
    def test_a_wrong_checksum_refuses(self) -> None:
        """A truncated download that still unpacked would leave a DLL that
        loads and then takes the process down with it."""
        import tempfile
        from pathlib import Path

        with tempfile.NamedTemporaryFile(delete=False, suffix=".whl") as handle:
            handle.write(b"not really a wheel")
            path = Path(handle.name)
        try:
            with self.assertRaises(RuntimeError) as caught:
                cuda_runtime._verify(path, "0" * 64)
            self.assertIn("nothing was installed", str(caught.exception).lower())
        finally:
            path.unlink(missing_ok=True)

    def test_only_dlls_are_kept(self) -> None:
        """A wheel carries headers, metadata and a tree none of this needs."""
        import tempfile
        import zipfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as workspace:
            wheel = Path(workspace) / "fake.whl"
            with zipfile.ZipFile(wheel, "w") as archive:
                archive.writestr("nvidia/cublas/bin/cublas64_12.dll", b"MZ fake")
                archive.writestr("nvidia/cublas/include/cublas.h", b"header")
                archive.writestr("nvidia_cublas_cu12.dist-info/METADATA", b"meta")
            into = Path(workspace) / "out"
            into.mkdir()
            kept = cuda_runtime._extract_dlls(wheel, into)

        self.assertEqual(kept, 1)


class ItIsOfferedOnlyWhereItHelpsTests(unittest.TestCase):
    def test_a_machine_with_no_nvidia_card_is_not_offered_it(self) -> None:
        """On any other machine the gigabyte buys precisely nothing."""
        with mock.patch.object(cuda_runtime.subprocess, "run",
                               side_effect=OSError("no nvidia-smi")):
            self.assertFalse(cuda_runtime.nvidia_gpu_present())

    def test_a_failing_probe_is_a_no_not_a_crash(self) -> None:
        """This runs before a menu is drawn. It may not raise there."""
        with mock.patch.object(cuda_runtime.subprocess, "run",
                               return_value=mock.Mock(returncode=1, stdout="")):
            self.assertFalse(cuda_runtime.nvidia_gpu_present())

    def test_the_search_path_is_empty_until_it_is_installed(self) -> None:
        """Nothing is put on PATH on a machine that never asked for this."""
        with mock.patch.object(cuda_runtime, "is_installed", return_value=False):
            self.assertEqual(cuda_runtime.library_dirs(), [])

    def test_the_engine_looks_at_the_apps_own_copy_first(self) -> None:
        """A frozen build has no site-packages, so the app's own directory is
        the one that matters."""
        from knight_flow import local_stt

        with mock.patch.object(cuda_runtime, "is_installed", return_value=True):
            self.assertIn(str(cuda_runtime.cuda_dir()), local_stt._nvidia_library_dirs())


class ItCanBeGivenBackTests(unittest.TestCase):
    def test_removing_it_reports_what_was_freed(self) -> None:
        """A gigabyte the person can take back, and be told how much."""
        self.assertTrue(hasattr(cuda_runtime, "remove"))
        with mock.patch.object(cuda_runtime, "installed_size_mb", return_value=1226), \
             mock.patch.object(cuda_runtime.shutil, "rmtree"):
            self.assertEqual(cuda_runtime.remove(), 1226)


if __name__ == "__main__":
    unittest.main()
