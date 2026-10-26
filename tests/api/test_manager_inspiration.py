import gzip
import io
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request

from dumbapi_core.app import App
from dumbapi_core.common import APIError, Config, now
from dumbapi_core.inspiration_sources import BY_ID, MAX_BYTES, Blog, Redirects, fetch, item, plain, read, read_rss, safe_url, stamp
from dumbapi_core.manager import Manager
from dumbapi_core.manager_inspiration import CONFIG, LEASE, STATUS, Inspiration, balanced, rank


class SourceTest(unittest.TestCase):

    def test_rss_atom_skip_missing_links_and_keep_unknown_date(self):
        xml = b'''<rss><channel><item><title>A &amp; B</title><link>https://example.com/one?utm_source=x</link>
            <description>&lt;p&gt;Real excerpt&lt;/p&gt;</description><pubDate>bad</pubDate></item>
            <item><title>Missing URL</title></item></channel></rss>'''
        rows = read_rss(io.BytesIO(xml), BY_ID['freecad'])
        self.assertEqual(len(rows), 1); self.assertEqual(rows[0]['excerpt'], 'Real excerpt')
        self.assertIsNone(rows[0]['published_at']); self.assertEqual(rows[0]['url'], 'https://example.com/one')
        atom = b'''<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Atom</title>
            <link rel="self" href="https://example.com/feed"/><link href="https://example.com/article"/>
            <summary>Source says so.</summary><updated>2025-01-01T12:00:00Z</updated></entry></feed>'''
        self.assertEqual(read_rss(io.BytesIO(atom), BY_ID['openai'])[0]['url'], 'https://example.com/article')

    def test_xml_is_bounded_and_entity_declarations_rejected(self):
        for xml in (b'<!DOCTYPE rss [<!ENTITY a "boom">]><rss/>', '<rss/>'.encode('utf-16'), b'<rss><broken>'):
            with self.assertRaises(Exception): read_rss(io.BytesIO(xml), BY_ID['openai'])
        with self.assertRaises(APIError): read_rss(io.BytesIO(b' ' * (MAX_BYTES + 1)), BY_ID['openai'])
        entries = b''.join(b'<item><title>A</title><link>https://example.com/%d</link></item>' % i for i in range(40))
        self.assertEqual(len(read_rss(io.BytesIO(b'<rss>' + entries + b'</rss>'), BY_ID['openai'])), 18)
        with self.assertRaises(APIError): read_rss(io.BytesIO(b'<rss/>'), BY_ID['openai'], time.monotonic() - 1)

    def test_gzipped_feed_and_redirect_contract(self):
        xml = b'<rss><item><title>CAD update</title><link>https://example.com/a</link></item></rss>'
        response = io.BytesIO(gzip.compress(xml)); response.headers = {'Content-Encoding': 'gzip'}
        with patch('dumbapi_core.inspiration_sources.build_opener') as opener:
            opener.return_value.open.return_value = response
            self.assertEqual(fetch(BY_ID['deepmind'])[0]['title'], 'CAD update')
        for url in ('http://openai.com/x', 'https://evil.example/x', 'https://user@openai.com/x'):
            with self.assertRaises(APIError): Redirects().redirect_request(Request('https://openai.com/a'), None, 301, '', {}, url)

    def test_blog_headings_deduplicate_repeated_link_cards(self):
        parser = Blog(BY_ID['typesafe'])
        parser.feed('<a href="./blog/new-model"><h3>New model</h3><p>A source preview</p></a>' * 3)
        self.assertEqual(len(parser.rows), 1); self.assertEqual(parser.rows[0]['title'], 'New model')
        self.assertEqual(parser.rows[0]['excerpt'], 'A source preview')
        parser = Blog(BY_ID['typesafe'])
        parser.feed('<a href="./blog/new"><h3>New</h3><p>TL;DR: First sentence.</p><p>TL;DR: First sentence.</p></a>')
        self.assertEqual(parser.rows[0]['excerpt'], 'First sentence.')
        parser = Blog(BY_ID['typesafe'])
        parser.feed('<a href="./blog/card"><p>Media</p><div data-framer-name="H"><p>Actual headline</p></div><p>Source summary.</p></a>')
        self.assertEqual(parser.rows[0]['title'], 'Actual headline')
        self.assertEqual(parser.rows[0]['excerpt'], 'Source summary.')



