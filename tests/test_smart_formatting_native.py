"""The smart formatting step and Settings row, driven in the real web view.

Proves the JavaScript half: the card appears on the Voice chapter with the
recommended button primary, Set up starts the job and progress is visible,
Finish setup completes while it is still downloading, and Settings >
Formatting shows the same job through Failed, Retry and Ready. The setup
object is a fake, so nothing is installed and nothing is downloaded.
"""
import copy,ctypes,multiprocessing,queue,sys,threading,time,unittest
from pathlib import Path
from types import SimpleNamespace
from knight_flow.config import DEFAULT_CONFIG
from knight_flow.overlay import Overlay
from knight_flow.web_shell import shell_backend
from knight_flow.web_shell.shell_host import ShellController,_run_window,bundled_html
from knight_flow.web_shell.setup_workspace import SetupWorkspace

ASSETS=Path(__file__).resolve().parents[1]/'knight_flow/web_shell/shell_assets'


def native_formatting_probe(connection,evidence,html):
    if sys.platform=='win32':
        from ctypes import wintypes
        user=ctypes.windll.user32;user.GetThreadDesktop.restype=wintypes.HANDLE
        desktop=user.GetThreadDesktop(ctypes.windll.kernel32.GetCurrentThreadId())
        name=ctypes.create_unicode_buffer(256);required=wintypes.DWORD()
        if not user.GetUserObjectInformationW(desktop,2,name,ctypes.sizeof(name),ctypes.byref(required)) or not name.value.startswith('talkdat-tests-'):
            evidence.send({'error':'The native proof requires the isolated desktop'});return
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
                deadline=time.monotonic()+20
                while time.monotonic()<deadline:
                    if window.evaluate_js(script):return
                    time.sleep(.05)
                raise AssertionError('Did not settle: '+script)
            def click(text):
                until("Array.from(document.querySelectorAll('button')).some(b=>b.textContent==="+repr(text)+"&&b.getClientRects().length&&!b.disabled)")
                window.evaluate_js("Array.from(document.querySelectorAll('button')).find(b=>b.textContent==="+repr(text)+"&&b.getClientRects().length&&!b.disabled).click();true")
            try:
                until("document.body.classList.contains('connected')")
                window.evaluate_js("window.TalkDat.navigate('setup');true")
                until("document.querySelector('.setup-welcome')")
                click('Voice');until("document.querySelector('.setup-formatting')&&!document.querySelector('.setup-formatting').hidden")
                assert window.evaluate_js("document.querySelector('.setup-formatting').textContent.includes('Formatting runs on')")
                assert window.evaluate_js("document.querySelector('.setup-formatting').textContent.includes('Recommended for')")
                assert window.evaluate_js("Array.from(document.querySelectorAll('.setup-formatting button')).find(b=>b.textContent==='Set up smart formatting').classList.contains('primary')")
                assert window.evaluate_js("Array.from(document.querySelectorAll('.setup-formatting button')).some(b=>b.textContent==='Not now')")
                click('Set up smart formatting')
                until("document.querySelector('.setup-formatting-status')?.textContent.includes('Downloading 40%')")
                until("document.querySelector('.setup-formatting progress')?.value===40")
                click('Try it');until("document.querySelector('.setup-formatting-note')&&!document.querySelector('.setup-formatting-note').hidden")
                click('Finish setup');until("document.querySelector('.setup-status')?.textContent.includes('Setup saved')")
                window.evaluate_js("window.TalkDat.navigate('formatting');true")
                until("document.querySelector('#smart-formatting')?.textContent.includes('Downloading 40%')")
                until("Array.from(document.querySelectorAll('#smart-formatting button')).some(b=>b.textContent==='Retry')")
                assert window.evaluate_js("document.querySelector('#smart-formatting').textContent.includes('Failed')")
                click('Retry')
                until("document.querySelector('#smart-formatting .smart-formatting-state')?.textContent.startsWith('Ready')")
                assert window.evaluate_js("!Array.from(document.querySelectorAll('#smart-formatting button')).length")
                evidence.send({'desktop':surface,'status':'passed'})
            except Exception as error:evidence.send({'error':str(error),'ui':window.evaluate_js('document.body.innerText.slice(-1500)')})
            finally:window.destroy()
        window.events.loaded+=probe;return window
    webview.create_window=create_probe
    _run_window(connection,html,'setup',hidden=sys.platform=='darwin')


