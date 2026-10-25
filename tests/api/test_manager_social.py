import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from dumbapi_core.app import App
from dumbapi_core.common import APIError, Config


class SocialTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.app=App(Config(self.root,self.root/'data'))

    def itch(self, state='ready', title='Stop the mobile overflow'):
        row=self.app.call('manager.capture',{'project':'demo','title':title,'use_active':False})
        if state=='resolved':
            return self.app.call('manager.complete',{'id':row['id'],'accepted':True,'summary':'Cards now fit on my phone.'})
        return self.app.call('manager.update',{'id':row['id'],'changes':json.dumps({'state':state})})

    def draft(self, row):
        return self.app.call('manager.social.draft',{'itch_id':row['id']})

    def save(self, draft, **changes):
        return self.app.call('manager.social.save',{'id':draft['id'],'expected_version':draft['version'],
            **{k:draft[k] for k in ('headline','summary','caption')},**changes})

    def preview(self, draft):
        return self.app.call('manager.social.preview',{'id':draft['id']})

    def test_accepted_and_review_are_distinct_and_no_private_context_copied(self):
        self.itch('open');review=self.itch();accepted=self.itch('resolved')
        listing=self.app.call('manager.social.list',{'limit':1})
        self.assertEqual(listing['total'],2);self.assertEqual(listing['next_offset'],1)
        self.assertEqual(self.app.call('manager.social.list',{'project':'missing'})['total'],0)
        d=self.draft(review);self.assertEqual(d['stage'],'review')
        self.assertNotIn('One less dumb thing',d['caption'])
        self.assertNotIn('SO BACK',self.preview(d)['svg'])
        a=self.draft(accepted);self.assertEqual(a['summary'],'Cards now fit on my phone.')
        self.assertEqual(a['stage'],'accepted');self.assertIn('SO BACK',self.preview(a)['svg'])
        current=self.app.call('manager.get',{'id':review['id']})
        self.assertEqual(current['state'],'ready');self.assertEqual(current['outcomes'],[])
        with self.assertRaises(APIError):self.draft(self.itch('working'))

    def test_draft_reopen_save_retry_conflict_and_reload(self):
        row=self.itch();d=self.draft(row);self.assertEqual(d['id'],self.draft(row)['id'])
        edited=self.save(d,caption='My edited caption')
        retried=self.save(d,caption='My edited caption');self.assertEqual(edited['version'],retried['version'])
        with self.assertRaises(APIError) as caught:self.save(d,caption='Clobber another edit')
        self.assertEqual(caught.exception.code,'conflict')
        self.app=App(self.app.config);self.assertEqual(self.draft(row)['caption'],'My edited caption')

    def test_portable_escaped_preview_no_paths_or_evidence_in_automatic_copy(self):
        row=self.itch(title='A <script>alert("x")</script> & emoji 🐟')
        self.app.call('manager.update',{'id':row['id'],'changes':json.dumps({'evidence':[r'C:\private\credentials.txt'],'next_step':'private testing notes','test_url':'http://127.0.0.1:8783'})})
        d=self.draft(row);d=self.save(d,caption='Unicode 🐟 & a #tag\nnext line',summary='Long & <unsafe> '+('detail '*110)[:550])
        p=self.preview(d);ET.fromstring(p['svg'])
        self.assertNotIn('<script>',p['svg']);self.assertNotIn('credentials',str(p));self.assertNotIn('127.0.0.1',str(p))
        self.assertNotIn('private testing notes',str(p));self.assertNotIn('<image',p['svg'])
        for link in p['composers'].values():self.assertEqual(parse_qs(urlsplit(link).query)['text'],[d['caption']])

    def test_changed_source_requires_review_and_reopened_work_cannot_export(self):
        row=self.itch('resolved');d=self.draft(row)
        self.app.call('manager.update',{'id':row['id'],'changes':json.dumps({'title':'Reviewed new title'})})
        self.assertTrue(self.preview(d)['draft']['source_changed'])
        saved=self.save(d,headline='Reviewed new title');self.assertFalse(saved['source_changed'])
        self.app.call('manager.repeat',{'id':row['id']})
        with self.assertRaises(APIError):self.preview(saved)
        with self.assertRaises(APIError):self.save(saved)
        self.assertEqual(self.app.call('manager.social.list')['total'],0)

    def test_inputs_bounded_and_unrelated_itch_cannot_be_used_as_draft(self):
        row=self.itch();d=self.draft(row)
        with self.assertRaises(APIError):self.save(d,caption='x'*2001)
        with self.assertRaises(APIError):self.save(d,headline='')
        with self.assertRaises(APIError):self.preview({'id':row['id']})
        with self.assertRaises(APIError):self.app.call('manager.social.preview',{'id':d['id'],'publish':True})

    def test_card_contains_all_manual_copy_with_and_without_picture(self):
        from dumbapi_core.manager_social import card
        import re
        for headline,summary in [('Long title '*12, 'A complete description with details. '*16),('魚'*120,'• '+'魚'*295+'\n• '+'x'*300),('unbroken'*15,'x'*600)]:
            for image in ('','data:image/png;base64,AA=='):
                svg=card({'headline':headline[:120],'summary':summary[:600],'stage':'review'},image)
                root=ET.fromstring(svg)
                for name,value,top,bottom in [('headline',headline[:120],175,315),('summary',summary[:600],342,482)]:
                    group=next(g for g in root.iter() if g.get('data-copy')==name)
                    content=''.join(t.text or '' for t in group)
                    self.assertEqual(re.sub(r'\s','',content),re.sub(r'\s','',value))
                    for t in group:
                        self.assertGreater(float(t.get('y')),top)
                        self.assertLessEqual(float(t.get('y')),bottom)
                self.assertNotIn('…',svg)

    def test_high_resolution_variety_stays_stable_without_external_assets(self):
        from dumbapi_core.manager_social import card
        creatures=set()
        for i in range(64):
            draft={'id':f'post-fixture-{i}','headline':'Small changes, less friction',
                   'summary':'• Paste the picture directly\n• Keep the caption editable','stage':'review'}
            svg=card(draft)
            self.assertEqual(svg,card(draft))
            root=ET.fromstring(svg)
            self.assertEqual((root.get('width'),root.get('height')),('2400','1260'))
            creatures.update(g.get('data-critter') for g in root.iter() if g.get('data-critter'))
            self.assertNotIn('http',svg.split('viewBox',1)[1])
            self.assertNotIn('post-fixture',svg)
            self.assertIn('READY TO TEST',svg)
        self.assertEqual(creatures,{'cat','crab','fish','ghost','frog','moth'})


if __name__=='__main__':unittest.main()