class InspirationTest(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory(); self.addCleanup(t.cleanup)
        root = Path(t.name) / 'DumbAPI'; root.mkdir(); (root.parent / 'sample').mkdir()
        (root/'settings.json').write_text(json.dumps({'projects_root':'..'}))
        self.config = Config(root, Path(t.name) / 'state')
        self.app, self.manager = App(self.config), Manager(self.config)
        self.service = Inspiration(self.config)
        self.configure(['show-hn'])

    def call(self, op, **args): return self.app.call('manager.inspiration.' + op, args)

    def configure(self, sources, **extra):
        version = self.call('get')['settings']['version']
        return self.call('configure', sources=json.dumps(sources), expected_version=version, **extra)

    def row(self, key='one', source='show-hn', **extra):
        return item(BY_ID[source], 'A useful ' + key, 'https://example.com/' + key, 'Actual source preview.', '2025-01-01T00:00:00Z', updated_at=now(), **extra)

    def seed(self, rows):
        with self.manager.db() as db:
            for row in rows: self.manager.put(db, 'inspiration', {**row, 'saved': False, 'hidden': False, 'itches': {}})

    def due(self, source='show-hn'):
        with self.manager.db() as db:
            statuses = self.manager.setting(db, STATUS, {}); statuses[source] = {'next_at': 0}
            self.manager.set_setting(db, STATUS, statuses)

    def test_open_and_settings_are_local_with_conflict_and_validation(self):
        with patch('dumbapi_core.manager_inspiration.read', side_effect=AssertionError('No fetch')), patch('dumbapi_core.manager_inspiration.rank', side_effect=AssertionError('No model')):
            self.assertEqual(self.call('get')['items'], [])
            self.configure(['docs'], rank=True, interests='CAD')
            refs = self.call('get', category='docs')['items']
            self.assertEqual(len(refs), 6); self.assertTrue(all(r['published_at'] is None for r in refs))
            self.assertEqual(self.call('get')['total'], 0)
        with self.assertRaises(APIError): self.call('configure', sources='["arbitrary"]', expected_version=3)
        with self.assertRaises(APIError): self.call('configure', sources='[]', expected_version=0)
        with self.assertRaises(APIError): self.call('get', category='invented')

    def test_refresh_cooldown_lost_response_recovery_and_conflicting_key(self):
        with patch('dumbapi_core.manager_inspiration.read', return_value=([self.row()], 'Actual preview')) as reader:
            first = self.call('refresh', request_key='same')
            again = self.call('refresh', request_key='same')
            self.assertTrue(again['recovered']); self.assertEqual(first['received'], 1)
            self.assertEqual(reader.call_count, 1)
            cooldown = self.call('refresh', request_key='next')
            self.assertEqual(cooldown['cooldown'], ['show-hn']); self.assertEqual(reader.call_count, 1)
            with self.assertRaises(APIError): self.call('refresh', request_key='same', source='docs')
        self.assertFalse(self.call('get')['refreshing'])

    def test_partial_failure_keeps_cache_and_hides_error_details(self):
        self.configure(['show-hn', 'freecad']); self.seed([self.row('cached', 'freecad')])
        def reader(source, _):
            if source['id'] == 'freecad': raise RuntimeError('private://secret')
            return [self.row()], 'Actual preview'
        with patch('dumbapi_core.manager_inspiration.read', side_effect=reader):
            result = self.call('refresh', request_key='partial')
        pack = self.call('get'); self.assertEqual(pack['total'], 2)
        self.assertEqual(result['unavailable'], ['freecad']); self.assertNotIn('private://secret', json.dumps(pack))
        failed = next(s for s in pack['sources'] if s['id'] == 'freecad')
        self.assertLessEqual(failed['retry_after_seconds'], 60); self.assertGreater(failed['retry_after_seconds'], 0)
        self.assertIn('CAD project', failed['description'])

    def test_cross_process_lease_keeps_cached_page_readable(self):
        self.seed([self.row()])
        with self.manager.db() as db: self.manager.set_setting(db, LEASE, {'until': time.time() + 70, 'token': 'another'})
        self.assertTrue(Inspiration(self.config).get()['refreshing'])
        with patch('dumbapi_core.manager_inspiration.read') as reader:
            with self.assertRaises(APIError) as err: self.call('refresh', request_key='blocked')
            self.assertEqual(err.exception.code, 'inspiration_busy'); reader.assert_not_called()

    def test_refresh_preserves_preferences_changed_during_network_read(self):
        row = self.row(); self.seed([row])
        def reader(*_):
            other = Inspiration(self.config)
            other.mark(row['id'], 'save'); other.mark(row['id'], 'hide')
            return [dict(row, title='Updated preview')], 'Source'
        with patch('dumbapi_core.manager_inspiration.read', side_effect=reader): self.call('refresh', request_key='race')
        self.assertEqual(self.call('get')['total'], 0)
        self.call('mark', id=row['id'], action='show')
        self.assertTrue(self.call('get')['items'][0]['saved'])
        self.assertEqual(self.call('get')['items'][0]['title'], 'Updated preview')

    def test_filters_paging_save_disabled_sources_hide_and_restore(self):
        self.configure(['show-hn', 'freecad'])
        self.seed([self.row(str(i)) for i in range(9)] + [self.row('cad', 'freecad')])
        self.assertEqual(len(self.call('get')['items']), 6)
        self.assertEqual(len(self.call('get', offset=6)['items']), 4)
        self.assertEqual(self.call('get', category='cad')['total'], 1)
        row = self.call('get', query='cad')['items'][0]
        self.call('mark', id=row['id'], action='save'); self.configure(['show-hn'])
        self.assertEqual(self.call('get', saved=True)['total'], 1)
        self.call('mark', id=row['id'], action='hide'); self.assertEqual(self.call('get', saved=True)['total'], 1)
        self.assertEqual(self.call('get', category='cad')['total'], 0)
        self.call('mark', id=row['id'], action='show'); self.assertEqual(self.call('get', saved=True)['total'], 1)
        self.call('mark', id=row['id'], action='unsave'); self.assertEqual(self.call('get', category='cad')['total'], 0)

    def test_balancing_spreads_publishers_and_categories(self):
        rows = [self.row(str(i), source) for source in ('show-hn', 'typesafe', 'huggingface', 'freecad', 'mit-health') for i in range(4)]
        ordered = balanced(rows)
        self.assertEqual({r['category'] for r in ordered[:4]}, {'showcases', 'models', 'cad', 'science'})
        self.assertNotEqual(ordered[1]['source_id'], ordered[5]['source_id'])
        undated = [dict(self.row('z', 'typesafe'), published_at=None, source_order=0), dict(self.row('a', 'typesafe'), published_at=None, source_order=1)]
        self.assertEqual(balanced(undated)[0]['source_order'], 0)

    def test_stash_preserves_source_and_edited_goal_without_active_context_or_actions(self):
        row = self.row(); self.seed([row])
        with patch('dumbapi_core.t3.T3.send', side_effect=AssertionError('No send')):
            result = self.call('stash', id=row['id'], title='Try the rendering technique', goal='Measure readability in our UI.', project='sample', request_key='stash-1')
        itch = result['itch']; self.assertEqual(itch['project'], 'sample')
        self.assertEqual(itch['desired_outcome'], 'Measure readability in our UI.')
        self.assertIn(row['url'], itch['original']); self.assertEqual(itch['evidence'][0]['excerpt'], row['excerpt'])
        self.assertEqual(itch['state'], 'open'); self.assertEqual(itch['outcomes'], [])
        self.assertTrue(self.call('get', saved=True)['items'][0]['saved'])
        recovered = self.call('stash', id=row['id'], title=itch['title'], goal=itch['desired_outcome'], project='sample', request_key='stash-1')
        self.assertEqual(recovered['itch']['id'], itch['id'])
        duplicate = self.call('stash', id=row['id'], title='Different title', project='sample', request_key='stash-2')
        self.assertTrue(duplicate['existing']); self.assertEqual(duplicate['itch']['id'], itch['id'])
        with self.assertRaises(APIError): self.call('stash', id=row['id'], title='Other', request_key='stash-1')
        with self.assertRaises(APIError): self.call('stash', id=row['id'], title='Other', project='missing', request_key='bad')

    def test_shelf_limit_and_cache_eviction_keep_saved_items(self):
        self.seed([dict(self.row('s' + str(i)), saved=True) for i in range(100)])
        # seed deliberately supplies the final flag below; normal seed defaults to unsaved.
        with self.manager.db() as db:
            for r in self.service.rows(db): r['saved'] = True; self.manager.put(db, 'inspiration', r)
        extra = self.row('extra'); self.seed([extra])
        with self.assertRaises(APIError): self.call('mark', id=extra['id'], action='save')
        with self.assertRaises(APIError): self.call('stash', id=extra['id'], title='Full', request_key='full')
        with self.manager.db() as db:
            for i in range(260): self.manager.put(db, 'inspiration', dict(self.row('u' + str(i)), saved=False))
        with patch('dumbapi_core.manager_inspiration.read', return_value=([], 'Empty source')):
            self.call('refresh', request_key='evict')
        with self.manager.db() as db:
            self.assertEqual(len(self.service.rows(db)), 340)
        self.assertEqual(self.call('get', saved=True)['total'], 100)

    def test_opt_in_ranking_is_one_batch_and_unchanged_preview_is_not_reranked(self):
        row = self.row(); self.configure(['show-hn'], rank=True)
        with patch('dumbapi_core.manager_inspiration.read', return_value=([row], 'Source')), patch('dumbapi_core.manager_inspiration.rank', return_value=({row['id']: 2.5}, {'state': 'ranked'})) as ranking:
            self.call('refresh', request_key='ranked')
            self.assertEqual(len(ranking.call_args.args[1]), 1)
            self.due(); self.call('refresh', request_key='unchanged')
            self.assertEqual(ranking.call_args.args[1], [])
        self.assertEqual(self.call('get')['items'][0]['relevance'], 2.5)

    def test_jev_validates_scores_and_never_returns_secret_or_errors(self):
        rows = [self.row(str(i)) for i in range(20)]
        with patch('dumbapi_core.manager_ai.jev_key', return_value='private-key'), patch('dumbapi_core.browser.service_json') as service:
            def result(_url, payload, _key, **_):
                ids = list(payload['questions'])
                self.assertEqual(len(ids), 12); self.assertEqual(set(payload['state']), {'interests', 'previews'})
                return {'answers': {ids[0]: {'score': 2.4}, ids[1]: {'score': True}, ids[2]: {'score': float('nan')}, ids[3]: {'score': 9}}}
            service.side_effect = result
            scores, status = rank(self.config, rows, 'CAD')
            self.assertEqual(list(scores.values()), [2.4]); self.assertNotIn('private-key', json.dumps(status))
            service.side_effect = RuntimeError('private-key')
            self.assertEqual(rank(self.config, rows, 'CAD')[1]['state'], 'unavailable')
        with patch('dumbapi_core.manager_ai.jev_key', return_value=''):
            self.assertEqual(rank(self.config, rows, 'CAD')[1]['state'], 'unconfigured')


if __name__ == '__main__': unittest.main()