class FakeFormatting:
    """Not set up -> (start) downloading 40% for a few polls -> failed -> (retry) ready."""
    def __init__(self):self.starts=0;self.polls=0;self.state='not_set_up'
    def start(self):
        self.starts+=1;self.polls=0
        self.state='downloading' if self.starts==1 else 'ready'
        return {'message':'Smart formatting setup started.'}
    def check_again(self):return {'message':'Checked again.'}
    def open_download_page(self):return {'message':'opened'}
    def snapshot(self):
        if self.state=='downloading':
            self.polls+=1
            if self.polls>8:self.state='failed'
        labels={'not_set_up':'Not set up','downloading':'Downloading 40%','failed':'Failed','ready':'Ready'}
        return {'state':self.state,'label':labels[self.state],'percent':40 if self.state=='downloading' else None,
            'message':'The download did not finish.' if self.state=='failed' else '','title':'Smart formatting',
            'explanation':'Formatting runs on this PC. Nothing you say leaves it. Setup downloads a writing model (about 2.5 GB) once.',
            'note':'','recommended':True,'recommended_label':'Recommended for this PC',
            'can_start':self.state in {'not_set_up','failed'},'download_page':False,'offer_in_setup':True}


@unittest.skipUnless(sys.platform in {'win32','darwin'},'Native desktop acceptance')
class NativeSmartFormattingTests(unittest.TestCase):
    def test_setup_step_and_settings_row(self):
        tasks=queue.Queue();config=copy.deepcopy(DEFAULT_CONFIG);fake=FakeFormatting()
        def save(candidate):return {'saved':True,'runtime_refreshed':True}
        def action(name,value):
            if name=='permissions':return []
            if name=='speech_status':return {'active':False,'processing':False}
        idle={'check':{'phase':'idle','mode':'mic','active':False,'message':'Microphone off.','level':0,'elapsed':0,'seconds':3,'text':'','report':None,'recognition_ms':None},'devices':{'status':'ready','devices':[],'message':''},'selected':''}
        microphone=SimpleNamespace(snapshot=lambda:copy.deepcopy(idle),handle=lambda _:copy.deepcopy(idle))
        service=SetupWorkspace(config,save,action,microphone,fake)
        backend=shell_backend.ShellBackend(config,ASSETS,lambda _:None,lambda:None,object.__new__(Overlay)._settings_palette,
            workspaces=SimpleNamespace(handle=lambda p:service.handle({k:v for k,v in p.items() if k!='area'})),formatting=fake)
        context=multiprocessing.get_context('spawn');parent,child=context.Pipe();receiver,sender=context.Pipe(duplex=False)
        process=context.Process(target=native_formatting_probe,args=(child,sender,bundled_html(ASSETS)));process.start();child.close();sender.close()
        controller=ShellController(ASSETS,tasks.put,backend.handle,on_failure=lambda:None);controller.connection=parent
        listener=threading.Thread(target=controller._listen,args=(parent,),daemon=True);listener.start()
        try:
            deadline=time.monotonic()+120
            while time.monotonic()<deadline and not receiver.poll():
                while not tasks.empty():tasks.get_nowait()()
                time.sleep(.005)
            self.assertTrue(receiver.poll(),'No native receipt');result=receiver.recv();self.assertNotIn('error',result,result)
            self.assertEqual(fake.starts,2)
            self.assertTrue(config['onboarding']['completed'])
            self.assertEqual(config['onboarding']['smart_formatting'],'started')
            print('Native smart formatting step and Settings row passed on',result['desktop'])
        finally:
            process.join(5)
            if process.is_alive():process.terminate();process.join(5)
            listener.join(2);parent.close();receiver.close()


if __name__=='__main__':unittest.main()
