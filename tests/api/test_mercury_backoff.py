import io
import json
import tempfile
import unittest
from email.message import Message
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from dumbapi_core import mercury_client as client, typing_generator as typing
from dumbapi_core.browser_mercury import propose
from dumbapi_core.common import APIError, Config


def limited(delay='60'):
    headers=Message();headers['Retry-After']=delay
    return HTTPError('https://provider.invalid',429,'private upstream body',headers,io.BytesIO(b'private-key'))


class MercuryBackoffTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.config=Config(data=Path(self.temp.name))
        self.page={'url':'about:blank','title':'about:blank','text':'','nodes':[]}
        with client._lock:client._cooldowns.clear()
        self.addCleanup(client._cooldowns.clear)
        with typing._lock:typing._cache.clear();typing._active.clear();typing._next.clear()
        self.clock=self.enterContext(patch.object(client.time,'monotonic',return_value=100))
        self.enterContext(patch.object(typing,'settings',return_value={'provider':'inception'}))
        self.enterContext(patch.object(typing.TypingKeyStore,'load',return_value='fixture-shared-key'))

    def test_browser_rate_limit_stops_typing_and_repeated_plans_until_expiry(self):
        goal='Find the official X account on the X website'
        with patch('dumbapi_core.browser_mercury.service_json',side_effect=limited()) as service:
            with self.assertRaises(APIError) as caught:propose(self.config,goal,self.page,[],'[]')
            self.assertEqual(caught.exception.code,'mercury_rate_limited')
            self.assertEqual(caught.exception.status,429)
            self.assertEqual(caught.exception.retry_after_ms,60000)
            self.assertNotIn('private',str(caught.exception))
            with self.assertRaises(APIError):propose(self.config,goal,self.page,[],'[]')
            self.assertEqual(service.call_count,1)
        with patch.object(typing,'service_json') as service:
            result=typing.generate(self.config,'A new button with ',{'task':'Build a manager'})
            self.assertEqual(result['status'],'rate_limited');self.assertEqual(result['items'],[])
            self.assertEqual(result['retry_after_ms'],60000);service.assert_not_called()
        self.clock.return_value=161
        move={'operation':'navigate','node':'','text':'','destination':'https://x.com/','tab':'','key':'','message':'Open X','needs_review':False}
        with patch('dumbapi_core.browser_mercury.service_json',return_value={'choices':[{'message':{'content':json.dumps(move)}}]}) as service:
            result=propose(self.config,goal,self.page,[],'[]')
            self.assertEqual(result['action']['url'],'https://x.com/');service.assert_called_once()

    def test_typing_rate_limit_is_shared_with_browsing(self):
        with patch.object(typing,'service_json',side_effect=limited('12')) as service:
            result=typing.generate(self.config,'A button with ',{'task':'Build a manager'})
            self.assertEqual(result['status'],'rate_limited');service.assert_called_once()
        with patch('dumbapi_core.browser_mercury.service_json') as service:
            with self.assertRaises(APIError) as caught:propose(self.config,'Open a website',self.page,[],'[]')
            self.assertEqual(caught.exception.retry_after_ms,12000);service.assert_not_called()

    def test_retry_after_http_date_malformed_and_missing(self):
        with patch.object(client.time,'time',return_value=0):
            for value,seconds in [('7',7),('Thu, 01 Jan 1970 00:00:13 GMT',13),('bad',60),('',60),('NaN',60)]:
                with self.subTest(value=value):self.assertEqual(client._retry_seconds({'Retry-After':value}),seconds)
        self.assertEqual(client._retry_seconds(None),60)

    def test_other_keys_work_and_provider_errors_are_sanitized_without_retry(self):
        first=Mock(side_effect=limited())
        with self.assertRaises(APIError):client.request(first,'endpoint',{},'one',10)
        other=Mock(return_value={'ok':True})
        self.assertEqual(client.request(other,'endpoint',{},'two',10),{'ok':True})
        for status in (401,403,500):
            service=Mock(side_effect=HTTPError('https://provider.invalid',status,'private key',{},None))
            with self.subTest(status=status),self.assertRaises(APIError) as caught:client.request(service,'endpoint',{},'two',10)
            self.assertNotIn('private',str(caught.exception));service.assert_called_once()
        with self.assertRaises(APIError) as caught:client.request(Mock(side_effect=TimeoutError('private')),'endpoint',{},'two',10)
        self.assertIn('did not reply in time',str(caught.exception))
