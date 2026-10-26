"""Thin local web host. All durable/domain operations are implemented in DumbAPI."""
import argparse
import hmac
import json
import mimetypes
import os
import secrets
import sys
import threading
import time
from contextlib import nullcontext
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "backend"))
from dumbapi_core.app import App
from dumbapi_core.common import APIError, Config, json_text
from dumbapi_core.manager import Manager
from dumbapi_core.manager_media import Media
from dumbapi_core.replay import Replay
from cook_control import Cook
from dumbapi_core.manager_social_gif import SMOKE

ALLOWED = {"projects.list", "workspace.status", "workspace.configure",
           "bridge.status", "bridge.configure", "bridge.discord.commands", "bridge.discord.register",
           "t3.threads", "t3.read", "t3.send", "t3.connect", "t3.distributions", "t3.select_distribution", "git.projects", "git.status", "git.diff", "git.history", "git.action", "git.clone",
           "browser.status", "browser.start", "browser.stop", "browser.snapshot", "browser.frame", "browser.interact", "browser.action", "browser.connect", "browser.suggest", "browser.plan", "browser.apply"}


def make_server(port=8783, config=None):
    backend = App(config or Config())
    manager = Manager(backend.config)
    media = Media(manager)
    cook = Cook(backend)
    token_path = manager.data / "desktop.token"
    if not token_path.exists():
        try:
            with token_path.open("x", encoding="utf-8") as handle:
                handle.write(secrets.token_urlsafe(32))
        except FileExistsError:
            pass
    desktop_token = token_path.read_text(encoding="utf-8").strip()
    session = secrets.token_urlsafe(32)
    replay = Replay(manager.data)
    previews, preview_lock = {}, threading.Lock()
    upload_slots = threading.BoundedSemaphore(2)
    preview_csp = ("default-src 'none'; script-src 'unsafe-inline' https:; style-src 'unsafe-inline' https:; "
                   "img-src data: blob: https:; font-src data: https:; media-src data: blob: https:; "
                   "connect-src 'none'; frame-src 'none'; frame-ancestors 'self'; base-uri 'none'; form-action 'none'; sandbox allow-scripts")

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_):
            pass

        def host_ok(self):
            return self.headers.get("Host") in {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}

        def authorized(self):
            origin = self.headers.get("Origin")
            if origin and origin not in {f"http://127.0.0.1:{self.server.server_port}", f"http://localhost:{self.server.server_port}"}:
                return False
            auth = self.headers.get("Authorization", "")
            if auth.startswith("Bearer ") and hmac.compare_digest(auth[7:], desktop_token):
                return True
            cookie = SimpleCookie()
            try:
                cookie.load(self.headers.get("Cookie", ""))
                value = cookie.get(f"dm_session_{self.server.server_port}")
                return bool(value and hmac.compare_digest(value.value, session) and self.headers.get("X-DumbManager") == "1")
            except Exception:
                return False

        def send(self, status, payload, mime="application/json; charset=utf-8", cookie=False, csp=None, script_nonce=None):
            raw = payload if isinstance(payload, bytes) else json_text(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(raw)))
            if self.close_connection:
                self.send_header("Connection", "close")
            self.send_header("Cache-Control", "no-store" if not mime.startswith("font/") else "public,max-age=86400")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            policy = csp or "default-src 'self'; script-src 'self'; style-src 'self'; font-src 'self'; img-src 'self' blob:; media-src 'self' blob:; connect-src 'self' https://api.openai.com wss://generativelanguage.googleapis.com; frame-src 'self' http://127.0.0.1:* http://localhost:*; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
            if script_nonce:
                policy = policy.replace("script-src 'self';", f"script-src 'self' 'nonce-{script_nonce}';")
            self.send_header("Content-Security-Policy", policy)
            if cookie:
                self.send_header("Set-Cookie", f"dm_session_{self.server.server_port}={session}; HttpOnly; SameSite=Strict; Path=/")
            try:
                self.end_headers()
                self.wfile.write(raw)
            except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):
                self.close_connection=True  # A reload can close an otherwise valid in-flight reply.

        def do_GET(self):
            if not self.host_ok():
                return self.send(403, {"error": "Loopback host required."})
            path = urlsplit(self.path).path
            if path.startswith("/preview/"):
                with preview_lock:
                    entry = previews.get(path)
                if not entry or entry[0] < time.monotonic():
                    return self.send(404, {"error": "Preview expired. Open it again from chat."})
                return self.send(200, entry[1], "text/html; charset=utf-8", csp=preview_csp)
            if path == "/health":
                return self.send(200, {"name": "DumbManager", "version": "0.1.0", "backend": "DumbAPI", "pid": os.getpid()})
            path = "/index.html" if path == "/" else path
            if path == "/ascii-smoke.js":
                return self.send(200, SMOKE.read_bytes(), "text/javascript; charset=utf-8")
            allowed = {"/index.html", "/app.js", "/t3-settings.js", "/bridge.js", "/ai.js", "/voice.js", "/pcm-worklet.js", "/social.js", "/webhook.js", "/intake.js", "/git.js", "/browse.js", "/ui.js", "/aquarium.js", "/chat.js", "/itches.js", "/richtext.js", "/previews.js", "/attachments.js", "/style.css", "/fonts/SpaceGrotesk.ttf", "/fonts/IBMPlexMono.ttf", "/fonts/Silkscreen.ttf"}
            allowed.update({"/learning.js", "/learning.css"})
            allowed.update({"/research.js", "/research.css"})
            allowed.update({"/inspiration.js", "/inspiration.css"})
            if path not in allowed:
                return self.send(404, {"error": "Not found"})
            file = ROOT / "web" / path.lstrip("/")
            if not file.is_file():
                return self.send(404, {"error": "Not found"})
            mime = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
            if path == "/index.html":
                nonce = secrets.token_urlsafe(18)
                startup = (ROOT / "web/startup.js").read_text(encoding="utf-8")
                html = file.read_text(encoding="utf-8").replace('<!-- STARTUP_RECOVERY -->', f'<script nonce="{nonce}">{startup}</script>')
                return self.send(200, html.encode("utf-8"), "text/html; charset=utf-8", cookie=True, script_nonce=nonce)
            self.send(200, file.read_bytes(), mime, cookie=path == "/index.html")

        def do_POST(self):
            if not self.host_ok() or not self.authorized():
                # The rejected request body has not been consumed. Reusing this
                # socket would parse that JSON as the next HTTP request line.
                self.close_connection = True
                return self.send(403, {"error": "Local session required."})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if urlsplit(self.path).path in {"/api/upload", "/api/itch-upload"}:
                    from dumbapi_core.t3 import T3
                    from dumbapi_core.t3_uploads import MAX_UPLOAD, upload
                    if not 0 < length <= MAX_UPLOAD:
                        self.close_connection = True
                        raise APIError("Attach a nonempty file up to 50 MiB.", "too_large", 413)
                    # Capture exact destination before consuming bytes. This does
                    # not send a chat message; chips wait for explicit Send.
                    local = urlsplit(self.path).path == "/api/itch-upload"
                    thread_id = self.headers.get("X-Thread-Id", "")
                    if not local:
                        T3.thread_id(thread_id)
                        from dumbapi_core.t3_distributions import request_target
                        with request_target(self.headers.get('X-T3-Target')):
                            T3(backend.config).connection()
                    if not upload_slots.acquire(blocking=False):
                        self.close_connection = True
                        raise APIError("Two files are already processing. Try again shortly.", "busy", 429)
                    try:
                        self.connection.settimeout(60)
                        uploader = media.upload if local else upload
                        from dumbapi_core.t3_distributions import connection_lock, request_target
                        with (connection_lock(backend.config) if not local else nullcontext()), request_target(self.headers.get('X-T3-Target')):
                            result = uploader(backend.config, self.rfile, length,
                                            unquote(self.headers.get("X-File-Name", "attachment")),
                                            self.headers.get("X-File-Type", "application/octet-stream"),
                                            self.headers.get("X-Video-Mode", "frameboard"))
                        return self.send(200, {**result, "thread_id": thread_id})
                    finally:
                        upload_slots.release()
                if not 0 < length <= 80_000:
                    self.close_connection = True
                    raise APIError("Use a JSON request under 80 KB.")
                value = json.loads(self.rfile.read(length))
                if not isinstance(value, dict):
                    raise APIError("Expected a JSON object.")
                path = urlsplit(self.path).path
                if path == "/api/call":
                    name, args = value.get("name", ""), value.get("args", {})
                    if not isinstance(name, str) or not isinstance(args, dict):
                        raise APIError("Expected a named capability and object arguments.")
                    if not (name.startswith(("manager.", "ai.")) or name in ALLOWED):
                        raise APIError("That operation is not exposed by this UI.", "forbidden", 403)
                    from dumbapi_core.t3_distributions import request_target
                    with request_target(value.get('t3_target')):
                        result = backend.call(name, args, value.get("idempotency_key"))
                    if name == "manager.capture":
                        replay.finish(result["id"])
                    self.send(200, result)
                elif path == "/api/preview":
                    from dumbapi_core.t3_distributions import request_target
                    with request_target(value.get('t3_target')):
                        result = backend.call("t3.preview", {"thread_id": value["thread_id"], "attachment_id": value["attachment_id"]})
                    document = result.pop("html").encode("utf-8")
                    ticket = "/preview/" + secrets.token_urlsafe(32)
                    with preview_lock:
                        for old in list(previews):
                            if previews[old][0] < time.monotonic():
                                del previews[old]
                        while len(previews) >= 4:
                            del previews[next(iter(previews))]
                        previews[ticket] = (time.monotonic() + 600, document)
                    self.send(200, {**result, "url": ticket})
                elif path == "/api/jobs":
                    self.send(200, backend.jobs.view(value["id"], 10) if value.get("id") else backend.jobs.list(15))
                elif path == "/api/itch-media":
                    file, metadata = media.read(value.get("id"))
                    self.send(200, file.read_bytes(), metadata["mimeType"])
                elif path == "/api/native":
                    from native_control import control
                    if value.get('itch_id'):
                        backend.call('manager.get', {'id':value['itch_id']})
                        self.send(200, control(manager.data, value.get("action", "status"), value['itch_id']))
                    else:
                        self.send(200, control(manager.data, value.get("action", "status")))
                elif path == "/api/cook":
                    self.send(200, cook.control(value))
                elif path == "/api/replay":
                    action = value.get("action", "status")
                    if action not in {"status", "windows", "arm", "disarm", "begin", "item", "keep", "delete", "frame"}:
                        raise APIError("Unknown replay action.")
                    result = getattr(replay, action)(**{k: v for k, v in value.items() if k != "action"})
                    if action == "frame":
                        self.send(200, result, "image/jpeg")
                    else:
                        self.send(200, result)
                elif path == "/api/shutdown":
                    self.send(200, {"stopping": True})
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
                else:
                    self.send(404, {"error": "Not found"})
            except APIError as exc:
                if urlsplit(self.path).path in {"/api/upload", "/api/itch-upload"}:
                    self.close_connection = True
                self.send(exc.status, {"error": str(exc), "code": exc.code,
                          **({'retry_after_ms':exc.retry_after_ms} if hasattr(exc, 'retry_after_ms') else {})})
            except (ValueError, TypeError, KeyError) as exc:
                self.send(400, {"error": str(exc)})
            except Exception as exc:
                self.send(500, {"error": f"{type(exc).__name__}: {exc}"})

    class SessionServer(ThreadingHTTPServer):
        def server_close(self):
            from dumbapi_core.browser import close_instance
            try:
                close_instance(backend.config)
            finally:
                super().server_close()

    server = SessionServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    server.replay = replay
    return server


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8783)
    args = parser.parse_args()
    server = make_server(args.port)
    try:
        server.serve_forever(poll_interval=.3)
    finally:
        server.replay.disarm()
        server.server_close()


if __name__ == "__main__":
    main()
