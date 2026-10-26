import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from dumbapi_core.app import App
from dumbapi_core.common import APIError, Config
from dumbapi_core import typing_generator as gen
from dumbapi_core.typing_ideas import qualities


class QualitySuggestionTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        base=Path(self.temp.name);(base/'hub').mkdir()
        self.config=Config(base/'hub',base/'state')
        self.app=App(self.config)
        self.keys=patch.object(gen.TypingKeyStore,'load',return_value='fixture-inception-key');self.keys.start()
        self.options=patch.object(gen,'settings',return_value={'provider':'inception','model':'mercury-3','revision':'qa'});self.options.start()
        with gen._lock:gen._cache.clear();gen._active.clear();gen._next.clear()

    def tearDown(self):
        self.options.stop();self.keys.stop();self.temp.cleanup()

    def reply(self, values, field='qualities'):
        return {'choices':[{'message':{'content':json.dumps({field:values})}}]}

    def test_arbitrary_subject_and_novel_qualities_are_model_output(self):
        ctx={'project':'spectralweaver','task':'Build a phase lattice editor','testing':'Drag eigenmodes; preserve phase coherence.'}
        novel=['phase-coherent eigenmode snapping','a chromatic interference preview','adaptive spectral interpolation']
        with patch.object(gen,'service_json',return_value=self.reply(novel)) as request:
            result=gen.generate(self.config,'A phase lattice with ',ctx,{'thread':'one'})
        self.assertEqual([r['quality'] for r in result['items']],novel)
        url,payload,key=request.call_args.args
        self.assertEqual((url,payload['model'],key),(gen.ENDPOINT,'mercury-3','fixture-inception-key'))
        self.assertEqual(payload['reasoning_effort'],'instant')
        self.assertEqual(payload['response_format']['type'],'json_schema')
        self.assertEqual(json.loads(payload['messages'][1]['content'])['context']['task'],ctx['task'])
        self.assertFalse(any(word in payload['messages'][0]['content'].lower() for word in ('fish','gmod','teeth','workshop')))

    def test_prefix_validation_partial_quality_and_no_static_fallback(self):
        typed='  A control with a violet '
        found=qualities(typed,['a violet interference pulse','a green glow','a violet ',{},'a violet\nline','a violet interference pulse'])
        self.assertEqual([r['text'] for r in found],['  A control with a violet interference pulse'])
        self.assertEqual(qualities('A fish with '),[])
        self.assertEqual(qualities('A button with '),[])
        self.assertEqual(qualities('Open https://x.with ',['something']),[])
        self.assertTrue(all(len(r['text'])<=500 for r in qualities('x'*480+' with ',['x'*130])))

    def test_unfinished_sentence_generates_location_without_a_quality_connector(self):
        typed='Add the ability to post directly from '
        context={'project':'dumbmanager','task':'Integrate social media posting into Side quests',
                 'surface':'Side quests / social media tab', 'recent':[{'role':'user','text':'Keep posting near the account stats'}]}
        with patch.object(gen,'service_json',return_value=self.reply(['the Side quests social media tab','the account stats panel'],'suffixes')) as request:
            result=gen.generate(self.config,typed,context,{'thread':'current'})
        self.assertEqual(result['items'][0]['text'],typed+'the Side quests social media tab')
        self.assertEqual(result['items'][0]['kind'],'continuation')
        payload=json.loads(request.call_args.args[1]['messages'][1]['content'])
        self.assertNotIn('fragment',payload);self.assertEqual(payload['context']['surface'],context['surface'])
        self.assertNotIn('Side quests',request.call_args.args[1]['messages'][0]['content'])
        self.assertEqual(qualities(typed+'the Si',[typed+'the Side quests social media tab'])[0]['text'],typed+'the Side quests social media tab')

    def test_sentence_cache_refines_but_surface_changes_recompute(self):
        ctx={'task':'Build a flexible exporter','surface':'Archive / exports'}
        with patch.object(gen,'service_json',return_value=self.reply(['the export panel'],'suffixes')) as request:
            gen.generate(self.config,'Export the results from ',ctx)
            refined=gen.generate(self.config,'Export the results from the ex',ctx)
            self.assertTrue(refined['cached']);self.assertEqual(request.call_count,1)
            with gen._lock:gen._next.clear()
            gen.generate(self.config,'Export the results from ',{**ctx,'surface':'Workspace / analysis'})
            self.assertEqual(request.call_count,2)

    def test_refinement_cache_is_exact_context_and_thread_scoped(self):
        ctx={'project':'orbit','task':'Tune an orbital control'}
        with patch.object(gen,'service_json',return_value=self.reply(['adaptive orbit damping','adaptive orbit trails'])) as request:
            one=gen.generate(self.config,'A control with ',ctx,{'thread':'one'})
            two=gen.generate(self.config,'A control with adaptive orbit d',ctx,{'thread':'one'})
            self.assertEqual(two['items'][0]['text'],'A control with adaptive orbit damping')
            self.assertTrue(two['cached']);self.assertEqual(request.call_count,1)
            for scope,identity in [({'project':'other','task':'Tune a cloth simulation'},{'thread':'one'}),(ctx,{'thread':'two'}),({'project':'orbit','task':'Changed task'},{'thread':'one'})]:
                with gen._lock:gen._next.clear()
                gen.generate(self.config,'A control with ',scope,identity)
            self.assertEqual(request.call_count,4)
        self.assertEqual(one['status'],'ready')

    def test_broadening_a_fragment_requests_new_diverse_ideas(self):
        with patch.object(gen,'service_json',return_value=self.reply(['a violet outline'])) as request:
            gen.generate(self.config,'A control with a violet',{'task':'Build a control'})
            with gen._lock:gen._next.clear()
            gen.generate(self.config,'A control with ',{'task':'Build a control'})
            self.assertEqual(request.call_count,2)

    def test_failures_and_malformed_results_fall_back_without_exposing_body(self):
        for response in ({},self.reply([{}]),self.reply(['unmatched']),'invalid'):
            with self.subTest(response=response):
                with gen._lock:gen._cache.clear();gen._next.clear()
                with patch.object(gen,'service_json',return_value=response):
                    result=gen.generate(self.config,'A control with a violet',{'task':'Build a control'})
                self.assertEqual(result['items'],[])
        with gen._lock:gen._cache.clear();gen._next.clear()
        with patch.object(gen,'service_json',side_effect=RuntimeError('private upstream body fixture-inception-key')):
            result=gen.generate(self.config,'A control with ',{'task':'Build a control'})
        self.assertEqual(result['status'],'unavailable')
        self.assertNotIn('private',json.dumps(result));self.assertNotIn('fixture-inception-key',json.dumps(result))

    def test_disabled_or_incomplete_opening_does_not_contact_provider(self):
        with patch.object(gen,'service_json') as request:
            self.assertEqual(gen.generate(self.config,'Normal sentence',{'task':'Work'})['status'],'idle')
            with patch.object(gen,'settings',return_value={'provider':'off'}):
                self.assertEqual(gen.generate(self.config,'A control with ',{'task':'Work'})['status'],'not_configured')
            request.assert_not_called()

    def test_screenshot_opening_works_without_project_or_chat_destination(self):
        self.app.call('manager.context.publish',{'project':'private-other-project',
            'thread_id':'12345678-1234-4234-8234-123456789abc','task':'Unrelated private task','select':True})
        typed='Add 2 ascii horses with '
        with patch.object(gen,'service_json',return_value=self.reply(['flowing manes and staggered gallops','subtle hoof dust trails'])) as request, \
                patch('dumbapi_core.t3.T3.read') as read:
            result=self.app.call('manager.suggest',{'text':typed,'mode':'chat','candidates':'["Unrelated private task"]'})
        self.assertEqual(result['source'],'mercury')
        self.assertEqual(result['items'][0]['text'],typed+'flowing manes and staggered gallops')
        self.assertEqual(result['context']['thread_id'],'')
        scope=json.loads(request.call_args.args[1]['messages'][1]['content'])
        self.assertEqual(scope['context']['task'],'')
        self.assertNotIn('Unrelated private',json.dumps(scope))
        read.assert_not_called()

    def test_selected_project_enriches_words_without_a_published_context(self):
        with patch.object(gen,'service_json',return_value=self.reply(['an undoable group toggle'])) as request:
            result=self.app.call('manager.suggest',{'text':'A selection tool with ','project':'neweditor','mode':'chat'})
        self.assertEqual(result['source'],'mercury')
        self.assertEqual(json.loads(request.call_args.args[1]['messages'][1]['content'])['context']['project'],'neweditor')

    def test_explicit_more_ideas_bypasses_cache_but_preserves_spacing(self):
        typed='A control with '
        with patch.object(gen,'service_json',side_effect=[self.reply(['a violet outline']),self.reply(['a focus halo'])]) as request:
            gen.generate(self.config,typed,{})
            self.assertTrue(gen.generate(self.config,typed,{})['cached'])
            self.assertEqual(gen.generate(self.config,typed,{},fresh=True)['status'],'waiting')
            self.assertEqual(request.call_count,1)
            with gen._lock:gen._next.clear()
            more=gen.generate(self.config,typed,{},fresh=True)
            self.assertEqual(more['items'][0]['text'],typed+'a focus halo')
            self.assertEqual(json.loads(request.call_args.args[1]['messages'][1]['content'])['previous_suggestions'],['a violet outline'])
            self.assertEqual(request.call_count,2)
            self.assertTrue(gen.generate(self.config,typed,{})['cached'])

    def test_manual_refresh_honors_provider_cooldown_without_exposing_errors(self):
        from dumbapi_core.mercury_client import _limited
        with patch.object(gen,'request',side_effect=_limited(5)) as request:
            result=self.app.call('manager.suggest',{'text':'A control with ','mode':'chat','fresh':True})
        self.assertEqual(result['generation']['status'],'rate_limited')
        self.assertEqual(result['generation']['retry_after_ms'],5000)
        self.assertNotIn('private body',json.dumps(result))
        request.assert_called_once()

    def test_one_active_request_and_capture_stays_available(self):
        entered,release=threading.Event(),threading.Event()
        def wait(*args,**kwargs):entered.set();release.wait(3);return self.reply(['phase-aware snapping'])
        with patch.object(gen,'service_json',side_effect=wait),ThreadPoolExecutor(2) as pool:
            first=pool.submit(gen.generate,self.config,'A lattice with ',{'task':'Build a lattice'})
            self.assertTrue(entered.wait(1))
            try:
                self.assertEqual(gen.generate(self.config,'A different control with ',{'task':'Work'})['status'],'waiting')
                row=self.app.call('manager.capture',{'title':'Capture without waiting','use_active':False})
                self.assertEqual(row['title'],'Capture without waiting')
            finally:release.set()
            self.assertEqual(first.result(2)['status'],'ready')

    def test_manager_returns_generated_ideas_without_second_ranking_call(self):
        ctx=self.app.call('manager.context.publish',{'project':'unknown','thread_id':'12345678-1234-4234-8234-123456789abc','task':'Build a phase lattice'})
        with patch.object(gen,'service_json',return_value=self.reply(['phase-coherent snapping'])),patch('dumbapi_core.manager_ai.ask') as jev:
            result=self.app.call('manager.suggest',{'text':'A lattice with ','project':'unknown','context_id':ctx['id']})
        self.assertEqual(result['source'],'mercury');self.assertEqual(result['items'][0]['text'],'A lattice with phase-coherent snapping')
        jev.assert_not_called()

    def test_context_is_bounded_and_setup_credentials_are_omitted(self):
        scope=gen.state('A control with ',{'task':'x'*3000,'recent':[{'role':'user','text':'sk_fixture_key_never_send_123456789'}]*20})
        self.assertEqual(len(scope['context']['task']),1500)
        self.assertEqual(len(scope['context']['recent']),4)
        self.assertNotIn('sk_fixture',json.dumps(scope))
        self.assertNotIn('workspace',scope['context'])
        scope=gen.state('A control with sk_fixture_key_never_send_123456789',{})
        self.assertNotIn('sk_fixture',json.dumps(scope))


