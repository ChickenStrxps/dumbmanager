import json
import tempfile
import threading
import unittest
from contextlib import ExitStack
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from dumbapi_core.browser import Browser, installed_browser
from dumbapi_core.browser_mercury import propose
from dumbapi_core.common import APIError, Config


def move(operation='done', **overrides):
    return {'operation':operation,'node':'','text':'','destination':'','tab':'','key':'','message':'Done','needs_review':False,**overrides}


class MercuryContractTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.config=Config(Path(self.temp.name),Path(self.temp.name)/'state')
        self.page={'url':'https://example.com','title':'Editor','text':'Write a short bio','nodes':[
            {'id':'n1','kind':'textarea','label':'Bio','editable':True},
            {'id':'n2','kind':'button','label':'Publish'},
            {'id':'n3','kind':'select','label':'Theme','options':[{'value':'pink','label':'Pink'}]},
            {'id':'n4','kind':'input','input_type':'checkbox','label':'Animate'}]}

    def run_plan(self, output, **kw):
        with patch('dumbapi_core.typing_generator.settings',return_value={'provider':'inception'}),patch('dumbapi_core.typing_generator.TypingKeyStore.load',return_value='synthetic-key'),patch('dumbapi_core.browser_mercury.service_json',return_value={'choices':[{'message':{'content':json.dumps(output)}}]}) as service:
            result=propose(self.config,kw.get('goal','Write a friendly bio'),self.page,[],kw.get('history','[]'))
            payload=service.call_args.args[1];self.assertEqual(payload['model'],'mercury-3')
            self.assertNotIn('synthetic-key',json.dumps(result))
            return result

    def test_generated_field_text_and_final_click_review(self):
        r=self.run_plan(move('fill',node='n1',text='Building useful things, one pixel at a time.'))
        self.assertEqual(r['action']['text'],'Building useful things, one pixel at a time.')
        self.assertTrue(self.run_plan(move('node',node='n2'))['needs_review'])
        self.assertTrue(self.run_plan(move('key',key='Enter'))['needs_review'])
        self.assertIsNone(self.run_plan(move('answer',message='The page offers a bio editor.'))['action'])

    def test_grounding_and_strict_schema(self):
        for output in [move('node',node='fake'),move('fill',node='n2'),move('select',node='n3',text='invented'),
                       move('check',node='n4',text='yes'),move('navigate',destination='https://attacker.test/secret'),
                       move('key',key='F12'),move('evaluate'),{**move(), 'script':'fetch(secret)'}]:
            with self.subTest(output=output),self.assertRaises(APIError):self.run_plan(output)
        with self.assertRaises(APIError):self.run_plan(move(),history='["not a move"]')

    def test_named_sites_are_not_limited_to_preset_destinations(self):
        for goal,url in [('Go on X','https://x.com/'),('Open Figma','https://figma.com/'),
                         ('Open Itch','https://itch.io/'),('Open a named project site','https://a-new-project.community/')]:
            with self.subTest(goal=goal):
                r=self.run_plan(move('navigate',destination=url),goal=goal)
                self.assertEqual(r['action'],{'operation':'navigate','url':url})
        r=self.run_plan(move('new_tab',destination='https://figma.com'),goal='Open Figma in a new tab')
        self.assertEqual(r['action'],{'operation':'new_tab','url':'https://figma.com/'})

    def test_search_discovers_unfamiliar_sites_without_inventing_a_domain(self):
        r=self.run_plan(move('search',text='Midnight Drift Workshop'),goal='Open Midnight Drift Workshop')
        self.assertEqual(r['action'],{'operation':'navigate','url':'https://duckduckgo.com/?q=Midnight%20Drift%20Workshop'})
        with self.assertRaises(APIError):self.run_plan(move('search',text='page secret'),goal='Open Midnight Drift Workshop')
        with self.assertRaises(APIError):self.run_plan(move('search',text=''),goal='Open a site')

    def test_supplied_paths_work_but_inferred_addresses_cannot_embed_page_data(self):
        url='http://127.0.0.1:8783/local/page?query=hello'
        self.assertEqual(self.run_plan(move('navigate',destination=url),goal='Go to '+url)['action']['url'],url)
        for url in ['file:///C:/private','javascript:alert(1)','https://user:pass@x.com/',
                    'https://x.com/?page=secret','https://x.com/secret','https://x.com/#private',
                    'http://figma.com/','https://127.0.0.1/','https://local.internal/']:
            with self.subTest(url=url),self.assertRaises(APIError):self.run_plan(move('navigate',destination=url),goal='Go on X')

    def test_disconnected_and_upstream_errors_do_not_leak(self):
        with patch('dumbapi_core.typing_generator.settings',return_value={'provider':'off'}),patch('dumbapi_core.browser_mercury.service_json') as service:
            with self.assertRaises(APIError):propose(self.config,'Hi',self.page,[],'[]')
            service.assert_not_called()
        with patch('dumbapi_core.typing_generator.settings',return_value={'provider':'inception'}),patch('dumbapi_core.typing_generator.TypingKeyStore.load',return_value='synthetic-key'),patch('dumbapi_core.browser_mercury.service_json',side_effect=RuntimeError('synthetic-key raw body')):
            with self.assertRaises(APIError) as caught:propose(self.config,'Hi',self.page,[],'[]')
            self.assertNotIn('synthetic-key',str(caught.exception))


