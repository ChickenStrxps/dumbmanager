"""Project-scoped Git workflows. Fixed argv, bounded reads, durable write receipts."""
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

from .catalog import SENSITIVE
from .common import APIError, inside, json_text, now, slug

_LOCAL_LOCKS = {}
_LOCAL_LOCKS_GUARD = threading.Lock()

MAX_OUTPUT = 2 * 1024 * 1024
MAX_DIFF = 160_000
ACTIONS = ['init', 'stage', 'unstage', 'commit', 'branch_create', 'branch_switch',
           'branch_delete', 'merge_ff', 'fetch', 'pull', 'push', 'remote_add',
           'remote_remove', 'stash_save', 'stash_apply', 'stash_drop']


def sensitive(path):
    return any(SENSITIVE.search(part) or part.lower() == '.git' for part in Path(path).parts)


def scrub(value):
    # Never return URL passwords or access-token query strings from Git diagnostics.
    value = re.sub(r'((?:https?|ssh)://)[^\s/@]+@', r'\1[redacted]@', value, flags=re.I)
    value = re.sub(r'(https?://[^\s?]+)\?[^\s]*', r'\1?[redacted]', value, flags=re.I)
    return re.sub(r'([?&](?:token|access_token|key|password)=)[^\s&]+', r'\1[redacted]', value, flags=re.I)


