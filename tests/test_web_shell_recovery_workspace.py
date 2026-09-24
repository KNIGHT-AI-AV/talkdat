import unittest
from knight_flow.web_shell.recovery_workspace import RecoveryWorkspace

class RecoveryWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.rows=[{'session_id':'private-id','audio_path':'private/path.wav','metadata_path':'secret/path',
            'has_audio':True,'duration_ms':1000,'created_at':1,'final_text':'all the words '+('👩🏿‍💻'*1000)}]
        self.recovered=[];self.played=[];self.copied=[]
        self.service=RecoveryWorkspace(lambda:self.rows,self.recovered.append,self.played.append,self.copied.append)
    def test_list_never_exposes_paths_or_full_transcripts(self):
        row=self.service.handle({'operation':'list'})['sessions'][0]
        self.assertNotIn('audio_path',row);self.assertNotIn('session_id',row)
        self.assertEqual(len(row['preview']),240)
    def test_copy_and_recovery_use_current_engine_owned_row(self):
        row=self.service.handle({'operation':'list'})['sessions'][0]
        for operation in ('copy','recover','play'):self.service.handle({'operation':operation,'id':row['id']})
        self.assertEqual(self.recovered,['private-id']);self.assertEqual(self.copied,[self.rows[0]['final_text']])
        self.assertEqual(self.played,[self.rows[0]])
    def test_deleted_session_cannot_be_replayed(self):
        row=self.service.handle({'operation':'list'})['sessions'][0];self.rows=[]
        with self.assertRaises(ValueError):self.service.handle({'operation':'recover','id':row['id']})
        self.assertEqual(self.recovered,[])
    def test_foreign_path_extra_fields_and_missing_audio_are_refused(self):
        for payload in ({'operation':'play','id':'../../other.wav'},{'operation':'play','id':'a','path':'other.wav'}):
            with self.assertRaises(ValueError):self.service.handle(payload)
        self.rows[0]['has_audio']=False
        identifier=self.service.handle({'operation':'list'})['sessions'][0]['id']
        with self.assertRaises(ValueError):self.service.handle({'operation':'recover','id':identifier})

if __name__=='__main__':unittest.main()
