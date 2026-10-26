"""Explicit itch-to-thread handoff with durable media mappings and retry identity."""
import hashlib
import json
import os
from contextlib import contextmanager

from .common import APIError, json_text, now
from .manager import Manager, text
from .manager_media import Media
from .t3 import T3
from .t3_distributions import connection_lock, target
from .t3_uploads import upload


@contextmanager
def sending_lock(path):
    # Separate from the manager DB: uploads must not block ordinary itch saves.
    with path.open("a+b") as handle:
        try:
            handle.seek(0)
            if not handle.read(1):
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise APIError("Another itch is being sent. Retry when that send finishes.", "busy", 409) from None
        try:
            yield
        finally:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


class Handoff:
    def __init__(self, config):
        self.config, self.manager = config, Manager(config)
        self.media = Media(self.manager)
        with self.manager.db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS handoffs(key TEXT PRIMARY KEY,digest TEXT NOT NULL,data TEXT NOT NULL)")

    def save(self, key, digest, value):
        with self.manager.db() as db:
            db.execute("INSERT OR REPLACE INTO handoffs VALUES (?,?,?)", (key, digest, json_text(value)))

    def finish(self, id, request_key, result):
        with self.manager.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self.manager.get(db, id, "itch")
            history = row.get("handoffs", [])
            if not any(item["request_key"] == request_key for item in history):
                row["handoffs"] = (history + [{"request_key": request_key, "thread_id": result["thread_id"],
                                              "message_id": result["message_id"], "at": result["sent_at"]}])[-20:]
                row["version"] += 1
                row["updated_at"] = now()
                self.manager.put(db, "itch", row)
        return result

    def send(self, id, thread_id, request_key, message="", video_mode="frameboard", followup=""):
        T3.thread_id(thread_id)
        request_key, message, followup = text(request_key, 100), text(message, 12000), text(followup, 2000)
        if not request_key or video_mode not in ("frameboard", "original"):
            raise APIError("Use a retry key and choose frameboard or original video.")
        digest = hashlib.sha256(json_text([id, thread_id, message, video_mode]+([followup] if followup else [])).encode()).hexdigest()
        with sending_lock(self.manager.data / "handoff.lock"), connection_lock(self.config):
            with self.manager.db() as db:
                db.execute("BEGIN IMMEDIATE")
                saved = db.execute("SELECT digest,data FROM handoffs WHERE key=?", (request_key,)).fetchone()
                if saved and saved["digest"] != digest:
                    raise APIError("This retry belongs to different text, evidence or a different thread. Retry the original send.", "conflict", 409)
                pending = json.loads(saved["data"]) if saved else None
                if not pending:
                    row = self.manager.get(db, id, "itch")
                    brief = self.manager.op_brief(db, id)["brief"]
                    brief = brief.replace("Open this itch in DumbManager to inspect it. These local files are not automatically sent to T3.",
                                          "The visual evidence is attached to this message. Video frameboards contain sampled timestamps and no audio.")
                    pending = {"message": message or brief, "local": row.get("attachments", []), "uploaded": [], "result": None,
                               "target": target(self.config)}
                    if followup:
                        pending['message'] = ('Follow-up request: '+followup+'\n\n'+pending['message']+
                            '\n\nContinue from the latest result on this same itch. Recheck the requested change; completed plan steps are history. Preserve earlier evidence and outcomes. Report ready for review; acceptance stays with the user.')
                    if len(pending["message"]) > 12000:
                        raise APIError("Shorten this handoff to 12,000 characters before sending.")
                    if followup:
                        # Save the feedback and retry identity together before uploads.
                        # A failed/lost send can resume without appending it twice.
                        self.manager.op_update(db, id, changes={'state':'open','run_state':'not_sent',
                            'feedback':row['feedback']+[{'at':now(),'text':followup,'request_key':request_key}]}, expected_version=row['version'])
                        db.execute('INSERT INTO handoffs VALUES (?,?,?)',(request_key,digest,json_text(pending)))
            if pending["result"]:
                return self.finish(id, request_key, pending["result"])
            if pending.get("target") and pending["target"] != target(self.config):
                raise APIError("This handoff belongs to the other T3 installation. Switch back before retrying it.", "t3_target_changed", 409)
            self.save(request_key, digest, pending)
            # Validate remaining source files before uploading any of them. The
            # mapping is committed after each upload and reused after failures.
            remaining = pending["local"][len(pending["uploaded"]):]
            sources = [self.media.read(item["id"]) for item in remaining]
            for file, metadata in sources:
                with file.open("rb") as stream:
                    result = upload(self.config, stream, metadata["sizeBytes"], metadata["name"], metadata["mimeType"], video_mode)
                pending["uploaded"].append(result["attachment"])
                self.save(request_key, digest, pending)
            receipt = T3(self.config).send(thread_id, pending["message"], "itch:" + request_key, json_text(pending["uploaded"]))
            result = {**receipt, "id": id, "sent_at": now(), "attachment_count": len(pending["uploaded"]),
                      "thread_url": "t3-thread://v1/" + thread_id}
            pending["result"] = result
            self.save(request_key, digest, pending)
            return self.finish(id, request_key, result)
