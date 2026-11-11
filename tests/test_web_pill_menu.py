"""Real Pill -> menu -> Settings handoff on an isolated Windows desktop."""
import copy
import ctypes
import math
from ctypes import wintypes
import multiprocessing
from pathlib import Path
import queue
import sys
import threading
import time
import tkinter as tk
import unittest
from unittest.mock import Mock
from knight_flow.config import DEFAULT_CONFIG
from knight_flow.overlay import Overlay
from knight_flow.web_shell.menu_geometry import pill_menu_bounds
from knight_flow.web_shell.shell_app import AppShell
from knight_flow.web_shell.shell_host import ShellController, _run_window, bundled_html


def probe_window(connection, html, page, hidden, mode, bounds):
    u=ctypes.windll.user32
    u.GetThreadDesktop.restype=wintypes.HANDLE
    name=ctypes.create_unicode_buffer(256);needed=wintypes.DWORD()
    desktop=u.GetThreadDesktop(ctypes.windll.kernel32.GetCurrentThreadId())
    assert u.GetUserObjectInformationW(desktop,2,name,ctypes.sizeof(name),ctypes.byref(needed)) and name.value.startswith('talkdat-tests-')
    import webview
    create=webview.create_window
    def instrument(*args,**kwargs):
        window=create(*args,**kwargs)
        if type(kwargs['js_api']).__name__=='_SubmenuApi':return window  # 0.4.178: the submenu window, not probed
        def probe():
            api=kwargs['js_api']
            def until(expression):
                deadline=time.monotonic()+20
                while time.monotonic()<deadline:
                    value=window.evaluate_js(expression)
                    if value:return value
                    time.sleep(.05)
                raise AssertionError(expression)
            try:
                until("document.body.classList.contains('connected')")
                if mode=='menu':
                    until("!!document.querySelector('[data-action=\"menu:settings\"]')")
                    # 0.4.177 IA phase 3: the window takes the width its widest row needs (from 288 to 360 px). It
                    # lands after the page has measured; then the main action's label is whole beside its shortcut.
                    until("(()=>{const s=document.querySelector('.menu-row-default .menu-label>span');return !!s&&s.scrollWidth<=s.clientWidth+0.5})()")
                    rect=wintypes.RECT();hwnd=wintypes.HWND(int(window.native.Handle.ToInt64()))
                    u.GetWindowRect(hwnd,ctypes.byref(rect))
                    report={'bounds':[rect.left,rect.top,rect.right-rect.left,rect.bottom-rect.top]}
                    # X-684: the real window carries the menu class's drop shadow.
                    private=ctypes.WinDLL('user32',use_last_error=True)
                    private.GetClassLongPtrW.argtypes=(wintypes.HWND,ctypes.c_int);private.GetClassLongPtrW.restype=ctypes.c_size_t
                    report['shadow']=bool(private.GetClassLongPtrW(hwnd,-26)&0x00020000)
                    report['main']=window.evaluate_js("(()=>{const r=document.querySelector('.menu-row-default');return {label:r.querySelector('.menu-label>span').textContent,value:r.querySelector('.menu-value')?.textContent||null,width:window.innerWidth}})()")
                    report['layout']=window.evaluate_js("({scroll:document.getElementById('page').scrollHeight,height:document.getElementById('page').clientHeight,rows:[...document.querySelectorAll('.menu-row:not([hidden])')].map(n=>({x:n.getBoundingClientRect().x,h:n.getBoundingClientRect().height})),mask:getComputedStyle(document.querySelector('.menu-row[data-action=\"menu:settings\"] .nav-icon')).maskMode})")
                    window.evaluate_js("document.querySelector('[data-action=\"menu:settings\"]').click();true")
                    # X-744: an error is read to screen readers from #alert (role=alert).
                    until("document.getElementById('alert').textContent==='Synthetic open failure'")
                    report['error_visible']=bool(u.IsWindowVisible(hwnd))
                    api.request('state',{'probe':'menu','report':report})
                    window.evaluate_js("document.querySelector('[data-action=\"menu:settings\"]').click();true")
                else:
                    until("!!document.querySelector('main h1')")
                    api.request('state',{'probe':'settings','report':{'visible':bool(u.IsWindowVisible(wintypes.HWND(int(window.native.Handle.ToInt64())))),'heading':window.evaluate_js("document.querySelector('main h1').textContent")}})
            except Exception as error:
                api.request('state',{'probe':mode,'report':{'error':str(error)}})
        window.events.loaded+=lambda:threading.Thread(target=probe,daemon=True).start()
        return window
    webview.create_window=instrument
    _run_window(connection,html,page,hidden,mode,bounds)


class ProbeController(ShellController):
    def open(self,page='general',*,hidden=False,bounds=None,side=None,**menu):  # 0.4.178: and what an open carries
        if self.process and self.process.is_alive():return super().open(page,hidden=hidden,bounds=bounds,**menu)
        ctx=multiprocessing.get_context('spawn');parent,child=ctx.Pipe()
        self.connection=parent
        self.process=ctx.Process(target=probe_window,args=(child,bundled_html(self.assets),page,hidden,self.mode,bounds),daemon=True)
        self.process.start();child.close()
        threading.Thread(target=self._listen,args=(parent,),daemon=True).start()


