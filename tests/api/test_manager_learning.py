import json
import tempfile
import unittest
from pathlib import Path

from dumbapi_core.app import App
from dumbapi_core.common import APIError, Config
from dumbapi_core.manager import Manager


class LearningTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.app = App(Config(root / 'DumbAPI', root / 'state'))
        self.manager = Manager(self.app.config)

    def tearDown(self):
        self.temp.cleanup()

    def ready(self, **changes):
        row = self.app.call('manager.capture', {'title': 'Keep the selected page on reload', 'project': 'sample', 'use_active': False})
        return self.app.call('manager.update', {'id': row['id'], 'changes': json.dumps({
            'state': 'ready', 'run_state': 'agent_reported_done',
            'plan': [{'id': 'route', 'text': 'Restore the selected page after reload.', 'done': True}],
            'evidence': [{'summary': 'Node syntax and Playwright browser checks passed.',
                          'workspace': 'C:\\Projects\\Sample', 'environment': 'Windows, Python 3.14',
                          'commands': ['node --check web/app.js']}], **changes})})

    def get(self, row):
        return self.app.call('manager.learning.get', {'id': row['id']})

    def update(self, row, **changes):
        return self.app.call('manager.update', {'id': row['id'], 'changes': json.dumps(changes)})

    def note(self, pack):
        return {'lessons': [{'title': 'Separate parsing from behavior',
            'explanation': 'Syntax checks and browser checks answer different questions.',
            'try_this': 'Locate the reload assertion and describe its setup.',
            'question': 'Does parsing prove that reload preserves the route?',
            'answer': 'No. That needs a browser behavior check.',
            'source_id': 'evidence:0', 'quote': 'Node syntax and Playwright browser checks passed.'}],
            'commands': [{'command': 'node --check web/app.js', 'explanation': 'Parse without running the script.',
                'caution': 'Run from the recorded workspace if you choose to reuse it.',
                'source_id': 'evidence:0:command:0', 'quote': 'node --check web/app.js'}],
            'packages': [{'name': 'Playwright', 'tip': 'Prefer a visible role or label for a locator.',
                'source_id': 'evidence:0', 'quote': 'Node syntax and Playwright browser checks passed.'}]}

    def record(self, row, pack, notes):
        return self.app.call('manager.learning.record', {'id': row['id'], 'revision': pack['revision'], 'notes': json.dumps(notes)})

    def mark(self, row, pack, **overrides):
        return self.app.call('manager.learning.progress', {'id': row['id'], 'revision': pack['revision'],
            'lesson_id': pack['lessons'][0]['id'], 'expected_version': pack['progress']['version'], **overrides})

    def test_read_is_local_scoped_and_does_not_accept_or_mutate(self):
        row = self.ready()
        self.app.call('manager.context.publish', {'project': 'other', 'thread_id': 'other', 'task': 'Private other project', 'workspace': 'C:\\Other', 'select': True})
        before = self.app.call('manager.get', {'id': row['id']})
        pack = self.get(row)
        self.assertEqual(before, self.app.call('manager.get', {'id': row['id']}))
        self.assertEqual(pack['workspace'], 'C:\\Projects\\Sample')
        self.assertEqual(pack['environment'], 'Windows, Python 3.14')
        self.assertNotIn('Private other project', json.dumps(pack))
        self.assertEqual(pack['stage'], 'Ready to test')
        self.assertFalse(before['outcomes'])
        self.assertEqual(self.get(row)['revision'], pack['revision'])

    def test_only_reported_work_supports_tool_tips(self):
        row = self.ready(plan=[], evidence=[], title='Please add Playwright, SQLite, unittest and a GIF')
        pack = self.get(row)
        self.assertFalse(pack['packages'])
        self.assertFalse(pack['commands'])
        self.assertIn('not enough history', pack['lessons'][0]['explanation'])

    def test_legacy_reports_do_not_invent_commands_or_dependencies(self):
        pack = self.get(self.ready(evidence=['Node syntax passed; 26 Python checks passed.']))
        self.assertFalse(pack['commands'])
        self.assertEqual([p['name'] for p in pack['packages']], ['Node syntax checks'])
        self.assertEqual(pack['packages'][0]['kind'], 'Mentioned in saved work')

    def test_exact_commands_are_preserved_including_quotes_and_paths(self):
        command = 'py -3.14 "C:\\Work Space\\inspect.py" --name "fish & chips"'
        pack = self.get(self.ready(evidence=[{'commands': [command, command]}]))
        self.assertEqual([c['command'] for c in pack['commands']], [command])

    def test_authored_notes_require_same_itch_evidence_and_exact_command(self):
        row = self.ready(); pack = self.get(row)
        saved = self.record(row, pack, self.note(pack))
        self.assertEqual(saved['notes_version'], 1)
        self.assertIn('Separate parsing from behavior', [l['title'] for l in saved['lessons']])
        self.assertEqual(len(saved['commands']), 1)
        for section, field, bad in [('commands', 'command', 'npm install anything'), ('packages', 'name', 'invented'), ('lessons', 'source_id', 'evidence:99')]:
            notes = self.note(saved); notes[section][0][field] = bad
            with self.assertRaises(APIError):
                self.record(row, saved, notes)

    def test_notes_refuse_request_as_evidence_and_unbounded_or_unknown_data(self):
        row = self.ready(); pack = self.get(row)
        notes = self.note(pack); notes['lessons'][0].update(source_id='observation', quote='Keep the selected page on reload')
        with self.assertRaises(APIError): self.record(row, pack, notes)
        for notes in ({'extra': []}, {'lessons': [None]}, {'commands': [{}]}, {'packages': [self.note(pack)['packages'][0]] * 7}):
            with self.assertRaises(APIError): self.record(row, pack, notes)

    def test_changed_work_invalidates_authored_notes_and_old_progress(self):
        row = self.ready(); pack = self.record(row, self.get(row), self.note(None))
        marked = self.mark(row, pack)
        self.assertTrue(marked['progress']['read'])
        self.update(row, plan=[{'id': 'route', 'text': 'A different completed change', 'done': True}])
        changed = self.get(row)
        self.assertTrue(changed['notes_stale'])
        self.assertFalse(changed['progress']['read'])
        self.assertNotIn('Separate parsing from behavior', [l['title'] for l in changed['lessons']])
        with self.assertRaises(APIError) as cm: self.mark(row, marked)
        self.assertEqual(cm.exception.status, 409)

    def test_progress_persists_separately_and_recovers_identical_retry(self):
        row = self.ready(); pack = self.get(row)
        first = self.mark(row, pack, request_key='read-once')
        self.assertEqual(first, self.mark(row, pack, request_key='read-once'))
        self.assertEqual(self.get(row)['progress']['version'], 1)
        self.assertEqual(self.app.call('manager.get', {'id': row['id']})['version'], row['version'])
        self.assertEqual(self.app.call('manager.get', {'id': row['id']})['state'], 'ready')
        unread = self.mark(row, first, done=False)
        self.assertFalse(unread['progress']['read'])
        self.assertEqual(self.app.call('manager.state')['active_context'], None)

    def test_concurrent_progress_and_other_itch_ids_are_rejected(self):
        row = self.ready(); pack = self.get(row)
        self.mark(row, pack)
        with self.assertRaises(APIError): self.mark(row, pack)
        other = self.ready(evidence=['A distinct report'])
        opack = self.get(other)
        with self.assertRaises(APIError): self.mark(other, opack, lesson_id=pack['lessons'][0]['id'])

    def test_unfinished_archived_and_repeated_work_is_not_mislabeled_finished(self):
        row = self.ready()
        self.app.call('manager.repeat', {'id': row['id'], 'note': 'It recurred'})
        pack = self.get(row)
        self.assertFalse(pack['eligible']); self.assertEqual(pack['stage'], 'Work not finished')
        self.assertFalse(pack['lessons'])
        self.update(row, state='archived', run_state='agent_reported_done')
        self.assertFalse(self.get(row)['eligible'])

    def test_accepted_stage_does_not_require_new_acceptance_to_learn(self):
        row = self.ready()
        self.app.call('manager.complete', {'id': row['id'], 'summary': 'Reload now keeps my page.', 'accepted': True})
        pack = self.get(row)
        self.assertEqual(pack['stage'], 'Accepted by you')
        self.mark(row, pack)
        self.assertEqual(len(self.app.call('manager.get', {'id': row['id']})['outcomes']), 1)

    def test_accepting_same_work_preserves_authored_notes_and_their_read_marks(self):
        row = self.ready(); pack = self.record(row, self.get(row), self.note(None))
        entry = next(l for l in pack['lessons'] if l['title'] == 'Separate parsing from behavior')
        self.mark(row, pack, lesson_id=entry['id'])
        self.app.call('manager.complete', {'id': row['id'], 'summary': 'Accepted this same reload change.', 'accepted': True})
        accepted = self.get(row)
        self.assertFalse(accepted['notes_stale'])
        self.assertIn(entry['id'], accepted['progress']['read'])
        self.assertTrue(accepted['commands'])
        self.assertEqual(accepted['work_revision'], pack['work_revision'])
        self.assertNotEqual(accepted['revision'], pack['revision'])

    def test_malformed_optional_history_and_credential_log_do_not_leak_or_crash(self):
        row = self.ready(evidence=[{'commands': None}, {'commands': {'not': 'a log'}},
            {'commands': ['curl --header "Authorization: Bearer abcdefghijklmnop"']},
            'api_key=supersecret123456 password=do-not-show sk-abcdefghijklmnop'])
        pack = self.get(row)
        self.assertFalse(pack['commands'])
        encoded = json.dumps(pack)
        for secret in ('abcdefghijklmnop', 'supersecret123456', 'do-not-show'):
            self.assertNotIn(secret, encoded)

    def test_capture_context_is_snapshot_not_live_environment(self):
        ctx = self.app.call('manager.context.publish', {'project': 'sample', 'thread_id': 'old', 'task': 'Old task', 'workspace': 'C:\\Old'})
        row = self.app.call('manager.capture', {'title': 'A change', 'context_id': ctx['id']})
        self.update(row, state='ready')
        self.app.call('manager.context.publish', {'project': 'sample', 'thread_id': 'old', 'task': 'New task', 'workspace': 'C:\\New'})
        pack = self.get(row)
        self.assertEqual(pack['workspace'], 'C:\\Old')
        self.assertIn('Snapshot', pack['workspace_note'])

    def test_quoted_credentials_and_secret_cli_arguments_are_removed(self):
        row = self.ready(evidence=[{'api_key': 'secretJSON1234', 'token': 'opaqueJSON1234',
            'commands': ['curl --api-key "secretCLI1234" https://example.invalid']}])
        pack = self.get(row)
        self.assertFalse(pack['commands'])
        for value in ('secretJSON1234', 'opaqueJSON1234', 'secretCLI1234'):
            self.assertNotIn(value, json.dumps(pack))

    def test_acceptance_does_not_evict_notes_in_a_full_source_window(self):
        row = self.ready(evidence=['Result ' + str(i) for i in range(24)])
        pack = self.get(row)
        entry = {'title': 'Keep a bounded review trail', 'explanation': 'Review recent recorded work.',
                 'try_this': 'Identify the latest result.', 'question': 'Is this a live run?', 'answer': 'No.',
                 'source_id': 'evidence:23', 'quote': 'Result 23'}
        pack = self.record(row, pack, {'lessons': [entry]})
        self.app.call('manager.complete', {'id': row['id'], 'summary': 'Accepted after review.', 'accepted': True})
        after = self.get(row)
        self.assertFalse(after['notes_stale'])
        self.assertEqual(pack['work_revision'], after['work_revision'])

    def test_duplicate_authored_lessons_cannot_make_read_total_unreachable(self):
        row = self.ready(); pack = self.get(row); notes = self.note(pack)
        notes['lessons'] *= 2
        pack = self.record(row, pack, notes)
        self.assertEqual(len(pack['lessons']), len({l['id'] for l in pack['lessons']}))
        for entry in pack['lessons']:
            pack = self.mark(row, pack, lesson_id=entry['id'])
        self.assertEqual(len(pack['progress']['read']), pack['progress']['total'])

    def test_contracts_are_discoverable_without_execution_or_runtime_dependencies(self):
        for name, mode in [('get', 'read'), ('record', 'action'), ('progress', 'action')]:
            self.assertEqual(self.app.describe('manager.learning.' + name)['mode'], mode)
        row = self.ready()
        self.assertIn('manager.learning.get/record', self.app.call('manager.brief', {'id': row['id']})['brief'])


if __name__ == '__main__':
    unittest.main()
