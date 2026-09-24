"""Real Ramble editing, worker exports and recovery through the native pipe."""
import copy
import ctypes
import multiprocessing
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest

from knight_flow.config import DEFAULT_CONFIG
from knight_flow.overlay import Overlay
from knight_flow.web_shell.ramble_workspace import RambleWorkspace
from knight_flow.web_shell.shell_backend import ShellBackend
from knight_flow.web_shell.shell_host import ShellController, _run_window, bundled_html


def native_ramble_probe(connection,evidence,html):
    if sys.platform=='win32':
        from ctypes import wintypes
        user=ctypes.windll.user32
        user.GetThreadDesktop.restype=wintypes.HANDLE
        desktop=user.GetThreadDesktop(ctypes.windll.kernel32.GetCurrentThreadId())
        name=ctypes.create_unicode_buffer(256);required=wintypes.DWORD()
        if not user.GetUserObjectInformationW(desktop,2,name,ctypes.sizeof(name),ctypes.byref(required)) or not name.value.startswith('talkdat-tests-'):
            evidence.send({'error':'Native Ramble proof requires the isolated desktop'});return
        surface=name.value
    else:surface='hidden WKWebView'
    import webview
    if sys.platform=='darwin':
        from webview.platforms.cocoa import BrowserView
        BrowserView.app.setActivationPolicy_(2)
    create=webview.create_window
    once=threading.Event()
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
                raise AssertionError('Native Ramble control did not settle: '+script[:100])
            def click(label):
                import json
                window.evaluate_js("Array.from(document.querySelectorAll('.ramble-workspace button')).find(b=>b.textContent==="+json.dumps(label)+").click();true")
            try:
                until("document.body.classList.contains('connected')")
                window.evaluate_js("window.TalkDat.navigate('ramble');true")
                until("document.querySelector('[aria-label=\"Ramble draft\"]') && !document.querySelector('[aria-label=\"Ramble draft\"]').disabled")
                window.evaluate_js("(()=>{const draft=document.querySelector('[aria-label=\"Ramble draft\"]');draft.value='  Native 美和 👨‍👩‍👧‍👦 € 425,75.\\n'.repeat(900);draft.dispatchEvent(new Event('input',{bubbles:true}));})();true")
                click('Copy')
                until("document.getElementById('notice').textContent.startsWith('Text copied.')")
                window.evaluate_js("window.TalkDat.navigate('general');true")
                until("document.querySelector('main h1').textContent==='General'")
                window.evaluate_js("window.TalkDat.navigate('ramble');true")
                until("document.querySelector('[aria-label=\"Ramble draft\"]')?.value.startsWith('  Native')")
                click('Finish writing')
                until("document.querySelector('[aria-label=\"Ramble draft\"]')?.value.startsWith('Finished:')")
                original=window.evaluate_js("document.querySelector('[aria-label=\"Original Ramble text\"]').value")
                window.evaluate_js("(()=>{const field=document.querySelector('[aria-label=\"Document format\"]');field.value='text';field.dispatchEvent(new Event('change',{bubbles:true}));})();true")
                click('Save document')
                until("document.querySelector('.ramble-status').textContent.startsWith('Saved ')")
                click('Save document')
                until("document.querySelector('.ramble-status').textContent.includes('Injected export failure')")
                retained=window.evaluate_js("document.querySelector('[aria-label=\"Ramble draft\"]').value")
                click('Record more')
                until("Array.from(document.querySelectorAll('.ramble-toolbar button')).some(b=>b.textContent==='Finish recording'&&!b.disabled)")
                click('Finish recording')
                until("document.querySelector('[aria-label=\"Ramble draft\"]')?.value.endsWith('Native microphone addition.')")
                evidence.send({'original':original,'retained':retained,
                    'final':window.evaluate_js("document.querySelector('[aria-label=\"Ramble draft\"]').value"),'desktop':surface})
            except Exception as error:
                evidence.send({'error':str(error),'ui':window.evaluate_js('document.body.innerText.slice(-2500)')})
            finally:window.destroy()
        window.events.loaded+=probe
        return window
    webview.create_window=create_probe
    _run_window(connection,html,'ramble',hidden=sys.platform=='darwin')


@unittest.skipUnless(sys.platform in {'win32','darwin'},'Native desktop Ramble acceptance')
class NativeRambleTests(unittest.TestCase):
    def test_edit_copy_reopen_finish_save_and_record_through_the_real_pipe(self):
        assets=Path(__file__).resolve().parents[1]/'knight_flow/web_shell/shell_assets'
        tasks=[];copied=[];exports=[];recording={'active':False,'sink':None};attempts=[]
        with tempfile.TemporaryDirectory() as folder:
            config=copy.deepcopy(DEFAULT_CONFIG)
            config['privacy']['save_history']=False
            def utility(action,value):
                if action=='writing_ready':return True
                if action=='copy':copied.append(value)
                if action=='finish':return 'Finished: '+value['text']
                if action=='export':
                    attempts.append(threading.get_ident())
                    if len(attempts)>1:raise OSError('Injected export failure.')
                    from knight_flow.ramble_export import render
                    from knight_flow.export_files import save_new_export
                    data,extension=render(value['text'],value['format'])
                    path=save_new_export(Path(folder),'native-ramble.'+extension,data)
                    exports.append(path);return path
                if action=='speech_start':recording.update(active=True,sink=value)
                if action=='speech_active':return recording['active']
                if action=='speech_cancel':recording['active']=False
                if action=='speech_stop':
                    def deliver():
                        recording['active']=False
                        recording['sink']('Native microphone addition.')
                    tasks.append(deliver)
            workspace=RambleWorkspace(config,utility,tasks.append)
            backend=ShellBackend(config,assets,lambda _:None,lambda:None,
                object.__new__(Overlay)._settings_palette,
                workspaces=SimpleNamespace(handle=lambda payload:workspace.handle({key:value for key,value in payload.items() if key!='area'})))
            context=multiprocessing.get_context('spawn')
            parent,child=context.Pipe();receiver,sender=context.Pipe(duplex=False)
            process=context.Process(target=native_ramble_probe,args=(child,sender,bundled_html(assets)))
            process.start();child.close();sender.close()
            controller=ShellController(assets,tasks.append,backend.handle,on_failure=lambda:None)
            controller.connection=parent
            listener=threading.Thread(target=controller._listen,args=(parent,),daemon=True);listener.start()
            try:
                deadline=time.monotonic()+90
                while time.monotonic()<deadline and not receiver.poll():
                    while tasks:tasks.pop(0)()
                    time.sleep(.01)
                self.assertTrue(receiver.poll(),'No native Ramble result')
                result=receiver.recv();self.assertNotIn('error',result,result)
                source='  Native 美和 👨‍👩‍👧‍👦 € 425,75.\n'*900
                self.assertEqual(copied,[source])
                self.assertEqual(result['original'],source)
                self.assertEqual(result['retained'],'Finished: '+source)
                self.assertEqual(result['final'],'Finished: '+source+'\n\nNative microphone addition.')
                self.assertEqual(len(exports),1)
                self.assertIn('Finished: '+source,exports[0].read_text(encoding='utf-8'))
                self.assertTrue(all(identifier!=threading.get_ident() for identifier in attempts))
                print('Native Ramble draft, copy, reopen, finish, export failure and microphone handoff passed on',result['desktop'])
            finally:
                process.join(5)
                if process.is_alive():process.terminate();process.join(5)
                listener.join(2);parent.close();receiver.close()


if __name__=='__main__':unittest.main()
