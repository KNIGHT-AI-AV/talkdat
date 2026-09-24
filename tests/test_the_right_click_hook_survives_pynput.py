"""X-434: the right-click rewrite hook must install even after pynput has
set its own argtypes on the shared user32.

Seen for real (2026-09-04, running from source on Python 3.13, and the
packaged app ships 3.13 too): the TalkDatRightClick thread died with

    ctypes.ArgumentError: argument 2: TypeError: expected WinFunctionType
    instance instead of WinFunctionType

before installing anything, so the right-click chip never appeared. pynput's
win32 shim assigns `windll.user32.SetWindowsHookExW.argtypes` with its own
hook-proc class, WINFUNCTYPE(LPARAM, c_int32, WPARAM, LPARAM). Ours is
WINFUNCTYPE(c_ssize_t, c_int, WPARAM, c_void_p): a different signature, so a
different class, and `ctypes.windll.user32` is a process-wide singleton, so
pynput's argtypes reached our call and refused our instance. (Python caches
WINFUNCTYPE classes by signature; identical signatures WOULD have matched.)

The fix is a private WinDLL in selection_menu, whose function objects carry
nobody else's argtypes. This test pins the two halves of that contract.
"""
from __future__ import annotations

import ctypes
import sys
import unittest

from knight_flow import selection_menu


@unittest.skipUnless(sys.platform == "win32", "the hook is a Windows feature")
class TheRightClickHookSurvivesPynput(unittest.TestCase):
    def test_the_module_never_reaches_for_the_shared_user32(self) -> None:
        source = open(selection_menu.__file__, encoding="utf-8").read()
        self.assertNotIn(
            "ctypes.windll.user32",
            source,
            "selection_menu must keep its own WinDLL; the shared one carries pynput's argtypes",
        )
        self.assertIn('ctypes.WinDLL("user32"', source)

    def test_a_private_windll_ignores_argtypes_set_on_the_shared_one(self) -> None:
        # The exact thing pynput does at import, with a class of its own.
        foreign_hookproc = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t, ctypes.c_int, ctypes.c_size_t, ctypes.c_ssize_t
        )
        shared = ctypes.windll.user32.SetWindowsHookExW
        before = shared.argtypes
        try:
            shared.argtypes = (ctypes.c_int, foreign_hookproc, ctypes.c_void_p, ctypes.c_uint)
            private = ctypes.WinDLL("user32", use_last_error=True)
            self.assertIsNone(private.SetWindowsHookExW.argtypes)
            # And the two are genuinely different function objects.
            self.assertIsNot(private.SetWindowsHookExW, shared)
        finally:
            shared.argtypes = before

    def test_a_64_bit_lparam_reaches_callnexthookex_without_overflowing(self) -> None:
        """The second half. The first cut of X-434 left the private user32
        untyped, so lparam (a pointer) overflowed c_int on every mouse event
        and the hook never chained. With no hook installed CallNextHookEx is
        a harmless no-op that returns 0; the point is that the call converts."""
        from ctypes import wintypes

        hookproc = ctypes.WINFUNCTYPE(
            getattr(wintypes, "LRESULT", ctypes.c_ssize_t), ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
        )
        user32 = selection_menu.typed_user32(hookproc)
        self.assertIn(hookproc, user32.SetWindowsHookExW.argtypes)
        self.assertEqual(user32.CallNextHookEx(None, 0, 0, 2**40 + 12345), 0)

    def test_pynputs_argtypes_on_the_shared_user32_reject_our_hook_class(self) -> None:
        """The premise, reproduced: pynput's signature and ours are different
        classes, and argtypes set with theirs refuse an instance of ours."""
        from ctypes import wintypes

        theirs = ctypes.WINFUNCTYPE(wintypes.LPARAM, ctypes.c_int32, wintypes.WPARAM, wintypes.LPARAM)
        ours = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, ctypes.c_void_p)
        self.assertIsNot(theirs, ours)
        shared = ctypes.windll.user32.SetWindowsHookExW
        before = shared.argtypes
        try:
            shared.argtypes = (ctypes.c_int, theirs, wintypes.HINSTANCE, wintypes.DWORD)
            with self.assertRaises(ctypes.ArgumentError):
                # WH_MOUSE_LL with a proc of the wrong class never reaches Win32;
                # ctypes refuses it at the argtypes check, exactly as in the log.
                shared(14, ours(lambda code, w, l: 0), None, 0)
        finally:
            shared.argtypes = before


if __name__ == "__main__":
    unittest.main()
