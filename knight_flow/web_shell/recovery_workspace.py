"""Allowlisted recovery actions over opaque session identifiers."""
import hashlib
import math


class RecoveryWorkspace:
    def __init__(self, sessions, recover, play, copy_text, spans=None, retranscribe=None):
        self.sessions, self.recover, self.play, self.copy_text = sessions, recover, play, copy_text
        # T9: where a kept take's audio failed, and one failed part transcribed again.
        self.spans, self.retranscribe = spans, retranscribe

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
        if operation in {'spans','retranscribe'}:
            return self.span_action(operation, payload, rows)
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

    def span_action(self, operation, payload, rows):
        """T9: the failed spans of one kept take, each with its alternative when
        one was transcribed; or ONE span transcribed again. Codes and numbers
        only: the wording belongs to the view."""
        fields={'operation','id'} if operation=='spans' else {'operation','id','span'}
        if set(payload)!=fields or self.spans is None or (operation=='retranscribe' and (
                self.retranscribe is None or type(payload['span']) is not int)):
            raise ValueError('That recovery action is unavailable.')
        row=next((row for row in rows if self.identifier(row)==payload['id']),None)
        if row is None:raise ValueError('That recording is no longer available. Refresh Recovery.')
        if not row.get('has_audio'):raise ValueError('This session has no recorded audio.')
        session_id=str(row['session_id'])
        if operation=='retranscribe':
            if not self.retranscribe(session_id,payload['span']):
                raise ValueError('That recovery action is unavailable.')
            return {'requested':True,'span':payload['span']}
        alternatives=row.get('span_alternatives') if type(row.get('span_alternatives')) is dict else {}
        spans=[]
        for index,span in enumerate(self.spans(session_id)):
            if type(span) is not dict or span.get('kind') not in {'clipped','silent','noisy'}:continue
            again=alternatives.get(str(index))
            spans.append({'index':index,'kind':span['kind'],'start_ms':max(0,self.number(span.get('start_ms'))),
                          'end_ms':max(0,self.number(span.get('end_ms'))),
                          'alternative':str(again.get('text',''))[:2000] if type(again) is dict else ''})
        return {'spans':spans}
