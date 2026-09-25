"""X-744: an answer on a pressed control never moves the page, in the real renderer.

The owner's rule: a message is the part itself changing shape, and it goes where
there is room: "never moving the page". Measured in WebView2 on a hidden desktop
(through scripts/run_tests_offscreen.py), on the Tools page:

* a face stretch (a long answer on a Tools button): every element outside the
  button keeps its exact box, the button keeps its own box, the stretched face is
  a child of the button, lies inside the button's row, overlaps no other control
  and stops short of the row's description, and the joined corner is square
  while the far end keeps the button's radius;
* a label roll (a short answer): the button's box does not change either;
* a request error with Retry: the same, and the button still says what it is.
"""
from __future__ import annotations

import copy
import ctypes
import json
import multiprocessing
import queue
import sys
import threading
import time
import tkinter as tk
import unittest
from ctypes import wintypes
from unittest.mock import Mock

from knight_flow.config import DEFAULT_CONFIG
from knight_flow.overlay import Overlay
from knight_flow.web_shell.shell_app import AppShell
from knight_flow.web_shell.shell_host import ShellController, _run_window, bundled_html

PROBE_JS = r"""(()=>{window.__answers=null;(async()=>{try{
const wait=ms=>new Promise(done=>setTimeout(done,ms));
await window.TalkDat.navigate("tools");await wait(400);
const rows=[...document.querySelectorAll('.tool-row')];
const words=row=>row.querySelector('p').textContent.length;
rows.sort((a,b)=>words(a)-words(b));
const box=node=>{const r=node.getBoundingClientRect();return [r.x,r.y,r.width,r.height].map(v=>Math.round(v*10)/10).join(',');};
const ink=node=>{const range=document.createRange();range.selectNodeContents(node);return range.getBoundingClientRect();};
async function measure(button,say){
  // A person presses what they can see: the row is brought into view first.
  button.closest('.tool-row').scrollIntoView({block:"center"});await wait(300);
  // Every element but this button, the live regions and other buttons' own
  // answer parts (an earlier answer folding away belongs to its own button).
  const others=[...document.querySelectorAll('body *')].filter(node=>node!==button&&!button.contains(node)&&!node.closest('#notice,#alert,.say-ext,.say-roll'));
  const before=new Map(others.map(node=>[node,box(node)]));const host=box(button);
  say(button);await wait(700);
  const moved=[];for(const [node,was] of before){const now=box(node);if(now!==was)moved.push(node.tagName+'.'+node.className+' '+was+' -> '+now);}
  const ext=button.querySelector('.say-ext');const row=button.closest('.tool-row');
  let e=null,overlaps=0,descRight=ink(row.querySelector('p')).right;
  if(ext){const r=ext.getBoundingClientRect();e={left:r.left,right:r.right,top:r.top,bottom:r.bottom,parent:ext.parentNode===button,
    joined:getComputedStyle(button).borderTopLeftRadius,outer:getComputedStyle(ext).borderTopLeftRadius,edge:getComputedStyle(button).borderLeftColor,clip:getComputedStyle(ext).clipPath};
    for(const other of row.querySelectorAll('button,a,input,select,textarea,[tabindex]')){if(other===button||button.contains(other))continue;const o=other.getBoundingClientRect();
      if(o.width&&!(o.right<=r.left||o.left>=r.right||o.bottom<=r.top||o.top>=r.bottom))overlaps++;}}
  const rb=row.getBoundingClientRect();
  return {moved:moved.slice(0,8),movedCount:moved.length,hostBefore:host,hostAfter:box(button),ext:e,overlaps,descRight,
    row:{left:rb.left,right:rb.right,top:rb.top,bottom:rb.bottom},radius:getComputedStyle(button).borderTopRightRadius,
    label:button.getAttribute('aria-label'),classes:button.className};
}
const report={};
report.stretch=await measure(rows[0].querySelector('button'),button=>window.TalkDat.flag(button,"Hearing you clearly on this microphone",{tone:"done"}));
report.roll=await measure(rows[1].querySelector('button'),button=>window.TalkDat.flag(button,"Done",{tone:"info"}));
report.retry=await measure(rows[2].querySelector('button'),button=>window.TalkDat.flag(button,"Could not reach the release server.",{tone:"error",actions:[{label:"Retry",run:()=>{}}]}));
window.__answers=JSON.stringify(report);}catch(error){window.__answers=JSON.stringify({error:String(error&&error.stack||error)});}})();return true;})()"""


