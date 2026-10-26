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

from .bridge import ACK, BotKey, bounded, remote, snowflake
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
        {'name':'dumbbridge','description':'Shape a message into an itch, research or T3 conversation.',
         'type':1,'integration_types':[0,1],'contexts':[0,1,2], 'options':[
             {'name':'message','description':'Idea, research question or message to T3','type':3,'required':True,'max_length':2000},
             {'name':'attachment','description':'Optional image or video evidence','type':11,'required':False}]}]


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
    if mode=='projects':
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
    else:
        controls.append(action_row(button(row,'prepare','Stash as Itch',1,bool(row['itch_id'])),
                                  button(row,'research','Research with Jev'),button(row,'related','Find Related Itches'),button(row,'chat','Chat / Send to T3')))
    frozen=bool(row.get('send_pending')) or bool(row.get('stash_pending')) and not row['itch_id']
    controls.append(action_row(button(row,'edit','Edit intake',disabled=bool(row['itch_id']) or frozen),
                              button(row,'save','Retry same stash' if row.get('stash_pending') and not row['itch_id'] else 'Save to Stashed',1,bool(row['itch_id']) or bool(row.get('send_pending'))),
                              button(row,'projects','Project',disabled=bool(row['itch_id']) or frozen),
                              button(row,'vibe','Another vibe'),button(row,'menu','Actions')))
    if card:
        embed['image']={'url':'attachment://'+card['filename']}
        if card.get('notice'):embed['footer']['text']+=' · still fallback'
    # Discord caps the combined embed text at 6000 characters. Full text stays local.
    budget=5800-len(embed['title'])-len(embed['description'])-len(embed['footer']['text'])
    kept=[]
    for field in embed['fields'][:25]:
        size=min(1024,max(0,budget-len(field['name'])))
        if size<30:break
        value=str(field['value']);field={**field,'value':value if len(value)<=size else value[:size-2]+' …'}
        kept.append(field);budget-=len(field['name'])+len(field['value'])
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
        with self.lock:
            with self.bridge.manager.db() as db:
                saved=db.execute('SELECT * FROM bridge_events WHERE id=?',(event,)).fetchone()
            if saved:
                if saved['digest']!=digest:raise APIError('This event ID was reused with a different body.','conflict',409)
                return json.loads(saved['response']),None
            response,task=self.dispatch(value,actor,channel)
            if task and not self.slots.acquire(blocking=False):
                return {'type':4,'data':{'content':'The bridge is busy. Your draft is kept; try again shortly.','flags':64,'allowed_mentions':{'parse':[]}}},None
            try:
                if task:task={**task,'application_id':settings['application_id']}
                secret=base64.b64encode(_crypt(token.encode())).decode() if task else None
                with self.bridge.manager.db() as db:
                    db.execute('INSERT INTO bridge_events VALUES (?,?,?,?,?,?)',(event,digest,json_text(response),json_text(task) if task else None,secret,'queued' if task else 'done'))
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
                attachment=(data.get('resolved') or {}).get('attachments',{}).get(options.get('attachment'))
                envelope={'text':options.get('message',''),'author_id':actor.split(':',1)[1], 'attachments':[attachment] if attachment else []}
            else:raise APIError('Unknown DumbBridge command.')
            envelope.update(platform='discord',channel_id=channel,guild_id=str(value.get('guild_id') or ''))
            row=self.bridge.create(envelope,actor,value['id'])
            return {'type':4,'data':{**panel(self.bridge,row),'flags':64}}, {'id':row['id'],'actor':actor,'action':'card'}
        if kind not in (3,5):raise APIError('Unsupported interaction type.')
        match=re.fullmatch(r'db:([a-z]+):([a-f0-9]{32}):([0-9]+)',str(data.get('custom_id','')))
        if not match:raise APIError('Unknown DumbBridge control.')
        action,id,version=match.groups();version=int(version);row=self.bridge.get(id,actor)
        if row['source']['channel_id']!=channel:raise APIError('This card belongs to another channel.','forbidden',403)
        if row['version']!=version: return {'type':7,'data':panel(self.bridge,row)},None
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
                 'searchsubmit','menu','vibe','send','replies','link','continue','cancel','append'}
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
                card=self.bridge.card(id,actor);row=self.bridge.get(id,actor)
                if row['version']==version:self.deliver(event,panel(self.bridge,row,card),card)
            except Exception:
                try:
                    row=self.bridge.get(id,actor)
                    if row['version']==version:
                        payload=panel(self.bridge,row);payload['content']='ASCII card unavailable for this reply. Your text and controls are ready; Another vibe retries the render.'
                        self.deliver(event,payload)
                except Exception:pass

    def work(self,event):
        bridge=self.bridge
        with bridge.manager.db() as db:
            hit=db.execute('SELECT * FROM bridge_events WHERE id=?',(event,)).fetchone()
            db.execute("UPDATE bridge_events SET state='running' WHERE id=?",(event,))
        task=json.loads(hit['task']);id,actor,action=task['id'],task['actor'],task['action']
        try:
            try:
                row=bridge.get(id,actor)
                options=bridge.options()
                if not options['enabled'] or options['application_id']!=task.get('application_id') or actor.removeprefix('discord:') not in options['users'] or options['channels'] and row['source']['channel_id'] not in options['channels']:
                    raise APIError('This queued action is no longer enabled. Your draft is kept.')
                if action!='card' and row['version']!=task['version']:raise APIError('This card changed. Use its newest controls.','conflict',409)
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
                row=bridge.mutate(id,actor,{'notice':note[:600]})
                self.deliver(hit,panel(bridge,row))
            with bridge.manager.db() as db:db.execute("UPDATE bridge_events SET state='done',secret=NULL WHERE id=?",(event,))
        except Exception:
            # Do not log tokens, payloads or remote bodies, nor resend on uncertainty.
            with bridge.manager.db() as db:db.execute("UPDATE bridge_events SET state='delivery_uncertain',secret=NULL WHERE id=?",(event,))
        finally:self.slots.release()

    def deliver(self,event,payload,card=None):
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
