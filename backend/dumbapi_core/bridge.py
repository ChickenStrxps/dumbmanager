"""Shared chat-to-work workflows. Discord is an adapter, never the domain store."""
import hashlib
import json
import re
import threading
import time
from contextlib import contextmanager
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .common import APIError, json_text, now
from .manager import Manager, text
from .browser_credentials import JevKeyStore, valid_key

_LOCKS = [threading.RLock() for _ in range(32)]
ACK = threading.local()


@contextmanager
def draft_lock(id):
    if not re.fullmatch('[a-f0-9]{32}',id):raise APIError('Use an exact bridge draft ID.')
    lock=_LOCKS[int(id[:4],16)%32];deadline=getattr(ACK,'deadline',None)
    acquired=lock.acquire() if deadline is None else lock.acquire(timeout=max(0,deadline-time.monotonic()))
    if not acquired:raise APIError('The draft is busy. Use its latest controls shortly.','bridge_busy',409)
    try:yield
    finally:lock.release()


class BridgeManager(Manager):
    @contextmanager
    def db(self):
        with super().db() as db:
            deadline=getattr(ACK,'deadline',None)
            if deadline is not None:
                db.execute('PRAGMA busy_timeout='+str(max(0,int((deadline-time.monotonic())*1000))))
            yield db


class BotKey(JevKeyStore):
    def __init__(self, data):
        super().__init__(data)
        self.path = self.path.with_name('bridge-discord-bot.dpapi')


def bounded(value, limit):
    return text(value, limit)


def snowflake(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{6,24}', value):
        raise APIError('Use an exact Discord ID.')
    return value


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise APIError('The remote endpoint redirected. Nothing was retried.', 'bridge_remote', 502)


def remote(url, *, method='GET', body=None, headers=None, timeout=12, limit=1024*1024):
    """Fixed/validated destinations only; callers never return raw HTTP errors."""
    # Discord rejects urllib's default Python client signature at its edge.
    # This bridge is hosted locally and has no public project/documentation URL.
    request_headers = {'User-Agent':'DiscordBot (http://127.0.0.1:8780, 1.0) DumbBridge'}
    request_headers.update(headers or {})
    request = Request(url, data=body, method=method, headers=request_headers)
    with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=timeout) as response:
        raw = response.read(limit+1)
        if len(raw) > limit:
            raise APIError('The remote reply exceeded its limit.', 'bridge_remote', 502)
        return raw


