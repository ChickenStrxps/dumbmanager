"""Discord's signed HTTP interactions, native components and private replies.

Uses the installed OpenSSL verifier, not handwritten signature cryptography.
No bot token is needed to answer interactions; registration is an explicit action.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote, urlencode

from .bridge import ACK, BotKey, bounded, remote, snowflake, draft_lock
from .browser_credentials import _crypt
from .common import APIError, json_text, now


def verifier():
    found=shutil.which('openssl')
    if found:return found
    path=Path(os.environ.get('ProgramFiles',r'C:\Program Files'))/'Git'/'usr'/'bin'/'openssl.exe'
    return str(path) if path.is_file() else None


def verify(public_key,signature,timestamp,body):
    try:
        if not re.fullmatch(r'[0-9]{1,14}',timestamp) or abs(time.time()-int(timestamp))>300:return False
        sig=bytes.fromhex(signature);key=bytes.fromhex(public_key)
        if len(sig)!=64 or len(key)!=32 or not verifier():return False
        with tempfile.TemporaryDirectory(prefix='dumbbridge-verify-') as temp:
            folder=Path(temp)
            # RFC 8410 SubjectPublicKeyInfo for Ed25519; public inputs only.
            (folder/'key.der').write_bytes(bytes.fromhex('302a300506032b6570032100')+key)
            (folder/'signature').write_bytes(sig)
            (folder/'message').write_bytes(timestamp.encode('ascii')+body)
            result=subprocess.run([verifier(),'pkeyutl','-verify','-pubin','-keyform','DER','-inkey',str(folder/'key.der'),
                '-rawin','-in',str(folder/'message'),'-sigfile',str(folder/'signature')],
                capture_output=True,timeout=2,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            return result.returncode==0
    except (OSError,ValueError,subprocess.TimeoutExpired):return False


def commands():
    return [{'name':'DumbBridge','type':3,'integration_types':[0,1],'contexts':[0,1,2]},
        {'name':'Inspect characters','type':3,'integration_types':[0,1],'contexts':[0,1,2]},
        {'name':'dbinspect','description':'Privately inspect invisible characters without saving a draft.',
         'type':1,'integration_types':[0,1],'contexts':[0,1,2], 'options':[
             {'name':'text','description':'Text to inspect; no history fetch, automatic repair or provider call','type':3,'required':True,'max_length':4000}]},
        {'name':'dumbbridge','description':'Shape a message into an itch, research or T3 conversation.',
         'type':1,'integration_types':[0,1],'contexts':[0,1,2], 'options':[
             {'name':'message','description':'Idea, research question or message to T3','type':3,'required':False,'max_length':2000},
             {'name':'attachment','description':'Optional image or video evidence','type':11,'required':False},
             {'name':'inbox','description':'Open your private follow-ups instead','type':5,'required':False}]}]


def register(bridge,confirm=False,guild_id=''):
    options=bridge.options();app=options['application_id']
    if not app:raise APIError('Save the Discord application ID first.')
    if guild_id:snowflake(guild_id)
    invite='https://discord.com/oauth2/authorize?'+urlencode({'client_id':app,'scope':'applications.commands','integration_type':1})
    definitions=commands()
    if not confirm:return {'commands':definitions,'install_url':invite,'registered':False}
    key=BotKey(bridge.config.data).load()
    if not key:raise APIError('Save a Discord bot token in DumbBridge settings to register commands.')
    endpoint=f'https://discord.com/api/v10/applications/{app}/'+(f'guilds/{guild_id}/' if guild_id else '')+'commands'
    result=[]
    try:
        for command in definitions:
            command=dict(command)
            if guild_id:
                command.pop('integration_types',None);command.pop('contexts',None)
            value=json.loads(remote(endpoint,method='POST',body=json_text(command).encode(),headers={
                'Authorization':'Bot '+key,'Content-Type':'application/json'}))
            result.append({'id':value['id'],'name':value['name']})
    except Exception:
        raise APIError('Discord did not confirm all command registrations. Recheck the app/token and retry; named upserts do not replace other commands.', 'discord_registration',502) from None
    return {'registered':True,'commands':result,'install_url':invite}


def button(row,action,label,style=2,disabled=False):
    return {'type':2,'style':style,'label':label,'custom_id':f'db:{action}:{row["id"]}:{row["version"]}','disabled':disabled}


def action_row(*components):return {'type':1,'components':list(components)}

def utf16_length(value):return len(str(value).encode('utf-16-le'))//2

def utf16_clip(value,limit):
    return str(value).encode('utf-16-le')[:limit*2].decode('utf-16-le','ignore')



def panel(bridge,row,card=None):
    mode=row.get('panel','menu')
    project=row['project'] or 'All / unsorted'
    thread=(row['thread_title']+' · `'+row['thread_id']+'`') if row['thread_id'] else 'Choose an exact thread'
    description=f'**Project:** {project}\n**T3:** {thread}\n\n'+row['observation'][:900]
    fields=[]
    for name,key in [('Goal','goal'),('Why it matters','why'),('Open questions','questions')]:
        if row.get(key):fields.append({'name':name,'value':row[key][:700]})
    if row.get('generation_note'):fields.append({'name':'Draft','value':row['generation_note'][:300]})
    if row['itch_id']:fields.append({'name':'Saved itch','value':row['itch_id']})
    if row.get('notice'):fields.append({'name':'Status','value':row['notice'][:600]})
    if row.get('suggested_project'):fields.append({'name':'Suggested project','value':row['suggested_project']+' · choose Project to apply it.'})
    embed={'title':row['title'][:240],'description':description,'color':0xEB5ABC,'fields':fields,
           'footer':{'text':'DumbBridge · '+row['status']+' · source kept · acceptance stays with you'}}
    source_url=row['source']['url']
    if source_url.startswith('https://discord.com/channels/'):embed['url']=source_url
    controls=[]
    if mode=='brief':
        brief=row.get('repro_brief') or {}
        source=row.get('source',{}).get('text','')
        embed={'title':'Repro brief - private', 'description':('Edit the five fields, then download the complete Markdown. Unknown fields remain unknown. Automatic IDs and media are omitted. Your text is not redacted; review the full file.\n\nSource snapshot: '+('INCLUDED - use Omit source to remove it.' if brief.get('include_source') else 'OMITTED - use Include source to review and include it.')), 'color':0xEB5ABC, 'fields':[], 'footer':{'text':'No provider call, itch capture or T3 send.'}}
        for key,label in [('title','Title'),('environment','Environment'),('expected','Expected'),('observed','Observed'),('steps','Steps')]:
            embed['fields'].append({'name':label,'value':brief.get(key) or 'Unknown'})
        if brief.get('include_source'):
            embed['fields'].append({'name':'Selected source snapshot (complete in file)', 'value':(source or '[No text supplied]')[:1000]})
        brief_controls=[button(row,'briefedit','Edit brief',1),button(row,'briefsource','Omit source' if brief.get('include_source') else 'Include source'),button(row,'brieffile','Download full Markdown',1)]
        if row.get('brief_recovery'):
            embed['fields'].insert(0,{'name':'Recovered edit: not applied','value':'A stale submission is retained separately. Download it before retrying your edit.'})
            brief_controls += [button(row,'briefrecovery','Download recovered edit'),button(row,'clearbriefrecovery','Discard recovered edit')]
        controls.append(action_row(*brief_controls))
    elif mode=='projects':
        choices=list(bridge.config.roots().items());offset=row.get('project_offset',0)
        options=[{'label':name[:100],'value':id} for id,(name,_) in choices[offset:offset+24]]
        options.insert(0,{'label':'All / unsorted','value':'_unsorted'})
        controls.append(action_row({'type':3,'custom_id':f'db:project:{row["id"]}:{row["version"]}',
                                    'placeholder':'Choose a project','options':options}))
        controls.append(action_row(button(row,'prevprojects','Previous projects',disabled=offset==0),
                                  button(row,'nextprojects','More projects',disabled=offset+24>=len(choices))))
    elif mode=='threads':
        options=[{'label':r['title'][:100] or 'Untitled','value':r['id'],
                  'description':str(r.get('project') or '')[:100] or 'T3 thread'} for r in row.get('thread_choices',[])[:25]]
        if options:controls.append(action_row({'type':3,'custom_id':f'db:thread:{row["id"]}:{row["version"]}',
                                              'placeholder':'Choose an exact T3 thread','options':options}))
        controls.append(action_row(button(row,'threadsearch','Search threads')))
    elif mode=='related':
        embed['fields'].append({'name':'Related itches','value':row.get('related_note','')[:300] or 'No candidates yet.'})
        options=[]
        for item in row['related']:
            embed['fields'].append({'name':item['title'][:180],'value':item['state']+' · '+item['id']+'\n'+item['basis']})
            options.append({'label':item['title'][:100],'value':item['id'],'description':'Link source · '+item['state']})
        if options:controls.append(action_row({'type':3,'custom_id':f'db:link:{row["id"]}:{row["version"]}',
                                              'placeholder':'Explicitly link this source to an itch','options':options}))
    elif mode=='research':
        research=row['research']
        if research:
            embed['fields'].append({'name':'Research','value':research.get('summary','')[:1000] or 'Research incomplete.'})
            for source in research.get('sources',[])[:3]:
                embed['fields'].append({'name':(source.get('title') or 'Observed source')[:180], 'value':source['url'][:500]})
        controls.append(action_row(button(row,'continue','Review & run next step',disabled=not research.get('needs_review')),
                                  button(row,'append','Append research to itch',disabled=not row['itch_id'] or not research),
                                  button(row,'cancel','Stop research')))
    elif mode=='chat':
        message=bridge.message(row)
        embed['fields'].append({'name':'Itch brief preview' if row['itch_id'] else 'Message preview',
            'value':(message[:900]+'\n… excerpt; the full '+('saved itch brief' if row['itch_id'] else 'original message')+' is sent.' if len(message)>900 else message) or 'Attachments only'})
        if row['source']['attachments']:
            embed['fields'].append({'name':'Evidence sent with it','value':'\n'.join(f['filename'] for f in row['source']['attachments'])[:900]})
        controls.append(action_row(button(row,'send',('Retry same send' if row.get('send_pending') and not row['send_receipt'] else 'Send to '+(row['thread_title'][:40] or 'T3')),1,not row['thread_id'] or bool(row['send_receipt'])),
                                  button(row,'threads','Choose thread',disabled=bool(row.get('send_pending'))),button(row,'replies','Read latest replies',disabled=not row['thread_id'])))
        if row.get('t3_reply'):embed['fields'].append({'name':'Latest T3 reply (bounded)','value':row['t3_reply'][:1000]})
    elif mode!='followup':
        controls.append(action_row(button(row,'prepare','Stash as Itch',1,bool(row['itch_id'])),
                                  button(row,'research','Research with Jev'),button(row,'related','Find Related Itches'),button(row,'chat','Chat / Send to T3')))
    if mode=='followup':
        pending=row.get('followup_pending') or {}
        embed={'title':'Review follow-up before saving', 'description':'Local private app data; no notification or automatic source refresh. The review is local temporary draft data. Confirm adds it to your inbox; Cancel clears the review copy.', 'fields':[{'name':'Note','value':pending.get('note') or '(none)'},{'name':'Captured excerpt (not live)','value':pending.get('excerpt') or '(omitted)'}], 'footer':{'text':'Attachments are omitted.'}, 'color':0xEB5ABC}
        controls.append(action_row(button(row,'followedit','Edit note / excerpt'),button(row,'followsave','Confirm save follow-up',1),button(row,'followcancel','Cancel / clear excerpt')))
    if mode=='menu':controls.append(action_row(button(row,'brief','Make repro brief'),button(row,'followedit','Save follow-up')))
    frozen=bool(row.get('send_pending')) or bool(row.get('stash_pending')) and not row['itch_id']
    controls.append(action_row(button(row,'edit','Edit intake',disabled=bool(row['itch_id']) or frozen),
                              button(row,'save','Retry same stash' if row.get('stash_pending') and not row['itch_id'] else 'Save to Stashed',1,bool(row['itch_id']) or bool(row.get('send_pending'))),
                              button(row,'projects','Project',disabled=bool(row['itch_id']) or frozen),
                              button(row,'vibe','Another vibe'),button(row,'menu','Actions')))
    if card:
        embed['image']={'url':'attachment://'+card['filename']}
        if card.get('notice'):embed['footer']['text']+=' · still fallback'
    # Discord caps the combined embed text at 6000 characters. Full text stays local.
    budget=5800-utf16_length(embed['title'])-utf16_length(embed['description'])-utf16_length(embed['footer']['text'])
    kept=[]
    for field in embed['fields'][:25]:
        size=min(1024,max(0,budget-utf16_length(field['name'])))
        if size<30:break
        value=str(field['value']);field={**field,'value':value if utf16_length(value)<=size else utf16_clip(value,max(0,size-52))+' [EXCERPT; review complete Markdown file]'}
        kept.append(field);budget-=utf16_length(field['name'])+utf16_length(field['value'])
    embed['fields']=kept
    return {'content':'','embeds':[embed],'components':controls[:5], 'allowed_mentions':{'parse':[]},
            'attachments':[{'id':0,'filename':card['filename']}] if card else []}


def modal(row,query=False):
    fields=[('query','Find a T3 thread','',100)] if query else [(k,label,row[k],240 if k=='title' else 1500)
        for k,label in [('title','Title'),('observation','Observation / idea'),('goal','Goal'),('why','Why it matters'),('questions','Open questions')]]
    return {'type':9,'data':{'custom_id':f'db:{"searchsubmit" if query else "edited"}:{row["id"]}:{row["version"]}',
        'title':'Choose a T3 thread' if query else 'Shape this itch','components':[
            {'type':18,'label':label,'component':{'type':4,'custom_id':key,'style':1 if key in ('title','query') else 2,
                'value':value,'max_length':limit,'required':key=='title'}} for key,label,value,limit in fields]}}


def brief_modal(row):
    from .bridge_brief import FIELDS
    brief=row.get('repro_brief') or {}
    return {'type':9,'data':{'custom_id':f'db:briefedited:{row["id"]}:{row["version"]}', 'title':'Edit repro brief', 'components':[
        {'type':18,'label':label,'component':{'type':4,'custom_id':key,'style':1 if key=='title' else 2,
         'value':brief.get(key,''),'max_length':200 if key=='title' else 1500,'required':False}} for key,label in FIELDS]}}


def follow_modal(row):
    pending=row.get('followup_pending') or {}
    return {'type':9,'data':{'custom_id':f'db:followreview:{row["id"]}:{row["version"]}', 'title':'Prepare follow-up', 'components':[
        {'type':18,'label':'Note (optional)','component':{'type':4,'custom_id':'note','style':1,'value':pending.get('note',''),'max_length':200,'required':False}},
        {'type':18,'label':'Optional excerpt: paste to consent','component':{'type':4,'custom_id':'excerpt','style':2,'value':pending.get('excerpt',''),'max_length':500,'required':False}}]}}

def inbox_panel(db,app,actor,offset=0):
    from .bridge_followups import listing, PAGE
    rows,total,offset=listing(db,app,actor,offset)
    components=[]
    if rows:
        components.append(action_row({'type':3,'custom_id':'fi:open:0','placeholder':'Open a follow-up', 'options':[
            {'label':utf16_clip(r['note'] or 'Untitled follow-up',90), 'value':r['id'], 'description':r['status']+' / '+(r.get('channel_id') or 'unknown channel')} for r in rows]}))
    components.append(action_row({'type':2,'style':2,'label':'Previous','custom_id':f'fi:list:{max(0,offset-PAGE)}','disabled':offset==0},
        {'type':2,'style':2,'label':'Next','custom_id':f'fi:list:{offset+PAGE}','disabled':offset+PAGE>=total}))
    return {'content':f'Private follow-ups: {total} stored, page starting {offset+1}. Local workspace must be reachable. Source access is not implied.', 'components':components,'embeds':[],'allowed_mentions':{'parse':[]}}

def literal(text):
    fence='~'*max(3,1+max((len(x) for x in re.findall(r'~+',text)),default=0))
    return fence+'text\n'+text+'\n'+fence


def follow_panel(row):
    def b(action,label):return {'type':2,'style':2,'label':label,'custom_id':f'fi:{action}:{row["id"]}:{row["version"]}'}
    content=('**Follow-up** - '+row['status']+'\nNote: '+(row['note'] or '(none)')+'\nCaptured excerpt (not live): '+(row['excerpt'] or '(omitted)')+
             '\nCaptured: '+row['created_at']+'\nSource channel: '+(row.get('channel_id') or 'unknown')+' / server: '+(row.get('guild_id') or 'DM / unknown')+
             '\nSource link may no longer work: '+(row.get('url') or '(unavailable)'))
    return {'content':content,'embeds':[],'components':[action_row(b('edit','Edit note'),b('reopen' if row['status']=='done' else 'done','Reopen' if row['status']=='done' else 'Mark done'),b('delete','Delete bookmark')),action_row({'type':2,'style':2,'label':'Back to inbox','custom_id':'fi:list:0'})], 'allowed_mentions':{'parse':[]}}

def form_values(data):
    out={}
    def visit(value):
        if not isinstance(value,dict):return
        if value.get('type')==4:out[value['custom_id']]=value.get('value','')
        if 'component' in value:visit(value['component'])
        for child in value.get('components',[]):visit(child)
    visit(data)
    return out


class Discord:
    def __init__(self,bridge):
        self.bridge=bridge;self.lock=threading.RLock();self.slots=threading.BoundedSemaphore(12)
        self.pool=ThreadPoolExecutor(max_workers=2,thread_name_prefix='DumbBridge')
        self.renderer=ThreadPoolExecutor(max_workers=1,thread_name_prefix='DumbBridgeCards')
        self.card_queue={};self.rendering=False
        with bridge.manager.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS bridge_events(id TEXT PRIMARY KEY,digest TEXT NOT NULL,response TEXT NOT NULL,task TEXT,secret TEXT,state TEXT NOT NULL)')
            # A crashed task never replays a write. A fresh click can recover its durable workflow receipt.
            db.execute("UPDATE bridge_events SET state='interrupted',secret=NULL WHERE state IN ('queued','running')")

    def receive(self,body,headers):
        ACK.deadline=time.monotonic()+2.35
        busy={'type':4,'data':{'content':'The local workspace is busy. Reopen this message action shortly.',
            'flags':64,'allowed_mentions':{'parse':[]}}}
        try:return self._receive(body,headers)
        except APIError as exc:
            if exc.code!='bridge_busy':raise
            return busy,None
        except sqlite3.OperationalError as exc:
            if 'locked' not in str(exc).lower() and 'busy' not in str(exc).lower():raise
            return busy,None
        finally:del ACK.deadline

    def _receive(self,body,headers):
        settings=self.bridge.options()
        if not settings['enabled']:raise APIError('DumbBridge is disabled.','unavailable',503)
        if not verify(settings['public_key'],headers.get('X-Signature-Ed25519',''),headers.get('X-Signature-Timestamp',''),body):
            raise APIError('Invalid Discord signature.','unauthorized',401)
        try:value=json.loads(body)
        except (ValueError,UnicodeError):raise APIError('Invalid interaction JSON.') from None
        if not isinstance(value,dict) or value.get('application_id')!=settings['application_id']:
            raise APIError('Wrong Discord application.','forbidden',403)
        if value.get('type')==1:
            with self.bridge.manager.db() as db:self.bridge.manager.set_setting(db,'bridge_discord_check',{'at':now()})
            return {'type':1},None
        user=(value.get('member') or {}).get('user') or value.get('user') or {}
        actor=snowflake(user.get('id',''));channel=snowflake(value.get('channel_id',''))
        if actor not in settings['users'] or settings['channels'] and channel not in settings['channels']:
            raise APIError('This user or channel is not enabled for DumbBridge.','forbidden',403)
        actor='discord:'+actor;event=snowflake(value.get('id',''));digest=hashlib.sha256(body).hexdigest()
        token=bounded(value.get('token',''),500)
        if not token or not re.fullmatch(r'[A-Za-z0-9_.-]+',token):raise APIError('Invalid interaction token.')
        data=value.get('data') or {}
        if value.get('type')==2 and data.get('name') in ('dbinspect','Inspect characters'):
            # No intake, provider, worker, token storage or persistent replay copy.
            from .bridge_inspect import inspect
            text=None
            if data.get('name')=='dbinspect' and data.get('type')==1:
                options=data.get('options')
                if isinstance(options,list) and len(options)==1 and isinstance(options[0],dict) and options[0].get('name')=='text':text=options[0].get('value')
            elif data.get('name')=='Inspect characters' and data.get('type')==3:
                target=data.get('target_id','')
                message=(data.get('resolved') or {}).get('messages',{}).get(target)
                if isinstance(message,dict) and message.get('id')==target and isinstance(target,str) and re.fullmatch(r'[0-9]{6,24}',target):text=message.get('content')
            try:
                if not isinstance(text,str):raise APIError('Discord did not supply text to inspect. Use /dbinspect text: to supply it explicitly; attachments are not read.')
                response=inspect(text)
            except APIError as exc:response={'type':4,'data':{'flags':64,'content':str(exc),'allowed_mentions':{'parse':[]}}}
            return response,None
        with self.lock:
            with self.bridge.manager.db() as db:
                saved=db.execute('SELECT * FROM bridge_events WHERE id=?',(event,)).fetchone()
            if saved:
                if saved['digest']!=digest:raise APIError('This event ID was reused with a different body.','conflict',409)
                return json.loads(saved['response']),None
            try:response,task=self.dispatch(value,actor,channel)
            except APIError as exc:
                custom=str(value.get('data',{}).get('custom_id',''))
                if not (custom.startswith(('fi:','db:brief','db:clearbrief','db:follow')) or any(o.get('name')=='inbox' for o in value.get('data',{}).get('options',[]))):raise
                response={'type':4,'data':{'flags':64,'content':str(exc)[:1400]+' Use the newest controls to retry; nothing was sent.','allowed_mentions':{'parse':[]}}};task=None
            if task and not self.slots.acquire(blocking=False):
                return {'type':4,'data':{'content':'The bridge is busy. Your draft is kept; try again shortly.','flags':64,'allowed_mentions':{'parse':[]}}},None
            try:
                if task:task={**task,'application_id':settings['application_id'],'guild_id':str(value.get('guild_id') or '')}
                secret=base64.b64encode(_crypt(token.encode())).decode() if task else None
                with self.bridge.manager.db() as db:
                    custom=str(value.get('data',{}).get('custom_id',''))
                    private_bookmark=custom.startswith(('fi:','db:follow')) or any(o.get('name')=='inbox' and o.get('value') for o in value.get('data',{}).get('options',[]))
                    cached={'type':4,'data':{'flags':64,'content':'This follow-up interaction was handled. Reopen /dumbbridge inbox:true for current items, or invoke the source action again.','allowed_mentions':{'parse':[]}}} if private_bookmark else response
                    db.execute('INSERT INTO bridge_events VALUES (?,?,?,?,?,?)',(event,digest,json_text(cached),json_text(task) if task else None,secret,'queued' if task else 'done'))
                    # Keep a bounded replay ledger; retain queued/running work.
                    db.execute("DELETE FROM bridge_events WHERE id IN (SELECT id FROM bridge_events WHERE state NOT IN ('queued','running') ORDER BY rowid DESC LIMIT -1 OFFSET 2000)")
            except Exception:
                if task:self.slots.release()
                raise
            return response,event if task else None

    def dispatch(self,value,actor,channel):
        data=value.get('data',{});kind=value.get('type')
        if kind==2:
            if data.get('name')=='DumbBridge' and data.get('type')==3:
                source=(data.get('resolved') or {}).get('messages',{}).get(data.get('target_id'))
                if not isinstance(source,dict):raise APIError('Discord did not supply the selected message.')
                message_id=snowflake(str(source['id']));guild=str(value.get('guild_id') or '@me')
                envelope={'text':source.get('content',''),'message_id':message_id,'author_id':source.get('author',{}).get('id',''),
                    'timestamp':source.get('timestamp',''),'url':f'https://discord.com/channels/{guild}/{channel}/{message_id}',
                    'attachments':source.get('attachments',[])}
            elif data.get('name')=='dumbbridge' and data.get('type')==1:
                options={o['name']:o.get('value') for o in data.get('options',[])}
                if options.get('inbox'):
                    if options.get('message') or options.get('attachment'):raise APIError('Choose inbox or message, not both.')
                    with self.bridge.manager.db() as db:result=inbox_panel(db,value['application_id'],actor)
                    return {'type':4,'data':{**result,'flags':64}},None
                attachment=(data.get('resolved') or {}).get('attachments',{}).get(options.get('attachment'))
                envelope={'text':options.get('message',''),'author_id':actor.split(':',1)[1], 'attachments':[attachment] if attachment else []}
            else:raise APIError('Unknown DumbBridge command.')
            envelope.update(platform='discord',channel_id=channel,guild_id=str(value.get('guild_id') or ''))
            row=self.bridge.create(envelope,actor,value['id'])
            if row.get('discord_app') not in (None,value['application_id']):raise APIError('This draft belongs to another app. Invoke the command again.','forbidden',403)
            if not row.get('discord_app'):row=self.bridge.mutate(row['id'],actor,{'discord_app':value['application_id']})
            return {'type':4,'data':{**panel(self.bridge,row),'flags':64}}, {'id':row['id'],'actor':actor,'action':'card'}
        if kind not in (3,5):raise APIError('Unsupported interaction type.')
        custom=str(data.get('custom_id',''))
        if custom.startswith('fi:'):
            from .bridge_followups import get, change
            app=value['application_id']
            listmatch=re.fullmatch(r'fi:(list|open):([0-9]+)',custom)
            if listmatch:
                action,offset=listmatch.groups()
                with self.bridge.manager.db() as db:
                    result=inbox_panel(db,app,actor,int(offset)) if action=='list' else follow_panel(get(db,app,actor,(data.get('values') or [''])[0]))
                return {'type':7,'data':result},None
            match=re.fullmatch(r'fi:(edit|edited|done|reopen|delete):([a-f0-9]{32}):([0-9]+)',custom)
            if not match:raise APIError('Unknown follow-up control.')
            action,id,version=match.groups();version=int(version)
            if action=='edited':
                from .bridge_followups import clean
                note=clean(form_values(data).get('note',''),200)
                try:
                    with self.bridge.manager.db() as db:result=follow_panel(change(db,app,actor,id,version,'edit',note))
                except APIError:
                    return {'type':4,'data':{'flags':64,'content':'NOT APPLIED: the follow-up changed or was deleted. Copy your submitted note below, then reopen the inbox.',
                        'embeds':[{'title':'Your submitted note (recovery only)','description':literal(note or '(empty note)')}], 'allowed_mentions':{'parse':[]}}},None
                return {'type':7,'data':result},None
            with self.bridge.manager.db() as db:
                row=get(db,app,actor,id)
                if row['version']!=version:raise APIError('Follow-up changed. Reopen it from the inbox.','conflict',409)
                if action=='edit':
                    return {'type':9,'data':{'custom_id':f'fi:edited:{id}:{version}','title':'Edit follow-up note','components':[{'type':18,'label':'Note','component':{'type':4,'custom_id':'note','style':1,'value':row['note'],'max_length':200,'required':False}}]}},None
                row=change(db,app,actor,id,version,'edit' if action=='edited' else action,form_values(data).get('note',''))
                result=follow_panel(row) if row else inbox_panel(db,app,actor)
            return {'type':7,'data':result},None
        match=re.fullmatch(r'db:([a-z]+):([a-f0-9]{32}):([0-9]+)',str(data.get('custom_id','')))
        if not match:raise APIError('Unknown DumbBridge control.')
        action,id,version=match.groups();version=int(version);row=self.bridge.get(id,actor)
        if row.get('discord_app')!=value['application_id'] or row['source'].get('guild_id','')!=str(value.get('guild_id') or ''):
            raise APIError('This card belongs to another app/server or predates secure binding. Invoke DumbBridge on the source again.','forbidden',403)
        if row['source']['channel_id']!=channel:raise APIError('This card belongs to another channel.','forbidden',403)
        if row['version']!=version:
            if kind==5 and action=='briefedited':
                from .bridge_brief import clean_fields
                values=clean_fields(form_values(data))
                row=self.bridge.mutate(id,actor,{'brief_recovery':values,'panel':'brief','notice':'Not applied: the draft changed. Your submitted edit is available as recovery Markdown.'},row['version'])
            if kind==5 and action=='followreview':
                values=form_values(data)
                return {'type':4,'data':{'flags':64,'content':'NOT SAVED: the draft changed. Copy your submission below, then reopen Save follow-up.\nNote: '+utf16_clip(values.get('note',''),200)+'\nExcerpt: '+utf16_clip(values.get('excerpt',''),500),'allowed_mentions':{'parse':[]}}},None
            return {'type':7,'data':panel(self.bridge,row)},None
        if action=='clearbriefrecovery':
            row=self.bridge.mutate(id,actor,{'brief_recovery':None},version)
            return {'type':7,'data':panel(self.bridge,row)},None
        if action=='followcancel':
            row=self.bridge.mutate(id,actor,{'followup_pending':None,'panel':'menu','notice':'Follow-up review cleared. The original intake draft is unchanged.'},version)
            return {'type':7,'data':panel(self.bridge,row)},None
        if action=='followedit':return follow_modal(row),None
        if action=='followreview':
            from .bridge_followups import clean
            values=form_values(data);pending={'note':clean(values.get('note',''),200),'excerpt':clean(values.get('excerpt',''),500)}
            row=self.bridge.mutate(id,actor,{'panel':'followup','followup_pending':pending},version)
            return {'type':7,'data':panel(self.bridge,row)},None
        if action=='followsave':
            from .bridge_followups import save
            with draft_lock(id):
                row=self.bridge.get(id,actor)
                if row['version']!=version or row.get('panel')!='followup' or 'followup_pending' not in row:raise APIError('Review the newest follow-up before saving.','conflict',409)
                with self.bridge.manager.db() as db:
                    db.execute('BEGIN IMMEDIATE')
                    row=self.bridge.manager.get(db,id,'bridge_draft')
                    if row['version']!=version or row['actor']!=actor or row.get('discord_app')!=value['application_id']:raise APIError('Review the latest draft first.','conflict',409)
                    item=save(db,value['application_id'],actor,row,row['followup_pending'])
                    row.update(followup_pending=None,panel='menu',version=version+1,updated_at=now())
                    self.bridge.manager.put(db,'bridge_draft',row)
            return {'type':7,'data':follow_panel(item)},None
        if action=='briefedit':return brief_modal(row),None
        if action=='briefedited':
            row=self.bridge.edit_brief(id,actor,form_values(data),version)
            return {'type':7,'data':panel(self.bridge,row)},None
        if action in ('brief','briefsource'):
            brief=dict(row.get('repro_brief') or {})
            if action=='briefsource':brief['include_source']=not brief.get('include_source',False)
            row=self.bridge.mutate(id,actor,{'panel':'brief','repro_brief':brief},version)
            return {'type':7,'data':panel(self.bridge,row)},None
        if action in ('edit','threadsearch'):
            if action=='edit':
                if row['itch_id']:raise APIError('This intake is already saved.')
                self.bridge.editable(row)
            return modal(row,action=='threadsearch'),None
        if action=='cancel':
            # Immediate cancellation flag, even while every worker is occupied.
            row=self.bridge.mutate(id,actor,{'cancelled':True,'status':'cancelled','notice':'Stop requested. Any current read finishes, then the research browser closes.'},version)
            return {'type':7,'data':panel(self.bridge,row)},None
        task={'id':id,'actor':actor,'action':action,'version':version}
        if action=='edited':
            row=self.bridge.edit(id,actor,form_values(data),version)
            return {'type':7,'data':panel(self.bridge,row)}, {**task,'action':'card'}
        if action=='searchsubmit':task['query']=form_values(data).get('query','')[:100]
        if action in ('project','thread','link'):task['value']=(data.get('values') or [''])[0]
        allowed={'prepare','save','research','related','chat','projects','nextprojects','prevprojects','project','threads','thread',
                 'searchsubmit','menu','vibe','send','replies','link','continue','cancel','append','brieffile','briefrecovery'}
        if action not in allowed:raise APIError('Unknown DumbBridge action.')
        return {'type':6},task

    def start(self,event):
        if event:self.pool.submit(self.work,event)

    def queue_card(self,event,row):
        with self.lock:
            self.card_queue[row['id']]=(dict(event),row['actor'],row['version'],time.monotonic())
            if len(self.card_queue)>24:self.card_queue.pop(next(iter(self.card_queue)))
            if not self.rendering:
                self.rendering=True;self.renderer.submit(self.render_cards)

    def render_cards(self):
        while True:
            with self.lock:
                if not self.card_queue:self.rendering=False;return
                id=next(iter(self.card_queue));event,actor,version,queued=self.card_queue.pop(id)
            try:
                if time.monotonic()-queued>300 or self.bridge.get(id,actor)['version']!=version:continue
                if not self.authorized(event,self.bridge.get(id,actor)):continue
                card=self.bridge.card(id,actor);row=self.bridge.get(id,actor)
                if row['version']==version:self.deliver(event,panel(self.bridge,row,card),card)
            except Exception:
                try:
                    row=self.bridge.get(id,actor)
                    if row['version']==version and self.authorized(event,row):
                        payload=panel(self.bridge,row);payload['content']='ASCII card unavailable for this reply. Your text and controls are ready; Another vibe retries the render.'
                        self.deliver(event,payload)
                except Exception:pass

    def authorized(self,event,row):
        task=json.loads(event['task']);options=self.bridge.options()
        return (options['enabled'] and options['application_id']==task.get('application_id')
            and row.get('discord_app')==task.get('application_id')
            and row['source'].get('guild_id','')==task.get('guild_id','')
            and task['actor'].removeprefix('discord:') in options['users']
            and (not options['channels'] or row['source']['channel_id'] in options['channels']))

    def work(self,event):
        bridge=self.bridge
        with bridge.manager.db() as db:
            hit=db.execute('SELECT * FROM bridge_events WHERE id=?',(event,)).fetchone()
            db.execute("UPDATE bridge_events SET state='running' WHERE id=?",(event,))
        task=json.loads(hit['task']);id,actor,action=task['id'],task['actor'],task['action']
        try:
            try:
                row=bridge.get(id,actor)
                if not self.authorized(hit,row):
                    with bridge.manager.db() as db:db.execute("UPDATE bridge_events SET state='done',secret=NULL WHERE id=?",(event,))
                    return  # Revoked work must not mutate or return its private draft.
                if action!='card' and row['version']!=task['version']:raise APIError('This card changed. Use its newest controls.','conflict',409)
                if action in ('brieffile','briefrecovery'):
                    from .bridge_brief import render
                    if action=='briefrecovery':
                        if not row.get('brief_recovery'):raise APIError('No recovered edit remains.')
                        row={**row,'repro_brief':{**row['brief_recovery'],'include_source':False}}
                    content=render(row).encode('utf-8')
                    file={'filename':'repro-brief.md','mime':'text/markdown; charset=utf-8','data':base64.b64encode(content).decode()}
                    self.deliver(hit,{'content':'Complete private Markdown brief. Review before sharing.','allowed_mentions':{'parse':[]},'attachments':[{'id':0,'filename':file['filename']}]},file)
                    with bridge.manager.db() as db:db.execute("UPDATE bridge_events SET state='done',secret=NULL WHERE id=?",(event,))
                    return
                if action=='prepare':row=bridge.generate(id,actor)
                elif action=='save':row=bridge.stash(id,actor,task['version'])
                elif action=='related':row=bridge.related(id,actor);row=bridge.mutate(id,actor,{'panel':'related'})
                elif action in ('research','continue'):
                    def progress(current):
                        self.deliver(hit,panel(bridge,current));self.queue_card(hit,current)
                    row=bridge.research(id,actor,action=='continue',progress)
                elif action=='cancel':row=bridge.cancel(id,actor)
                elif action=='append':
                    if not row['itch_id'] or not row['research']:raise APIError('Save an itch and gather research first.')
                    with bridge.manager.db() as db:itch=bridge.manager.get(db,row['itch_id'],'itch')
                    marker={'type':'bridge_research','bridge_id':id,'details':row['research']}
                    if marker not in itch['evidence']:
                        bridge.manager.call('manager.update',{'id':itch['id'],'expected_version':itch['version'],'changes':json_text({'evidence':itch['evidence']+[marker]})})
                    row=bridge.mutate(id,actor,{'notice':'Research appended. Itch acceptance is unchanged.'})
                elif action=='link':row=bridge.link(id,actor,task['value'])
                elif action=='send':row=bridge.send(id,actor,task['version'])
                elif action=='replies':
                    from .t3 import T3
                    reply=T3(bridge.config).read(row['thread_id']);messages=[m['text'] for m in reply['messages'] if m['role']=='assistant']
                    row=bridge.mutate(id,actor,{'panel':'chat','t3_reply':messages[-1][-1000:] if messages else 'No assistant reply in the bounded recent window.'})
                elif action in ('chat','menu'):row=bridge.mutate(id,actor,{'panel':action})
                elif action in ('projects','nextprojects','prevprojects'):
                    offset=0 if action=='projects' else max(0,row.get('project_offset',0)+(24 if action=='nextprojects' else -24))
                    row=bridge.mutate(id,actor,{'panel':'projects','project_offset':min(offset,max(0,len(bridge.config.roots())-1))})
                elif action=='project':row=bridge.bind(id,actor,project='' if task['value']=='_unsorted' else task['value']);row=bridge.mutate(id,actor,{'panel':'menu'})
                elif action in ('threads','searchsubmit'):
                    from .t3 import T3
                    found=T3(bridge.config).threads(query=task.get('query',''),limit=25)
                    row=bridge.mutate(id,actor,{'panel':'threads','thread_choices':found['items'],'notice':'Search to narrow these results.' if found.get('partial') else 'Choose a thread; its exact ID is remembered.'})
                elif action=='thread':
                    if task['value'] not in [r['id'] for r in row.get('thread_choices',[])]:raise APIError('Search and choose a listed thread.')
                    row=bridge.bind(id,actor,thread_id=task['value']);row=bridge.mutate(id,actor,{'panel':'chat'})
                elif action=='vibe':row=bridge.mutate(id,actor,{'vibe':row['vibe']+1})
                # The user sees the result before the heavier GIF render starts.
                row=bridge.get(id,actor)
                self.deliver(hit,panel(bridge,row))
                if action not in ('cancel',):self.queue_card(hit,row)
            except Exception as exc:
                note=str(exc) if isinstance(exc,APIError) else 'This action could not finish. Your draft is kept; try its newest controls.'
                row=bridge.get(id,actor)
                if not self.authorized(hit,row):
                    with bridge.manager.db() as db:db.execute("UPDATE bridge_events SET state='done',secret=NULL WHERE id=?",(event,))
                    return
                row=bridge.mutate(id,actor,{'notice':note[:600]})
                self.deliver(hit,panel(bridge,row))
            with bridge.manager.db() as db:db.execute("UPDATE bridge_events SET state='done',secret=NULL WHERE id=?",(event,))
        except Exception:
            # Do not log tokens, payloads or remote bodies, nor resend on uncertainty.
            with bridge.manager.db() as db:db.execute("UPDATE bridge_events SET state='delivery_uncertain',secret=NULL WHERE id=?",(event,))
        finally:self.slots.release()

    def deliver(self,event,payload,card=None):
        task=json.loads(event['task'])
        if not self.authorized(event,self.bridge.get(task['id'],task['actor'])):return
        token=_crypt(base64.b64decode(event['secret']),decrypt=True).decode()
        app=json.loads(event['task'])['application_id']
        url=f'https://discord.com/api/v10/webhooks/{app}/{quote(token,safe="")}/messages/@original'
        if card:
            boundary='DumbBridge'+os.urandom(12).hex()
            content=(f'--{boundary}\r\nContent-Disposition: form-data; name="payload_json"\r\nContent-Type: application/json\r\n\r\n'.encode()+json_text(payload).encode()+
                f'\r\n--{boundary}\r\nContent-Disposition: form-data; name="files[0]"; filename="{card["filename"]}"\r\nContent-Type: {card["mime"]}\r\n\r\n'.encode()+base64.b64decode(card['data'])+f'\r\n--{boundary}--\r\n'.encode())
            headers={'Content-Type':'multipart/form-data; boundary='+boundary}
        else:content=json_text(payload).encode();headers={'Content-Type':'application/json'}
        remote(url,method='PATCH',body=content,headers=headers,limit=200000)

    def close(self):
        self.pool.shutdown(wait=True,cancel_futures=True)
        self.renderer.shutdown(wait=True,cancel_futures=True)
        with self.bridge.manager.db() as db:
            db.execute("UPDATE bridge_events SET state='interrupted',secret=NULL WHERE state IN ('queued','running')")
