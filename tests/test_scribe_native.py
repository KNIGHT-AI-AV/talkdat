import ctypes,json,multiprocessing,sys,threading,time,unittest
from pathlib import Path
from types import SimpleNamespace
from knight_flow.overlay import Overlay
from knight_flow.web_shell.shell_backend import ShellBackend
from knight_flow.web_shell.shell_host import ShellController,_run_window,bundled_html
from tests.scribe_fixture import ScribeFixture

ASSETS=Path(__file__).resolve().parents[1]/'knight_flow/web_shell/shell_assets'
TEXT='Native Scribe 日本語 👩🏽‍💻\nComplete notes without truncation.\n'*1300


def native_scribe_probe(connection,evidence,html):
    if sys.platform=='win32':
        from ctypes import wintypes
        user=ctypes.windll.user32;user.GetThreadDesktop.restype=wintypes.HANDLE
        desktop=user.GetThreadDesktop(ctypes.windll.kernel32.GetCurrentThreadId());name=ctypes.create_unicode_buffer(256);required=wintypes.DWORD()
        if not user.GetUserObjectInformationW(desktop,2,name,ctypes.sizeof(name),ctypes.byref(required)) or not name.value.startswith('talkdat-tests-'):
            evidence.send({'error':'Scribe proof requires an isolated desktop'});return
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
                raise AssertionError('Scribe control did not settle: '+script)
            def click(text):
                until("Array.from(document.querySelectorAll('button')).some(b=>b.textContent==="+repr(text)+"&&b.getClientRects().length&&!b.disabled)")
                window.evaluate_js("Array.from(document.querySelectorAll('button')).find(b=>b.textContent==="+repr(text)+"&&b.getClientRects().length&&!b.disabled).click();true")
            try:
                until("document.body.classList.contains('connected')")
                window.evaluate_js("window.TalkDat.navigate('scribe');true");click('Start recording');click('Finish recording')
                until("document.querySelector('.scribe-phase').textContent.includes('Saved and ready')")
                click('Edit notes')
                window.evaluate_js("var editor=document.querySelector('[aria-label=\"Scribe notes\"]');editor.value="+json.dumps(TEXT)+";editor.dispatchEvent(new Event('input',{bubbles:true}));true")
                until("document.querySelector('.scribe-status').textContent.includes('Draft saved on this computer')")
                window.evaluate_js("window.TalkDat.navigate('general');true");until("document.querySelector('main h1').textContent==='General'")
                window.evaluate_js("window.TalkDat.navigate('scribe');true");click('Edit notes')
                assert window.evaluate_js("document.querySelector('[aria-label=\"Scribe notes\"]').value")==TEXT
                click('Copy');click('Save a copy')
                until("document.querySelector('.scribe-status').textContent.includes('could not be saved')")
                assert window.evaluate_js("document.querySelector('[aria-label=\"Scribe notes\"]').value")==TEXT
                click('Save a copy');until("document.querySelector('.scribe-status').textContent.includes('new copy is saved')")
                window.evaluate_js("document.querySelector('.scribe-receipt button').click();true")
                until("document.getElementById('notice').textContent==='Opened the saved notes.'")
                window.evaluate_js("document.querySelector('.scribe-library summary').click();true");click('Refresh recordings')
                until("document.querySelector('.scribe-library-entry')&&!document.querySelector('.scribe-library-entry').disabled")
                window.evaluate_js("document.querySelector('.scribe-library-entry').click();true")
                until("document.querySelector('.scribe-status').textContent.includes('Saved recording opened')")
                assert window.evaluate_js("document.querySelector('[aria-label=\"Scribe notes\"]').value")==TEXT
                evidence.send({'surface':surface,'status':'Native recording review, long draft, save failure/retry, copy and recovery passed'})
            except Exception as error:evidence.send({'error':str(error),'ui':window.evaluate_js('document.body.innerText.slice(-2000)')})
            finally:window.destroy()
        window.events.loaded+=probe;return window
    webview.create_window=create_probe
    _run_window(connection,html,'scribe',hidden=sys.platform=='darwin')


@unittest.skipUnless(sys.platform in {'win32','darwin'},'Native desktop Scribe acceptance')
class NativeScribeTests(unittest.TestCase):
    def test_native_long_draft_save_retry_copy_and_reopen(self):
        fixture=ScribeFixture();self.addCleanup(fixture.temp.cleanup);fixture.flags['save_failures']=1
        backend=ShellBackend(fixture.config,ASSETS,lambda _:None,lambda:None,object.__new__(Overlay)._settings_palette,
            workspaces=SimpleNamespace(handle=lambda p:fixture.service.handle({k:v for k,v in p.items() if k!='area'})))
        context=multiprocessing.get_context('spawn');parent,child=context.Pipe();receiver,sender=context.Pipe(duplex=False)
        process=context.Process(target=native_scribe_probe,args=(child,sender,bundled_html(ASSETS)));process.start();child.close();sender.close()
        controller=ShellController(ASSETS,fixture.queue.put,backend.handle,on_failure=lambda:None);controller.connection=parent
        listener=threading.Thread(target=controller._listen,args=(parent,),daemon=True);listener.start()
        try:
            deadline=time.monotonic()+80
            while time.monotonic()<deadline and not receiver.poll():fixture.drain();time.sleep(.005)
            self.assertTrue(receiver.poll(),'No native Scribe result');result=receiver.recv();self.assertNotIn('error',result,result)
            fixture.drain();self.assertEqual(fixture.flags['starts'],1);self.assertEqual(fixture.flags['copied'],[TEXT]);self.assertEqual(len(fixture.flags['opened']),1)
            self.assertEqual(fixture.engine.body,TEXT);self.assertEqual(fixture.engine.saved_path.read_text(encoding='utf-8'),TEXT)
            self.assertTrue(fixture.engine.recorder.closed.is_set());print(result['status'],'on',result['surface'])
        finally:
            process.join(5)
            if process.is_alive():process.terminate();process.join(5)
            listener.join(2);parent.close();receiver.close()


if __name__=='__main__':unittest.main()
