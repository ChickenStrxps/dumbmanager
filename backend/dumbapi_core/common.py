import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class APIError(Exception):
    def __init__(self, message, code="invalid_request", status=400):
        super().__init__(message)
        self.code, self.status = code, status


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def slug(value):
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def json_text(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json_text(value), encoding="utf-8")
    temp.replace(path)


class Config:
    def __init__(self, root=ROOT, data=None):
        self.root = Path(root).resolve()
        self.settings = read_json(self.root / "settings.json") if (self.root / "settings.json").exists() else {}
        self.projects_root = (self.root / self.settings.get("projects_root", "__no_workspace_selected__")).resolve()
        default_data = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local/share")) / "DumbAPICommunity"
        self.data = Path(data or os.environ.get("DUMBAPI_DATA_DIR", default_data)).resolve()
        self.data.mkdir(parents=True, exist_ok=True)
        workspace_file = self.data / 'workspace.json'
        if workspace_file.exists():
            selected = read_json(workspace_file).get('path', '')
            if selected:self.projects_root=Path(selected).resolve()
        self.db = self.data / "index.sqlite"
        self.port = int(self.settings.get("port", 8781))
        self.python = self.settings.get("python") or sys.executable
        self.max_files = int(self.settings.get("max_files_per_project", 1200))
        self.refresh_seconds = int(self.settings.get("refresh_seconds", 300))

    def roots(self):
        # A fresh install has no source access. Only explicitly selected roots count.
        saved = self.data / 'workspace.json'
        explicit = read_json(saved).get('path', '') if saved.exists() else ''
        if explicit:
            path = Path(explicit).resolve()
            return {slug(path.name): (path.name, path)} if path.is_dir() else {}
        found = {}
        if 'projects_root' in self.settings and self.projects_root.is_dir():
            for path in sorted(self.projects_root.iterdir(), key=lambda p: p.name.lower()):
                if path.is_dir() and not path.name.startswith(('.', '_')) and not path.is_symlink() and not path.is_junction():
                    found[slug(path.name)] = (path.name, path.resolve())
        for extra in self.settings.get('extra_projects', []):
            path = Path(os.path.expandvars(extra['path'])).expanduser().resolve()
            found[extra['id']] = (extra.get('name', path.name), path)
        return found


def inside(root, relative, must_exist=True):
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts or ":" in str(relative):
        raise APIError("Use a relative path inside the named project.")
    cursor = root
    for part in path.parts:
        cursor = cursor / part
        if cursor.is_symlink() or cursor.is_junction():
            raise APIError("Linked files/directories are not accepted as project inputs.")
    target = (root / path).resolve()
    if not target.is_relative_to(root.resolve()) or (must_exist and not target.is_file()):
        raise APIError("File is missing or outside the project.", "file_unavailable", 404)
    return target


def page(rows, limit=10, offset=0):
    return {"items": rows[offset:offset + limit], "total": len(rows), "offset": offset,
            "next_offset": offset + limit if offset + limit < len(rows) else None}
