"""On-demand installed Edge session. No bundled browser, personal profile or agent runtime."""
import atexit
import base64
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .browser_cdp import CDP
from .browser_credentials import JevKeyStore, valid_key
from .browser_intents import prepare, search_url
from .browser_process import BrowserProcess
from .common import APIError, now

WIDTH, HEIGHT, IDLE_SECONDS = 1100, 700, 15*60
_instances, _instances_lock = {}, threading.Lock()

# Executed in a CDP isolated world. Page scripts cannot read or replace this map.
# Input values, password fields and editable text are excluded from Jev's state.
PAGE_STATE = r'''(() => {
  const store = globalThis.__dmBrowse ||= {nonce: Array.from(crypto.getRandomValues(new Uint32Array(4))).join('-'), nodes: new Map(), ids: new WeakMap(), next: 0};
  const visible = el => {const r=el.getBoundingClientRect(),s=getComputedStyle(el);return r.width>0&&r.height>0&&r.bottom>0&&r.right>0&&r.top<innerHeight&&r.left<innerWidth&&s.visibility==='visible'&&s.display!=='none';};
  store.nodes.clear(); const nodes=[];
  const labelText = label => {if(!label)return '';const copy=label.cloneNode(true);copy.querySelectorAll('input,textarea,select,button,[contenteditable]').forEach(n=>n.remove());return copy.textContent;};
  for(const el of document.querySelectorAll('a[href],button,input,textarea,select,[contenteditable="true"],[role="textbox"],[role="searchbox"],[role="button"],[role="link"],[tabindex="0"]')){
    if(nodes.length>=80)break;
    if(!visible(el)||el.disabled||el.type==='password'||el.type==='hidden')continue;
    let id=store.ids.get(el);if(!id){id='n'+(++store.next);store.ids.set(el,id);}store.nodes.set(id,el);
    const r=el.getBoundingClientRect(),kind=el.tagName.toLowerCase();
    const label=(el.getAttribute('aria-label')||el.getAttribute('placeholder')||labelText(el.labels?.[0])||(kind==='input'||kind==='textarea'||el.isContentEditable?'':el.innerText)||el.getAttribute('title')||kind).replace(/\s+/g,' ').trim().slice(0,160);
    const editable=!el.readOnly&&(kind==='textarea'||el.isContentEditable||(kind==='input'&&['text','search','email','url','tel'].includes(el.type)));
    const options=kind==='select'?Array.from(el.options).filter(o=>!o.disabled).slice(0,80).map(o=>({value:o.value.slice(0,200),label:o.text.slice(0,160)})):undefined;
    nodes.push({id,kind,label,editable,input_type:kind==='input'?el.type:'',checked:['checkbox','radio'].includes(el.type)?el.checked:undefined,options,x:Math.round(Math.max(0,r.left)+(Math.min(innerWidth,r.right)-Math.max(0,r.left))/2),y:Math.round(Math.max(0,r.top)+(Math.min(innerHeight,r.bottom)-Math.max(0,r.top))/2)});
  }
  store.contentIds ||= new WeakMap();store.contentNext ||= 0;
  const parts=[], groups=new Map(), walker=document.createTreeWalker(document.body||document.documentElement,NodeFilter.SHOW_TEXT);let node,count=0,size=0;
  while((node=walker.nextNode())&&count++<4000&&size<8000){
    const p=node.parentElement;if(!p||p.closest('script,style,noscript,input,textarea,[contenteditable]')||!visible(p))continue;
    const range=document.createRange();range.selectNodeContents(node);
    const rects=Array.from(range.getClientRects()).filter(r=>r.width>0&&r.height>0&&r.bottom>0&&r.right>0&&r.top<innerHeight&&r.left<innerWidth);
    if(!rects.length)continue;
    const text=node.textContent.replace(/\s+/g,' ').trim().slice(0,8000-size);if(!text)continue;
    parts.push(text);size+=text.length;
    const block=p.closest('p,li,blockquote,pre,h1,h2,h3,h4,h5,h6,td,th')||p;
    if(!groups.has(block)&&groups.size>=48)continue;
    if(!groups.has(block)){let id=store.contentIds.get(block);if(!id){id='p'+(++store.contentNext);store.contentIds.set(block,id);}groups.set(block,{id,text:'',left:innerWidth,top:innerHeight,right:0,bottom:0});}
    const group=groups.get(block);group.text=(group.text+' '+text).trim().slice(0,900);
    for(const r of rects){group.left=Math.min(group.left,Math.max(0,r.left));group.top=Math.min(group.top,Math.max(0,r.top));group.right=Math.max(group.right,Math.min(innerWidth,r.right));group.bottom=Math.max(group.bottom,Math.min(innerHeight,r.bottom));}
  }
  const passages=Array.from(groups.values(),g=>({id:g.id,text:g.text,bounds:{x:Math.floor(g.left),y:Math.floor(g.top),width:Math.ceil(g.right-g.left),height:Math.ceil(g.bottom-g.top)}}));
  return {url:location.href,title:document.title.slice(0,250),nonce:store.nonce,text:parts.join(' ').slice(0,8000),passages,nodes,scrollY:Math.round(scrollY),height:innerHeight,width:innerWidth};
})()'''


