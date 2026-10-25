import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from dumbapi_core.app import App
from dumbapi_core.common import APIError, Config, atomic_json
from dumbapi_core.manager import Manager
from dumbapi_core.replay import OWNER, Replay


class ManagerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.hub = self.base / "DumbAPICommunity"
        self.hub.mkdir()
        self.app = App(Config(self.hub, self.base / "state"))
        self.manager = Manager(self.app.config)

    def tearDown(self):
        self.temp.cleanup()

    def context(self, **overrides):
        return self.app.call("manager.context.publish", {"project": "fish", "thread_id": "thread-a", "task": "Fish physics",
                    "testing": "Flop on land", "candidates": json.dumps(["Fish flop has no recovery"]), **overrides})

    def test_publish_is_not_selection_and_capture_freezes_context(self):
        a = self.context()
        self.assertFalse(self.app.call("manager.state")["active_context"])
        self.app.call("manager.context.select", {"id": a["id"]})
        itch = self.app.call("manager.capture", {"title": "fish fl"})
        self.context(testing="Swimming now")
        current = self.app.call("manager.context")
        stored = self.app.call("manager.get", {"id": itch["id"]})
        self.assertEqual(current["testing"], "Swimming now")
        self.assertEqual(stored["context"]["testing"], "Flop on land")
        self.assertEqual(stored["title"], "fish fl")

    def test_explicit_unlinked_capture_does_not_inherit_active_thread(self):
        self.context(select=True)
        itch = self.app.call("manager.capture", {"project": "other", "title": "scroll jumps", "use_active": False})
        self.assertIsNone(itch["context"])
        with self.assertRaises(APIError):
            self.app.call("manager.capture", {"project": "other", "title": "wrong context"})

    def test_offline_capture_keeps_observation_time_context_after_agent_update(self):
        original = self.context()
        self.context(testing="The task changed while the UI was offline")
        row = self.app.call("manager.capture", {"title": "Old observation", "context_id": original["id"],
                            "context_snapshot": json.dumps(original), "use_active": False})
        self.assertEqual(row["context"]["testing"], "Flop on land")
        with self.assertRaises(APIError):
            self.app.call("manager.capture", {"title": "Bad snapshot", "context_id": original["id"],
                            "context_snapshot": json.dumps({**original, "project": "other"})})

    def test_idempotency_survives_retry_and_detects_conflicts(self):
        args = {"title": "Capture once", "request_key": "browser-retry"}
        first = self.app.call("manager.capture", args)
        self.assertEqual(first, self.app.call("manager.capture", args))
        with self.assertRaises(APIError) as cm:
            self.app.call("manager.capture", {**args, "title": "different"})
        self.assertEqual(cm.exception.status, 409)
        self.assertEqual(self.app.call("manager.list")["total"], 1)

    def test_parallel_identical_capture_creates_one_record(self):
        rows, errors = [], []
        def save():
            try:
                rows.append(self.app.call("manager.capture", {"title": "Same moment", "request_key": "same"}))
            except Exception as exc:
                errors.append(exc)
        threads = [threading.Thread(target=save) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertFalse(errors)
        self.assertEqual(len({r["id"] for r in rows}), 1)

    def test_versions_stable_plan_ids_and_acceptance_are_separate(self):
        row = self.app.call("manager.capture", {"title": "Animation stops"})
        args = {"id": row["id"], "expected_version": 1, "changes": json.dumps({"plan": [{"text": "Reproduce"}, {"text": "Fix"}], "run_state": "agent_reported_done"})}
        updated = self.app.call("manager.update", args)
        self.assertEqual(updated["state"], "open")
        self.assertTrue(all(t["id"] for t in updated["plan"]))
        with self.assertRaises(APIError) as cm:
            self.app.call("manager.update", args)
        self.assertEqual(cm.exception.status, 409)
        with self.assertRaises(APIError):
            self.app.call("manager.complete", {"id": row["id"], "summary": "Agent finished"})
        resolved = self.app.call("manager.complete", {"id": row["id"], "summary": "Tested recovery", "accepted": True})
        self.assertEqual(resolved["state"], "resolved")
        repeated = self.app.call("manager.repeat", {"id": row["id"]})
        self.assertEqual(repeated["state"], "open")
        self.assertEqual(len(repeated["outcomes"]), 1)
        self.assertEqual(len(repeated["occurrences"]), 2)
        self.assertIsNone(repeated["recheck"])

    def test_marker_needs_description_and_brief_does_not_send(self):
        row = self.app.call("manager.capture", {"moment": True})
        self.assertEqual(row["state"], "needs_description")
        with self.assertRaises(APIError):
            self.app.call("manager.complete", {"id": row["id"], "summary": "Unknown", "accepted": True})
        brief = self.app.call("manager.brief", {"id": row["id"]})
        self.assertEqual(brief["handoff"], "copy_brief")
        self.assertIn("Recheck current conditions", brief["brief"])
        self.assertEqual(self.app.jobs.list()["total"], 0)

    def test_bounded_validation_rejects_wrong_json_and_blank_outcome(self):
        row = self.app.call("manager.capture", {"title": "Saved"})
        for changes in ['{"state":"resolved"}', '{"title":""}', '{"plan":"bad"}', '{"recheck":{"status":"fixed"}}']:
            with self.assertRaises(APIError):
                self.app.call("manager.update", {"id": row["id"], "changes": changes})
        with self.assertRaises(APIError):
            self.app.call("manager.complete", {"id": row["id"], "summary": "", "accepted": True})

    def test_replay_is_idle_bounded_and_cleanup_stays_in_owned_directory(self):
        replay = Replay(self.base / "media-test")
        self.assertFalse(replay.status()["armed"])
        for n in range(100):
            replay.add_frame(float(n)/10, b"x" * 1000)
        self.assertLessEqual(len(replay.ring), 61)
        self.assertLessEqual(replay.ring_bytes, 32 * 1024**2)
        id = "a"*32
        path = replay.directory(id)
        path.mkdir()
        atomic_json(path / "index.json", {"owner": OWNER, "id": id, "created": 0, "keep": False, "bytes": 10})
        (path / "0000.jpg").write_bytes(b"test")
        unrelated = self.base / "never-delete.txt"
        unrelated.write_text("keep")
        replay.cleanup()
        self.assertFalse(path.exists())
        self.assertTrue(unrelated.exists())
        with self.assertRaises(APIError):
            replay.directory("../outside")

    def test_replay_kept_budget_and_unexpected_files_are_preserved(self):
        replay = Replay(self.base / "replays")
        id = "b"*32
        path = replay.directory(id)
        path.mkdir()
        atomic_json(path / "index.json", {"owner": OWNER, "id": id, "created": 0, "keep": False, "bytes": 130*1024**2, "frames": [0]})
        (path / "unrelated.txt").write_text("keep")
        replay.cleanup()
        self.assertTrue(path.exists())
        with self.assertRaises(APIError):
            replay.keep(id)
        with self.assertRaises(APIError):
            replay.delete(id)





def read_json_fixture(path):
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

