import ctypes,multiprocessing,queue,sys,tempfile,threading,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from knight_flow.config import DEFAULT_CONFIG
from knight_flow.overlay import Overlay
from knight_flow.web_shell.shell_backend import ShellBackend
from knight_flow.web_shell.shell_host import ShellController,_run_window,bundled_html
from knight_flow.web_shell.history_exports import HistoryExports
from knight_flow.web_shell.history_workspace import HistoryWorkspace
import copy

ASSETS=Path(__file__).resolve().parents[1]/'knight_flow/web_shell/shell_assets'

def native_history_export_probe(connection,evidence,html):
    if sys.platform=='win32':
        from ctypes import wintypes
        user=ctypes.windll.user32;user.GetThreadDesktop.restype=wintypes.HANDLE
        desktop=user.GetThreadDesktop(ctypes.windll.kernel32.GetCurrentThreadId())
        name=ctypes.create_unicode_buffer(256);required=wintypes.DWORD()
        if not user.GetUserObjectInformationW(desktop,2,name,ctypes.sizeof(name),ctypes.byref(required)) or not name.value.startswith('talkdat-tests-'):
            evidence.send({'error':'History native proof requires the isolated desktop'});return
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
                raise AssertionError('History export did not settle: '+script)
            def click(text):window.evaluate_js("Array.from(document.querySelectorAll('button')).find(b=>b.textContent==="+repr(text)+").click();true")
            def open_history():
                window.evaluate_js("window.TalkDat.navigate('history');true")
                until("document.querySelector('.document-text')?.textContent.includes('Native saved words')")
                window.evaluate_js("document.querySelector('.workspace-options').open=true;true")
            try:
                until("document.body.classList.contains('connected')");open_history()
                click('Save a copy');until("document.querySelector('.history-export-status').textContent.includes('could not be saved')")
                click('Save a copy');until("document.querySelector('.history-export-controls button').disabled")
                click('Copy full text')
                window.evaluate_js("window.TalkDat.navigate('general');true");time.sleep(.4);open_history()
                until("document.querySelectorAll('.history-export-receipts li').length===1")
                click('Open');click('Show folder')
                until("document.getElementById('notice').textContent==='Copied the full entry.'")
                time.sleep(.12)
                # innerText needs a real layout pass, which a hidden/off-screen
                # WKWebView on macOS never runs; textContent reads the DOM
                # directly and does not depend on one.
                evidence.send({'receipt':window.evaluate_js("document.querySelector('.history-export-receipts').textContent"),'desktop':surface})
            except Exception as error:evidence.send({'error':str(error),'ui':window.evaluate_js('document.body.innerText.slice(-1600)')})
            finally:window.destroy()
        window.events.loaded+=probe;return window
    webview.create_window=create_probe
    _run_window(connection,html,'history',hidden=sys.platform=='darwin')


@unittest.skipUnless(sys.platform in {'win32','darwin'},'Native desktop History export acceptance')
class NativeHistoryExportTests(unittest.TestCase):
    def test_save_failure_retry_navigation_copy_and_explicit_file_actions(self):
        tasks=queue.Queue();copied=[];opened=[];workers=[];config=copy.deepcopy(DEFAULT_CONFIG)
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        path=Path(temporary.name)/'native-history.txt';path.write_text('Native saved words. 日本語 👩🏽‍💻',encoding='utf-8')
        calls=[]
        def loader(config,format):
            calls.append(format);workers.append(threading.get_ident());time.sleep(.2)
            if len(calls)==1:raise OSError('fixture save failure')
            return dict(path=path,entries=1,format=format,capped=False)
        exports=HistoryExports(config,tasks.put,opened.append,loader=loader)
        store=SimpleNamespace(recent=lambda _: [{'text':'Native saved words. 日本語 👩🏽‍💻','created_at':time.time()}])
        # Stable ids let the independently requested reader resolve its row.
        rows=store.recent(1);store.recent=lambda _:rows
        service=HistoryWorkspace(store,lambda:[],lambda _:None,lambda _:None,copied.append,exports=exports)
        backend=ShellBackend(config,ASSETS,lambda _:None,lambda:None,object.__new__(Overlay)._settings_palette,
            workspaces=SimpleNamespace(handle=lambda p:service.handle({k:v for k,v in p.items() if k!='area'})))
        context=multiprocessing.get_context('spawn');parent,child=context.Pipe();receiver,sender=context.Pipe(duplex=False)
        process=context.Process(target=native_history_export_probe,args=(child,sender,bundled_html(ASSETS)))
        process.start();child.close();sender.close()
        controller=ShellController(ASSETS,tasks.put,backend.handle,on_failure=lambda:None);controller.connection=parent
        listener=threading.Thread(target=controller._listen,args=(parent,),daemon=True);listener.start()
        try:
            deadline=time.monotonic()+65
            while time.monotonic()<deadline and not receiver.poll():
                while not tasks.empty():tasks.get_nowait()()
                time.sleep(.005)
            self.assertTrue(receiver.poll(),'No native History export receipt')
            result=receiver.recv();self.assertNotIn('error',result,result)
            self.assertIn('native-history.txt',result['receipt'])
            self.assertEqual(calls,['txt','txt']);self.assertEqual(copied,[rows[0]['text']])
            self.assertEqual(opened,[path,path.parent]);self.assertTrue(all(i!=threading.get_ident() for i in workers))
            print('Native History export failure, worker retry, navigation retention, full copy and explicit Open/folder passed on',result['desktop'])
        finally:
            process.join(5)
            if process.is_alive():process.terminate();process.join(5)
            listener.join(2);parent.close();receiver.close()

if __name__=='__main__':unittest.main()
