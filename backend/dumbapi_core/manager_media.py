"""Local itch evidence. Bounded streaming storage, independent of T3 accounts."""
import base64
import json
import mimetypes
import re
import shutil
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .common import APIError, now
from .t3_uploads import IMAGE_TYPES, MAX_UPLOAD, frameboard

MAX_TOTAL = 512 * 1024 * 1024


class Media:
    def __init__(self, manager):
        self.manager = manager
        self.folder = manager.data / "itch-media"
        self.folder.mkdir(exist_ok=True)

    @staticmethod
    def public(row):
        return {key: row[key] for key in ("id", "type", "name", "mimeType", "sizeBytes", "note")}

    def read(self, id):
        if not isinstance(id, str) or not re.fullmatch(r"[a-f0-9]{32}", id):
            raise APIError("Invalid evidence ID.")
        with self.manager.db() as db:
            row = self.manager.get(db, id, "media")
        file = self.folder / id / "content"
        if not file.is_file():
            raise APIError("This evidence file is missing from local storage.", "not_found", 404)
        return file, row

    def references(self, db, ids):
        if not isinstance(ids, list) or len(ids) > 8 or any(not isinstance(id, str) for id in ids) or len(set(ids)) != len(ids):
            raise APIError("Attach up to eight different evidence IDs.")
        rows = [self.manager.get(db, id, "media") for id in ids]
        if sum(row["sizeBytes"] for row in rows) > 80 * 1024 * 1024:
            raise APIError("Keep one itch's attachments under 80 MiB.")
        for row in rows:
            if not re.fullmatch(r"[a-f0-9]{32}", row["id"]) or not (self.folder / row["id"] / "content").is_file():
                raise APIError("An evidence file is missing. Attach it again before saving.")
            row["claimed"] = True
            self.manager.put(db, "media", row)
        return [self.public(row) for row in rows]

    def upload(self, config, stream, size, name, mime, video_mode="original"):
        if not 0 < size <= MAX_UPLOAD:
            raise APIError("Use a nonempty image or video up to 50 MiB.", "too_large", 413)
        name = re.sub(r'[\x00-\x1f<>:"/\\|?*]', "_", name).strip()[:220] or "evidence"
        mime = mime.lower().split(";", 1)[0].strip()
        if mime in ("", "application/octet-stream"):
            mime = mimetypes.guess_type(name)[0] or ""
        if mime not in IMAGE_TYPES and not re.fullmatch(r"video/[\w.+-]+", mime):
            raise APIError("Stash supports PNG, JPEG, WebP, GIF and videos. Use Chat for other files.")
        if mime in IMAGE_TYPES and size > 10 * 1024 * 1024:
            raise APIError("Resize images to 10 MiB or less.", "too_large", 413)
        if video_mode not in ("original", "frameboard"):
            raise APIError("Choose original video or frameboard.")
        identifier, thumbnail = uuid.uuid4().hex, None
        destination = self.folder / identifier
        try:
            with tempfile.TemporaryDirectory(prefix="upload-", dir=self.folder) as temporary:
                folder = Path(temporary)
                source = folder / ("input" + Path(name).suffix[:12])
                with source.open("wb") as output:
                    remaining = size
                    while remaining:
                        chunk = stream.read(min(65536, remaining))
                        if not chunk:
                            raise APIError("Upload interrupted. Your draft is kept; attach the file again.")
                        output.write(chunk)
                        remaining -= len(chunk)
                note = "Saved locally with this itch"
                if mime.startswith("video/") and video_mode == "frameboard":
                    source, duration = frameboard(source, folder, config.root)
                    name = Path(name).stem[:150] + f"-frameboard-{duration:.1f}s-no-audio.jpg"
                    mime, size = "image/jpeg", source.stat().st_size
                    thumbnail = base64.b64encode(source.read_bytes()).decode("ascii")
                    note = f"9 timestamped samples across {duration:.1f}s; no audio. Original video is not kept."
                elif mime.startswith("video/"):
                    note = "Original video saved locally; playback depends on your browser's codecs"
                stamp = now()
                row = {"id": identifier, "type": "image" if mime in IMAGE_TYPES else "video", "name": name,
                       "mimeType": mime, "sizeBytes": size, "note": note, "created_at": stamp,
                       "updated_at": stamp, "claimed": False}
                with self.manager.db() as db:
                    db.execute("BEGIN IMMEDIATE")
                    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
                    total = 0
                    for entry in db.execute("SELECT id,data FROM records WHERE kind='media'").fetchall():
                        old = json.loads(entry["data"])
                        if not old["claimed"] and old["created_at"] < cutoff:
                            shutil.rmtree(self.folder / old["id"], ignore_errors=True)
                            db.execute("DELETE FROM records WHERE id=? AND kind='media'", (old["id"],))
                        else:
                            file = self.folder / old["id"] / "content"
                            total += file.stat().st_size if file.is_file() else 0
                    if total + size > MAX_TOTAL:
                        raise APIError("Local itch evidence has reached its 512 MiB budget. Back up and free local media space first.", "too_large", 413)
                    destination.mkdir()
                    source.replace(destination / "content")
                    self.manager.put(db, "media", row)
            return {"attachment": self.public(row), "note": note, "thumbnail": thumbnail}
        except BaseException:
            shutil.rmtree(destination, ignore_errors=True)
            raise