class Git:
    def __init__(self, config):
        self.config = config
        self.folder = config.data / 'git'
        self.folder.mkdir(exist_ok=True)
        self.database = self.folder / 'receipts.sqlite'
        with self.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS receipts (key TEXT PRIMARY KEY,digest TEXT,state TEXT,result TEXT)')

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.database, timeout=5)
        try:
            with db:
                yield db
        finally:
            db.close()

    def project(self, project):
        roots = self.config.roots()
        if project not in roots or not roots[project][1].is_dir():
            raise APIError('Choose a registered project folder.', 'not_found', 404)
        return roots[project][1].resolve()

    @contextmanager
    def lock(self, root):
        canonical = os.path.normcase(str(Path(root).resolve()))
        path = self.folder / (hashlib.sha256(canonical.encode()).hexdigest() + '.lock')
        key = os.path.normcase(str(path.resolve()))
        with _LOCAL_LOCKS_GUARD:
            local = _LOCAL_LOCKS.setdefault(key, threading.Lock())
        if not local.acquire(blocking=False):
            raise APIError('Git is busy for this project. Try again when it finishes.', 'busy', 409)
        try:
            # Append descriptors may move the Windows CRT byte-lock position.
            # Use a stable non-append descriptor plus an in-process guard.
            fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
            with os.fdopen(fd, 'r+b') as handle:
                handle.seek(0, 2)
                if not handle.tell():
                    handle.write(b'0');handle.flush()
                handle.seek(0)
                try:
                    if os.name == 'nt':
                        import msvcrt
                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError as exc:
                    raise APIError('Git is busy for this project. Try again when it finishes.', 'busy', 409) from exc
                try:
                    yield
                finally:
                    if os.name == 'nt':
                        handle.seek(0);msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(handle, fcntl.LOCK_UN)
        finally:
            local.release()

    def run(self, root, args, *, ok=(0,), timeout=20, limit=MAX_OUTPUT):
        env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
        env.update(GIT_TERMINAL_PROMPT='0', GCM_INTERACTIVE='Never', GIT_OPTIONAL_LOCKS='0',
                   GIT_PAGER='cat', GIT_EDITOR='true', GIT_SEQUENCE_EDITOR='true')
        # Literal pathspecs belong on file operations only. Propagating the flag
        # into `stash` disables Git's internal magic pathspecs during cleanup.
        literal = ['--literal-pathspecs'] if args[0] in {'add', 'reset', 'rm', 'diff', 'show', 'ls-files'} else []
        command = ['git', '--no-pager', *literal, '-c', 'color.ui=false',
                   '-c', 'core.quotepath=false', '-c', 'core.fsmonitor=false',
                   '-c', 'protocol.ext.allow=never', '-c', 'maintenance.auto=false', '-C', str(root), *args]
        flags = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
        with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as error:
            try:
                process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=output, stderr=error, env=env, **flags)
            except FileNotFoundError as exc:
                raise APIError('Git is not installed or is not on PATH.', 'git_unavailable', 503) from exc
            deadline = time.monotonic() + timeout
            while process.poll() is None:
                too_large = os.fstat(output.fileno()).st_size > limit or os.fstat(error.fileno()).st_size > MAX_OUTPUT
                if too_large or time.monotonic() >= deadline:
                    if os.name == 'nt':
                        subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW, timeout=5)
                    else:
                        process.kill()
                    process.wait(timeout=5)
                    if too_large: raise APIError('Git output is too large for this view.', 'git_too_large', 413)
                    raise APIError('Git timed out. Check the current status before another action.', 'git_timeout', 504)
                try: process.wait(timeout=0.1)
                except subprocess.TimeoutExpired: pass
            output.seek(0); raw = output.read(limit + 1)
            error.seek(0); diagnostic = scrub(error.read(12_000).decode('utf-8', 'replace').strip())
            if process.returncode not in ok:
                raise APIError(diagnostic or 'Git could not complete that action.', 'git_failed', 409)
            if len(raw) > limit:
                raise APIError('Git output is too large for this view. Use a narrower project or file.', 'git_too_large', 413)
            return raw, diagnostic, process.returncode

    def repository(self, root):
        # Do not inherit a parent repository and accidentally operate outside this project.
        marker = root / '.git'
        if not marker.exists():
            if (root / 'HEAD').is_file() and (root / 'objects').is_dir() and (root / 'config').is_file():
                raise APIError('This is a bare repository. Clone it into a working project to use this view.')
            return False
        raw, _, _ = self.run(root, ['rev-parse', '--show-toplevel'])
        if Path(raw.decode('utf-8', 'replace').strip()).resolve() != root:
            raise APIError('Select the registered repository root, not a folder inside it.')
        return True

    def projects(self):
        return {'items': [{'id': pid, 'name': name, 'repository': (root / '.git').exists()}
                          for pid, (name, root) in self.config.roots().items() if root.is_dir()], 'time': now()}

    def snapshot(self, root):
        if not self.repository(root):
            return {'repository': False, 'snapshot': hashlib.sha256(str(root).encode()).hexdigest(),
                    'files': [], 'branch': None, 'head': None, 'upstream': None, 'ahead': 0, 'behind': 0}
        raw, _, _ = self.run(root, ['status', '--porcelain=v2', '--branch', '-z', '--untracked-files=all'])
        parts = raw.decode('utf-8', 'replace').split('\0'); files = []; info = {}
        digest = hashlib.sha256(raw)
        i = 0
        while i < len(parts):
            entry = parts[i]; i += 1
            if not entry:
                continue
            if entry.startswith('# '):
                key, _, value = entry[2:].partition(' '); info[key] = value; continue
            origin = None
            if entry.startswith('1 '):
                fields = entry.split(' ', 8); xy, path = fields[1], fields[8]
            elif entry.startswith('2 '):
                fields = entry.split(' ', 9); xy, path = fields[1], fields[9]
                origin = parts[i]; i += 1
            elif entry.startswith('u '):
                fields = entry.split(' ', 10); xy, path = fields[1], fields[10]
            elif entry.startswith('? '):
                xy, path = '??', entry[2:]
            else:
                continue
            conflict = xy in {'DD', 'AU', 'UD', 'UA', 'DU', 'AA', 'UU'}
            files.append({'path': path, 'original_path': origin, 'status': xy,
                          'staged': xy[0] not in '.?', 'unstaged': xy[1] not in '.',
                          'untracked': xy == '??', 'conflict': conflict, 'sensitive': sensitive(path) or bool(origin and sensitive(origin))})
            for rel in [path, origin] if origin else [path]:
                try:
                    stat = (root / rel).lstat()
                    digest.update(json_text([rel, stat.st_size, stat.st_mtime_ns, stat.st_mode]).encode())
                except FileNotFoundError:
                    digest.update((rel + ':deleted').encode())
        # Index content catches new staging even if porcelain letters remain the same.
        index, _, _ = self.run(root, ['rev-parse', '--git-path', 'index'])
        index_path = Path(index.decode('utf-8', 'replace').strip())
        if not index_path.is_absolute():
            index_path = root / index_path
        if index_path.exists():
            with index_path.open('rb') as stream:
                while block := stream.read(65536): digest.update(block)
        stashes = self.stashes(root)
        digest.update(json_text(stashes).encode())
        refs, _, _ = self.run(root, ['for-each-ref', '--format=%(refname)%00%(objectname)'])
        remote_config, _, _ = self.run(root, ['config', '--null', '--get-regexp', r'^remote\.'], ok=(0, 1))
        digest.update(refs); digest.update(remote_config)
        tracking = info.get('branch.ab', '+0 -0').split()
        return {'repository': True, 'branch': info.get('branch.head'), 'head': info.get('branch.oid'),
                'upstream': info.get('branch.upstream'), 'ahead': int(tracking[0][1:]), 'behind': int(tracking[1][1:]),
                'files': files, 'snapshot': digest.hexdigest(), 'stashes': stashes}

    def stashes(self, root):
        raw, _, _ = self.run(root, ['stash', 'list', '--format=%H%x00%gs%x00'])
        fields = raw.decode('utf-8', 'replace').split('\0'); rows = []
        for i in range(0, len(fields) - 1, 2):
            oid = fields[i].strip()
            if oid: rows.append({'id': oid, 'message': fields[i + 1], 'index': len(rows)})
        return rows

    def status(self, project, limit=50, offset=0):
        root = self.project(project)
        with self.lock(root):
            data = self.snapshot(root)
            files = data.pop('files')
            data.update(project=project, files=files[offset:offset + limit], total=len(files), offset=offset,
                        next_offset=offset + limit if offset + limit < len(files) else None,
                        staged_count=sum(f['staged'] for f in files), conflict_count=sum(f['conflict'] for f in files),
                        changed_count=sum(f['unstaged'] for f in files), time=now())
            if not data['repository']:
                return data
            raw, _, _ = self.run(root, ['for-each-ref', '--format=%(refname:short)%00%(objectname)%00%(upstream:short)', 'refs/heads/'])
            branches = []
            for line in raw.decode('utf-8', 'replace').splitlines():
                name, oid, upstream = line.split('\0'); branches.append({'name': name, 'head': oid, 'upstream': upstream})
            data['branches'] = branches[:300]; data['branches_total'] = len(branches)
            raw, _, _ = self.run(root, ['remote'])
            remotes = []
            for name in raw.decode('utf-8', 'replace').splitlines()[:30]:
                fetch, _, _ = self.run(root, ['remote', 'get-url', '--', name])
                push, _, _ = self.run(root, ['remote', 'get-url', '--push', '--', name])
                remotes.append({'name': name, 'fetch': scrub(fetch.decode('utf-8', 'replace').strip()),
                                'push': scrub(push.decode('utf-8', 'replace').strip())})
            data['remotes'] = remotes
            return data

    def revision(self, value):
        if not re.fullmatch(r'[a-f0-9]{40}|[a-f0-9]{64}', value):
            raise APIError('Choose a full commit or stash ID from this view.')
        return value

    def file(self, root, path):
        if not path or '\0' in path or path in {'.', './'}:
            raise APIError('Choose an individual file.')
        target = inside(root, path, must_exist=False)
        if sensitive(path):
            raise APIError('Credential/session files are not opened or staged through this view.')
        return target

    def diff(self, project, path, staged=False, revision=''):
        root = self.project(project); target = self.file(root, path)
        with self.lock(root):
            if not self.repository(root): raise APIError('Initialize Git first.')
            if not revision:
                item = next((f for f in self.snapshot(root)['files'] if f['path'] == path), None)
                if item and item['sensitive']: raise APIError('Credential/session files are not opened through this view.')
            args = ['show', '--format=', '--no-renames', '--no-ext-diff', '--no-textconv', self.revision(revision), '--', path] if revision else [
                'diff', '--no-ext-diff', '--no-textconv', *(['--cached'] if staged else []), '--', path]
            raw, _, _ = self.run(root, args, limit=MAX_OUTPUT)
            if not raw and not staged and not revision:
                check, _, _ = self.run(root, ['ls-files', '--error-unmatch', '--', path], ok=(0, 1))
                if not check and target.is_file():
                    with target.open('rb') as stream: raw = stream.read(MAX_DIFF + 1)
                    if b'\0' in raw[:8192]: raw = b'Binary file; no text preview.'
            truncated = len(raw) > MAX_DIFF
            return {'path': path, 'staged': staged, 'revision': revision,
                    'text': raw[:MAX_DIFF].decode('utf-8', 'replace'), 'truncated': truncated}

    def history(self, project, limit=15, offset=0, revision=''):
        root = self.project(project)
        with self.lock(root):
            if not self.repository(root): return {'items': [], 'next_offset': None}
            if revision:
                oid = self.revision(revision)
                raw, _, _ = self.run(root, ['show', '--format=', '--name-only', '--no-renames', '-z', oid, '--'])
                return {'revision': oid, 'files': [{'path': p, 'sensitive': sensitive(p)} for p in raw.decode('utf-8', 'replace').split('\0') if p]}
            head, _, code = self.run(root, ['rev-parse', '--verify', 'HEAD'], ok=(0, 128))
            if code: return {'items': [], 'next_offset': None}
            raw, _, _ = self.run(root, ['log', '--no-show-signature', f'--max-count={limit+1}', f'--skip={offset}',
                                       '--format=%H%x00%an%x00%aI%x00%s%x00', '--'])
            fields = raw.decode('utf-8', 'replace').split('\0'); items = []
            for i in range(0, len(fields) - 3, 4):
                items.append(dict(zip(['id', 'author', 'at', 'subject'], [fields[i].strip(), *fields[i+1:i+4]])))
            return {'items': items[:limit], 'offset': offset, 'next_offset': offset + limit if len(items) > limit else None}

    def name(self, root, value):
        if not value or value.startswith('-') or value in {'HEAD', '@'} or '@{' in value or any(c in value for c in '\0\r\n'):
            raise APIError('Use a valid branch name.')
        self.run(root, ['check-ref-format', '--branch', value])
        return value

    def remote(self, root, name):
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,79}', name):
            raise APIError('Use a simple remote name, such as origin.')
        return name

    def url(self, value):
        if not value or value.startswith('-') or any(c in value for c in '\0\r\n') or '::' in value:
            raise APIError('Use an HTTPS, SSH or local repository address.')
        if re.match(r'^https?://', value, re.I):
            parsed = urlsplit(value)
            if parsed.scheme.lower() != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise APIError('Use HTTPS without embedded credentials or query tokens; Git uses your installed credential manager.')
        elif value.startswith('ssh://'):
            if urlsplit(value).password: raise APIError('Use SSH keys, not a password in the URL.')
        elif re.fullmatch(r'[\w.-]+@[\w.-]+:[^\s]+', value):
            pass
        elif not Path(value).is_absolute() or not Path(value).is_dir():
            raise APIError('Use HTTPS, SSH or an existing absolute local repository path.')
        return value

    def receipt(self, key, args, work):
        if not re.fullmatch(r'[A-Za-z0-9._-]{8,120}', key):
            raise APIError('Use a stable request key for a Git action.')
        digest = hashlib.sha256(json_text(args).encode()).hexdigest()
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT digest,state,result FROM receipts WHERE key=?', (key,)).fetchone()
            if row:
                if row[0] != digest: raise APIError('This retry key belongs to a different Git action.', 'conflict', 409)
                if row[1] == 'pending': raise APIError('The earlier action is running or has an uncertain result. Refresh status before another action.', 'git_uncertain', 409)
                result = json.loads(row[2])
                if row[1] == 'error': raise APIError(result['error'], result['code'], result['status'])
                return {**result, 'replayed': True}
            db.execute('INSERT INTO receipts VALUES (?,?,?,?)', (key, digest, 'pending', '{}'))
        try:
            result = work()
        except Exception as exc:
            error = exc if isinstance(exc, APIError) else APIError('Git action failed. Refresh status before another action.', 'git_failed', 409)
            with self.db() as db:
                db.execute('UPDATE receipts SET state=?,result=? WHERE key=?',
                           ('error', json_text({'error': str(error), 'code': error.code, 'status': error.status}), key))
            raise error
        with self.db() as db:
            db.execute('UPDATE receipts SET state=?,result=? WHERE key=?', ('done', json_text(result), key))
        return result

    def action(self, project, operation, snapshot, request_key, paths='[]', message='', branch='', remote='', url='', stash_id=''):
        root = self.project(project)
        args = {k: v for k, v in locals().copy().items() if k not in {'self', 'root', 'request_key'}}
        def work():
            with self.lock(root):
                data = self.snapshot(root)
                if data['snapshot'] != snapshot:
                    raise APIError('This repository changed. Refresh and review the current changes.', 'stale_snapshot', 409)
                files = data['files']; indexed = {f['path']: f for f in files}
                if operation == 'init':
                    if data['repository']: raise APIError('This project already has Git.')
                    command = ['init', '--initial-branch=' + self.name(root, branch or 'main')]
                else:
                    if not data['repository']: raise APIError('Initialize Git first.')
                    if operation in {'stage', 'unstage'}:
                        try: chosen = json.loads(paths)
                        except ValueError as exc: raise APIError('Choose a JSON list of file paths.') from exc
                        if not isinstance(chosen, list) or not 1 <= len(chosen) <= 200 or any(not isinstance(p, str) for p in chosen):
                            raise APIError('Select 1-200 changed files.')
                        chosen = list(dict.fromkeys(chosen)); selected = []
                        for path in chosen:
                            self.file(root, path)
                            if path not in indexed: raise APIError('A selected file changed. Refresh first.', 'stale_snapshot', 409)
                            item = indexed[path]; selected.append(path)
                            if item['original_path']:
                                self.file(root, item['original_path']); selected.append(item['original_path'])
                        if operation == 'stage': command = ['add', '--all', '--', *selected]
                        elif data['head'] == '(initial)': command = ['rm', '--cached', '--force', '--ignore-unmatch', '--', *selected]
                        else: command = ['reset', '--quiet', 'HEAD', '--', *selected]
                    elif operation == 'commit':
                        if not message.strip(): raise APIError('Add a commit message.')
                        if any(f['conflict'] for f in files): raise APIError('Resolve and stage the conflicts before committing.')
                        if not any(f['staged'] for f in files): raise APIError('Stage the changes you want to commit first.')
                        if any(f['staged'] and f['sensitive'] for f in files): raise APIError('Unstage credential/session files outside this view before committing.')
                        command = ['commit', '-m', message.strip()]
                    elif operation in {'branch_create', 'branch_switch', 'branch_delete', 'merge_ff'}:
                        name = self.name(root, branch)
                        if operation in {'branch_switch', 'merge_ff'} and files:
                            raise APIError('Commit or stash the current changes before switching or merging.')
                        command = {'branch_create': ['switch', '-c', name], 'branch_switch': ['switch', '--', name],
                                   'branch_delete': ['branch', '-d', '--', name], 'merge_ff': ['merge', '--ff-only', '--', name]}[operation]
                    elif operation in {'fetch', 'pull', 'push'}:
                        name = self.remote(root, remote)
                        # Validate the actual fetch/push destination too, not only newly added remotes.
                        destination, _, _ = self.run(root, ['remote', 'get-url', '--all', *(['--push'] if operation == 'push' else []), '--', name])
                        destinations = destination.decode('utf-8', 'replace').strip().splitlines()
                        if len(destinations) != 1: raise APIError('Use a remote with one destination for this view.')
                        self.url(destinations[0])
                        if operation in {'pull', 'push'}:
                            name_branch = self.name(root, branch)
                            if data['branch'] != name_branch: raise APIError('Refresh and choose the currently checked-out branch.')
                            if operation == 'pull' and files: raise APIError('Commit or stash current changes before pulling.')
                            command = ['pull', '--ff-only', '--no-rebase', '--no-tags', '--no-recurse-submodules', name, name_branch] if operation == 'pull' else ['push', '--no-follow-tags', '--recurse-submodules=no', '--set-upstream', name, 'HEAD:refs/heads/' + name_branch]
                        else: command = ['fetch', '--no-tags', '--no-recurse-submodules', name]
                    elif operation == 'remote_add':
                        command = ['remote', 'add', '--', self.remote(root, remote), self.url(url)]
                    elif operation == 'remote_remove':
                        command = ['remote', 'remove', '--', self.remote(root, remote)]
                    elif operation == 'stash_save':
                        if not files: raise APIError('There are no changes to stash.')
                        if any(f['sensitive'] for f in files): raise APIError('Handle changed credential/session files outside this view before stashing.')
                        command = ['stash', 'push', '--include-untracked', '-m', message.strip() or 'DumbManager stash']
                    elif operation in {'stash_apply', 'stash_drop'}:
                        oid = self.revision(stash_id)
                        item = next((s for s in data['stashes'] if s['id'] == oid), None)
                        if not item: raise APIError('That stash changed. Refresh first.', 'stale_snapshot', 409)
                        if operation == 'stash_apply' and files: raise APIError('Commit or stash current changes before applying this stash.')
                        command = ['stash', 'apply', '--index', oid] if operation == 'stash_apply' else ['stash', 'drop', 'stash@{' + str(item['index']) + '}']
                    else: raise APIError('Unknown Git action.')
                output, diagnostic, _ = self.run(root, command, timeout=45)
                return {'operation': operation, 'project': project, 'request_key': request_key,
                        'output': scrub(output.decode('utf-8', 'replace').strip())[:12_000], 'note': diagnostic, 'time': now()}
        return self.receipt(request_key, args, work)

    def clone(self, name, url, request_key):
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', name):
            raise APIError('Use a new folder name containing letters, numbers, hyphens or underscores.')
        destination = self.config.projects_root / name
        address = self.url(url)
        def work():
            with self.lock(destination):
                if destination.exists(): raise APIError('That project folder already exists. Choose a new name.')
                if slug(name) in self.config.roots(): raise APIError('That name matches an existing project ID. Choose a different folder name.')
                output, diagnostic, _ = self.run(self.config.projects_root, ['clone', '--no-recurse-submodules', '--', address, str(destination)], timeout=45)
                return {'operation': 'clone', 'project': slug(name), 'name': name, 'output': scrub(output.decode('utf-8', 'replace')), 'note': diagnostic, 'time': now()}
        return self.receipt(request_key, {'name': name, 'url': url, 'operation': 'clone'}, work)


