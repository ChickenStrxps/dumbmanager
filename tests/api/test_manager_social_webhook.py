import base64
import json
import tempfile
import threading
import unittest
from email.parser import BytesParser
from email.policy import default
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from dumbapi_core.app import App
from dumbapi_core.common import APIError, Config
from dumbapi_core.manager import Manager
from dumbapi_core import manager_social_gif as animation
from dumbapi_core import manager_social_webhook as webhook

GIF = b'GIF89a' + b'\0'*20 + b'NETSCAPE2.0' + b';'
META = {'theme':'Shark week','key':'shark','events':['greg'],'frames':72,'seconds':3.6,'width':1200,'height':675}


class WebhookTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name); self.app = App(Config(root, root/'data'))
        row = self.app.call('manager.capture', {'title':'Cards with **details**','project':'demo','use_active':False})
        self.itch = self.app.call('manager.update', {'id':row['id'],'changes':json.dumps({'state':'ready'})})
        draft = self.app.call('manager.social.draft', {'itch_id':self.itch['id']})
        self.draft = self.app.call('manager.social.save', {'id':draft['id'],'expected_version':draft['version'],
            'headline':'Cards with **details**','summary':'• **Sharper** cards\n• A [picture](https://example.com)',
            'caption':'Ready to test.\n\nCards with **details**\n• **Sharper** cards\n• A [picture](https://example.com)'})
        self.draw = patch.object(animation, 'draw', return_value=(GIF, META)).start()
        self.addCleanup(patch.stopall)
        self.g = self.app.call('manager.social.gif', {'id':self.draft['id'],'vibe':2})
        self.requests = []; self.code = 200; self.reply = {'id':'123','channel_id':'456','guild_id':'789'}; self.headers = {}
        owner = self
        class Receiver(BaseHTTPRequestHandler):
            def log_message(self, *_): pass
            def do_POST(self):
                raw = self.rfile.read(int(self.headers['Content-Length']))
                parsed = BytesParser(policy=default).parsebytes(('Content-Type: '+self.headers['Content-Type']+'\r\nMIME-Version: 1.0\r\n\r\n').encode()+raw)
                parts = {p.get_param('name',header='content-disposition'):p for p in parsed.iter_parts()}
                owner.requests.append({'path':self.path,'parts':parts,'key':self.headers.get('Idempotency-Key')})
                body = json.dumps(owner.reply).encode()
                self.send_response(owner.code)
                for k,v in owner.headers.items(): self.send_header(k,v)
                self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
        self.server = ThreadingHTTPServer(('127.0.0.1',0),Receiver)
        threading.Thread(target=self.server.serve_forever,daemon=True).start()
        self.addCleanup(self.server.server_close); self.addCleanup(self.server.shutdown)
        self.url = f'http://127.0.0.1:{self.server.server_port}/hooks/test-secret?thread_id=456'
        self.options = self.configure()

    def call(self, op, **args):
        return self.app.call('manager.social.webhook_'+op, args)

    def configure(self, **args):
        version = self.call('settings')['version']
        return self.call('configure', **{'expected_version':version, 'url':self.url, **args})

    def send(self, **args):
        return self.call('send', **{'id':self.draft['id'],'expected_version':self.draft['version'],
            'settings_version':self.options['version'],'sha256':self.g['sha256'],'vibe':2,
            'request_key':'webhook-request-123','confirm':True,**args})

    def test_settings_encrypted_persisted_redacted_and_concurrent_edits_rejected(self):
        public = self.call('settings')
        self.assertTrue(public['configured']); self.assertNotIn('test-secret',str(public))
        manager = Manager(self.app.config)
        with manager.db() as db:
            saved = manager.setting(db,webhook.SETTING)
            self.assertNotIn('test-secret',json.dumps(saved)); self.assertEqual(webhook.endpoint(saved),self.url)
        self.app = App(self.app.config); self.assertEqual(public,self.call('settings'))
        with self.assertRaises(APIError):self.call('configure',expected_version=0,url=self.url)
        kept = self.call('configure',expected_version=public['version'],layout='plain',bullets=False,markdown=False)
        self.assertTrue(kept['configured']); self.assertEqual(kept['layout'],'plain')
        cleared = self.call('configure',expected_version=kept['version'],clear_url=True)
        self.assertFalse(cleared['configured']); self.assertEqual(cleared['destination'],'')

    def test_invalid_destinations_leave_previous_settings_untouched(self):
        before = self.call('settings')
        for url in ('file:///secret','http://example.com/hook','https://name:secret@example.com/','https://example.com/#token','https://example.com/\r\nX-Test:1','https://example.com:0/hook'):
            with self.assertRaises(APIError):self.configure(url=url)
        self.assertEqual(before,self.call('settings')); self.assertEqual(self.requests,[])

    def test_discord_upload_exact_gif_embed_ack_and_retry_deduplication(self):
        result = self.send(); self.assertEqual(result['state'],'sent')
        self.assertEqual(result['message_url'],'https://discord.com/channels/789/456/123')
        request = self.requests[0]; self.assertIn('wait=true',request['path']);self.assertIn('thread_id=456',request['path'])
        parts = request['parts']; payload = json.loads(parts['payload_json'].get_payload(decode=True))
        self.assertEqual(parts['files[0]'].get_payload(decode=True),base64.b64decode(self.g['gif']))
        self.assertEqual(parts['files[0]'].get_content_type(),'image/gif')
        self.assertEqual(payload['allowed_mentions'],{'parse':[]})
        self.assertEqual(payload['embeds'][0]['description'],'- **Sharper** cards\n- A [picture](https://example.com)')
        self.assertEqual(payload['embeds'][0]['image']['url'],'attachment://'+self.g['filename'])
        self.assertEqual(payload['embeds'][0]['footer']['text'],'Ready to test')
        self.assertEqual(self.send(),result); self.assertEqual(len(self.requests),1)
        self.assertEqual(self.call('status',request_key='webhook-request-123'),result)
        self.assertEqual(self.call('status',id=self.draft['id']),result)
        self.assertNotIn('test-secret',json.dumps(result))
        self.assertEqual(self.app.call('manager.get',{'id':self.itch['id']}),self.itch)
        self.assertNotEqual(self.app.call('manager.social.draft',{'itch_id':self.itch['id']})['posting']['state'],'posted')

    def test_plain_generic_no_bullets_or_markdown_and_no_network_preview(self):
        self.options = self.configure(format='generic',layout='plain',bullets=False,markdown=False)
        preview = self.call('preview',id=self.draft['id'],expected_version=self.draft['version'])
        self.assertEqual(self.requests,[])
        text = preview['payload']['text']; self.assertNotIn('**',text);self.assertNotIn('•',text)
        self.assertIn('A picture (https://example.com)',text)
        result = self.send();self.assertEqual(result['state'],'sent')
        parts = self.requests[0]['parts'];self.assertEqual(parts['file'].get_payload(decode=True),GIF)
        self.assertNotIn('wait=',self.requests[0]['path'])
        payload = json.loads(parts['payload_json'].get_payload(decode=True));self.assertEqual(payload,preview['payload'])
        self.assertNotIn('embed',payload)

    def test_selected_flow_uploads_exact_preview_and_cannot_change_on_retry(self):
        self.draw.return_value = (GIF[:-1]+b'flow;', {**META,'key':'flow','theme':'Water flow'})
        flow = self.app.call('manager.social.gif', {'id':self.draft['id'],'vibe':2,'theme':'flow'})
        self.assertNotEqual(flow['sha256'], self.g['sha256'])
        with self.assertRaises(APIError):self.send(sha256=flow['sha256'])
        self.assertEqual(self.requests, [])
        result = self.send(sha256=flow['sha256'],theme='flow')
        self.assertEqual(result['state'],'sent')
        self.assertEqual(self.requests[0]['parts']['files[0]'].get_payload(decode=True),base64.b64decode(flow['gif']))
        self.assertEqual(self.send(sha256=flow['sha256'],theme='flow'),result)
        with self.assertRaises(APIError):self.send(sha256=flow['sha256'])
        self.assertEqual(len(self.requests),1)

    def test_all_format_choices_and_plain_caption_preservation(self):
        for layout in ('embed','plain'):
            for bullets in (True,False):
                for markdown in (True,False):
                    self.options = self.configure(layout=layout,bullets=bullets,markdown=markdown)
                    payload = self.call('preview',id=self.draft['id'],expected_version=self.draft['version'])['payload']
                    text = payload['embeds'][0]['description'] if layout=='embed' else payload['content']
                    self.assertEqual('**Sharper**' in text,markdown)
                    self.assertEqual(any(l.startswith(('- ','• ')) for l in text.splitlines()),bullets)
                    if layout=='plain':self.assertIn('Ready to test.',text)

    def test_confirmation_stale_inputs_wrong_gif_and_reopened_itch_block_network(self):
        for args in ({'confirm':False},{'expected_version':999},{'settings_version':999},{'sha256':'0'*64}):
            with self.assertRaises(APIError):self.send(**args)
        self.assertEqual(self.requests,[])
        self.app.call('manager.update',{'id':self.itch['id'],'changes':json.dumps({'title':'Changed after preview'})})
        with self.assertRaises(APIError):self.send()
        self.assertEqual(self.requests,[])

    def test_receiver_errors_and_rate_limit_do_not_retry_or_expose_secret(self):
        self.code = 429; self.headers = {'Retry-After':'2'};self.reply = {'url':self.url}
        result = self.send();self.assertEqual(result['state'],'failed');self.assertEqual(result['retry_after'],2)
        self.assertNotIn('test-secret',json.dumps(result))
        self.assertEqual(self.send(),result)
        with self.assertRaises(APIError):self.send(request_key='another-request-123')
        self.assertEqual(len(self.requests),1)

    def test_uncertain_server_and_lost_response_are_not_resent(self):
        self.code = 500; self.reply = {'url':self.url}
        result = self.send();self.assertEqual(result['state'],'unknown')
        self.assertEqual(self.send(),result);self.assertEqual(len(self.requests),1)
        with self.assertRaises(APIError):self.send(sha256='0'*64)
        self.app = App(self.app.config);self.assertEqual(self.send(),result)

    def test_redirect_is_not_followed_and_discord_requires_message_receipt(self):
        self.code = 302; self.headers = {'Location':self.url+'/redirect'}
        result = self.send();self.assertEqual(result['state'],'failed');self.assertEqual(len(self.requests),1)
        self.code = 200;self.headers = {};self.reply = {}
        result = self.send(request_key='request-without-ack');self.assertEqual(result['state'],'unknown')
        self.assertEqual(len(self.requests),2)

    def test_network_timeout_has_uncertain_receipt_and_stable_retry(self):
        with patch.object(webhook,'build_opener') as opener:
            opener.return_value.open.side_effect = TimeoutError('secret '+self.url)
            result = self.send()
            self.assertEqual(result['state'],'unknown');self.assertNotIn('test-secret',str(result))
            self.assertEqual(self.send(),result);self.assertEqual(opener.return_value.open.call_count,1)

    def test_concurrent_identical_sends_upload_once(self):
        started = threading.Event(); finish = threading.Event(); results = []
        original = webhook.deliver
        def delayed(*args):
            started.set();finish.wait(5);return original(*args)
        with patch.object(webhook,'deliver',side_effect=delayed):
            worker = threading.Thread(target=lambda:results.append(self.send()))
            worker.start();self.assertTrue(started.wait(3))
            pending = self.send();self.assertEqual(pending['state'],'sending')
            finish.set();worker.join(5);self.assertFalse(worker.is_alive())
        self.assertEqual(results[0]['state'],'sent');self.assertEqual(len(self.requests),1)


if __name__=='__main__':unittest.main()