class MercuryCredentialsTest(unittest.TestCase):
    def test_model_setup_persists_separately_and_forget_keeps_jev(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'hub').mkdir();config=Config(root/'hub',root/'data')
            from dumbapi_core.browser_credentials import JevKeyStore
            JevKeyStore(config.data).save('fixture-jev-original')
            result=gen.configure(config,api_key='fixture-inception-private')
            self.assertTrue(result['configured']);self.assertNotIn('fixture',json.dumps(result))
            self.assertNotIn(b'fixture-inception-private',gen.TypingKeyStore(config.data).path.read_bytes())
            self.assertEqual(gen.TypingKeyStore(config.data).load(),'fixture-inception-private')
            gen.configure(config,enabled=False)
            self.assertFalse(gen.status(config)['configured']);self.assertTrue(gen.status(config)['key_saved'])
            gen.configure(config,enabled=True)
            self.assertTrue(gen.status(config)['configured'])
            with self.assertRaises(APIError):gen.configure(config,api_key='invalid key')
            self.assertEqual(gen.TypingKeyStore(config.data).load(),'fixture-inception-private')
            gen.configure(config,forget=True)
            self.assertFalse(gen.status(config)['key_saved'])
            self.assertEqual(JevKeyStore(config.data).load(),'fixture-jev-original')
