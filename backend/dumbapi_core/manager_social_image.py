"""Local, flattened work thumbnails. Original pixels never enter exported SVGs."""
import base64
import hashlib
import io
import json
import math
import os
import subprocess
import tempfile
import uuid
from pathlib import Path

from .common import APIError, now
from .manager_media import Media

FULL={'x':0,'y':0,'width':1,'height':1}


def rectangles(value, crop=False):
    try:
        parsed=json.loads(value)
    except (ValueError,TypeError):
        raise APIError('Invalid image rectangles.') from None
    values=[parsed] if crop else parsed
    if not isinstance(values,list) or len(values)>32:
        raise APIError('Use up to 32 privacy masks.')
    for r in values:
        if not isinstance(r,dict) or set(r)!={'x','y','width','height'} or any(not isinstance(v,(int,float)) or isinstance(v,bool) or not math.isfinite(v) for v in r.values()):
            raise APIError('Use normalized image rectangles.')
        if r['x']<0 or r['y']<0 or r['width']<(0.05 if crop else 0.001) or r['height']<(0.05 if crop else 0.001) or r['x']+r['width']>1.000001 or r['y']+r['height']>1.000001:
            raise APIError('Keep image rectangles within the picture.')
    return parsed


def render(source, destination, crop, masks):
    if os.name!='nt':
        raise APIError('Local private previews need Windows OCR on this PC.', 'image_unavailable',503)
    with tempfile.TemporaryDirectory(prefix='private-preview-',dir=destination.parent) as temp:
        temp=Path(temp);config=temp/'input.json';output=temp/'safe.png'
        config.write_text(json.dumps({'source':str(source),'output':str(output),'ocr_input':str(temp/'ocr.png'),'crop':crop,'masks':masks}),encoding='utf-8')
        try:
            result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(Path(__file__).with_name('social_image.ps1')),'-InputJson',str(config)],
                capture_output=True,timeout=45,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            if result.returncode or not output.is_file():
                raise APIError('Private preview could not be created. Use an upright image under 16 megapixels and check Windows OCR language support. Your original is kept locally.', 'image_unavailable',503)
            details=json.loads(result.stdout.decode('utf-8-sig'))
            data=output.read_bytes()
            if len(data)>2_000_000 or not data.startswith(b'\x89PNG\r\n\x1a\n'):
                raise ValueError('Invalid output')
            with destination.open('xb') as handle:handle.write(data)
            return details
        except (OSError,ValueError,subprocess.TimeoutExpired) as exc:
            raise APIError('Local image processing failed. The original is kept and no new image is exportable.', 'image_unavailable',503) from exc


def set_image(social, db, id, expected_version, attachment_id='', source='receipt', crop='{"x":0,"y":0,"width":1,"height":1}', masks='[]'):
    manager=social.manager;row=manager.get(db,id,'post_draft');itch=manager.get(db,row['itch_id'],'itch')
    if social.refresh(db,row)['stage']=='changed':
        raise APIError('This itch is back in progress. Review it before making a completion image.')
    if row['version']!=expected_version:
        raise APIError('This draft changed. Reopen it before changing the picture.','conflict',409)
    crop=rectangles(crop,True);masks=rectangles(masks)
    media=Media(manager)
    if source=='none':
        image=None
    else:
        if source=='browser':
            from .browser import instance
            snap=instance(manager.config).snapshot()
            raw=base64.b64decode(snap['image'],validate=True)
            attachment_id=media.upload(manager.config,io.BytesIO(raw),len(raw),'work-screenshot.jpg','image/jpeg')['attachment']['id']
        elif not attachment_id:
            attachment_id=next((a['id'] for a in reversed(itch.get('attachments',[])) if a['type']=='image'),'')
        if not attachment_id:
            raise APIError('Add a work screenshot or capture the current Browse tab.')
        file,attachment=media.read(attachment_id)
        if attachment['type']!='image':
            raise APIError('Choose a saved image or video frameboard.')
        identity=hashlib.sha256(file.read_bytes()+json.dumps([crop,masks,'text-hide-v1'],sort_keys=True).encode()).hexdigest()
        folder=manager.data/'social-images';folder.mkdir(exist_ok=True)
        if sum(p.stat().st_size for p in folder.glob('*.png'))>64*1024*1024:
            raise APIError('Saved preview pictures reached 64 MiB. Back up and free old social-images files before adding another. Existing drafts are kept.','too_large',413)
        output=folder/(identity[:24]+'-'+uuid.uuid4().hex+'.png')
        # New content-addressed file; failed OCR cannot replace the previous image.
        details=render(file,output,crop,masks)
        image={'digest':hashlib.sha256(output.read_bytes()).hexdigest(),'file':output.name,'source':media.public(attachment),
               'crop':crop,'masks':masks,'automatic_regions':details['automatic_regions'],'boxes':details['boxes'],
               'width':details['width'],'height':details['height'],'reviewed':False,'created_at':now()}
    db.execute('BEGIN IMMEDIATE')
    current=manager.get(db,id,'post_draft')
    if current['version']!=expected_version:
        raise APIError('This draft changed while the image was processing. Reopen it.','conflict',409)
    if social.refresh(db,current)['stage']=='changed':
        raise APIError('This itch returned to work while the image was processing. Review it first.','conflict',409)
    if image:media.references(db,[image['source']['id']])
    current.update(image=image,image_opt_out=source=='none',version=current['version']+1,updated_at=now())
    manager.put(db,'post_draft',current)
    return social.refresh(db,current)