def probe_window(connection, html, page, hidden, mode, bounds):
    user32 = ctypes.windll.user32
    user32.GetThreadDesktop.restype = wintypes.HANDLE
    name = ctypes.create_unicode_buffer(256)
    needed = wintypes.DWORD()
    desktop = user32.GetThreadDesktop(ctypes.windll.kernel32.GetCurrentThreadId())
    assert user32.GetUserObjectInformationW(desktop, 2, name, ctypes.sizeof(name), ctypes.byref(needed))
    assert name.value.startswith("talkdat-tests-"), "run through scripts/run_tests_offscreen.py"
    import webview

    create = webview.create_window

    def instrument(*args, **kwargs):
        window = create(*args, **kwargs)

        def probe():
            api = kwargs["js_api"]

            def until(expression, timeout=30):
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    value = window.evaluate_js(expression)
                    if value:
                        return value
                    time.sleep(0.1)
                raise AssertionError(expression)

            try:
                until("document.querySelectorAll('#navigation button').length>0")
                window.evaluate_js(PROBE_JS)
                report = json.loads(until("window.__answers"))
                api.request("state", {"probe": "answers", "report": report})
            except Exception as error:  # noqa: BLE001
                api.request("state", {"probe": "answers", "report": {"error": str(error)}})

        window.events.loaded += lambda: threading.Thread(target=probe, daemon=True).start()
        return window

    webview.create_window = instrument
    _run_window(connection, html, page, hidden, mode, bounds)


class ProbeController(ShellController):
    def open(self, page="general", *, hidden=False, bounds=None):
        if self.process and self.process.is_alive():
            return super().open(page, hidden=hidden, bounds=bounds)
        context = multiprocessing.get_context("spawn")
        parent, child = context.Pipe()
        self.connection = parent
        self.process = context.Process(
            target=probe_window,
            args=(child, bundled_html(self.assets), page, hidden, self.mode, bounds),
            daemon=True,
        )
        self.process.start()
        child.close()
        threading.Thread(target=self._listen, args=(parent,), daemon=True).start()


@unittest.skipUnless(sys.platform == "win32", "WebView2 renderer")
class AnswersNeverMoveThePageTests(unittest.TestCase):
    def test_a_stretch_a_roll_and_a_retry_move_nothing(self) -> None:
        from knight_flow.ui_scale import enable_dpi_awareness

        enable_dpi_awareness()
        root = tk.Tk()
        root.withdraw()
        overlay = Mock()
        overlay.root = root
        overlay._settings_palette = object.__new__(Overlay)._settings_palette
        source = object.__new__(Overlay)
        rows = source._context_menu_default_rows()
        overlay._context_menu_rows.return_value = rows
        overlay._context_menu_default_rows.return_value = rows
        overlay._context_menu_access_rows.return_value = source._context_menu_default_rows(include_feature_actions=True)
        overlay._context_menu_feature_rows.return_value = source._context_menu_feature_rows()
        overlay.MENU_SAFETY_ZONE_ACTIONS = Overlay.MENU_SAFETY_ZONE_ACTIONS
        app = Mock()
        app.config = copy.deepcopy(DEFAULT_CONFIG)
        app.overlay = overlay
        app._cross_thread_calls = queue.Queue()
        shell = AppShell(app, controller_factory=ProbeController)
        reports: dict = {}
        original = shell.backend.handle

        def handle(method, payload):
            if payload.get("probe"):
                reports[payload["probe"]] = payload["report"]
            return original(method, payload)

        shell.settings_controller.handler = handle
        try:
            self.assertTrue(shell.open_settings("home"))
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline and "answers" not in reports:
                root.update()
                try:
                    app._cross_thread_calls.get(timeout=0.02)()
                except queue.Empty:
                    pass
            report = reports.get("answers")
            self.assertIsNotNone(report, "the page never reported")
            self.assertNotIn("error", report, report)
            for name in ("stretch", "roll", "retry"):
                with self.subTest(answer=name):
                    case = report[name]
                    self.assertEqual(case["movedCount"], 0, f"the page moved: {case['moved']}")
                    self.assertEqual(case["hostBefore"], case["hostAfter"], "the pressed button changed size")
            stretch = report["stretch"]
            ext = stretch["ext"]
            self.assertIsNotNone(ext, f"no room was found for the stretch: {stretch}")
            self.assertTrue(ext["parent"], "the stretched face is not a child of its button")
            self.assertEqual(stretch["overlaps"], 0, "the stretched face covers another control")
            self.assertGreaterEqual(ext["left"], stretch["descRight"], "the stretched face covers the row's words")
            self.assertGreaterEqual(ext["left"], stretch["row"]["left"])
            self.assertLessEqual(ext["top"], ext["bottom"])
            self.assertEqual(ext["joined"], "0px", "the joined corner is not square")
            # Where the face grows its old edge disappears, and the face's own shadow
            # stops at the join: no seam between the two.
            self.assertEqual(ext["edge"], "rgba(0, 0, 0, 0)", "the button kept its old edge at the join")
            self.assertIn("inset(-8px 0px -8px -8px)", ext["clip"], "the face's shadow spills onto the button")
            self.assertNotEqual(ext["outer"], "0px", "the far end lost the button's radius")
            self.assertIsNone(report["roll"]["ext"], "a short answer stretched the face")
            self.assertTrue(report["retry"]["label"].endswith(": Retry"), "the button lost its own name")
            self.assertIn("say-error", report["retry"]["classes"])
        finally:
            shell.close()
            root.destroy()
            controller = shell.settings_controller
            if controller.process:
                controller.process.join(4)
                if controller.process.is_alive():
                    controller.process.terminate()
                    controller.process.join(3)


if __name__ == "__main__":
    unittest.main()
