"""DumbManager's local domain backend. Shared by CLI/MCP and the thin desktop UI."""
import hashlib
import json
import os
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .common import APIError, json_text, now


def text(value, limit=2000):
    if not isinstance(value, str) or len(value) > limit:
        raise APIError(f"Expected text of at most {limit} characters.")
    return value.strip()


def unpack(value, expected, default):
    if value in (None, ""):
        return default
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError as exc:
            raise APIError("Expected JSON data.") from exc
    if not isinstance(value, expected):
        raise APIError(f"Expected {expected.__name__}.")
    return value


class Manager:
    def __init__(self, config):
        self.config = config
        default = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local/share"))
        self.data = Path(os.environ.get("DUMBMANAGER_DATA_DIR") or
                         (default / "DumbManagerCommunity" if config.data == default / "DumbAPICommunity" else config.data / "manager"))
        self.data.mkdir(parents=True, exist_ok=True)
        self.path = self.data / "manager.sqlite"
        with self.db() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS records(id TEXT PRIMARY KEY,kind TEXT NOT NULL,project TEXT NOT NULL,updated TEXT NOT NULL,data TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS records_kind ON records(kind,updated);
                CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS requests(key TEXT PRIMARY KEY,fingerprint TEXT NOT NULL,result TEXT NOT NULL);
            """)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=8)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def get(self, db, id, kind=None):
        row = db.execute("SELECT kind,data FROM records WHERE id=?", (id,)).fetchone()
        if not row or (kind and row["kind"] != kind):
            raise APIError("Item not found.", "not_found", 404)
        return json.loads(row["data"])

    def put(self, db, kind, record):
        db.execute("INSERT OR REPLACE INTO records VALUES (?,?,?,?,?)",
                   (record["id"], kind, record.get("project", "unsorted"), record["updated_at"], json_text(record)))
        return record

    def records(self, db, kind, limit=500):
        return [json.loads(r[0]) for r in db.execute(
            "SELECT data FROM records WHERE kind=? ORDER BY updated DESC LIMIT ?", (kind, limit))]

    def setting(self, db, key, fallback=None):
        key = self.setting_key(key)
        row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else fallback

    def set_setting(self, db, key, value):
        key = self.setting_key(key)
        db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, json_text(value)))

    def setting_key(self, key):
        if key in {"active_context", "scout_thread", "research-thread"}:
            from .t3_distributions import active, check_target, distribution
            connection = active(self.config)
            check_target(connection)
            selected = distribution(connection)
            if selected != "t3":
                return key + ":" + selected
        return key

    def call(self, name, args):
        actions = {"capture", "attach", "update", "context.publish", "context.select", "settings", "complete", "repeat", "merge", "propose", "review", "scout.remember", "learning.record", "learning.progress", "research.prepare", "research.record", "research.adopt"}
        operation = name.removeprefix("manager.")
        with self.db() as db:
            if operation in actions:
                db.execute("BEGIN IMMEDIATE")
            key = args.get("request_key", "")
            fingerprint = hashlib.sha256(json_text({"name": name, "args": args}).encode()).hexdigest()
            if key:
                old = db.execute("SELECT fingerprint,result FROM requests WHERE key=?", (key,)).fetchone()
                if old:
                    if old[0] != fingerprint:
                        raise APIError("Request key already used for different input.", "conflict", 409)
                    return json.loads(old[1])
            handler = getattr(self, "op_" + operation.replace(".", "_"), None)
            if handler is None:
                raise APIError("Unknown manager operation.")
            result = handler(db, **{k: v for k, v in args.items() if k != "request_key"})
            if key:
                db.execute("INSERT INTO requests VALUES (?,?,?)", (key, fingerprint, json_text(result)))
            return result

    def op_status(self, db):
        return {"name": "DumbManager", "version": "0.1.0", "backend": "DumbAPI", "data_dir": str(self.data),
                "counts": {k: db.execute("SELECT count(*) FROM records WHERE kind=?", (k,)).fetchone()[0]
                           for k in ("itch", "context")}, "time": now()}

    def op_state(self, db):
        from .typing_words import COMMON
        from .typing_generator import status as typing_status
        from .manager_posts import cached
        itches = self.records(db, 'itch')
        for itch in itches:
            itch['posting'] = cached(db,itch['id'])
        return {"itches": itches, "contexts": self.records(db, "context", 80),
                "active_context": self.setting(db, "active_context"),
                "preferences": self.setting(db, "preferences", {"motion": True}), "backend": "DumbAPI", "typing_words": COMMON, "typing_generator":typing_status(self.config),
                "coverage": "Most recent 500 itches and 80 contexts; use manager.list/export for older records."}

    def op_list(self, db, project="", state="", query="", limit=50, offset=0):
        rows = [r for r in self.records(db, "itch", 2000)
                if (not project or r["project"] == project) and (not state or r["state"] == state)
                and all(w in json_text(r).casefold() for w in query.casefold().split())]
        return {"items": rows[offset:offset + limit], "total": len(rows), "limit": limit,
                "next_offset": offset + limit if offset + limit < len(rows) else None}

    def op_get(self, db, id):
        return self.get(db, id)

    def op_research_get(self, db, **args):
        from .manager_research import get
        return get(self, db, **args)

    def op_research_prepare(self, db, **args):
        from .manager_research import prepare
        return prepare(self, db, **args)

    def op_research_record(self, db, **args):
        from .manager_research import record
        return record(self, db, **args)

    def op_research_adopt(self, db, **args):
        from .manager_research import adopt
        return adopt(self, db, **args)

    def op_learning_get(self, db, **args):
        from .manager_learning import get
        return get(self, db, **args)

    def op_learning_record(self, db, **args):
        from .manager_learning import record
        return record(self, db, **args)

    def op_learning_progress(self, db, **args):
        from .manager_learning import progress
        return progress(self, db, **args)

    def op_capture(self, db, title="", project="", context_id="", original="", moment=False, event_at="", use_active=True, context_snapshot="", attachments="[]"):
        title, original = text(title, 500), text(original)
        context_id = context_id or (self.setting(db, "active_context", "") if use_active else "")
        context = self.get(db, context_id, "context") if context_id else None
        snapshot = unpack(context_snapshot, dict, {})
        snapshot.pop("agent_guidance", None)
        if snapshot:
            if not context or snapshot.get("id") != context["id"] or snapshot.get("project") != context["project"] or snapshot.get("thread_id") != context["thread_id"]:
                raise APIError("The saved context snapshot does not match its project/thread.")
            if set(snapshot) - set(context) or len(json_text(snapshot)) > 22000:
                raise APIError("Unsupported or oversized context snapshot.")
            for key in ("task", "testing", "entities", "workspace", "updated_at", "source"):
                text(snapshot.get(key, ""))
            if not isinstance(snapshot.get("version"), int) or not 1 <= snapshot["version"] <= context["version"]:
                raise APIError("Invalid context snapshot version.")
            candidates = snapshot.get("candidates", [])
            if not isinstance(candidates, list) or len(candidates) > 32:
                raise APIError("Invalid snapshot candidates.")
            for candidate in candidates:
                text(candidate, 240)
            context = snapshot
        project = text(project or (context or {}).get("project", "unsorted"), 100)
        if context and context["project"] != project:
            raise APIError("The context belongs to a different project. Select the correct context.")
        from .manager_media import Media
        media = Media(self).references(db, unpack(attachments, list, []))
        if not title and not moment and not media:
            raise APIError("Type an itch or mark a moment.")
        stamp = now()
        if event_at:
            try:
                datetime.fromisoformat(event_at.replace("Z", "+00:00"))
            except ValueError as exc:
                raise APIError("Invalid event timestamp.") from exc
        record = {"id": uuid.uuid4().hex, "project": project, "title": title or ("Evidence: " + media[0]["name"] if media else "That moment…"),
                  "attachments": media,
                  "key": re.sub(r"[^a-z0-9]+", ".", title.lower()).strip(".")[:100] or "moment",
                  "state": "needs_description" if not title else "open", "version": 1,
                  "original": original or title, "context_id": context_id, "context": context,
                  "created_at": stamp, "updated_at": stamp, "event_at": event_at or stamp,
                  "occurrences": [{"at": event_at or stamp, "note": original or title}],
                  "plan": [], "outcomes": [], "feedback": [], "evidence": [], "run_state": "not_sent",
                  "next_step": "", "desired_outcome": "", "test_url": "", "recheck": None}
        return self.put(db, "itch", record)

    def op_attach(self, db, id, attachments="[]"):
        """Append uploaded receipts atomically, preserving concurrent edits."""
        from .manager_media import Media
        row = self.get(db, id, "itch")
        added = unpack(attachments, list, [])
        if not isinstance(added, list) or any(not isinstance(a, str) for a in added):
            raise APIError("Use uploaded evidence IDs.")
        ids = list(dict.fromkeys([a['id'] for a in row.get('attachments', [])] + added))
        files = Media(self).references(db, ids)
        if files != row.get('attachments', []):
            row.update(attachments=files, updated_at=now(), version=row['version'] + 1)
            self.put(db, 'itch', row)
        return row

    def op_update(self, db, id, changes="{}", expected_version=0):
        row = self.get(db, id, "itch")
        if expected_version and row["version"] != expected_version:
            raise APIError("This itch changed. Reload it before saving.", "conflict", 409)
        changes = unpack(changes, dict, {})
        allowed = {"title", "desired_outcome", "next_step", "test_url", "state", "plan", "feedback", "recheck", "run_state", "evidence"}
        if set(changes) - allowed:
            raise APIError("Unsupported itch changes: " + ", ".join(sorted(set(changes) - allowed)))
        for key, value in changes.items():
            if key in {"title", "desired_outcome", "next_step", "test_url", "state", "run_state"}:
                value = text(value, 2000)
            if key == "title" and not value:
                raise APIError("An itch needs a description.")
            if key == "state" and value not in {"open", "needs_description", "working", "ready", "archived"}:
                raise APIError("Use manager.complete for accepted outcomes.")
            if key == "run_state" and value not in {"not_sent", "brief_ready", "agent_reported_running", "agent_reported_done", "failed"}:
                raise APIError("Invalid run state.")
            if key == "test_url" and value and not value.startswith(("http://", "https://", "t3-thread://v1/")):
                raise APIError("Use an HTTP(S) test URL or exact T3 thread link.")
            if key == "plan":
                if not isinstance(value, list) or len(value) > 30:
                    raise APIError("Use at most 30 meaningful plan steps.")
                clean = []
                for task in value:
                    if not isinstance(task, dict):
                        raise APIError("Each plan step needs text and an optional stable id.")
                    clean.append({"id": text(task.get("id", ""), 100) or uuid.uuid4().hex[:12],
                                  "text": text(task.get("text", ""), 1000), "done": bool(task.get("done", False))})
                value = clean
            if key in {"feedback", "evidence"} and (not isinstance(value, list) or len(value) > 80 or len(json_text(value)) > 15000):
                raise APIError("Evidence/feedback must be a bounded list.")
            if key == "recheck" and value is not None:
                if not isinstance(value, dict) or value.get("status") not in {"still_relevant", "already_addressed", "conditions_changed", "related", "cannot_verify"}:
                    raise APIError("A recheck needs an explicit supported status.")
                if len(json_text(value)) > 12000:
                    raise APIError("Recheck is too large.")
            row[key] = value
        if changes.get("title") and row["state"] == "needs_description":
            row["state"] = "open"
        row["version"] += 1
        row["updated_at"] = now()
        return self.put(db, "itch", row)

    def op_repeat(self, db, id, note=""):
        row = self.get(db, id, "itch")
        if len(row["occurrences"]) >= 500:
            raise APIError("This itch has reached its occurrence limit; archive/export it.")
        cid = self.setting(db, "active_context", "")
        ctx = self.get(db, cid, "context") if cid else None
        row["occurrences"].append({"at": now(), "note": text(note), "context": ctx if ctx and ctx["project"] == row["project"] else None})
        row["state"] = "open"
        row["recheck"] = None
        row["run_state"] = "not_sent"
        row["plan"] = [{**task, "done": False} for task in row["plan"]]
        row["version"] += 1
        row["updated_at"] = now()
        return self.put(db, "itch", row)

    def op_complete(self, db, id, summary, evidence="", accepted=False, resolved_elsewhere=False):
        if not accepted:
            raise APIError("User acceptance is required; otherwise report ready for review with manager.update.")
        if not text(summary):
            raise APIError("Describe the accepted outcome.")
        row = self.get(db, id, "itch")
        if row["state"] == "needs_description":
            raise APIError("Describe this moment before accepting an outcome.")
        if row["state"] == "resolved":
            return row
        row["outcomes"].append({"at": now(), "summary": text(summary), "evidence": text(evidence),
                                "acceptance": "user_confirmed", "resolved_elsewhere": resolved_elsewhere})
        row.update(state="resolved", updated_at=now(), version=row["version"] + 1)
        return self.put(db, "itch", row)

    def op_context_publish(self, db, project, thread_id, task, testing="", entities="", candidates="[]", workspace="", select=False, source="agent_published"):
        project, thread_id = text(project, 100), text(thread_id, 120).removeprefix("t3-thread://v1/")
        if not project or not thread_id or not task.strip():
            raise APIError("Project, thread_id and task are required.")
        cid = hashlib.sha256((project + ":" + thread_id).encode()).hexdigest()[:24]
        try:
            previous = self.get(db, cid, "context")
        except APIError:
            previous = {}
        suggestions = unpack(candidates, list, [])
        if len(suggestions) > 32:
            raise APIError("Use at most 32 prepared completions.")
        suggestions = [text(x, 240) for x in suggestions if isinstance(x, str) and x.strip()]
        row = {"id": cid, "project": project, "thread_id": thread_id, "task": text(task), "testing": text(testing),
               "entities": text(entities), "candidates": suggestions, "workspace": text(workspace),
               "version": previous.get("version", 0) + 1, "updated_at": now(), "source": source}
        self.put(db, "context", row)
        if select:
            self.set_setting(db, "active_context", cid)
        return row

    def op_context_select(self, db, id=""):
        if id:
            self.get(db, id, "context")
        self.set_setting(db, "active_context", id)
        return {"active_context": id}

    def op_context(self, db, id=""):
        id = id or self.setting(db, "active_context", "")
        return self.get(db, id, "context") if id else {"state": "unlinked", "contexts": self.records(db, "context", 80)}

    def op_settings(self, db, motion=True):
        self.set_setting(db, "preferences", {"motion": motion})
        return {"motion": motion}

    def op_brief(self, db, id, direction=""):
        row = self.get(db, id, "itch")
        context = row.get("context") or {}
        blocks = [f"DumbManager itch {id}", f"Project: {row['project']}", f"Observation: {row['title']}",
                  f"Desired outcome: {row['desired_outcome'] or 'Confirm from the observed problem; do not assume the original proposed fix.'}",
                  f"Task when observed: {context.get('task', 'Unknown')}", f"Testing: {context.get('testing', 'Unknown')}",
                  f"Workspace: {context.get('workspace', 'Choose the correct workspace before edits.')}"]
        if direction:
            blocks += [f"Requested feel adjustment: {text(direction)}"]
        if row.get("attachments"):
            blocks += ["Local image/video evidence: " + json_text(row["attachments"]) +
                       "\nOpen this itch in DumbManager to inspect it. These local files are not automatically sent to T3."]
        if row["feedback"]:
            blocks += ["Previous feedback: " + json_text(row["feedback"][-5:])]
        blocks += ["Recheck current conditions before edits; report still_relevant / already_addressed / conditions_changed / related / cannot_verify with evidence.",
                   "Use DumbAPI manager.get/update on this stable itch ID. For 1 action use a sentence; 2–3 use a short sequence; 4+ use a checklist with stable task IDs.",
                   "For finished work, preserve useful learning history in evidence: actual workspace, environment, commands (an array of exact strings actually used), checks and tools. Do not invent missing history. Optional short lessons and package tips can be saved with manager.learning.get/record, citing this itch's source IDs and exact quotes. Learning never accepts the itch.",
                   "Report ready for review with evidence. Only explicit user acceptance resolves an itch. Do not publish or deploy as a side effect."]
        from .manager_research import brief_context
        research = brief_context(self, db, id)
        if research: blocks += [research]
        thread = context.get("thread_id")
        return {"id": id, "brief": "\n\n".join(blocks), "thread_url": "t3-thread://v1/" + thread if thread else None,
                "handoff": "copy_brief", "note": "External desktop-to-T3 sending is not available in this process."}

    # ---------- Typing model setup and intake helpers ----------
    def op_typing_status(self, db):
        from .typing_generator import status
        return status(self.config)

    def op_typing_configure(self, db, enabled=True, api_key='', forget=False):
        from .typing_generator import configure
        return configure(self.config, enabled, api_key, forget)

    def op_suggest(self, db, text="", project="", context_id="", jev=True, mode="itch", thread_id="", candidates="[]", surface="", fresh=False):
        from .manager_ai import suggest
        clean_text(text, 500)
        typed = text
        supplied = unpack(candidates, list, [])
        if len(supplied) > 32 or any(not isinstance(c, str) or len(c) > 240 for c in supplied):
            raise APIError("Use up to 32 short completion candidates.")
        context_id = context_id or (self.setting(db, "active_context", "") if not project and mode != "chat" else "")
        try:
            context = self.get(db, context_id, "context") if context_id else {}
        except APIError:
            context = {}
        if mode == "chat":
            context = next((c for c in self.records(db, "context", 80) if c["thread_id"] == thread_id), {}) if thread_id else {}
        elif project and project != context.get("project", project):
            context = {}
        project = project or context.get("project", "")
        titles = [r["title"] for r in self.records(db, "itch", 300)
                  if r["state"] not in {"suggested", "declined", "archived"} and (not project or r["project"] == project)]
        pool = supplied if mode == "chat" and thread_id else [] if mode == "chat" else list(context.get("candidates", [])) + titles
        scope = {k: context.get(k, "") for k in ("project", "task", "testing", "entities")}
        scope['project'] = context.get('project') or project
        if surface:scope['surface']=clean_text(surface,1800)
        from .typing_context import recent
        exact_thread = thread_id if mode == "chat" else context.get("thread_id", "")
        activity = recent(self.config, exact_thread) if exact_thread and len(typed.strip()) >= 4 else {"source": "published", "messages": []}
        if activity.get("messages"):
            scope["recent"] = activity["messages"]
        result = suggest(self.config, typed, pool, jev, scope, mode,
                          {'thread':exact_thread,'context':context.get('id',''),'revision':context.get('updated_at','')},fresh=fresh)
        result["context"] = {"thread_id": exact_thread, "source": activity["source"], "at": activity.get("at")}
        return result

    def op_split(self, db, text="", jev=True):
        from .manager_ai import split
        return split(self.config, text, jev)

    def op_duplicates(self, db, project="", id="", jev=True):
        from .manager_ai import duplicates
        rows = [r for r in self.records(db, "itch", 500) if not project or r["project"] == project]
        if id:
            self.get(db, id, "itch")
        return duplicates(self.config, rows, id, jev)

    def op_merge(self, db, id, into):
        if id == into:
            raise APIError("Pick two different itches to merge.")
        drop, keep = self.get(db, id, "itch"), self.get(db, into, "itch")
        if drop["project"] != keep["project"]:
            raise APIError("Only merge itches from the same project.")
        if drop["state"] in {"resolved", "archived", "suggested", "declined"} or keep["state"] in {"archived", "suggested", "declined"}:
            raise APIError("Only merge open itches.")
        if len(keep["occurrences"]) + len(drop["occurrences"]) > 500:
            raise APIError("Too many occurrences to merge; archive/export first.")
        stamp = now()
        keep["occurrences"] = sorted(keep["occurrences"] + [{**o, "merged_from": drop["id"]} for o in drop["occurrences"]], key=lambda o: o.get("at", ""))
        known = {a.get("id") for a in keep.get("attachments", [])}
        keep["attachments"] = keep.get("attachments", []) + [a for a in drop.get("attachments", []) if a.get("id") not in known]
        keep["feedback"] = (keep["feedback"] + drop["feedback"])[-80:]
        keep["merged"] = (keep.get("merged", []) + [{"id": drop["id"], "title": drop["title"], "at": stamp}])[-80:]
        if keep["state"] == "resolved":
            keep["state"] = "open"
        keep.update(version=keep["version"] + 1, updated_at=stamp)
        drop.update(state="archived", merged_into=keep["id"], version=drop["version"] + 1, updated_at=stamp)
        self.put(db, "itch", drop)
        return {"kept": self.put(db, "itch", keep), "archived": drop}

    # ---------- scout suggestions (separate inbox; never in the main pile until approved) ----------
    def op_propose(self, db, title, project, where, kind="improvement", steps="", saw="", by="scout"):
        from .manager_ai import similarity
        title, project = text(title, 240), text(project, 100)
        if not title or not project:
            raise APIError("A suggestion needs a title and project.")
        if kind not in {"bug", "improvement", "idea"}:
            raise APIError("Kind is bug, improvement or idea.")
        where, steps, saw, by = text(where, 500), text(steps, 2000), text(saw, 2000), text(by, 60)
        if not where:
            raise APIError("Say where you found it (feature, capability or file).")
        key = re.sub(r"[^a-z0-9]+", ".", title.lower()).strip(".")[:100]
        rows = self.records(db, "itch", 2000)
        for row in rows:
            if row["project"] == project and (row["key"] == key or similarity(row["title"], title) >= 0.8):
                return {"duplicate": True, "item": row}
        if sum(r["state"] == "suggested" for r in rows) >= 25:
            raise APIError("The suggestion inbox is full. Wait for the user to review it.", "inbox_full", 409)
        stamp = now()
        if sum(r.get("scout", {}).get("at", "").startswith(stamp[:10]) for r in rows) >= 3:
            raise APIError("Today's three scout suggestions are in. Try tomorrow.", "daily_limit", 409)
        record = {"id": uuid.uuid4().hex, "project": project, "title": title, "attachments": [], "key": key,
                  "state": "suggested", "version": 1, "original": title, "context_id": "", "context": None,
                  "created_at": stamp, "updated_at": stamp, "event_at": stamp,
                  "occurrences": [{"at": stamp, "note": saw or title}], "plan": [], "outcomes": [], "feedback": [],
                  "evidence": [], "run_state": "not_sent", "next_step": "", "desired_outcome": "", "test_url": "", "recheck": None,
                  "scout": {"kind": kind, "where": where, "steps": steps, "saw": saw, "by": by, "at": stamp}}
        return {"duplicate": False, "item": self.put(db, "itch", record)}

    def op_review(self, db, id, decision, reason="", title=""):
        row = self.get(db, id, "itch")
        if row["state"] != "suggested":
            raise APIError("This suggestion was already reviewed.", "conflict", 409)
        if decision not in {"approve", "decline", "edit"}:
            raise APIError("Decision is approve, decline or edit.")
        if title:
            row["title"] = text(title, 500)
            row["original"] = row["title"]
            row["key"] = re.sub(r"[^a-z0-9]+", ".", row["title"].lower()).strip(".")[:100]
        if decision == "edit":
            row["scout"] = {**row.get("scout", {}), "edited_at": now()}
        else:
            row["state"] = "open" if decision == "approve" else "declined"
            row["scout"] = {**row.get("scout", {}), "decision": decision, "reason": text(reason, 500), "reviewed_at": now()}
        row.update(version=row["version"] + 1, updated_at=now())
        return self.put(db, "itch", row)

    def op_scout_remember(self, db, thread_id):
        """Remember an explicitly used scout destination. Never sends or selects chat."""
        from .t3 import T3
        thread_id = T3.thread_id(thread_id)
        self.set_setting(db, "scout_thread", thread_id)
        return {"thread_id": thread_id}

    def op_scout_plan(self, db, seed="", project=""):
        """Prepare a chosen (or random) project for a read-only scout. Runs nothing."""
        import random
        from .registry import definitions as all_definitions
        caps = scout_capabilities(all_definitions())
        roots = self.config.roots()
        if not roots:
            raise APIError("No connected projects are available to scout.", "not_found", 404)
        if project and project not in roots:
            raise APIError("Choose a connected project to scout.", "not_found", 404)
        pick = project or random.Random(seed or None).choice(sorted(roots))
        rows = self.records(db, "itch", 2000)
        # every project can be read through source.read / git.*; some also have their own read capabilities
        shared = {"projects.list", "source.read", "git.status", "git.diff", "git.history", "manager.list", "manager.get"}
        from .manager_scout import prepare
        return prepare(self.config, {"project": pick, "folder": roots[pick][0],
                "scout_thread_id": self.setting(db, "scout_thread", ""),
                "projects": [{"id": key, "folder": roots[key][0]} for key in sorted(roots)],
                "capabilities": [{"id": c["id"], "description": c["description"]} for k, c in caps.items() if c["project"] == pick or k in shared],
                "search_hint": f"python dumbapi.py search \"<words>\" --project {pick} --kind file  (read-only)",
                "known_itches": [{"title": r["title"], "state": r["state"]} for r in rows if r["project"] == pick][:40],
                "pending_suggestions": sum(r["state"] == "suggested" for r in rows),
                "daily_remaining": max(0, 3-sum(r.get("scout", {}).get("at", "").startswith(now()[:10]) for r in rows)),
                "rules": SCOUT_RULES})

    def op_export(self, db):
        rows = db.execute("SELECT kind,data FROM records ORDER BY updated").fetchall()
        return {"schema": 1, "exported_at": now(), "records": [{"kind": r[0], "record": json.loads(r[1])} for r in rows],
                "note": "Export contains media references, not bytes. Back up the local itch-media folder alongside this JSON; replay media has separate retention."}


clean_text = text
SCOUT_BLOCKED = {"catalog.refresh", "manager.state", "manager.export", "manager.brief", "manager.suggest", "manager.split", "manager.duplicates"}
from .manager_scout import SCOUT_RULES


def scout_capabilities(caps):
    return {k: c for k, c in caps.items() if c["mode"] == "read" and k not in SCOUT_BLOCKED and not k.startswith(("browser.", "t3."))}


def definitions():
    from .registry import boolean, capability, integer, string
    def cap(action, description, props=None, required=(), write=False):
        item = capability("manager." + action, "dumbmanager", description, props, required, tags=("itches", "context", "workflow"))
        if write:
            item["mode"] = "action"
            item["input_schema"]["properties"]["request_key"] = string("Optional retry key; reuse with identical arguments only.")
        return item
    return [
        cap("status", "Read DumbManager backend availability and counts."),
        cap("typing_status", "Read the fresh typing idea model configuration without key material."),
        cap("typing_configure", "Configure Mercury 3 context-driven typing ideas and Windows-encrypted Inception key storage.",
            {"enabled":boolean(True),"api_key":string("Inception key; blank keeps the saved key.",default="",maxLength=500),"forget":boolean()},write=True),
        cap("state", "Bounded UI state: recent itches, published contexts and explicit context selection."),
        cap("list", "Search saved frustrations without running an agent.", {"project": string(default=""), "state": string(default=""), "query": string(default=""), "limit": integer(50, 1, 100), "offset": integer(0, 0, 2000)}),
        cap("get", "Read one itch and its preserved context, fix plan, evidence and outcomes.", {"id": string()}, ("id",)),
        cap("attach", "Append local uploaded evidence to an existing itch without replacing its other receipts or edits.", {"id": string(), "attachments": string("JSON array of uploaded evidence IDs; up to eight per itch.", default="[]", maxLength=1000)}, ("id",), write=True),
        cap("send", "Explicitly send an itch and its uploaded image/video evidence to an exact T3 thread. Retries reuse media and message IDs; queues after active work.", {"id": string(), "thread_id": string(), "message": string("Optional reviewed message; empty uses the itch's recheck/fix brief.", default="", maxLength=12000), "video_mode": string("frameboard (default) or original; native video depends on the provider.", default="frameboard"), "followup": string("Optional requested revision: saves feedback once, reopens the same itch and includes the note in this handoff.",default="",maxLength=2000)}, ("id", "thread_id", "request_key"), write=True),
        cap("capture", "Save a frustration or unfinished moment locally; never runs code.", {"title": string(default=""), "project": string(default=""), "context_id": string(default=""), "original": string(default=""), "moment": boolean(), "event_at": string(default=""), "use_active": boolean(True), "attachments": string("JSON array of up to eight locally uploaded evidence IDs.", default="[]", maxLength=1000), "context_snapshot": string("Optional JSON snapshot returned by manager.context/state at observation time, preserved across offline retries.", default="", maxLength=22000)}, write=True),
        cap("update", "Update an itch using bounded JSON changes. Agent completion remains reviewable, not accepted.", {"id": string(), "changes": string("JSON object: title, desired_outcome, next_step, test_url, state, plan, feedback, recheck, run_state, evidence.", default="{}", maxLength=24000), "expected_version": integer(0, 0, 1000000)}, ("id",), write=True),
        cap("repeat", "Save another occurrence and reopen the itch while retaining earlier outcomes.", {"id": string(), "note": string(default="")}, ("id",), write=True),
        cap("complete", "Accept an outcome only after explicit user confirmation, never from agent-turn completion.", {"id": string(), "summary": string(), "evidence": string(default=""), "accepted": boolean(), "resolved_elsewhere": boolean()}, ("id", "summary"), write=True),
        cap("context.publish", "Publish a compact current task/test context. Publishing does not imply the thread is active; select=true only for an explicit user selection.", {"project": string(), "thread_id": string(), "task": string(), "testing": string(default=""), "entities": string(default=""), "candidates": string("JSON array of up to 32 plausible sentence completions.", default="[]", maxLength=10000), "workspace": string(default=""), "select": boolean(), "source": string(default="agent_published", enum=["agent_published", "user_entered"])}, ("project", "thread_id", "task"), write=True),
        cap("context.select", "Explicitly choose which published thread/context capture uses.", {"id": string(default="")}, write=True),
        cap("context", "Read the active or named context; no full chat polling.", {"id": string(default="")}),
        cap("settings", "Save local presentation preferences.", {"motion": boolean(True)}, write=True),
        cap("brief", "Prepare a scoped copyable T3 brief; does not send or start a thread.", {"id": string(), "direction": string(default="")}, ("id",)),
        cap("export", "Export manager records as JSON; never copies T3 chats or provider tokens."),
        cap("suggest", "Complete typed requests, optionally grounded in exact-thread context; Mercury generates ideas and Jev ranks source matches. Never sends a message.", {"text": string(maxLength=500), "project": string(default=""), "context_id": string(default=""), "jev": boolean(True), "mode": string(default="itch", enum=["itch", "chat"]), "thread_id": string(default=""), "candidates": string(default="[]", maxLength=10000), "surface": string("Optional bounded current DumbManager UI labels; no typed fields or message bodies.",default="",maxLength=1800), "fresh": {**boolean(), "description":"Explicitly request different ideas; retains concurrency and provider cooldown limits."}}, ("text",)),
        cap("split", "Split a typed batch idea into separate itch titles (local cuts; Jev judges which belong together). Saves nothing.", {"text": string(maxLength=4000), "jev": boolean(True)}, ("text",)),
        cap("duplicates", "Find likely duplicate open itches (local near-matches confirmed by Jev). Saves nothing.", {"project": string(default=""), "id": string("Optional itch to check against the others.", default=""), "jev": boolean(True)}),
        cap("merge", "Merge a duplicate itch into another: occurrences, files and feedback move over; the duplicate is archived, never deleted.", {"id": string("Duplicate to archive."), "into": string("Itch to keep.")}, ("id", "into"), write=True),
        cap("propose", "Scout-only: suggest a bug/improvement/idea into the separate review inbox. Never enters the main pile until the user approves.", {"title": string(maxLength=240), "project": string(), "where": string("Where you found it: feature, capability or file.", maxLength=500), "kind": string(default="improvement", enum=["bug", "improvement", "idea"]), "steps": string(default="", maxLength=2000), "saw": string(default="", maxLength=2000), "by": string(default="scout")}, ("title", "project", "where"), write=True),
        cap("review", "User review of a suggestion: approve moves it to the pile, decline hides it, edit keeps the revised title pending.", {"id": string(), "decision": string(enum=["approve", "decline", "edit"]), "reason": string(default=""), "title": string("Optional edited title.", default="")}, ("id", "decision"), write=True),
        cap("scout.plan", "Prepare a chosen connected project (random if omitted) and its read-only capabilities for a short scout look-around. Returns project choices; runs nothing.", {"seed": string(default=""), "project": string(default="")}),
        cap("scout.remember", "Remember the user's exact scout destination across desktop and phone. Never sends a message or changes the active chat/context.", {"thread_id": string()}, ("thread_id",), write=True),
    ]
