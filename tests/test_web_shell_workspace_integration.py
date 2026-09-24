"""Real native document controls, inherited pipe and isolated local stores."""
import copy
import ctypes
import json
import multiprocessing
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from knight_flow.config import DEFAULT_CONFIG
from knight_flow.overlay import Overlay
from knight_flow.web_shell.notes_workspace import NotesWorkspace
from knight_flow.web_shell.words_workspace import WordsWorkspace
from knight_flow.web_shell.translation_workspace import TranslationWorkspace
from knight_flow.web_shell.shell_backend import ShellBackend
from knight_flow.web_shell.shell_host import _run_window, _send, _receive, bundled_html, ShellController


def native_document_probe(connection, evidence, html):
    from ctypes import wintypes
    user=ctypes.windll.user32
    user.GetThreadDesktop.restype=wintypes.HANDLE
    desktop=user.GetThreadDesktop(ctypes.windll.kernel32.GetCurrentThreadId())
    name=ctypes.create_unicode_buffer(256);required=wintypes.DWORD()
    if not user.GetUserObjectInformationW(desktop,2,name,ctypes.sizeof(name),ctypes.byref(required)) or not name.value.startswith('talkdat-tests-'):
        evidence.send({'error':'Native document proof requires the isolated desktop'});return
    import webview
    original=webview.create_window
    once=threading.Event()
    def create(*args,**kwargs):
        window=original(*args,**kwargs)
        def probe():
            if once.is_set():return
            once.set()
            def until(script):
                deadline=time.monotonic()+18
                while time.monotonic()<deadline:
                    if window.evaluate_js(script):return
                    time.sleep(.05)
                raise AssertionError('Native control did not settle: '+script[:100])
            try:
                until("document.body.classList.contains('connected')")
                window.evaluate_js("window.TalkDat.navigate('scratchpad');true")
                until("document.querySelector('.note-editor') && !document.querySelector('.note-editor').disabled")
                window.evaluate_js("const editor=document.querySelector('.note-editor');editor.value='Native Unicode 👨‍👩‍👧‍👦 中文 <literal>\\n'.repeat(900);editor.dispatchEvent(new Event('input',{bubbles:true}));Array.from(document.querySelectorAll('button')).find(b=>b.textContent==='Save').click();true")
                until("document.querySelector('.note-status').textContent==='Saved on this computer.'")
                window.evaluate_js("Array.from(document.querySelectorAll('button')).find(b=>b.textContent==='Copy full note').click();true")
                until("document.getElementById('notice').textContent==='Copied the full note.'")
                window.evaluate_js("window.TalkDat.navigate('general');true")
                until("document.querySelector('main h1').textContent==='General'")
                window.evaluate_js("window.TalkDat.navigate('scratchpad');true")
                until("document.querySelector('.note-editor') && document.querySelector('.note-editor').value.startsWith('Native Unicode')")
                result=window.evaluate_js("({characters:Array.from(document.querySelector('.note-editor').value).length,text:document.querySelector('.note-editor').value,connected:document.body.classList.contains('connected')})")
                window.evaluate_js("window.TalkDat.navigate('words');true")
                until("document.querySelector('[data-workspace=words]') && !Array.from(document.querySelectorAll('button')).find(b=>b.textContent==='Add word').disabled")
                window.evaluate_js("Array.from(document.querySelectorAll('button')).find(b=>b.textContent==='Add word').click();true")
                until("document.getElementById('word-first') && !document.getElementById('word-first').disabled")
                window.evaluate_js("const word=document.getElementById('word-first');word.value='Native 美和';word.dispatchEvent(new Event('input',{bubbles:true}));const alias=document.getElementById('word-second');alias.value='native mee wa';alias.dispatchEvent(new Event('input',{bubbles:true}));Array.from(document.querySelectorAll('button')).find(b=>b.textContent==='Save entry').click();true")
                until("document.querySelector('.note-status').textContent==='Saved on this computer.' && document.querySelector('.document-entry strong')?.textContent==='Native 美和'")
                window.evaluate_js("document.querySelector('[aria-label=\\\"Word collections\\\"] button:last-child').click();true")
                until("Array.from(document.querySelectorAll('button')).some(b=>b.textContent==='Add snippet'&&!b.disabled)")
                window.evaluate_js("Array.from(document.querySelectorAll('button')).find(b=>b.textContent==='Add snippet').click();true")
                until("document.getElementById('word-first') && !document.getElementById('word-first').disabled")
                window.evaluate_js("const trigger=document.getElementById('word-first');trigger.value='native signature';trigger.dispatchEvent(new Event('input',{bubbles:true}));const text=document.getElementById('word-second');text.value='  Native 👨‍👩‍👧‍👦 中文\\nSecond line ';text.dispatchEvent(new Event('input',{bubbles:true}));Array.from(document.querySelectorAll('button')).find(b=>b.textContent==='Save entry').click();true")
                until("document.querySelector('.note-status').textContent==='Saved on this computer.'")
                result['snippet']=window.evaluate_js("document.getElementById('word-second').value")
                window.evaluate_js("window.TalkDat.navigate('general');true")
                until("document.querySelector('main h1').textContent==='General'")
                window.evaluate_js("window.TalkDat.navigate('words');true")
                until("document.querySelector('.document-entry strong')?.textContent==='Native 美和'")
                window.evaluate_js("document.querySelector('.document-entry').click();true")
                until("document.getElementById('word-second').value==='native mee wa'")
                result['alias']=window.evaluate_js("document.getElementById('word-second').value")
                window.evaluate_js("window.TalkDat.navigate('translation');true")
                until("document.querySelector('[aria-label=\"Text to translate\"]') && !document.querySelector('[aria-label=\"Text to translate\"]').disabled")
                window.evaluate_js("const input=document.querySelector('[aria-label=\"Text to translate\"]');input.value='  Native translation 美和 👨‍👩‍👧‍👦\\n'.repeat(900);input.dispatchEvent(new Event('input',{bubbles:true}));true")
                until("Array.from(document.querySelectorAll('button')).some(b=>b.textContent==='Translate'&&!b.disabled)")
                window.evaluate_js("Array.from(document.querySelectorAll('button')).find(b=>b.textContent==='Translate').click();true")
                until("document.querySelector('[aria-label=\"Translation result\"]')?.value.startsWith('Translated:')")
                window.evaluate_js("Array.from(document.querySelectorAll('button')).find(b=>b.textContent==='Copy result').click();true")
                until("document.getElementById('notice').textContent.startsWith('Translation copied.')")
                window.evaluate_js("window.TalkDat.navigate('general');true")
                until("document.querySelector('main h1').textContent==='General'")
                window.evaluate_js("window.TalkDat.navigate('translation');true")
                until("document.querySelector('[aria-label=\"Text to translate\"]')?.value.startsWith('  Native translation')")
                result['translation_source']=window.evaluate_js("document.querySelector('[aria-label=\"Text to translate\"]').value")
                until("document.querySelector('[aria-label=\"Translation result\"]')?.value.startsWith('Translated:')")
                result['translation_result']=window.evaluate_js("document.querySelector('[aria-label=\"Translation result\"]').value")
                result['desktop']=name.value;evidence.send(result)
            except Exception as error:evidence.send({'error':str(error),'ui':window.evaluate_js("document.body.innerText.slice(-2500)")})
            finally:window.destroy()
        window.events.loaded+=probe
        return window
    webview.create_window=create
    _run_window(connection,html,'scratchpad',hidden=False)