@unittest.skipUnless(sys.platform=='win32','Native Windows menu')
class PillMenuNativeTests(unittest.TestCase):
    def test_pill_anchor_error_and_settings_click_use_real_windows(self):
        from knight_flow.ui_scale import enable_dpi_awareness
        enable_dpi_awareness()
        root=tk.Tk();root.overrideredirect(True);root.geometry('200x48+500+850');root.update()
        overlay=Mock();overlay.root=root;overlay._settings_palette=object.__new__(Overlay)._settings_palette
        source=object.__new__(Overlay)
        rows=source._context_menu_default_rows()
        overlay._context_menu_rows.return_value=rows;overlay._context_menu_default_rows.return_value=rows
        overlay._context_menu_access_rows.return_value=source._context_menu_default_rows(include_feature_actions=True)
        overlay._context_menu_feature_rows.return_value=source._context_menu_feature_rows()
        overlay.MENU_SAFETY_ZONE_ACTIONS=Overlay.MENU_SAFETY_ZONE_ACTIONS
        overlay._logical_work_area.return_value=(0,0,1920,1080)
        overlay._foreground_target_window.return_value=0
        app=Mock();app.config=copy.deepcopy(DEFAULT_CONFIG);app.overlay=overlay;app._cross_thread_calls=queue.Queue()
        shell=AppShell(app,controller_factory=ProbeController)
        reports={};failed=False
        original=shell.backend.handle
        def handle(method,payload):
            nonlocal failed
            if payload.get('probe'):reports[payload['probe']]=payload['report']
            if method=='action' and payload.get('name')=='menu:settings' and not failed:
                failed=True;raise ValueError('Synthetic open failure')
            return original(method,payload)
        shell.menu_controller.handler=handle;shell.settings_controller.handler=handle
        try:
            self.assertTrue(shell.open_menu(17,19)) # Deliberately unrelated mouse position.
            deadline=time.monotonic()+55
            while time.monotonic()<deadline and len(reports)<2:
                root.update()
                try:app._cross_thread_calls.get(timeout=.02)()
                except queue.Empty:pass
            self.assertEqual(set(reports),{'menu','settings'},reports)
            for result in reports.values():self.assertNotIn('error',result,result)
            self.assertEqual(reports['menu']['bounds'],shell._menu_bounds)
            self.assertTrue(reports['menu']['error_visible'])
            self.assertTrue(reports['menu']['shadow'], 'the menu window casts no shadow')
            self.assertTrue(reports['settings']['visible'])
            self.assertEqual(reports['settings']['heading'],'Startup and updates')
            # 0.4.177 IA phase 3: with the default binding, the bold main action and Ctrl+Win+Space both show in full
            # in a real renderer, and the window widened past the old 288 px to fit them (never past 360).
            main=reports['menu']['main']
            self.assertEqual((main['label'],main['value']),('Start hands-free dictation','Ctrl+Win+Space'))
            self.assertGreater(shell._menu_width,288);self.assertLessEqual(shell._menu_width,360)
            self.assertLessEqual(abs(main['width']-shell._menu_width),1)
            layout=reports['menu']['layout']
            self.assertLessEqual(layout['scroll'],layout['height'])
            self.assertEqual(len({row['x'] for row in layout['rows']}),1)
            # 0.4.177: WinUI's own MenuFlyout row, read from its source (FLUENT-MENUS-SPEC.md B2): 20 px text padded
            # 4 and 5 when the menu is opened with a mouse, pen or keyboard, so 29 px (the 10-09 note's "Fluent's 40 px"
            # was not WinUI's number).
            self.assertGreaterEqual(min(row['h'] for row in layout['rows']),29)
            # The menu's icons come from the line-art ATLAS, which is a luminance
            # mask. This probed `.nav-icon` -- the first one in the document --
            # until X-172 put Home at the top of the rail with a mask of its own,
            # and the assertion started reading an icon the menu never shows.
            # Name the menu's icon, so it keeps protecting the atlas. 0.4.177 IA phase 2: the first row is Start
            # hands-free dictation, whose voice wave is a drawn (alpha) mask, so the probe names Settings' row.
            self.assertEqual(layout['mask'],'luminance')
            print('Native Pill menu and Settings:',reports)
        finally:
            shell.close();root.destroy()
            for controller in (shell.menu_controller,shell.settings_controller):
                if controller.process:
                    controller.process.join(4)
                    if controller.process.is_alive():controller.process.terminate();controller.process.join(3)


class PillAnchorGeometryTests(unittest.TestCase):
    def test_all_scales_center_above_the_pill_on_a_negative_monitor(self):
        for scale in (1,1.25,1.5,2):
            with self.subTest(scale=scale):
                pill=(-1300,1600,200,60)
                # 0.4.177 IA phase 3: the floor before the page has measured, then the width its widest row needs.
                for width in (None,344,360):
                    x,y,w,h=pill_menu_bounds(pill,(-2560,0,0,1800),scale,width=width)
                    self.assertLessEqual(abs(x+w/2-(pill[0]+pill[2]/2)),.5)
                    self.assertEqual(y+h,pill[1]-round(10*scale))
                    self.assertEqual(w,math.ceil((width or 288)*scale-1e-9))
    def test_top_edge_falls_below_without_crossing_work_area(self):
        x,y,w,h=pill_menu_bounds((700,10,200,50),(0,0,1920,1040),1.5)
        self.assertGreaterEqual(y,60)
        self.assertLessEqual(y+h,1040)

if __name__=='__main__':unittest.main()


