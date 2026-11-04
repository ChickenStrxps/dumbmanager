"""Bounded public discovery and a local package shelf; never edits an MCP client."""
import json
import os
from pathlib import Path
import platform
import shutil
import threading
import urllib.parse
import urllib.request
import uuid

from .common import APIError, atomic_json, now
from .manager import Manager

LOCK = threading.RLock()
CATALOG = Path(__file__).with_name('plugin-catalog.json')


def bounded(path, limit=65536):
    path = Path(path)
    if path.is_symlink() or path.is_junction() or not path.is_file() or path.stat().st_size > limit:
        return None
    with path.open('rb') as handle:
        raw = handle.read(limit + 1)
    return raw if len(raw) <= limit else None


def requirements(args):
    id = args.get("id", "")
    rows = []
    if id == 'dumb-lighting':
        found = bool(Path(args.get('signalrgb_path','')).is_file() or shutil.which('SignalRgb.exe') or shutil.which('SignalRGB'))
        if os.name == 'nt' and not found:
            import winreg
            for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
                    try:
                        with winreg.OpenKey(hive, r'Software\Microsoft\Windows\CurrentVersion\Uninstall', 0, winreg.KEY_READ | view) as key:
                            for i in range(min(winreg.QueryInfoKey(key)[0], 2000)):
                                try:
                                    with winreg.OpenKey(key, winreg.EnumKey(key, i)) as app:
                                        name = winreg.QueryValueEx(app, 'DisplayName')[0]
                                        if 'signalrgb' in str(name).lower().replace(' ', ''):
                                            found = True
                                except OSError:
                                    pass
                    except OSError:
                        pass
        rows.append({'name':'SignalRGB', 'state':'found' if found else 'not_found', 'separate_app':True,
                     'detail':'Windows app registration or command found.' if found else 'Not found in Windows app registrations or PATH. Install SignalRGB separately, or locate an existing portable install.'})
    elif id == 'dumbvoice':
        rows.extend([
            {'name':'Windows x64', 'state':'found' if os.name == 'nt' and platform.machine().lower() in ('amd64','x86_64') else 'not_found', 'detail':'Required for the native package.'},
            {'name':'Speech engine and English model', 'state':'found' if Path(args.get('engine_path','')).is_file() and Path(args.get('model_path','')).is_file() else 'choose', 'detail':'Choose your whisper.cpp executable and model in DumbVoice settings. Custom paths are supported; no drive scan or model download runs here.'},
            {'name':'Python (optional engines only)', 'state':'found' if shutil.which('py') or shutil.which('python') else 'optional', 'detail':'The native whisper.cpp path does not require Python. Python engine packages can be installed by the setup thread.'}
        ])
    if id == 'dumbvoice':
        found = False
        if os.name == 'nt':
            import winreg
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full', 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
                    found = isinstance(winreg.QueryValueEx(key, 'Release')[0], int)
            except OSError:
                pass
        rows.append({'name':'.NET Framework 4.x','state':'found' if found else 'not_found','detail':'Windows runtime registration check. Source builds also need the Framework C# compiler; the T3 setup request verifies build tools before installing.'})
    return {'items':rows, 'checked_at':now()}


