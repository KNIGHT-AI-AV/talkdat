import os, tempfile, time, unittest
from unittest.mock import patch
from knight_flow import plugins, text_pipeline


class PluginReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        self.env = patch.dict(os.environ, {"TALK_DAT_HOME": self.home.name})
        self.env.start()
        self.addCleanup(self.env.stop)
        plugins.reload_plugins()
        self.addCleanup(plugins.reload_plugins)
        self.config = {"plugins": {"enabled": True}, "formatting": {"engine": "rules"}}

    def install(self, body, name="check.py"):
        (plugins.plugins_dir() / name).write_text(body, encoding="utf-8")

    def filtered(self, text="Keep every word."):
        return text_pipeline.complete_prepared_dictation(
            text_pipeline.ProcessedText(text, text), self.config
        ).text

    def test_none_filter_keeps_the_original_words(self):
        self.install(
            "def register(api):\n    api.add_text_filter(lambda text,config:None)\n"
        )
        self.assertEqual(self.filtered(), "Keep every word.")

    def test_blank_filter_cannot_erase_dictation(self):
        self.install(
            "def register(api):\n    api.add_text_filter(lambda text,config:'  ')\n"
        )
        self.assertEqual(self.filtered(), "Keep every word.")

    def test_non_string_transform_is_not_pasted(self):
        self.install(
            "def register(api):\n    api.add_transform('check',lambda text,config: {'unexpected':'object'})\n"
        )
        self.assertIsNone(plugins.plugin_transform("check", "Hello", self.config))

    def test_failed_registration_does_not_leave_half_a_plugin_active(self):
        self.install(
            "def register(api):\n    api.add_text_filter(lambda text,config:'CORRUPTED')\n    raise RuntimeError('partial registration')\n"
        )
        self.assertEqual(self.filtered(), "Keep every word.")

    def test_plugin_config_edits_do_not_change_the_application(self):
        self.install(
            "def mutate(text,config):\n    config['plugins']['enabled']=False\n    return text\ndef register(api):api.add_text_filter(mutate)\n"
        )
        self.filtered()
        self.assertIs(self.config["plugins"]["enabled"], True)

    def test_enable_requires_an_explicit_boolean(self):
        for enabled in ("false", "true", 1, [], None):
            self.assertFalse(plugins.plugins_enabled({"plugins": {"enabled": enabled}}))

    def test_successful_transform_preserves_whitespace(self):
        self.install(
            "def register(api):api.add_transform('check',lambda text,config:'  '+text+'\\n')\n"
        )
        self.assertEqual(
            plugins.plugin_transform("check", "Hello", self.config), "  Hello\n"
        )

    def test_reload_uses_current_source_even_with_same_size_and_timestamp(self):
        self.install(
            "def register(api):api.add_transform('check',lambda text,config:'first')\n"
        )
        p = plugins.plugins_dir() / "check.py"
        st = p.stat()
        self.assertEqual(plugins.plugin_transform("check", "Hi", self.config), "first")
        p.write_text(p.read_text().replace("first", "other"), encoding="utf-8")
        os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns))
        plugins.reload_plugins()
        self.assertEqual(plugins.plugin_transform("check", "Hi", self.config), "other")

    def test_slow_filter_keeps_words_with_a_bounded_delay(self):
        self.install(
            "import time\ndef slow(text,config):time.sleep(2);return 'late'\ndef register(api):api.add_text_filter(slow)\n"
        )
        filters = plugins.plugin_text_filters(self.config)
        started = time.perf_counter()
        result = filters[0]("Keep every word.", self.config)
        elapsed = time.perf_counter() - started
        self.assertEqual(result, "Keep every word.")
        self.assertLess(elapsed, 0.9)

    def test_crashing_host_cannot_exit_dictation_or_disable_a_healthy_plugin(self):
        self.install(
            "import os\ndef bad(t,c):os._exit(29)\ndef register(api):api.add_text_filter(bad)\n",
            "a_crash.py",
        )
        self.install(
            "def register(api):api.add_text_filter(lambda t,c:t+' Safe.')\n",
            "b_good.py",
        )
        self.assertEqual(self.filtered(), "Keep every word. Safe.")
        self.assertIn("HostClosed", " ".join(plugins.load_errors()))

    def test_system_exit_during_registration_is_contained(self):
        self.install("raise SystemExit(9)\n", "a_exit.py")
        self.install(
            "def register(api):api.add_transform('check',lambda t,c:t+'!')\n",
            "b_good.py",
        )
        self.assertEqual(plugins.plugin_transform("check", "Hi", self.config), "Hi!")

    def test_print_output_does_not_enter_the_protocol_or_dictation(self):
        self.install(
            "print('noise')\ndef noisy(t,c):\n    print('more noise')\n    return t+'!'\ndef register(api):api.add_text_filter(noisy)\n"
        )
        self.assertEqual(self.filtered(), "Keep every word.!")

    def test_huge_output_preserves_input(self):
        self.install("def register(api):api.add_text_filter(lambda t,c:'x'*200001)\n")
        self.assertEqual(self.filtered(), "Keep every word.")

    def test_import_stall_is_bounded(self):
        self.install("import time\ntime.sleep(20)\n")
        started = time.perf_counter()
        self.assertEqual(self.filtered(), "Keep every word.")
        self.assertLess(time.perf_counter() - started, 1.6)
        self.assertIn("TimeoutError", " ".join(plugins.load_errors()))

    def test_errors_do_not_retain_private_text(self):
        self.install(
            "def bad(t,c):raise ValueError(t)\ndef register(api):api.add_text_filter(bad)\n"
        )
        self.assertEqual(self.filtered("private fixture text"), "private fixture text")
        self.assertNotIn("private fixture text", " ".join(plugins.load_errors()))
        self.assertIn("ValueError", " ".join(plugins.load_errors()))

    def test_reload_reaps_its_host_processes(self):
        self.install("def register(api):api.add_transform('check',lambda t,c:t)\n")
        plugins.plugin_transform("check", "Hello", self.config)
        import multiprocessing

        processes = [host.process.pid for host in plugins._hosts]
        self.assertTrue(processes)
        plugins.reload_plugins()
        active = {process.pid for process in multiprocessing.active_children()}
        self.assertTrue(all(pid not in active for pid in processes))

    def test_filter_chain_has_one_total_runtime_budget(self):
        for n in range(4):
            self.install(
                "import time\ndef slow(t,c):time.sleep(.3);return t+'!'\ndef register(api):api.add_text_filter(slow)\n",
                f"{n}.py",
            )
        filters = plugins.plugin_text_filters(self.config)
        started = time.perf_counter()
        text = "Original"
        for callback in filters:
            text = callback(text, self.config)
        self.assertLess(time.perf_counter() - started, 0.9)
        self.assertEqual(text, "Original!")

    def test_timed_out_reply_is_never_used_for_later_text(self):
        self.install(
            "import time\ndef slow(t,c):time.sleep(2);return 'STALE'\ndef register(api):api.add_text_filter(slow)\n"
        )
        self.assertEqual(self.filtered("First"), "First")
        self.assertEqual(self.filtered("Second"), "Second")

    def test_plugin_output_still_respects_the_house_punctuation_rule(self):
        self.install(
            "def register(api):api.add_transform('check',lambda t,c:'Hello\\u2014world')\n"
        )
        self.assertNotIn(
            "\u2014", plugins.plugin_transform("check", "Hello", self.config)
        )

    def test_child_with_inherited_pipe_cannot_hold_the_parent_close(self):
        self.install(
            "import os,subprocess,sys,time\ndef slow(t,c):\n    flags={'creationflags':0x08000000} if os.name=='nt' else {}\n    subprocess.Popen([sys.executable,'-c','import time;time.sleep(2)'],stdout=sys.__stdout__,stderr=subprocess.DEVNULL,**flags)\n    time.sleep(20)\ndef register(api):api.add_text_filter(slow)\n"
        )
        filters = plugins.plugin_text_filters(self.config)
        started = time.perf_counter()
        text = filters[0]("Original", self.config)
        self.assertEqual(text, "Original")
        self.assertLess(time.perf_counter() - started, 0.9)

    def test_unavailable_plugin_folder_cannot_break_dictation(self):
        with patch('knight_flow.plugins.plugins_dir',side_effect=PermissionError('fixture denied')):
            self.assertEqual(self.filtered(),'Keep every word.')
            self.assertIsNone(plugins.plugin_transform('check','Hello',self.config))
        self.assertIn('PermissionError',' '.join(plugins.load_errors()))

    def test_returned_filter_chain_can_be_used_for_another_take(self):
        self.install("def register(api):api.add_text_filter(lambda t,c:t+'!')\n")
        filters=plugins.plugin_text_filters(self.config)
        self.assertEqual(filters[0]('First',self.config),'First!')
        time.sleep(.55)
        self.assertEqual(filters[0]('Second',self.config),'Second!')

    def test_excess_registration_is_rejected_as_a_whole(self):
        self.install("def register(api):\n    for _ in range(129):api.add_text_filter(lambda t,c:t+'!')\n")
        self.assertEqual(self.filtered(),'Keep every word.')
        self.assertTrue(plugins.load_errors())