def definitions():
    from .registry import capability, string, integer, boolean
    project = {'project': string('Registered project ID.')}
    def cap(name, description, props, required=(), action=False):
        value = capability('git.' + name, 'dumbapi', description, props, required, tags=('git', 'repositories'))
        if action: value['mode'] = 'action'
        return value
    return [
        cap('projects', 'List registered project folders and Git markers; does not initialize or fetch.', {}),
        cap('status', 'Live Git status, stage counts, branches, remotes and stashes with an action snapshot.',
            {**project, 'limit': integer(50, 1, 100), 'offset': integer(0, 0, 100000)}, ('project',)),
        cap('diff', 'Read one file diff or untracked text preview; no external diff/textconv or credential files.',
            {**project, 'path': string(maxLength=2000), 'staged': boolean(), 'revision': string(default='')}, ('project', 'path')),
        cap('history', 'Page commit history, or list the changed filenames of one full commit ID.',
            {**project, 'limit': integer(15, 1, 50), 'offset': integer(0, 0, 100000), 'revision': string(default='')}, ('project',)),
        cap('action', 'Explicit Git workflow with a current snapshot and durable retry key. No force pushes, hard resets or generic commands. Push is a remote write; call only when requested.',
            {**project, 'operation': string(enum=ACTIONS), 'snapshot': string(), 'request_key': string(),
             'paths': string(default='[]', maxLength=20000), 'message': string(default='', maxLength=4000),
             'branch': string(default=''), 'remote': string(default=''), 'url': string(default=''), 'stash_id': string(default='')},
            ('project', 'operation', 'snapshot', 'request_key'), True),
        cap('clone', 'Explicitly clone into a new named project folder. Existing folders are never replaced.',
            {'name': string(), 'url': string(), 'request_key': string()}, ('name', 'url', 'request_key'), True),
    ]
