import json
import shutil
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path

from dumbapi_core.app import App
from dumbapi_core.common import APIError, Config
from dumbapi_core.git import Git, scrub


@unittest.skipUnless(shutil.which('git'), 'Git is required for disposable workflow checks')
class GitTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.projects = self.base / 'projects'; self.projects.mkdir()
        hub = self.projects / 'DumbAPI'; hub.mkdir()
        self.root = self.projects / 'Sample'; self.root.mkdir()
        (hub/'settings.json').write_text(json.dumps({'projects_root':'..'}))
        self.app = App(Config(hub, self.base / 'state'))
        self.git = Git(self.app.config)

    def tearDown(self):
        # Git makes object files read-only on Windows.
        def writable(function, path, exc):
            import os, stat
            os.chmod(path, stat.S_IWRITE); function(path)
        shutil.rmtree(self.base, onexc=writable)
        self.temp.cleanup()

    def raw(self, *args, root=None):
        return subprocess.check_output(['git', '-c', 'commit.gpgsign=false', '-C', str(root or self.root), *args], stderr=subprocess.STDOUT).decode().strip()

    def status(self, **kw):
        return self.app.call('git.status', {'project': 'sample', **kw})

    def act(self, operation, **kw):
        return self.app.call('git.action', {'project': 'sample', 'operation': operation,
                   'snapshot': self.status()['snapshot'], 'request_key': uuid.uuid4().hex, **kw})

    def init(self):
        self.act('init', branch='main')
        self.raw('config', 'user.name', 'Fixture'); self.raw('config', 'user.email', 'fixture@example.test')
        self.raw('config', 'commit.gpgsign', 'false')

    def commit(self, text='hello\n', path='hello.txt'):
        (self.root / path).write_text(text)
        self.act('stage', paths=json.dumps([path])); self.act('commit', message='Fixture change')

    def test_unborn_stage_unstage_commit_diff_and_receipt(self):
        self.assertFalse(self.status()['repository']); self.init()
        (self.root / 'hello.txt').write_text('one\n')
        self.assertIn('one', self.git.diff('sample', 'hello.txt')['text'])
        self.act('stage', paths='["hello.txt"]')
        (self.root / 'hello.txt').write_text('two\n')
        self.act('unstage', paths='["hello.txt"]')
        self.assertEqual((self.root / 'hello.txt').read_text(), 'two\n')
        self.act('stage', paths='["hello.txt"]')
        args = dict(project='sample', operation='commit', snapshot=self.status()['snapshot'], request_key=uuid.uuid4().hex, message='First')
        self.git.action(**args); self.assertTrue(self.git.action(**args)['replayed'])
        self.assertEqual(self.raw('rev-list', '--count', 'HEAD'), '1')
        with self.assertRaises(APIError): self.git.action(**{**args, 'message': 'Different'})
        self.assertEqual(self.git.history('sample')['items'][0]['subject'], 'First')
        oid = self.raw('rev-parse', 'HEAD')
        self.assertEqual(self.git.history('sample', revision=oid)['files'][0]['path'], 'hello.txt')
        self.assertIn('+two', self.git.diff('sample', 'hello.txt', revision=oid)['text'])

    def test_stale_snapshot_and_precise_paths(self):
        self.init(); self.commit(); (self.root / 'hello.txt').write_text('change')
        token = self.status()['snapshot']; (self.root / 'hello.txt').write_text('changed again')
        with self.assertRaisesRegex(APIError, 'changed'):
            self.git.action('sample', 'stage', token, uuid.uuid4().hex, paths='["hello.txt"]')
        (self.root / 'other.txt').write_text('other')
        self.act('stage', paths='["hello.txt"]')
        self.assertEqual(self.raw('diff', '--cached', '--name-only'), 'hello.txt')
        self.act('unstage', paths='["hello.txt"]'); self.assertEqual(self.status()['staged_count'], 0)
        for path in ['../outside', '.env', '.git/config', 'C:/outside']:
            with self.subTest(path=path), self.assertRaises(APIError): self.git.diff('sample', path)
        with self.assertRaises(APIError): self.git.status('missing')

    def test_branches_stashes_and_history_paging(self):
        self.init(); self.commit(); self.act('branch_create', branch='feature/test')
        self.assertEqual(self.status()['branch'], 'feature/test')
        (self.root / 'hello.txt').write_text('unfinished')
        with self.assertRaises(APIError): self.act('branch_switch', branch='main')
        self.act('stash_save', message='Pause')
        self.assertEqual(self.status()['total'], 0); stash = self.status()['stashes'][0]['id']
        self.act('branch_switch', branch='main'); self.act('stash_apply', stash_id=stash)
        self.assertEqual((self.root / 'hello.txt').read_text(), 'unfinished')
        self.assertEqual(len(self.status()['stashes']), 1)
        self.act('stage', paths='["hello.txt"]'); self.act('commit', message='Second')
        self.act('stash_drop', stash_id=stash); self.act('branch_delete', branch='feature/test')
        self.assertEqual(self.git.history('sample', limit=1)['next_offset'], 1)
        self.assertEqual(self.git.history('sample', limit=1, offset=1)['items'][0]['subject'], 'Fixture change')
        with self.assertRaises(APIError): self.act('branch_create', branch='@{-1}')

    def test_local_clone_fetch_pull_push_and_remote_changes(self):
        self.init(); self.commit()
        bare = self.base / 'remote.git'; subprocess.check_output(['git', 'init', '--bare', '--initial-branch=main', str(bare)], stderr=subprocess.STDOUT)
        self.act('remote_add', remote='origin', url=str(bare)); self.act('push', remote='origin', branch='main')
        clone = self.git.clone('Copy', str(bare), uuid.uuid4().hex)
        self.assertEqual(clone['operation'], 'clone'); self.assertTrue((self.projects / 'Copy' / 'hello.txt').exists())
        self.commit('new remote version')
        self.act('push', remote='origin', branch='main')
        copy = 'copy'; token = self.git.status(copy)['snapshot']
        self.git.action(copy, 'fetch', token, uuid.uuid4().hex, remote='origin')
        self.assertEqual(self.git.status(copy)['behind'], 1)
        self.git.action(copy, 'pull', self.git.status(copy)['snapshot'], uuid.uuid4().hex, remote='origin', branch='main')
        self.assertEqual((self.projects / 'Copy' / 'hello.txt').read_text(), 'new remote version')
        self.act('remote_remove', remote='origin'); self.assertEqual(self.status()['remotes'], [])
        with self.assertRaises(APIError): self.git.clone('Copy', str(bare), uuid.uuid4().hex)

    def test_secrets_options_binary_and_remote_snapshot(self):
        self.init(); self.commit()
        (self.root / '.env').write_text('TEST_SECRET=synthetic')
        with self.assertRaises(APIError): self.act('stage', paths='[".env"]')
        self.raw('add', '.env')
        with self.assertRaises(APIError): self.act('commit', message='Blocked')
        self.raw('reset', 'HEAD', '--', '.env'); (self.root / '.env').unlink()
        for url in ['-bad', 'ext::bad', 'https://user:pass@example.test/a', 'https://example.test/a?token=secret']:
            with self.subTest(url=url), self.assertRaises(APIError): self.act('remote_add', remote='origin', url=url)
        (self.root / 'binary.bin').write_bytes(b'\0binary')
        self.assertIn('Binary', self.git.diff('sample', 'binary.bin')['text'])
        token = self.status()['snapshot']; self.raw('remote', 'add', 'other', 'https://example.test/repo.git')
        with self.assertRaises(APIError): self.git.action('sample', 'remote_remove', token, uuid.uuid4().hex, remote='other')
        with self.assertRaises(APIError): self.app.call('git.action', {'project': 'sample', 'operation': 'exec', 'snapshot': token, 'request_key': 'test-key'})

    def test_rename_conflict_and_no_parent_repository(self):
        self.init(); self.commit(); self.raw('mv', 'hello.txt', 'renamed name.txt')
        row = self.status()['files'][0]; self.assertEqual(row['original_path'], 'hello.txt')
        self.act('unstage', paths='["renamed name.txt"]')
        self.assertTrue((self.root / 'renamed name.txt').exists())
        child = self.root / 'Child'; child.mkdir()
        self.app.config.settings['extra_projects'] = [{'id': 'child', 'path': str(child)}]
        self.assertFalse(self.git.status('child')['repository'])
        # Build conflicting commits in a separate temporary clone of this fixture.
        self.raw('reset', '--hard', 'HEAD'); (self.root / 'renamed name.txt').unlink(missing_ok=True)
        self.raw('switch', '-c', 'topic'); self.commit('topic\n')
        self.raw('switch', 'main'); self.commit('main\n')
        subprocess.run(['git', '-C', str(self.root), 'merge', 'topic'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(self.status()['conflict_count'], 1)
        with self.assertRaises(APIError): self.act('commit', message='Conflict')

    def test_fast_forward_unmerged_branch_protection_and_pagination(self):
        self.init(); self.commit(); self.act('branch_create', branch='topic'); self.commit('topic')
        self.act('branch_switch', branch='main')
        with self.assertRaises(APIError): self.act('branch_delete', branch='topic')
        self.act('merge_ff', branch='topic'); self.assertEqual((self.root/'hello.txt').read_text(), 'topic')
        self.act('branch_delete', branch='topic')
        for i in range(4): (self.root/f'new-{i}.txt').write_text('page')
        self.assertEqual(self.status(limit=2)['next_offset'], 2)
        self.assertEqual(len(self.status(limit=2, offset=2)['files']), 2)

    def test_stash_untracked_literal_name_is_saved_removed_and_recoverable(self):
        self.init(); self.commit()
        path='new file [literal].txt'; (self.root/path).write_text('pause me')
        self.act('stash_save', message='Untracked only')
        self.assertFalse((self.root/path).exists()); self.assertEqual(self.status()['total'], 0)
        stash=self.status()['stashes'][0]['id']; self.act('stash_apply', stash_id=stash)
        self.assertEqual((self.root/path).read_text(),'pause me'); self.assertEqual(len(self.status()['stashes']),1)

    def test_symlink_protection_limits_and_durable_pending(self):
        self.init(); self.commit()
        outside=self.base/'outside.txt'; outside.write_text('outside fixture')
        link=self.root/'link.txt'
        try: link.symlink_to(outside)
        except OSError: pass
        else:
            with self.assertRaises(APIError): self.git.diff('sample', 'link.txt')
            with self.assertRaises(APIError): self.act('stage', paths='["link.txt"]')
            link.unlink()
        with self.assertRaises(APIError): self.git.run(self.root, ['log', '--format=%H'], limit=8)
        with self.assertRaises(APIError):
            with self.git.lock(self.root): self.git.status('sample')
        args={'operation':'fixture'}; key=uuid.uuid4().hex
        import hashlib
        from dumbapi_core.common import json_text
        with self.git.db() as db:
            db.execute('INSERT INTO receipts VALUES (?,?,?,?)',(key,hashlib.sha256(json_text(args).encode()).hexdigest(),'pending','{}'))
        with self.assertRaisesRegex(APIError,'uncertain'): self.git.receipt(key,args,lambda: self.fail('Repeated interrupted write'))
        self.assertNotIn('password', scrub('ssh://user:password@example.test/repo'))


if __name__ == '__main__': unittest.main()