@unittest.skipUnless(sys.platform=='win32','Native WebView2 document proof')
class NativeWorkspaceTests(unittest.TestCase):
    def test_native_note_save_reopen_and_copy_use_the_complete_words(self):
        assets=Path(__file__).resolve().parents[1]/'knight_flow/web_shell/shell_assets'
        copied=[]
        with tempfile.TemporaryDirectory() as directory:
            config=copy.deepcopy(DEFAULT_CONFIG)
            config['dictionary'].update(words=[],terms=[],replacements=[]);config['snippets']=[]
            saved_config=Path(directory)/'config.json'
            words=WordsWorkspace(config,lambda candidate:saved_config.write_text(json.dumps(candidate),encoding='utf-8'))
            notes=NotesWorkspace(Path(directory)/'notes.json',Path(directory)/'legacy.md',copied.append)
            tasks=[]
            translations=[]
            def translation_utility(action,value):
                if action=='translate':return {'text':'Translated:\n'+value['text'],'source_code':'en','target_code':'es','model':'fixture','chunks':1}
                if action=='check':return {'success':True,'status':{'ready':True,'model':value['options']['model']},'message':'Ready.'}
                if action=='copy':copied.append(value)
                if action=='accept':translations.append(value)
            translation=TranslationWorkspace(config,translation_utility,tasks.append)
            class Workspaces:
                def handle(self,payload):
                    service={'scratchpad':notes,'words':words,'translation':translation}.get(payload.get('area'))
                    if service is None:raise ValueError('Unexpected workspace')
                    return service.handle({k:v for k,v in payload.items() if k!='area'})
            backend=ShellBackend(config,assets,lambda _:None,lambda:None,
                object.__new__(Overlay)._settings_palette,workspaces=Workspaces())
            context=multiprocessing.get_context('spawn')
            parent,child=context.Pipe();receiver,sender=context.Pipe(duplex=False)
            process=context.Process(target=native_document_probe,args=(child,sender,bundled_html(assets)))
            process.start();child.close();sender.close()
            # Exercise the actual engine-side method allowlist and dispatcher too.
            controller=ShellController(assets,tasks.append,backend.handle,on_failure=lambda:None)
            controller.connection=parent
            listener=threading.Thread(target=controller._listen,args=(parent,),daemon=True)
            listener.start()
            try:
                deadline=time.monotonic()+65
                while time.monotonic()<deadline and not receiver.poll():
                    while tasks:tasks.pop(0)()
                    time.sleep(.01)
                self.assertTrue(receiver.poll(),'No native document result')
                result=receiver.recv();self.assertNotIn('error',result,result)
                text='Native Unicode 👨‍👩‍👧‍👦 中文 <literal>\n'*900
                self.assertEqual(result['text'],text)
                translation_source='  Native translation 美和 👨‍👩‍👧‍👦\n'*900
                self.assertEqual(result['translation_source'],translation_source)
                self.assertEqual(result['translation_result'],'Translated:\n'+translation_source)
                self.assertEqual(copied,[text,'Translated:\n'+translation_source])
                self.assertEqual(len(translations),1)
                self.assertEqual(notes.load()['tabs'][0]['text'],text)
                self.assertEqual(result['alias'],'native mee wa')
                self.assertEqual(result['snippet'],'  Native 👨‍👩‍👧‍👦 中文\nSecond line ')
                saved=json.loads(saved_config.read_text(encoding='utf-8'))
                self.assertEqual(saved['dictionary']['terms'][0],{'text':'Native 美和','sounds_like':['native mee wa']})
                self.assertEqual(saved['snippets'][0]['text'],result['snippet'])
                print('Native document, vocabulary and translation save/reopen passed on',result['desktop'])
            finally:
                process.join(5)
                if process.is_alive():process.terminate();process.join(5)
                listener.join(2);parent.close();receiver.close()

if __name__=='__main__':unittest.main()