class Bridge:
    def __init__(self, config):
        self.config, self.manager = config, BridgeManager(config)
        with self.manager.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS bridge_bindings(scope TEXT PRIMARY KEY,data TEXT NOT NULL)')

    def options(self):
        with self.manager.db() as db:
            return {'version':0, 'enabled':False, 'application_id':'', 'public_key':'',
                    'users':[], 'channels':[], 'animated':True, 'flashes':False, 'theme':'',
                    **self.manager.setting(db, 'bridge_discord', {})}

    def status(self):
        from .discord_bridge import verifier
        options = self.options()
        try: key_saved = bool(BotKey(self.config.data).load())
        except APIError: key_saved = False
        ready = bool(options['application_id'] and options['public_key'] and options['users'] and verifier())
        with self.manager.db() as db:
            check = self.manager.setting(db, 'bridge_discord_check', {})
        return {**options, 'bot_key_saved':key_saved, 'signature_verifier':bool(verifier()),
                'configured':ready, 'state':'configured' if ready else 'not_configured',
                'last_verified_interaction':check.get('at'),
                'note':'Listener starts explicitly with dumbbridge.py serve. Configured does not mean connected.'}

    def configure(self, enabled=False, application_id='', public_key='', users='', channels='',
                  animated=True, flashes=False, theme='', bot_token='', forget_token=False, expected_version=0):
        from .manager_social_gif import THEMES
        if application_id: snowflake(application_id)
        if public_key and not re.fullmatch('[a-fA-F0-9]{64}', public_key):
            raise APIError('Use the Discord application public key (64 hexadecimal characters).')
        if theme and theme not in THEMES: raise APIError('Unknown ASCII theme.')
        def ids(value):
            values = list(dict.fromkeys(re.split(r'[\s,]+', value.strip()))) if value.strip() else []
            if len(values)>100: raise APIError('Use at most 100 Discord IDs.')
            return [snowflake(v) for v in values]
        row = {'enabled':enabled, 'application_id':application_id, 'public_key':public_key.lower(),
               'users':ids(users), 'channels':ids(channels), 'animated':animated, 'flashes':flashes, 'theme':theme}
        if enabled and not (row['users'] and public_key and application_id):
            raise APIError('Set the app ID, public key and allowed Discord users before enabling.')
        if bot_token and not valid_key(bot_token):
            raise APIError('Use a valid Discord bot token.')
        with self.manager.db() as db:
            db.execute('BEGIN IMMEDIATE')
            old = self.manager.setting(db, 'bridge_discord', {'version':0})
            if old['version'] != expected_version: raise APIError('Settings changed. Reload before saving.', 'conflict',409)
            if bot_token or forget_token: BotKey(self.config.data).save('' if forget_token else bot_token)
            if old.get('application_id')!=application_id or old.get('public_key')!=public_key.lower():
                self.manager.set_setting(db,'bridge_discord_check',{})
            self.manager.set_setting(db,'bridge_discord',{**row,'version':old['version']+1})
        return self.status()

    def binding(self, actor, channel):
        with self.manager.db() as db:
            hit = db.execute('SELECT data FROM bridge_bindings WHERE scope=?',(json_text([actor,channel]),)).fetchone()
        return json.loads(hit[0]) if hit else {'project':'','thread_id':'','thread_title':''}

    def get(self, id, actor):
        with self.manager.db() as db: row = self.manager.get(db,id,'bridge_draft')
        if row['actor'] != actor: raise APIError('This private card belongs to another user.', 'forbidden',403)
        return row

    def mutate(self, id, actor, changes, expected_version=0):
        with self.manager.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = self.manager.get(db,id,'bridge_draft')
            if row['actor'] != actor: raise APIError('This private card belongs to another user.', 'forbidden',403)
            if expected_version and row['version'] != expected_version:
                raise APIError('This card changed. Use its newest buttons.', 'conflict',409)
            row.update(changes,version=row['version']+1,updated_at=now())
            return self.manager.put(db,'bridge_draft',row)

    def create(self, envelope, actor, request_key):
        source = json.loads(envelope) if isinstance(envelope,str) else envelope
        if not isinstance(source,dict): raise APIError('Use a message envelope.')
        actor, request_key = bounded(actor,100), bounded(request_key,100)
        if not actor or not request_key: raise APIError('A user and stable event key are required.')
        clean = {k:bounded(str(source.get(k,'') or ''), n) for k,n in
                 [('platform',30),('channel_id',100),('guild_id',100),('message_id',100),
                  ('author_id',100),('text',6000),('url',1000),('timestamp',100)]}
        original=source.get('text') or ''
        if not isinstance(original,str) or len(original)>6000:raise APIError('Use message text up to 6000 characters.')
        clean['text']=original  # retain whitespace verbatim in the immutable source
        if clean['platform'] != 'discord': raise APIError('Only Discord intake is implemented.')
        files = source.get('attachments',[])
        if not isinstance(files,list) or len(files)>8: raise APIError('Use up to eight attachments.')
        clean['attachments'] = []
        for file in files:
            if not isinstance(file,dict): raise APIError('Invalid attachment.')
            url = bounded(file.get('url',''),2000)
            part = urlsplit(url)
            if part.scheme!='https' or part.hostname not in {'cdn.discordapp.com','media.discordapp.net'} or not part.path.startswith('/attachments/') or part.username is not None or part.password is not None or part.port not in (None,443):
                raise APIError('Use a Discord attachment URL.')
            clean['attachments'].append({'id':bounded(str(file.get('id','')),100), 'url':url,
                'filename':bounded(file.get('filename') or 'attachment',220), 'content_type':bounded(file.get('content_type') or '',100)})
        if not clean['text'].strip() and not files: raise APIError('Type a message or choose one with an attachment.')
        id = hashlib.sha256(json_text([actor,request_key]).encode()).hexdigest()[:32]
        with draft_lock(id), self.manager.db() as db:
            db.execute('BEGIN IMMEDIATE')
            hit = db.execute('SELECT data FROM records WHERE id=? AND kind=?',(id,'bridge_draft')).fetchone()
            if hit:
                old=json.loads(hit[0])
                if old['source']!=clean: raise APIError('This event key belongs to another message.','conflict',409)
                return old
            binding=self.binding(actor,clean['channel_id'])
            row={'id':id,'actor':actor,'source':clean,'project':binding['project'],
                 'thread_id':binding['thread_id'],'thread_title':binding['thread_title'],
                 'title':clean['text'].strip().split('\n',1)[0][:120] or 'Message attachments',
                 'observation':clean['text'][:1500], 'goal':'','why':'','questions':'',
                 'generation':'original_only','status':'draft','version':1,'created_at':now(),'updated_at':now(),
                 'itch_id':'','media':[],'related':[],'research':{},'vibe':0,'cancelled':False,'send_receipt':None}
            return self.manager.put(db,'bridge_draft',row)

    def edit(self, id, actor, changes, expected_version):
        value=json.loads(changes) if isinstance(changes,str) else changes
        if not isinstance(value,dict) or set(value)-{'title','observation','goal','why','questions'}:
            raise APIError('Only intake text can be edited here.')
        value={k:bounded(v,240 if k=='title' else 1500) for k,v in value.items()}
        if 'title' in value and not value['title']: raise APIError('Give this itch a title.')
        with draft_lock(id):
            row=self.get(id,actor)
            if row['itch_id']: raise APIError('This card is already stashed. Edit the itch in DumbManager.')
            self.editable(row)
            return self.mutate(id,actor,{**value,'generation':'edited'},expected_version)

    @staticmethod
    def editable(row):
        if (row.get('stash_pending') and not row['itch_id']) or row.get('send_pending'):
            raise APIError('A save/send is pending. Retry that same action to recover its receipt before changing the card.', 'conflict',409)

    def bind(self, id, actor, project=None, thread_id=None):
        from .t3 import T3
        with draft_lock(id):
            row=self.get(id,actor)
            self.editable(row)
            changes={}
            if project is not None:
                if project and project not in self.config.roots(): raise APIError('Choose a connected project.')
                if row['itch_id']: raise APIError('This itch already has a project. Start another card to change projects.')
                changes['project']=project
            if thread_id is not None:
                if not thread_id: changes.update(thread_id='',thread_title='')
                else:
                    found=T3(self.config).read(T3.thread_id(thread_id))['thread']
                    if found.get('archived'): raise APIError('Choose an available T3 thread.')
                    changes.update(thread_id=thread_id,thread_title=found.get('title','Untitled'))
            row=self.mutate(id,actor,changes)
            binding={k:row[k] for k in ('project','thread_id','thread_title')}
            with self.manager.db() as db:
                db.execute('INSERT OR REPLACE INTO bridge_bindings VALUES (?,?)',(json_text([actor,row['source']['channel_id']]),json_text(binding)))
            return row

    def generate(self,id,actor):
        from .bridge_ai import intake
        row=self.get(id,actor)
        if row['generation'] in ('mercury','edited') or row['itch_id']: return row
        self.editable(row)
        values=intake(self.config,row)
        return self.mutate(id,actor,values,row['version'])

    def related(self,id,actor):
        from .bridge_ai import related
        row=self.get(id,actor)
        result=related(self.config,self.manager,row)
        return self.mutate(id,actor,{'related':result['items'],'related_note':result['note'],'status':'related'},row['version'])

    def import_media(self,row):
        from .manager_media import Media
        saved=list(row['media']); owner=Media(self.manager)
        for attachment in row['source']['attachments'][len(saved):]:
            try:
                data=remote(attachment['url'],limit=8*1024*1024,timeout=8)
                import io
                media=owner.upload(self.config,io.BytesIO(data),len(data),attachment['filename'],attachment['content_type'])['attachment']
            except Exception:
                raise APIError('An attachment could not be retained. The draft is kept; reattach expired/unsupported files before stashing.', 'bridge_attachment',409) from None
            saved.append(media)
            row=self.mutate(row['id'],row['actor'],{'media':saved})
        return row

    def stash(self,id,actor,expected_version):
        with draft_lock(id):
            row=self.get(id,actor)
            if row['itch_id']: return row
            if row['version']!=expected_version: raise APIError('Review the latest card before stashing.','conflict',409)
            if row.get('send_pending'):raise APIError('Recover the pending T3 send before stashing this card.')
            if not row.get('stash_pending'):
                row=self.mutate(id,actor,{'stash_pending':{'stage':'retaining_media'}})
            row=self.import_media(row)
            # Full immutable message lives in the bridge record even above the itch's 2k limit.
            source=row['source']; original=source['text']
            if len(original)>1750:original=original[:1750]+'\n[Full original retained in DumbBridge '+id+']'
            original+='\nSource: '+source['url'][:150]
            pending=row['stash_pending']
            if 'capture' not in pending:
                pending={**pending,'capture':{'title':row['title'],'project':row['project'] or 'unsorted',
                    'original':original,'use_active':False,'attachments':json_text([m['id'] for m in row['media']]),'request_key':'bridge:'+id}}
                row=self.mutate(id,actor,{'stash_pending':pending})
            capture=self.manager.call('manager.capture',pending['capture'])
            if 'update' not in pending:
                details={'observation':row['observation'],'why':row['why'],'questions':row['questions'],
                         'bridge_id':id,'source':{k:source[k] for k in ('platform','url','message_id','author_id','timestamp')}}
                evidence=capture['evidence']+[{'type':'bridge_intake','at':row['created_at'],'details':details}]
                if row['research']:evidence.append({'type':'bridge_research','details':row['research']})
                pending={**pending,'update':{'id':capture['id'],'expected_version':capture['version'],
                    'changes':json_text({'desired_outcome':row['goal'],'evidence':evidence}), 'request_key':'bridge-save:'+id}}
                row=self.mutate(id,actor,{'stash_pending':pending})
            self.manager.call('manager.update',pending['update'])
            return self.mutate(id,actor,{'itch_id':capture['id'],'status':'stashed'})

    def link(self,id,actor,itch_id):
        with draft_lock(id):
            row=self.get(id,actor)
            self.editable(row)
            if itch_id not in [r['id'] for r in row['related']]: raise APIError('Choose one of this card\'s related itches.')
            with self.manager.db() as db: itch=self.manager.get(db,itch_id,'itch')
            marker={'type':'bridge_source','bridge_id':id,'source_url':row['source']['url'],'text':row['source']['text'][:1500]}
            evidence=itch['evidence']
            if not any(e.get('bridge_id')==id for e in evidence if isinstance(e,dict)):
                self.manager.call('manager.update',{'id':itch_id,'changes':json_text({'evidence':evidence+[marker]}),'expected_version':itch['version']})
            return self.mutate(id,actor,{'itch_id':itch_id,'status':'linked'})

    def message(self,row):
        if row.get('send_pending'):return row['send_pending']['message']
        if row['itch_id']:
            with self.manager.db() as db:return self.manager.op_brief(db,row['itch_id'])['brief']
        return row['source']['text']

    def send(self,id,actor,expected_version):
        from .t3 import T3
        from .t3_distributions import connection_lock, target
        from .t3_uploads import upload
        from .manager_media import Media
        with draft_lock(id), connection_lock(self.config):
            row=self.get(id,actor)
            if row['send_receipt']: return row
            if row['version']!=expected_version: raise APIError('Review the newest card and destination before sending.','conflict',409)
            if row.get('stash_pending') and not row['itch_id']:raise APIError('Recover the pending stash before sending this card.')
            if not row['thread_id']: raise APIError('Choose an exact T3 thread first.')
            T3(self.config).read(row['thread_id'])  # validate; never guess or replace
            row=self.import_media(row)
            # Freeze retry identity, text and uploads before the first external send.
            pending=row.get('send_pending')
            if not pending:
                pending={'thread_id':row['thread_id'],'message':self.message(row),'uploaded':[],'key':'bridge:'+id,'target':target(self.config)}
                row=self.mutate(id,actor,{'send_pending':pending})
            if pending.get('target') and pending['target']!=target(self.config):
                raise APIError('This bridge send belongs to the other T3 installation. Switch back before retrying.','t3_target_changed',409)
            for item in row['media'][len(pending['uploaded']):]:
                file,meta=Media(self.manager).read(item['id'])
                with file.open('rb') as stream:
                    pending['uploaded'].append(upload(self.config,stream,meta['sizeBytes'],meta['name'],meta['mimeType'],'frameboard')['attachment'])
                row=self.mutate(id,actor,{'send_pending':pending})
            receipt=T3(self.config).send(pending['thread_id'],pending['message'],pending['key'],json_text(pending['uploaded']))
            return self.mutate(id,actor,{'send_receipt':receipt,'status':'sent'})

    def research(self,id,actor,reviewed=False,progress=None):
        from .bridge_research import run
        return run(self,id,actor,reviewed,progress)

    def cancel(self,id,actor):
        from .bridge_research import cancel
        row=self.mutate(id,actor,{'cancelled':True,'status':'cancelled'})
        cancel(self,id)
        return row

    def card(self,id,actor):
        from .bridge_cards import card
        return card(self,self.get(id,actor))

    def call(self,name,args):
        method=name.removeprefix('bridge.')
        if method=='discord.commands':
            from .discord_bridge import commands
            return {'commands':commands()}
        if method=='discord.register':
            from .discord_bridge import register
            return register(self,**args)
        return getattr(self,method)(**args)


