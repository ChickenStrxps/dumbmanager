"""Animated completion cards: seeded ASCII scenes encoded as a seamless looping GIF.

social_gif.js draws and encodes the frames inside a throwaway headless Edge that
DumbAPI owns (own temp profile, loopback CDP, no network use). Results are cached
by draft version + image digest + vibe, so every client sees the same card."""
import base64
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from urllib.request import urlopen

from .common import APIError
from .browser_process import BrowserProcess

SCRIPT = Path(__file__).with_name('social_gif.js')
SMOKE = Path(__file__).with_name('ascii_smoke.js')
LOCK = threading.Lock()
CACHE_LIMIT = 96*1024*1024
GIF_LIMIT = 15*1024*1024  # X accepts GIFs up to 15 MB.
THEMES = ('dumb','windows','mac','nvidia','t3','dog','cat','fish','shark','penguin','ohmypi','chill','nature','beach','desert','flow','smoke')
EVENTS = ('greg','flicker','lightning')


def renderer_source():
    return SMOKE.read_text(encoding='utf-8')+'\n'+SCRIPT.read_text(encoding='utf-8')


def renderer_digest():
    return hashlib.sha256(renderer_source().encode('utf-8')).hexdigest()


def identity(row, image, vibe, theme, events):
    script = renderer_digest()
    parts = [script, row['id'], row['version'], row['headline'], row['summary'], row['stage'], row.get('project',''),
             (image or {}).get('digest',''), vibe, theme, events]
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()[:40]


def draw(data_folder, payload, vibe, force, timeout=90, still=False):
    """Render one card in an isolated browser. Returns (gif bytes, meta)."""
    from .browser import installed_browser
    from .browser_cdp import CDP
    executable = installed_browser()
    if not executable:
        raise APIError('Install Microsoft Edge to make animated cards.', 'browser_missing', 503)
    folder = data_folder/'browser-sessions'; folder.mkdir(exist_ok=True)
    profile = Path(tempfile.mkdtemp(prefix='gif-', dir=folder))
    process, browser_ws = None, ''
    try:
        process = BrowserProcess([str(executable), '--headless=new', '--remote-debugging-address=127.0.0.1', '--remote-debugging-port=0',
            '--user-data-dir='+str(profile), '--no-first-run', '--no-default-browser-check', '--disable-background-networking',
            '--disable-extensions', '--disable-sync', '--disable-component-update', '--mute-audio', 'about:blank'])
        deadline, port = time.monotonic()+15, 0
        while time.monotonic() < deadline and not port:
            file = profile/'DevToolsActivePort'
            try: lines = file.read_text().splitlines() if file.is_file() else []
            except OSError: lines = []  # Edge may still be writing it
            if lines:
                if len(lines) >= 2: port, browser_ws = int(lines[0]), f'ws://127.0.0.1:{lines[0]}'+lines[1]
            if process.poll() is not None: raise OSError('Browser exited')
            time.sleep(.1)
        if not port: raise TimeoutError('Browser did not start')
        with urlopen(f'http://127.0.0.1:{port}/json/list', timeout=5) as response:
            page = next(t for t in json.load(response) if t.get('type') == 'page')
        with CDP(page['webSocketDebuggerUrl']) as cdp:
            def run(expression):
                result = cdp.call('Runtime.evaluate', {'expression': expression, 'returnByValue': True})
                if 'exceptionDetails' in result:
                    raise RuntimeError(result['exceptionDetails'].get('text', 'script error'))
                return result.get('result', {}).get('value')
            run(renderer_source()+';0')
            render = ('(async()=>{const s=await DMCardGif.prepare('+json.dumps(payload)+','+json.dumps(vibe)+','+json.dumps(force)+');'
                      'try{s.draw(0);const blob=await new Promise(ok=>s.canvas.toBlob(ok,"image/png"));return {blob,theme:s.p.theme.name,key:s.p.key,events:s.p.events,width:s.canvas.width,height:s.canvas.height,frames:1,seconds:0};}finally{s.close();}})()') if still else (
                      'DMCardGif.make('+json.dumps(payload)+','+json.dumps(vibe)+',()=>false,'+json.dumps(force)+')')
            run('window.__card=null;window.__fail="";'+render+
                '.then(r=>new Promise(ok=>{const f=new FileReader();f.onload=()=>{const {blob,...meta}=r;window.__card={meta,data:String(f.result).split(",")[1]};ok();};f.readAsDataURL(r.blob);}))'
                '.catch(e=>{window.__fail=String(e&&e.message||e)});0')
            end = time.monotonic()+timeout
            while True:
                state = run('window.__fail?"fail:"+window.__fail:window.__card?"done":""')
                if state == 'done': break
                if state: raise RuntimeError(state[5:])
                if time.monotonic() > end: raise TimeoutError('Card render timed out')
                time.sleep(.25)
            meta = run('window.__card.meta'); size = run('window.__card.data.length')
            chunks = [run(f'window.__card.data.slice({i},{i+2_000_000})') for i in range(0, size, 2_000_000)]
        data = base64.b64decode(''.join(chunks), validate=True)
        if not (data.startswith(b'\x89PNG\r\n\x1a\n') if still else data.startswith(b'GIF89a') and data.endswith(b';')):
            raise ValueError('Invalid GIF output')
        return data, meta
    except APIError:
        raise
    except (OSError, ValueError, RuntimeError, TimeoutError, StopIteration, ConnectionError, KeyError) as exc:
        raise APIError('Animated card could not be rendered. The still card still works.', 'gif_unavailable', 503) from exc
    finally:
        if process and process.poll() is None and browser_ws:
            # Graceful close waits for Edge's helper processes, which hold the profile.
            try:
                with CDP(browser_ws) as cdp: cdp.call('Browser.close')
                process.wait(timeout=8)
            except (APIError, OSError, ValueError, ConnectionError, TimeoutError, subprocess.TimeoutExpired): pass
        if process:
            process.close()
        target, base = profile.resolve(), folder.resolve()
        if target.parent == base and target.name.startswith('gif-'):
            for _ in range(20):
                shutil.rmtree(target, ignore_errors=True)
                if not target.exists(): break
                time.sleep(.2)


