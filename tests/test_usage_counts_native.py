"""The usage-counts toggle, in the real Settings renderer (owner decision 2026-09-23).

An official build shows "Share anonymous usage counts" on the Privacy page,
on by default, and first-run setup shows the same line with its toggle once,
on the last chapter; flipping that toggle saves privacy.share_usage_counts.
Runs in the real web shell on the isolated test desktop
(scripts/run_tests_offscreen.py tests.test_usage_counts_native).
"""
import copy, ctypes, multiprocessing, os, queue, sys, threading, time, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from knight_flow import official_build
from knight_flow.config import DEFAULT_CONFIG
from knight_flow.overlay import Overlay
from knight_flow.web_shell import shell_backend
from knight_flow.web_shell.shell_host import ShellController, _run_window, bundled_html
from knight_flow.web_shell.setup_workspace import SetupWorkspace

ASSETS = Path(__file__).resolve().parents[1] / 'knight_flow/web_shell/shell_assets'
FIELD = 'field-privacy.share_usage_counts'


def native_usage_probe(connection, evidence, html, label, detail):
    if sys.platform == 'win32':
        from ctypes import wintypes
        user = ctypes.windll.user32; user.GetThreadDesktop.restype = wintypes.HANDLE
        desktop = user.GetThreadDesktop(ctypes.windll.kernel32.GetCurrentThreadId())
        name = ctypes.create_unicode_buffer(256); required = wintypes.DWORD()
        if not user.GetUserObjectInformationW(desktop, 2, name, ctypes.sizeof(name), ctypes.byref(required)) \
                or not name.value.startswith('talkdat-tests-'):
            evidence.send({'error': 'The usage-counts native proof requires the isolated desktop'}); return
        surface = name.value
    else:
        surface = 'hidden WKWebView'
    import webview
    if sys.platform == 'darwin':
        from webview.platforms.cocoa import BrowserView
        BrowserView.app.setActivationPolicy_(2)
    create = webview.create_window; once = threading.Event()

    def create_probe(*args, **kwargs):
        kwargs['focus'] = False; window = create(*args, **kwargs)

        def probe():
            if once.is_set(): return
            once.set()

            def until(script):
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    if window.evaluate_js(script): return
                    time.sleep(.04)
                raise AssertionError('Did not settle: ' + script)

            def click(text):
                until("Array.from(document.querySelectorAll('button')).some(b=>b.textContent===" + repr(text) + "&&b.getClientRects().length&&!b.disabled)")
                window.evaluate_js("Array.from(document.querySelectorAll('button')).find(b=>b.textContent===" + repr(text) + "&&b.getClientRects().length).click();true")
            try:
                until("document.body.classList.contains('connected')")
                window.evaluate_js("window.TalkDat.navigate('privacy');true")
                until("document.getElementById(" + repr(FIELD) + ")")
                assert window.evaluate_js("document.getElementById(" + repr(FIELD) + ").getAttribute('aria-checked')==='true'"), 'Settings toggle is not on by default'
                page = window.evaluate_js("document.querySelector('main').innerText")
                assert label in page and detail in page, 'Settings does not show the owner\'s words'
                assert 'Keep speech and finishing on this computer' in page, 'Local-only privacy is gone'
                window.evaluate_js("window.TalkDat.navigate('setup');true")
                until("document.querySelector('.setup-welcome')")
                assert not window.evaluate_js("document.querySelector('.setup-usage')"), 'mentioned on the welcome chapter too'
                click('Try it'); until("document.querySelector('.setup-usage .switch')")
                assert window.evaluate_js("document.querySelectorAll('.setup-usage').length===1")
                setup_text = window.evaluate_js("document.querySelector('.setup-usage').innerText")
                assert label in setup_text and 'Never your audio or text.' in setup_text, setup_text
                assert window.evaluate_js("document.querySelector('.setup-usage .switch').getAttribute('aria-checked')==='true'")
                window.evaluate_js("document.querySelector('.setup-usage .switch').click();true")
                until("document.querySelector('.setup-usage .switch')?.getAttribute('aria-checked')==='false'")
                until("document.querySelector('.setup-status')?.textContent.includes('Anonymous usage counts are off')")
                evidence.send({'desktop': surface, 'status': 'Settings and setup usage-counts toggles passed'})
            except Exception as error:
                evidence.send({'error': str(error), 'ui': window.evaluate_js('document.body.innerText.slice(-1500)')})
            finally:
                window.destroy()
        window.events.loaded += probe; return window
    webview.create_window = create_probe
    _run_window(connection, html, 'general', hidden=sys.platform == 'darwin')


