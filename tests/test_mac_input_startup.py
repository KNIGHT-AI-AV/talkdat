"""Resolve the shared PyObjC trust function before concurrent listeners start."""
import sys,threading,types,unittest
from unittest.mock import Mock,patch
from knight_flow import hotkeys,mac_support


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
        self.controller=Mock()
        self.modules=patch.dict(sys.modules,{'HIServices':self.framework})
        self.modules.start();self.addCleanup(self.modules.stop)

    def start(self,mac=True):
        def listener(**kwargs):
            def start():self.started.append('AXIsProcessTrusted' in vars(self.framework))
            return types.SimpleNamespace(start=start)
        with patch.object(mac_support,'IS_MAC',mac),patch.object(hotkeys.keyboard,'Listener',side_effect=listener),patch.object(hotkeys.mouse,'Listener',side_effect=listener),patch.object(hotkeys.threading,'Thread'):
            hotkeys.HotkeyController.start(self.controller)

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


if __name__=='__main__':unittest.main()
