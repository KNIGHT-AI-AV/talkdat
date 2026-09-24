import copy,ctypes,multiprocessing,queue,sys,tempfile,threading,time,unittest
from pathlib import Path
from types import SimpleNamespace
from knight_flow.config import DEFAULT_CONFIG
from knight_flow.overlay import Overlay
from knight_flow.web_shell import shell_backend
from knight_flow.web_shell.shell_host import ShellController,_run_window,bundled_html
from knight_flow.web_shell.feedback_workspace import FeedbackWorkspace

ASSETS=Path(__file__).resolve().parents[1]/'knight_flow/web_shell/shell_assets'


def native_feedback_probe(connection,evidence,html):
    if sys.platform=='win32':
        from ctypes import wintypes
        user=ctypes.windll.user32;user.GetThreadDesktop.restype=wintypes.HANDLE
        desktop=user.GetThreadDesktop(ctypes.windll.kernel32.GetCurrentThreadId())
        name=ctypes.create_unicode_buffer(256);required=wintypes.DWORD()
        if not user.GetUserObjectInformationW(desktop,2,name,ctypes.sizeof(name),ctypes.byref(required)) or not name.value.startswith('talkdat-tests-'):
            evidence.send({'error':'Feedback native proof requires the isolated desktop'});return
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
                raise AssertionError('Feedback did not settle: '+script)
            def click(text):window.evaluate_js("Array.from(document.querySelectorAll('button')).find(b=>b.textContent==="+repr(text)+"&&b.getClientRects().length).click();true")
            def field(identifier,value):window.evaluate_js("{const e=document.getElementById("+repr(identifier)+");e.value="+repr(value)+";e.dispatchEvent(new Event('input',{bubbles:true}));}true")
            try:
                until("document.body.classList.contains('connected')")
                window.evaluate_js("window.TalkDat.navigate('feedback');true")
                until("document.getElementById('feedback-title')&&!document.getElementById('feedback-title').disabled")
                field('feedback-title','A native fixture');field('feedback-details','Keep this complete message. 日本語 👩🏽‍💻')
                window.evaluate_js("window.TalkDat.navigate('general');true")
                until("!document.getElementById('feedback-title')")
                window.evaluate_js("window.TalkDat.navigate('feedback');true")
                until("document.getElementById('feedback-title')?.value==='A native fixture'")
                click('Open email draft');until("document.querySelector('.feedback-status')?.textContent.includes('Finish sending')")
                click('Send to the team');until("document.querySelector('.feedback-status')?.textContent.includes('Delivery was not confirmed')")
                assert window.evaluate_js("document.getElementById('feedback-details').value.includes('日本語')")
                click('Copy message');click('Preview formatting log')
                until("document.querySelector('.feedback-log-dialog textarea')?.value.includes('Approved synthetic log')")
                click('Attach this excerpt');click('Send to the team')
                until("document.querySelector('.feedback-status')?.textContent.includes('Sending')")
                window.evaluate_js("window.TalkDat.navigate('general');true")
                until("!document.getElementById('feedback-title')")
                window.evaluate_js("window.TalkDat.navigate('feedback');true")
                until("document.querySelector('.feedback-status')?.textContent.includes('confirmed receipt')")
                assert window.evaluate_js("!document.getElementById('feedback-include').checked")
                evidence.send({'desktop':surface,'status':window.evaluate_js("document.querySelector('.feedback-status').textContent")})
            except Exception as error:evidence.send({'error':str(error),'ui':window.evaluate_js('document.body.innerText.slice(-1600)')})
            finally:window.destroy()
        window.events.loaded+=probe;return window
    webview.create_window=create_probe
    _run_window(connection,html,'feedback',hidden=sys.platform=='darwin')


@unittest.skipUnless(sys.platform in {'win32','darwin'},'Native desktop feedback acceptance')
class NativeFeedbackTests(unittest.TestCase):
    def test_draft_navigation_explicit_email_unconfirmed_retry_and_reviewed_logs(self):
        tasks=queue.Queue();sent=[];copied=[];opened=[];worker_threads=[];logs=[];config=copy.deepcopy(DEFAULT_CONFIG)
        def sender(payload):
            sent.append(copy.deepcopy(payload));worker_threads.append(threading.get_ident());time.sleep(.6)
            return len(sent)>1
        def read_logs():logs.append(threading.get_ident());return 'Approved synthetic log 日本語'
        service=FeedbackWorkspace(tasks.put,sender,read_logs,copied.append,lambda url:opened.append(url) or True)
        pages=shell_backend.PAGES
        if not any(row[0]=='feedback' for row in pages):
            shell_backend.PAGES=(*pages,('feedback','Share an idea','Share an idea','Tell us what would make Talk DAT better.'),('language-request','Request a language','Request a language','Tell us which language and region matter to you.'))
        self.addCleanup(setattr,shell_backend,'PAGES',pages)
        backend=shell_backend.ShellBackend(config,ASSETS,lambda _:None,lambda:None,object.__new__(Overlay)._settings_palette,
            workspaces=SimpleNamespace(handle=lambda p:service.handle({k:v for k,v in p.items() if k!='area'})))
        context=multiprocessing.get_context('spawn');parent,child=context.Pipe();receiver,sender_pipe=context.Pipe(duplex=False)
        process=context.Process(target=native_feedback_probe,args=(child,sender_pipe,bundled_html(ASSETS)))
        process.start();child.close();sender_pipe.close()
        controller=ShellController(ASSETS,tasks.put,backend.handle,on_failure=lambda:None);controller.connection=parent
        listener=threading.Thread(target=controller._listen,args=(parent,),daemon=True);listener.start()
        try:
            deadline=time.monotonic()+65
            while time.monotonic()<deadline and not receiver.poll():
                while not tasks.empty():tasks.get_nowait()()
                time.sleep(.005)
            self.assertTrue(receiver.poll(),'No native feedback receipt')
            result=receiver.recv();self.assertNotIn('error',result,result)
            self.assertEqual(len(sent),2);self.assertNotIn('logs',sent[0]);self.assertEqual(sent[1]['logs'],'Approved synthetic log 日本語')
            self.assertEqual(len(opened),1);self.assertEqual(copied,[sent[0]['text']]);self.assertEqual(logs,[threading.get_ident()])
            self.assertTrue(all(i!=threading.get_ident() for i in worker_threads))
            print('Native feedback draft, explicit email, unconfirmed retry, navigation receipt and reviewed-log consent passed on',result['desktop'])
        finally:
            process.join(5)
            if process.is_alive():process.terminate();process.join(5)
            listener.join(2);parent.close();receiver.close()

if __name__=='__main__':unittest.main()