def prune(folder, keep):
    files = sorted(folder.glob('*.gif'), key=lambda p: p.stat().st_mtime, reverse=True)
    total = 0
    for file in files:
        total += file.stat().st_size
        if total > CACHE_LIMIT and file.stem != keep:
            file.unlink(missing_ok=True); file.with_suffix('.json').unlink(missing_ok=True)


def gif(social, db, id, vibe=0, theme='', events=''):
    """Animated version of the current draft card. Never publishes."""
    from .manager_social_image import data_uri
    manager = social.manager
    original = manager.get(db, id, 'post_draft'); row = social.refresh(db, original)
    if row['stage'] == 'changed':
        raise APIError('This itch is back in progress. Reopen it when it is ready to review or accepted.')
    if theme and theme not in THEMES:
        raise APIError('Unknown card theme.')
    chosen = [e for e in events.split(',') if e] if events else None
    if chosen is not None and any(e not in EVENTS for e in chosen):
        raise APIError('Unknown card event.')
    image = original.get('image')
    key = identity(row, image, vibe, theme, chosen)
    folder = manager.data/'social-gifs'; folder.mkdir(exist_ok=True)
    file, info = folder/(key+'.gif'), folder/(key+'.json')
    with LOCK:  # one browser render at a time; repeat calls reuse the cache
        if file.is_file() and info.is_file():
            data, meta = file.read_bytes(), json.loads(info.read_text(encoding='utf-8'))
            file.touch()
        else:
            payload = {'id': row['id'], 'headline': row['headline'], 'summary': row['summary'], 'stage': row['stage'],
                       'project': row.get('project', ''), 'image': data_uri(manager, image)}
            force = {k: v for k, v in (('theme', theme), ('events', chosen)) if v not in ('', None)}
            data, meta = draw(manager.data, payload, vibe, force)
            if len(data) > GIF_LIMIT:
                raise APIError('Animated card came out over 15 MB. Try another vibe.', 'too_large', 413)
            meta = {'theme': meta.get('theme'), 'key': meta.get('key'), 'events': meta.get('events', []), 'frames': meta.get('frames'),
                    'seconds': meta.get('seconds'), 'width': meta.get('width'), 'height': meta.get('height')}
            temp = file.with_suffix('.tmp'); temp.write_bytes(data); temp.replace(file)
            info.write_text(json.dumps(meta), encoding='utf-8')
            prune(folder, key)
    return {'draft_id': row['id'], 'version': row['version'], 'source_version': row['source_version'], 'stage': row['stage'],
            'digest': (image or {}).get('digest'), 'export_ready': True, 'vibe': vibe, 'requested_theme': theme, **meta,
            'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(), 'filename': 'dumbmanager-'+row['itch_id'][:8]+'.gif',
            'gif': base64.b64encode(data).decode('ascii')}


def set_clipboard(path):
    """Put one GIF file on the Windows clipboard. Ctrl+V in a browser composer
    attaches it as an animated image/gif file (web clipboard APIs only do PNG)."""
    if os.name != 'nt':
        raise APIError('GIF copy needs the Windows clipboard on this PC. Use Save image.', 'clipboard_unavailable', 503)
    env = dict(os.environ, DM_CLIP=str(path))
    script = '$ErrorActionPreference="Stop";Set-Clipboard -LiteralPath $env:DM_CLIP;(Get-Clipboard -Format FileDropList).FullName'
    try:
        result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-STA', '-Command', script], env=env,
                                capture_output=True, text=True, timeout=15, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise APIError('Clipboard did not respond. Try again, or use Save image.', 'clipboard_unavailable', 503) from exc
    if result.returncode or result.stdout.strip().casefold() != str(path).casefold():
        raise APIError('Couldn’t copy the GIF. Try again, or use Save image.', 'clipboard_unavailable', 503)


def copy(social, db, id, expected_version, vibe=0, theme='', events=''):
    """Copy the current animated card to the clipboard as a .gif file. Never publishes."""
    if social.manager.get(db, id, 'post_draft')['version'] != expected_version:
        raise APIError('This draft changed. Reopen it and check the copy.', 'conflict', 409)
    result = gif(social, db, id, vibe, theme, events)
    if result['version'] != expected_version:
        raise APIError('This draft changed. Reopen it and check the copy.', 'conflict', 409)
    # The clipboard references the file, so keep exactly the latest copy on disk.
    folder = social.manager.data/'social-gifs'/'clipboard'; folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob('*.gif'):
        if old.name != result['filename']: old.unlink(missing_ok=True)
    target = folder/result['filename']
    temp = target.with_suffix('.tmp'); temp.write_bytes(base64.b64decode(result['gif'])); temp.replace(target)
    set_clipboard(target.resolve())
    return {'copied': True, 'format': 'image/gif file', 'filename': result['filename'], 'bytes': result['bytes'], 'sha256': result['sha256'],
            'version': result['version'], 'theme': result['theme'], 'events': result['events']}
