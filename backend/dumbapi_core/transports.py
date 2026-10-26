"""Authenticated loopback HTTP and newline-delimited stdio MCP (no SDK)."""
import hmac
import json
import secrets
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import __version__
from .common import APIError, json_text
from .guidance import MCP_INSTRUCTIONS, guided

PROTOCOLS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
TOOLS = [
    {"name": "dumb_search", "description": "Find Projects capabilities, projects or source owners when the capability/schema is unknown. Reuse known contracts. Compact metadata, no media/dependency scans.",
     "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}, "project": {"type": "string"},
                     "kind": {"type": "string", "enum": ["capability", "project", "file"]},
                     "limit": {"type": "integer", "minimum": 1, "maximum": 50}, "offset": {"type": "integer", "minimum": 0}},
                     "required": ["query"], "additionalProperties": False},
     "annotations": {"readOnlyHint": True, "openWorldHint": False}},
    {"name": "dumb_describe", "description": "Get an unknown project or capability contract, including exact arguments, mode and examples; reuse it for later calls. Read project instructions before authoring inputs.",
     "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"], "additionalProperties": False},
     "annotations": {"readOnlyHint": True, "openWorldHint": False}},
    {"name": "dumb_call", "description": "Call a capability with a known schema. For lookups, report results/caveats and stop, including empty results; no extra audits or maintenance unless requested. Explicit render/compression requests create jobs; inspect with dumb_job and cancel queued work with jobs.cancel. social.schedule can schedule a post only with confirm=true after the user approved that specific post in this conversation; never immediate publishing. No captures or arbitrary shell execution.",
     "inputSchema": {"type": "object", "properties": {"capability": {"type": "string"}, "arguments": {"type": "object"},
                     "idempotency_key": {"type": "string"}}, "required": ["capability"], "additionalProperties": False},
     "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False}},
    {"name": "dumb_job", "description": "Inspect a job's state, queue position, elapsed seconds, cancellation eligibility and last log lines, or list recent jobs if id is omitted. queued/running does not mean success. Cancel queued work through dumb_call jobs.cancel.",
     "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}, "log_lines": {"type": "integer", "minimum": 0, "maximum": 100}}, "additionalProperties": False},
     "annotations": {"readOnlyHint": True, "openWorldHint": False}},
]


def job_view(app, id=None, log_lines=0):
    if not isinstance(log_lines, int) or isinstance(log_lines, bool) or not 0 <= log_lines <= 100:
        raise APIError("log_lines must be an integer from 0 to 100.")
    return app.jobs.view(id, log_lines) if id else app.jobs.list()


def mcp_response(app, request):
    if not isinstance(request, dict) or request.get("jsonrpc") != "2.0" or not isinstance(request.get("method"), str):
        return {"jsonrpc": "2.0", "id": request.get("id") if isinstance(request, dict) else None, "error": {"code": -32600, "message": "Invalid Request"}}
    if "id" not in request:
        return None
    rid, method = request["id"], request["method"]
    try:
        params = request.get("params", {})
        if not isinstance(params, dict):
            raise APIError("params must be an object.")
        if hasattr(app, 'mcp_touch'):
            app.mcp_touch()
        if method == "initialize":
            requested = params.get("protocolVersion")
            result = {"protocolVersion": requested if requested in PROTOCOLS else PROTOCOLS[0],
                      "capabilities": {"tools": {}}, "serverInfo": {"name": "DumbAPI", "version": __version__},
                      "instructions": getattr(app, 'mcp_instructions', MCP_INSTRUCTIONS)}
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": app.mcp_tools() if hasattr(app, 'mcp_tools') else TOOLS}
        elif method == "tools/call":
            args = params.get("arguments", {})
            name = params.get("name")
            tool = next((t for t in TOOLS if t["name"] == name), None)
            if not tool:
                raise APIError("Unknown tool.")
            if not isinstance(args, dict) or set(args) - set(tool["inputSchema"]["properties"]) or set(tool["inputSchema"].get("required", [])) - set(args):
                raise APIError("Invalid tool arguments.")
            try:
                if name == "dumb_search":
                    data = app.search(**args)
                elif name == "dumb_describe":
                    if not isinstance(args["id"], str):
                        raise APIError("id must be a string.")
                    data = app.describe(**args)
                elif name == "dumb_call":
                    if not isinstance(args["capability"], str):
                        raise APIError("capability must be a string.")
                    data = app.call(args["capability"], args.get("arguments"), args.get("idempotency_key"))
                else:
                    data = job_view(app, **args)
                result = {"content": [{"type": "text", "text": json_text(data)}],
                          "structuredContent": data if isinstance(data, dict) else {'data': data}, "isError": False}
            except APIError as exc:
                result = {"content": [{"type": "text", "text": json_text(guided({"error": exc.code, "message": str(exc)}))}], "isError": True}
        else:
            return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "Method not found"}}
        return {"jsonrpc": "2.0", "id": rid, "result": result}
    except (APIError, TypeError, ValueError) as exc:
        return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32602, "message": str(exc)}}


