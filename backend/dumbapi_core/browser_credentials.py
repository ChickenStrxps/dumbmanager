"""Current-Windows-user Jev key storage. No plaintext credential files."""
import ctypes
import os
import tempfile
from pathlib import Path

from .common import APIError


PREFIX = b'DumbAPI-Jev-v1\0'
DISCONNECTED = b'DumbAPI-Jev-disconnected-v1\n'
MAX_BLOB = 16384


def valid_key(value):
    return isinstance(value, str) and len(value) <= 500 and value.isascii() and not any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value)


def _crypt(value, decrypt=False):
    if os.name != 'nt':
        raise APIError('Remembering Jev keys requires Windows.', 'key_storage_unavailable', 503)
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]

    crypt32 = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    transform = crypt32.CryptUnprotectData if decrypt else crypt32.CryptProtectData
    transform.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p if decrypt else wintypes.LPCWSTR,
                          ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                          wintypes.DWORD, ctypes.POINTER(Blob)]
    transform.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    buffer = (ctypes.c_ubyte * len(value)).from_buffer_copy(value)
    source, target = Blob(len(value), buffer), Blob()
    try:
        # Current-user scope; no machine-wide flag and no interactive Windows prompt.
        if not transform(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
            raise APIError('Windows could not unlock the saved Jev key. Reconnect Jev.', 'key_storage_unavailable', 503)
        if not 0 < target.size <= MAX_BLOB:
            raise APIError('Saved Jev key is invalid. Reconnect Jev.', 'key_storage_unavailable', 503)
        return ctypes.string_at(target.data, target.size)
    finally:
        ctypes.memset(buffer, 0, len(value))
        if target.data:
            ctypes.memset(target.data, 0, target.size)
            kernel32.LocalFree(target.data)


class JevKeyStore:
    def __init__(self, data):
        self.path = Path(data) / 'browser-jev-key.dpapi'

    def load(self):
        """None means unconfigured; empty means explicitly disconnected (ignores env)."""
        try:
            with self.path.open('rb') as stream:
                blob = stream.read(MAX_BLOB + 1)
        except FileNotFoundError:
            return None
        except OSError:
            raise APIError('Saved Jev key could not be read. Reconnect Jev.', 'key_storage_unavailable', 503) from None
        if blob == DISCONNECTED:
            return ''
        if not blob or len(blob) > MAX_BLOB:
            raise APIError('Saved Jev key is invalid. Reconnect Jev.', 'key_storage_unavailable', 503)
        clear = _crypt(blob, decrypt=True)
        if not clear.startswith(PREFIX):
            raise APIError('Saved Jev key is invalid. Reconnect Jev.', 'key_storage_unavailable', 503)
        try:
            key = clear[len(PREFIX):].decode('ascii')
        except UnicodeError:
            key = None
        if not key or not valid_key(key):
            raise APIError('Saved Jev key is invalid. Reconnect Jev.', 'key_storage_unavailable', 503)
        return key

    def save(self, key):
        # The nonsecret disconnect marker replaces the encrypted key, and prevents
        # an environment fallback from silently reconnecting after a restart.
        blob = _crypt(PREFIX + key.encode('ascii')) if key else DISCONNECTED
        temporary = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=self.path.parent, prefix='.jev-', delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(blob)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(self.path)
        except OSError:
            raise APIError('Could not save Jev settings. Your previous connection is unchanged.', 'key_storage_unavailable', 503) from None
        finally:
            if temporary:
                try: temporary.unlink(missing_ok=True)
                except OSError: pass
