"""Short, revisitable setup with truthful checks and transactional progress."""
from __future__ import annotations
import copy,hashlib,hmac,json,secrets
from knight_flow import official_build
from knight_flow.config import _SAVE_LOCK
from knight_flow.onboarding import mark_onboarding_complete,primary_hotkey,hotkey_labels,WRITING_PRESETS,apply_writing_preset
from knight_flow.stt_registry import local_only,provider_settings,PROVIDER_BY_ID,FLAGSHIP_CLOUD_PROVIDER_IDS,sync_legacy_deepgram

CHAPTERS=('welcome','voice','controls','practice')
LEGACY={'intro':'welcome','welcome':'welcome','voice':'voice','microphone':'voice','permissions':'voice',
        'controls':'controls','menu':'controls','superpowers':'controls','writing':'practice','test':'practice'}
FLAGS=('microphone_tested','hotkey_rehearsed','dictation_tested')


class SetupWorkspace:
    def __init__(self,config,save,actions,microphone,formatting=None):
        self.config,self.save,self.actions,self.microphone=config,save,actions,microphone
        # Smart formatting (the local writing model). Optional: absent, the
        # step is simply not shown, and it never gates Finish setup.
        self.formatting=formatting
        self.key=secrets.token_bytes(32)
        onboarding=config.get('onboarding',{})
        onboarding=onboarding if type(onboarding) is dict else {}
        flags=onboarding.get('resume_flags',{})
        flags=flags if type(flags) is dict else {}
        self.flags={key:onboarding.get(key) is True or flags.get(key) is True for key in FLAGS}
        self.chapter=onboarding.get('shared_chapter',LEGACY.get(onboarding.get('resume_step_id'),'welcome'))
        if self.chapter not in CHAPTERS:self.chapter='welcome'
        self.practice={'phase':'idle','text':'','message':'Your microphone is off. Start when you are ready.'}
        self.generation=0;self.message='';self.rehearsing=False

    def revision(self):
        raw=json.dumps(self.config,sort_keys=True,ensure_ascii=True,separators=(',',':')).encode()
        return hmac.new(self.key,raw,hashlib.sha256).hexdigest()

    def require(self,payload,fields=()):
        if type(payload) is not dict or set(payload)!={'operation',*fields}:
            raise ValueError('That setup action is unavailable.')

    def current(self,revision):
        if type(revision) is not str or not hmac.compare_digest(revision,self.revision()):
            raise ValueError('Settings changed elsewhere. Refresh setup before saving this choice.')

    def normalize(self):
        candidate=copy.deepcopy(self.config)
        if type(candidate.get('onboarding')) is not dict:candidate['onboarding']={}
        return candidate

    def persist(self,candidate):
        try:result=self.save(candidate)
        except Exception:raise ValueError('Setup could not be saved. Your previous settings remain; try again.') from None
        if type(result) is not dict or result.get('saved') is not True:
            raise ValueError('Setup could not be saved. Your previous settings remain; try again.')
        self.config.clear();self.config.update(candidate)
        self.message='Saved.' if result.get('runtime_refreshed') is not False else 'Saved. Restart Talk DAT to apply every setting.'

    def update_checks(self):
        mic=self.microphone.snapshot()['check']
        if mic.get('phase')=='ready' and mic.get('mode')=='mic' and type(mic.get('report')) is dict:
            self.flags['microphone_tested']=True
        if self.rehearsing:
            result=self.actions('rehearsal_status',None)
            self.rehearsing=result['active']
            if result.get('matched') is True:self.flags['hotkey_rehearsed']=True
        if self.practice['phase'] in {'listening','processing'}:
            status=self.actions('speech_status',None)
            if not status['active']:
                self.practice.update(phase='idle',message='The practice stopped without a result. Check your voice settings and try again.')
            elif status.get('processing'):self.practice['phase']='processing'

    def snapshot(self):
        self.update_checks()
        onboarding=self.config.get('onboarding',{})
        onboarding=onboarding if type(onboarding) is dict else {}
        stt=self.config.get('stt',{});route=str(stt.get('route_mode','local'))
        provider_id='local' if local_only(self.config) or route=='local' else str(stt.get('cloud_provider') or stt.get('provider') or '')
        provider=PROVIDER_BY_ID.get(provider_id)
        return {'revision':self.revision(),'chapter':self.chapter,'completed':onboarding.get('completed') is True,
            'flags':dict(self.flags),'route':route,'local_only':local_only(self.config),
            'provider':provider.label if provider else 'Review speech settings',
            'shortcut':list(hotkey_labels(primary_hotkey(self.config))),
            'preset':onboarding.get('writing_preset',''),'presets':[{'id':key,'label':value['title'],'description':value['description']} for key,value in WRITING_PRESETS.items()],
            'permissions':self.actions('permissions',None),'practice':dict(self.practice),'rehearsing':self.rehearsing,
            'message':self.message,'microphone':self.microphone.snapshot(),
            'formatting':self.formatting_snapshot(),'formatting_choice':str(onboarding.get('smart_formatting','')),
            'usage_counts':self.usage_counts_snapshot()}

    def usage_counts_snapshot(self):
        # Owner decision 2026-09-23: setup mentions the anonymous usage counts
        # once -- a line and the toggle, no nag -- and only in a build that can
        # send them. The switch is privacy.share_usage_counts, the same one
        # Settings > Privacy shows.
        if not official_build.usage_counts_available():return None
        return {'on':official_build.share_usage_counts(self.config)}

    def formatting_snapshot(self):
        if self.formatting is None:return None
        try:return self.formatting.snapshot()
        except Exception:return None

    def receive(self,generation,text):
        if generation!=self.generation:return
        clean=str(text or '').strip()
        self.practice={'phase':'ready' if clean else 'empty','text':clean,
            'message':'Review the words below. Nothing was pasted into another app.' if clean else 'No words returned. Check your microphone or voice settings and try again.'}
        if clean:self.flags['dictation_tested']=True

    def stop_activity(self):
        self.actions('speech_cancel',None)
        self.actions('rehearsal_stop',None);self.rehearsing=False
        self.microphone.handle({'operation':'stop'})
        self.generation+=1
        if self.practice['phase'] in {'listening','processing'}:self.practice.update(phase='idle',message='Practice cancelled. Your microphone is off.')

    def handle(self,payload):
        if type(payload) is not dict:raise ValueError('That setup action is unavailable.')
        operation=payload.get('operation')
        if operation=='state':self.require(payload)
        elif operation=='mic':
            self.require(payload,{'request'})
            request=payload['request']
            if type(request) is not dict or request.get('operation') not in {'open','refresh','select','start','stop','status'}:
                raise ValueError('That microphone action is unavailable.')
            if request.get('operation')=='open' and request.get('mode')!='mic':raise ValueError('Choose the microphone level check.')
            if request.get('operation')=='start' and self.rehearsing:raise ValueError('End the trigger check before testing the microphone.')
            self.microphone.handle(request)
        elif operation=='usage':
            self.require(payload,{'revision','value'})
            if type(payload['value']) is not bool or not official_build.usage_counts_available():
                raise ValueError('That setup action is unavailable.')
            with _SAVE_LOCK:
                self.current(payload['revision'])
                candidate=self.normalize()
                privacy=candidate.get('privacy')
                if type(privacy) is not dict:privacy=candidate['privacy']={}
                privacy['share_usage_counts']=payload['value']
                self.persist(candidate)
            if self.message=='Saved.':
                self.message=('Anonymous usage counts are on.' if payload['value'] else 'Anonymous usage counts are off.')+' Change it any time in Settings, Privacy.'
        elif operation in {'chapter','route','preset','finish'}:
            fields={'revision','value'} if operation!='finish' else {'revision','accepted'}
            self.require(payload,fields)
            with _SAVE_LOCK:
                self.current(payload['revision'])
                if operation=='finish' and payload['accepted'] is not True:raise ValueError('Choose Finish setup to accept the displayed terms.')
                value=payload.get('value')
                allowed=CHAPTERS if operation=='chapter' else ('local','byok') if operation=='route' else WRITING_PRESETS
                if operation!='finish' and (type(value) is not str or value not in allowed):raise ValueError('Choose an available setup option.')
                self.stop_activity();self.update_checks();candidate=self.normalize()
                if operation=='route':
                    stt=candidate.setdefault('stt',{})
                    if value=='byok':
                        if local_only(candidate):raise ValueError('Local-only privacy is on. Choose Local, or review Privacy before using your own provider.')
                        provider=str(stt.get('cloud_provider') or stt.get('provider') or '')
                        if provider not in FLAGSHIP_CLOUD_PROVIDER_IDS:raise ValueError('Choose your provider in Speech settings first.')
                        spec=PROVIDER_BY_ID[provider];settings=provider_settings(candidate,provider)
                        if not spec.key_optional and not str(settings.get('api_key','')).strip():raise ValueError('Add your provider key in Speech settings first, or choose Local.')
                        stt['cloud_provider']=provider
                    else:
                        previous=str(stt.get('provider',''))
                        if previous in FLAGSHIP_CLOUD_PROVIDER_IDS:stt['cloud_provider']=previous
                        provider='local'
                    stt.update(provider=provider,route_mode=value);sync_legacy_deepgram(candidate)
                    candidate['onboarding']['route']=value
                if operation=='preset':apply_writing_preset(candidate,value)
                if operation=='chapter':candidate['onboarding']['shared_chapter']=value
                candidate['onboarding']['resume_flags']=dict(self.flags)
                if operation=='finish':
                    mark_onboarding_complete(candidate,route=str(candidate.get('stt',{}).get('route_mode','local')),
                        access_choice=str(candidate['onboarding'].get('access_choice','private')),**self.flags)
                self.persist(candidate)
                if operation=='chapter':self.chapter=value
                if operation=='finish':self.message='Setup saved. You can revisit any check in Help.'+(' Restart Talk DAT to apply every setting.' if 'Restart' in self.message else '')
        elif operation=='formatting':
            self.require(payload,{'revision','value'})
            value=payload['value']
            if self.formatting is None or value not in {'start','later','check','download_page'}:
                raise ValueError('That formatting action is unavailable.')
            if value in {'start','later'}:
                with _SAVE_LOCK:
                    self.current(payload['revision'])
                    candidate=self.normalize();candidate['onboarding']['smart_formatting']='later' if value=='later' else 'started'
                    self.persist(candidate)
            if value=='start':self.message=self.formatting.start()['message']
            elif value=='later':self.message='Not now. Set up smart formatting any time in Settings, Formatting.'
            elif value=='check':self.message=self.formatting.check_again()['message']
            else:self.message=self.formatting.open_download_page()['message']
        elif operation=='rehearse':
            self.require(payload);self.stop_activity();self.actions('rehearsal_start',None);self.rehearsing=True
        elif operation=='practice':
            self.require(payload);self.stop_activity();generation=self.generation
            self.actions('speech_start',lambda text:self.receive(generation,text))
            self.practice={'phase':'listening','text':'','message':'Speak naturally, then choose Finish recording. Your result stays here.'}
        elif operation=='stop':self.require(payload);self.actions('speech_stop',None)
        elif operation=='cancel':self.require(payload);self.stop_activity()
        elif operation=='copy':
            self.require(payload)
            if not self.practice['text']:raise ValueError('There are no practice words to copy yet.')
            self.actions('copy',self.practice['text'])
        elif operation=='permission':self.require(payload,{'value'});self.actions('permission',payload['value'])
        elif operation=='document':self.require(payload,{'value'});self.actions('document',payload['value'])
        else:raise ValueError('That setup action is unavailable.')
        return self.snapshot()

    def close(self):self.stop_activity()
