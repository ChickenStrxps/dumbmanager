import json
import tempfile
import threading
import unittest
from contextlib import ExitStack
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from dumbapi_core import browser as engine
from dumbapi_core.browser import Browser,installed_browser
from dumbapi_core.common import APIError,Config


PAGE=b'''<!doctype html><title>Directory</title><h1>Directory</h1>
<input aria-label="Bio" value="private-existing-field"><a href="/profile">Official account</a>
<button onclick="document.body.dataset.posts='1'">Publish</button>'''


@unittest.skipUnless(installed_browser(),'Installed Edge needed')
class HybridBrowserTest(unittest.TestCase):
    def setUp(self):
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                body=b'<!doctype html><title>Official profile</title><h1>Official profile</h1>' if self.path=='/profile' else PAGE
                self.send_response(200);self.send_header('Content-Type','text/html');self.end_headers();self.wfile.write(body)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        threading.Thread(target=self.server.serve_forever,daemon=True).start()
        self.stack.callback(self.server.server_close);self.stack.callback(self.server.shutdown)
        temp=self.stack.enter_context(tempfile.TemporaryDirectory())
        self.b=Browser(Config(data=Path(temp)));self.stack.callback(self.b.stop)
        self.s=self.b.start(f'http://127.0.0.1:{self.server.server_port}/');self.b.key='fixture-jev-key'
        self.real=engine.service_json;self.requests=[]

    def service(self,choose):
        def call(url,payload=None,key='',timeout=10):
            if not url.startswith('https://api.typesafe.ai/'):return self.real(url,payload,key,timeout)
            self.requests.append(payload)
            self.assertNotIn('private-existing-field',json.dumps(payload))
            choice=choose(payload)
            return {'model':'jev-latest','answers':{'next':{'type':'choice','choice':choice,'confidence':.95,'probabilities':{choice:1}}}}
        return call

    def test_navigation_then_done_never_contacts_rate_limited_mercury(self):
        def choose(p):
            if p['state']['completed_moves']:return 'done'
            return next(k for k,v in p['state']['actions'].items() if isinstance(v,dict) and v.get('label')=='Official account')
        with patch.object(engine,'service_json',side_effect=self.service(choose)),patch('dumbapi_core.browser_mercury.propose',side_effect=APIError('Limited','mercury_rate_limited',429)) as mercury:
            goal='Find the official account on this page and open its profile'
            first=self.b.plan(goal,self.s['snapshot']);self.assertEqual(first['engine'],'jev-latest')
            s=self.b.apply(first['id']);self.assertTrue(s['url'].endswith('/profile'))
            last=self.b.plan(goal,s['snapshot'],json.dumps([{'operation':'node','node':first['action']['node'],'url':s['url']}]))
            self.assertEqual(last['operation'],'done');self.assertIsNone(last['action']);mercury.assert_not_called()
        self.assertEqual(len(self.requests),2)

    def test_generated_text_uses_mercury_only_for_the_generation_step(self):
        def choose(p):return 'done' if p['state']['completed_moves'] else 'generate'
        def generated(config,goal,page,tabs,history):
            node=next(n for n in page['nodes'] if n['label']=='Bio')
            return {'action':{'operation':'fill','node':node['id'],'text':'Freshly drafted bio.'},'needs_review':False,'label':'Draft the bio','operation':'fill','engine':'mercury-3'}
        with patch.object(engine,'service_json',side_effect=self.service(choose)),patch('dumbapi_core.browser_mercury.propose',side_effect=generated) as mercury:
            goal='Write a playful bio';first=self.b.plan(goal,self.s['snapshot'])
            self.assertEqual(first['engine'],'mercury-3');s=self.b.apply(first['id'])
            last=self.b.plan(goal,s['snapshot'],json.dumps([{'operation':'fill','text':first['action']['text']}]))
            self.assertEqual(last['engine'],'jev-latest');mercury.assert_called_once()

    def test_final_click_still_requires_review_and_failed_planning_clears_it(self):
        choose=lambda p:next(k for k,v in p['state']['actions'].items() if isinstance(v,dict) and v.get('label')=='Publish')
        with patch.object(engine,'service_json',side_effect=self.service(choose)):
            result=self.b.plan('Publish this profile',self.s['snapshot']);self.assertTrue(result['needs_review'])
            with self.assertRaises(APIError) as caught:self.b.apply(result['id'])
            self.assertEqual(caught.exception.code,'browser_review')
        with patch.object(engine,'service_json',side_effect=self.service(lambda p:'generate')),patch('dumbapi_core.browser_mercury.propose',side_effect=APIError('Limited','mercury_rate_limited',429)):
            with self.assertRaises(APIError) as caught:self.b.plan('Write a new bio',self.s['snapshot'])
            self.assertEqual(caught.exception.code,'mercury_generation_limited')
            self.assertIsNone(self.b.suggestion)
        # An unrelated navigation goal remains available after the generation failure.
        with patch.object(engine,'service_json',side_effect=self.service(lambda p:'done')),patch('dumbapi_core.browser_mercury.propose') as mercury:
            self.assertIsNone(self.b.plan('Show this page',self.s['snapshot'])['action']);mercury.assert_not_called()

    def test_low_confidence_and_jev_outage_escalate_without_executing(self):
        safe={'action':None,'needs_review':False,'label':'Need a clearer goal.','operation':'blocked','engine':'mercury-3'}
        with patch.object(self.b,'suggest',return_value={'choice':'node','confidence':.2,'probability':.4}),patch('dumbapi_core.browser_mercury.propose',return_value=safe) as mercury:
            self.assertIsNone(self.b.plan('Do something',self.s['snapshot'])['action']);mercury.assert_called_once()
        with patch.object(self.b,'suggest',side_effect=APIError('Offline','jev_unavailable',503)),patch('dumbapi_core.browser_mercury.propose',return_value=safe) as mercury:
            self.assertIsNone(self.b.plan('Do something',self.s['snapshot'])['action']);mercury.assert_called_once()

    def test_overlapping_search_spans_do_not_escalate_clear_search_intent(self):
        def service(url,payload=None,key='',timeout=10):
            if not url.startswith('https://api.typesafe.ai/'):return self.real(url,payload,key,timeout)
            topic=next(k for k,v in payload['questions']['text']['criteria'].items() if v=='official X account')
            picks={'next':('search',.95),'destination':('google',.95),'text':(topic,.3)}
            return {'answers':{k:{'type':'choice','choice':v,'confidence':p,'probabilities':{v:p}} for k,(v,p) in picks.items()}}
        with patch.object(engine,'service_json',side_effect=service),patch('dumbapi_core.browser_mercury.propose') as mercury:
            result=self.b.plan('find the official X account on google',self.s['snapshot'])
            self.assertEqual(result['action']['url'],'https://www.google.com/search?q=official%20X%20account')
            mercury.assert_not_called()

    def test_site_challenge_stops_without_spending_a_generation_request(self):
        with patch.object(engine,'service_json',side_effect=self.service(lambda p:'blocked')),patch('dumbapi_core.browser_mercury.propose') as mercury:
            result=self.b.plan('Find an account',self.s['snapshot'])
            self.assertIsNone(result['action']);self.assertIn('manual check',result['label']);mercury.assert_not_called()
