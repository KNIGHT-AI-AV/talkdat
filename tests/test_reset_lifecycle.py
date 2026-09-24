import copy
import queue
import unittest
from unittest.mock import Mock,patch
from knight_flow.app import TalkDatApp
from knight_flow.overlay import Overlay
from tests import test_auxiliary_exit, test_web_shell_app

class ResetLifecycleTests(unittest.TestCase):
    def app(self):
        fixture=test_auxiliary_exit.AuxiliaryExitTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        fixture.app.wake_listener.closed.set()
        # The Mac Pill is a Toplevel; quitting destroys its separate Tk root.
        fixture.app.overlay._tk_root=Mock()
        return fixture.app

    def test_quit_cannot_interrupt_an_active_reset(self):
        app=self.app();app._reset_in_progress=True;app._reset_finished=False
        with patch("knight_flow.app.save_config") as save:app.quit(settings_confirmed=True)
        app.hotkeys.stop.assert_not_called();save.assert_not_called()
        app.overlay.root.after.assert_not_called()

    def test_restart_cannot_interrupt_an_active_reset(self):
        app=self.app();app._reset_in_progress=True;app._reset_finished=False
        with patch("subprocess.Popen") as launch,patch("os._exit") as leave:
            app.restart(settings_confirmed=True)
        launch.assert_not_called();leave.assert_not_called()

    def test_completed_reset_quits_without_rewriting_cleared_settings(self):
        app=self.app();app._reset_in_progress=app._reset_finished=True
        with patch("knight_flow.app.save_config") as save:app.quit(settings_confirmed=True)
        save.assert_not_called();app.remind_about_update.assert_not_called()
        app.hotkeys.stop.assert_called_once()
        self.assertEqual(app.overlay.root.after.call_args.args[0],0)

    def test_periodic_work_does_not_start_during_reset(self):
        app=self.app();app._reset_in_progress=True
        with patch("knight_flow.app.save_config") as save,patch("threading.Thread") as thread:
            app.save_settings();app._clipboard_learn_tick();app.check_updates()
            app.warm_selected_local_model();app.prefetch_selected_local_model()
        save.assert_not_called();thread.assert_not_called()

    def test_shared_backend_refuses_mutations_during_reset(self):
        app,shell=test_web_shell_app.AppShellTests().make_shell();app._reset_in_progress=True
        with self.assertRaisesRegex(ValueError,"reset is confirmed"):
            shell.backend.handle("action",{"name":"backup"})
        with self.assertRaisesRegex(ValueError,"reset is confirmed"):
            shell.backend.handle("save",{"revision":"fixture","changes":{}})
        shell._persist=Mock()

    def test_other_settings_destinations_return_to_reset_receipt(self):
        app,shell=test_web_shell_app.AppShellTests().make_shell();app._reset_in_progress=True
        shell.open_settings("appearance")
        self.assertEqual(shell.settings_controller.open.call_args.args[0],"reset")

    def test_legacy_failed_persistence_keeps_live_config(self):
        overlay=Overlay.__new__(Overlay);overlay.config={"dictionary":{"words":["keep"]}};overlay.callbacks={}
        before=copy.deepcopy(overlay.config)
        with patch("knight_flow.config.save_config",side_effect=OSError):
            with self.assertRaises(OSError):overlay._apply_pruned_config({},("dictionary",))
        self.assertEqual(overlay.config,before)

    def test_learning_timer_remains_scheduled_if_reset_later_fails(self):
        app=self.app();app._reset_in_progress=True
        app._clipboard_learn_tick()
        self.assertEqual(app.overlay.root.after.call_args.args[0],1100)

    def test_normal_quit_can_close_the_completed_reset_receipt(self):
        app,shell=test_web_shell_app.AppShellTests().make_shell();app._reset_finished=True
        self.assertFalse(shell.confirm_exit(lambda:None))
        shell.settings_controller.confirm_close.assert_not_called()

    def test_reset_refuses_new_global_shortcut_actions(self):
        from knight_flow.hotkeys import HotkeyController
        controller=HotkeyController.__new__(HotkeyController)
        controller.callbacks={"_actions_blocked":lambda:True,"translate":Mock()}
        controller._dispatch_queue=queue.SimpleQueue()
        controller._trigger("translate")
        self.assertTrue(controller._dispatch_queue.empty())

    def test_queued_shortcut_is_checked_again_before_running(self):
        from knight_flow.hotkeys import HotkeyController
        controller=HotkeyController.__new__(HotkeyController)
        callback=Mock();controller.callbacks={"_actions_blocked":lambda:True}
        controller._dispatch_queue=Mock()
        controller._dispatch_queue.get.side_effect=[("translate",callback),StopIteration]
        with self.assertRaises(StopIteration):controller._drain_dispatch()
        callback.assert_not_called()

if __name__=="__main__":unittest.main()
