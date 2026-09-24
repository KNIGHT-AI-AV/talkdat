import ctypes,multiprocessing,sys,threading,time,unittest
from pathlib import Path
from types import SimpleNamespace
from knight_flow.overlay import Overlay
from knight_flow.web_shell.shell_backend import ShellBackend
from knight_flow.web_shell.shell_host import ShellController,_run_window,bundled_html
import copy,os,queue,tempfile
from unittest.mock import patch
from knight_flow import plugins
from knight_flow.config import DEFAULT_CONFIG
from knight_flow.web_shell.plugins_workspace import PluginsWorkspace

ASSETS=Path(__file__).resolve().parents[1]/'knight_flow/web_shell/shell_assets'


def native_plugins_probe(connection,evidence,html):
    if sys.platform=='win32':
        from ctypes import wintypes
        user=ctypes.windll.user32;user.GetThreadDesktop.restype=wintypes.HANDLE
        desktop=user.GetThreadDesktop(ctypes.windll.kernel32.GetCurrentThreadId());name=ctypes.create_unicode_buffer(256);required=wintypes.DWORD()
        if not user.GetUserObjectInformationW(desktop,2,name,ctypes.sizeof(name),ctypes.byref(required)) or not name.value.startswith('talkdat-tests-'):
            evidence.send({'error':'Plugin proof requires an isolated desktop'});return
        surface=name.value
    else:surface='hidden WKWebView'
    import webview
    if sys.platform=='darwin':
        from webview.platforms.cocoa import BrowserView
        BrowserView.app.setActivationPolicy_(2)
    create=webview.create_window;once=threading.Event()
    def create_probe(*args,**kwargs):
        kwargs['focus']=False;window=create(*args,**kwargs)
        def probe():
            if once.is_set():return
            once.set()
            def until(script):
                deadline=time.monotonic()+16
                while time.monotonic()<deadline:
                    if window.evaluate_js(script):return
                    time.sleep(.04)
                raise AssertionError('Plugin control did not settle: '+script)
            def click(text):
                until("Array.from(document.querySelectorAll('button')).some(b=>b.textContent==="+repr(text)+"&&b.getClientRects().length&&!b.disabled)")
                window.evaluate_js("Array.from(document.querySelectorAll('button')).find(b=>b.textContent==="+repr(text)+"&&b.getClientRects().length&&!b.disabled).click();true")
            try:
                until("document.body.classList.contains('connected')")
                window.evaluate_js("window.TalkDat.navigate('privacy');true")
                def expand():
                    until("document.querySelector('[data-field=\"plugins.enabled\"]')")
                    window.evaluate_js("document.querySelector('[data-field=\"plugins.enabled\"]').closest('details').open=true;true")
                expand()
                until("document.querySelector('.plugin-tools p').textContent==='Plugins are off.'")
                window.evaluate_js("document.getElementById('field-plugins.enabled').click();true")
                click('Save changes')
                until("document.getElementById('save-strip').hidden")
                expand();click('Reload plugins')
                until("document.querySelector('.plugin-issues').textContent.includes('RuntimeError')")
                click('Open plugins folder')
                until("document.getElementById('notice').textContent==='Opened your local plugins folder.'")
                window.evaluate_js("window.TalkDat.navigate('general');true")
                until("document.querySelector('main h1').textContent==='General'")
                window.evaluate_js("window.TalkDat.navigate('privacy');true");expand()
                until("document.querySelector('.plugin-issues').textContent.includes('RuntimeError')")
                window.evaluate_js("document.getElementById('field-plugins.enabled').click();true")
                click('Save changes');until("document.getElementById('save-strip').hidden");expand()
                until("document.querySelector('.plugin-tools p').textContent==='Plugins are off.'")
                assert window.evaluate_js("Array.from(document.querySelectorAll('.plugin-tools button')).every(b=>b.getBoundingClientRect().height>=44)")
                assert window.evaluate_js("document.documentElement.scrollWidth<=window.innerWidth+1")
                evidence.send({'surface':surface,'status':'Native plugin opt-in, reload failure, folder, navigation and disable passed'})
            except Exception as error:evidence.send({'error':str(error),'ui':window.evaluate_js('document.body.innerText.slice(-2000)')})
            finally:window.destroy()
        window.events.loaded+=probe;return window
    webview.create_window=create_probe
    _run_window(connection,html,'privacy',hidden=sys.platform=='darwin')


@unittest.skipUnless(sys.platform in {'win32','darwin'},'Native desktop plugin acceptance')
class NativePluginTests(unittest.TestCase):
    def test_native_plugin_controls_and_failed_reload(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        env=patch.dict(os.environ,{'TALK_DAT_HOME':temporary.name});env.start();self.addCleanup(env.stop)
        plugins.request_reload(None).wait(4);self.addCleanup(lambda:plugins.request_reload(None).wait(4))
        (plugins.plugins_dir()/'broken.py').write_text("raise RuntimeError('private fixture detail')")
        config=copy.deepcopy(DEFAULT_CONFIG);config['plugins']['enabled']=False
        queue_=queue.Queue();opened=[]
        service=PluginsWorkspace(config,lambda:False,lambda path:opened.append(path))
        def drain():
            while not queue_.empty():queue_.get_nowait()()
        backend=ShellBackend(config,ASSETS,lambda _:None,
            lambda:plugins.request_reload(config if plugins.plugins_enabled(config) else None),
            object.__new__(Overlay)._settings_palette,
            workspaces=SimpleNamespace(handle=lambda p:service.handle({k:v for k,v in p.items() if k!='area'})))
        context=multiprocessing.get_context('spawn');parent,child=context.Pipe();receiver,sender=context.Pipe(duplex=False)
        process=context.Process(target=native_plugins_probe,args=(child,sender,bundled_html(ASSETS)));process.start();child.close();sender.close()
        controller=ShellController(ASSETS,queue_.put,backend.handle,on_failure=lambda:None);controller.connection=parent
        listener=threading.Thread(target=controller._listen,args=(parent,),daemon=True);listener.start()
        try:
            deadline=time.monotonic()+65
            while time.monotonic()<deadline and not receiver.poll():drain();time.sleep(.005)
            self.assertTrue(receiver.poll(),'No native plugin result');result=receiver.recv();self.assertNotIn('error',result,result)
            drain();self.assertFalse(config['plugins']['enabled']);self.assertEqual(opened,[plugins.plugins_dir()])
            self.assertTrue(plugins._reload_done.wait(3));self.assertEqual(plugins._hosts,[])
            print(result['status'],'on',result['surface'])
        finally:
            process.join(5)
            if process.is_alive():process.terminate();process.join(5)
            listener.join(2);parent.close();receiver.close()

if __name__=='__main__':unittest.main()
