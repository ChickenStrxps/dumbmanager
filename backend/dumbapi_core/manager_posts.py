"""Local user-supplied post links. No private capture provider or account scan."""
import hashlib
import json
from urllib.parse import urlsplit, urlunsplit
from .common import APIError,now

def status_id(itch_id):return 'posted-'+hashlib.sha256(itch_id.encode()).hexdigest()[:28]
def cached(db,itch_id):
    row=db.execute("SELECT data FROM records WHERE id=? AND kind='post_status'",(status_id(itch_id),)).fetchone()
    return json.loads(row[0]) if row else {'state':'unconfirmed','posts':[],'candidates':[],'checked_at':None}
def check(manager,db,itch_id='',url=''):
    itches=[manager.get(db,itch_id,'itch')] if itch_id else manager.records(db,'itch',500)
    if url:
        if not itch_id:raise APIError('Choose one itch before saving a link.')
        try:
            u=urlsplit(url)
            host=(u.hostname or '').lower().removeprefix('www.')
            if u.scheme!='https' or u.username or u.password or u.port not in (None,443) or host not in {'x.com','twitter.com','bsky.app','tiktok.com','youtube.com','youtu.be'} or not u.path.strip('/') or u.query or u.fragment:
                raise ValueError()
            url=urlunsplit(('https',host,u.path,'',''))
        except ValueError:raise APIError('Use a direct HTTPS post URL from X, Bluesky, TikTok or YouTube, without tracking parameters.') from None
    rows=[]
    for itch in itches:
        row=cached(db,itch['id'])
        if url:
            posts=[p for p in row.get('posts',[]) if p['url']!=url]
            posts.append({'url':url,'platform':host,'basis':'user_supplied_link','added_at':now(),'account':''})
            row.update(id=status_id(itch['id']),itch_id=itch['id'],project=itch['project'],state='linked',posts=posts[-20:],candidates=[],candidate_count=0,updated_at=now(),checked_at=None)
            manager.put(db,'post_status',row)
        rows.append({**row,'itch_id':itch['id']})
    return {'items':rows,'coverage':{'scope':'manual_links','history_complete':False},'note':'User-supplied links only. No account or availability check was performed.'}
def unlink(manager,db,itch_id):
    itch=manager.get(db,itch_id,'itch')
    row={'id':status_id(itch_id),'itch_id':itch_id,'project':itch['project'],'updated_at':now(),'unlinked_at':now(),'state':'unconfirmed','posts':[],'candidates':[],'checked_at':None}
    manager.put(db,'post_status',row);return row