def installed_browser():
    for folder in (os.environ.get('PROGRAMFILES(X86)', r'C:\Program Files (x86)'), os.environ.get('PROGRAMFILES', r'C:\Program Files')):
        path = Path(folder)/'Microsoft/Edge/Application/msedge.exe'
        if path.is_file(): return path
    return None


def web_url(value):
    value = value.strip()
    if value == 'about:blank': return value
    if ('://' in value and not value.startswith(('http://', 'https://'))) or value.split(':',1)[0].lower() in ('file','javascript','data','chrome','edge','about','ws','wss'):
        raise APIError('Use an HTTP or HTTPS page address.')
    if not value.startswith(('http://', 'https://')): value = 'https://'+value
    try:
        url = urlsplit(value)
        if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password or any(ord(c)<33 for c in value): raise ValueError()
        _ = url.port
    except ValueError:
        raise APIError('Use an HTTP or HTTPS address without embedded credentials.') from None
    return value


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise APIError('The service redirected unexpectedly.', 'browser_unavailable', 503)


def service_json(url, payload=None, key='', timeout=10):
    headers = {'Content-Type': 'application/json'}
    if key: headers['Authorization'] = 'Bearer '+key
    request = Request(url, data=json.dumps(payload).encode() if payload is not None else None, headers=headers)
    with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=timeout) as response:
        raw = response.read(1024*1024+1)
        if len(raw)>1024*1024: raise ValueError('Oversized reply')
        return json.loads(raw)


