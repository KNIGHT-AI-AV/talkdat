"""App preferences through the native renderer and real typed workspace."""
import copy,ctypes,json,multiprocessing,queue,sys,tempfile,threading,time,unittest
from pathlib import Path
from types import SimpleNamespace
from knight_flow.config import DEFAULT_CONFIG
from knight_flow.overlay import Overlay
from knight_flow.web_shell.shell_backend import ShellBackend
from knight_flow.web_shell.shell_host import ShellController,_run_window,bundled_html
from knight_flow.web_shell.workspace_adapter import Workspaces

ASSETS=Path(__file__).resolve().parents[1]/'knight_flow/web_shell/shell_assets'


def native_app_profile_probe(connection,evidence,html):
    if sys.platform=='win32':
        from ctypes import wintypes
        user=ctypes.windll.user32;user.GetThreadDesktop.restype=wintypes.HANDLE
        desktop=user.GetThreadDesktop(ctypes.windll.kernel32.GetCurrentThreadId())
        name=ctypes.create_unicode_buffer(256);required=wintypes.DWORD()
        if not user.GetUserObjectInformationW(desktop,2,name,ctypes.sizeof(name),ctypes.byref(required)) or not name.value.startswith('talkdat-tests-'):
            evidence.send({'error':'App preference proof requires the isolated desktop'});return
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
                deadline=time.monotonic()+15
                while time.monotonic()<deadline:
                    if window.evaluate_js(script):return
                    time.sleep(.04)
                raise AssertionError('App preference did not settle: '+script)
            def click(text):window.evaluate_js("Array.from(document.querySelectorAll('button')).find(b=>b.textContent==="+repr(text)+"&&b.getClientRects().length).click();true")
            def field(identifier,value):window.evaluate_js("{const e=document.getElementById("+repr(identifier)+");e.value="+repr(value)+";e.dispatchEvent(new Event('input',{bubbles:true}));}true")
            try:
                until("document.body.classList.contains('connected')")
                window.evaluate_js("window.TalkDat.navigate('app-profiles');true")
                until("document.getElementById('profile-match')?.value==='Slack'")
                field('profile-language','de');field('profile-tone','friendly')
                field('search','per app')
                until("document.getElementById('app-profile-leave-title')?.closest('dialog').open")
                window.evaluate_js("window.TalkDat.refresh().then(()=>window.__draftRefreshDone=true);true")
                until("window.__draftRefreshDone===true")
                assert window.evaluate_js("document.getElementById('app-profile-leave-title')?.closest('dialog').open")
                click('Keep editing');until("document.getElementById('search').value===''")
                window.evaluate_js("window.TalkDat.requestClose();true")
                until("document.getElementById('app-profile-leave-title')?.closest('dialog').open")
                click('Keep editing');click('Save app')
                until("document.querySelector('.profile-status')?.textContent.includes('could not be saved')")
                assert window.evaluate_js("document.getElementById('profile-language').value==='de'")
                click('Save app');until("document.querySelector('.profile-status')?.textContent.startsWith('Saved preference')")
                window.evaluate_js("window.TalkDat.navigate('general');true")
                until("!document.getElementById('profile-match')")
                window.evaluate_js("window.TalkDat.navigate('app-profiles');true")
                until("document.getElementById('profile-language')?.value==='de'")
                field('search','per app');until("!!document.querySelector('.search-result')")
                window.evaluate_js("window.TalkDat.refresh().then(()=>window.__searchRefreshDone=true);true")
                until("window.__searchRefreshDone===true")
                assert window.evaluate_js("!!document.querySelector('.search-result')")
                window.evaluate_js("document.querySelector('.search-result').click();true")
                until("document.getElementById('profile-language')?.value==='de'")
                click('Add app');field('profile-match','Sakura 日本語');field('profile-cleanup','light');click('Save app')
                until("document.querySelector('.profile-status')?.textContent.startsWith('Saved preference')")
                assert window.evaluate_js("document.querySelectorAll('.app-profiles-workspace .document-entry').length===2")
                evidence.send({'desktop':surface,'text':window.evaluate_js("document.querySelector('.app-profiles-workspace').innerText")})
            except Exception as error:evidence.send({'error':str(error),'ui':window.evaluate_js('document.body.innerText.slice(-2000)')})
            finally:window.destroy()
        window.events.loaded+=probe;return window
    webview.create_window=create_probe
    _run_window(connection,html,'app-profiles',hidden=sys.platform=='darwin')


@unittest.skipUnless(sys.platform in {'win32','darwin'},'Native desktop app preference acceptance')
class NativeAppPreferenceTests(unittest.TestCase):
    def test_native_save_retry_close_protection_reopen_and_unicode_app(self):
        tasks=queue.Queue();config=copy.deepcopy(DEFAULT_CONFIG);config['profiles']=[{'match':'Slack'}]
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        path=Path(temporary.name)/'settings.json';calls=[]
        def persist(candidate):
            calls.append(threading.get_ident())
            if len(calls)==1:raise OSError('fixture save failure')
            from knight_flow.app import atomic_write_text
            atomic_write_text(path,json.dumps(candidate,ensure_ascii=False))
        app=SimpleNamespace(config=config);workspaces=Workspaces(app,persist,lambda:False)
        backend=ShellBackend(config,ASSETS,persist,lambda:None,object.__new__(Overlay)._settings_palette,workspaces=workspaces)
        context=multiprocessing.get_context('spawn');parent,child=context.Pipe();receiver,sender=context.Pipe(duplex=False)
        process=context.Process(target=native_app_profile_probe,args=(child,sender,bundled_html(ASSETS)))
        process.start();child.close();sender.close()
        controller=ShellController(ASSETS,tasks.put,backend.handle,on_failure=lambda:None);controller.connection=parent
        listener=threading.Thread(target=controller._listen,args=(parent,),daemon=True);listener.start()
        try:
            deadline=time.monotonic()+65
            while time.monotonic()<deadline and not receiver.poll():
                while not tasks.empty():tasks.get_nowait()()
                time.sleep(.005)
            self.assertTrue(receiver.poll(),'No native app preference receipt')
            result=receiver.recv();self.assertNotIn('error',result,result)
            saved=json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(saved['profiles'][0]['language'],'de');self.assertEqual(saved['profiles'][0]['tone'],'friendly')
            self.assertEqual(saved['profiles'][1]['match'],'Sakura 日本語');self.assertEqual(saved['profiles'][1]['cleanup_level'],'light')
            self.assertEqual(saved['profiles'],config['profiles']);self.assertEqual(len(calls),3)
            self.assertTrue(all(i==threading.get_ident() for i in calls))
            print('Native app preference save retry, draft/search refresh protection, reopen and Unicode app passed on',result['desktop'])
        finally:
            process.join(5)
            if process.is_alive():process.terminate();process.join(5)
            listener.join(2);parent.close();receiver.close()


if __name__=='__main__':unittest.main()
