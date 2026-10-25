"""Quiet local launcher; no installs, cloud service, or bundled browser runtime."""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get("DUMBMANAGER_DATA_DIR", Path(os.environ.get("LOCALAPPDATA", Path.home())) / "DumbManagerCommunity"))


def request(path="/health", value=None):
    headers = {}
    raw = None
    if value is not None:
        headers = {"Authorization": "Bearer " + (DATA / "desktop.token").read_text().strip(), "Content-Type": "application/json"}
        raw = json.dumps(value).encode()
    req = urllib.request.Request("http://127.0.0.1:8783" + path, data=raw, headers=headers)
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=3) as response:
        return json.load(response)


def start(native=True):
    frozen=getattr(sys,'frozen',False)
    child_env={**os.environ,**({'PYINSTALLER_RESET_ENVIRONMENT':'1'} if frozen else {})}
    child_cwd=Path(sys.executable).resolve().parent if frozen else ROOT
    try:
        health = request()
        if health.get("name") != "DumbManager":
            raise RuntimeError("Another service is using port 8783.")
    except urllib.error.URLError as exc:
        if not isinstance(exc.reason, ConnectionRefusedError):
            raise RuntimeError("Port 8783 is not responding as DumbManager.") from exc
        DATA.mkdir(parents=True, exist_ok=True)
        flags = {"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
        with (DATA / "server.log").open("ab") as log:
            process = subprocess.Popen(([sys.executable, "--host"] if getattr(sys, "frozen", False) else [sys.executable, str(ROOT / "app.py")]), cwd=child_cwd, env=child_env, stdin=subprocess.DEVNULL, stdout=log, stderr=log, **flags)
        for _ in range(60):
            if process.poll() is not None:
                raise RuntimeError("DumbManager failed to start. See " + str(DATA / "server.log"))
            try:
                health = request()
                break
            except urllib.error.URLError:
                time.sleep(.15)
        else:
            raise RuntimeError("DumbManager is taking too long to start.")
    if native and os.name == "nt":
        with (DATA / "native.log").open("ab") as log:
            subprocess.Popen(([sys.executable, "--native"] if getattr(sys, "frozen", False) else [sys.executable, str(ROOT / "native.py")]), cwd=child_cwd, env=child_env, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                             creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP)
    return health


def main():
    p = argparse.ArgumentParser()
    p.add_argument("action", nargs="?", choices=["start", "stop", "status"], default="start")
    p.add_argument("--no-open", action="store_true")
    p.add_argument("--no-native", action="store_true")
    args = p.parse_args()
    try:
        if args.action == "stop":
            print(request("/api/shutdown", {}))
        elif args.action == "status":
            print(request())
        else:
            start(not args.no_native)
            print("DumbManager: http://127.0.0.1:8783")
            if not args.no_open:
                webbrowser.open("http://127.0.0.1:8783")
    except (OSError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
