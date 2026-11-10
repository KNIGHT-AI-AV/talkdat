"""Resolve the shared PyObjC trust function before concurrent listeners start."""
import contextlib,sys,threading,types,unittest
from unittest.mock import Mock,patch
from knight_flow import hotkeys,mac_support

# A shortcut on a mouse button as well as the keys, so start() hooks both. Since 0.4.176 H4 (3a238b1) the mouse
# hook starts only while a shortcut uses a mouse button, and start() reads the controller's own state to choose its
# hooks, so these tests start a real controller rather than calling start() on a Mock.
KEYS_AND_MOUSE={'push_to_talk':[['ctrl','cmd'],['mouse4']]}
KEYS_ONLY={'push_to_talk':[['ctrl','cmd']]}


class MacInputStartupTests(unittest.TestCase):
    def setUp(self):
        self.framework=types.ModuleType('HIServices')
        self.lookups=[]
        self.permission=Mock(return_value=False)
        def lookup(name):
            if name!='AXIsProcessTrusted':raise AttributeError(name)
            self.lookups.append(threading.get_ident())
            self.framework.AXIsProcessTrusted=self.permission
            return self.permission
        self.framework.__getattr__=lookup
        self.started=[]
        self.modules=patch.dict(sys.modules,{'HIServices':self.framework})
        self.modules.start();self.addCleanup(self.modules.stop)
        # On a Mac, start() hands pynput's real listener module a layout reader; put pynput's back.
        backend=sys.modules.get('pynput.keyboard._darwin')
        if backend is not None:self.addCleanup(setattr,backend,'keycode_context',backend.keycode_context)

    @contextlib.contextmanager
    def patched(self,mac=True):
        def listener(**kwargs):
            def start():self.started.append('AXIsProcessTrusted' in vars(self.framework))
            return types.SimpleNamespace(start=start,stop=lambda:None)
        with patch.object(mac_support,'IS_MAC',mac),patch.object(hotkeys.keyboard,'Listener',side_effect=listener),patch.object(hotkeys.mouse,'Listener',side_effect=listener),patch.object(hotkeys.threading,'Thread'),patch.object(hotkeys.HotkeyController,'_start_gamepad_poller',lambda self:None),patch.object(hotkeys.HotkeyController,'_start_midi_listener',lambda self:None):
            yield

    def start(self,mac=True,layout=KEYS_AND_MOUSE):
        controller=hotkeys.HotkeyController(layout,{})
        with self.patched(mac):
            controller.start()
        return controller

    def test_first_resolution_precedes_both_listener_threads(self):
        self.start()
        self.assertEqual(self.started,[True,True])
        self.assertEqual(self.lookups,[threading.get_ident()])
        self.permission.assert_not_called()

    def test_repeated_start_reuses_resolved_bridge(self):
        self.start();self.start()
        self.assertEqual(self.started,[True]*4)
        self.assertEqual(len(self.lookups),1)
        self.permission.assert_not_called()

    def test_other_platforms_do_not_load_apple_bridge(self):
        self.start(mac=False)
        self.assertEqual(self.lookups,[])
        self.assertEqual(self.started,[False,False])

    def test_a_mouse_hook_that_starts_later_finds_the_bridge_resolved(self):
        # The default shortcuts use no mouse button: start() hooks only the keys. A mouse shortcut saved later
        # starts the mouse hook then, off the startup path, and the startup thread's resolution already covers it.
        controller=self.start(layout=KEYS_ONLY)
        self.assertEqual(self.started,[True])
        with self.patched():
            controller.update_config(KEYS_AND_MOUSE)
        self.assertEqual(self.started,[True,True])
        self.assertEqual(self.lookups,[threading.get_ident()])
        self.permission.assert_not_called()


if __name__=='__main__':unittest.main()
