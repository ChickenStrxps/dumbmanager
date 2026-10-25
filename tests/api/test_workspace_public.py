"""The public build grants source access only after an explicit choice."""
import tempfile
import unittest
from pathlib import Path
from dumbapi_core.common import APIError, Config
from dumbapi_core.workspace import Workspace

class WorkspaceBoundaryTest(unittest.TestCase):
    def test_nearby_projects_are_hidden_until_selected_and_clear_revokes_access(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);hub=base/'backend';hub.mkdir()
            project=base/'Example Project';project.mkdir()
            config=Config(hub,base/'state');service=Workspace(config)
            self.assertEqual(config.roots(),{})
            self.assertFalse(service.status()['configured'])
            service.configure(str(project))
            self.assertEqual(list(config.roots()),['example-project'])
            self.assertEqual(list(Config(hub,base/'state').roots()),['example-project'])
            service.configure('')
            self.assertEqual(config.roots(),{})
            self.assertEqual(Config(hub,base/'state').roots(),{})

    def test_relative_and_missing_folders_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);hub=base/'backend';hub.mkdir()
            service=Workspace(Config(hub,base/'state'))
            for path in ('relative',str(base/'missing')):
                with self.subTest(path=path),self.assertRaises(APIError):service.configure(path)
            self.assertFalse(service.status()['configured'])
