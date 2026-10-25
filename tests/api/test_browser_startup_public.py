"""Startup readiness retries never repeat a user browsing action."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from dumbapi_core.browser import Browser
from dumbapi_core.common import Config

class StartupReadinessTest(unittest.TestCase):
    def test_devtools_file_can_precede_websocket_readiness(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);config=Config(base,base/'state')
            profile=base/'profile';profile.mkdir()
            (profile/'DevToolsActivePort').write_text('12345\n/devtools/browser/fixture\n')
            process=MagicMock();process.poll.return_value=None
            cdp=MagicMock();cdp.__enter__.return_value=cdp
            cdp.call.return_value={'userAgent':'HeadlessChrome/fixture'}
            browser=Browser(config)
            try:
                with patch('dumbapi_core.browser.installed_browser',return_value=Path('edge.exe')), \
                     patch('dumbapi_core.browser.tempfile.mkdtemp',return_value=str(profile)), \
                     patch('dumbapi_core.browser.BrowserProcess',return_value=process), \
                     patch('dumbapi_core.browser.CDP',side_effect=[OSError('not ready'),cdp]) as connect, \
                     patch.object(browser,'_tabs',return_value=[{'id':'page-fixture'}]), \
                     patch.object(browser,'snapshot',return_value={'ready':True}), \
                     patch('dumbapi_core.browser.time.sleep'), \
                     patch('dumbapi_core.browser.threading.Thread'):
                    self.assertEqual(browser.start(),{'ready':True})
                    self.assertEqual(connect.call_count,2)
                    self.assertEqual(browser.tab,'page-fixture')
            finally:browser.stop()