class Plugins:
    def __init__(self, config):
        self.config = config
        self.folder = Manager(config).data / 'plugins'
        if self.folder.is_symlink() or self.folder.is_junction():
            raise APIError('Plugin storage must be an ordinary app folder.')
        self.folder.mkdir(exist_ok=True)
        self.path = self.folder / 'shelf.json'

    def shelf(self):
        return json.loads(self.path.read_text('utf-8')) if self.path.exists() else {'items':{}}

    def context(self, project):
        item = self.config.roots().get(project)
        signals = []
        if item:
            root = item[1]
            for name, tags in [('Cargo.toml',['rust']),('pyproject.toml',['python']),('requirements.txt',['python']),('default.project.json',['roblox','luau']),('go.mod',['golang'])]:
                if bounded(root / name) is not None:
                    signals += tags
            raw = bounded(root / 'package.json')
            if raw is not None:
                signals.append('javascript')
                try:
                    package = json.loads(raw)
                    for name, tag in [('react','react'),('next','nextjs'),('typescript','typescript'),('discord.js','discord'),('@tauri-apps/api','tauri')]:
                        if name in package.get('dependencies',{}) or name in package.get('devDependencies',{}):
                            signals.append(tag)
                except (ValueError, TypeError):
                    pass
        return {'signals':sorted(set(signals)), 'note':'Matched from root manifests; only stack keywords are used in discovery.' if signals else 'Choose a registered project with a recognized root manifest, or search by language.'}

    def call(self, name, args):
        if name == 'plugins.list':
            with LOCK:
                return {'items':json.loads(CATALOG.read_text('utf-8')), 'shelf':self.shelf(), 'context':self.context(args.get('project',''))}
        if name == 'plugins.search':
            return self.search(args)
        if name == 'plugins.requirements':
            return requirements(args)
        with LOCK:
            shelf = self.shelf()
            if name == 'plugins.add':
                item = args.get('item')
                if not isinstance(item,dict) or item.get('kind') not in ('mcp','api','library') or not isinstance(item.get('id'),str) or not item['id'] or len(json.dumps(item)) > 16000:
                    raise APIError('Choose a catalog tool.')
                url = urllib.parse.urlsplit(item.get('url',''))
                if url.scheme != 'https' or not url.hostname or url.username or url.password:
                    raise APIError('Tool needs a public HTTPS source.')
                shelf['items'][item['id']] = {**item, 'state':'added', 'added_at':now()}
            elif name == 'plugins.remove':
                shelf['items'].pop(args.get('id',''),None)
            elif name == 'plugins.install':
                id = args.get('id')
                files = {'dumbvoice':['DumbVoice.exe','transcribe.py'], 'dumb-lighting':[f'Dumb {s}.html' for s in ('Cinema','Coding','FPS','Horror','Music','Simulator')]}.get(id)
                if not files:
                    raise APIError('This app has no installable package yet.')
                source = Path(args.get('source','')).resolve()
                payload = []
                for file in files:
                    raw = bounded(source / file,32*1024*1024)
                    if raw is None or (file.endswith('.exe') and not raw.startswith(b'MZ')):
                        raise APIError(f'Package needs an ordinary {file} file (up to 32 MiB).')
                    payload.append((file,raw))
                destination = self.folder / f'{id}-{uuid.uuid4()}'
                destination.mkdir()
                for file, raw in payload:
                    (destination / file).write_bytes(raw)
                item = next(i for i in json.loads(CATALOG.read_text('utf-8')) if i['id'] == id)
                shelf['items'][id] = {**item, 'state':'installed','path':str(destination),'added_at':now()}
            elif name == 'plugins.folder':
                item = shelf['items'].get(args.get('id'),{})
                path = Path(item.get('path','')).resolve()
                if item.get('state') != 'installed' or not path.is_relative_to(self.folder.resolve()) or not path.is_dir():
                    raise APIError('Install the package first.')
                if os.name != 'nt':
                    raise APIError('Opening package folders requires Windows.')
                os.startfile(path)
                return {'opened':True}
            else:
                raise APIError('Unknown plugin action.')
            atomic_json(self.path,shelf)
            return shelf

    @staticmethod
    def get(url):
        # All callers construct URLs for these two fixed services. Redirects are blocked.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None
        opener = urllib.request.build_opener(NoRedirect)
        request = urllib.request.Request(url, headers={'User-Agent':'DumbManager-Plugins/0.1','Accept':'application/json'})
        with opener.open(request,timeout=12) as response:
            raw = response.read(2*1024*1024+1)
        if len(raw)>2*1024*1024:
            raise APIError('Source response is too large.')
        return json.loads(raw)

    def search(self, args):
        query = args.get('query','')
        if not isinstance(query,str) or len(query)>120 or any(ord(c)<32 for c in query):
            raise APIError('Search with up to 120 characters.')
        ctx = self.context(args.get('project',''))
        term = query.strip() or (ctx['signals'][-1] if ctx['signals'] else 'developer')
        kind = args.get('kind','all')
        items, sources = [], []
        if kind in ('all','mcp',''):
            try:
                result = self.get('https://registry.modelcontextprotocol.io/v0.1/servers?'+urllib.parse.urlencode({'search':term if len(term)>=3 else 'mcp','version':'latest','limit':40}))
                for entry in result.get('servers',[])[:40]:
                    server = entry['server'];name = server.get('name','')
                    if not name or entry.get('_meta',{}).get('io.modelcontextprotocol.registry/official',{}).get('status','active') != 'active':
                        continue
                    items.append({'id':'mcp:'+name,'name':server.get('title') or name,'kind':'mcp','description':server.get('description',''),'url':'https://registry.modelcontextprotocol.io/v0.1/servers/'+urllib.parse.quote(name,safe='')+'/versions/latest','source':'MCP Registry','version':server.get('version'),'tags':[term],'manifest':server,'setup':'Review the publisher’s package or remote endpoint. Adding it keeps the configuration on your DumbManager shelf; no other MCP client is changed.'})
                sources.append({'name':'MCP Registry','ok':True})
            except (OSError,ValueError,KeyError,APIError):
                sources.append({'name':'MCP Registry','ok':False,'error':'Source unavailable or rate limited. Try again shortly.'})
        if kind in ('all','library',''):
            try:
                words = ' '.join(''.join(c if c.isalnum() or c in '-_' else ' ' for c in term).split()[:8])
                result = self.get('https://api.github.com/search/repositories?'+urllib.parse.urlencode({'q':words+' library archived:false','sort':'stars','per_page':24}))
                for repo in result.get('items',[])[:24]:
                    items.append({'id':'github:'+repo['full_name'],'name':repo['full_name'],'kind':'library','description':repo.get('description'),'url':repo['html_url'],'source':'GitHub','stars':repo.get('stargazers_count'),'updated_at':repo.get('pushed_at'),'tags':repo.get('topics',[]),'setup':'Read the repository’s installation and compatibility notes. Add this reference to your shelf; install the package using your project’s package manager.'})
                sources.append({'name':'GitHub','ok':True})
            except (OSError,ValueError,KeyError,APIError):
                sources.append({'name':'GitHub','ok':False,'error':'Source unavailable or rate limited. Try again shortly.'})
        return {'items':items,'sources':sources,'context':ctx,'term':term,'checked_at':now()}
