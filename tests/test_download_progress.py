from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from knight_flow.local_stt import download_progress_mb, local_model_for_id


class AFirstRunDownloadShowsItsProgressTests(unittest.TestCase):
    """640 MB labelled "Downloading" with no number looks like a hang.

    A fresh machine installs 210 MB and then fetches a 640 MB model before the
    first word is transcribed. Until now the only feedback was the word
    "Downloading", which on a slow connection is indistinguishable from a
    frozen application -- and closing it is the reasonable thing to do when
    that is what you believe.

    Hugging Face's own progress bar cannot be used: it is switched off
    deliberately in `_prepare_model_download`, because a frozen windowed build
    has no stderr and printing to it crashed the first-run download outright.
    The bytes are read from the `.incomplete` files it is already writing,
    which costs a directory walk and touches nothing the download relies on.
    """

    def model(self):
        return local_model_for_id("parakeet-tdt-0.6b-v3")

    def test_it_reports_the_expected_size_before_anything_arrives(self) -> None:
        """So the panel can say "640 MB" rather than nothing at all."""
        with patch("knight_flow.local_stt.Path") as fake_path:
            fake_path.return_value.is_dir.return_value = False
            fetched, expected = download_progress_mb(self.model())
        self.assertEqual(fetched, 0.0)
        self.assertEqual(expected, 640.0)

    def test_it_counts_partial_files(self) -> None:
        model = self.model()
        with self.tempCache() as cache:
            blobs = cache / "models--someone--parakeet" / "blobs"
            blobs.mkdir(parents=True)
            (blobs / "a.incomplete").write_bytes(b"x" * (7 * 1048576))
            (blobs / "b.incomplete").write_bytes(b"x" * (3 * 1048576))
            fetched, expected = download_progress_mb(model)
        self.assertAlmostEqual(fetched, 10.0, places=1)
        self.assertEqual(expected, 640.0)

    def test_a_finished_file_is_not_counted(self) -> None:
        """Only `.incomplete` is in flight. Counting finished blobs would show
        a bar that starts near 100% on a machine with other models installed."""
        with self.tempCache() as cache:
            blobs = cache / "models--someone--parakeet" / "blobs"
            blobs.mkdir(parents=True)
            (blobs / "finished-blob").write_bytes(b"x" * (50 * 1048576))
            fetched, _ = download_progress_mb(self.model())
        self.assertEqual(fetched, 0.0)

    def test_an_unreadable_cache_reports_zero_rather_than_raising(self) -> None:
        """This runs on the first-run path. Raising here would turn a cosmetic
        progress figure into a failed model download."""
        with patch("knight_flow.local_stt.Path", side_effect=OSError("nope")):
            fetched, expected = download_progress_mb(self.model())
        self.assertEqual(fetched, 0.0)
        self.assertEqual(expected, 640.0)

    def test_every_local_model_advertises_a_size(self) -> None:
        """Without one the panel has no denominator and falls back to the
        wordless message this exists to replace."""
        from knight_flow.local_stt import LOCAL_MODELS

        missing = [m.id for m in LOCAL_MODELS if not getattr(m, "size_mb", 0)]
        self.assertEqual(missing, [], f"models with no size: {missing}")

    # -- helper -------------------------------------------------------------
    def tempCache(self):
        import contextlib
        import tempfile

        @contextlib.contextmanager
        def _cache():
            with tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                with patch("huggingface_hub.constants.HF_HUB_CACHE", str(root)):
                    yield root

        return _cache()


if __name__ == "__main__":
    unittest.main()


class BothDownloadMessagesComeFromOnePlaceTests(unittest.TestCase):
    """The wordless message existed twice and only one copy got fixed.

    app.py had "Downloading local model. One-time setup." in the session path,
    shown when a dictation triggers the download and the pill is the only thing
    on screen, and a second variant in the prefetch path. Fixing one left the
    other silent -- and the session path is the worse of the two, because there
    is no Settings panel to look at instead.
    """

    def source(self) -> str:
        return (Path(__file__).resolve().parents[1] / "knight_flow" / "app.py").read_text(encoding="utf-8")

    def test_no_wordless_download_message_survives(self) -> None:
        source = self.source()
        stale = '"Downloading local model. One-time setup."'
        # Permitted exactly once: the fallback inside the helper itself, for
        # when the progress read fails.
        self.assertLessEqual(
            source.count(stale), 1,
            "a download message with no byte count is back; on a 640 MB first "
            "run that is indistinguishable from a hang",
        )

    def test_both_paths_call_the_same_helper(self) -> None:
        source = self.source()
        self.assertGreaterEqual(
            source.count("_local_download_message"), 3,
            "definition plus both call sites -- two copies drifted apart once already",
        )


class AFailedDownloadSaysRetryingIsCheapTests(unittest.TestCase):
    """"Model download failed: <exception>" reads as "start the 640 MB again".

    It does not. huggingface_hub keeps the partial file and resumes with an
    HTTP Range request -- verified: it writes `.incomplete` parts and dropped
    its `resume_download` flag because resuming became unconditional.

    So the person is one click from finishing and the message implies they are
    back at the beginning. On the first-run path, after a 640 MB download has
    already failed once, that is the difference between a retry and an
    uninstall.
    """

    def source(self) -> str:
        return (Path(__file__).resolve().parents[1] / "knight_flow" / "overlay.py").read_text(encoding="utf-8")

    def test_the_failure_message_says_it_resumes(self) -> None:
        source = self.source()
        self.assertIn("resumes from where it stopped", source)

    def test_it_names_the_model_rather_than_saying_model(self) -> None:
        """"Could not download Parakeet TDT 0.6B v3" tells someone which of
        several downloads failed; "Model download failed" does not."""
        source = self.source()
        self.assertIn('f"Could not download {model.label}', source)

    def test_resume_is_actually_true_before_the_message_claims_it(self) -> None:
        """The claim has to keep being true. If a future dependency stops
        resuming, this message becomes a lie that costs someone 640 MB."""
        import inspect

        from huggingface_hub import hf_hub_download

        module_source = inspect.getsource(inspect.getmodule(hf_hub_download))
        self.assertIn(".incomplete", module_source)
        self.assertIn("Range", module_source)
