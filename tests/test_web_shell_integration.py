"""Native WebView2 -> pipe -> typed settings -> atomic fixture file.

Run only through the product's isolated-desktop test runner.
"""
import copy
import json
import multiprocessing
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from knight_flow.config import DEFAULT_CONFIG
from knight_flow.overlay import Overlay
from knight_flow.web_shell.shell_backend import ShellBackend
from knight_flow.web_shell.shell_host import _run_window, _receive, _send, bundled_html


def child_save(connection,evidence,html):
    import ctypes
    from ctypes import wintypes
    user32=ctypes.windll.user32
    user32.GetThreadDesktop.restype=wintypes.HANDLE
    desktop=user32.GetThreadDesktop(ctypes.windll.kernel32.GetCurrentThreadId())
    name=ctypes.create_unicode_buffer(256);required=wintypes.DWORD()
    if not user32.GetUserObjectInformationW(desktop,2,name,ctypes.sizeof(name),ctypes.byref(required)) or not name.value.startswith('talkdat-tests-'):
        evidence.send({'error':'The native test is not on an isolated desktop'});return
    import webview
    create=webview.create_window
    once=threading.Event()
    def create_probe(*args,**kwargs):
        window=create(*args,**kwargs)
        def probe():
            if once.is_set():return
            once.set()
            try:
                deadline=time.monotonic()+20
                while time.monotonic()<deadline:
                    if window.evaluate_js("document.body.classList.contains('connected')"):break
                    time.sleep(0.05)
                window.evaluate_js("window.TalkDat.navigate('formatting');true")
                while time.monotonic()<deadline:
                    if window.evaluate_js("!!document.getElementById('field-cleanup.max_ai_format_ms')"):break
                    time.sleep(0.05)
                window.evaluate_js("const field=document.getElementById('field-cleanup.max_ai_format_ms');field.value='1700';field.dispatchEvent(new Event('input',{bubbles:true}));document.getElementById('save').click();true")
                saved=False
                while time.monotonic()<deadline:
                    saved=window.evaluate_js("document.getElementById('save-strip').hidden && document.getElementById('field-cleanup.max_ai_format_ms').value==='1700'")
                    if saved:break
                    time.sleep(0.05)
                window.evaluate_js("window.TalkDat.navigate('appearance');true")
                while time.monotonic()<deadline:
                    if window.evaluate_js("!!document.querySelector('.theme-choice[aria-label=\"Brass Lamp Dark\"]')"):break
                    time.sleep(0.05)
                window.evaluate_js("document.querySelector('.theme-choice[aria-label=\"Brass Lamp Dark\"]').click();true")
                material_ready = False
                while time.monotonic()<deadline:
                    material_ready = window.evaluate_js("!!document.querySelector('.theme-current img').naturalWidth && getComputedStyle(document.documentElement).getPropertyValue('--theme-material').includes('data:image/webp')")
                    if material_ready:break
                    time.sleep(0.05)
                window.evaluate_js("document.getElementById('save').click();true")
                while time.monotonic()<deadline:
                    if window.evaluate_js("document.getElementById('save-strip').hidden"):break
                    time.sleep(0.05)
                window.evaluate_js("window.TalkDat.navigate('model-guide');true")
                guide = window.evaluate_js("""(() => {
                    const search=document.getElementById('model-guide-search');
                    const location=document.getElementById('model-guide-location');
                    const availability=document.getElementById('model-guide-availability');
                    if(!search||!location||!availability)return {missing:true};
                    location.value='local';location.dispatchEvent(new Event('change'));
                    availability.value='wired';availability.dispatchEvent(new Event('change'));
                    search.focus();search.value='NVIDIA';search.dispatchEvent(new Event('input'));
                    const names=Array.from(document.querySelectorAll('#model-guide-results h2')).map(n=>n.textContent);
                    const focused=document.activeElement===search;
                    search.value='no-matching-model-zzzz';search.dispatchEvent(new Event('input'));
                    return {names,focused,empty:document.getElementById('model-guide-results').textContent};
                })()""")
                from System import Action
                native = window.native.browser.webview
                native.Invoke(Action(lambda:setattr(native,'ZoomFactor',2.0)))
                window.evaluate_js("window.TalkDat.navigate('appearance');true")
                while time.monotonic()<deadline:
                    if window.evaluate_js("!!document.querySelector('.theme-grid')"):break
                    time.sleep(0.05)
                time.sleep(0.15)
                layout = window.evaluate_js("({viewport:innerWidth, content:document.documentElement.scrollWidth, clipped:Array.from(document.querySelectorAll('main button,main input,main select,header button')).filter(node=>node.getClientRects().length&&(node.getBoundingClientRect().right>innerWidth+1||node.getBoundingClientRect().left<0)).map(node=>node.textContent), minimumTarget:Math.min(...Array.from(document.querySelectorAll('button,input,select,summary')).filter(node=>node.getClientRects().length).map(node=>node.getBoundingClientRect().height))})")
                navigation=[]
                def observed(_sender,event):navigation.append({'url':str(event.Uri), 'cancelled':bool(event.Cancel)})
                native.NavigationStarting += observed
                window.evaluate_js("window.location.href='http://127.0.0.1:8765/foreign';true")
                time.sleep(0.2)
                blocked=any(item['url']=='http://127.0.0.1:8765/foreign' and item['cancelled'] for item in navigation)
                evidence.send({'saved':saved,'material_ready':material_ready,'desktop':name.value,'font_ready':window.evaluate_js("document.fonts.check('16px Knight')"),'zoom_200':layout,'foreign_navigation_refused':blocked,'guide':guide})
            except Exception as error:
                evidence.send({'error':str(error)})
            finally:window.destroy()
        window.events.loaded+=probe
        return window
    webview.create_window=create_probe
    _run_window(connection,html,'formatting',hidden=False)


