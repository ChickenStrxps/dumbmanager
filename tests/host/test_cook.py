from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'backend'))
from dumbapi_core.app import App
from dumbapi_core.common import APIError, Config, atomic_json
from cook_control import Cook


class CookTest(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        base=Path(temporary.name);hub=base/'DumbAPI';hub.mkdir()
        self.app=App(Config(hub,base/'state'));self.cook=Cook(self.app)
        row=self.app.call('manager.capture',{'title':'Test itch'})
        self.args={'id':row['id'],'thread_id':'12345678-1234-4234-8234-123456789abc','request_key':'global-cook','message':'Fix this','video_mode':'frameboard'}

    def prepare(self):
        self.cook.control({'action':'prepare','owner':'popup','args':self.args})

    def test_missing_expired_closed_or_other_popup_cannot_be_sent(self):
        with self.assertRaises(APIError):self.cook.control({'action':'send'})
        self.prepare()
        with self.assertRaises(APIError):self.cook.control({'action':'send','owner':'other','request_key':'global-cook'})
        self.cook.target['expires']=0
        with self.assertRaises(APIError):self.cook.control({'action':'send'})
        self.prepare();self.cook.control({'action':'clear','owner':'popup'})
        with self.assertRaises(APIError):self.cook.control({'action':'send'})

    def test_evidence_target_does_not_require_a_thread_or_send_and_is_owner_scoped(self):
        self.assertEqual(self.cook.control({'action':'evidence_target'}),{})
        self.cook.control({'action':'focus','id':self.args['id'],'owner':'popup','activate':True})
        self.assertEqual(self.cook.control({'action':'evidence_target'})['id'],self.args['id'])
        self.cook.control({'action':'clear','owner':'popup'})
        self.assertEqual(self.cook.control({'action':'evidence_target'})['id'],self.args['id'])
        self.cook.control({'action':'unfocus','owner':'other'})
        self.assertTrue(self.cook.control({'action':'evidence_target'}))
        self.cook.control({'action':'unfocus','owner':'popup'})
        self.assertFalse(self.cook.control({'action':'evidence_target'}))
        self.cook.control({'action':'focus','id':self.args['id'],'owner':'popup'})
        self.cook.evidence['expires']=0
        self.assertFalse(self.cook.control({'action':'evidence_target'}))


    def test_global_trigger_and_popup_button_share_one_background_send_and_receipt(self):
        self.prepare();release=threading.Event();entered=threading.Event();original=self.app.call;calls=[]
        def call(name,args):
            if name!='manager.send':return original(name,args)
            calls.append(dict(args));entered.set();release.wait(3)
            return {'accepted':True,'thread_id':args['thread_id'],'message_id':'fixture'}
        with patch.object(self.app,'call',side_effect=call):
            self.assertTrue(self.cook.control({'action':'send'})['busy'])
            self.assertTrue(entered.wait(2))
            self.assertTrue(self.cook.control({'action':'send','owner':'popup','request_key':'global-cook'})['busy'])
            self.cook.control({'action':'clear','owner':'popup'});release.set()
            for _ in range(100):
                status=self.cook.control({'action':'status','request_key':'global-cook'})
                if not status['busy']:break
                time.sleep(.01)
            self.assertTrue(status['result']['accepted']);self.assertEqual(calls,[{**self.args,'followup':''}])
            self.prepare();self.assertTrue(self.cook.control({'action':'send'})['result']['accepted'])
            self.assertEqual(len(calls),1)
            with self.assertRaises(APIError):self.cook.control({'action':'prepare','owner':'popup','args':{**self.args,'message':'Different'}})

    def test_background_heartbeat_cannot_steal_a_more_recent_popup(self):
        self.prepare()
        other={**self.args,'request_key':'second-popup'}
        self.assertFalse(self.cook.control({'action':'prepare','owner':'other','args':other})['ready'])
        self.assertEqual(self.cook.target['owner'],'popup')
        self.assertTrue(self.cook.control({'action':'prepare','owner':'other','args':other,'activate':True})['ready'])
        self.cook.control({'action':'clear','owner':'popup'})
        self.assertEqual(self.cook.target['owner'],'other')
        self.assertFalse(self.cook.control({'action':'prepare','owner':'popup','args':self.args})['ready'])
