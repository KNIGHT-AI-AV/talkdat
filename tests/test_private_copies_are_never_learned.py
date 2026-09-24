"""X-604: the clipboard learner never learns, stores or shows a password.

Found 2026-09-23: _clipboard_learn_tick reads the clipboard every 1.1 s and
learns any token mixing letters and digits on sight, so a password copied out
of a password manager ("Kx7mQ2vp9RtZ") was added to the dictionary, saved to
the config and shown in the pop-over above the Pill. Two guards now:
  - a copy its app marked private (Windows' clipboard-history opt-out formats,
    macOS's nspasteboard.org concealed/transient types) is never read at all;
  - a token shaped like a generated secret is never learnable.
No test here touches the real clipboard.
"""
from __future__ import annotations

import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from knight_flow import paste
from knight_flow.learned_words import looks_learnable, looks_like_a_secret, note_fix_evidence


class _FakeUser32:
    def __init__(self, present: set[str]) -> None:
        self._ids = {name: 49000 + i for i, name in enumerate(paste.PRIVATE_CLIPBOARD_FORMATS)}
        self._present = {self._ids[name] for name in present}
        self.RegisterClipboardFormatW = self._register
        self.IsClipboardFormatAvailable = self._available

    def _register(self, name):
        return self._ids.get(name, 0)

    def _available(self, fmt):
        return int(fmt in self._present)


@unittest.skipUnless(sys.platform == "win32", "the Windows clipboard formats")
class APrivateCopyIsNeverReadTests(unittest.TestCase):
    def private(self, present: set[str]) -> bool:
        fake = _FakeUser32(present)
        with patch.object(paste.ctypes, "WinDLL", return_value=SimpleNamespace(
                RegisterClipboardFormatW=_Settable(fake.RegisterClipboardFormatW),
                IsClipboardFormatAvailable=_Settable(fake.IsClipboardFormatAvailable))):
            return paste.clipboard_is_private()

    def test_each_opt_out_format_marks_the_copy_private(self):
        for name in paste.PRIVATE_CLIPBOARD_FORMATS:
            with self.subTest(format=name):
                self.assertTrue(self.private({name}))

    def test_an_ordinary_copy_is_not_private(self):
        self.assertFalse(self.private(set()))

    def test_a_probe_that_fails_says_private(self):
        with patch.object(paste.ctypes, "WinDLL", side_effect=OSError("no user32")):
            self.assertTrue(paste.clipboard_is_private())


class _Settable:
    """A callable that accepts argtypes/restype like a ctypes function."""

    def __init__(self, fn) -> None:
        self._fn = fn

    def __call__(self, *args):
        return self._fn(*args)


class _FakeClipboardDll:
    """user32 + kernel32 in one: records what lands on the clipboard."""

    def __init__(self) -> None:
        self.formats: dict[int, bytes] = {}
        self._memory: dict[int, bytearray] = {}
        self._names: dict[str, int] = {}
        for name in ("OpenClipboard", "CloseClipboard", "EmptyClipboard", "SetClipboardData",
                     "RegisterClipboardFormatW", "GlobalAlloc", "GlobalLock", "GlobalUnlock", "GlobalFree"):
            setattr(self, name, _Settable(getattr(self, "_" + name)))

    def _OpenClipboard(self, _owner): return 1
    def _CloseClipboard(self): return 1
    def _EmptyClipboard(self): self.formats.clear(); return 1
    def _RegisterClipboardFormatW(self, name): return self._names.setdefault(name, 49100 + len(self._names))
    def _GlobalAlloc(self, _flags, size):
        handle = 1000 + len(self._memory); self._memory[handle] = bytearray(size); return handle
    def _GlobalLock(self, handle): return handle
    def _GlobalUnlock(self, _handle): return 1
    def _GlobalFree(self, _handle): return None
    def _SetClipboardData(self, fmt, handle):
        self.formats[fmt] = bytes(self._memory[handle]); return handle

    def named(self) -> set[str]:
        return {name for name, fmt in self._names.items() if fmt in self.formats}


@unittest.skipUnless(sys.platform == "win32", "the Windows clipboard")
class TalkDatsOwnCopiesStayLocalTests(unittest.TestCase):
    def write(self, text: str, transient: bool) -> _FakeClipboardDll:
        fake = _FakeClipboardDll()
        with patch.dict("os.environ", {"TALK_DAT_PLAIN_CLIPBOARD": ""}), \
             patch.object(paste.ctypes, "WinDLL", return_value=fake), \
             patch.object(paste.ctypes, "memmove", side_effect=lambda dst, src, n: fake._memory[dst].__setitem__(slice(0, n), src[:n])):
            self.assertTrue(paste._copy_text_windows(text, transient=transient))
        return fake

    def test_a_borrowed_clipboard_stays_out_of_history_and_the_cloud(self):
        fake = self.write("dictated words", transient=True)
        self.assertEqual(fake.formats[13], "dictated words\0".encode("utf-16-le"))
        self.assertEqual(fake.named(), {"CanUploadToCloudClipboard", "CanIncludeInClipboardHistory",
                                        "ExcludeClipboardContentFromMonitorProcessing"})

    def test_a_copy_the_person_asked_for_only_stays_off_the_cloud(self):
        fake = self.write("kept words", transient=False)
        self.assertEqual(fake.named(), {"CanUploadToCloudClipboard"})
        upload = fake._names["CanUploadToCloudClipboard"]
        self.assertEqual(fake.formats[upload], bytes(4))

    def test_the_test_package_never_reaches_the_real_clipboard(self):
        self.assertEqual(__import__("os").environ.get("TALK_DAT_PLAIN_CLIPBOARD"), "1")
        self.assertFalse(paste._copy_text_windows("x", transient=True))


class ASecretIsNeverLearnableTests(unittest.TestCase):
    def test_generated_secrets_are_refused(self):
        # A cloud-key shape is BUILT AT RUNTIME so no key-shaped literal sits in
        # the source for the export's secret gate (or anyone else) to trip on.
        key_shaped = "".join(("AK", "IA", "7Q2ZP4XN", "8L0M3R5T"))
        for token in ("Kx7mQ2vp9RtZ", "xoqQy2-bivrad-zapjec", "8f3k2m9x7q1w5e6r", key_shaped):
            with self.subTest(token=token):
                self.assertTrue(looks_like_a_secret(token))
                self.assertFalse(looks_learnable(token))
                self.assertEqual(note_fix_evidence(token, {"dictionary": {}}, 1000.0), "ignore")

    def test_the_spellings_the_feature_exists_for_still_learn(self):
        for token in ("SAHVVV", "iPhone", "McRae", "B2B", "GPT4", "v2ray", "build@knightaiav.com", "NVMe", "MSFT"):
            with self.subTest(token=token):
                self.assertFalse(looks_like_a_secret(token))
                self.assertTrue(looks_learnable(token))


class TheLearnerAsksFirstTests(unittest.TestCase):
    def test_the_tick_skips_a_private_copy_before_reading_it(self):
        from pathlib import Path

        source = (Path(__file__).resolve().parents[1] / "knight_flow" / "app.py").read_text(encoding="utf-8")
        tick = source[source.index("def _clipboard_learn_tick"):]
        tick = tick[:tick.index("\n    def ", 10)]
        self.assertIn('"" if clipboard_is_private() else str(pyperclip.paste()', tick)


if __name__ == "__main__":
    unittest.main()
