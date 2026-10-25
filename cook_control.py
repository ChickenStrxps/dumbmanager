"""Transient open-popup target for the global cook key. Handoffs belong to DumbAPI."""
import threading
import time
import hashlib

from dumbapi_core.common import APIError, json_text
from dumbapi_core.registry import validate
from dumbapi_core.t3 import T3
from dumbapi_core.t3_distributions import active, check_target, connection_lock, request_target, value_target


class Cook:
    def __init__(self, backend):
        self.backend, self.lock = backend, threading.Lock()
        self.target, self.active, self.states = None, None, {}
        self.evidence = None

    def control(self, value):
        action, owner = value.get("action", "status"), value.get("owner", "")
        if action == 'focus':
            if not isinstance(owner, str) or not 1 <= len(owner) <= 100:
                raise APIError('Open an itch popup first.')
            row = self.backend.call('manager.get', {'id':value.get('id','')})
            with self.lock:
                if self.evidence and self.evidence['owner'] != owner and self.evidence['expires'] >= time.monotonic() and not value.get('activate'):
                    return {'ready':False}
                self.evidence = {'id':row['id'], 'title':row['title'], 'owner':owner, 'expires':time.monotonic()+180}
            return {'ready':True, 'id':row['id']}
        if action == 'unfocus':
            with self.lock:
                if self.evidence and self.evidence['owner'] == owner: self.evidence = None
            return {'cleared':True}
        if action == 'evidence_target':
            with self.lock:
                target = self.evidence
                return {k:target[k] for k in ('id','title')} if target and target['expires'] >= time.monotonic() else {}
        if action == "prepare":
            if not isinstance(owner, str) or not 1 <= len(owner) <= 100:
                raise APIError("Open the itch popup first.")
            connection = active(self.backend.config)
            with request_target(value.get('t3_target')):
                check_target(connection)
            expected_target = value_target(connection)
            args = validate(self.backend.capabilities["manager.send"]["input_schema"], value.get("args", {}))
            T3.thread_id(args["thread_id"])
            if not args["request_key"] or len(args["request_key"]) > 100 or args["video_mode"] not in ("original", "frameboard"):
                raise APIError("Invalid handoff draft.")
            row = self.backend.call("manager.get", {"id": args["id"]})
            with self.lock:
                if self.target and self.target["owner"] != owner and self.target["expires"] >= time.monotonic() and not value.get("activate"):
                    return {"ready": False, "note": "Another itch popup was selected more recently."}
                previous = self.states.get(args["request_key"])
                if previous and previous["digest"] != hashlib.sha256(json_text(args).encode()).hexdigest():
                    raise APIError("That send key belongs to a different handoff.", "conflict", 409)
                if previous and previous.get('target', expected_target) != expected_target:
                    raise APIError("That handoff belongs to the other T3 installation. Switch back to retry it.", "t3_target_changed", 409)
                self.target = {"owner": owner, "args": args, "expires": time.monotonic()+180, "title": row["title"], "target": expected_target}
            return {"ready": True, "id": args["id"], "request_key": args["request_key"]}
        if action == "clear":
            with self.lock:
                if self.target and self.target["owner"] == owner:
                    self.target = None
            return {"cleared": True}
        if action == "status":
            with self.lock:
                return dict(self.states.get(value.get("request_key"), {"busy": False}))
        if action != "send":
            raise APIError("Unknown cook action.")
        with self.lock:
            target = self.target
            if not target or target["expires"] < time.monotonic():
                raise APIError("Open an itch popup and choose its T3 thread first.", "no_target", 409)
            expected_target = target['target']
            with request_target(expected_target):
                check_target(active(self.backend.config))
            args, key = dict(target["args"]), target["args"]["request_key"]
            if owner and (owner != target["owner"] or value.get("request_key") != key):
                raise APIError("The open itch changed. Retry from its popup.", "conflict", 409)
            previous = self.states.get(key)
            if previous and (previous.get("busy") or previous.get("result")):
                return dict(previous)
            if self.active:
                raise APIError("An itch is already cooking. Let that handoff finish first.", "busy", 409)
            state = {"id": args["id"], "request_key": key, "busy": True, "digest": hashlib.sha256(json_text(args).encode()).hexdigest(), "target": expected_target}
            self.states[key] = state
            self.active = key
            while len(self.states) > 20:
                del self.states[next(iter(self.states))]
        def work():
            try:
                with connection_lock(self.backend.config), request_target(expected_target):
                    check_target(active(self.backend.config))
                    result = self.backend.call("manager.send", args)
                update = {"busy": False, "result": result}
            except Exception as exc:
                update = {"busy": False, "error": str(exc), "code": getattr(exc, "code", "unavailable")}
            with self.lock:
                state.update(update)
                self.active = None
        threading.Thread(target=work, daemon=True).start()
        return {"id": args["id"], "request_key": key, "busy": True}
