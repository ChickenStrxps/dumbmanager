"""On-demand, scoped T3 orchestration adapter. No private database or resident client."""
import base64
import hashlib
import json
import os
import re
import socket
import sqlite3
import struct
import subprocess
import time
import uuid
from contextlib import closing
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .common import APIError, atomic_json, now, read_json

MAX_REPLY = 4 * 1024 * 1024
MAX_PREVIEW = 2 * 1024 * 1024


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise APIError("T3 redirected its local endpoint. Reconnect T3.", "t3_unavailable", 503)


def rpc(connection, tag, payload):
    """One bounded Effect JSON RPC over an RFC6455 socket, then disconnect."""
    url = urlsplit(connection["url"])
    key = base64.b64encode(os.urandom(16)).decode()
    deadline = time.monotonic() + 12
    with socket.create_connection((url.hostname, url.port), timeout=8) as sock:
        sock.settimeout(8)
        with sock.makefile("rb") as reader:
            headers = (f"GET /ws?orchestrationProtocol=2 HTTP/1.1\r\nHost: {url.netloc}\r\n"
                       f"Upgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
                       "Sec-WebSocket-Version: 13\r\n"
                       f"Authorization: Bearer {connection['token']}\r\n\r\n")
            sock.sendall(headers.encode("ascii"))
            status = reader.readline(4096)
            response_headers, count = {}, len(status)
            while True:
                line = reader.readline(4096)
                count += len(line)
                if count > 16384 or not line:
                    raise APIError("Invalid T3 handshake.", "t3_unavailable", 503)
                if line == b"\r\n":
                    break
                k, _, v = line.decode("latin1").partition(":")
                response_headers[k.lower()] = v.strip()
            expected = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
            if status.split()[1:2] != [b"101"] or response_headers.get("sec-websocket-accept") != expected:
                raise APIError("T3 refused its chat connection. Reconnect the local T3 session.", "t3_unavailable", 503)

            def send(raw, opcode=1):
                mask = os.urandom(4)
                n = len(raw)
                length = bytes([128 | n]) if n < 126 else bytes([128 | 126]) + struct.pack("!H", n) if n <= 65535 else bytes([128 | 127]) + struct.pack("!Q", n)
                sock.sendall(bytes([128 | opcode]) + length + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(raw)))

            def exact(n):
                raw = reader.read(n)
                if len(raw) != n:
                    raise ConnectionError("T3 disconnected before confirming delivery.")
                return raw

            send(json.dumps({"_tag": "Request", "id": "1", "tag": tag, "payload": payload, "headers": []}).encode())
            fragments, total = bytearray(), 0
            for _ in range(128):
                sock.settimeout(max(.1, min(8, deadline-time.monotonic())))
                if time.monotonic() > deadline:
                    raise TimeoutError("T3 did not confirm in time.")
                a, b = exact(2)
                n, opcode = b & 127, a & 15
                if n == 126:
                    n = struct.unpack("!H", exact(2))[0]
                elif n == 127:
                    n = struct.unpack("!Q", exact(8))[0]
                total += n
                if b & 128 or total > MAX_REPLY or a & 112:
                    raise APIError("T3 reply exceeded the supported local protocol.", "t3_unavailable", 503)
                raw = exact(n)
                if opcode == 9:
                    send(raw, 10)
                    continue
                if opcode == 8:
                    raise ConnectionError("T3 closed before confirming delivery.")
                if opcode == 10:
                    continue
                if opcode not in (0, 1):
                    raise APIError("Unsupported T3 frame.", "t3_unavailable", 503)
                fragments.extend(raw)
                if not a & 128:
                    continue
                value = json.loads(fragments)
                fragments.clear()
                for message in value if isinstance(value, list) else [value]:
                    if message.get("_tag") == "Ping":
                        send(b'{"_tag":"Pong"}')
                    if message.get("_tag") == "Exit" and str(message.get("requestId")) == "1":
                        send(struct.pack("!H", 1000), 8)
                        result = message.get("exit", {})
                        if result.get("_tag") == "Success":
                            return result.get("value")
                        raise APIError("T3 rejected the message. Open the thread to check its state.", "t3_rejected", 409)
            raise APIError("T3 returned too many frames.", "t3_unavailable", 503)


