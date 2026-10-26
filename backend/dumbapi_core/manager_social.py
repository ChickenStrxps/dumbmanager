"""Local completion post drafts. No account access or publishing side effects."""
import hashlib
import html
import json
import unicodedata
from urllib.parse import urlencode

from .common import APIError, now
from .manager import Manager, text


def stage(itch):
    accepted = itch['state'] == 'resolved' and any(o.get('acceptance') == 'user_confirmed' for o in itch.get('outcomes', []))
    return 'accepted' if accepted else 'review' if itch['state'] == 'ready' else 'changed'


def card_lines(value, width):
    """Wrap complete text, including wide glyphs and unbroken identifiers."""
    paragraphs = value.splitlines()
    if len(paragraphs)>6: paragraphs=[' '.join(paragraphs)]
    result=[]
    def weight(s):
        return sum(0 if unicodedata.combining(c) else 2 if unicodedata.east_asian_width(c) in 'WF' else 1 for c in s)
    for paragraph in paragraphs:
        line=''
        for word in paragraph.split():
            if line and weight(line+' '+word)>width and weight(word)<=width:
                result.append(line);line=''
            pending=(' ' if line else '')+word
            for char in pending:
                if weight(line+char)>width:
                    result.append(line.rstrip());line=''
                if line or not char.isspace():line+=char
        if line:result.append(line)
    return result or ['']


