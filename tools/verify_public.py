"""Validate the audited source inventory and syntax without starting the app."""
import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT=Path(__file__).resolve().parents[1]

def main():
    manifest=json.loads((ROOT/'SOURCE-MANIFEST.json').read_text('utf-8'))
    errors=[]
    for item in manifest['files']:
        p=ROOT/item['path']
        if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=item['sha256']:
            errors.append('Manifest mismatch: '+item['path'])
    forbidden=re.compile(r'github_pat_[A-Za-z0-9_]{20,}|gh[pousr]_[A-Za-z0-9]{30,}|sk-[A-Za-z0-9_-]{30,}',re.I)
    modules={p.relative_to(ROOT/'backend').with_suffix('').as_posix().replace('/','.') for p in (ROOT/'backend').rglob('*.py')}
    for p in ROOT.rglob('*'):
        if not p.is_file() or any(part in ('.git','__pycache__','dist','build','.venv','evidence') for part in p.relative_to(ROOT).parts):continue
        if p.name in ('settings.json','desktop.token','http.token') or p.suffix in ('.sqlite','.db','.pyc'):
            errors.append('Runtime file: '+p.relative_to(ROOT).as_posix())
        if p.suffix not in ('.py','.js','.md','.html','.css','.ps1','.yml','.json','.txt','.toml'):continue
        text=p.read_text('utf-8-sig')
        if p.name!='verify_public.py' and forbidden.search(text):errors.append('Excluded identifier: '+p.relative_to(ROOT).as_posix())
        if p.suffix=='.py':
            try:tree=ast.parse(text,str(p))
            except SyntaxError as exc:errors.append(str(exc));continue
            if p.is_relative_to(ROOT/'backend'/'dumbapi_core'):
                relative=p.relative_to(ROOT/'backend').with_suffix('').parts
                for n in ast.walk(tree):
                    if isinstance(n,ast.ImportFrom) and n.level:
                        package=list(relative[:-1]);base=package[:len(package)-n.level+1]
                        name='.'.join(base+((n.module or '').split('.') if n.module else []))
                        if n.module and name not in modules and name+'.__init__' not in modules:errors.append('Missing relative import: '+name+' in '+p.name)
        if p.suffix=='.js':
            r=subprocess.run(['node','--check'],input=text,text=True,capture_output=True)
            if r.returncode:errors.append('JS syntax: '+p.relative_to(ROOT).as_posix()+' '+r.stderr[-700:])
    print(json.dumps({'manifest_files':len(manifest['files']),'errors':errors},indent=2))
    return bool(errors)
if __name__=='__main__':raise SystemExit(main())
