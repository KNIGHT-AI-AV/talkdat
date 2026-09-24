"""Explicit feedback submission with memory-only drafts and owned receipts."""
from __future__ import annotations
import copy,secrets,threading,time
from knight_flow.feedback import build_feedback_payload,feedback_mailto,feedback_log_excerpt,validate_feedback_payload


class FeedbackWorkspace:
    def __init__(self, post, sender, logs, copy_text, open_email, *, thread_factory=None, clock=time.monotonic):
        self.post,self.sender,self.logs,self.copy_text,self.open_email=post,sender,logs,copy_text,open_email
        self.thread_factory=thread_factory or (lambda target:threading.Thread(target=target,name='TalkDatFeedback',daemon=True))
        self.clock=clock;self.active=None;self.previews={}
        self.drafts={kind:{'record':{'title':'','details':'','contact':''},'revision':0,
                           'status':'idle','message':'Ready when you are.'}
                     for kind in ('feature','language')}

    @staticmethod
    def require(payload, fields):
        if set(payload)!={'operation','kind',*fields}:raise ValueError('That feedback action is unavailable.')

    @staticmethod
    def record(value):
        if type(value) is not dict or set(value)!={'title','details','contact'}:
            raise ValueError('Complete the feedback fields before sending.')
        for key,limit in [('title',120),('details',16000),('contact',120)]:
            text=value[key]
            if type(text) is not str or len(text)>limit or '\x00' in text:
                raise ValueError('Use a short title, reply address and message.')
            try:text.encode('utf-8')
            except UnicodeError as error:raise ValueError('The message contains an unreadable character. Your draft is still here.') from error
        return copy.deepcopy(value)

    def payload(self,kind,record,logs=''):
        return build_feedback_payload(kind=kind,title=record['title'] if kind=='feature' else '',
            language=record['title'] if kind=='language' else '',details=record['details'],
            contact=record['contact'],context='share-an-idea-'+kind,logs=logs)

    def snapshot(self,kind):
        value=copy.deepcopy(self.drafts[kind])
        value['sending']=self.active is not None and self.active['kind']==kind
        value['busy']=self.active is not None
        value['kind']=kind
        text=self.payload(kind,value['record'])['text']
        value['message_length']=len(text.encode('utf-16-le'))//2
        value['message_limit']=2000
        return value

    def handle(self,payload):
        if type(payload) is not dict or type(payload.get('kind')) is not str or payload['kind'] not in self.drafts:
            raise ValueError('Choose an idea or a language request.')
        kind=payload['kind'];operation=payload.get('operation');draft=self.drafts[kind]
        if operation=='state':
            self.require(payload,set());return self.snapshot(kind)
        if operation=='logs':
            self.require(payload,set())
            logs=feedback_log_excerpt(self.logs())
            token=secrets.token_urlsafe(24)
            self.previews[kind]=(token,self.clock(),logs)
            return {'token':token,'text':logs,'bytes':len(logs.encode('utf-8'))}
        if operation=='draft':
            self.require(payload,{'revision','record'})
            self.current(kind,payload['revision'])
            if self.active is not None and self.active['kind']==kind:
                raise ValueError('Wait for the current send to finish before editing this message.')
            record=self.record(payload['record'])
            if record!=draft['record']:
                draft.update(record=record,revision=draft['revision']+1,status='idle',message='Draft kept in Talk DAT until you quit the app.')
            return self.snapshot(kind)
        if operation=='copy':
            self.require(payload,{'record'})
            text=self.payload(kind,self.record(payload['record']))['text']
            if not text.strip():raise ValueError('Write a few words before copying.')
            self.copy_text(text);return {'message':'Copied the complete message. Formatting logs were not copied.'}
        if operation=='email':
            self.require(payload,{'revision'});self.current(kind,payload['revision'])
            record=draft['record'];message=self.payload(kind,record)
            validate_feedback_payload(message)
            if not message['text'].strip():raise ValueError('Write a few words before opening an email draft.')
            try:
                opened=self.open_email(feedback_mailto(kind=kind,title=record['title'] if kind=='feature' else '',
                    language=record['title'] if kind=='language' else '',details=record['details'],contact=record['contact']))
            except Exception:opened=False
            if not opened:raise ValueError('An email draft could not be opened. Your message is still here to copy.')
            return {'message':'Email draft requested. Finish sending in your mail app. Formatting logs are not attached.'}
        if operation=='send':
            self.require(payload,{'revision','confirmed','include_logs','log_token'})
            self.current(kind,payload['revision'])
            if payload['confirmed'] is not True or type(payload['include_logs']) is not bool:
                raise ValueError('Choose Send to the team when your message is ready.')
            if self.active is not None:raise ValueError('Wait for the current feedback send to finish.')
            if draft['status']=='received':raise ValueError('This message already has a receipt. Start a new message before sending again.')
            logs=''
            if payload['include_logs']:
                preview=self.previews.get(kind)
                if not preview or payload['log_token']!=preview[0] or not 0<=self.clock()-preview[1]<=300 or not preview[2]:
                    raise ValueError('Preview the formatting log again before choosing to attach it.')
                logs=preview[2]
            elif payload['log_token'] not in ('',None):
                raise ValueError('Choose whether to include the previewed formatting log.')
            message=self.payload(kind,draft['record'],logs)
            validate_feedback_payload(message)
            if not message['text'].strip():raise ValueError('Write a few words before sending.')
            job={'kind':kind,'token':object()};self.active=job
            draft.update(status='sending',message='Sending your message…')
            immutable=copy.deepcopy(message)
            def complete(ok,error):
                if self.active is not job:return
                self.active=None
                draft.update(status='received' if ok else 'unconfirmed',message='The Talk DAT service confirmed receipt. Thank you.' if ok else error)
            def worker():
                ok=False;error='Delivery was not confirmed. Your message is still here to copy or retry.'
                try:ok=self.sender(immutable) is True
                except ValueError as failure:error=str(failure)
                except Exception:pass
                self.post(lambda:complete(ok,error))
            try:self.thread_factory(worker).start()
            except Exception:
                self.active=None;draft.update(status='unconfirmed',message='Sending could not start. Your draft is still here; try again.')
                raise ValueError(draft['message'])
            self.previews.pop(kind,None)
            return self.snapshot(kind)
        raise ValueError('That feedback action is unavailable.')

    def current(self,kind,revision):
        if type(revision) is not int or revision!=self.drafts[kind]['revision']:
            raise ValueError('This feedback draft changed. Reopen the latest draft before sending.')
