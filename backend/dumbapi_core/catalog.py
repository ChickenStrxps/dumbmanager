"""Bounded, rebuildable source summaries. Never traverse dependency/media trees."""
import os
import re
import sqlite3
import subprocess
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from .common import APIError, inside, json_text, now, read_json

SKIP = {".git", ".svn", "node_modules", ".next", ".venv", "venv", "__pycache__", "site-packages",
        "target", "dist", "build", "out", "output", "outputs", "cache", ".cache", "archive", "archives",
        "assets", "public", "prepped", "library", "session_data", "scratch", "logs", ".tools", ".agy", ".gem"}
SKIP.update({"vendor", "packages", ".gradle", ".idea", ".vscode", "bin", "obj", "venv_lib", "Lib", "devenv", "env"})
EXTENSIONS = {".md", ".txt", ".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".rs",
              ".lua", ".luau", ".toml", ".json", ".yaml", ".yml", ".html", ".css", ".ps1", ".bat", ".sh"}
SENSITIVE = re.compile(r"(^\.env($|\.)|credential|secret|cookie|session|(?:^|[._-])tokens?(?:[._-]|$)|id_rsa|private.key|^state\.json$|post_log)", re.I)
SYMBOL = re.compile(r"^\s*(?:(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?(?:def|class|fn|struct|enum|trait|function|interface|type)\s+[^\n{;]{2,180}|(?:export\s+)?(?:const|local\s+function)\s+\w+[^\n{;]{0,100})", re.M)


def eligible(path):
    return path.suffix.lower() in EXTENSIONS and not SENSITIVE.search(path.name) and not path.name.endswith(("-lock.json", ".lock", ".min.js", ".d.ts", ".tsbuildinfo"))


def summary(text):
    lines = text.splitlines()
    intro = "\n".join(lines[:24])[:1700]
    symbols = "\n".join(m.group(0).strip() for m in SYMBOL.finditer(text))[:4200]
    return intro + "\n" + symbols


