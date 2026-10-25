import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from dumbapi_core.app import App
from dumbapi_core.common import APIError, Config
from dumbapi_core.manager_social_copy import clip


class ChangelogTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name); self.app = App(Config(root, root/'data'))
        self.itch = self.app.call('manager.capture', {'project':'secretproject','title':'The ability to add a small picture to completion posts','use_active':False})
        self.update(state='ready', plan=[{'id':'picture','text':'Add a small work picture to completion posts.','done':True}, {'id':'future','text':'Publish everything automatically.','done':False}], evidence=[r'Review ready. Saved C:\private\receipt.png person@example.com https://private.example sk_abcdefghijklmnopqrstuv'])
        self.draft = self.app.call('manager.social.draft',{'itch_id':self.itch['id']})

    def update(self, **changes):
        self.itch = self.app.call('manager.update',{'id':self.itch['id'],'changes':json.dumps(changes)})

    def preview(self):
        return self.app.call('manager.social.preview',{'id':self.draft['id']})

    def save(self, draft, **changes):
        return self.app.call('manager.social.save',{'id':draft['id'],'expected_version':draft['version'],**{k:draft[k] for k in ('headline','summary','caption')},**changes})

    @patch('dumbapi_core.manager_social_copy.generate')
    def test_automatic_once_and_private_context_excluded(self, generate):
        generate.return_value={'headline':'Work pictures in completion posts','summary':'• Work picture beside the changelog\n• Editable privacy masks'}
        first=self.preview(); second=self.preview()
        self.assertEqual(first['draft'],second['draft']); self.assertEqual(generate.call_count,1)
        d=first['draft']; self.assertEqual(d['headline'],'Work pictures in completion posts')
        self.assertTrue(d['caption'].startswith('Ready to test.'))
        self.assertEqual(d['copy_source'],'mercury');self.assertIn('Work picture beside the changelog',first['svg'])
        self.assertEqual(d['summary'].count('•'),2);self.assertNotIn('…',d['caption'])
        scope=generate.call_args.args[1]; raw=json.dumps(scope)
        for private in ('person@example.com','private.example','receipt.png','abcdefghijklmnopqrstuv','Publish everything'):
            self.assertNotIn(private,raw)
        self.assertEqual(self.app.call('manager.get',{'id':self.itch['id']})['outcomes'],[])

    @patch('dumbapi_core.manager_social_copy.generate')
    def test_manual_and_legacy_edits_survive_reopen_and_acceptance(self, generate):
        edited=self.save(self.draft,headline='My title',caption='My carefully written post')
        self.assertTrue(edited['copy_edited']); self.assertEqual(self.preview()['draft']['caption'],edited['caption'])
        self.app.call('manager.complete',{'id':self.itch['id'],'accepted':True,'summary':'Picture added.'})
        self.assertEqual(self.preview()['draft']['caption'],edited['caption']);generate.assert_not_called()
        # Older records have no marker; non-default copy is still preserved.
        from dumbapi_core.manager import Manager
        m=Manager(self.app.config)
        with m.db() as db:
            row=m.get(db,edited['id']);row.pop('copy_edited');m.put(db,'post_draft',row)
        self.assertEqual(self.preview()['draft']['headline'],'My title');generate.assert_not_called()

    @patch('dumbapi_core.manager_social_copy.generate')
    def test_failed_provider_has_short_durable_fallback_and_keeps_image_metadata(self, generate):
        generate.side_effect=APIError('Unavailable')
        first=self.preview()['draft']; self.assertEqual(first['copy_source'],'local')
        self.assertNotIn('The ability to',first['headline']);self.assertLessEqual(len(first['caption']),280)
        self.assertEqual(first,self.preview()['draft']);self.assertEqual(generate.call_count,1)
        self.assertEqual(first['source_version'],self.draft['source_version'])
        with patch('dumbapi_core.manager_social_copy.time.time',return_value=first['copy_retry_at']+1):
            generate.side_effect=None
            generate.return_value={'headline':'Work pictures','summary':'Preview the actual result.'}
            self.assertEqual(self.preview()['draft']['copy_source'],'mercury')
        self.assertEqual(generate.call_count,2)

    @patch('dumbapi_core.manager_social_copy.generate')
    def test_concurrent_edit_is_not_overwritten_and_no_write_lock_during_model(self, generate):
        def write(config, scope):
            self.save(self.draft,caption='Typed while the model was working')
            return {'headline':'Old model output','summary':'Do not overwrite the edit.'}
        generate.side_effect=write
        d=self.preview()['draft'];self.assertEqual(d['caption'],'Typed while the model was working')
        self.assertNotIn('Old model output',d['headline'])

    @patch('dumbapi_core.manager_social_copy.generate')
    def test_reopened_or_changed_source_during_generation_preserves_copy(self, generate):
        def change(config, scope):
            self.app.call('manager.repeat',{'id':self.itch['id']})
            return {'headline':'Do not apply','summary':'Stale result'}
        generate.side_effect=change
        with self.assertRaises(APIError):self.preview()
        row=self.app.call('manager.get',{'id':self.draft['id']})
        self.assertEqual(row['caption'],self.draft['caption'])

    @patch('dumbapi_core.manager_social_copy.generate')
    def test_parallel_previews_collapse_and_acceptance_refreshes_only_automatic_copy(self, generate):
        generate.return_value={'headline':'Work pictures','summary':'Preview the actual result.'}
        with ThreadPoolExecutor(max_workers=2) as pool:
            values=list(pool.map(lambda _:self.preview(),range(2)))
        self.assertEqual(generate.call_count,1);self.assertEqual(values[0]['draft'],values[1]['draft'])
        self.app.call('manager.complete',{'id':self.itch['id'],'accepted':True,'summary':'Work pictures show the result.'})
        self.assertTrue(self.preview()['draft']['caption'].startswith('Build update.'))
        self.assertEqual(generate.call_count,2)

    @patch('dumbapi_core.typing_generator.TypingKeyStore.load',return_value='synthetic-key')
    @patch('dumbapi_core.typing_generator.settings',return_value={'provider':'inception'})
    @patch('dumbapi_core.mercury_client.request')
    def test_transport_contract_grounding_validation_and_no_unsafe_claim(self, request, settings, key):
        def response(value): return {'choices':[{'message':{'content':json.dumps(value)}}]}
        request.return_value=response({'headline':'Work pictures','bullets':['Show a small result preview','Editable privacy masks'],'facts':['step-0']})
        d=self.preview()['draft'];self.assertEqual(d['copy_source'],'mercury')
        payload=request.call_args.args[2]
        self.assertEqual(payload['model'],'mercury-3');self.assertEqual(payload['max_completion_tokens'],1200)
        from dumbapi_core.manager_social_copy import generate, scope
        data=scope(self.itch,'review')
        for bad in ({'headline':'Shipped work pictures','bullets':['All done.'],'facts':['step-0']},
                    {'headline':'Pictures','bullets':['See https://private.example'],'facts':['step-0']},
                    {'headline':'Pictures','bullets':['Done'],'facts':['invented']},
                    {'headline':'Pictures','bullets':['Done'],'facts':[]},
                    {'headline':'Pictures','bullets':['Useful description '*20],'facts':['step-0']},
                    {'headline':'Pictures','bullets':['An incomplete sentence…'],'facts':['step-0']}):
            request.return_value=response(bad)
            with self.assertRaises(ValueError):generate(self.app.config,data)
        request.return_value=response({'headline':'Ready to test: Work pictures','bullets':['Useful description'],'facts':['step-0']})
        generated=generate(self.app.config,data)
        self.assertEqual(generated['headline'],'Work pictures');self.assertLessEqual(len(generated['summary']),150)
        request.return_value={'choices':[{'message':{'content':'{}'},'finish_reason':'length'}]}
        with self.assertRaises(ValueError):generate(self.app.config,data)

    @patch('dumbapi_core.manager_social_copy.generate')
    def test_previous_automatic_draft_migrates_without_losing_image_or_manual_copy(self, generate):
        from dumbapi_core.manager import Manager
        manager=Manager(self.app.config)
        with manager.db() as db:
            old=manager.get(db,self.draft['id']);old.update(copy_style='changelog-v1',copy_stage='review',copy_source='mercury',summary='An old cut-off sentence…')
            manager.put(db,'post_draft',old)
        generate.return_value={'headline':'Work pictures','summary':'• Result preview\n• Privacy masks'}
        migrated=self.preview()['draft']
        self.assertEqual(migrated['copy_style'],'changelog-v2');self.assertNotIn('…',migrated['summary'])
        self.save(migrated,summary='My own complete description.')
        self.preview();self.assertEqual(generate.call_count,1)

    @patch('dumbapi_core.manager_social_copy.generate')
    def test_unicode_caption_keeps_whole_bullet_instead_of_cutoff(self, generate):
        generate.return_value={'headline':'魚'*70,'summary':'• '+'魚'*70+'\n• '+'魚'*70}
        draft=self.preview()['draft']
        self.assertLessEqual(sum(1 if ord(c)<128 else 2 for c in draft['caption']),280)
        self.assertIn('魚'*70,draft['caption']);self.assertNotIn('…',draft['caption'])

    def test_unicode_budget_is_conservative(self):
        for text in ('longword'*100, 'a long description '*100, '魚'*300, '🐟 detail '*100):
            result=clip(text,278)
            self.assertLessEqual(sum(1 if ord(c)<128 else 2 for c in result),280)


if __name__=='__main__':unittest.main()
