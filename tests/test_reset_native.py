"""Run the complete reset UI against disposable data in the native webview."""
import copy,ctypes,multiprocessing,os,queue,sys,tempfile,threading,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from knight_flow.config import DEFAULT_CONFIG
from knight_flow.overlay import Overlay
from knight_flow.web_shell.shell_backend import ShellBackend
from knight_flow.web_shell.shell_host import ShellController,_run_window,bundled_html
from knight_flow.web_shell.reset_workspace import ResetWorkspace
from knight_flow.web_shell.reset_adapter import ResetActions

ASSETS=Path(__file__).resolve().parents[1]/"knight_flow/web_shell/shell_assets"

def native_reset_probe(connection,evidence,html):
    if sys.platform=="win32":
        from ctypes import wintypes
        user=ctypes.windll.user32;user.GetThreadDesktop.restype=wintypes.HANDLE
        desktop=user.GetThreadDesktop(ctypes.windll.kernel32.GetCurrentThreadId())
        name=ctypes.create_unicode_buffer(256);required=wintypes.DWORD()
        if not user.GetUserObjectInformationW(desktop,2,name,ctypes.sizeof(name),ctypes.byref(required)) or not name.value.startswith("talkdat-tests-"):
            evidence.send({"error":"Reset proof requires an isolated desktop"});return
        surface=name.value
    else:surface="hidden WKWebView"
    import webview
    if sys.platform=="darwin":
        from webview.platforms.cocoa import BrowserView
        BrowserView.app.setActivationPolicy_(2)
    create=webview.create_window;once=threading.Event()
    def create_probe(*args,**kwargs):
        kwargs["focus"]=False;window=create(*args,**kwargs)
        def probe():
            if once.is_set():return
            once.set()
            def until(script):
                deadline=time.monotonic()+16
                while time.monotonic()<deadline:
                    if window.evaluate_js(script):return
                    time.sleep(.04)
                raise AssertionError("Reset control did not settle: "+script)
            def click(text):
                selector="Array.from(document.querySelectorAll('button')).find(b=>b.textContent==="+repr(text)+"&&b.getClientRects().length&&!b.disabled)"
                until("Boolean("+selector+")");window.evaluate_js(selector+".click();true")
            try:
                until("document.body.classList.contains('connected')")
                window.evaluate_js("window.TalkDat.navigate('reset');true")
                until("document.getElementById('reset-category-history')")
                window.evaluate_js("['settings','onboarding','history'].forEach(k=>document.getElementById('reset-category-'+k).click());true")
                click("Preview selected items")
                until("document.querySelector('.reset-review[open]')")
                assert window.evaluate_js("document.querySelector('[data-reset-confirm]').disabled")
                click("Go back")
                until("!document.querySelector('.reset-review')")
                click("Preview selected items")
                until("document.getElementById('reset-phrase')")
                window.evaluate_js("const p=document.getElementById('reset-phrase');p.value='ERASE';p.dispatchEvent(new Event('input',{bubbles:true}));true")
                click("Erase selected items")
                until("Array.from(document.querySelectorAll('button')).some(b=>b.textContent==='Close Talk DAT')")
                assert window.evaluate_js("document.querySelector('.reset-workspace').textContent.includes('items cleared')")
                window.evaluate_js("window.TalkDat.navigate('appearance');true")
                # X-744: an error is read to screen readers from #alert (role=alert).
                until("document.getElementById('alert').textContent.includes('Close Talk DAT')")
                assert window.evaluate_js("document.querySelector('main h1').textContent==='Clear local data'")
                assert window.evaluate_js("document.documentElement.scrollWidth<=window.innerWidth+1")
                click("Close Talk DAT")
                time.sleep(.2)
                evidence.send({"surface":surface,"status":"Native reset preview, cancel, typed consent, selective deletion and close receipt passed"})
            except Exception as error:
                evidence.send({"error":str(error),"ui":window.evaluate_js("document.body.innerText.slice(-2000)")})
            finally:window.destroy()
        window.events.loaded+=probe;return window
    webview.create_window=create_probe
    _run_window(connection,html,"reset",hidden=sys.platform=="darwin")

@unittest.skipUnless(sys.platform in {"win32","darwin"},"Native desktop reset acceptance")
class NativeResetTests(unittest.TestCase):
    def test_native_reset_preview_and_confirmation(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        env=patch.dict(os.environ,TALK_DAT_HOME=temporary.name);env.start();self.addCleanup(env.stop)
        root=Path(temporary.name);(root/"history.jsonl").write_text("fixture",encoding="utf-8")
        (root/"models").mkdir();(root/"models/keep.bin").write_bytes(b"keep")
        config=copy.deepcopy(DEFAULT_CONFIG);posts=queue.Queue();closed=[]
        app=SimpleNamespace(config=config,paused=False,_quitting=False,lock=threading.RLock(),
            _cross_thread_calls=posts,_auxiliary_audio_exit=lambda _resume:True,refresh_wake_word=lambda:None,
            last_transcript="fixture",overlay=SimpleNamespace(root=SimpleNamespace(after=lambda _ms,fn:posts.put(fn)),utility_windows={}),
            quit=lambda **_:closed.append(True))
        services=SimpleNamespace(services={})
        shell=SimpleNamespace(app=app,models=SimpleNamespace(lock=threading.RLock(),status={}),
                              workspaces=services,_capture_busy=lambda:False)
        actions=ResetActions(shell,threads=lambda:[])
        service=ResetWorkspace(config,root,posts.put,actions.busy,actions.execute,actions.finish)
        services.services["reset"]=service
        backend=ShellBackend(config,ASSETS,lambda _:None,lambda:None,object.__new__(Overlay)._settings_palette,
            workspaces=SimpleNamespace(handle=lambda p:service.handle({k:v for k,v in p.items() if k!="area"})))
        def drain():
            while not posts.empty():posts.get_nowait()()
        context=multiprocessing.get_context("spawn");parent,child=context.Pipe()
        receiver,sender=context.Pipe(duplex=False)
        process=context.Process(target=native_reset_probe,args=(child,sender,bundled_html(ASSETS)))
        process.start();child.close();sender.close()
        controller=ShellController(ASSETS,posts.put,backend.handle,on_failure=lambda:None);controller.connection=parent
        listener=threading.Thread(target=controller._listen,args=(parent,),daemon=True);listener.start()
        try:
            deadline=time.monotonic()+65
            while time.monotonic()<deadline and not receiver.poll():drain();time.sleep(.005)
            self.assertTrue(receiver.poll(),"No native reset result");result=receiver.recv()
            self.assertNotIn("error",result,result);drain()
            self.assertFalse((root/"history.jsonl").exists());self.assertTrue((root/"models/keep.bin").exists())
            self.assertTrue(closed);print(result["status"],"on",result["surface"])
        finally:
            process.join(5)
            if process.is_alive():process.terminate();process.join(5)
            listener.join(2);parent.close();receiver.close()

if __name__=="__main__":unittest.main()