@unittest.skipUnless(sys.platform == 'win32', 'Windows WebView2 integration; macOS has a separate native proof')
class NativeSettingsIntegrationTests(unittest.TestCase):
    def test_a_real_web_edit_saves_through_the_typed_backend(self):
        config=copy.deepcopy(DEFAULT_CONFIG)
        config['stt']['providers']['openai']['api_key']='synthetic-kept-key'
        stage=Path(__file__).resolve().parents[1]/'knight_flow/web_shell/shell_assets'
        with tempfile.TemporaryDirectory() as folder:
            destination=Path(folder)/'config.json'
            threads=[]
            def persist(candidate):
                temporary=destination.with_suffix('.tmp')
                temporary.write_text(json.dumps(candidate),encoding='utf-8')
                temporary.replace(destination)
                threads.append(threading.get_ident())
            effects=[]
            backend=ShellBackend(config,stage,persist,lambda:effects.append('applied'),object.__new__(Overlay)._settings_palette)
            ctx=multiprocessing.get_context('spawn')
            parent,child=ctx.Pipe();receiver,sender=ctx.Pipe(duplex=False)
            process=ctx.Process(target=child_save,args=(child,sender,bundled_html(stage)))
            process.start();child.close();sender.close()
            send_lock=threading.Lock()
            try:
                deadline=time.monotonic()+35
                while time.monotonic()<deadline and not receiver.poll():
                    if parent.poll(0.05):
                        request=_receive(parent)
                        result=backend.handle(request['method'],request['payload'])
                        _send(parent,send_lock,{'id':request['id'],'answer':{'ok':True,'result':result}})
                    if not process.is_alive():break
                self.assertTrue(receiver.poll(),'No native save result')
                result=receiver.recv()
                self.assertNotIn('error',result,result)
                self.assertTrue(result['saved'],result)
                self.assertTrue(result['font_ready'],result)
                self.assertTrue(result['material_ready'],result)
                self.assertTrue(result['foreign_navigation_refused'],result)
                self.assertEqual(result['guide']['names'], ['Parakeet TDT 0.6B v3', 'Parakeet TDT 0.6B v2'], result)
                self.assertTrue(result['guide']['focused'],result)
                self.assertEqual(result['guide']['empty'],'No models match these filters.',result)
                self.assertLessEqual(result['zoom_200']['content'], result['zoom_200']['viewport'],result)
                self.assertGreaterEqual(result['zoom_200']['minimumTarget'],44,result)
                self.assertEqual(result['zoom_200']['clipped'],[],result)
                saved=json.loads(destination.read_text(encoding='utf-8'))
                self.assertEqual(saved['cleanup']['max_ai_format_ms'],1700)
                self.assertEqual(saved['ui']['settings_theme'],'Brass Lamp Dark')
                self.assertEqual(saved['stt']['providers']['openai']['api_key'],'synthetic-kept-key')
                self.assertEqual(effects,['applied','applied'])
                self.assertEqual(threads,[threading.get_ident(),threading.get_ident()])
                print('Native settings saved through the real backend on',result['desktop'])
            finally:
                process.join(5)
                if process.is_alive():process.terminate();process.join(5)
                parent.close();receiver.close()


if __name__=='__main__':unittest.main()
