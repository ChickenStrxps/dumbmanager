import http.client
import base64
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app import make_server
from dumbapi_core.common import Config
from phone_share import make_gateway


class PhoneTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        hub = root / 'DumbAPI'
        hub.mkdir()
        self.app = make_server(0, Config(hub, root / 'data'))
        self.gateway = make_gateway('test-invitation', time.time()+100, self.app.server_port, 0, False)
        self.gateway.origin = 'https://phone.example'
        self.threads = []
        for server in (self.app, self.gateway):
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.threads.append(thread)

    def tearDown(self):
        for server in (self.gateway, self.app):
            server.shutdown()
            server.server_close()
        self.app.replay.disarm()
        for thread in self.threads:
            thread.join()
        self.temp.cleanup()

    def request(self, path='/', body=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.gateway.server_port, timeout=5)
        connection.request('POST' if body is not None else 'GET', path,
                           body if isinstance(body,bytes) else json.dumps(body) if body is not None else None,
                           {'Host':'phone.example', **(headers or {})})
        response = connection.getresponse()
        value = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return value

    def session(self):
        status, headers, _ = self.request('/connect?key=test-invitation')
        self.assertEqual(status, 303)
        self.assertEqual(headers['Location'], '/')
        self.assertEqual(headers['Referrer-Policy'], 'no-referrer')
        phone = headers['Set-Cookie'].split(';')[0]
        status, headers, body = self.request(headers={'Cookie':phone})
        self.assertEqual(status, 200)
        self.assertIn(b'DumbManager', body)
        return {'Cookie':phone+'; '+headers['Set-Cookie'].split(';')[0],
                'X-DumbManager':'1', 'Content-Type':'application/json', 'Origin':'https://phone.example'}

    def test_invitation_required_for_html_api_and_private_media(self):
        for path in ('/', '/app.js', '/preview/anything'):
            self.assertEqual(self.request(path)[0], 403)
        self.assertEqual(self.request('/api/call', {'name':'manager.state','args':{}})[0], 403)
        self.assertEqual(self.request('/api/itch-media', {'id':'any'})[0], 403)
        self.assertEqual(self.request('/connect?key=wrong')[0], 403)
        self.assertEqual(self.request('/connect?key=%C3%A9')[0], 403)

    def test_paired_phone_uses_browser_session_and_can_capture_and_reload(self):
        headers = self.session()
        status, _, body = self.request('/api/call', {'name':'manager.capture','args':{'title':'Phone fixture'}}, headers)
        self.assertEqual(status, 200, body)
        saved = json.loads(body)['id']
        status, _, body = self.request('/api/call', {'name':'manager.get','args':{'id':saved}}, headers)
        self.assertEqual(status, 200, body)
        self.assertEqual(json.loads(body)['title'], 'Phone fixture')
        # A stale upstream cookie still renews through the normal index page.
        status, _, _ = self.request(headers={'Cookie':'dm_phone=test-invitation; dm_session_'+str(self.app.server_port)+'=stale'})
        self.assertEqual(status, 200)

    def test_phone_upload_keeps_file_metadata_and_saved_image_can_be_read(self):
        headers=self.session()
        png=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a6VQAAAAASUVORK5CYII=')
        status,_,body=self.request('/api/itch-upload',png,{**headers,'Content-Type':'image/png','X-Thread-Id':'@itch',
            'X-File-Name':'phone%20receipt.png','X-File-Type':'image/png','X-Video-Mode':'original'})
        self.assertEqual(status,200,body)
        attachment=json.loads(body)['attachment']
        self.assertEqual(attachment['name'],'phone receipt.png')
        self.assertEqual(attachment['mimeType'],'image/png')
        status,_,body=self.request('/api/call',{'name':'manager.capture','args':{'title':'Phone image fixture','attachments':json.dumps([attachment['id']])}},headers)
        self.assertEqual(status,200,body)
        status,_,body=self.request('/api/itch-media',{'id':attachment['id']},headers)
        self.assertEqual(status,200,body)
        self.assertEqual(body,png)

    def test_cross_origin_desktop_stop_arbitrary_hosts_and_oversize_are_blocked(self):
        headers = self.session()
        body = {'name':'manager.state','args':{}}
        self.assertEqual(self.request('/api/call', body, {**headers,'Origin':'https://attacker.example'})[0], 403)
        self.assertEqual(self.request('/api/call', body, {**headers,'Host':'attacker.example'})[0], 403)
        self.assertEqual(self.request('/api/call', body, {**headers,'X-DumbManager':''})[0], 403)
        self.assertEqual(self.request('/api/shutdown', {}, headers)[0], 403)
        self.assertEqual(self.request('http://other.example/', headers=headers)[0], 403)
        self.assertEqual(self.request('/api/upload', {}, {**headers,'Content-Length':str(52*1024*1024)})[0], 413)
        self.assertEqual(self.request('/api/upload', {}, {**headers,'Transfer-Encoding':'chunked'})[0], 411)

    def test_expired_link_revokes_existing_browser_cookie(self):
        headers = self.session()
        from unittest.mock import patch
        with patch('phone_share.time.time', return_value=time.time()+200):
            self.assertEqual(self.request(headers=headers)[0], 410)
            self.assertEqual(self.request('/connect?key=test-invitation')[0], 410)
