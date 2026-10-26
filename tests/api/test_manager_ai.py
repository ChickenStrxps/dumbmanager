import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dumbapi_core.app import App
from dumbapi_core.common import APIError, Config
from dumbapi_core import manager_ai


class ManagerAITest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        (base / "DumbAPICommunity").mkdir()
        (base/"DumbAPICommunity"/"settings.json").write_text(json.dumps({"projects_root":".."}))
        self.app = App(Config(base / "DumbAPICommunity", base / "state"))
        self.no_key = patch.object(manager_ai, "jev_key", return_value="")
        self.no_key.start()

    def tearDown(self):
        self.no_key.stop()
        self.temp.cleanup()

    def itch(self, title, project="fish"):
        return self.app.call("manager.capture", {"title": title, "project": project, "use_active": False})

    def test_suggest_local_then_jev_pick(self):
        self.itch("Fish flops too slowly")
        self.itch("Fishing rod breaks on cast")
        local = self.app.call("manager.suggest", {"text": "fish fl", "project": "fish"})
        self.assertEqual(local["source"], "local")
        self.assertEqual(local["items"][0]["text"], "fish flops too slowly")
        with patch.object(manager_ai, "ask", return_value={"completion": {"choice": "c1", "p": 0.8, "probabilities": {"c1": 0.8, "c0": 0.1}}}):
            jev = self.app.call("manager.suggest", {"text": "fish rod", "project": "fish"})
        self.assertEqual(jev["source"], "jev")
        self.assertEqual(jev["items"][0]["source"], "jev")
        self.assertEqual(jev["pick"], jev["items"][0]["text"])

    def test_split_local_and_jev_joins(self):
        local = self.app.call("manager.split", {"text": "- fix login\n- add dark mode\n- the sound is too loud"})
        self.assertEqual(local["parts"], ["Fix login", "Add dark mode", "The sound is too loud"])
        text = "The boat is too slow. Also the shop is hidden on mobile and it needs a bigger button"
        pieces = manager_ai.fragments(text)
        self.assertGreaterEqual(len(pieces), 3)
        answers = {f"cut{i}": {"choice": "together" if i == len(pieces) - 1 else "separate", "p": .9, "probabilities": {}} for i in range(1, len(pieces))}
        with patch.object(manager_ai, "ask", return_value=answers):
            jev = self.app.call("manager.split", {"text": text})
        self.assertEqual(jev["source"], "jev")
        self.assertEqual(len(jev["parts"]), len(pieces) - 1)
        self.assertIn("bigger button", jev["parts"][-1])
        with self.assertRaises(APIError):
            self.app.call("manager.split", {"text": "   "})

    def test_chat_suggestions_use_exact_thread_context_and_candidates(self):
        a = "12345678-1234-4234-8234-123456789abc"
        b = "22345678-1234-4234-8234-123456789abc"
        self.app.call("manager.context.publish", {"project": "fish", "thread_id": a, "task": "Wrong task", "select": True})
        self.app.call("manager.context.publish", {"project": "shop", "thread_id": b, "task": "Shop search", "testing": "Search dropdown"})
        with patch.object(manager_ai, "ask", return_value=None) as ask:
            result = self.app.call("manager.suggest", {"text": "help search", "mode": "chat", "thread_id": b,
                "project": "fish", "candidates": json.dumps(["Help fix the search dropdown"])})
            self.assertEqual(result["items"][0]["text"], "Help fix the search dropdown")
            scope = ask.call_args.args[1]
            self.assertEqual(scope["context"], {"project": "shop", "task": "Shop search", "testing": "Search dropdown", "entities": ""})
        self.assertEqual(self.app.call("manager.suggest", {"text": "help", "mode": "chat", "candidates": '["Help me"]'})["items"], [])
        with self.assertRaises(APIError):
            self.app.call("manager.suggest", {"text": "help", "candidates": '[{}]'})

    def test_wrong_project_does_not_leak_selected_context(self):
        self.app.call("manager.context.publish", {"project": "fish", "thread_id": "12345678-1234-4234-8234-123456789abc",
            "task": "Axolotl flop", "candidates": '["Axolotl flop is stiff"]', "select": True})
        self.assertEqual(self.app.call("manager.suggest", {"text": "axo", "project": "shop"})["items"], [])

    def test_new_sentence_completes_partial_word_without_saved_phrase(self):
        for typed, expected in [("Add more fish to the ba", "Add more fish to the background"),
                                ("  Add fish to the BACKG", "  Add fish to the BACKGROUND")]:
            result = self.app.call("manager.suggest", {"text": typed, "project": "fish", "jev": False})
            self.assertIn(expected, [i["text"] for i in result["items"]])
            self.assertTrue(all(i["text"].startswith(typed) for i in result["items"]))
        self.assertTrue(self.app.call("manager.state")["typing_words"])

    def test_word_completion_uses_scoped_task_terms_and_jev_can_rank_it(self):
        thread = "12345678-1234-4234-8234-123456789abc"
        ctx = self.app.call("manager.context.publish", {"project": "fish", "thread_id": thread,
            "task": "Axolotl recovery", "entities": "Estuary"})
        result = self.app.call("manager.suggest", {"text": "Add an axo", "project": "fish", "context_id": ctx["id"], "jev": False})
        self.assertEqual(result["items"][0]["text"], "Add an axolotl")
        result = self.app.call("manager.suggest", {"text": "Open the estu", "mode": "chat", "thread_id": thread, "jev": False})
        self.assertEqual(result["items"][0]["text"], "Open the estuary")
        with patch.object(manager_ai, "ask", return_value={"completion": {"choice": "c0", "p": .95, "probabilities": {"c0": .95}}}):
            result = self.app.call("manager.suggest", {"text": "Add more fish to the ba", "project": "fish"})
        self.assertEqual((result["pick"], result["items"][0]["kind"]), ("Add more fish to the background", "word"))

    def test_word_completion_does_not_rewrite_urls_or_finished_words(self):
        for typed in ("Open https://example.ba", "Email me@example.ba", "Open ./ba", "background "):
            result = self.app.call("manager.suggest", {"text": typed, "project": "fish", "jev": False})
            self.assertEqual(result["items"], [])

    def test_longer_sentence_uses_recent_selected_thread_and_testing(self):
        thread = '12345678-1234-4234-8234-123456789abc'
        ctx = self.app.call('manager.context.publish', {'project':'fish', 'thread_id':thread,
            'task':'Fishing game', 'testing':'Fish should flop naturally when landing on the dock.'})
        with patch('dumbapi_core.t3.T3.read', return_value={'thread':{'title':'Fishing game'}, 'messages':[
                {'role':'user','text':'Fish stops flopping after landing on the dock.','at':'now'}]}) as read:
            value = self.app.call('manager.suggest', {'text':'I noticed the fish stops fl', 'context_id':ctx['id'], 'project':'fish', 'jev':False})
            self.assertEqual(value['context']['source'], 'live_thread')
            self.assertEqual(value['items'][0]['text'], 'I noticed the fish stops flopping after landing on the dock')
            self.assertEqual(value['items'][0]['kind'], 'continuation')
            value = self.app.call('manager.suggest', {'text':'Make sure the fish should fl', 'context_id':ctx['id'], 'project':'fish', 'jev':False})
            self.assertTrue(value['items'][0]['text'].endswith('naturally when landing on the dock'))
            read.assert_called_once_with(thread)
            # A different project cannot read the pinned thread or inherit its text.
            other = self.app.call('manager.suggest', {'text':'I noticed the fish stops fl', 'context_id':ctx['id'], 'project':'shop', 'jev':False})
            self.assertFalse(any(i['kind']=='continuation' for i in other['items']))
            read.assert_called_once()

    def test_split_comma_actions_and_limits_preserve_user_text(self):
        result = self.app.call("manager.split", {"text": "fix the login, add search, make the buttons bigger", "jev": False})
        self.assertEqual(result["parts"], ["Fix the login", "Add search", "Make the buttons bigger"])
        for value in ("A" * 501, "; ".join(f"Fix issue {i}" for i in range(13))):
            with self.assertRaises(APIError):
                self.app.call("manager.split", {"text": value, "jev": False})

    def test_merge_retry_is_exact_and_slow_suggestions_do_not_block_capture(self):
        import threading
        from concurrent.futures import ThreadPoolExecutor
        a, b = self.itch("Same problem"), self.itch("Same problem")
        args = {"id": b["id"], "into": a["id"], "request_key": "merge-retry"}
        self.assertEqual(self.app.call("manager.merge", args), self.app.call("manager.merge", args))
        self.itch("Fish flop is stiff")
        entered, release = threading.Event(), threading.Event()
        def wait(*args, **kwargs):
            entered.set()
            release.wait(3)
            return None
        with patch.object(manager_ai, "ask", side_effect=wait), ThreadPoolExecutor(2) as pool:
            future = pool.submit(self.app.call, "manager.suggest", {"text": "fish flop", "project": "fish"})
            try:
                self.assertTrue(entered.wait(2))
                captured = pool.submit(self.itch, "Capture while Jev waits").result(timeout=1)
                self.assertEqual(captured["title"], "Capture while Jev waits")
            finally:
                release.set()
            future.result(timeout=2)

    def test_propose_daily_limit_and_review_retry(self):
        titles = ["Search loses focus on escape", "Video preview lacks a pause button", "Export uses the wrong project folder"]
        for i, title in enumerate(titles):
            row = self.app.call("manager.propose", {"title": title, "project": "fish", "where": "fixture.py"})["item"]
            args = {"id": row["id"], "decision": "decline", "request_key": f"review-{i}"}
            self.assertEqual(self.app.call("manager.review", args), self.app.call("manager.review", args))
        with self.assertRaises(APIError) as caught:
            self.app.call("manager.propose", {"title": "Keyboard shortcut needs an editable binding", "project": "shop", "where": "fixture.py"})
        self.assertEqual(caught.exception.code, "daily_limit")

    def test_malformed_jev_responses_fall_back(self):
        question = {"pick": {"type": "choice", "criteria": {"yes": "Yes", "no": "No"}}}
        for response in ([], {"answers": []}, {"answers": {"pick": {"choice": ["yes"]}}}):
            with patch.object(manager_ai, "jev_key", return_value="fixture"), patch("dumbapi_core.browser.service_json", return_value=response):
                self.assertFalse(manager_ai.ask(self.app.config, {}, question))

    def test_duplicates_and_merge_keep_history(self):
        a = self.itch("Fish flops too slowly on land")
        b = self.itch("fish flops too slowly on land")
        self.itch("Shop button hidden", "shop")
        found = self.app.call("manager.duplicates", {"project": "fish"})
        self.assertEqual(found["source"], "local")
        self.assertEqual(len(found["pairs"]), 1)
        pair = found["pairs"][0]
        self.assertEqual({pair["keep"]["id"], pair["drop"]["id"]}, {a["id"], b["id"]})
        keep, drop = pair["keep"]["id"], pair["drop"]["id"]
        merged = self.app.call("manager.merge", {"id": drop, "into": keep})
        self.assertEqual(len(merged["kept"]["occurrences"]), 2)
        self.assertEqual(merged["archived"]["state"], "archived")
        self.assertEqual(self.app.call("manager.get", {"id": drop})["merged_into"], keep)
        self.assertEqual(self.app.call("manager.duplicates", {"project": "fish"})["pairs"], [])
        with self.assertRaises(APIError):
            self.app.call("manager.merge", {"id": drop, "into": keep})

    def test_jev_none_suppresses_weak_pairs(self):
        self.itch("Camera shakes while reeling")
        self.itch("Camera shakes while walking")
        with patch.object(manager_ai, "ask", return_value={"d0": {"choice": "none", "p": .9, "probabilities": {}}, "d1": {"choice": "none", "p": .9, "probabilities": {}}}):
            self.assertEqual(self.app.call("manager.duplicates", {})["pairs"], [])


    def test_scout_plan_is_read_only(self):
        from dumbapi_core.manager import scout_capabilities
        allowed = scout_capabilities(self.app.capabilities)
        self.assertTrue(all(c["mode"] == "read" for c in allowed.values()))
        for blocked in ("catalog.refresh", "browser.start", "browser.snapshot", "manager.capture", "git.action", "t3.read", "manager.export"):
            self.assertNotIn(blocked, allowed)
        self.assertIn("source.read", allowed)

    def test_scout_plan_scopes_selected_project_and_preserves_random_default(self):
        base = self.app.config.root.parent
        (base / "Sample Workspace").mkdir()
        (base / "OtherProject").mkdir()
        wanted = self.itch("Voxel chunk stalls", project="sample-workspace")
        self.itch("Other project stalls", project="otherproject")
        self.app.call("manager.propose", {"title": "Voxel UI needs labels", "project": "sample-workspace", "where": "fixture"})
        before = self.app.call("manager.list", {})
        plan = self.app.call("manager.scout.plan", {"project": "sample-workspace"})
        self.assertEqual((plan["project"], plan["folder"]), ("sample-workspace", "Sample Workspace"))
        self.assertIn({"id": "sample-workspace", "folder": "Sample Workspace"}, plan["projects"])
        self.assertEqual({r["title"] for r in plan["known_itches"]}, {wanted["title"], "Voxel UI needs labels"})
        self.assertIn("--project 'sample-workspace'", plan["search_hint"])
        self.assertTrue(all(c["id"] in {"projects.list", "source.read", "git.status", "git.diff", "git.history", "manager.list", "manager.get"} for c in plan["capabilities"]))
        self.assertEqual(before, self.app.call("manager.list", {}))
        self.assertEqual(self.app.call("manager.scout.plan", {"seed": "stable"}), self.app.call("manager.scout.plan", {"seed": "stable"}))
        with self.assertRaises(APIError):self.app.call("manager.scout.plan", {"project": "missing"})


if __name__ == "__main__":
    unittest.main()