def card(draft, image_uri=''):
    """2x vector card; decorative variety is stable per draft, never source text."""
    seed = int(hashlib.sha256(str(draft.get('id') or draft['headline']).encode()).hexdigest()[:8],16)
    accent, secondary = [('#ff5ccc','#8b8fff'),('#69f5ce','#a6a0ff'),
                         ('#ffc166','#ff74b8'),('#b9a1ff','#65e5f4')][seed % 4]
    creatures = [
        ('cat', [' /\\_/\\', '( o.o )', ' > ^ <', ' /| |\\', '(_| |_)']),
        ('crab', [' \\     /', '  (o o)', ' /|___|\\', '/ /   \\ \\', 'v v   v v']),
        ('fish', ['       /\\', '  ____/  \\__', ' /  o        >', '<     ____ /', ' \\__/    \\/']),
        ('ghost', ['  .----.', ' / o  o \\', '|   __   |', '|        |', ' \\_/\\_/\\_/']),
        ('frog', ['  @..@', ' (----)', '( >__< )', '^^ ~~ ^^']),
        ('moth', [' \\  /', '/\\oo/\\', '> |<>| <', '\\/||\\/', '  /  \\'])]
    creature, art = creatures[(seed // 4) % len(creatures)]
    def lines(value, top, height, size, color, name):
        width=640
        for font in range(size,5,-1):
            wrapped=card_lines(value,int(width/(font*.65)))
            if len(wrapped)*(font+7)<=height:break
        return f'<g data-copy="{name}" font-weight="{700 if name=="headline" else 400}">'+''.join(f'<text x="64" y="{top+font+i*(font+7)}" font-size="{font}" fill="{color}">{html.escape(line)}</text>' for i,line in enumerate(wrapped))+'</g>'
    label = {'accepted':'WE’RE SO BACK', 'review':'READY TO TEST', 'changed':'WORK IN PROGRESS'}[draft['stage']]
    # 1200x630 design coordinates stay independent of 2400x1260 export pixels.
    # Only the already-sanitized data URI is allowed into the work-picture panel.
    creature_x, creature_y, creature_size = (1032,500,14) if image_uri else (943,238,34)
    critter = f'<g data-critter="{creature}" xml:space="preserve" text-anchor="middle" font-weight="700">'+''.join(
        f'<text x="{creature_x}" y="{creature_y+i*(creature_size+3)}" font-size="{creature_size}" fill="{accent if i%2==0 else secondary}">{html.escape(line)}</text>' for i,line in enumerate(art))+'</g>'
    specks=''.join(f'<rect x="{x}" y="{y}" width="{size}" height="{size}" fill="{secondary}" opacity="{opacity}"/>'
                   for x,y,size,opacity in [(780,138,6,.8),(1120,152,10,.7),(738,495,5,.6),(1102,535,5,.5),(822,537,7,.7),(1090,106,4,.8)])
    panel = (f'<rect x="752" y="183" width="388" height="298" fill="{accent}" opacity=".25"/>'
             f'<rect x="744" y="175" width="388" height="298" fill="#12131f" stroke="{secondary}" stroke-width="2"/>'
             '<rect x="756" y="187" width="364" height="274" fill="#080910"/>'
             f'<image x="756" y="187" width="364" height="274" preserveAspectRatio="xMidYMid meet" href="{image_uri}"/>'
             f'<text x="746" y="156" font-size="14" letter-spacing="2" fill="{secondary}">ON SCREEN</text>') if image_uri else (
             f'<rect x="762" y="172" width="370" height="318" fill="#12131f" stroke="{secondary}" stroke-opacity=".45"/>'
             f'<path d="M782 192h36m-36 0v36M1112 470h-36m36 0v-36" fill="none" stroke="{accent}" stroke-width="3"/>'
             f'<text x="947" y="459" text-anchor="middle" font-size="14" letter-spacing="3" fill="{secondary}">[ BUILD LOG ]</text>')
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="2400" height="1260" viewBox="0 0 1200 630">'
            '<defs><radialGradient id="glow" cx="90%" cy="5%" r="100%">'
            f'<stop stop-color="{secondary}" stop-opacity=".23"/><stop offset="1" stop-color="#090a12" stop-opacity="0"/></radialGradient>'
            '<pattern id="grid" width="24" height="24" patternUnits="userSpaceOnUse"><rect width="2" height="2" fill="#aaa9cf" opacity=".13"/></pattern></defs>'
            '<rect width="1200" height="630" fill="#090a12"/><rect width="1200" height="630" fill="url(#glow)"/>'
            '<rect x="722" y="24" width="454" height="582" fill="url(#grid)"/>'
            f'<path d="M24 122V24h98M1078 24h98v98M1176 508v98h-98M122 606H24v-98" fill="none" stroke="{accent}" stroke-width="4"/>'
            f'<rect x="64" y="60" width="32" height="32" fill="{accent}"/><rect x="72" y="68" width="8" height="8" fill="#090a12"/><rect x="80" y="76" width="8" height="8" fill="#090a12"/>'
            '<g font-family="monospace">'
            f'<text x="110" y="82" font-size="19" font-weight="700" letter-spacing="2" fill="#f9f6ff">DUMBMANAGER</text>'
            f'<text x="1134" y="81" text-anchor="end" font-size="15" letter-spacing="2" fill="{secondary}">DEV / LOG</text>'
            f'<path d="M64 120H1136" stroke="{secondary}" stroke-opacity=".3"/>'
            f'<text x="64" y="154" font-size="14" letter-spacing="3" fill="{accent}">WHAT CHANGED</text>'
            + lines(draft['headline'],175,140,42,'#fcfaff','headline')
            + f'<rect x="64" y="325" width="60" height="4" fill="{accent}"/><rect x="130" y="325" width="10" height="4" fill="{secondary}"/>'
            + lines(draft['summary'],342,140,24,'#d7d7e8','summary')
            + panel + critter + specks
            + f'<rect x="64" y="532" width="{len(label)*12+64}" height="40" fill="{accent}"/>'
            f'<text x="82" y="558" font-size="18" font-weight="700" fill="#090a12">[+] {label}</text>'
            f'<path d="M64 590H1136" stroke="{secondary}" stroke-opacity=".25"/>'
            '</g></svg>')


class Social:
    def __init__(self, config):
        self.manager = Manager(config)

    def call(self, name, args):
        method = name.removeprefix('manager.social.')
        with self.manager.db() as db:
            if method.startswith('webhook_'):
                from . import manager_social_webhook as webhook
                handlers = {'webhook_settings': webhook.settings, 'webhook_configure': webhook.configure,
                            'webhook_preview': webhook.preview, 'webhook_send': webhook.send, 'webhook_status': webhook.status}
                return handlers[method](self, db, **args)
            if method in {'image','image_review'}:
                from .manager_social_image import set_image, review
                return (review if method=='image_review' else set_image)(self,db,**args)
            if method in {'gif','gif_copy'}:
                from .manager_social_gif import gif, copy
                return (copy if method=='gif_copy' else gif)(self,db,**args)
            if method in {'check','link','unlink'}:
                from .manager_posts import check, unlink
                if method == 'unlink':
                    return unlink(self.manager,db,**args)
                return check(self.manager,db,**args)
            if method in {'draft', 'save'}:
                db.execute('BEGIN IMMEDIATE')
            return getattr(self, method)(db, **args)

    def list(self, db, project='', query='', limit=12, offset=0):
        # Query every matching record; do not silently omit older accepted work.
        rows = db.execute("SELECT data FROM records WHERE kind='itch' AND (?='' OR project=?) ORDER BY updated DESC", (project,project))
        items = []
        for raw in rows:
            itch = json.loads(raw[0]); current = stage(itch)
            if current == 'changed' or not all(w in (itch['title']+' '+itch['id']).casefold() for w in query.casefold().split()):
                continue
            from .manager_posts import cached
            items.append({'id':itch['id'],'title':itch['title'],'project':itch['project'],'stage':current,'updated_at':itch['updated_at'],'posting':cached(db,itch['id'])})
        return {'items':items[offset:offset+limit], 'total':len(items), 'next_offset':offset+limit if offset+limit<len(items) else None}

    def refresh(self, db, draft):
        itch = self.manager.get(db, draft['itch_id'], 'itch')
        from .manager_posts import cached
        from .manager_social_image import public_image
        return {**draft,'image':public_image(self.manager,draft.get('image')),'stage':stage(itch),'source_changed':itch['version'] != draft['source_version'],'posting':cached(db,itch['id'])}

    def draft(self, db, itch_id):
        itch = self.manager.get(db, itch_id, 'itch')
        if stage(itch) == 'changed':
            raise APIError('Choose an accepted W or an itch ready for review.')
        id = 'post-'+hashlib.sha256(itch_id.encode()).hexdigest()[:28]
        existing = db.execute("SELECT data FROM records WHERE id=? AND kind='post_draft'", (id,)).fetchone()
        if existing:
            return self.refresh(db, json.loads(existing[0]))
        accepted = stage(itch) == 'accepted'
        outcome = next((o['summary'] for o in reversed(itch.get('outcomes',[])) if o.get('acceptance')=='user_confirmed'), '') if accepted else ''
        headline = itch['title'][:120]
        summary = outcome[:600] if outcome else 'Ready for review. Testing before calling it a W.'
        prefix = 'One less dumb thing.' if accepted else 'Ready to test.'
        row = {'id':id, 'itch_id':itch_id,'project':itch['project'],'source_version':itch['version'],
               'headline':headline,'summary':summary,'caption':f'{prefix}\n\n{headline}\n\n{summary}',
               'version':1,'created_at':now(),'updated_at':now()}
        self.manager.put(db,'post_draft',row)
        return self.refresh(db,row)

    def save(self, db, id, expected_version, headline, summary, caption):
        row = self.manager.get(db,id,'post_draft')
        itch = self.manager.get(db,row['itch_id'],'itch')
        if stage(itch) == 'changed':
            raise APIError('This itch is back in progress. Share it when it is ready to review or accepted.')
        values = {'headline':text(headline,120),'summary':text(summary,600),'caption':text(caption,2000)}
        if not values['headline'] or not values['caption']:
            raise APIError('Add a headline and caption.')
        # Retrying an identical save after a lost response is harmless.
        if row['version'] != expected_version and any(row[k] != v for k,v in values.items()):
            raise APIError('This draft changed in another window. Reload before saving.', 'conflict',409)
        if any(row[k] != v for k,v in values.items()) or row['source_version'] != itch['version']:
            if any(row[k] != v for k,v in values.items()):
                row['copy_edited'] = True
            row.update(values);row.update(version=row['version']+1,updated_at=now(),source_version=itch['version'])
            self.manager.put(db,'post_draft',row)
        return self.refresh(db,row)

    def preview(self, db, id):
        from .manager_social_image import set_image, data_uri
        original = self.manager.get(db,id,'post_draft')
        itch = self.manager.get(db,original['itch_id'],'itch')
        from .manager_social_copy import prepare
        original = prepare(self,db,original,itch,stage(itch))
        itch = self.manager.get(db,original['itch_id'],'itch')
        if stage(itch)!='changed' and not original.get('image') and not original.get('image_opt_out'):
            # Proof picture: the latest image attachment, else a saved review-evidence screenshot.
            if any(a['type']=='image' for a in itch.get('attachments',[])):
                set_image(self,db,id,original['version'])
            else:
                from .manager_social_image import attach_evidence_shot
                attach_evidence_shot(self,db,id,original['version'],itch)
            original = self.manager.get(db,id,'post_draft')
        row = self.refresh(db,original)
        if row['stage'] == 'changed':
            raise APIError('This itch is back in progress. Reopen it when it is ready to review or accepted.')
        return {'draft':row,'svg':card(row,data_uri(self.manager,original.get('image'))),'export_ready':True,  # no manual picture check; local text hiding still applies
                'filename':'dumbmanager-'+row['itch_id'][:8]+'.png',
                'composers':{'bluesky':'https://bsky.app/intent/compose?'+urlencode({'text':row['caption']}),
                             'x':'https://twitter.com/intent/tweet?'+urlencode({'text':row['caption']})},
                'note':'Local draft only. Web composers prefill text; attach the downloaded card yourself. Share sheet file support depends on the app. Nothing is marked posted.'}


def definitions():
    from .registry import boolean, capability, integer, string
    from .manager_social_gif import THEMES
    def cap(name, description, props, required=(), write=False):
        result=capability('manager.social.'+name,'dumbmanager',description,props,required,tags=('social','completion','draft'))
        if write:result['mode']='action'
        return result
    return [cap('webhook_settings','Read webhook formatting and destination host; never returns the saved secret URL.', {}),
            cap('webhook_configure','Save the Windows-encrypted webhook URL and formatting. Empty URL keeps the saved URL; clear_url forgets it. No network request or publishing.',
                {'expected_version':integer(0,0,100000000),'url':string(default='',maxLength=2000),'clear_url':boolean(),
                 'format':string(default='discord',enum=['discord','generic']),'layout':string(default='embed',enum=['embed','plain']),
                 'bullets':boolean(True),'markdown':boolean(True)},('expected_version',),True),
            cap('webhook_preview','Preview the saved webhook text/embed payload for this exact draft. No network request.',
                {'id':string(),'expected_version':integer(1,1,100000000)},('id','expected_version')),
            cap('webhook_status','Read a delivery receipt by request_key, or the latest receipt for a draft id. Never retries or marks an itch posted on X.',
                {'request_key':string(default='',maxLength=100),'id':string(default='')}),
            cap('webhook_send','Send the exact previewed GIF and saved text to the configured webhook only on explicit user action (confirm=true). Durable request keys prevent duplicate retry sends. Returns a receipt; timeout/5xx are uncertain, never automatically retried. Does not accept an itch or mark it posted on X.',
                {'id':string(),'expected_version':integer(1,1,100000000),'settings_version':integer(0,0,100000000),
                 'sha256':string(maxLength=64),'request_key':string(maxLength=100),'vibe':integer(0,0,1000000),'theme':string(default='',maxLength=20),'confirm':boolean()},
                ('id','expected_version','settings_version','sha256','request_key'),True),
            cap('image','Generate a small locally text-obscured work image from saved evidence or the current owned Browse tab. Masks/crop are normalized JSON; no publishing or remote image analysis.',
                {'id':string(),'expected_version':integer(1,1,100000000),'attachment_id':string(default=''),'source':string(default='receipt',enum=['receipt','browser','none']),
                 'crop':string(default='{"x":0,"y":0,"width":1,"height":1}',maxLength=500),'masks':string(default='[]',maxLength=10000)},('id','expected_version'),True),
            cap('gif','Render the current draft as a seamless looping animated GIF (1200x675, X-ready, under 15 MB): seeded ASCII critter scenes with random themes (DumbManager, Windows, Mac, NVIDIA, T3 Code, Oh My Pi, lofi chill, forest, beach, desert, dog, cat, fish, shark, penguin, refractive water flow, dithered smoke) and chance events (Greg, light flicker, lightning). Change vibe to reroll; theme/events optionally force a look. Rendered locally in a throwaway headless Edge and cached. Returns base64 GIF bytes plus export_ready. Never publishes.',
                {'id':string(),'vibe':integer(0,0,1000000),'theme':string(default='',enum=['',*THEMES]),'events':string(default='',maxLength=40)},('id',),True),
            cap('gif_copy','Copy the current animated card to the Windows clipboard as a .gif file, so Ctrl+V in a browser post composer attaches the looping GIF. Requires the exact draft version. Renders if not cached. Never publishes.',
                {'id':string(),'expected_version':integer(1,1,100000000),'vibe':integer(0,0,1000000),'theme':string(default='',maxLength=20),'events':string(default='',maxLength=40)},('id','expected_version'),True),
            cap('image_review','Record the user reviewing this exact sanitized image before export. Does not publish or accept an itch.',
                {'id':string(),'expected_version':integer(1,1,100000000),'digest':string(maxLength=64)},('id','expected_version','digest'),True),
            cap('check','Read saved manually supplied post links. No account scan or publication.',{'itch_id':string(default='')},write=True),
            cap('link','Save a user-supplied post URL without claiming verification. Does not publish or accept an itch.',{'itch_id':string(),'url':string(maxLength=2000)},('itch_id','url'),True),
            cap('unlink','Remove local saved post links. Does not delete an external post.',{'itch_id':string()},('itch_id',),True),
            cap('list','List accepted completions and ready-for-review itches for local post drafts.',
                {'project':string(default=''),'query':string(default='',maxLength=500),'limit':integer(12,1,50),'offset':integer(0,0,100000)}),
            cap('draft','Create or reopen one persistent local draft per itch; never publishes or resolves an itch.',{'itch_id':string()},('itch_id',),True),
            cap('save','Save editable post copy with optimistic concurrency; no external account access.',
                {'id':string(),'expected_version':integer(1,1,100000000),'headline':string(maxLength=120),'summary':string(maxLength=600),'caption':string(maxLength=2000)},
                ('id','expected_version','headline','summary','caption'),True),
            cap('preview','Generate a portable completion card with automatic short changelog copy using saved Mercury settings (local fallback), preserving edited copy. Prepares an available image receipt with local text redaction; export_ready requires exact image review. Never publishes.',{'id':string()},('id',),True)]
