"""The public T3 boundary retains a working session after failed pairing."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from dumbapi_core.common import APIError,Config,atomic_json,read_json
from dumbapi_core.t3 import T3
from dumbapi_core.t3_distributions import Distributions,connection_lock,target

class T3BoundaryTest(unittest.TestCase):
    def test_failed_candidate_is_not_published_and_success_requires_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);config=Config(base,base/'state');file=config.data/'t3-connection.json'
            old={'url':'http://127.0.0.1:3773','token':'fixture-old'};atomic_json(file,old)
            previous=file.read_bytes();expected=target(config)
            def pair(client,port):
                self.assertNotEqual(client.config.data,config.data)
                atomic_json(client.config.data/'t3-connection.json',{'url':old['url'],'token':'fixture-new'})
            with patch.object(T3,'_connect',pair),patch.object(T3,'get_from',side_effect=APIError('Unavailable')):
                with self.assertRaises(APIError):Distributions(config).select('t3',True,expected)
            self.assertEqual(file.read_bytes(),previous)
            self.assertEqual(list(config.data.glob('t3-pair-*')),[])
            observed=[]
            def probe(client,value,route):
                observed.append(route);self.assertEqual(file.read_bytes(),previous)
                return {'threads':[],'projects':[]}
            with patch.object(T3,'_connect',pair),patch.object(T3,'get_from',probe):
                self.assertTrue(Distributions(config).select('t3',True,expected)['connected'])
            self.assertEqual(observed,['/api/orchestration/shell'])
            self.assertEqual(read_json(file)['token'],'fixture-new')
            self.assertTrue(read_json(file)['verified_at'])

    def test_nested_same_thread_reuses_lock_but_other_owners_are_busy(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);config=Config(base,base/'state');results=[]
            def compete():
                try:
                    with connection_lock(config):results.append('free')
                except APIError as exc:results.append(exc.code)
            child="""import sys
from pathlib import Path
from dumbapi_core.common import Config,APIError
from dumbapi_core.t3_distributions import connection_lock
base=Path(sys.argv[1])
try:
    with connection_lock(Config(base,base/'state')):print('free')
except APIError as exc:print(exc.code)
"""
            flags={'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {}
            with connection_lock(config):
                with connection_lock(config):pass
                thread=threading.Thread(target=compete);thread.start();thread.join(timeout=5)
                self.assertFalse(thread.is_alive());self.assertEqual(results,['busy'])
                answer=subprocess.check_output([sys.executable,'-B','-c',child,str(base)],text=True,timeout=15,**flags)
                self.assertEqual(answer.strip(),'busy')
            with connection_lock(config):pass
