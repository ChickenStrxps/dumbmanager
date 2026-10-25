"""Explicit local workspace selection. No adjacent directory discovery by default."""
from pathlib import Path
from .common import APIError, atomic_json, read_json

class Workspace:
    def __init__(self, config): self.config=config
    def status(self):
        file=self.config.data/'workspace.json'
        path=read_json(file).get('path','') if file.exists() else ''
        return {'configured':bool(path and Path(path).is_dir()),'path':path}
    def configure(self,path):
        if path:
            chosen=Path(path).expanduser()
            if not chosen.is_absolute() or not chosen.is_dir() or chosen.is_symlink() or chosen.is_junction():
                raise APIError('Choose an existing absolute folder path without a directory link.')
            path=str(chosen.resolve())
        atomic_json(self.config.data/'workspace.json',{'path':path})
        if path:self.config.projects_root=Path(path)
        from .catalog import Catalog
        from .registry import definitions
        Catalog(self.config).refresh(definitions())
        return self.status()
