from types import SimpleNamespace
import unittest
from knight_flow.web_shell.history_workspace import HistoryWorkspace

class HistoryRowDateTests(unittest.TestCase):
    def listing(self,dates):
        rows=[{'text':f'Keep row {i}','created_at':date} for i,date in enumerate(dates)]
        service=HistoryWorkspace(SimpleNamespace(recent=lambda _:rows),lambda:[],lambda _:None,lambda _:None,lambda _:None)
        return service.handle({'operation':'list','query':'','offset':0,'pinned':False})['entries']
    def test_unrepresentable_dates_are_null_in_the_reader_protocol(self):
        rows=self.listing([float('nan'),float('inf'),1e300,True,None,'invalid'])
        self.assertEqual(len(rows),6);self.assertTrue(all(row['created_at'] is None for row in rows))
    def test_extremely_large_saved_number_does_not_hide_other_entries(self):
        rows=self.listing([10**1000,1700000000])
        self.assertEqual(len(rows),2);self.assertEqual(rows[0]['created_at'],1700000000)
        self.assertIsNone(rows[1]['created_at'])
    def test_a_real_epoch_timestamp_is_not_an_unknown_date(self):
        self.assertEqual(self.listing([0])[0]['created_at'],0)

if __name__=='__main__':unittest.main()