SHOT_TYPES={'.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg','.webp':'image/webp'}


def shot_size(path):
    """Pixel size from a PNG/JPEG header (0,0 when unknown). Avoids decoding whole images."""
    try:
        with path.open('rb') as f:head=f.read(64*1024)
    except OSError:return 0,0
    if head[:8]==b'\x89PNG\r\n\x1a\n' and len(head)>=24:return int.from_bytes(head[16:20],'big'),int.from_bytes(head[20:24],'big')
    if head[:2]==b'\xff\xd8':
        i=2
        while i+9<len(head):
            if head[i]!=0xFF:i+=1;continue
            marker,length=head[i+1],int.from_bytes(head[i+2:i+4],'big')
            if marker in (0xC0,0xC1,0xC2):return int.from_bytes(head[i+7:i+9],'big'),int.from_bytes(head[i+5:i+7],'big')
            i+=2+length
    return 0,0


def evidence_shot(manager,itch):
    """Best landscape proof screenshot saved for this itch under <data>/review-evidence.
    Only that folder is read: the itch's own subfolder plus evidence lines that point inside it."""
    root=(manager.data/'review-evidence').resolve()
    folders=[root/itch['id']]
    for line in itch.get('evidence',[]):
        for word in str(line).replace('"',' ').split():
            try:
                path=Path(word.strip('.,;()')).resolve()
                if path!=root and path.is_relative_to(root):folders.append(path if path.is_dir() else path.parent)
            except (OSError,ValueError):pass
    best,score=None,None
    for folder in dict.fromkeys(folders):
        if not folder.is_dir():continue
        for file in folder.iterdir():
            if file.suffix.lower() not in SHOT_TYPES or not file.is_file():continue
            size=file.stat().st_size
            if not 0<size<=10*1024*1024:continue
            w,h=shot_size(file);name=file.stem.lower()
            # Wide desktop captures read best on a 16:9 card; phone shots are a fallback.
            rank=(w>=h and w>=900,any(k in name for k in ('desktop','live','1366','1440','wide')),w*h,file.stat().st_mtime)
            if score is None or rank>score:best,score=file,rank
    return best


def attach_evidence_shot(social,db,id,expected_version,itch):
    """Use a saved proof screenshot when the itch has no image attachment. Never blocks the card."""
    file=evidence_shot(social.manager,itch)
    if not file:return False
    try:
        raw=file.read_bytes()
        attachment=Media(social.manager).upload(social.manager.config,io.BytesIO(raw),len(raw),'proof-'+file.name,SHOT_TYPES[file.suffix.lower()])['attachment']
        set_image(social,db,id,expected_version,attachment_id=attachment['id'])
        return True
    except (APIError,OSError):
        if db.in_transaction:db.rollback()  # only set_image's unwritten picture step is open here
        return False


def review(social,db,id,expected_version,digest):
    db.execute('BEGIN IMMEDIATE')
    row=social.manager.get(db,id,'post_draft');image=row.get('image')
    if not image or image['digest']!=digest or row['version']!=expected_version:
        raise APIError('The image changed. Review the latest preview.','conflict',409)
    row.update(image={**image,'reviewed':True},version=row['version']+1,updated_at=now())
    social.manager.put(db,'post_draft',row)
    return social.refresh(db,row)


def public_image(manager,image):
    if not image:return None
    return {k:v for k,v in image.items() if k!='file'}


def data_uri(manager,image):
    if not image:return ''
    name=image['file']
    if Path(name).name!=name or not name.endswith('.png'):
        raise APIError('Invalid preview image.')
    path=manager.data/'social-images'/name
    if not path.is_file():raise APIError('The private preview is missing. Add the work image again.','not_found',404)
    data=path.read_bytes()
    if hashlib.sha256(data).hexdigest()!=image['digest']:
        raise APIError('The private preview changed. Create and review it again.','conflict',409)
    return 'data:image/png;base64,'+base64.b64encode(data).decode('ascii')
