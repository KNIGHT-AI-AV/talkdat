import copy,ctypes,multiprocessing,queue,sys,threading,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from knight_flow.config import DEFAULT_CONFIG
from knight_flow.overlay import Overlay
from knight_flow.mic_registry import MicrophoneRegistry
from knight_flow.web_shell import shell_backend
from knight_flow.web_shell.shell_backend import ShellBackend
from knight_flow.web_shell.shell_host import ShellController,_run_window,bundled_html
from knight_flow.microphone_check import MicrophoneCheck
from knight_flow.web_shell.mic_check_workspace import MicCheckWorkspace


def native_mic_probe(connection,evidence,html):
    if sys.platform=='win32':
        from ctypes import wintypes
        user=ctypes.windll.user32;user.GetThreadDesktop.restype=wintypes.HANDLE
        desktop=user.GetThreadDesktop(ctypes.windll.kernel32.GetCurrentThreadId())
        name=ctypes.create_unicode_buffer(256);required=wintypes.DWORD()
        if not user.GetUserObjectInformationW(desktop,2,name,ctypes.sizeof(name),ctypes.byref(required)) or not name.value.startswith('talkdat-tests-'):
            evidence.send({'error':'Microphone UI proof requires the isolated desktop'});return
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
                    time.sleep(.04)
                raise AssertionError('Microphone UI did not settle: '+script)
            def click(text):window.evaluate_js("Array.from(document.querySelectorAll('button')).find(b=>b.textContent==="+repr(text)+").click();true")
            def phase(value):until("document.querySelector('[data-workspace=mic-check]')?.dataset.phase==="+repr(value))
            try:
                until("document.body.classList.contains('connected')")
                window.evaluate_js("window.TalkDat.navigate('mic-doctor');true")
                until("document.querySelector('.mic-selection-status')?.textContent.includes('Selecting')")
                click('Check my mic');phase('error')
                error=window.evaluate_js("document.querySelector('.mic-check-status').getAttribute('role')")
                click('Check my mic');phase('ready')
                metrics=window.evaluate_js("document.querySelectorAll('.mic-check-metrics dd').length")
                click('Check my mic');phase('listening')
                window.evaluate_js("window.TalkDat.navigate('general');true")
                until("document.querySelector('main h1')?.textContent==='General'")
                time.sleep(.1)
                window.evaluate_js("window.TalkDat.navigate('speech-check');true")
                until("Array.from(document.querySelectorAll('button')).some(b=>b.textContent==='Start speech check'&&!b.disabled)")
                click('Start speech check');phase('ready');click('Copy test words')
                until("document.getElementById('notice')?.textContent==='Test words copied.'")
                text=window.evaluate_js("document.querySelector('.mic-check-transcript').textContent")
                evidence.send({'metrics':metrics,'error':error,'text':text,'desktop':surface})
            except Exception as error:evidence.send({'error':str(error),'ui':window.evaluate_js('document.body.innerText.slice(-1600)')})
            finally:window.destroy()
        window.events.loaded+=probe
        return window
    webview.create_window=create_probe
    _run_window(connection,html,'mic-doctor',hidden=sys.platform=='darwin')


@unittest.skipUnless(sys.platform in {'win32','darwin'},'Native desktop microphone acceptance')
class NativeMicrophoneWorkspaceTests(unittest.TestCase):
    def test_error_retry_result_navigation_cancel_and_speech_copy(self):
        assets=Path(__file__).resolve().parents[1]/'knight_flow/web_shell/shell_assets';config=copy.deepcopy(DEFAULT_CONFIG)
        config['audio']['input_device']='7: Synthetic selected microphone'
        tasks=queue.Queue();registry=MicrophoneRegistry();calls=[];copies=[];workers=[];sessions=[]
        def start(mode):
            if sessions and not sessions[-1].finished.is_set():raise ValueError('Previous check is still stopping.')
            check=MicrophoneCheck(config,registry=registry,dispatch=tasks.put,mode=mode,prepare=lambda _:None,
                recognize=lambda *args:'Native words.\n日本語 👩🏽‍💻')
            sessions.append(check);check.start();return check
        devices=SimpleNamespace(snapshot=lambda:{'status':'ready','devices':[config['audio']['input_device']],'message':''},refresh=lambda:None)
        service=MicCheckWorkspace(config,lambda _:None,start,copies.append,devices)
        backend=ShellBackend(config,assets,lambda _:None,lambda:None,object.__new__(Overlay)._settings_palette,
            workspaces=SimpleNamespace(handle=lambda payload:service.handle({k:v for k,v in payload.items() if k!='area'})))
        def open_stream(**kwargs):
            calls.append(kwargs['device']);workers.append(threading.get_ident())
            if len(calls)==1:raise OSError('Injected first-open failure')
            delay=.07 if len(calls)==3 else .005
            class Stream:
                def __init__(self):self.stop_event=threading.Event();self.thread=None
                def start(self):
                    def feed():
                        for index in range(80):
                            if self.stop_event.is_set():break
                            kwargs['callback'](b'\x00\x08'*1600,1600,None,None)
                            self.stop_event.wait(delay)
                    self.thread=threading.Thread(target=feed,daemon=True);self.thread.start()
                def stop(self):self.stop_event.set()
                def close(self):self.stop_event.set();self.thread.join(1)
            return Stream(),16000,1,7
        html=bundled_html(assets)
        context=multiprocessing.get_context('spawn');parent,child=context.Pipe();receiver,sender=context.Pipe(duplex=False)
        process=context.Process(target=native_mic_probe,args=(child,sender,html))
        process.start();child.close();sender.close()
        controller=ShellController(assets,tasks.put,backend.handle,on_failure=lambda:None);controller.connection=parent
        listener=threading.Thread(target=controller._listen,args=(parent,),daemon=True);listener.start()
        try:
            with patch('knight_flow.audio_input.open_raw_input_stream',open_stream),patch('knight_flow.audio_input.resolve_input_device',return_value=7):
                deadline=time.monotonic()+90
                while time.monotonic()<deadline and not receiver.poll():
                    while not tasks.empty():tasks.get_nowait()()
                    time.sleep(.005)
                self.assertTrue(receiver.poll(),'No native microphone result')
                result=receiver.recv();self.assertNotIn('ui',result,result)
                self.assertEqual(result['error'],'alert');self.assertEqual(result['metrics'],3)
                self.assertEqual(result['text'],'Native words.\n日本語 👩🏽‍💻')
                self.assertEqual(copies,[result['text']]);self.assertEqual(calls,[7]*4)
                self.assertFalse(registry.is_active());self.assertTrue(all(i!=threading.get_ident() for i in workers))
                self.assertEqual(sessions[2].snapshot()['phase'],'cancelled')
                print('Native microphone error/retry, selected input, close ownership, navigation cancel and Unicode speech copy passed on',result['desktop'])
        finally:
            service.close();process.join(5)
            if process.is_alive():process.terminate();process.join(5)
            listener.join(2);parent.close();receiver.close()


if __name__=='__main__':unittest.main()
