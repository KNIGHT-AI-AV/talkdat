"""Allowlisted recovery actions over opaque session identifiers."""
import hashlib
import math


class RecoveryWorkspace:
    def __init__(self, sessions, recover, play, copy_text):
        self.sessions, self.recover, self.play, self.copy_text = sessions, recover, play, copy_text

    @staticmethod
    def identifier(row):
        return hashlib.sha256(str(row.get('session_id','')).encode()).hexdigest()[:32]

    @staticmethod
    def number(value):
        return value if type(value) in (float,int) and math.isfinite(value) else 0

    def handle(self, payload):
        if type(payload) is not dict:raise ValueError('That recovery action is unavailable.')
        operation=payload.get('operation')
        rows=self.sessions()
        if operation=='list' and set(payload)=={'operation'}:
            return {'sessions':[{'id':self.identifier(row),'created_at':self.number(row.get('created_at')),
                'duration_ms':max(0,self.number(row.get('duration_ms'))), 'status':str(row.get('status','saved'))[:60],
                'has_audio':bool(row.get('has_audio')), 'has_text':bool(row.get('final_text') or row.get('raw_transcript')),
                'preview':str(row.get('final_text') or row.get('raw_transcript') or '')[:240]} for row in rows]}
        if operation not in {'recover','play','copy'} or set(payload)!={'operation','id'}:
            raise ValueError('That recovery action is unavailable.')
        row=next((row for row in rows if self.identifier(row)==payload['id']),None)
        if row is None:raise ValueError('That recording is no longer available. Refresh Recovery.')
        if operation=='copy':
            text=str(row.get('final_text') or row.get('raw_transcript') or '')
            if not text:raise ValueError('This recording has no text yet. Choose Recover text.')
            self.copy_text(text)
            # Find-more P0-3: a copied take has reached the person; it no longer
            # needs to outlive rotation.
            from knight_flow.audio_spool import mark_session_handled
            mark_session_handled(str(row.get('session_id','')))
            return {'message':'Copied the full recovered text.'}
        if not row.get('has_audio'):raise ValueError('This session has no recorded audio.')
        if operation=='play':
            self.play(row);return {'message':'Opened the recording in your audio player.'}
        self.recover(str(row['session_id']))
        return {'message':'Recovery requested. Finished words appear in History.'}
