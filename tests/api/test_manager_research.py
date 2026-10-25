import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dumbapi_core.app import App
from dumbapi_core.common import APIError, Config
from dumbapi_core.manager import Manager

THREAD = '12345678-1234-4234-8234-123456789abc'
OTHER = '22345678-1234-4234-8234-123456789abc'


class ResearchTest(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory(); self.addCleanup(t.cleanup)
        self.app = App(Config(Path(t.name) / 'DumbAPI', Path(t.name) / 'state'))
        self.manager = Manager(self.app.config)
        self.itch = self.app.call('manager.capture', {'title': 'Keep the page on reload', 'project': 'sample', 'use_active': False})

    def call(self, name, **args):
        return self.app.call('manager.research.' + name, {'id': self.itch['id'], **args})

    def get(self, **args):
        return self.call('get', **args)

    def prepare(self, **args):
        return self.call('prepare', expected_version=self.app.call('manager.get', {'id': self.itch['id']})['version'], **args)

    def payload(self):
        return {'summary': 'Source-only: restoring a saved page is supported; UI behavior was not tested.',
            'sources': [{'id': 'S1', 'title': 'Reload handler', 'path': 'web/app.js:66', 'excerpt': 'restorePage loads the saved view. The selected tab is restored.'}],
            'findings': [{'kind': 'observed', 'text': 'The source includes saved-page restoration, not proof that it works in the UI.',
                          'citations': [{'source_id': 'S1', 'quote': 'restorePage loads the saved view.'}]},
                         {'kind': 'inference', 'text': 'Testing the selected tab would help verify the user flow.',
                          'citations': [{'source_id': 'S1', 'quote': 'The selected tab is restored.'}]}],
            'plan': [{'id': 'route', 'text': 'Verify the selected page survives a reload.'}, {'id': 'recover', 'text': 'Provide recovery for missing saved pages.'}],
            'tools': [{'capability': 'source.read', 'reason': 'Inspect the restore handler.'}],
            'open_questions': ['Does phone reload preserve it?'], 'limitations': ['No UI tests were run.'], 'tool_ideas': []}

    def record(self, pack=None, data=None, **extra):
        pack = pack or self.get()
        return self.call('record', run_id=pack['run']['id'], expected_version=pack['run']['version'],
                         report=json.dumps(data or self.payload()), **extra)

    def adopt(self, pack, **extra):
        return self.call('adopt', run_id=pack['run']['id'], report_id=pack['run']['reports'][-1]['id'],
            expected_version=pack['run']['version'], itch_version=pack['itch_version'], step_ids='["route"]', **extra)

    def test_get_and_prepare_are_local_and_do_not_change_itch_or_active_context(self):
        with patch('dumbapi_core.t3.T3.send', side_effect=AssertionError('must not send')), patch('dumbapi_core.browser.Browser.start', side_effect=AssertionError('must not browse')):
            self.assertIsNone(self.get()['run'])
            p = self.prepare(question='Compare lightweight page recovery options.', request_key='prepare-once')
            repeated = self.prepare(question='Compare lightweight page recovery options.', request_key='prepare-once')
        self.assertEqual(p, repeated)
        self.assertEqual(len(self.get()['history']), 1)
        self.assertEqual(self.app.call('manager.get', {'id': self.itch['id']}), self.itch)
        self.assertIn('DEEP RESEARCH ONLY', p['run']['brief'])
        self.assertIn('manager.research.record', p['run']['brief'])
        self.assertEqual(p['run']['reports'], [])
        self.assertIsNone(self.app.call('manager.state')['active_context'])

    def test_prepare_revision_and_archive_guards(self):
        with self.assertRaises(APIError): self.call('prepare', expected_version=900)
        self.app.call('manager.update', {'id': self.itch['id'], 'changes': '{"state":"archived"}'})
        with self.assertRaises(APIError): self.prepare()

    def test_prepare_brief_remains_bounded_and_retains_save_instructions(self):
        self.app.call('manager.update', {'id': self.itch['id'], 'changes': json.dumps({'title': 't' * 2000,
            'desired_outcome': 'g' * 2000, 'feedback': [{'text': 'f' * 3000}] * 3})})
        brief = self.prepare(question='q' * 2000)['run']['brief']
        self.assertLessEqual(len(brief), 12000)
        self.assertTrue(brief.endswith('ready or resolved.'))

    def test_sources_quotes_plan_tools_survive_restart_and_export(self):
        p = self.prepare(); p = self.record(p)
        self.app = App(self.app.config)
        self.assertEqual(self.get()['run']['reports'], p['run']['reports'])
        export = self.app.call('manager.export')
        self.assertTrue(any(r['kind'] == 'research' and r['record']['id'] == p['run']['id'] for r in export['records']))
        self.assertEqual(self.app.call('manager.get', {'id': self.itch['id']}), self.itch)
        brief = self.app.call('manager.brief', {'id': self.itch['id']})['brief']
        self.assertIn('not implementation evidence', brief)
        self.assertIn(p['run']['id'], brief)

    def test_invalid_or_uncited_findings_are_not_saved(self):
        self.prepare()
        for change in ('bad_quote', 'missing_source', 'uncited', 'unknown_kind'):
            p = self.payload()
            if change == 'bad_quote': p['findings'][0]['citations'][0]['quote'] = 'invented'
            if change == 'missing_source': p['findings'][0]['citations'][0]['source_id'] = 'S9'
            if change == 'uncited': p['findings'][0]['citations'] = []
            if change == 'unknown_kind': p['findings'][0]['kind'] = 'verified'
            with self.assertRaises(APIError): self.record(data=p)
        self.assertEqual(self.get()['run']['reports'], [])

    def test_url_path_credentials_and_nonexistent_tools_rejected(self):
        self.prepare()
        for url in ('javascript:alert(1)', 'file:///C:/secrets', 'https://user:pass@example.org'):
            p = self.payload(); p['sources'][0].update(url=url, path='')
            with self.assertRaises(APIError): self.record(data=p)
        for path in ('../secret.txt', 'C:\\secret.txt', '/secret.txt'):
            p = self.payload(); p['sources'][0]['path'] = path
            with self.assertRaises(APIError): self.record(data=p)
        p = self.payload(); p['tools'][0]['capability'] = 'shell.anything'
        with self.assertRaises(APIError): self.record(data=p)

    def test_report_masks_credentials_before_storage_and_matches_redacted_quotes(self):
        self.prepare()
        p = self.payload(); credential = 'sk-' + ('f' * 24)
        p['summary'] += ' ' + credential
        p['sources'][0]['excerpt'] += ' ' + credential
        p['findings'][0]['citations'][0]['quote'] = credential
        pack = self.record(data=p)
        self.assertNotIn(credential, json.dumps(pack))
        self.assertIn('[credential removed]', json.dumps(pack))

    def test_empty_findings_are_honest_and_do_not_fill_quota(self):
        self.prepare()
        p = self.record(data={'summary': 'Source was unavailable; no supported finding.', 'limitations': ['No page content was available.']})
        self.assertEqual(p['run']['reports'][0]['findings'], [])
        self.assertEqual(p['run']['reports'][0]['tools'], [])

    def test_versions_cross_itch_ids_and_duplicate_step_ids_rejected(self):
        a = self.prepare(); b = self.record(a)
        with self.assertRaises(APIError): self.record(a)
        other = self.app.call('manager.capture', {'title': 'Other itch', 'use_active': False})
        with self.assertRaises(APIError): self.app.call('manager.research.get', {'id': other['id'], 'run_id': b['run']['id']})
        p = self.payload(); p['plan'][1]['id'] = p['plan'][0]['id']
        with self.assertRaises(APIError): self.record(b, p)

    def test_reports_and_passes_append_without_overwriting_and_scope_change_is_visible(self):
        p = self.prepare(); first = self.record(p)
        second = self.record(first)
        self.assertEqual(len(second['run']['reports']), 2)
        self.assertEqual(second['run']['reports'][0], first['run']['reports'][0])
        self.app.call('manager.update', {'id': self.itch['id'], 'changes': '{"desired_outcome":"A different goal"}'})
        old = self.get(run_id=p['run']['id']); self.assertTrue(old['stale'])
        with self.assertRaises(APIError): self.adopt(old)
        fresh = self.prepare()
        self.assertFalse(fresh['stale']); self.assertEqual(len(fresh['history']), 2)
        self.assertEqual(len(self.get(run_id=p['run']['id'])['run']['reports']), 2)

    def test_same_second_passes_and_reports_have_deterministic_latest_order(self):
        with patch('dumbapi_core.manager_research.now', return_value='2026-10-23T12:00:00+00:00'):
            a = self.prepare(question='First pass')
            b = self.prepare(question='Second pass')
            self.assertEqual(self.get()['run']['id'], b['run']['id'])
            self.assertEqual(self.get()['history'][0]['id'], b['run']['id'])
            a = self.record(a)
            self.assertEqual(self.get()['run']['id'], a['run']['id'])
            b = self.record(b)
            self.assertEqual(self.get()['run']['id'], b['run']['id'])
            self.assertIn(b['run']['id'], self.app.call('manager.brief', {'id': self.itch['id']})['brief'])

    def test_adopt_only_selected_steps_preserves_history_and_retries_do_not_duplicate(self):
        self.app.call('manager.update', {'id': self.itch['id'], 'changes': json.dumps({'state': 'ready', 'run_state': 'agent_reported_done',
            'plan': [{'id': 'old', 'text': 'Earlier work', 'done': True}], 'evidence': [{'summary': 'Earlier evidence'}]})})
        p = self.record(self.prepare())
        p = self.adopt(p, request_key='adopt-once'); self.adopt(self.get(), request_key='adopt-again')
        row = self.app.call('manager.get', {'id': self.itch['id']})
        self.assertEqual(len(row['plan']), 2); self.assertTrue(row['plan'][0]['done']); self.assertFalse(row['plan'][1]['done'])
        self.assertEqual(row['plan'][1]['text'], 'Verify the selected page survives a reload.')
        self.assertEqual(row['state'], 'open'); self.assertEqual(row['run_state'], 'not_sent')
        self.assertEqual(row['evidence'], [{'summary': 'Earlier evidence'}]); self.assertEqual(row['outcomes'], [])

    def test_adopt_keeps_active_work_status_and_rejects_conflict_or_accepted_itch(self):
        self.app.call('manager.update', {'id': self.itch['id'], 'changes': '{"state":"working","run_state":"agent_reported_running"}'})
        p = self.record(self.prepare()); self.adopt(p)
        row = self.app.call('manager.get', {'id': self.itch['id']}); self.assertEqual(row['run_state'], 'agent_reported_running')
        with self.assertRaises(APIError): self.adopt(p)
        # Synthetic fixture acceptance only.
        self.app.call('manager.complete', {'id': self.itch['id'], 'summary': 'Fixture accepted', 'accepted': True})
        with self.assertRaises(APIError): self.adopt(self.get())

    def test_plan_capacity_failure_is_atomic(self):
        self.app.call('manager.update', {'id': self.itch['id'], 'changes': json.dumps({'plan': [{'id': str(i), 'text': str(i)} for i in range(30)]})})
        p = self.record(self.prepare())
        with self.assertRaises(APIError): self.adopt(p)
        self.assertEqual(self.get()['run']['adopted'], [])

    def test_send_frozen_retries_and_remembered_destination_do_not_mark_itch_cooking(self):
        p = self.prepare(); args = dict(run_id=p['run']['id'], expected_version=p['run']['version'], thread_id=THREAD, request_key='research-once')
        with patch('dumbapi_core.t3.T3.connection', return_value={'url': 'http://127.0.0.1:3773', 'token': 'fixture'}):
            with patch('dumbapi_core.t3.rpc', side_effect=OSError('Lost response')) as failed:
                with self.assertRaises(APIError): self.call('send', **args)
            pending = self.get(); self.assertEqual(pending['run']['state'], 'send_unconfirmed')
            with self.assertRaises(APIError): self.prepare()
            with self.assertRaises(APIError): self.call('send', **{**args, 'thread_id': OTHER})
            self.app.call('manager.update', {'id': self.itch['id'], 'changes': '{"title":"Changed meanwhile"}'})
            with patch('dumbapi_core.t3.rpc', return_value={'sequence': 2}) as succeeded:
                done = self.call('send', **args)
                self.call('send', **args)
            self.assertEqual(succeeded.call_count, 1)
            self.assertEqual(failed.call_args.args[2], succeeded.call_args.args[2])
        row = self.app.call('manager.get', {'id': self.itch['id']})
        self.assertEqual(row.get('handoffs', []), []); self.assertEqual(row['state'], 'open'); self.assertEqual(row['run_state'], 'not_sent')
        self.assertEqual(done['thread_id'], THREAD); self.assertTrue(done['stale'])
        self.assertEqual(done['run']['state'], 'awaiting_report')

    def test_fresh_send_rejects_changed_scope_and_invalid_thread_before_freezing(self):
        p = self.prepare(); args = dict(run_id=p['run']['id'], expected_version=p['run']['version'], thread_id='wrong', request_key='send')
        with self.assertRaises(APIError): self.call('send', **args)
        self.assertIsNone(self.get()['run']['send'])
        self.app.call('manager.update', {'id': self.itch['id'], 'changes': '{"title":"New scope"}'})
        with self.assertRaises(APIError): self.call('send', **{**args, 'thread_id': THREAD})
        self.assertIsNone(self.get()['run']['send'])

    def test_report_saving_never_accepts_or_writes_implementation_evidence(self):
        p = self.prepare(); self.record(p, request_key='report-once')
        repeated = self.record(p, request_key='report-once')
        self.assertEqual(len(repeated['run']['reports']), 1)
        self.assertEqual(self.app.call('manager.get', {'id': self.itch['id']}), self.itch)


if __name__ == '__main__':
    unittest.main()
