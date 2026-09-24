"""X-612: signing in happens on the web Account page.

The web Settings had an Account page that was a title and a "Manage account"
button, and the button opened the square Tk Account window. The page now signs
in itself, with the app's own sign-in path, worded as the window worded it, and
it never receives the device code.
"""
import copy
import multiprocessing
import queue
import sys
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from knight_flow.config import DEFAULT_CONFIG
from knight_flow.web_shell.account_workspace import AccountWorkspace, account_view

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "knight_flow/web_shell/shell_assets"
SECRET = "device-" + "code-" + "0123456789abcdef"


class TheWordsTests(unittest.TestCase):
    def test_not_signed_in(self):
        view = account_view({}, {"state": "idle"})
        self.assertEqual((view["headline"], view["signed_in"], view["code_box"]), ("Not signed in", False, False))
        self.assertIn("work the same without an account", view["detail"])

    def test_a_code_was_emailed(self):
        view = account_view({}, {"state": "code_sent", "detail": "We sent a six-digit code to a@b.co. Type it here.",
                                 "device_code": SECRET, "user_code": "ABCD-EFGH", "email": "a@b.co"})
        self.assertEqual(view["headline"], "Type the code from your email")
        self.assertTrue(view["code_box"])
        self.assertEqual(view["code"], "")
        self.assertNotIn(SECRET, repr(view))

    def test_a_wrong_code_keeps_the_box_and_says_why(self):
        view = account_view({}, {"state": "code_error", "detail": "That code is not right."})
        self.assertTrue(view["code_box"])
        self.assertEqual(view["note"], "That code is not right.")

    def test_the_browser_wait_shows_the_pairing_code_and_counts_down(self):
        view = account_view({}, {"state": "waiting", "user_code": "ABCD-EFGH", "expires_at": 1000.0,
                                 "device_code": SECRET}, now=875.0)
        self.assertEqual((view["code"], view["waiting"], view["poll"]), ("ABCD-EFGH", True, True))
        self.assertIn("The code stays good for 2:05.", view["detail"])
        self.assertNotIn(SECRET, repr(view))

    def test_signed_in(self):
        view = account_view({"email": "a@b.co", "detail": "This device is activated."}, {"state": "active"})
        self.assertEqual((view["headline"], view["signed_in"]), ("Signed in as a@b.co", True))

    def test_error(self):
        self.assertEqual(account_view({}, {"state": "error", "detail": "Offline."})["headline"], "Sign-in did not finish")