def mcp(app):
    for line in sys.stdin:
        try:
            if len(line) > 1_000_000:
                raise ValueError("Message too large")
            request = json.loads(line)
            result = mcp_response(app, request)
        except ValueError:
            result = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        except Exception as exc:
            print(f"DumbAPI: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
            result = {"jsonrpc": "2.0", "id": request.get("id") if isinstance(request, dict) else None,
                      "error": {"code": -32603, "message": "Internal error; see stderr"}}
        if result is not None:
            print(json_text(result), flush=True)


def token(config):
    path = config.data / "http.token"
    if not path.exists():
        try:
            with path.open("x", encoding="utf-8") as file:
                file.write(secrets.token_urlsafe(32))
            path.chmod(0o600)
        except FileExistsError:
            pass
    return path.read_text(encoding="utf-8").strip()


def server(app, port=None):
    port = app.config.port if port is None else port
    key = token(app.config)

    class Handler(BaseHTTPRequestHandler):
        server_version = "DumbAPI/" + __version__

        def log_message(self, format, *args):
            # Paths, queries and authorization are never written to request logs.
            pass

        def reply(self, code, body):
            raw = json_text(body).encode("utf-8") if body is not None else b''
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(raw)

        def handle_api(self):
            try:
                self.connection.settimeout(15)
                actual_port = self.server.server_port
                allowed_hosts = {f"127.0.0.1:{actual_port}", f"localhost:{actual_port}"}
                if self.headers.get("Host") not in allowed_hosts:
                    raise APIError("Invalid Host.", "forbidden", 403)
                origin = self.headers.get("Origin")
                if origin and origin not in {"http://" + h for h in allowed_hosts}:
                    raise APIError("Cross-origin requests are not accepted.", "forbidden", 403)
                uri = urlparse(self.path)
                if self.command == "GET" and uri.path == "/health":
                    return self.reply(200, app.health())
                if uri.path.startswith('/mcp/'):
                    # Stateless Streamable HTTP with JSON responses; no event stream.
                    # This token grants only one integration, never the owner /v1 API.
                    from .ai.service import ScopedApp
                    profile = uri.path.removeprefix('/mcp/')
                    auth = self.headers.get('Authorization', '')
                    app.ai.authenticate(profile, auth[7:] if auth.startswith('Bearer ') else '')
                    if self.command != 'POST':
                        return self.reply(405, {'error': 'Use POST for this stateless MCP endpoint.'})
                    version = self.headers.get('MCP-Protocol-Version')
                    if version and version not in PROTOCOLS:
                        raise APIError('Unsupported MCP protocol version.')
                    length = int(self.headers.get('Content-Length', '0'))
                    if not 0 < length <= 64000 or self.headers.get('Transfer-Encoding') or self.headers.get_content_type() != 'application/json':
                        raise APIError('Use a JSON MCP request of 1–64000 bytes.')
                    request = json.loads(self.rfile.read(length))
                    result = mcp_response(ScopedApp(app.ai, profile), request)
                    return self.reply(200 if result is not None else 202, result)
                if not hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + key):
                    raise APIError("Bearer token required; read the local http.token file.", "unauthorized", 401)
                query = {k: v[-1] for k, v in parse_qs(uri.query).items()}
                if self.command == "GET":
                    if uri.path == "/v1/search":
                        for field in ("limit", "offset"):
                            if field in query:
                                query[field] = int(query[field])
                        data = app.search(**query)
                    elif uri.path == "/v1/projects":
                        data = app.call("projects.list", {k: int(v) for k, v in query.items()})
                    elif uri.path.startswith("/v1/describe/"):
                        data = app.describe(uri.path.removeprefix("/v1/describe/"))
                    elif uri.path == "/v1/jobs":
                        data = app.jobs.list()
                    elif uri.path.startswith("/v1/jobs/"):
                        data = job_view(app, uri.path.removeprefix("/v1/jobs/"), int(query.get("log_lines", 0)))
                    else:
                        raise APIError("Route not found.", "not_found", 404)
                elif self.command == "POST" and uri.path == "/v1/stop":
                    self.reply(200, {"state": "stopping"})
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
                    return
                elif self.command == "POST" and uri.path == "/v1/call":
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= 64_000 or self.headers.get("Transfer-Encoding"):
                        raise APIError("JSON body must be 1–64000 bytes.")
                    if self.headers.get_content_type() != "application/json":
                        raise APIError("Content-Type must be application/json.")
                    payload = json.loads(self.rfile.read(length))
                    if not isinstance(payload, dict) or set(payload) - {"capability", "arguments", "idempotency_key"} or not isinstance(payload.get("capability"), str):
                        raise APIError("Expected capability, arguments and optional idempotency_key.")
                    data = app.call(payload["capability"], payload.get("arguments"), payload.get("idempotency_key"))
                else:
                    raise APIError("Route not found.", "not_found", 404)
                self.reply(200, data)
            except APIError as exc:
                self.reply(exc.status, guided({"error": exc.code, "message": str(exc)}))
            except (ValueError, TypeError, OSError) as exc:
                self.reply(400, guided({"error": "invalid_request", "message": str(exc)}))
            except Exception as exc:
                print(f"DumbAPI HTTP: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
                self.reply(500, guided({"error": "internal_error", "message": "Internal error; see server log."}))

        do_GET = handle_api
        do_POST = handle_api

    http = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    http.daemon_threads = True
    return http
