"""Exercise UIA ranges on an owned native Edit, only on the test desktop."""
from __future__ import annotations

import sys
import threading
import unittest


@unittest.skipUnless(sys.platform == "win32", "Windows UI Automation")
class NativeCaretRangeTests(unittest.TestCase):
    def test_bounded_ranges_from_a_real_native_edit(self):
        import ctypes as c
        from ctypes import wintypes as w
        from comtypes.client import CreateObject, GetModule
        from knight_flow.caret_context import _read_uia

        user = c.WinDLL("user32", use_last_error=True)
        user.CreateWindowExW.argtypes = [w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD,
                                        c.c_int, c.c_int, c.c_int, c.c_int,
                                        w.HWND, w.HMENU, w.HINSTANCE, c.c_void_p]
        user.CreateWindowExW.restype = w.HWND
        user.SendMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
        user.SendMessageW.restype = w.LPARAM
        user.PostMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
        user.DestroyWindow.argtypes = [w.HWND]
        user.PeekMessageW.argtypes = [c.POINTER(w.MSG), w.HWND, w.UINT, w.UINT, w.UINT]
        ready, stop = threading.Event(), threading.Event()
        state = {}
        content = "Private synthetic prefix. I think  tomorrow. Synthetic suffix."
        position = content.index(" tomorrow")

        def editor():
            try:
                hwnd = user.CreateWindowExW(0, "Edit", content, 0x90000004,
                                             0, 0, 400, 200, None, None, None, None)
                state["hwnd"] = hwnd
                user.SendMessageW(hwnd, 0xB1, position, position)  # EM_SETSEL
                ready.set()
                msg = w.MSG()
                while not stop.is_set():
                    while user.PeekMessageW(c.byref(msg), None, 0, 0, 1):
                        user.TranslateMessage(c.byref(msg))
                        user.DispatchMessageW(c.byref(msg))
                    stop.wait(0.005)
                user.DestroyWindow(hwnd)
            finally:
                ready.set()

        thread = threading.Thread(target=editor, daemon=True)
        thread.start()
        try:
            self.assertTrue(ready.wait(2))
            self.assertTrue(state.get("hwnd"))
            uia = GetModule("UIAutomationCore.dll")
            automation = CreateObject(uia.CUIAutomation8, interface=uia.IUIAutomation2)
            automation.AutoSetFocus = False
            automation.ConnectionTimeout = 500
            automation.TransactionTimeout = 500
            native = automation.ElementFromHandle(state["hwnd"])

            class OwnedElement:
                # The test desktop is deliberately not the active desktop.
                # Focus security is tested separately; every text/range call
                # here goes through the real native accessibility provider.
                CurrentHasKeyboardFocus = True

                def __getattr__(self, key):
                    return getattr(native, key)

            element = OwnedElement()

            class OwnedAutomation:
                def GetFocusedElement(self):
                    return element

                def CompareElements(self, left, right):
                    return left is right

            context = _read_uia(OwnedAutomation(), uia)
            self.assertEqual(context, {"left": content[max(0, position - 32):position],
                                       "right": content[position:position + 32]})
            user.SendMessageW(state["hwnd"], 0xB1, position - 2, position)
            self.assertIsNone(_read_uia(OwnedAutomation(), uia))
        finally:
            stop.set()
            thread.join(2)
            self.assertFalse(thread.is_alive())


if __name__ == "__main__":
    unittest.main()
