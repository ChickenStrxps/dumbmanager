"""Manual live relay checks with an isolated installed browser; no external sites/models."""
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from dumbapi_core.browser import Browser, installed_browser
from dumbapi_core.common import Config, APIError


class Page(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.send_header('Content-Type','text/html'); self.end_headers()
        self.wfile.write(b'''<title>Relay fixture</title><style>body{margin:0;height:2500px}#panel{position:fixed;right:0;top:0;width:300px;height:400px;overflow:auto}#inside{height:2000px}</style><button onclick="window.clicks=(window.clicks||0)+1">Count</button><input id="field"><div id="panel"><div id="inside">Nested scroll</div></div>''')
    def log_message(self,*args): pass


@unittest.skipUnless(installed_browser(), 'Installed Edge required')
class RelayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),Page)
        threading.Thread(target=cls.server.serve_forever,daemon=True).start()
        cls.url=f'http://127.0.0.1:{cls.server.server_port}/'
    @classmethod
    def tearDownClass(cls): cls.server.shutdown(); cls.server.server_close()
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); base=Path(self.tmp.name); (base/'hub').mkdir()
        self.b=Browser(Config(base/'hub',base/'data')); self.s=self.b.start(self.url)
    def tearDown(self): self.b.stop(); self.tmp.cleanup()
    def evaluate(self,expression):
        with self.b._page() as cdp: return cdp.call('Runtime.evaluate',{'expression':expression,'returnByValue':True})['result'].get('value')
    def test_frames_are_lightweight_preserve_grounding_and_do_not_keep_session_alive(self):
        before=self.b.last; token=self.b.snapshot_id
        with patch.object(self.b,'_read',side_effect=AssertionError('Live frame scanned DOM')),patch.object(self.b.cdp,'call',wraps=self.b.cdp.call) as calls:
            first=self.b.frame(); second=self.b.frame()
        self.assertEqual(self.b.last,before); self.assertEqual(self.b.snapshot_id,token)
        self.assertNotEqual(first['frame'],second['frame'])
        self.assertNotIn('Emulation.setDeviceMetricsOverride',[c.args[0] for c in calls.call_args_list])
        self.b.interact('click',first['frame'],x=25,y=10)
        self.assertEqual(self.evaluate('window.clicks'),1)
        with self.assertRaises(APIError): self.b.interact('click',first['frame'],x=25,y=10)
        self.assertEqual(self.evaluate('window.clicks'),1)
    def test_scroll_targets_nested_container_and_text_keys_stay_in_order(self):
        self.b.interact('scroll',self.s['frame'],x=1000,y=150,delta_y=300)
        deadline=time.monotonic()+2
        while time.monotonic()<deadline and not self.evaluate('document.querySelector("#panel").scrollTop'): time.sleep(.03)
        self.assertGreater(self.evaluate('document.querySelector("#panel").scrollTop'),0)
        self.assertEqual(self.evaluate('scrollY'),0)
        self.evaluate('document.querySelector("#field").focus()')
        for operation,args in [('type',{'text':'hello'}),('key',{'key':'Backspace'}),('type',{'text':'p'})]:
            self.b.interact(operation,self.b.frame()['frame'],**args)
        self.assertEqual(self.evaluate('document.querySelector("#field").value'),'hellp')
    def test_navigation_and_uncertain_input_never_replay_old_frames(self):
        old=self.s['frame']; self.b.action('navigate',url=self.url+'next')
        with self.assertRaises(APIError): self.b.interact('click',old,x=25,y=10)
        current=self.b.frame()['frame']; original=self.b.cdp.call
        def lost(method,params=None):
            result=original(method,params)
            if method=='Input.dispatchMouseEvent' and params['type']=='mouseReleased': raise OSError('lost response')
            return result
        with patch.object(self.b.cdp,'call',side_effect=lost),self.assertRaises(APIError): self.b.interact('click',current,x=25,y=10)
        with self.assertRaises(APIError): self.b.interact('click',current,x=25,y=10)
        self.assertEqual(self.evaluate('window.clicks'),1)


if __name__=='__main__': unittest.main()
