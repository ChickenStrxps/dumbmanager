"""Windows-owned background browsers, including when the Python host is killed.

The job is assigned by CreateProcess itself, before Edge can spawn helpers.
Its non-inherited handle dies with this host. A private, never-shown desktop
also keeps Chromium's native windows out of the user's task switcher.
"""
import ctypes
import math
import os
import subprocess
import time
import uuid
from ctypes import wintypes as w


class _Limits(ctypes.Structure):
    _fields_ = [('process_time', ctypes.c_int64), ('job_time', ctypes.c_int64),
                ('flags', w.DWORD), ('min_working_set', ctypes.c_size_t),
                ('max_working_set', ctypes.c_size_t), ('active_limit', w.DWORD),
                ('affinity', ctypes.c_size_t), ('priority', w.DWORD), ('scheduling', w.DWORD)]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [('basic', _Limits), ('io', ctypes.c_uint64 * 6),
                ('process_memory', ctypes.c_size_t), ('job_memory', ctypes.c_size_t),
                ('peak_process_memory', ctypes.c_size_t), ('peak_job_memory', ctypes.c_size_t)]


class _Accounting(ctypes.Structure):
    _fields_ = [('times', ctypes.c_int64 * 4), ('faults', w.DWORD),
                ('total', w.DWORD), ('active', w.DWORD), ('terminated', w.DWORD)]


class _Startup(ctypes.Structure):
    _fields_ = [('cb', w.DWORD), ('reserved', w.LPWSTR), ('desktop', w.LPWSTR),
                ('title', w.LPWSTR), ('x', w.DWORD), ('y', w.DWORD),
                ('width', w.DWORD), ('height', w.DWORD), ('chars_x', w.DWORD),
                ('chars_y', w.DWORD), ('fill', w.DWORD), ('flags', w.DWORD),
                ('show', w.WORD), ('reserved_size', w.WORD), ('reserved_bytes', ctypes.c_void_p),
                ('stdin', w.HANDLE), ('stdout', w.HANDLE), ('stderr', w.HANDLE)]


class _StartupEx(ctypes.Structure):
    _fields_ = [('startup', _Startup), ('attributes', ctypes.c_void_p)]


class _ProcessInfo(ctypes.Structure):
    _fields_ = [('process', w.HANDLE), ('thread', w.HANDLE), ('pid', w.DWORD), ('tid', w.DWORD)]


if os.name == 'nt':
    _kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    _user = ctypes.WinDLL('user32', use_last_error=True)
    for name, args, result in [
        ('CreateJobObjectW', [ctypes.c_void_p, w.LPCWSTR], w.HANDLE),
        ('SetInformationJobObject', [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD], w.BOOL),
        ('QueryInformationJobObject', [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.c_void_p], w.BOOL),
        ('InitializeProcThreadAttributeList', [ctypes.c_void_p, w.DWORD, w.DWORD, ctypes.POINTER(ctypes.c_size_t)], w.BOOL),
        ('UpdateProcThreadAttribute', [ctypes.c_void_p, w.DWORD, ctypes.c_size_t, ctypes.c_void_p,
                                       ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p], w.BOOL),
        ('DeleteProcThreadAttributeList', [ctypes.c_void_p], None),
        ('CreateProcessW', [w.LPCWSTR, w.LPWSTR, ctypes.c_void_p, ctypes.c_void_p, w.BOOL, w.DWORD,
                            ctypes.c_void_p, w.LPCWSTR, ctypes.c_void_p, ctypes.POINTER(_ProcessInfo)], w.BOOL),
        ('GetExitCodeProcess', [w.HANDLE, ctypes.POINTER(w.DWORD)], w.BOOL),
        ('WaitForSingleObject', [w.HANDLE, w.DWORD], w.DWORD),
        ('TerminateJobObject', [w.HANDLE, w.UINT], w.BOOL),
        ('CloseHandle', [w.HANDLE], w.BOOL),
    ]:
        function = getattr(_kernel, name)
        function.argtypes, function.restype = args, result
    _user.CreateDesktopW.argtypes = [w.LPCWSTR, ctypes.c_void_p, ctypes.c_void_p, w.DWORD, w.DWORD, ctypes.c_void_p]
    _user.CreateDesktopW.restype = w.HANDLE
    _user.CloseDesktop.argtypes, _user.CloseDesktop.restype = [w.HANDLE], w.BOOL


def _check(value):
    if not value:
        raise ctypes.WinError(ctypes.get_last_error())
    return value


