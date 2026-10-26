"""Real Windows regressions for window isolation and interrupted browser owners."""
import ctypes
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from ctypes import wintypes as w
from pathlib import Path

from dumbapi_core.browser import installed_browser
from dumbapi_core.browser_process import BrowserProcess

ROOT = (Path(__file__).resolve().parents[2]/"backend")


@unittest.skipUnless(os.name == 'nt', 'Windows process ownership required')
class BrowserProcessTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        self.kernel.OpenProcess.restype = w.HANDLE
        self.kernel.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
        self.kernel.WaitForSingleObject.restype = w.DWORD
        self.kernel.CloseHandle.argtypes = [w.HANDLE]

    def ready(self, path, owner):
        deadline = time.monotonic()+25
        while time.monotonic() < deadline:
            if path.exists():
                try:
                    return json.loads(path.read_text())
                except (OSError, ValueError):
                    pass
            self.assertIsNone(owner.poll(), 'Owner exited before publishing test state')
            time.sleep(.05)
        self.fail('Owner did not publish test state')

    def process_handle(self, pid):
        handle = self.kernel.OpenProcess(0x100000, False, pid)  # SYNCHRONIZE
        self.assertTrue(handle, f'Process {pid} was not running')
        self.addCleanup(self.kernel.CloseHandle, handle)
        return handle

    def windows(self, desktop=None):
        user = ctypes.WinDLL('user32', use_last_error=True)
        callback_type = ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
        result = []

        def record(hwnd, _):
            title = ctypes.create_unicode_buffer(256)
            user.GetWindowTextW(hwnd, title, len(title))
            if title.value:
                result.append(title.value)
            return True

        user.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
        callback = callback_type(record)
        if desktop:
            user.EnumDesktopWindows.argtypes = [w.HANDLE, callback_type, w.LPARAM]
            self.assertTrue(user.EnumDesktopWindows(desktop, callback, 0))
        else:
            user.EnumWindows.argtypes = [callback_type, w.LPARAM]
            self.assertTrue(user.EnumWindows(callback, 0))
        return result

    def test_native_windows_stay_off_the_interactive_desktop(self):
        ready = self.base/'ready.json'
        title = 'Fish lab isolation '+self.base.name
        code = '''import ctypes,json,sys,time
from ctypes import wintypes as w
from pathlib import Path
u=ctypes.WinDLL('user32',use_last_error=True)
u.CreateWindowExW.argtypes=[w.DWORD,w.LPCWSTR,w.LPCWSTR,w.DWORD,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,w.HWND,w.HMENU,w.HINSTANCE,ctypes.c_void_p]
u.CreateWindowExW.restype=w.HWND
h=u.CreateWindowExW(0,'STATIC',sys.argv[2],0x10cf0000,0,0,100,100,None,None,None,None)
assert h,ctypes.get_last_error()
Path(sys.argv[1]).write_text(json.dumps({'window':h}))
time.sleep(60)
'''
        process = BrowserProcess([sys.executable, '-c', code, str(ready), title])
        self.addCleanup(process.close)
        self.ready(ready, process)
        self.assertIn(title, self.windows(process._desktop))
        self.assertNotIn(title, self.windows())
        process.close()
        process.close()  # Stop/restart and error cleanup can both close the same owner.

    def test_close_reaps_helpers_even_after_the_browser_root_exits(self):
        ready = self.base/'ready.json'
        code = '''import json,subprocess,sys
from pathlib import Path
p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],creationflags=subprocess.CREATE_NO_WINDOW)
Path(sys.argv[1]).write_text(json.dumps({'child':p.pid}))
'''
        process = BrowserProcess([sys.executable, '-c', code, str(ready)])
        self.addCleanup(process.close)
        # The root is deliberately short-lived; wait for its output independently.
        process.wait(timeout=10)
        child = json.loads(ready.read_text())['child']
        handle = self.process_handle(child)
        self.assertEqual(self.kernel.WaitForSingleObject(handle, 0), 0x102)
        process.close()
        self.assertEqual(self.kernel.WaitForSingleObject(handle, 5000), 0)

    @unittest.skipUnless(installed_browser(), 'Installed Edge required')
    def test_forced_host_termination_reaps_real_edge_and_its_helpers(self):
        ready = self.base/'ready.json'
        code = '''import ctypes,json,sys,time
from ctypes import wintypes as w
from pathlib import Path
from dumbapi_core.browser import Browser
from dumbapi_core.browser_process import _kernel
from dumbapi_core.common import Config
base=Path(sys.argv[1]);(base/'hub').mkdir()
b=Browser(Config(base/'hub',base/'data'));b.start()
class Pids(ctypes.Structure):
    _fields_=[('assigned',w.DWORD),('count',w.DWORD),('pids',ctypes.c_size_t*128)]
pids=Pids()
assert _kernel.QueryInformationJobObject(b.process._job,3,ctypes.byref(pids),ctypes.sizeof(pids),None)
Path(sys.argv[2]).write_text(json.dumps({'pids':list(pids.pids[:pids.count])}))
time.sleep(60)
'''
        host = subprocess.Popen([sys.executable, '-c', code, str(self.base), str(ready)], cwd=ROOT,
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        handles = []
        try:
            state = self.ready(ready, host)
            for pid in state['pids']:
                handle = self.kernel.OpenProcess(0x100000, False, pid)
                if handle:
                    handles.append(handle)
                else:
                    # Edge can replace a renderer between the job snapshot and OpenProcess.
                    self.assertEqual(ctypes.get_last_error(), 87)
            self.assertGreater(len(handles), 1, 'Edge helpers were not exercised')
            host.terminate()  # Windows TerminateProcess skips Python finally and atexit.
            host.wait(timeout=10)
            for handle in handles:
                self.assertEqual(self.kernel.WaitForSingleObject(handle, 5000), 0,
                                 'An owned Edge process survived its forcibly terminated host')
        finally:
            self.stop_host(host)
            for handle in handles:
                self.kernel.WaitForSingleObject(handle, 5000)
                self.kernel.CloseHandle(handle)

    def stop_host(self, host):
        if host.poll() is None:
            host.kill()
        host.wait(timeout=10)

    def test_failed_launch_releases_job_and_desktop_handles(self):
        from dumbapi_core import browser_process as module
        from unittest.mock import patch
        with patch.object(module._user, 'CloseDesktop', wraps=module._user.CloseDesktop) as close_desktop:
            with self.assertRaises(OSError):
                BrowserProcess([str(self.base/'missing-edge.exe')])
            self.assertEqual(close_desktop.call_count, 1)


if __name__ == '__main__':
    unittest.main()
