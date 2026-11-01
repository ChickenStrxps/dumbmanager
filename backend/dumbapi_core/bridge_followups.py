"""Local, app-and-actor-scoped follow-up bookmarks. No source re-fetching."""
import hashlib
import json
import re
import uuid
from .common import APIError, json_text, now

CAP = 200
PAGE = 10

def setup(db):
    db.execute("CREATE TABLE IF NOT EXISTS bridge_followups (id TEXT PRIMARY KEY, app TEXT NOT NULL, actor TEXT NOT NULL, source_key TEXT NOT NULL, version INTEGER NOT NULL, data TEXT NOT NULL, UNIQUE(app,actor,source_key))")
    db.execute("CREATE INDEX IF NOT EXISTS bridge_followups_owner ON bridge_followups(app,actor)")

def clean(value, limit):
    if not isinstance(value,str) or len(value.encode('utf-16-le'))//2 > limit:
        raise APIError('Follow-up text exceeds its displayed limit.')
    return value.strip()

def get(db, app, actor, id):
    if not re.fullmatch('[a-f0-9]{32}',id): raise APIError('Invalid follow-up.')
    hit=db.execute('SELECT data FROM bridge_followups WHERE id=? AND app=? AND actor=?',(id,app,actor)).fetchone()
    if not hit: raise APIError('Follow-up not found for this account.', 'not_found',404)
    return json.loads(hit[0])

def save(db, app, actor, draft, pending):
    note=clean(pending.get('note',''),200); excerpt=clean(pending.get('excerpt',''),500)
    source=draft.get('source',{})
    key=(source.get('channel_id','')+':'+source.get('message_id','')) if source.get('message_id') else draft['id']
    if not db.in_transaction:db.execute('BEGIN IMMEDIATE')
    found=db.execute('SELECT data FROM bridge_followups WHERE app=? AND actor=? AND source_key=?',(app,actor,key)).fetchone()
    if found:return json.loads(found[0])
    count=db.execute('SELECT COUNT(*) FROM bridge_followups WHERE app=? AND actor=?',(app,actor)).fetchone()[0]
    if count>=CAP:raise APIError('Follow-up inbox is full (200). Delete an item before saving another.', 'conflict',409)
    id=uuid.uuid4().hex  # A recreated bookmark cannot accept controls from a deleted one.
    row={'id':id,'version':1,'note':note,'excerpt':excerpt,'status':'open','created_at':now(),
         'channel_id':source.get('channel_id',''),'guild_id':source.get('guild_id',''),
         'url':source.get('url','') if source.get('url','').startswith('https://discord.com/channels/') else ''}
    db.execute('INSERT INTO bridge_followups VALUES (?,?,?,?,?,?)',(id,app,actor,key,1,json_text(row)))
    return row

def listing(db,app,actor,offset):
    offset=max(0,min(int(offset),CAP))
    total=db.execute('SELECT COUNT(*) FROM bridge_followups WHERE app=? AND actor=?',(app,actor)).fetchone()[0]
    rows=db.execute('SELECT data FROM bridge_followups WHERE app=? AND actor=? ORDER BY rowid DESC LIMIT ? OFFSET ?', (app,actor,PAGE,offset)).fetchall()
    return [json.loads(x[0]) for x in rows],total,offset

def change(db,app,actor,id,version,action,note=None):
    if not db.in_transaction:db.execute('BEGIN IMMEDIATE')
    row=get(db,app,actor,id)
    if row['version']!=version:raise APIError('Follow-up changed. Reopen it from the inbox.', 'conflict',409)
    if action=='delete':
        db.execute('DELETE FROM bridge_followups WHERE id=? AND app=? AND actor=?',(id,app,actor));return None
    if action=='edit':row['note']=clean(note,200)
    elif action=='done':row['status']='done'
    elif action=='reopen':row['status']='open'
    else:raise APIError('Unknown follow-up action.')
    row['version']+=1
    db.execute('UPDATE bridge_followups SET version=?,data=? WHERE id=? AND app=? AND actor=?',(row['version'],json_text(row),id,app,actor))
    return row
