"""X-237: a model download must fetch the commit we audited, not today's `main`.

`WhisperModel("large-v3-turbo")` resolves to a Hugging Face repo owned by
somebody else and downloads whatever the default branch points at when the
user happens to click Download. A repo owner -- or whoever takes over that
account -- can rewrite the branch, and every install picks up different weights
with nothing to notice.

Severity, stated honestly rather than inflated: these are CTranslate2 binaries,
not pickles, so this is "you are running software you did not audit", not
remote code execution. Worth fixing, not worth panic.

WHAT THIS CANNOT PROVE: that the pinned commit is itself trustworthy, or that
Hugging Face serves the bytes that commit names. It proves the request asks for
a fixed commit instead of a moving branch.
"""

from __future__ import annotations

import re
import unittest

from knight_flow.local_stt import (
    LOCAL_MODELS,
    _PINNED_REVISIONS,
    LocalModel,
    pinned_revision,
)

FULL_SHA = re.compile(r"^[0-9a-f]{40}$")


class EveryBundledWhisperModelIsPinnedTests(unittest.TestCase):
    def test_none_are_missing(self) -> None:
        """The one that matters: adding a model without pinning it fails here
        rather than shipping an unpinned download to everybody."""
        unpinned = [
            model.id for model in LOCAL_MODELS
            if model.engine == "faster_whisper" and not pinned_revision(model)
        ]
        self.assertEqual(
            unpinned, [],
            "these download from a moving branch; run scripts/refresh_model_pins.py",
        )

    def test_the_pins_are_full_commit_shas(self) -> None:
        """A tag or a branch name would satisfy `revision=` and defeat the point:
        both can be repointed at different bytes by whoever owns the repo."""
        for name, revision in _PINNED_REVISIONS.items():
            with self.subTest(model=name):
                self.assertRegex(revision, FULL_SHA)

    def test_the_table_has_no_entries_for_models_we_do_not_ship(self) -> None:
        """A stale pin is a quiet lie about what is covered."""
        shipped = {model.engine_id for model in LOCAL_MODELS if model.engine == "faster_whisper"}
        self.assertEqual(set(_PINNED_REVISIONS) - shipped, set())


class WhatIsDeliberatelyNotPinnedTests(unittest.TestCase):
    """Stated in a test so the gaps are a decision, not an oversight."""

    def test_onnx_models_are_not_claimed_to_be_pinned(self) -> None:
        """onnx_asr.load_model() takes no revision argument, so there is nowhere
        to put one. Listing them in the table would assert a protection that
        does not exist -- worse than the gap itself."""
        import inspect

        import onnx_asr

        self.assertNotIn(
            "revision", inspect.signature(onnx_asr.load_model).parameters,
            "onnx_asr grew a revision parameter -- the onnx models can be pinned now",
        )
        for model in LOCAL_MODELS:
            if model.engine == "onnx_asr":
                self.assertIsNone(pinned_revision(model))

    def test_a_users_own_model_is_not_pinned(self) -> None:
        """They chose the repo. We have no basis for deciding which commit of it
        they meant, and guessing one would break their model for no benefit."""
        theirs = LocalModel(
            id="custom:someone/their-model",
            label="Theirs",
            engine="faster_whisper",
            engine_id="someone/their-model",
            size_mb=1,
            languages="en",
        )
        self.assertIsNone(pinned_revision(theirs))


class ThePinReachesTheDownloaderTests(unittest.TestCase):
    def test_the_revision_is_passed_to_whisper_model(self) -> None:
        """A table nothing reads is the same as no table."""
        from unittest.mock import patch

        from knight_flow import local_stt

        model = next(m for m in LOCAL_MODELS if m.engine == "faster_whisper")
        seen: dict = {}

        class FakeWhisperModel:
            def __init__(self, name, **kwargs):
                seen["name"] = name
                seen.update(kwargs)

        with patch.object(local_stt, "_prepare_model_download", lambda: None):
            with patch.dict("sys.modules", {"faster_whisper": type("M", (), {"WhisperModel": FakeWhisperModel})}):
                local_stt._load_faster_whisper(model)

        self.assertEqual(seen["name"], model.engine_id)
        self.assertEqual(seen["revision"], pinned_revision(model))
        self.assertRegex(seen["revision"], FULL_SHA)
