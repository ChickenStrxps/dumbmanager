import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dumbapi_core.browser import Browser
from dumbapi_core.browser_credentials import DISCONNECTED, MAX_BLOB, JevKeyStore
from dumbapi_core.common import APIError, Config


@unittest.skipUnless(os.name == 'nt', 'Windows DPAPI required')
class JevCredentialsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        (self.base / 'hub').mkdir()
        self.config = Config(self.base / 'hub', self.base / 'data')
        self.env = patch.dict(os.environ, {'TYPESAFE_API_KEY': ''})
        self.env.start()
        self.browsers = []

    def tearDown(self):
        import atexit
        for browser in self.browsers:
            browser.stop()
            atexit.unregister(browser.stop)
        self.env.stop()
        self.temp.cleanup()

    def browser(self):
        result = Browser(self.config)
        self.browsers.append(result)
        return result

    def test_encrypted_key_survives_new_host_process_without_response_leak(self):
        browser = self.browser()
        key = 'fixture-private-jev-key'
        reply = browser.connect(key)
        self.assertTrue(reply['key_saved'])
        blob = browser.credentials.path.read_bytes()
        self.assertNotIn(key.encode(), blob)
        self.assertNotIn(key, json.dumps([reply, browser.status(), browser.stop()]))
        # An actual separate interpreter decrypts the temp state's saved key.
        code = "from pathlib import Path; import sys; from dumbapi_core.browser_credentials import JevKeyStore; assert JevKeyStore(Path(sys.argv[1])).load() == 'fixture-private-jev-key'; print('restored')"
        result = subprocess.run([sys.executable, '-c', code, str(self.config.data)],
                                cwd=(Path(__file__).resolve().parents[2]/"backend"), capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'restored')
        restarted = self.browser()
        self.assertEqual(restarted.key, key)
        self.assertTrue(restarted.status()['key_saved'])

    def test_forget_removes_key_and_overrides_environment_on_restart(self):
        with patch.dict(os.environ, {'TYPESAFE_API_KEY': 'fixture-environment-key'}):
            browser = self.browser()
            self.assertTrue(browser.status()['jev_connected'])
            self.assertFalse(browser.status()['key_saved'])
            browser.connect('fixture-saved-key')
            reply = browser.connect('')
            self.assertFalse(reply['jev_connected'])
            self.assertEqual(browser.credentials.path.read_bytes(), DISCONNECTED)
            restarted = self.browser()
            self.assertFalse(restarted.status()['jev_connected'])
            self.assertIsNone(restarted.process)

    def test_corrupt_or_oversized_saved_key_fails_closed_and_can_reconnect(self):
        store = JevKeyStore(self.config.data)
        for blob in [b'corrupted', b'', b'x' * (MAX_BLOB + 1)]:
            with self.subTest(size=len(blob)):
                store.path.write_bytes(blob)
                with patch.dict(os.environ, {'TYPESAFE_API_KEY': 'fixture-environment-key'}):
                    browser = self.browser()
                self.assertFalse(browser.status()['jev_connected'])
                self.assertTrue(browser.status()['key_notice'])
                browser.connect('fixture-recovered-key')
                self.assertTrue(browser.status()['key_saved'])
                self.assertEqual(store.load(), 'fixture-recovered-key')

    def test_failed_write_or_forget_preserves_previous_connection_and_file(self):
        browser = self.browser()
        browser.connect('fixture-original-key')
        original = browser.credentials.path.read_bytes()
        for key in ['fixture-new-key', '']:
            with patch.object(Path, 'replace', side_effect=PermissionError('private details')):
                with self.assertRaises(APIError) as error:
                    browser.connect(key)
            self.assertNotIn('private details', str(error.exception))
            self.assertEqual(browser.key, 'fixture-original-key')
            self.assertEqual(browser.credentials.path.read_bytes(), original)
            self.assertEqual(list(self.config.data.glob('.jev-*')), [])

    def test_invalid_keys_do_not_replace_saved_credential(self):
        browser = self.browser()
        browser.connect('fixture-original-key')
        for key in ['new key', 'new\nkey', 'new\0key', 'new\x7fkey', 'é', 'x' * 501]:
            with self.subTest(key=repr(key)), self.assertRaises(APIError):
                browser.connect(key)
        self.assertEqual(browser.credentials.load(), 'fixture-original-key')

    def test_failed_windows_encryption_keeps_original_file(self):
        browser = self.browser()
        browser.connect('fixture-original-key')
        with patch('dumbapi_core.browser_credentials._crypt', side_effect=APIError('Windows unavailable')):
            with self.assertRaises(APIError): browser.connect('fixture-replacement')
        self.assertEqual(browser.credentials.load(), 'fixture-original-key')
        self.assertEqual(browser.key, 'fixture-original-key')


if __name__ == '__main__':
    unittest.main()