class Browser:
    def __init__(self, config):
        self.config, self.lock = config, threading.RLock()
        self.process = self.profile = None
        self.port, self.browser_ws, self.tab = None, '', ''
        self.user_agent = ''
        self.last, self.snapshot_id, self.observed, self.suggestion = 0, '', None, None
        self.credentials = JevKeyStore(config.data)
        self.key, self.key_saved, self.key_notice = '', False, ''
        try:
            saved = self.credentials.load()
            self.key = saved if saved is not None else os.environ.get('TYPESAFE_API_KEY', '')
            if not valid_key(self.key): self.key = ''
            self.key_saved = bool(saved)
        except APIError as exc:
            self.key_notice = str(exc)
        self.width, self.height = WIDTH, HEIGHT
        self.expiry = None
        self.cdp, self.cdp_tab = None, ''
        self.cdp_size, self.frame_id, self.frame_document = None, '', None
        self.frames = {}
        atexit.register(self.stop)

    def status(self):
        from .typing_generator import status as mercury_status
        with self.lock:
            running = self.process is not None and self.process.poll() is None
            return {'running': running, 'installed': installed_browser() is not None, 'jev_connected': bool(self.key),
                    'key_saved': self.key_saved, 'key_notice': self.key_notice, 'mercury_connected': mercury_status(self.config)['configured'],
                    'key_storage_available': os.name == 'nt',
                    'idle_seconds': IDLE_SECONDS, 'note': 'Separate temporary session. Stops after 15 minutes without a browser action.'}

    def connect(self, api_key=''):
        with self.lock:
            if not valid_key(api_key):
                raise APIError('Enter a TypeSafe API key without whitespace.')
            self.credentials.save(api_key)
            self.key = api_key
            self.key_saved, self.key_notice = bool(api_key), ''
            return {'jev_connected': bool(api_key), 'key_saved': self.key_saved, 'key_notice': '',
                    'note': 'Key saved with Windows encryption. Ready after restarts; verified on your next Ask Jev.' if api_key else 'Jev disconnected. Saved key forgotten.'}

    def _http(self, route):
        return service_json(f'http://127.0.0.1:{self.port}'+route)

    def _touch(self):
        if not self.process or self.process.poll() is not None:
            raise APIError('Start the browser first. The temporary session may have expired.', 'browser_stopped', 409)
        self.last = time.monotonic()

    def start(self, url='about:blank'):
        url = web_url(url)
        with self.lock:
            if self.process and self.process.poll() is None:
                return self.snapshot()
            self.stop()
            executable = installed_browser()
            if not executable: raise APIError('Install Microsoft Edge to use Browse.', 'browser_missing', 503)
            folder = self.config.data/'browser-sessions'; folder.mkdir(exist_ok=True)
            self.profile = Path(tempfile.mkdtemp(prefix='owned-', dir=folder))
            try:
                self.process = BrowserProcess([str(executable), '--headless=new', '--remote-debugging-address=127.0.0.1',
                    '--remote-debugging-port=0', '--user-data-dir='+str(self.profile), '--window-size=1100,700',
                    '--no-first-run', '--no-default-browser-check', '--disable-background-networking', '--disable-extensions',
                    '--disable-sync', '--disable-component-update', '--disable-features=msEdgeSidebarV2', '--block-new-web-contents', 'about:blank'])
                deadline = time.monotonic()+30
                ready = False
                while time.monotonic()<deadline:
                    if self.process.poll() is not None: raise OSError('Browser exited')
                    try:
                        file = self.profile/'DevToolsActivePort'
                        lines = file.read_text().splitlines() if file.is_file() else []
                        if len(lines)>=2:
                            self.port = int(lines[0]); self.browser_ws = f'ws://127.0.0.1:{self.port}'+lines[1]
                            with CDP(self.browser_ws) as cdp:
                                self.user_agent = cdp.call('Browser.getVersion')['userAgent'].replace('HeadlessChrome/', 'Chrome/')
                                cdp.call('Browser.setDownloadBehavior', {'behavior': 'deny'})
                            tabs = self._tabs()
                            if tabs:
                                self.tab = tabs[0]['id'];ready = True;break
                    except (OSError, ValueError, KeyError, APIError):
                        pass
                    time.sleep(.1)
                if not ready: raise TimeoutError('Browser debugging endpoint was not ready')
                self.last = time.monotonic(); self.expiry = threading.Event()
                threading.Thread(target=self._idle, args=(self.expiry,), daemon=True).start()
                if url != 'about:blank': return self.action('navigate', url=url)
                return self.snapshot()
            except BaseException as exc:
                self.stop()
                if isinstance(exc, APIError): raise
                raise APIError('Edge could not start its isolated session. Try again.', 'browser_unavailable', 503) from None

    def _idle(self, event):
        while not event.wait(30):
            with self.lock:
                if time.monotonic()-self.last >= IDLE_SECONDS:
                    self.stop(); return

    def stop(self):
        with self.lock:
            if self.expiry: self.expiry.set(); self.expiry = None
            if self.cdp: self.cdp.close(); self.cdp, self.cdp_tab = None, ''
            if self.process:
                try:
                    if self.process.poll() is None:
                        try:
                            with CDP(self.browser_ws) as cdp: cdp.call('Browser.close')
                        except (APIError, OSError, ValueError, ConnectionError, TimeoutError): pass
                        try: self.process.wait(timeout=3)
                        except subprocess.TimeoutExpired: pass
                finally:
                    # Also reap helpers after the root process has already exited.
                    self.process.close()
                    self.process = None
            if self.profile:
                # Only the concrete directory created by this object; never a user profile.
                target, base = self.profile.resolve(), (self.config.data/'browser-sessions').resolve()
                if target.parent == base and target.name.startswith('owned-'):
                    shutil.rmtree(target, ignore_errors=True)
                self.profile = None
            self.port, self.browser_ws, self.tab, self.snapshot_id = None, '', '', ''
            self.observed = self.suggestion = None
            self.frames.clear(); self.frame_id = ''; self.frame_document = None
            return {'running': False, 'jev_connected': bool(self.key)}

    def _tabs(self):
        return [t for t in self._http('/json/list') if t.get('type')=='page'][:8]

    @contextmanager
    def _page(self, touch=True):
        if touch: self._touch()
        elif not self.process or self.process.poll() is not None:
            raise APIError('Browser is off. Start a session.', 'browser_stopped', 409)
        tabs = self._tabs()
        target = next((t for t in tabs if t['id']==self.tab), None)
        if not target and tabs: target = tabs[0]; self.tab = target['id']
        if not target: raise APIError('No browser tab is open. Start a new session.', 'browser_stopped', 409)
        if not self.cdp or self.cdp_tab != self.tab:
            if self.cdp: self.cdp.close()
            self.cdp = CDP(target['webSocketDebuggerUrl']); self.cdp_tab = self.tab
            # Keep the installed browser's regular identity for website compatibility.
            self.cdp.call('Emulation.setUserAgentOverride', {'userAgent': self.user_agent})
            self.cdp.call('Page.enable')
            self.cdp.call('Page.bringToFront')
            self.cdp_size = None
        try:
            # Emulation is scoped to the attached CDP client, which stays alive for this tab.
            if self.cdp_size != (self.width, self.height):
                self.cdp.call('Emulation.setDeviceMetricsOverride', {'width': self.width, 'height': self.height, 'deviceScaleFactor': 1, 'mobile': False})
                self.cdp_size = (self.width, self.height)
            yield self.cdp
        except (OSError, ValueError, KeyError, ConnectionError):
            if self.cdp: self.cdp.close(); self.cdp, self.cdp_tab = None, ''
            raise

    def _world(self, cdp):
        frame = cdp.call('Page.getFrameTree')['frameTree']['frame']['id']
        return cdp.call('Page.createIsolatedWorld', {'frameId': frame, 'worldName': 'DumbManager Browse'})['executionContextId']

    def _read(self, cdp):
        world = self._world(cdp)
        result = cdp.call('Runtime.evaluate', {'expression': PAGE_STATE, 'contextId': world, 'returnByValue': True})
        value = result.get('result', {}).get('value')
        if not isinstance(value, dict) or 'nodes' not in value:
            raise APIError('The page is still changing. Refresh the preview.', 'browser_changed', 409)
        return value

    @staticmethod
    def _fingerprint(value):
        # A clock/ticker changing text must not break manual browsing. Document identity,
        # address, scroll position, control labels and geometry still have to match.
        return hashlib.sha256(json.dumps({k:v for k,v in value.items() if k not in ('text','passages')}, sort_keys=True).encode()).hexdigest()

    def _fresh(self, cdp, snapshot):
        value = self._read(cdp)
        if not snapshot or snapshot != self.snapshot_id or not self.observed or self._fingerprint(value)!=self._fingerprint(self.observed):
            self.snapshot_id = ''; self.suggestion = None
            raise APIError('The page changed. Refresh before acting on it.', 'browser_changed', 409)
        return value

    def _document(self, cdp):
        frame = cdp.call('Page.getFrameTree')['frameTree']['frame']
        return (self.tab, frame.get('loaderId', frame['id']), frame['url'], self.width, self.height)

    def _visual(self, cdp):
        document = self._document(cdp)
        image = cdp.call('Page.captureScreenshot', {'format':'jpeg', 'quality':65, 'captureBeyondViewport':False})['data']
        self.frame_id, self.frame_document = uuid.uuid4().hex, document
        self.frames[self.frame_id] = document
        while len(self.frames)>8: self.frames.pop(next(iter(self.frames)))
        return {'running':True, 'frame':self.frame_id, 'tab':self.tab, 'url':document[2], 'image':image,
                'mime':'image/jpeg', 'width':self.width, 'height':self.height, 'time':now()}

    def frame(self):
        """Lightweight pixels only. Does not extend idle lifetime or invalidate AI grounding."""
        with self.lock:
            try:
                with self._page(touch=False) as cdp: return self._visual(cdp)
            except (OSError, ValueError, KeyError, ConnectionError):
                raise APIError('Preview disconnected. Refresh to reconnect.', 'browser_unavailable', 503) from None

    def interact(self, operation, frame, x=0, y=0, delta_x=0, delta_y=0, text='', key='Enter'):
        """Explicit human input against the displayed document, independent of DOM animation.

        AI moves continue through action/apply and their full fresh-control check.
        A frame is single-use for input. Never retry an uncertain dispatch.
        """
        with self.lock:
            try:
                with self._page() as cdp:
                    if not frame or self.frames.get(frame) != self._document(cdp):
                        raise APIError('Page moved to another document. Check the refreshed preview.', 'browser_changed', 409)
                    if operation not in ('click','scroll','type','key'): raise APIError('Unsupported manual input.')
                    if not (0 <= x < self.width and 0 <= y < self.height): raise APIError('Point inside the page preview.')
                    if operation == 'key' and key not in ('Enter','Tab','Escape','Backspace','Delete','ArrowUp','ArrowDown','ArrowLeft','ArrowRight','Home','End','PageUp','PageDown',' ','SelectAll'):
                        raise APIError('Unsupported browser key.')
                    if len(text)>4000 or abs(delta_x)>1400 or abs(delta_y)>1400: raise APIError('Input exceeds browser bounds.')
                    self.frame_id = ''; self.frames.clear(); self.suggestion = None
                    if operation == 'click':
                        cdp.call('Input.dispatchMouseEvent', {'type':'mouseMoved','x':x,'y':y})
                        for event in ('mousePressed','mouseReleased'):
                            cdp.call('Input.dispatchMouseEvent', {'type':event,'x':x,'y':y,'button':'left','clickCount':1})
                    elif operation == 'scroll':
                        cdp.call('Input.dispatchMouseEvent', {'type':'mouseWheel','x':x,'y':y,'deltaX':delta_x,'deltaY':delta_y})
                    elif operation == 'type': cdp.call('Input.insertText', {'text':text})
                    else:
                        keys={'Enter':13,'Tab':9,'Escape':27,'Backspace':8,'Delete':46,'ArrowUp':38,'ArrowDown':40,'ArrowLeft':37,'ArrowRight':39,'Home':36,'End':35,'PageUp':33,'PageDown':34,' ':32,'SelectAll':65}
                        for event in ('keyDown','keyUp'):
                            cdp.call('Input.dispatchKeyEvent', {'type':event,'key':'a' if key=='SelectAll' else key,'windowsVirtualKeyCode':keys[key],
                                'modifiers':2 if key=='SelectAll' else 0, **({'text':'\r' if key=='Enter' else ' '} if key in ('Enter',' ') and event=='keyDown' else {})})
                return self.frame()
            except (OSError, ValueError, KeyError, ConnectionError):
                self.frame_id = ''; self.frames.clear(); self.suggestion = None
                raise APIError('Input response lost. Check the preview before trying again.', 'browser_unavailable', 503) from None

    def snapshot(self):
        with self.lock:
            try:
                with self._page() as cdp:
                    cdp.call('Page.enable')
                    value = self._read(cdp)
                    visual = self._visual(cdp)
                self.observed, self.snapshot_id, self.suggestion = value, uuid.uuid4().hex, None
                return {**visual, 'snapshot': self.snapshot_id, 'url': value['url'], 'title': value['title'],
                        'tabs': [{'id': t['id'], 'title': t.get('title', '')[:120], 'url': t.get('url', '')[:2000]} for t in self._tabs()],
                        'nodes': value['nodes'], 'jev_connected': bool(self.key),
                        'viewport_token': hashlib.sha256(json.dumps({k:value[k] for k in ('url','text','nodes','scrollY')},sort_keys=True).encode()).hexdigest()}
            except (OSError, ValueError, KeyError, ConnectionError):
                raise APIError('Browser preview unavailable. Try Refresh or restart the session.', 'browser_unavailable', 503) from None

    def _navigate(self, cdp, url):
        result=cdp.call('Page.navigate', {'url': web_url(url)})
        if result.get('errorText'):
            status=None
            if result['errorText']=='net::ERR_HTTP_RESPONSE_CODE_FAILURE':
                try:status=re.search(r'\bHTTP ERROR (\d{3})\b',self._read(cdp)['text'])
                except APIError:pass
            message=f'This website returned HTTP {status[1]}. The destination was resolved, but the site refused to open.' if status else 'This website could not load. Check the connection and try Refresh.'
            raise APIError(message, 'browser_navigation', 409)

    def action(self, operation, snapshot='', url='', tab='', node='', text='', x=0, y=0, key='Enter'):
        with self.lock:
            try:
                self._touch()
                if operation == 'viewport':
                    if text not in ('phone', 'desktop'): raise APIError('Choose phone or desktop.')
                    self.width, self.height = (390, 600) if text=='phone' else (WIDTH, HEIGHT)
                elif operation in ('new_tab', 'switch_tab', 'close_tab'):
                    tabs = self._tabs()
                    if operation == 'new_tab':
                        if len(tabs)>=8: raise APIError('Keep up to eight tabs open.')
                        destination=web_url(url or 'about:blank')
                        with CDP(self.browser_ws) as cdp: self.tab = cdp.call('Target.createTarget', {'url': 'about:blank'})['targetId']
                        with self._page() as cdp:self._navigate(cdp,destination)
                    else:
                        if tab not in [t['id'] for t in tabs]: raise APIError('That tab is no longer open.', 'browser_changed', 409)
                        if operation == 'close_tab':
                            if len(tabs)==1: raise APIError('Keep one tab open, or stop the browser.')
                            with CDP(self.browser_ws) as cdp: cdp.call('Target.closeTarget', {'targetId': tab})
                        self.tab = tab if operation=='switch_tab' else next(t['id'] for t in tabs if t['id']!=tab)
                else:
                    with self._page() as cdp:
                        cdp.call('Page.enable')
                        if operation == 'navigate':
                            self._navigate(cdp,url)
                        elif operation == 'reload': cdp.call('Page.reload')
                        elif operation in ('back', 'forward'):
                            history = cdp.call('Page.getNavigationHistory'); index = history['currentIndex']+(-1 if operation=='back' else 1)
                            if 0 <= index < len(history['entries']): cdp.call('Page.navigateToHistoryEntry', {'entryId': history['entries'][index]['id']})
                        else:
                            value = self._fresh(cdp, snapshot)
                            if operation in ('click', 'node'):
                                if operation == 'node':
                                    target = next((n for n in value['nodes'] if n['id']==node), None)
                                    if not target: raise APIError('That element is no longer visible.', 'browser_changed', 409)
                                    x, y = target['x'], target['y']
                                if not (0<=x<self.width and 0<=y<self.height): raise APIError('Click inside the page preview.')
                                for event in ('mousePressed', 'mouseReleased'):
                                    cdp.call('Input.dispatchMouseEvent', {'type': event, 'x': x, 'y': y, 'button': 'left', 'clickCount': 1})
                            elif operation in ('select','check'):
                                target = next((n for n in value['nodes'] if n['id']==node), None)
                                if not target: raise APIError('That control is no longer visible.', 'browser_changed',409)
                                if operation=='select' and (target['kind']!='select' or text not in [o['value'] for o in target.get('options',[])]): raise APIError('Choose one of the visible select options.')
                                if operation=='check' and (target.get('input_type') not in ('checkbox','radio') or text not in ('true','false') or target.get('input_type')=='radio' and text=='false'): raise APIError('Choose a valid checkbox or radio state.')
                                result=cdp.call('Runtime.evaluate',{'contextId':self._world(cdp),'returnByValue':True,
                                    'expression':'(() => {const el=globalThis.__dmBrowse.nodes.get('+json.dumps(node)+');if(!el||!el.isConnected||el.disabled)return false;'
                                    +('el.value='+json.dumps(text)+';el.dispatchEvent(new Event("input",{bubbles:true}));el.dispatchEvent(new Event("change",{bubbles:true}));' if operation=='select' else 'if(el.checked!=='+('true' if text=='true' else 'false')+')el.click();')
                                    +'return true;})()'}).get('result',{}).get('value')
                                if result is not True:raise APIError('The control changed. Refresh before acting.', 'browser_changed',409)
                            elif operation == 'fill':
                                target = next((n for n in value['nodes'] if n['id']==node and n.get('editable')), None)
                                if not target: raise APIError('That text field is no longer editable.', 'browser_changed', 409)
                                focused = cdp.call('Runtime.evaluate', {'contextId':self._world(cdp), 'returnByValue':True,
                                    'expression': '(() => {const el=globalThis.__dmBrowse.nodes.get('+json.dumps(node)+');'
                                        'if(!el||!el.isConnected||el.disabled||el.readOnly)return false;el.focus({preventScroll:true});'
                                        'if(el.isContentEditable){const range=document.createRange();range.selectNodeContents(el);'
                                        'const selection=getSelection();selection.removeAllRanges();selection.addRange(range);}else el.select();'
                                        'return document.activeElement===el;})()'}).get('result',{}).get('value')
                                if focused is not True: raise APIError('Could not focus that field. Refresh the preview.', 'browser_changed', 409)
                                cdp.call('Input.insertText', {'text':text})
                            elif operation == 'type': cdp.call('Input.insertText', {'text': text})
                            elif operation == 'key':
                                keys = {'Enter':13,'Tab':9,'Escape':27,'Backspace':8,'Delete':46,'ArrowUp':38,'ArrowDown':40,'ArrowLeft':37,'ArrowRight':39,'Home':36,'End':35,' ':32,'SelectAll':65}
                                if key not in keys: raise APIError('Unsupported browser key.')
                                for event in ('keyDown', 'keyUp'):
                                    cdp.call('Input.dispatchKeyEvent', {'type':event,'key':'a' if key=='SelectAll' else key,'windowsVirtualKeyCode':keys[key],'modifiers':2 if key=='SelectAll' else 0, **({'text':'\r'} if key=='Enter' and event=='keyDown' else {})})
                            elif operation in ('scroll_up', 'scroll_down'):
                                cdp.call('Input.dispatchMouseEvent', {'type':'mouseWheel','x':self.width/2,'y':self.height/2,'deltaX':0,'deltaY':-450 if operation=='scroll_up' else 450})
                            else: raise APIError('Unsupported browser action.')
                # Event-driven pages often settle just after CDP acknowledges input. No ongoing poll.
                time.sleep(.25)
                return self.snapshot()
            except (OSError, ValueError, KeyError, ConnectionError):
                self.snapshot_id = ''; self.suggestion = None
                raise APIError('Browser action unconfirmed. Refresh before trying again.', 'browser_unavailable', 503) from None

    def suggest(self, goal, snapshot, history=None):
        with self.lock:
            self.suggestion = None
            if not self.key: raise APIError('Connect a TypeSafe key to Ask Jev. Manual browsing is ready.', 'jev_not_connected', 409)
            if not goal.strip(): raise APIError('Give Jev a goal first.')
            # Judging a new goal always observes the current page. Only execution
            # requires the old target to remain unchanged.
            preview = self.snapshot(); snapshot = preview['snapshot']; value = self.observed
            questions, choices, plans, spans, destinations = prepare(goal, value | {'tab':self.tab}, self._tabs(), web_url, planning=history is not None)
            passages = {p['id']:p for p in value.get('passages',[])}
            payload = {'model':'jev-latest','state':{'goal':goal,'page':{'url':value['url'],'title':value['title'],'visible_text':value['text'],
                       'passages':{key:p['text'] for key,p in passages.items()},'scope':'Current viewport only; not the entire website.'},'actions':choices},
                       'questions':questions}
            if history is not None:payload['state']['completed_moves']=history
            started = time.monotonic()
            try:
                response = service_json('https://api.typesafe.ai/v1/systemone', payload, self.key, timeout=15)
                used = [];judgments = {}
                def pick(name):
                    answer = response['answers'][name]
                    if not isinstance(answer,dict): raise ValueError()
                    choice, confidence, probabilities = answer['choice'], answer['confidence'], answer['probabilities']
                    options = questions[name]['criteria']
                    if answer.get('type')!='choice' or not isinstance(choice,str) or choice not in options or not isinstance(probabilities,dict) or choice not in probabilities: raise ValueError()
                    for number in [confidence, *probabilities.values()]:
                        if isinstance(number,bool) or not isinstance(number,(int,float)) or not math.isfinite(number) or not 0<=number<=1: raise ValueError()
                    if set(probabilities)-set(options): raise ValueError()
                    used.append((confidence,probabilities[choice]));judgments[name]=(confidence,probabilities[choice]); return choice
                choice = pick('next'); action = plans.get(choice); detail = ''; found = None; continuation = False
                label = choices[choice]['label'] if isinstance(choices[choice],dict) else choices[choice]
                if choice == 'read':
                    passage = pick('passage')
                    label = 'Nothing matching in the visible text. Try scrolling, then ask again.'
                    if passage != 'none':
                        found = passages[passage];detail = found['text'];label = 'Here’s my pick.'
                    else:
                        follow = pick('continuation')
                        if follow != 'stop':
                            action = {'operation':follow}; continuation = True
                            label = 'Looking a little further…'
                elif choice in ('navigate','search'):
                    site = pick('destination')
                    if site == 'none':
                        choice, label = 'none', 'Name the website or paste its address in your goal.'
                    else:
                        destination = destinations[site]; url = destination['url']
                        label = 'Open '+destination['label']
                        if choice == 'search':
                            query = pick('text')
                            if query == 'none': choice, label = 'none', 'Tell Jev what to search for.'
                            else:
                                url = search_url(destination,spans[query]); label = 'Search '+destination['label']+' for “'+spans[query][:100]+'”'
                        if choice != 'none':
                            action = {'operation':'navigate','url':web_url(url)}; detail = action['url']
                elif choice.startswith('fill_'):
                    text = pick('text')
                    if text == 'none': choice, label = 'none', 'Include the exact text you want entered.'
                    else:
                        action = action | {'text':spans[text]}; label = 'Fill '+label+' with “'+spans[text][:100]+'”'; detail = spans[text]
                if choice == 'none': action = None
                if choice == 'done':label = 'Done · Check the page above.'
                if choice == 'blocked':label = 'This site needs a manual check. Complete it in the page above, then ask again.'
                confidence, probability = min(c for c,_ in used), min(p for _,p in used)
                routing=[judgments['next']]+([judgments['destination']] if choice in ('navigate','search') else [])
                routing_confidence,routing_probability=min(c for c,_ in routing),min(p for _,p in routing)
            except HTTPError as exc:
                message = 'TypeSafe rejected the key. Reconnect Jev.' if exc.code in (401,403) else 'TypeSafe is rate limited. Try again later.' if exc.code==429 else 'TypeSafe is unavailable. Manual browsing still works.'
                exc.close()
                raise APIError(message, 'jev_unavailable', 503) from None
            except (OSError, URLError, ValueError, KeyError, TypeError):
                raise APIError('Jev could not return a valid move. Nothing was changed.', 'jev_unavailable', 503) from None
            if choice == 'read':
                # Refresh the screenshot too: return source text only while it is still
                # present. Other text (such as a clock) need not invalidate browsing.
                preview = self.snapshot()
                current = {p['id']:p for p in self.observed['passages']}
                fresh = current.get(found['id']) if found else None
                changed = (not fresh or fresh['text'] != found['text']) if found else {k:p['text'] for k,p in current.items()} != {k:p['text'] for k,p in passages.items()}
                if self.observed['nonce'] != value['nonce'] or self.observed['url'] != value['url'] or changed:
                    raise APIError('The page text changed while Jev was reading. Refresh and ask again.', 'browser_changed', 409)
                found = fresh;snapshot = preview['snapshot']
            self.suggestion = {'id':uuid.uuid4().hex,'snapshot':snapshot,'choice':choice,'label':label,'detail':detail,'action':action,
                               'kind':'passage' if choice=='read' else 'action','continuation':continuation,
                               'confidence':confidence,'probability':probability,'milliseconds':round((time.monotonic()-started)*1000),'model':str(response.get('model','jev-latest'))[:80]}
            if history is not None:self.suggestion.update(routing_confidence=routing_confidence,routing_probability=routing_probability)
            if preview:self.suggestion['preview'] = preview
            if found:self.suggestion.update(source={'title':value['title'],'url':value['url'],'scope':'Visible page text'},bounds=found['bounds'])
            return self.suggestion

    def plan(self, goal, snapshot, history='[]'):
        from .browser_mercury import propose, history_moves, FINAL
        with self.lock:
            if not goal.strip():raise APIError('Give Mercury a goal first.')
            clean=history_moves(history)
            self.suggestion=None
            started=time.monotonic()
            # Jev selects grounded controls/source words in one batched request.
            # Reserve text generation for steps that actually need it. Mercury's
            # cooldown never prevents a new navigation/search/control judgment.
            if self.key:
                try:
                    selected=self.suggest(goal,snapshot,history=clean)
                except APIError as exc:
                    if exc.code!='jev_unavailable':raise
                else:
                    # Overlapping query spans can split probability between equally
                    # useful user-word searches. Judge navigation intent/destination
                    # separately; literal field fills still use all argument judgments.
                    search=selected['choice']=='search'
                    confidence=selected.get('routing_confidence',selected['confidence']) if search else selected['confidence']
                    probability=selected.get('routing_probability',selected['probability']) if search else selected['probability']
                    if selected['choice'] not in ('generate','none') and confidence>=.6 and probability>=.6:
                        action=selected['action']
                        target=next((n for n in self.observed['nodes'] if action and n['id']==action.get('node')),None)
                        review=bool(action and (action['operation']=='key' and action.get('key')=='Enter' or
                                    action['operation']=='node' and target and FINAL.search(target['label'])))
                        selected.update(engine='jev-latest',operation=action['operation'] if action else selected['choice'],needs_review=review)
                        return selected
            preview=self.snapshot()
            self.suggestion=None
            try:
                plan=propose(self.config,goal,self.observed,self._tabs(),history)
            except APIError as exc:
                if exc.code=='mercury_rate_limited' and self.key:
                    exc.code='mercury_generation_limited'
                    exc.args=('Mercury is waiting to generate text. Navigation, searches and page controls still work with Jev. Your goal is kept.',)
                raise
            self.suggestion={'id':uuid.uuid4().hex,'snapshot':preview['snapshot'],**plan,
                'choice':plan['operation'],'kind':'action' if plan['action'] else 'answer','detail':'',
                'milliseconds':round((time.monotonic()-started)*1000),'preview':preview,'continuation':False}
            return self.suggestion

    def apply(self, suggestion, reviewed=False):
        with self.lock:
            saved = self.suggestion
            if not saved or saved['id'] != suggestion: raise APIError('Ask Jev again for a fresh suggestion.', 'browser_changed', 409)
            if not saved['action']: raise APIError('No action was suggested.')
            if saved.get('needs_review') and not reviewed:raise APIError('Review this final action before running it.', 'browser_review',409)
            # Enter authorizes one requested move. Only a pre-dispatch rejection
            # is retryable; uncertain execution must never be replayed.
            try:
                with self._page() as cdp: self._fresh(cdp,saved['snapshot'])
            except APIError as exc:
                if exc.code == 'browser_changed':
                    raise APIError('Page updated; observing it again before acting.', 'browser_stale', 409) from None
                raise
            self.suggestion = None
            return self.action(snapshot=saved['snapshot'], **saved['action'])