class TheWorkspaceTests(unittest.TestCase):
    def actions(self, **status):
        return SimpleNamespace(status=Mock(return_value=status), activation=Mock(return_value={"state": "idle"}),
                               email_code=Mock(), verify_code=Mock(), browser_sign_in=Mock(), cancel=Mock(),
                               sign_out=Mock(), website=Mock())

    def test_each_button_reaches_the_apps_own_path(self):
        actions = self.actions()
        account = AccountWorkspace(actions)
        account.handle({"operation": "email_code", "value": " a@b.co "})
        actions.email_code.assert_called_once_with("a@b.co")
        account.handle({"operation": "verify_code", "value": "123 456"})
        actions.verify_code.assert_called_once_with("123456")
        for operation in ("browser_sign_in", "cancel", "sign_out", "website"):
            account.handle({"operation": operation})
            getattr(actions, operation).assert_called_once_with()

    def test_bad_input_is_refused_with_a_sentence(self):
        account = AccountWorkspace(self.actions())
        for payload in ({"operation": "email_code", "value": "not an email"},
                        {"operation": "verify_code", "value": "12345"},
                        {"operation": "delete_everything"},
                        {"operation": "status", "extra": 1}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                account.handle(payload)

    def test_the_page_asks_the_web_shell_first(self):
        from knight_flow.overlay import Overlay

        overlay = SimpleNamespace(callbacks={"web_settings": Mock(return_value=True)})
        Overlay.open_account.__wrapped__(overlay)
        overlay.callbacks["web_settings"].assert_called_once_with("account")

    def test_the_module_is_loaded_and_drawn(self):
        self.assertIn('<script src="account.js" defer></script>', (ASSETS / "index.html").read_text(encoding="utf-8"))
        self.assertIn('window.TalkDatAccount({container:main,el,request:rpc,notice})',
                      (ASSETS / "shell.js").read_text(encoding="utf-8"))
        self.assertIn("'account.js'", (ROOT / "knight_flow/web_shell/shell_host.py").read_text(encoding="utf-8"))


def native_account_probe(connection, evidence, html):
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        user = ctypes.windll.user32
        user.GetThreadDesktop.restype = wintypes.HANDLE
        desktop = user.GetThreadDesktop(ctypes.windll.kernel32.GetCurrentThreadId())
        name = ctypes.create_unicode_buffer(256)
        required = wintypes.DWORD()
        if (not user.GetUserObjectInformationW(desktop, 2, name, ctypes.sizeof(name), ctypes.byref(required))
                or not name.value.startswith("talkdat-tests-")):
            evidence.send({"error": "The account proof requires the isolated desktop"})
            return
        surface = name.value
    else:
        surface = "hidden WKWebView"
    import webview
    from knight_flow.web_shell.shell_host import _run_window

    if sys.platform == "darwin":
        from webview.platforms.cocoa import BrowserView
        BrowserView.app.setActivationPolicy_(2)
    create = webview.create_window
    once = threading.Event()

    def create_probe(*args, **kwargs):
        kwargs["focus"] = False
        window = create(*args, **kwargs)

        def probe():
            if once.is_set():
                return
            once.set()

            def until(script):
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    if window.evaluate_js(script):
                        return
                    time.sleep(.04)
                raise AssertionError("The account page did not settle: " + script)

            def click(text):
                window.evaluate_js("[...document.querySelectorAll('.account-workspace button')]"
                                   ".find(b=>b.textContent===" + repr(text) + "&&b.getClientRects().length).click();true")

            def type_into(identifier, value):
                window.evaluate_js("{const e=document.getElementById(" + repr(identifier) + ");e.value=" + repr(value)
                                   + ";e.dispatchEvent(new Event('input',{bubbles:true}));}true")

            try:
                until("document.body.classList.contains('connected')")
                window.evaluate_js("window.TalkDat.navigate('account');true")
                until("document.querySelector('.account-headline')?.textContent==='Not signed in'")
                type_into("account-email", "a@b.co")
                click("Email me a code")
                until("document.querySelector('.account-code-row') && !document.querySelector('.account-code-row').hidden")
                type_into("account-code-input", "123456")
                click("Sign in with this code")
                until("document.querySelector('.account-headline')?.textContent==='Signed in as a@b.co'")
                layout = window.evaluate_js(
                    "({signin_hidden:document.querySelector('.account-signin').hidden,"
                    "sign_out:[...document.querySelectorAll('.account-workspace button')].some(b=>b.textContent==='Sign out'&&!b.hidden),"
                    "overflow:document.documentElement.scrollWidth>document.documentElement.clientWidth,"
                    "page:document.body.innerText})")
                evidence.send({"desktop": surface, "layout": layout})
            except Exception as error:
                evidence.send({"error": str(error), "ui": window.evaluate_js("document.body.innerText.slice(-1500)")})
            finally:
                window.destroy()

        window.events.loaded += probe
        return window

    webview.create_window = create_probe
    _run_window(connection, html, "account", hidden=sys.platform == "darwin")


@unittest.skipUnless(sys.platform in {"win32", "darwin"}, "Native desktop account acceptance")
class NativeAccountTests(unittest.TestCase):
    def test_email_code_sign_in_on_the_page(self):
        from knight_flow.overlay import Overlay
        from knight_flow.web_shell.shell_backend import ShellBackend
        from knight_flow.web_shell.shell_host import ShellController, bundled_html
        from knight_flow.web_shell.workspace_adapter import Workspaces

        tasks = queue.Queue()
        config = copy.deepcopy(DEFAULT_CONFIG)
        account = {"status": {}, "activation": {"state": "idle"}}
        calls = []

        def begin(email):
            calls.append(("email", email))
            account["activation"] = {"state": "code_sent", "detail": f"We sent a six-digit code to {email}. Type it here.",
                                     "email": email, "device_code": SECRET, "user_code": "ABCD-EFGH"}

        def finish(code):
            calls.append(("code", code))
            account["activation"] = {"state": "active", "detail": "Signed in.", "email": "a@b.co"}
            account["status"] = {"email": "a@b.co", "detail": "This device is activated."}

        app = SimpleNamespace(config=config, license_status=lambda: account["status"],
                              license_activation_status=lambda: account["activation"],
                              begin_email_sign_in=begin, finish_email_sign_in=finish)
        workspaces = Workspaces(app, lambda candidate: None, lambda: False)
        backend = ShellBackend(config, ASSETS, lambda candidate: None, lambda: None,
                               object.__new__(Overlay)._settings_palette, workspaces=workspaces)
        context = multiprocessing.get_context("spawn")
        parent, child = context.Pipe()
        receiver, sender = context.Pipe(duplex=False)
        process = context.Process(target=native_account_probe, args=(child, sender, bundled_html(ASSETS)))
        process.start()
        child.close()
        sender.close()
        controller = ShellController(ASSETS, tasks.put, backend.handle, on_failure=lambda: None)
        controller.connection = parent
        listener = threading.Thread(target=controller._listen, args=(parent,), daemon=True)
        listener.start()
        try:
            deadline = time.monotonic() + 65
            while time.monotonic() < deadline and not receiver.poll():
                while not tasks.empty():
                    tasks.get_nowait()()
                time.sleep(.005)
            self.assertTrue(receiver.poll(), "No native account receipt")
            result = receiver.recv()
            self.assertNotIn("error", result, result)
            self.assertEqual(calls, [("email", "a@b.co"), ("code", "123456")])
            self.assertTrue(result["layout"]["signin_hidden"])
            self.assertTrue(result["layout"]["sign_out"])
            self.assertFalse(result["layout"]["overflow"])
            self.assertNotIn(SECRET, result["layout"]["page"])
            print("Native account sign-in passed on", result["desktop"])
        finally:
            process.join(5)
            if process.is_alive():
                process.terminate()
                process.join(5)
            listener.join(2)
            parent.close()
            receiver.close()


if __name__ == "__main__":
    unittest.main()