class T3:
    def __init__(self, config):
        self.config = config

    def connect(self, port=3773):
        from .t3_distributions import connection_lock
        with connection_lock(self.config):
            return self._connect(port)

    def _connect(self, port):
        """Explicit local pairing through T3's own CLI; no user token in the UI."""
        cli = Path.home()/".t3/bin/t3.cmd"
        if not cli.is_file():
            raise APIError("T3's local CLI is missing. Open T3 Code once, then reconnect.", "t3_unavailable", 503)
        try:
            process = subprocess.run([str(cli), "auth", "session", "issue", "--scope", "orchestration:read",
                                      "--scope", "orchestration:operate", "--ttl", "30d", "--label", "DumbManager local chat", "--json"],
                                     capture_output=True, text=True, timeout=20, creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
            if process.returncode or len(process.stdout)>32000:
                raise ValueError()
            value = json.loads(process.stdout)
            if not isinstance(value.get("token"),str) or not value["token"]:
                raise ValueError()
            value["url"] = f"http://127.0.0.1:{port}"
            atomic_json(self.config.data / "t3-connection.json", value)
            return {"connected":True, "expires_at":value.get("expiresAt"), "note":"Local T3 chat connected for 30 days. Choose a thread in Chat to T3."}
        except (OSError, ValueError, subprocess.SubprocessError):
            raise APIError("T3 pairing failed. Open T3 Code and try reconnecting. Existing settings are kept.", "t3_unavailable", 503) from None

    @staticmethod
    def validate_connection(value):
        url = urlsplit(value.get("url", ""))
        if url.scheme != "http" or url.hostname != "127.0.0.1" or not url.port or url.path not in ("", "/") or url.query or url.fragment or url.username:
            raise ValueError()
        token = value["token"]
        if not isinstance(token, str) or not token or any(c.isspace() for c in token):
            raise ValueError()
        return value

    def connection(self):
        try:
            value = self.validate_connection(read_json(self.config.data / "t3-connection.json"))
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            raise APIError("Connect DumbManager to a local T3 session first. See Make it yours.", "t3_not_connected", 503) from None
        from .t3_distributions import check_target
        check_target(value)
        return value

    def distributions(self):
        from .t3_distributions import Distributions
        return Distributions(self.config).list()

    def select_distribution(self, distribution, reconnect=False, expected_target=""):
        from .t3_distributions import Distributions
        return Distributions(self.config).select(distribution, reconnect, expected_target)

    def get(self, route):
        return self.get_from(self.connection(), route)

    def get_from(self, value, route):
        headers = {"Authorization": "Bearer " + value["token"], "x-t3-orchestration-protocol": "2"}
        try:
            with build_opener(ProxyHandler({}), NoRedirect()).open(Request(value["url"].rstrip("/") + route, headers=headers), timeout=getattr(self, "read_timeout", 8)) as response:
                raw = response.read(MAX_REPLY + 1)
                if len(raw) > MAX_REPLY:
                    raise APIError("T3 reply is too large for this compact view. Open the thread in T3.", "t3_unavailable", 503)
                return json.loads(raw)
        except HTTPError as exc:
            message = "T3 session expired; reconnect it." if exc.code in (401, 403) else "T3 could not open that thread."
            exc.close()
            raise APIError(message, "t3_unavailable", 503) from None
        except (URLError, OSError, ValueError):
            raise APIError("Local T3 is unavailable. Your draft is kept.", "t3_unavailable", 503) from None

    @staticmethod
    def thread_id(value):
        try:
            # T3-created conversations use UUIDs; MCP-created conversations keep
            # the exact `mcp:` prefix in both shell choices and dispatch/read APIs.
            identifier = value.removeprefix("mcp:")
            if str(uuid.UUID(identifier)) != identifier.lower():
                raise ValueError()
            return value
        except (ValueError, TypeError, AttributeError):
            raise APIError("Choose an exact T3 thread.") from None

    @staticmethod
    def compact(row):
        return {"id": row["id"], "title": row.get("title", "Untitled"), "project_id": row.get("projectId"),
                "status": row.get("activityRunStatus") or row.get("status"), "active": bool(row.get("activeRunId")),
                "updated_at": row.get("updatedAt"), "archived": bool(row.get("archivedAt")),
                "model": row.get("modelSelection", {}).get("model")}

    def threads(self, query="", limit=60):
        shell = self.get("/api/orchestration/shell")
        projects = {p["id"]: p.get("title") or p.get("name") or "Project" for p in shell.get("projects", [])}
        rows = [{**self.compact(t), "project": projects.get(t.get("projectId"), "Project")} for t in shell.get("threads", [])
                if not t.get("deletedAt") and t.get("lineage", {}).get("relationshipToParent") != "subagent"]
        rows = [r for r in rows if all(w in (r["title"]+" "+r["project"]).casefold() for w in query.casefold().split())]
        rows.sort(key=lambda r:r.get("updated_at") or "", reverse=True)
        return {"items": rows[:limit], "total": len(rows), "partial": len(rows)>limit, "connected": True}

    def read(self, thread_id):
        self.thread_id(thread_id)
        data = self.get("/api/orchestration/threads/" + thread_id + "/bounded?compactTurnItems=1")
        projection = data["projection"]
        messages = [{"id": m["id"], "role": m["role"], "text": m.get("text", "")[:6000],
                     "truncated": len(m.get("text", ""))>6000, "streaming": m.get("streaming", False), "at": m.get("createdAt"),
                     "attachments": [{k:a.get(k) for k in ("id","type","name","mimeType","sizeBytes")} for a in m.get("attachments", [])[:8]]}
                    for m in projection.get("messages", []) if m.get("role") in ("user", "assistant") and (m.get("text") or m.get("attachments"))]
        messages.sort(key=lambda m:m.get("at") or "")
        thread = self.compact(projection["thread"])
        active = [r for r in projection.get("runs", []) if r.get("status") in ("running", "starting", "preparing", "waiting")]
        thread.update(active=bool(active), status=active[-1]["status"] if active else thread["status"])
        return {"thread": thread, "messages": messages[-8:], "previews": self.previews(projection),
                "queued": sum(r.get("status") == "queued" for r in projection.get("runs", [])),
                "partial": bool(data.get("hasMoreHistory")) or len(messages)>8,
                "note": "Eight recent messages · latest four published visuals. Open T3 for tools, approvals and full history."}

    @staticmethod
    def previews(projection):
        """Only references actually published by T3's HTML tool, never tool input HTML."""
        found = {}
        items = projection.get("visibleTurnItems", projection.get("turnItems", []))
        for entry in items:
            item = entry.get("item", entry)
            if item.get("type") != "dynamic_tool" or item.get("status") != "completed":
                continue
            if not re.fullmatch(r"(?:[\w-]+[._])?html_render", item.get("toolName", "")):
                continue
            output = item.get("output")
            if not isinstance(output, dict) or output.get("isError"):
                continue
            ref = output.get("htmlRender")
            if not isinstance(ref, dict):
                continue
            attachment = ref.get("attachmentId", "")
            height = ref.get("height")
            if not isinstance(attachment, str) or not re.fullmatch(r"[\w-]{1,256}", attachment):
                continue
            if not isinstance(height, (int, float)) or not 0 < height < 100_000:
                continue
            found[attachment] = {"id": attachment, "title": str(ref.get("title") or "Design preview")[:200],
                                 "height": min(1000, max(160, round(height))), "at": item.get("completedAt") or item.get("startedAt")}
        return sorted(found.values(), key=lambda r:r.get("at") or "")[-4:]

    def preview(self, thread_id, attachment_id):
        """Fetch one published HTML attachment on demand; no general file/URL reader."""
        self.thread_id(thread_id)
        data = self.get("/api/orchestration/threads/" + thread_id + "/bounded?compactTurnItems=1")
        ref = next((p for p in self.previews(data["projection"]) if p["id"] == attachment_id), None)
        if not ref:
            raise APIError("That visual is no longer in the bounded thread view. Open the full thread in T3.", "not_found", 404)
        connection = self.connection()
        try:
            asset = rpc(connection, "assets.createUrl", {"resource": {"_tag": "attachment", "attachmentId": attachment_id,
                        "fileName": "concept.html", "mimeType": "text/html", "disposition": "inline"}})
            route = asset.get("relativeUrl", "")
            if not re.fullmatch(r"/api/assets/[A-Za-z0-9_./?=&%-]{1,4096}", route) or ".." in route:
                raise ValueError()
            # Signed asset URL is kept on the server, with no credential forwarded.
            with build_opener(ProxyHandler({}), NoRedirect()).open(connection["url"].rstrip("/") + route, timeout=8) as response:
                if response.headers.get_content_type() != "text/html":
                    raise ValueError()
                raw = response.read(MAX_PREVIEW + 1)
                if len(raw) > MAX_PREVIEW:
                    raise APIError("This visual is larger than the 2 MiB lightweight preview limit. Open it in T3.", "preview_too_large", 413)
            return {**ref, "html": raw.decode("utf-8")}
        except (OSError, ValueError, URLError):
            raise APIError("That T3 visual could not load. Retry or open the full thread.", "t3_unavailable", 503) from None

    @staticmethod
    def attachment_list(encoded):
        try:
            rows = json.loads(encoded)
            if not isinstance(rows, list) or len(rows) > 8:
                raise ValueError()
            clean = []
            for row in rows:
                if not isinstance(row, dict) or set(row) != {"id","type","name","mimeType","sizeBytes"}:
                    raise ValueError()
                if not isinstance(row["id"], str) or not re.fullmatch(r"[\w-]{1,128}", row["id"]) or row["type"] not in ("image", "file"):
                    raise ValueError()
                if not isinstance(row["name"], str) or not 0 < len(row["name"]) <= 255 or not isinstance(row["mimeType"], str) or not re.fullmatch(r"[\w.+-]+/[\w.+-]+", row["mimeType"]):
                    raise ValueError()
                if type(row["sizeBytes"]) != int or not 0 < row["sizeBytes"] <= (10 if row["type"] == "image" else 50)*1024*1024:
                    raise ValueError()
                if row["type"] == "image" and row["mimeType"] not in ("image/jpeg","image/png","image/webp","image/gif"):
                    raise ValueError()
                clean.append(row)
            if sum(a["sizeBytes"] for a in clean) > 80*1024*1024 or len({a["id"] for a in clean}) != len(clean):
                raise ValueError()
            return clean
        except (ValueError, TypeError, KeyError):
            raise APIError("Use up to eight uploaded attachments (80 MiB total). Pick the files again if their details are missing.") from None

    def send(self, thread_id, message, request_key, attachments="[]"):
        from .t3_distributions import connection_lock
        with connection_lock(self.config):
            return self._send(thread_id, message, request_key, attachments)

    def _send(self, thread_id, message, request_key, attachments):
        self.thread_id(thread_id)
        files = self.attachment_list(attachments)
        if (not message.strip() and not files) or len(message)>12000 or not request_key.strip() or len(request_key)>120:
            raise APIError("Use a message up to 12,000 characters and a stable request key.")
        digest = hashlib.sha256((thread_id + "\0" + message + ("\0" + json.dumps(files, sort_keys=True, separators=(",", ":")) if files else "")).encode()).hexdigest()
        connection = self.connection()
        with closing(sqlite3.connect(self.config.data / "t3-receipts.sqlite3", timeout=20)) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS receipts (key TEXT PRIMARY KEY, digest TEXT, command TEXT, message TEXT, result TEXT, at TEXT)")
            if "destination" not in {r[1] for r in db.execute("PRAGMA table_info(receipts)")}:
                db.execute("ALTER TABLE receipts ADD COLUMN destination TEXT")
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT digest,command,message,result,destination FROM receipts WHERE key=?", (request_key,)).fetchone()
            if old and old[0] != digest:
                raise APIError("This send key already belongs to different words or a different thread.", "conflict", 409)
            if old and old[3]:
                return json.loads(old[3])
            if old and old[4] and old[4] != connection["url"]:
                raise APIError("This retry belongs to the other T3 installation. Switch back before retrying it.", "t3_target_changed", 409)
            command_id, message_id = (old[1:3] if old else (str(uuid.uuid4()), str(uuid.uuid4())))
            if not old:
                db.execute("INSERT INTO receipts VALUES (?,?,?,?,?,?,?)", (request_key,digest,command_id,message_id,None,now(),connection["url"]))
            # Commit the identifiers before transport: a lost receipt retries the
            # same T3 command, never a fresh message. Stored content is hashes only.
            db.commit()
            command = {"type":"message.dispatch", "commandId":command_id, "threadId":thread_id,
                       "messageId":message_id, "text":message, "attachments":files, "createdBy":"user",
                       "creationSource":"web", "dispatchMode":{"type":"queue_after_active"}}
            try:
                result = rpc(connection, "orchestration.dispatchCommand", command)
            except (OSError, ValueError):
                raise APIError("Delivery is unconfirmed. Retry these same words to this thread; the send key is kept.", "t3_unconfirmed", 503) from None
            receipt = {"accepted":True, "thread_id":thread_id, "message_id":message_id, "sequence":result["sequence"],
                       "note":"Sent to T3. Queues after active work; starts when the thread can run."}
            db.execute("UPDATE receipts SET result=? WHERE key=?", (json.dumps(receipt),request_key))
            return receipt


def definitions():
    from .registry import boolean, capability, integer, string
    return [
        capability("t3.distributions", "dumbmanager", "Read installed T3 distribution choices and the saved selection. Returns no credentials; does not start apps, pair or contact T3.", {}),
        {**capability("t3.select_distribution", "dumbmanager", "Explicitly verify and select a known local T3 installation. Retains independent sessions and the previous connection if checking fails. Never starts an app or sends a message.",
                     {"distribution":string(enum=["t3"]), "reconnect":boolean(), "expected_target":string(default="",maxLength=200)}, ("distribution",)), "mode":"action"},
        {**capability("t3.connect", "dumbmanager", "Explicitly issue a dedicated 30-day local T3 session through its installed CLI, restricted to orchestration read/operate. Stores the credential locally; never returns it.", {"port":integer(3773,1024,65535)}), "mode":"action"},
        capability("t3.threads", "dumbmanager", "Read compact existing T3 thread choices using a dedicated scoped local connection. Never creates threads.", {"query":string(default="",maxLength=200), "limit":integer(100,1,200)}),
        capability("t3.read", "dumbmanager", "Read eight recent T3 text messages through bounded orchestration HTTP; no private database or chat persistence.", {"thread_id":string()}, ("thread_id",)),
        capability("t3.preview", "dumbmanager", "Fetch one of the latest four published T3 HTML visuals, on demand, up to 2 MiB. Returns untrusted HTML for a sandbox only; no general file or URL access.", {"thread_id":string(), "attachment_id":string(maxLength=256)}, ("thread_id","attachment_id")),
        {**capability("t3.send", "dumbmanager", "Send user-written text to an exact existing T3 thread. Queue after active work; retain stable command/message IDs across retries. No thread creation, interruption or mode changes.",
                     {"thread_id":string(), "message":string(maxLength=12000), "request_key":string(maxLength=120), "attachments":string(default="[]",maxLength=12000)}, ("thread_id","message","request_key")), "mode":"action"},
    ]