PAGE=b'''<!doctype html><title>Profile editor</title><h1>Profile editor</h1>
<label>Bio<textarea id="bio">private existing field text</textarea></label>
<label>Theme<select id="theme"><option value="dark">Dark</option><option value="pink">Pink</option></select></label>
<label>Animate<input id="animate" type="checkbox"></label><input type="password" value="never-send-password">
<button onclick="document.querySelector('h1').textContent='Preview ready'">Preview</button>
<button onclick="document.body.dataset.posts='1'">Publish</button>'''


@unittest.skipUnless(installed_browser(),'Installed Edge needed')
class MercuryBrowserTest(unittest.TestCase):
    def test_grounded_form_moves_privacy_review_staleness_and_single_use(self):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                self.send_response(200);self.send_header('Content-Type','text/html');self.end_headers();self.wfile.write(PAGE)
        with tempfile.TemporaryDirectory() as tmp,ExitStack() as stack:
            server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
            stack.callback(server.server_close);stack.callback(server.shutdown)
            b=Browser(Config(Path(tmp),Path(tmp)/'state'));stack.callback(b.stop)
            s=b.start(f'http://127.0.0.1:{server.server_port}/')
            stack.enter_context(patch('dumbapi_core.typing_generator.settings',return_value={'provider':'inception'}))
            stack.enter_context(patch('dumbapi_core.typing_generator.TypingKeyStore.load',return_value='synthetic-key'))
            self.assertTrue(b.status()['mercury_connected'])
            history=[]
            for op,label,text in [('fill','Bio','Small tools. Big pixel energy.'),('select','Theme','pink'),('check','Animate','true'),('node','Preview','')]:
                def response(url,payload,key,timeout):
                    self.assertNotIn('private existing field text',json.dumps(payload));self.assertNotIn('never-send-password',json.dumps(payload))
                    scope=json.loads(payload['messages'][1]['content']);node=next(n['id'] for n in scope['page']['controls'] if n['label']==label)
                    return {'choices':[{'message':{'content':json.dumps(move(op,node=node,text=text))}}]}
                with patch('dumbapi_core.browser_mercury.service_json',side_effect=response):proposal=b.plan('Draft a profile and preview it',s['snapshot'],json.dumps(history))
                s=b.apply(proposal['id']);history.append({'operation':op,'node':proposal['action']['node'],'text':text})
                with self.assertRaises(APIError):b.apply(proposal['id'])
            with b._page() as cdp:
                actual=cdp.call('Runtime.evaluate',{'expression':"JSON.stringify([document.querySelector('#bio').value,document.querySelector('#theme').value,document.querySelector('#animate').checked,document.querySelector('h1').textContent,document.body.dataset.posts||''])",'returnByValue':True})['result']['value']
            self.assertEqual(json.loads(actual),['Small tools. Big pixel energy.','pink',True,'Preview ready',''])
            target=next(n['id'] for n in s['nodes'] if n['label']=='Publish')
            with patch('dumbapi_core.browser_mercury.service_json',return_value={'choices':[{'message':{'content':json.dumps(move('node',node=target))}}]}):proposal=b.plan('Publish this profile',s['snapshot'])
            self.assertTrue(proposal['needs_review'])
            with self.assertRaises(APIError) as caught:b.apply(proposal['id'])
            self.assertEqual(caught.exception.code,'browser_review')
            # A changed layout rejects a stale action before dispatch, even after review.
            with b._page() as cdp:cdp.call('Runtime.evaluate',{'expression':"document.querySelector('button').style.marginTop='30px'"})
            with self.assertRaises(APIError) as caught:b.apply(proposal['id'],reviewed=True)
            self.assertEqual(caught.exception.code,'browser_stale')


if __name__=='__main__':unittest.main()
