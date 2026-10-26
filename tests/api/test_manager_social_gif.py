import base64
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dumbapi_core import manager_social_gif
from dumbapi_core.app import App
from dumbapi_core.common import APIError, Config

FAKE = b'GIF89a' + b'\0'*20 + b';'
META = {'theme':'Shark week','key':'shark','events':['greg'],'frames':72,'seconds':3.6,'width':1200,'height':675}


class SocialGifTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name); self.app = App(Config(root, root/'data'))
        row = self.app.call('manager.capture', {'project':'demo','title':'Animated cards','use_active':False})
        self.itch = self.app.call('manager.update', {'id':row['id'],'changes':json.dumps({'state':'ready'})})
        self.draft = self.app.call('manager.social.draft', {'itch_id':self.itch['id']})

    @patch.object(manager_social_gif, 'draw', return_value=(FAKE, META))
    def test_renders_once_per_version_and_vibe(self, draw):
        first = self.app.call('manager.social.gif', {'id':self.draft['id']})
        self.assertEqual(base64.b64decode(first['gif']), FAKE)
        self.assertEqual((first['version'], first['theme'], first['events']), (self.draft['version'], 'Shark week', ['greg']))
        self.assertTrue(first['filename'].endswith('.gif')); self.assertTrue(first['export_ready'])
        payload = draw.call_args[0][1]
        self.assertEqual(payload['headline'], self.draft['headline']); self.assertEqual(payload['image'], '')
        self.app.call('manager.social.gif', {'id':self.draft['id']})
        self.assertEqual(draw.call_count, 1)  # cached
        self.app.call('manager.social.gif', {'id':self.draft['id'],'vibe':1})
        self.assertEqual(draw.call_count, 2)  # reroll is a new card
        saved = self.app.call('manager.social.save', {'id':self.draft['id'],'expected_version':self.draft['version'],
            'headline':'New headline','summary':self.draft['summary'],'caption':self.draft['caption']})
        again = self.app.call('manager.social.gif', {'id':self.draft['id']})
        self.assertEqual(draw.call_count, 3); self.assertEqual(again['version'], saved['version'])
        self.assertEqual(draw.call_args[0][1]['headline'], 'New headline')

    @patch.object(manager_social_gif, 'draw', return_value=(FAKE, META))
    def test_force_options_validated_and_reopened_work_refused(self, draw):
        self.app.call('manager.social.gif', {'id':self.draft['id'],'theme':'penguin','events':'greg,lightning'})
        self.assertEqual(draw.call_args[0][3], {'theme':'penguin','events':['greg','lightning']})
        with self.assertRaises(APIError): self.app.call('manager.social.gif', {'id':self.draft['id'],'theme':'vista'})
        with self.assertRaises(APIError): self.app.call('manager.social.gif', {'id':self.draft['id'],'events':'meteor'})
        self.app.call('manager.update', {'id':self.itch['id'],'changes':json.dumps({'state':'working'})})
        with self.assertRaises(APIError): self.app.call('manager.social.gif', {'id':self.draft['id']})

    @patch.object(manager_social_gif, 'set_clipboard')
    @patch.object(manager_social_gif, 'draw', return_value=(FAKE, {**META, 'key':'flow','theme':'Water flow'}))
    def test_explicit_flow_selection_survives_cache_and_clipboard(self, draw, clip):
        args = {'id':self.draft['id'],'vibe':4,'theme':'flow'}
        preview = self.app.call('manager.social.gif', args)
        self.assertEqual(preview['requested_theme'], 'flow')
        self.assertEqual(preview['key'], 'flow')
        copied = self.app.call('manager.social.gif_copy', {**args,'expected_version':self.draft['version']})
        self.assertEqual(copied['sha256'], preview['sha256'])
        self.assertEqual(draw.call_count, 1)
        self.assertEqual(draw.call_args.args[3], {'theme':'flow'})
        self.assertEqual(clip.call_args.args[0].read_bytes(), base64.b64decode(preview['gif']))
        random = self.app.call('manager.social.gif', {'id':self.draft['id'],'vibe':4})
        self.assertEqual(random['requested_theme'], '')
        self.assertEqual(draw.call_count, 2)

    @patch.object(manager_social_gif, 'set_clipboard')
    @patch.object(manager_social_gif, 'draw', return_value=(FAKE, {**META, 'key':'smoke','theme':'Dithered smoke'}))
    def test_smoke_selection_and_shared_art_changes_are_part_of_export_identity(self, draw, clip):
        args = {'id':self.draft['id'],'theme':'smoke'}
        preview = self.app.call('manager.social.gif', args)
        copied = self.app.call('manager.social.gif_copy', {**args,'expected_version':self.draft['version']})
        self.assertEqual((preview['requested_theme'],preview['key']),('smoke','smoke'))
        self.assertEqual(copied['sha256'],preview['sha256'])
        self.assertEqual(draw.call_count,1)
        self.assertEqual(clip.call_args.args[0].read_bytes(),FAKE)
        # A changed shared plume must invalidate the cached card, not just JS edits.
        changed = Path(self.temp.name)/'changed-smoke.js'
        changed.write_text(manager_social_gif.SMOKE.read_text(encoding='utf-8')+'\n// changed art',encoding='utf-8')
        with patch.object(manager_social_gif,'SMOKE',changed):
            self.app.call('manager.social.gif',args)
        self.assertEqual(draw.call_count,2)

    @patch.object(manager_social_gif, 'set_clipboard')
    @patch.object(manager_social_gif, 'draw', return_value=(FAKE, META))
    def test_copy_puts_exact_gif_file_on_clipboard(self, draw, clip):
        with self.assertRaises(APIError): self.app.call('manager.social.gif_copy', {'id':self.draft['id'],'expected_version':self.draft['version']+1})
        clip.assert_not_called()
        result = self.app.call('manager.social.gif_copy', {'id':self.draft['id'],'expected_version':self.draft['version'],'vibe':2})
        path = clip.call_args[0][0]
        self.assertEqual(path.read_bytes(), FAKE); self.assertEqual(path.suffix, '.gif'); self.assertEqual(result['filename'], path.name)
        self.app.call('manager.social.gif_copy', {'id':self.draft['id'],'expected_version':self.draft['version'],'vibe':2})
        self.assertEqual(draw.call_count, 1); self.assertEqual(len(list(path.parent.glob('*.gif'))), 1)

    @unittest.skipUnless(os.environ.get('DUMBAPI_LIVE_GIF'), 'needs Edge; set DUMBAPI_LIVE_GIF=1')
    def test_every_theme_renders(self):
        for theme in manager_social_gif.THEMES:
            result = self.app.call('manager.social.gif', {'id':self.draft['id'],'theme':theme})
            self.assertLess(result['bytes'], 15*1024*1024, theme); self.assertEqual(result['key'], theme)

    @unittest.skipUnless(os.environ.get('DUMBAPI_LIVE_GIF'), 'needs Edge; set DUMBAPI_LIVE_GIF=1')
    def test_live_render_is_a_looping_gif_under_x_limit(self):
        result = self.app.call('manager.social.gif', {'id':self.draft['id'],'events':'greg,lightning,flicker'})
        data = base64.b64decode(result['gif'])
        self.assertTrue(data.startswith(b'GIF89a') and b'NETSCAPE2.0' in data[:1200])
        self.assertLess(len(data), 15*1024*1024); self.assertEqual((result['width'], result['height']), (1200, 675))


if __name__ == '__main__':
    unittest.main()