def instance(config):
    with _instances_lock:
        key = str(config.data)
        if key not in _instances: _instances[key] = Browser(config)
        return _instances[key]


def close_instance(config):
    with _instances_lock:
        browser = _instances.pop(str(config.data), None)
    if browser:
        browser.stop()
        atexit.unregister(browser.stop)


def definitions():
    from .registry import capability, integer, string
    def cap(name, description, props=None, required=(), write=False):
        item = capability('browser.'+name, 'dumbmanager', description, props, required, tags=('browser','jev','workflow'))
        if write: item['mode']='action'
        return item
    return [cap('status','Read installed-browser and Jev connection availability without starting anything.'),
        cap('start','Start an isolated temporary installed Edge session on demand. No personal browser profile; downloads disabled; stops after 15 idle minutes.',{'url':string(default='about:blank')},write=True),
        cap('stop','Stop this host process owned browser session and remove its temporary profile.',write=True),
        cap('snapshot','Read a viewport screenshot and bounded visible controls from this host owned browser.'),
        cap('frame','Read lightweight live pixels from an existing owned browser. Does not start it, extend idle lifetime or invoke models.'),
        cap('interact','Send explicit manual click, scroll, typing or key input against a single-use displayed frame. AI moves use action/apply freshness checks.',{
            'operation':string(enum=['click','scroll','type','key']), 'frame':string(),
            'x':integer(0,0,WIDTH-1),'y':integer(0,0,HEIGHT-1), 'delta_x':integer(0,-1400,1400),'delta_y':integer(0,-1400,1400),
            'text':string(default='',maxLength=4000),'key':string(default='Enter',**{'x-ai-sensitive':False})},('operation','frame'),write=True),
        cap('connect','Save a TypeSafe API key with current-user Windows encryption, or forget it with an empty key. Never returned to callers.',{'api_key':string(default='',maxLength=500)},write=True),
        cap('action','Perform one explicit browser action. Coordinates and typing require a fresh snapshot. No arbitrary CDP, JavaScript or shell.',{
            'operation':string(enum=['navigate','reload','back','forward','new_tab','switch_tab','close_tab','viewport','click','node','fill','select','check','type','key','scroll_up','scroll_down']),
            'snapshot':string(default=''),'url':string(default=''),'tab':string(default=''),'node':string(default=''),'text':string(default='',maxLength=4000),
            'x':integer(0,0,WIDTH-1),'y':integer(0,0,HEIGHT-1),'key':string(default='Enter',**{'x-ai-sensitive':False})},('operation',),write=True),
        cap('suggest','Observe fresh page text/labels and send the goal to TypeSafe. Choose a fixed move or source quote; an explicit keep-looking request may offer a scroll continuation. Does not execute.',{'goal':string(maxLength=2000),'snapshot':string()},('goal','snapshot')),
        cap('plan','Ask saved Mercury 3 for one grounded page move or answer, with generated field text. Does not execute. Review consequential moves before applying.',{'goal':string(maxLength=2000),'snapshot':string(),'history':string(default='[]',maxLength=12000)},('goal','snapshot')),
        cap('apply','Apply one user-approved Jev suggestion only if the page is still fresh.',{'suggestion':string(),'reviewed':{'type':'boolean','default':False}},('suggestion',),write=True)]
