"""Activity refresh and failure recovery across the real native renderer pipe."""
import copy
import ctypes
import multiprocessing
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace
import unittest

from knight_flow.config import DEFAULT_CONFIG
from knight_flow.overlay import Overlay
from knight_flow.web_shell.stats_workspace import StatsWorkspace
from knight_flow.web_shell.shell_backend import ShellBackend
from knight_flow.web_shell.shell_host import ShellController, _run_window, bundled_html


def native_stats_probe(connection,evidence,html):
    if sys.platform=='win32':
        from ctypes import wintypes
        user=ctypes.windll.user32
        user.GetThreadDesktop.restype=wintypes.HANDLE
        desktop=user.GetThreadDesktop(ctypes.windll.kernel32.GetCurrentThreadId())
        name=ctypes.create_unicode_buffer(256);required=wintypes.DWORD()
        if not user.GetUserObjectInformationW(desktop,2,name,ctypes.sizeof(name),ctypes.byref(required)) or not name.value.startswith('talkdat-tests-'):
            evidence.send({'error':'Native Stats proof requires the isolated desktop'});return
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
                raise AssertionError('Native Stats did not settle: '+script[:100])
            def refresh():
                window.evaluate_js("document.querySelector('[data-workspace=stats] button').click();true")
            try:
                until("document.body.classList.contains('connected')")
                window.evaluate_js("window.TalkDat.navigate('stats');true")
                until("document.querySelector('.activity-metric strong')?.textContent==='3,703'")
                refresh()
                until("document.querySelector('.activity-status')?.textContent.includes('could not load')")
                retained=window.evaluate_js("document.querySelector('.activity-metric strong').textContent")
                refresh()
                until("document.querySelector('.activity-metric strong')?.textContent==='0'")
                window.evaluate_js("window.TalkDat.navigate('general');true")
                until("document.querySelector('main h1')?.textContent==='General'")
                window.evaluate_js("window.TalkDat.navigate('stats');true")
                until("document.querySelector('.activity-metric strong')?.textContent==='3,703'")
                window.evaluate_js("document.querySelector('.activity-estimates summary').click();true")
                evidence.send({'retained':retained,'final':window.evaluate_js("document.querySelector('.activity-metric strong').textContent"),
                    'days':window.evaluate_js("document.querySelectorAll('.activity-week li').length"),
                    # innerText needs a real layout pass, which a hidden/
                    # off-screen WKWebView on macOS never runs; textContent
                    # reads the DOM directly and does not depend on one.
                    'estimate':window.evaluate_js("document.querySelector('.activity-estimates').textContent.includes('not a bill')"),
                    'targets':window.evaluate_js("Array.from(document.querySelectorAll('[data-workspace=stats] button')).every(b=>b.getBoundingClientRect().height>=44)"),
                    'desktop':surface})
            except Exception as error:evidence.send({'error':str(error),'ui':window.evaluate_js('document.body.innerText.slice(-2000)')})
            finally:window.destroy()
        window.events.loaded+=probe
        return window
    webview.create_window=create_probe
    _run_window(connection,html,'stats',hidden=sys.platform=='darwin')


@unittest.skipUnless(sys.platform in {'win32','darwin'},'Native desktop Stats acceptance')
class NativeStatsTests(unittest.TestCase):
    def test_refresh_failure_empty_and_reopen_through_the_real_pipe(self):
        assets=Path(__file__).resolve().parents[1]/'knight_flow/web_shell/shell_assets'
        config=copy.deepcopy(DEFAULT_CONFIG);tasks=[];threads=[];calls=[]
        sample={'activity':{'entries':37,'words':3703,'dictations':36,'dictated_words':3503,'today':7,
            'active_days':7,'dictation_active_days':7,'streak_days':7,'minutes_saved':64,'capped':False,
            'unknown_dates':1,'limit':20000,'by_type':[{'label':'Dictation','entries':36},{'label':'Translation','entries':1}],
            'daily':[{'date':f'2026-09-{day:02}','entries':day-13,'dictated_words':100} for day in range(14,21)]},
            'speech':{'provider_label':'On this computer','model':'parakeet','model_label':'Parakeet',
                      'is_cloud':False,'total_minutes':23.4,'minutes_per_active_day':3.34,'estimated_monthly_cost':0},
            'history_enabled':False}
        def loader(_config):
            threads.append(threading.get_ident());calls.append(True)
            if len(calls)==2:raise OSError('Injected read failure')
            result=copy.deepcopy(sample)
            if len(calls)==3:
                result['activity'].update(entries=0,words=0,dictations=0,dictated_words=0,today=0,active_days=0,
                    dictation_active_days=0,streak_days=0,minutes_saved=0,unknown_dates=0,by_type=[])
                for row in result['activity']['daily']:row.update(entries=0,dictated_words=0)
                result['speech'].update(total_minutes=0,minutes_per_active_day=0)
            return result
        service=StatsWorkspace(config,tasks.append,loader)
        backend=ShellBackend(config,assets,lambda _:None,lambda:None,object.__new__(Overlay)._settings_palette,
            workspaces=SimpleNamespace(handle=lambda payload:service.handle({key:value for key,value in payload.items() if key!='area'})))
        context=multiprocessing.get_context('spawn')
        parent,child=context.Pipe();receiver,sender=context.Pipe(duplex=False)
        process=context.Process(target=native_stats_probe,args=(child,sender,bundled_html(assets)))
        process.start();child.close();sender.close()
        controller=ShellController(assets,tasks.append,backend.handle,on_failure=lambda:None)
        controller.connection=parent
        listener=threading.Thread(target=controller._listen,args=(parent,),daemon=True);listener.start()
        try:
            deadline=time.monotonic()+90
            while time.monotonic()<deadline and not receiver.poll():
                while tasks:tasks.pop(0)()
                time.sleep(.01)
            self.assertTrue(receiver.poll(),'No native Stats result')
            result=receiver.recv();self.assertNotIn('error',result,result)
            self.assertEqual(result['retained'],'3,703');self.assertEqual(result['final'],'3,703')
            self.assertEqual(result['days'],7);self.assertTrue(result['estimate']);self.assertTrue(result['targets'])
            self.assertEqual(len(calls),4)
            self.assertTrue(all(identifier!=threading.get_ident() for identifier in threads))
            print('Native Stats refresh, failure retention, empty history and reopen passed on',result['desktop'])
        finally:
            service.close();process.join(5)
            if process.is_alive():process.terminate();process.join(5)
            listener.join(2);parent.close();receiver.close()


if __name__=='__main__':unittest.main()
