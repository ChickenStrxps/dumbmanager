"""Bounded local helper controls. Never accept executable paths or key scripts."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid
import threading
import re

ROOT = Path(__file__).resolve().parent
_start_lock = threading.Lock()


def write_json(path, value):
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        temporary.write_text(json.dumps(value), encoding="utf-8")
        for attempt in range(5):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(.015 * (attempt + 1))
    finally:
        temporary.unlink(missing_ok=True)


def status(data):
    try:
        value = json.loads((data / "native-status.json").read_text(encoding="utf-8"))
        live = value.get("version") == 2 and 0 <= time.time() - value.get("heartbeat", 0) < 12
        if live:
            return {**value, "running": True, "test_remaining": max(0, int(value.get("test_until", 0) - time.time() + 0.99))}
    except (OSError, ValueError, TypeError):
        pass
    return {"running": False, "bindings": {}, "shortcut_conflicts": [], "test_remaining": 0,
            "note": "Global shortcuts are off. Enable them below."}


def start(data):
    with _start_lock:
        return _start(data)


def _start(data):
    if os.name != "nt":
        raise RuntimeError("Global shortcuts need the Windows desktop app.")
    data.mkdir(parents=True, exist_ok=True)
    if status(data)["running"]:
        return status(data)
    # A stale heartbeat can belong to a healthy Tk process whose file write failed.
    # Ask that exact helper to publish before launching a second mutex owner.
    probe = uuid.uuid4().hex
    write_json(data / 'native-command.json', {'id': probe, 'action': 'ping', 'at': time.time()})
    for _ in range(6):
        result = status(data)
        if result['running']:
            return result
        time.sleep(.1)
    env = {**os.environ, "DUMBMANAGER_DATA_DIR": str(data)}
    with (data / "native.log").open("ab") as log:
        subprocess.Popen([sys.executable, str(ROOT / "native.py")], cwd=ROOT, env=env,
                         stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                         creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP)
    for _ in range(30):
        result = status(data)
        if result["running"]:
            return result
        time.sleep(.1)
    raise RuntimeError("Shortcuts could not connect. Check native.log in local DumbManager data.")


def control(data, action, itch_id=''):
    if action == "status":
        return status(data)
    if action not in {"start", "test", "capture", "moment", "snip"}:
        raise ValueError("Unknown shortcut action.")
    if itch_id and (action != 'snip' or not isinstance(itch_id, str) or not re.fullmatch(r'[a-f0-9]{32}', itch_id)):
        raise ValueError('Invalid itch target.')
    result = start(data)
    if action in {"test", "capture", "moment", "snip"}:
        id = uuid.uuid4().hex
        write_json(data / "native-command.json", {"id": id, "action": action, "itch_id": itch_id, "at": time.time()})
        for _ in range(20):
            result = status(data)
            if result.get("command_id") == id or (action == 'test' and result.get("test_id") == id):
                return result
            time.sleep(.1)
        raise RuntimeError("The helper did not acknowledge that action. Try again.")
    return result