@unittest.skipUnless(sys.platform in {'win32', 'darwin'}, 'Native desktop settings acceptance')
class NativeUsageCountsTests(unittest.TestCase):
    def test_settings_and_setup_show_one_toggle_and_setup_saves_it(self):
        tasks = queue.Queue(); config = copy.deepcopy(DEFAULT_CONFIG); saved = []

        def save(candidate):
            saved.append(copy.deepcopy(candidate)); return {'saved': True, 'runtime_refreshed': True}

        def action(name, value):
            if name == 'permissions': return []
            if name == 'speech_status': return {'active': False, 'processing': False}
            if name == 'rehearsal_status': return {'active': False, 'matched': False}
        idle = {'check': {'phase': 'idle', 'mode': 'mic', 'active': False, 'message': 'Microphone off.', 'level': 0,
                          'elapsed': 0, 'seconds': 3, 'text': '', 'report': None, 'recognition_ms': None},
                'devices': {'status': 'ready', 'devices': [], 'message': ''}, 'selected': ''}
        microphone = SimpleNamespace(snapshot=lambda: copy.deepcopy(idle), handle=lambda _: copy.deepcopy(idle))
        clean = {k: v for k, v in os.environ.items() if not k.startswith('TALKDAT_')}
        with mock.patch.object(official_build, 'OFFICIAL', True), mock.patch.dict(os.environ, clean, clear=True):
            service = SetupWorkspace(config, save, action, microphone)
            backend = shell_backend.ShellBackend(config, ASSETS, lambda _: None, lambda: None,
                                                 object.__new__(Overlay)._settings_palette,
                                                 workspaces=SimpleNamespace(handle=lambda p: service.handle({k: v for k, v in p.items() if k != 'area'})))
            context = multiprocessing.get_context('spawn'); parent, child = context.Pipe(); receiver, sender = context.Pipe(duplex=False)
            process = context.Process(target=native_usage_probe,
                                      args=(child, sender, bundled_html(ASSETS), official_build.USAGE_COUNTS_LABEL,
                                            official_build.USAGE_COUNTS_DETAIL))
            process.start(); child.close(); sender.close()
            controller = ShellController(ASSETS, tasks.put, backend.handle, on_failure=lambda: None); controller.connection = parent
            listener = threading.Thread(target=controller._listen, args=(parent,), daemon=True); listener.start()
            try:
                deadline = time.monotonic() + 65
                while time.monotonic() < deadline and not receiver.poll():
                    while not tasks.empty(): tasks.get_nowait()()
                    time.sleep(.005)
                self.assertTrue(receiver.poll(), 'No native usage-counts receipt'); result = receiver.recv()
                self.assertNotIn('error', result, result)
                while not tasks.empty(): tasks.get_nowait()()
                self.assertIs(config['privacy']['share_usage_counts'], False)
                self.assertIs(saved[-1]['privacy']['share_usage_counts'], False)
                self.assertIs(config['privacy']['local_only'], True)
                print('Native usage-counts toggles in Settings and setup passed on', result['desktop'])
            finally:
                process.join(5)
                if process.is_alive(): process.terminate(); process.join(5)
                listener.join(2); parent.close(); receiver.close()


if __name__ == '__main__':
    unittest.main()