def definitions():
    from .registry import capability, string, integer, boolean
    def cap(name,desc,props=None,required=(),action=False):
        result=capability('bridge.'+name,'dumbmanager',desc,props,required,tags=('discord','bridge','itch'))
        if action: result['mode']='action'
        return result
    identity={'id':string(maxLength=32),'actor':string(maxLength=100)}
    expected={'expected_version':integer(0,0,1000000)}
    return [cap('status','Read Discord bridge configuration and honest prerequisite state.'),
        cap('configure','Save Discord allowlists, app public identity and encrypted bot key. Does not start or register an app.',{
            'enabled':boolean(),'application_id':string(default=''),'public_key':string(default=''),'users':string(default='',maxLength=2600),
            'channels':string(default='',maxLength=2600),'animated':boolean(True),'flashes':boolean(),'theme':string(default=''),
            'bot_token':string(default=''),'forget_token':boolean(),**expected},action=True),
        cap('create','Create an idempotent private intake draft from a normalized Discord message.',{
            'envelope':string(maxLength=24000),'actor':string(maxLength=100),'request_key':string(maxLength=100)},('envelope','actor','request_key'),True),
        cap('get','Read an intake draft for its owner.',identity,('id','actor')),
        cap('edit','Edit intake text; preserves the source message.',{**identity,'changes':string(maxLength=10000),**expected},('id','actor','changes','expected_version'),True),
        cap('bind','Remember an explicitly chosen project or exact T3 destination for this user/channel.',{
            **identity,'project':string(),'thread_id':string()},('id','actor'),True),
        *[cap(n,d,identity,('id','actor'),True) for n,d in [('generate','Draft structured itch text using saved Mercury; no save/send.'),
            ('related','Retrieve real itches and optionally rank them with Jev; never merges.'),('cancel','Cancel this card\'s bounded research.')]],
        *[cap(n,d,{**identity,**expected},('id','actor','expected_version'),True) for n,d in
          [('stash','Explicitly save the reviewed draft and evidence as a Stashed itch.'),('send','Explicitly send the reviewed message/evidence to its exact selected T3 thread. Stable retries.')]],
        cap('link','Explicitly append this source to a chosen related itch, without reopening or accepting it.',{**identity,'itch_id':string()},('id','actor','itch_id'),True),
        cap('research','Run bounded research in its own isolated browser. Pauses before reviewed actions.',{**identity,'reviewed':boolean()},('id','actor'),True),
        cap('card','Render/cache an animated fine-detail ASCII intake/status card; no publication.',identity,('id','actor'),True),
        cap('discord.commands','Preview native Discord message/slash command definitions.'),
        cap('discord.register','Preview app command setup. confirm=true explicitly upserts only DumbBridge commands.',{'confirm':boolean(),'guild_id':string(default='')},action=True)]
