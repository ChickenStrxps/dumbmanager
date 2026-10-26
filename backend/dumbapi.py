"""DumbAPI: call known capabilities directly; discover schemas only as needed. Python standard library only."""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from dumbapi_core.app import App
from dumbapi_core.common import APIError, Config, ROOT, json_text, read_json
from dumbapi_core.guidance import LOOKUP_GUIDANCE, guided
from dumbapi_core.transports import mcp, server


def launch(config):
    url = f"http://127.0.0.1:{config.port}"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    expected = App(config).health()["instance"]

    def healthy():
        try:
            with opener.open(url + "/health", timeout=1) as response:
                return json.load(response).get("instance") == expected
        except (OSError, ValueError):
            return False

    if healthy():
        return {"url": url, "state": "already_running", "token_file": str(config.data / "http.token")}
    flags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    with (config.data / "server.log").open("a", encoding="utf-8") as log:
        process = subprocess.Popen([config.python, str(config.root / "dumbapi.py"), "--data-dir", str(config.data), "serve"],
                                   cwd=config.root, stdout=log, stderr=log, stdin=subprocess.DEVNULL,
                                   creationflags=flags, start_new_session=os.name != "nt")
    for _ in range(30):
        if healthy():
            return {"url": url, "state": "started", "pid": process.pid, "token_file": str(config.data / "http.token")}
        if process.poll() is not None:
            break
        time.sleep(0.15)
    raise APIError(f"HTTP server did not start; inspect {config.data / 'server.log'}.", "startup_failed", 503)


def main():
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__, epilog=LOOKUP_GUIDANCE)
    parser.add_argument("--data-dir", type=Path, help="Isolated local state directory (also DUMBAPI_DATA_DIR).")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("refresh", help="Refresh all project/source metadata.")
    commands.add_parser("projects", help="List projects and indexing coverage.")
    search = commands.add_parser("search")
    search.add_argument("query")
    search.add_argument("--project")
    search.add_argument("--kind", choices=["project", "capability", "file"])
    search.add_argument("--limit", type=int, default=8)
    search.add_argument("--offset", type=int, default=0)
    search.add_argument("--scout", action="store_true", help="Return bounded research guidance instead of simple-lookup guidance.")
    describe = commands.add_parser("describe")
    describe.add_argument("id")
    describe.add_argument("--scout", action="store_true", help="Return bounded research guidance for this read-only schema lookup.")
    call = commands.add_parser("call")
    call.add_argument("capability")
    source = call.add_mutually_exclusive_group()
    source.add_argument("--json", default=None, help="JSON object of capability arguments.")
    source.add_argument("--args-file", type=Path, help="UTF-8 JSON file; convenient for PowerShell.")
    source.add_argument("--arg", "-a", action="append", help="Repeat key=value arguments; booleans/numbers use JSON values.")
    call.add_argument("--idempotency-key")
    scout = commands.add_parser("scout", help="Read-only call for the DumbManager scout; only read capabilities and manager.propose.")
    scout.add_argument("capability")
    scout.add_argument("--json", default=None)
    scout.add_argument("--arg", "-a", action="append")
    job = commands.add_parser("job")
    job.add_argument("id", nargs="?")
    job.add_argument("--log-lines", type=int, default=20)
    job.add_argument("--cancel", action="store_true", help="Cancel this job only if it is still queued.")
    mcp_parser = commands.add_parser("mcp", help="Stdio MCP, four tools; no HTTP server needed.")
    mcp_parser.add_argument('--integration', help='Use an enabled, capability-scoped MCP integration (e.g. dots or mcp).')
    commands.add_parser("serve", help="Foreground loopback HTTP server.")
    commands.add_parser("start", help="Start or reuse HTTP server silently in background; opens no windows.")
    commands.add_parser("stop", help="Stop this instance's HTTP server; leaves jobs and other apps running.")
    commands.add_parser("worker", help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        config = Config(data=args.data_dir)
        app = App(config)
        if args.command == "mcp":
            if args.integration:
                from dumbapi_core.ai.service import ScopedApp
                if app.ai.adapter(args.integration).kind != 'mcp':
                    raise APIError('Choose an MCP integration profile.')
                app = ScopedApp(app.ai, args.integration)
            return mcp(app)
        if args.command == "serve":
            http = server(app)
            print(f"DumbAPI listening on http://127.0.0.1:{http.server_port}", file=sys.stderr, flush=True)
            try:
                return http.serve_forever()
            finally:
                http.server_close()
        if args.command == "worker":
            return app.jobs.run()
        if args.command == "start":
            result = launch(config)
        elif args.command == "stop":
            from client import DumbClient
            client = DumbClient(f"http://127.0.0.1:{config.port}", config.data / "http.token")
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(f"http://127.0.0.1:{config.port}/health", timeout=2) as response:
                if json.load(response).get("instance") != app.health()["instance"]:
                    raise APIError("Another instance owns this port; no action taken.", "conflict", 409)
            result = client.request("/v1/stop", {})
        elif args.command == "refresh":
            result = app.call("catalog.refresh")
        elif args.command == "projects":
            result = app.call("projects.list", {"limit": 50})
        elif args.command == "search":
            result = app.search(args.query, args.project, args.kind, args.limit, args.offset)
        elif args.command == "describe":
            result = app.describe(args.id)
        elif args.command in {"call", "scout"}:
            if args.command == "scout":
                from dumbapi_core.manager import scout_capabilities
                if args.capability != "manager.propose" and args.capability not in scout_capabilities(app.capabilities):
                    raise APIError("Scout mode is look-around only: that capability is not allowed.", "forbidden", 403)
                args.args_file = args.idempotency_key = None
            arguments = read_json(args.args_file) if args.args_file else json.loads(args.json or "{}")
            if args.arg:
                for item in args.arg:
                    key, separator, value = item.partition("=")
                    if not separator or not key:
                        raise APIError("--arg expects key=value.")
                    try:
                        value = json.loads(value)
                    except ValueError:
                        pass
                    arguments[key] = value
            result = app.call(args.capability, arguments, args.idempotency_key)
        else:
            from dumbapi_core.transports import job_view
            if args.cancel:
                if not args.id:
                    raise APIError("job --cancel requires an ID.")
                result = app.call("jobs.cancel", {"id": args.id})
            else:
                result = job_view(app, args.id, args.log_lines)
        if args.command == "scout" or getattr(args, "scout", False):
            from dumbapi_core.manager_scout import SCOUT_GUIDANCE
            result = guided(result, SCOUT_GUIDANCE)
        print(json_text(result))
    except (APIError, OSError, ValueError) as exc:
        guidance = LOOKUP_GUIDANCE
        if args.command == "scout" or getattr(args, "scout", False):
            from dumbapi_core.manager_scout import SCOUT_GUIDANCE
            guidance = SCOUT_GUIDANCE
        print(json_text(guided({"error": getattr(exc, "code", "invalid_request"), "message": str(exc)}, guidance)), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
