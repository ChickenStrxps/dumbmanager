"""Real contention across instances, threads and a separate process."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from dumbapi_core.common import APIError,Config
from dumbapi_core.git import Git

class GitLockTest(unittest.TestCase):
    def test_competing_access_is_busy_then_released(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);config=Config(root,root/'state');first=Git(config);second=Git(config)
            (root/'nested').mkdir();alias=root/'nested'/'..'
            results=[]
            def compete():
                try:
                    with second.lock(root):results.append('free')
                except APIError as exc:results.append(exc.code)
            child="""import sys
from pathlib import Path
from dumbapi_core.common import APIError,Config
from dumbapi_core.git import Git
root=Path(sys.argv[1])
try:
    with Git(Config(root,root/'state')).lock(root):print('free')
except APIError as exc:print(exc.code)
"""
            flags={'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {}
            def subprocess_result():
                return subprocess.check_output([sys.executable,'-B','-c',child,str(root)],text=True,timeout=15,**flags).strip()
            with first.lock(root):
                with self.assertRaises(APIError) as caught:
                    with second.lock(alias):self.fail('Aliased nested access acquired the lock')
                self.assertEqual(caught.exception.code,'busy')
                thread=threading.Thread(target=compete);thread.start();thread.join(timeout=5)
                self.assertFalse(thread.is_alive());self.assertEqual(results,['busy'])
                self.assertEqual(subprocess_result(),'busy')
            self.assertEqual(subprocess_result(),'free')
            with second.lock(root):pass