def candidates(root):
    if (root / ".git").exists():
        try:
            result = subprocess.run(["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                                    capture_output=True, timeout=10, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if result.returncode == 0:
                names = {p.decode("utf-8", errors="replace") for p in result.stdout.split(b"\0") if p}
                for name in sorted(names, key=lambda n: (n.count("/"), n not in {"AGENTS.md", "README.md"}, n)):
                    rel = Path(name)
                    if len(rel.parts) <= 9 and not any(p in SKIP or SENSITIVE.search(p) for p in rel.parts):
                        yield root / rel
                return
        except (OSError, subprocess.TimeoutExpired):
            pass
    started, visited, inspected = time.monotonic(), 0, 0
    for directory, dirs, names in os.walk(root, followlinks=False):
        visited += 1
        current = Path(directory)
        depth = len(current.relative_to(root).parts)
        dirs[:] = sorted(d for d in dirs if d not in SKIP and not d.startswith((".git", "_"))
                         and (not d.startswith(".") or d in {".omp", ".agents", ".claude"})
                         and not (current / d).is_symlink() and not (current / d).is_junction()) if depth < 8 else []
        if visited > 300 or inspected > 10_000 or time.monotonic() - started > 3:
            yield None  # Explicit coverage marker, never silently claim a full source scan.
            return
        for name in sorted(names, key=lambda n: (n not in {"AGENTS.md", "README.md"}, n)):
            inspected += 1
            yield current / name


class Catalog:
    def __init__(self, config):
        self.config = config
        self.lock = threading.Lock()
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY,value TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS projects (id TEXT PRIMARY KEY, data TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS files (project TEXT,path TEXT,mtime INTEGER,size INTEGER,PRIMARY KEY(project,path))")
            db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS lookup USING fts5(id UNINDEXED,kind UNINDEXED,project UNINDEXED,path,title,text,tokenize='unicode61')")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.config.db, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def ensure(self, capabilities):
        with self.connect() as db:
            row = db.execute("SELECT value FROM meta WHERE key='refreshed_epoch'").fetchone()
        if not row or time.time() - float(row[0]) >= self.config.refresh_seconds:
            self.refresh(capabilities)

    def refresh(self, capabilities):
        with self.lock:
            records, files, projects = [], [], []
            with self.connect() as db:
                previous = {(r["project"], r["path"]): (r["mtime"], r["size"], r["text"])
                            for r in db.execute("SELECT files.project,files.path,mtime,size,text FROM files JOIN lookup ON files.project=lookup.project AND files.path=lookup.path WHERE kind='file'")}
            for pid, (name, root) in self.config.roots().items():
                count, partial, errors = 0, False, []
                docs = [p for p in ("AGENTS.md", ".omp/AGENTS.md", ".omp/RULES.md", "README.md") if (root / p).is_file()]
                description = name
                readme = root / "README.md"
                if readme.is_file():
                    try:
                        description = next((l.strip() for l in readme.read_text(encoding="utf-8", errors="replace").splitlines()
                                            if l.strip() and not l.startswith(("#", "!", "[", "<", "```"))), name)[:250]
                    except OSError:
                        pass
                manifest = root / "dumbapi.project.json"
                links = []
                if manifest.is_file():
                    try:
                        custom = read_json(manifest)
                        description = str(custom.get("description", description))[:500]
                        links = custom.get("references", [])[:20]
                    except (OSError, ValueError, TypeError):
                        errors.append("Invalid dumbapi.project.json; using detected metadata.")
                for path in candidates(root):
                    if path is None or count >= self.config.max_files:
                        partial = True
                        break
                    if not eligible(path) or any(SENSITIVE.search(p) for p in path.relative_to(root).parts) or path.is_symlink() or not path.resolve().is_relative_to(root):
                        continue
                    try:
                        stat = path.stat()
                        if stat.st_size > 512_000 or getattr(stat, "st_file_attributes", 0) & (0x1000 | 0x400000):
                            continue  # Do not hydrate cloud-only files to build an index.
                        rel = path.relative_to(root).as_posix()
                        # Git can list files below junctions; don't let aliases expose excluded files.
                        try:
                            inside(root, rel)
                        except APIError:
                            continue
                        old = previous.get((pid, rel))
                        if old and old[:2] == (stat.st_mtime_ns, stat.st_size):
                            brief = old[2]
                        else:
                            with path.open("rb") as source:
                                raw = source.read(192_000)
                            if b"\x00" in raw[:1024]:
                                continue
                            brief = summary(raw.decode("utf-8", errors="replace"))
                        records.append((f"{pid}:{rel}", "file", pid, rel, path.name, brief))
                        files.append((pid, rel, stat.st_mtime_ns, stat.st_size))
                        count += 1
                    except OSError as exc:
                        errors.append(f"{path.name}: {type(exc).__name__}")
                data = {"id": pid, "name": name, "root": str(root), "exists": root.is_dir(), "description": description,
                        "instructions": docs, "references": links, "indexed_files": count, "partial": partial,
                        "errors": errors[:5], "indexed_at": now()}
                projects.append((pid, json_text(data)))
                records.append((pid, "project", pid, "", name, description))
            for cap in capabilities.values():
                records.append((cap["id"], "capability", cap["project"], "", cap["id"], cap["description"] + " " + " ".join(cap.get("tags", []))))
            with self.connect() as db:
                for table in ("lookup", "files", "projects"):
                    db.execute(f"DELETE FROM {table}")
                db.executemany("INSERT INTO lookup VALUES (?,?,?,?,?,?)", records)
                db.executemany("INSERT INTO files VALUES (?,?,?,?)", files)
                db.executemany("INSERT INTO projects VALUES (?,?)", projects)
                db.execute("INSERT OR REPLACE INTO meta VALUES ('refreshed_epoch',?)", (str(time.time()),))
                db.execute("INSERT OR REPLACE INTO meta VALUES ('indexed_at',?)", (now(),))
            return {"projects": len(projects), "indexed_files": len(files), "indexed_at": now(),
                    "partial_projects": [pid for pid, data in projects if __import__('json').loads(data)["partial"]]}

    def projects(self):
        import json
        with self.connect() as db:
            return [json.loads(row[0]) for row in db.execute("SELECT data FROM projects ORDER BY id")]

    def search(self, query, project=None, kind=None, limit=8, offset=0):
        words = re.findall(r"\w+", query, re.UNICODE)[:12]
        if not words:
            raise APIError("Provide at least one search word.")
        match = " OR ".join('"' + word + '"*' for word in words)
        where, values = ["lookup MATCH ?"], [match]
        if project:
            where.append("project=?")
            values.append(project)
        if kind:
            where.append("kind=?")
            values.append(kind)
        clause = " AND ".join(where)
        with self.connect() as db:
            total = db.execute("SELECT count(*) FROM lookup WHERE " + clause, values).fetchone()[0]
            rows = db.execute("SELECT id,kind,project,path,title,snippet(lookup,5,'[',']',' … ',24) AS excerpt FROM lookup WHERE "
                              + clause + " ORDER BY CASE kind WHEN 'capability' THEN 0 WHEN 'project' THEN 1 ELSE 2 END,bm25(lookup,0,0,0,4,6,1),id LIMIT ? OFFSET ?",
                              [*values, limit, offset]).fetchall()
            stamp = db.execute("SELECT value FROM meta WHERE key='indexed_at'").fetchone()
        return {"items": [dict(row) for row in rows], "total": total, "next_offset": offset + limit if offset + limit < total else None,
                "indexed_at": stamp[0] if stamp else None, "note": "Source summaries only. Read live line ranges for implementation; refresh to discover new files."}

    def read(self, project, path, start=1, lines=60):
        roots = self.config.roots()
        if project not in roots:
            raise APIError("Unknown project.", "not_found", 404)
        root = roots[project][1]
        target = inside(root, path)
        relative = target.relative_to(root).as_posix()
        with self.connect() as db:
            indexed = db.execute("SELECT mtime,size FROM files WHERE project=? AND path=?", (project, relative)).fetchone()
        if not indexed or not eligible(target):
            raise APIError("File is outside the source index. Refresh the catalog if it is new.", "not_indexed", 404)
        stat = target.stat()
        if stat.st_size > 512_000:
            raise APIError("File exceeds the source read limit.")
        text = target.read_text(encoding="utf-8", errors="replace").splitlines()
        chosen = text[start - 1:start - 1 + lines]
        rendered = "\n".join(f"{i}: {line[:2000]}" for i, line in enumerate(chosen, start))
        clipped = len(rendered) > 20_000
        return {"project": project, "path": relative, "start": start, "total_lines": len(text),
                "text": rendered[:20_000], "truncated": clipped,
                "next_start": start + len(chosen) if not clipped and start + len(chosen) <= len(text) else None,
                "changed_since_index": (stat.st_mtime_ns, stat.st_size) != tuple(indexed), "untrusted_data": True}
