import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from dumbapi_core.common import Config, APIError
from dumbapi_core.manager_plugins import Plugins, requirements


class PluginsTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        env=patch.dict(os.environ,{'DUMBMANAGER_DATA_DIR':str(self.root/'manager')})
        env.start();self.addCleanup(env.stop)
        self.config=Config(self.root,self.root/'api')
        self.plugins=Plugins(self.config)

    def test_install_is_bounded_complete_and_preserves_source(self):
        source=self.root/'a different package location';source.mkdir()
        (source/'DumbVoice.exe').write_bytes(b'MZ synthetic, never executed')
        args={'id':'dumbvoice','source':str(source)}
        with self.assertRaises(APIError):self.plugins.call('plugins.install',args)
        (source/'transcribe.py').write_text('# synthetic')
        saved=self.plugins.call('plugins.install',args)
        package=Path(saved['items']['dumbvoice']['path'])
        self.assertTrue(package.is_relative_to(self.root/'manager'))
        self.assertTrue((source/'DumbVoice.exe').exists())
        self.plugins.call('plugins.remove',{'id':'dumbvoice'})
        self.assertTrue((package/'DumbVoice.exe').exists())
        with self.assertRaises(APIError):self.plugins.call('plugins.install',{'id':'dumbeffects','source':str(source)})

    def test_context_and_custom_engine_paths(self):
        project=self.root/'workspace';project.mkdir()
        (project/'Cargo.toml').write_text('[package]')
        (self.config.data/'workspace.json').write_text(json.dumps({'path':str(project)}))
        self.assertEqual(self.plugins.context('workspace')['signals'],['rust'])
        self.assertEqual(self.plugins.context('unknown')['signals'],[])
        engine=self.root/'custom-engine.exe';model=self.root/'english.bin'
        engine.write_text('never executed');model.write_text('not a model')
        self.assertEqual(requirements({'id':'dumbvoice','engine_path':str(engine),'model_path':str(model)})['items'][1]['state'],'found')

    def test_reference_save_is_truthful_and_survives_new_instance(self):
        item={'id':'mcp:test','name':'Test','kind':'mcp','url':'https://example.invalid/docs','state':'installed'}
        saved=self.plugins.call('plugins.add',{'item':item})
        self.assertEqual(saved['items']['mcp:test']['state'],'added')
        self.assertIn('mcp:test',Plugins(self.config).shelf()['items'])
        with self.assertRaises(APIError):self.plugins.call('plugins.add',{'item':{**item,'url':'file:///private'}})

    def test_source_failure_keeps_local_shelf_available(self):
        with patch.object(Plugins,'get',side_effect=OSError('offline')):
            result=self.plugins.call('plugins.search',{'query':'rust','kind':'all'})
        self.assertEqual(result['items'],[])
        self.assertTrue(all(not s['ok'] for s in result['sources']))
        self.assertEqual(len(self.plugins.call('plugins.list',{})['items']),7)
