"""DumbBridge uses the real dense ASCII/critters renderer, with truthful states."""
import base64
import hashlib
import json
from .common import APIError, atomic_json
from .manager_social_gif import draw, LOCK, renderer_digest

LIMIT=8*1024*1024


def card(bridge,row):
    options=bridge.options()
    source={'id':row['id'],'brand':'DUMBBRIDGE','headline':row['title'],
            'summary':row['goal'] or row['observation'] or 'A new idea, ready to shape.',
            'stage':row['status'],'project':'','image':None}
    # Never copy an unreviewed/private source attachment into a new card.
    key=hashlib.sha256(json.dumps([source,row['vibe'],options['theme'],options['animated'],options['flashes'],
        renderer_digest()],sort_keys=True).encode()).hexdigest()[:40]
    folder=bridge.manager.data/'bridge-cards';folder.mkdir(exist_ok=True)
    info=folder/(key+'.json');notice='';animated=options['animated']
    with LOCK:
        if info.is_file():
            meta=json.loads(info.read_text(encoding='utf-8'));path=folder/(key+meta['extension'])
            if path.is_file():
                path.touch();return {**meta,'draft_version':row['version'],'data':base64.b64encode(path.read_bytes()).decode()}
        force={'theme':options['theme']} if options['theme'] else {}
        if not options['flashes']:
            # Keep critter variety and a rare Greg; omit flashes unless requested.
            force['events']=['greg'] if int(key[:2],16)<64 else []
        try:
            data,meta=draw(bridge.manager.data,source,row['vibe'],force,still=not animated)
            if len(data)>LIMIT:raise APIError('Use the still card for this upload limit.','too_large',413)
        except APIError:
            if not animated:raise
            data,meta=draw(bridge.manager.data,source,row['vibe'],force,still=True)
            animated=False;notice='Animation unavailable or too large; still ASCII card retained.'
        if len(data)>LIMIT:raise APIError('The card exceeds the Discord attachment budget.','too_large',413)
        ext='.gif' if animated else '.png'
        result={**{k:meta.get(k) for k in ('theme','key','events','width','height','frames','seconds')},
            'extension':ext,'animated':animated,'mime':'image/gif' if animated else 'image/png',
            'filename':'dumbbridge-'+key[:12]+ext,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),
            'notice':notice,'draft_version':row['version']}
        path=folder/(key+ext);tmp=path.with_suffix('.tmp');tmp.write_bytes(data);tmp.replace(path);atomic_json(info,result)
        files=sorted([*folder.glob('*.gif'),*folder.glob('*.png')],key=lambda f:f.stat().st_mtime,reverse=True)
        total=0
        for file in files:
            total+=file.stat().st_size
            if total>96*1024*1024 and file!=path:
                file.unlink(missing_ok=True);file.with_suffix('.json').unlink(missing_ok=True)
        return {**result,'data':base64.b64encode(data).decode()}