class BrowserProcess:
    """Small Popen-like owner used only for our disposable installed Edge sessions."""
    def __init__(self, args):
        self.args, self.pid, self.returncode = args, None, None
        self._job = self._desktop = self._handle = None
        if os.name != 'nt':
            raise OSError('Owned Edge sessions require Windows')
        attributes = None
        try:
            self._job = _check(_kernel.CreateJobObjectW(None, None))
            limits = _ExtendedLimits()
            limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            _check(_kernel.SetInformationJobObject(self._job, 9, ctypes.byref(limits), ctypes.sizeof(limits)))
            desktop_name = 'DumbAPI-browser-'+uuid.uuid4().hex
            self._desktop = _check(_user.CreateDesktopW(desktop_name, None, None, 0, 0x10000000, None))
            size = ctypes.c_size_t()
            _kernel.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
            storage = ctypes.create_string_buffer(size.value)
            _check(_kernel.InitializeProcThreadAttributeList(storage, 1, 0, ctypes.byref(size)))
            attributes = storage
            job_list = (w.HANDLE * 1)(self._job)
            # PROC_THREAD_ATTRIBUTE_JOB_LIST: atomic ownership, no launch/assignment race.
            _check(_kernel.UpdateProcThreadAttribute(attributes, 0, 0x2000D, job_list,
                                                      ctypes.sizeof(job_list), None, None))
            startup = _StartupEx()
            startup.startup.cb = ctypes.sizeof(startup)
            startup.startup.desktop = desktop_name
            startup.startup.flags = 0x101  # STARTF_USESHOWWINDOW | STARTF_USESTDHANDLES
            startup.startup.stdin = startup.startup.stdout = startup.startup.stderr = w.HANDLE(-1).value
            startup.attributes = ctypes.cast(attributes, ctypes.c_void_p)
            info = _ProcessInfo()
            command = ctypes.create_unicode_buffer(subprocess.list2cmdline([os.fspath(a) for a in args]))
            # Neither the job nor desktop handle is inherited by Edge or its helpers.
            _check(_kernel.CreateProcessW(os.fspath(args[0]), command, None, None, False,
                                          0x08080000, None, None, ctypes.byref(startup), ctypes.byref(info)))
            self._handle, self.pid = info.process, info.pid
            _kernel.CloseHandle(info.thread)
        except BaseException:
            self.close()
            raise
        finally:
            if attributes is not None:
                _kernel.DeleteProcThreadAttributeList(attributes)

    def poll(self):
        if self.returncode is None and self._handle:
            result = _kernel.WaitForSingleObject(self._handle, 0)
            if result == 0:
                code = w.DWORD()
                _check(_kernel.GetExitCodeProcess(self._handle, ctypes.byref(code)))
                self.returncode = code.value
            elif result == 0xFFFFFFFF:
                raise ctypes.WinError(ctypes.get_last_error())
        return self.returncode

    def wait(self, timeout=None):
        if self.poll() is None:
            milliseconds = 0xFFFFFFFF if timeout is None else min(0xFFFFFFFE, max(0, math.ceil(timeout*1000)))
            result = _kernel.WaitForSingleObject(self._handle, milliseconds)
            if result == 0x102:
                raise subprocess.TimeoutExpired(self.args, timeout)
            if result == 0xFFFFFFFF:
                raise ctypes.WinError(ctypes.get_last_error())
        return self.poll()

    def terminate(self):
        if self._job:
            _check(_kernel.TerminateJobObject(self._job, 1))

    kill = terminate

    def close(self):
        """Reap the entire owned tree, even if its original browser already exited."""
        try:
            if self._job:
                _check(_kernel.TerminateJobObject(self._job, 1))
                deadline = time.monotonic()+5
                while True:
                    accounting = _Accounting()
                    _check(_kernel.QueryInformationJobObject(self._job, 1, ctypes.byref(accounting),
                                                              ctypes.sizeof(accounting), None))
                    if not accounting.active:
                        break
                    if time.monotonic() >= deadline:
                        raise TimeoutError('Owned browser helpers did not exit')
                    time.sleep(.02)
            if self._handle:
                self.wait(timeout=5)
        finally:
            if self._job:
                _kernel.CloseHandle(self._job)
                self._job = None
            if self._handle:
                _kernel.CloseHandle(self._handle)
                self._handle = None
            if self._desktop:
                _user.CloseDesktop(self._desktop)
                self._desktop = None

    def __del__(self):
        # At interpreter shutdown Windows also closes the non-inherited job handle.
        try:
            self.close()
        except Exception:
            pass
