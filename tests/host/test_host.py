import http.client
import json
import re
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/"backend"))
from app import make_server
from dumbapi_core.common import Config, atomic_json
from dumbapi_core.common import APIError


class HostTest(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        base=Path(self.temporary.name)
        hub=base/"DumbAPI"
        hub.mkdir()
        self.server=make_server(0,Config(hub,base/"state"))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.port=self.server.server_port

    def tearDown(self):
        self.server.shutdown()
        self.server.replay.disarm()
        self.server.server_close()
        self.thread.join()
        self.temporary.cleanup()

    def http(self,path="/",value=None,headers=None):
        connection=http.client.HTTPConnection("127.0.0.1",self.port,timeout=5)
        body=json.dumps(value) if value is not None else None
        connection.request("POST" if value is not None else "GET",path,body,headers or {})
        response=connection.getresponse()
        result=response.status,dict(response.getheaders()),response.read()
        connection.close()
        return result

    def session(self):
        status,headers,_=self.http()
        self.assertEqual(status,200)
        return {"Cookie":headers["Set-Cookie"].split(";")[0],"X-DumbManager":"1","Content-Type":"application/json"}

    def test_bridge_settings_are_available_without_exposing_workflow_dispatch(self):
        headers=self.session()
        self.assertEqual(self.http('/bridge.js',headers=headers)[0],200)
        status,_,body=self.http('/api/call',{'name':'bridge.status','args':{}},headers)
        self.assertEqual(status,200);self.assertFalse(json.loads(body)['enabled'])
        self.assertEqual(self.http('/api/call',{'name':'bridge.discord.commands','args':{}},headers)[0],200)
        self.assertEqual(self.http('/api/call',{'name':'bridge.send','args':{}},headers)[0],403)

    def test_shared_smoke_art_is_served_as_one_fixed_script_only(self):
        status, headers, body = self.http('/ascii-smoke.js')
        self.assertEqual(status,200)
        self.assertIn('javascript',headers['Content-Type'])
        self.assertIn(b'DMAsciiSmoke',body)
        self.assertEqual(self.http('/dumbapi_core/ascii_smoke.js')[0],404)

    def test_distribution_setting_is_served_and_lists_no_credentials(self):
        self.assertEqual(self.http('/t3-settings.js')[0], 200)
        data = Path(self.temporary.name) / 'state'
        atomic_json(data / 't3-connection.json', {'url':'http://127.0.0.1:3773', 'token':'private-fixture'})
        status, _, body = self.http('/api/call', {'name':'t3.distributions', 'args':{}}, self.session())
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['selected'], 't3')
        self.assertNotIn(b'private-fixture', body)


    def test_inspiration_assets_and_local_cache_are_accessible_with_session(self):
        for path in ('/inspiration.js', '/inspiration.css'):
            self.assertEqual(self.http(path)[0], 200)
        headers = self.session()
        value = {'name': 'manager.inspiration.get', 'args': {}}
        status, _, body = self.http('/api/call', value, headers)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['total'], 0)
        self.assertEqual(self.http('/api/call', value)[0], 403)

    def test_cookie_requires_same_origin_header_and_loopback_host(self):
        headers=self.session()
        value={"name":"manager.state","args":{}}
        self.assertEqual(self.http("/api/call",value,headers)[0],200)
        self.assertEqual(self.http("/api/call",value,{"Cookie":headers["Cookie"]})[0],403)
        self.assertEqual(self.http("/api/call",value,{**headers,"Origin":"https://elsewhere.example"})[0],403)
        self.assertEqual(self.http("/api/call",value,{**headers,"Host":"attacker.example"})[0],403)

    def test_startup_recovery_is_in_html_with_a_unique_csp_nonce(self):
        seen=[]
        for _ in range(2):
            status,headers,body=self.http()
            self.assertEqual(status,200)
            nonce=re.search(rb'<script nonce="([A-Za-z0-9_-]+)">',body).group(1).decode()
            self.assertIn("'nonce-"+nonce+"'",headers['Content-Security-Policy'])
            self.assertNotIn("'unsafe-inline'",headers['Content-Security-Policy'])
            self.assertIn(b'/app.js?retry=',body)
            self.assertNotIn(b'<!-- STARTUP_RECOVERY -->',body)
            seen.append(nonce)
        self.assertNotEqual(*seen)

    def test_provider_backoff_reaches_the_browser_without_upstream_details(self):
        error=APIError('Mercury is rate-limited. Your goal is kept.','mercury_rate_limited',429)
        error.retry_after_ms=12000
        with patch('app.App.call',side_effect=error):
            status,_,body=self.http('/api/call',{'name':'browser.status','args':{}},self.session())
        self.assertEqual(status,429)
        self.assertEqual(json.loads(body)['retry_after_ms'],12000)

    def test_ui_does_not_expose_publishing_or_arbitrary_capabilities(self):
        headers=self.session()
        for name in ["social.schedule","storage.decompress","source.read","catalog.refresh"]:
            self.assertEqual(self.http("/api/call",{"name":name,"args":{}},headers)[0],403)

    def test_git_is_authenticated_and_only_fixed_capabilities_are_exposed(self):
        value={'name':'git.projects','args':{}}
        self.assertEqual(self.http('/api/call',value)[0],403)
        self.assertEqual(self.http('/api/call',value,self.session())[0],200)
        self.assertEqual(self.http('/api/call',{'name':'git.exec','args':{}},self.session())[0],403)
        self.assertEqual(self.http('/api/call',{'name':'git.action','args':{'project':'dumbapi','operation':'shell','snapshot':'x','request_key':'test-key'}},self.session())[0],400)
        self.assertEqual(self.http('/git.js')[0],200)

    def test_ai_settings_and_actions_require_owner_session(self):
        value={'name':'ai.integrations.list','args':{}}
        self.assertEqual(self.http('/api/call',value)[0],403)
        status,_,raw=self.http('/api/call',value,self.session())
        self.assertEqual(status,200)
        self.assertTrue(all(not p['enabled'] and not p['credential_saved'] for p in json.loads(raw)['items']))
        for name in ('ai.integrations.configure','ai.approvals.decide','ai.sessions.start'):
            self.assertEqual(self.http('/api/call',{'name':name,'args':{}})[0],403)
        self.assertEqual(self.http('/api/call',value,{**self.session(),'Origin':'https://untrusted.example'})[0],403)
        for path in ('/ai.js','/voice.js','/pcm-worklet.js'):
            self.assertEqual(self.http(path)[0],200)
        status,headers,body=self.http()
        self.assertIn('connect-src \'self\' https://api.openai.com wss://generativelanguage.googleapis.com;',headers['Content-Security-Policy'])
        self.assertIn(b'/voice.js',body)

    def test_native_controls_require_session_and_only_pass_fixed_actions(self):
        with patch('native_control.control',return_value={'running':True,'bindings':{}}) as control:
            self.assertEqual(self.http('/api/native',{'action':'test'})[0],403)
            control.assert_not_called()
            self.assertEqual(self.http('/api/native',{'action':'test'},self.session())[0],200)
            self.assertEqual(control.call_args.args[1],'test')
        self.assertEqual(self.http('/api/native',{'action':'shell'},self.session())[0],400)

    def test_browser_is_authenticated_with_fixed_actions_and_server_side_key(self):
        value={'name':'browser.status','args':{}}
        self.assertEqual(self.http('/api/call',value)[0],403)
        self.assertEqual(self.http('/api/call',value,self.session())[0],200)
        self.assertEqual(self.http('/api/call',{'name':'browser.evaluate','args':{}},self.session())[0],403)
        self.assertEqual(self.http('/api/call',{'name':'browser.action','args':{'operation':'shell'}},self.session())[0],400)
        status,_,body=self.http('/api/call',{'name':'browser.connect','args':{'api_key':'fixture-only-key'}},self.session())
        self.assertEqual(status,200);self.assertNotIn(b'fixture-only-key',body)
        self.assertEqual(self.http('/browse.js')[0],200)

    def test_global_cook_requires_session_and_an_open_prepared_itch(self):
        self.assertEqual(self.http('/api/cook',{'action':'send'})[0],403)
        self.assertEqual(self.http('/api/cook',{'action':'send'},self.session())[0],409)
        self.assertEqual(self.http('/api/cook',{'action':'shell'},self.session())[0],400)

    def test_visuals_require_authenticated_request_and_have_opaque_sandbox(self):
        value={"thread_id":"12345678-1234-4234-8234-123456789abc","attachment_id":"visual"}
        self.assertEqual(self.http('/api/preview',value)[0],403)
        with patch('dumbapi_core.t3.T3.preview',return_value={'id':'visual','title':'Concept','height':400,'html':'<!doctype html><script>window.test=1</script>'}):
            status,_,body=self.http('/api/preview',value,self.session())
        self.assertEqual(status,200)
        route=json.loads(body)['url'];self.assertTrue(route.startswith('/preview/'))
        status,headers,body=self.http(route)
        self.assertEqual(status,200);self.assertIn(b'window.test',body)
        policy=headers['Content-Security-Policy']
        self.assertIn('sandbox allow-scripts',policy);self.assertNotIn('allow-same-origin',policy)
        self.assertIn("connect-src 'none'",policy);self.assertIn("frame-ancestors 'self'",policy)
        self.assertEqual(self.http('/preview/guessed')[0],404)

    def test_binary_upload_is_authenticated_and_rejects_oversized_body(self):
        status,headers,_=self.http('/api/upload',{'not':'binary'})
        self.assertEqual(status,403);self.assertEqual(headers['Connection'],'close')
        connection=http.client.HTTPConnection('127.0.0.1',self.port,timeout=5)
        headers={**self.session(),'Content-Length':str(51*1024*1024)}
        connection.request('POST','/api/upload',b'',headers)
        response=connection.getresponse();self.assertEqual(response.status,413);response.read();connection.close()

    def test_expired_session_closes_unread_body_before_refresh(self):
        connection=http.client.HTTPConnection("127.0.0.1",self.port,timeout=5)
        connection.request("POST","/api/call",json.dumps({"name":"manager.capture","args":{"title":"stale session"}}),
                           {"Cookie":"dm_session_"+str(self.port)+"=expired","X-DumbManager":"1","Content-Type":"application/json"})
        response=connection.getresponse()
        self.assertEqual(response.status,403)
        self.assertEqual(response.getheader("Connection"),"close")
        self.assertEqual(json.loads(response.read())["error"],"Local session required.")
        # A client can refresh its cookie and immediately save on the same client
        # object: no leftover JSON becomes a bogus request/HTML 501 response.
        connection.request("GET","/")
        response=connection.getresponse()
        self.assertEqual(response.status,200)
        cookie=response.getheader("Set-Cookie").split(";")[0]
        response.read()
        connection.request("POST","/api/call",json.dumps({"name":"manager.capture","args":{"title":"after refresh","use_active":False}}),
                           {"Cookie":cookie,"X-DumbManager":"1","Content-Type":"application/json"})
        response=connection.getresponse()
        self.assertEqual(response.status,200)
        self.assertEqual(json.loads(response.read())["title"],"after refresh")
        connection.close()

    def test_capture_persists_and_invalid_input_is_reviewable_error(self):
        headers=self.session()
        status,_,raw=self.http("/api/call",{"name":"manager.capture","args":{"title":"HTTP save","use_active":False,"request_key":"http-once"}},headers)
        self.assertEqual(status,200)
        row=json.loads(raw)
        status,_,raw=self.http("/api/call",{"name":"manager.get","args":{"id":row["id"]}},headers)
        self.assertEqual(json.loads(raw)["title"],"HTTP save")
        self.assertEqual(self.http("/api/call",{"name":"manager.update","args":{"id":row["id"],"changes":'{"state":"resolved"}'}},headers)[0],400)

    def test_itch_upload_and_read_are_authenticated_and_need_no_thread(self):
        def upload(headers):
            connection=http.client.HTTPConnection('127.0.0.1',self.port,timeout=5)
            connection.request('POST','/api/itch-upload',b'local image fixture',headers)
            response=connection.getresponse();result=response.status,response.read();connection.close();return result
        self.assertEqual(upload({'X-File-Type':'image/png'})[0],403)
        headers={**self.session(),'X-File-Type':'image/png','X-File-Name':'fish.png'}
        with patch('dumbapi_core.t3.T3.connection',side_effect=AssertionError('Must not connect')):
            status,raw=upload(headers)
        self.assertEqual(status,200)
        attachment=json.loads(raw)['attachment']
        args={'attachments':json.dumps([attachment['id']]),'request_key':'local-media'}
        status,_,raw=self.http('/api/call',{'name':'manager.capture','args':args},headers)
        self.assertEqual(status,200);self.assertEqual(json.loads(raw)['attachments'],[attachment])
        self.assertEqual(self.http('/api/itch-media',{'id':attachment['id']})[0],403)
        status,meta,raw=self.http('/api/itch-media',{'id':attachment['id']},headers)
        self.assertEqual((status,raw),(200,b'local image fixture'))
        self.assertEqual(meta['Content-Type'],'image/png')
        self.assertEqual(self.http('/api/itch-media',{'id':'../../desktop.token'},headers)[0],400)

    def test_static_paths_are_allowlisted_and_replay_is_off(self):
        headers=self.session()
        self.assertEqual(self.http("/../app.py")[0],404)
        status,_,raw=self.http("/api/replay",{"action":"status"},headers)
        self.assertEqual(status,200)
        self.assertFalse(json.loads(raw)["armed"])


if __name__=="__main__":
    unittest.main()

