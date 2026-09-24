from pathlib import Path
import copy
import importlib.util
import json
import queue
import threading
import time
import unittest
from unittest.mock import patch

from knight_flow.web_shell import stats_workspace as module
StatsWorkspace=module.StatsWorkspace


class ActivityWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.queue=queue.Queue()
        self.threads=[]
        self.config={'privacy':{'save_history':False},'api_key':'private-fixture'}
        self.block=threading.Event();self.block.set()
        self.entered=threading.Event()
        self.fail=False
        self.seen=[]
        def loader(config):
            self.threads.append(threading.get_ident());self.seen.append(config)
            self.entered.set();self.block.wait(2)
            if self.fail:raise OSError('fixture read failure')
            return {'total':12}
        self.service=StatsWorkspace(self.config,self.queue.put,loader)
    def tearDown(self):
        self.block.set();self.service.close()
    def settle(self):
        deadline=time.monotonic()+2
        while self.queue.empty() and time.monotonic()<deadline:time.sleep(.002)
        self.assertFalse(self.queue.empty())
        while not self.queue.empty():self.queue.get_nowait()()
        return self.service.handle({'operation':'status'})
    def test_history_reads_happen_off_the_ui_thread(self):
        self.assertEqual(self.service.handle({'operation':'refresh'})['phase'],'loading')
        self.assertEqual(self.settle()['data'],{'total':12})
        self.assertNotIn(threading.get_ident(),self.threads)
    def test_repeated_refresh_deduplicates_inflight_work(self):
        self.block.clear()
        self.service.handle({'operation':'refresh'});self.assertTrue(self.entered.wait(1))
        for _ in range(20):self.service.handle({'operation':'refresh'})
        self.assertEqual(len(self.threads),1)
        self.block.set();self.settle()
    def test_refresh_takes_a_config_snapshot(self):
        self.block.clear();self.service.handle({'operation':'refresh'})
        self.assertTrue(self.entered.wait(1))
        self.config['privacy']['save_history']=True
        self.assertFalse(self.seen[0]['privacy']['save_history'])
    def test_refresh_failure_keeps_the_last_successful_snapshot(self):
        self.service.handle({'operation':'refresh'});self.settle()
        self.fail=True;self.service.handle({'operation':'refresh'})
        result=self.settle();self.assertEqual(result['phase'],'error')
        self.assertEqual(result['data'],{'total':12})
        self.assertNotIn('fixture read failure',result['message'])
    def test_responses_cannot_mutate_the_cached_snapshot(self):
        self.service.handle({'operation':'refresh'});result=self.settle()
        result['data']['total']=999
        self.assertEqual(self.service.handle({'operation':'status'})['data']['total'],12)
    def test_only_explicit_read_operations_are_accepted(self):
        for payload in (None,[],{}, {'operation':'clear'}, {'operation':'refresh','config':{}}, {'operation':42}):
            with self.subTest(payload=payload),self.assertRaises(ValueError):self.service.handle(payload)
    def test_close_rejects_late_completion(self):
        self.block.clear();self.service.handle({'operation':'refresh'})
        self.assertTrue(self.entered.wait(1));self.service.close();self.block.set()
        deadline=time.monotonic()+2
        while self.queue.empty() and time.monotonic()<deadline:time.sleep(.002)
        self.assertFalse(self.queue.empty());self.queue.get_nowait()()
        self.assertIsNone(self.service.data)
    def test_the_builtin_loader_returns_counts_without_raw_text_or_credentials(self):
        counts={'dictated_words':15,'active_days':2,'by_type':{'dictation':1,'secret text type':2}}
        with patch('knight_flow.history.history_stats',return_value=counts):
            result=module.load_statistics(self.config)
        encoded=json.dumps(result)
        self.assertNotIn('private-fixture',encoded)
        self.assertNotIn('secret text type',encoded)
        self.assertFalse(result['history_enabled'])
        self.assertIn({'label':'Other','entries':2},result['activity']['by_type'])


if __name__=='__main__':unittest.main()
