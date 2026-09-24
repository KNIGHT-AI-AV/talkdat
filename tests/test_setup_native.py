import copy,ctypes,multiprocessing,queue,sys,threading,time,unittest
from pathlib import Path
from types import SimpleNamespace
from knight_flow.config import DEFAULT_CONFIG
from knight_flow.overlay import Overlay
from knight_flow.web_shell import shell_backend
from knight_flow.web_shell.shell_host import ShellController,_run_window,bundled_html
from knight_flow.web_shell.setup_workspace import SetupWorkspace

ASSETS=Path(__file__).resolve().parents[1]/'knight_flow/web_shell/shell_assets'


def native_setup_probe(connection,evidence,html):
    if sys.platform=='win32':
        from ctypes import wintypes
        user=ctypes.windll.user32;user.GetThreadDesktop.restype=wintypes.HANDLE
        desktop=user.GetThreadDesktop(ctypes.windll.kernel32.GetCurrentThreadId())
        name=ctypes.create_unicode_buffer(256);required=wintypes.DWORD()
        if not user.GetUserObjectInformationW(desktop,2,name,ctypes.sizeof(name),ctypes.byref(required)) or not name.value.startswith('talkdat-tests-'):
            evidence.send({'error':'Setup native proof requires the isolated desktop'});return
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
                raise AssertionError('Setup did not settle: '+script)
            def click(text):
                until("Array.from(document.querySelectorAll('button')).some(b=>b.textContent==="+repr(text)+"&&b.getClientRects().length&&!b.disabled)")
                window.evaluate_js("Array.from(document.querySelectorAll('button')).find(b=>b.textContent==="+repr(text)+"&&b.getClientRects().length).click();true")
            try:
                until("document.body.classList.contains('connected')")
                window.evaluate_js("window.TalkDat.navigate('setup');true")
                until("document.querySelector('.setup-welcome')")
                click('Try it');until("document.querySelector('.setup-result')")
                click('Start practice');until("Array.from(document.querySelectorAll('button')).some(b=>b.textContent==='Finish recording'&&!b.disabled)")
                click('Finish recording');until("document.querySelector('.setup-practice-status')?.textContent.includes('No words returned')")
                assert window.evaluate_js("document.querySelector('.setup-receipts').textContent.includes('Practice words received: not checked')")
                click('Start practice');until("Array.from(document.querySelectorAll('button')).some(b=>b.textContent==='Finish recording'&&!b.disabled)")
                click('Finish recording');until("document.querySelector('.setup-result')?.value.includes('日本語')")
                click('Copy result');click('Finish setup');until("document.querySelector('.setup-status')?.textContent.includes('could not be saved')")
                assert window.evaluate_js("document.querySelector('.setup-result').value.includes('日本語')")
                click('Finish setup');until("document.querySelector('.setup-status')?.textContent.includes('Setup saved')")
                click('Start practice');until("Array.from(document.querySelectorAll('button')).some(b=>b.textContent==='Finish recording'&&!b.disabled)")
                window.evaluate_js("window.TalkDat.navigate('general');true");until("!document.querySelector('.setup-workspace')")
                window.evaluate_js("window.TalkDat.navigate('setup');true");until("document.querySelector('.setup-result')")
                assert window.evaluate_js("document.querySelector('.setup-practice-status').textContent.includes('cancelled')")
                click('Voice');until("document.querySelector('.setup-permission')")
                assert window.evaluate_js("document.querySelector('.setup-permission').textContent.includes('Could not check')")
                click('Review Microphone')
                until("Array.from(document.querySelectorAll('button')).some(b=>b.textContent==='Review Microphone'&&!b.disabled)")
                evidence.send({'desktop':surface,'status':'Setup completion, result ownership and permission truth passed'})
            except Exception as error:evidence.send({'error':str(error),'ui':window.evaluate_js('document.body.innerText.slice(-1800)')})
            finally:window.destroy()
        window.events.loaded+=probe;return window
    webview.create_window=create_probe
    _run_window(connection,html,'setup',hidden=sys.platform=='darwin')


@unittest.skipUnless(sys.platform in {'win32','darwin'},'Native desktop setup acceptance')
class NativeSetupTests(unittest.TestCase):
    def test_empty_result_save_retry_copy_cancel_and_unknown_permission(self):
        tasks=queue.Queue();config=copy.deepcopy(DEFAULT_CONFIG);flags={'started':0,'active':False,'finishes':0};copied=[];opened=[]
        def save(candidate):
            if candidate.get('onboarding',{}).get('completed'):
                flags['finishes']+=1
                if flags['finishes']==1:raise OSError('fixture save failure')
            return {'saved':True,'runtime_refreshed':True}
        def action(name,value):
            if name=='permissions':return [{'id':'microphone','label':'Microphone','state':'unknown'}]
            if name=='permission':opened.append(value)
            if name=='speech_start':flags.update(started=flags['started']+1,active=True,callback=value)
            if name=='speech_cancel':flags['active']=False
            if name=='speech_status':return {'active':flags['active'],'processing':False}
            if name=='speech_stop':flags['callback']('' if flags['started']==1 else 'Native setup result 日本語 👩🏽‍💻');flags['active']=False
            if name=='copy':copied.append(value)
        idle={'check':{'phase':'idle','mode':'mic','active':False,'message':'Microphone off.','level':0,'elapsed':0,'seconds':3,'text':'','report':None,'recognition_ms':None},'devices':{'status':'ready','devices':[],'message':''},'selected':''}
        microphone=SimpleNamespace(snapshot=lambda:copy.deepcopy(idle),handle=lambda _:copy.deepcopy(idle))
        service=SetupWorkspace(config,save,action,microphone)
        backend=shell_backend.ShellBackend(config,ASSETS,lambda _:None,lambda:None,object.__new__(Overlay)._settings_palette,
            workspaces=SimpleNamespace(handle=lambda p:service.handle({k:v for k,v in p.items() if k!='area'})))
        context=multiprocessing.get_context('spawn');parent,child=context.Pipe();receiver,sender=context.Pipe(duplex=False)
        process=context.Process(target=native_setup_probe,args=(child,sender,bundled_html(ASSETS)));process.start();child.close();sender.close()
        controller=ShellController(ASSETS,tasks.put,backend.handle,on_failure=lambda:None);controller.connection=parent
        listener=threading.Thread(target=controller._listen,args=(parent,),daemon=True);listener.start()
        try:
            deadline=time.monotonic()+65
            while time.monotonic()<deadline and not receiver.poll():
                while not tasks.empty():tasks.get_nowait()()
                time.sleep(.005)
            self.assertTrue(receiver.poll(),'No native setup receipt');result=receiver.recv();self.assertNotIn('error',result,result)
            while not tasks.empty():tasks.get_nowait()()
            self.assertEqual(copied,['Native setup result 日本語 👩🏽‍💻']);self.assertFalse(flags['active'])
            self.assertTrue(config['onboarding']['completed']);self.assertFalse(config['onboarding']['microphone_tested'])
            self.assertEqual(opened,['microphone']);print('Native setup empty-result truth, save retry, Unicode copy, navigation cancel and unknown permission passed on',result['desktop'])
        finally:
            process.join(5)
            if process.is_alive():process.terminate();process.join(5)
            listener.join(2);parent.close();receiver.close()


if __name__=='__main__':unittest.main()
