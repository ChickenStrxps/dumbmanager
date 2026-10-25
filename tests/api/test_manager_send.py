import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dumbapi_core.app import App
from dumbapi_core.common import APIError, Config
from dumbapi_core.manager import Manager
from dumbapi_core.manager_media import Media
from dumbapi_core.manager_send import sending_lock

THREAD = "12345678-1234-4234-8234-123456789abc"


class HandoffTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        hub = base / "DumbAPICommunity"
        hub.mkdir()
        self.config = Config(hub, base / "state")
        self.app = App(self.config)
        self.manager = Manager(self.config)
        self.media = Media(self.manager)
        self.local = self.media.upload(self.config, io.BytesIO(b"image"), 5, "fish.png", "image/png")["attachment"]
        self.itch = self.app.call("manager.capture", {"title": "Fish flop", "attachments": json.dumps([self.local["id"]])})
        self.args = {"id": self.itch["id"], "thread_id": THREAD, "request_key": "cook-once"}
        self.remote = {"id": "t3-image", "type": "image", "name": "fish.png", "mimeType": "image/png", "sizeBytes": 5}
        self.connection = self.enterContext(patch("dumbapi_core.t3.T3.connection", return_value={"url": "http://127.0.0.1:3773", "token": "fixture"}))
        self.upload = self.enterContext(patch("dumbapi_core.manager_send.upload", return_value={"attachment": self.remote}))

    def test_media_is_transferred_once_and_receipt_preserves_original_itch(self):
        with patch("dumbapi_core.t3.rpc", return_value={"sequence": 1}) as transport:
            first = self.app.call("manager.send", self.args)
            self.assertEqual(self.app.call("manager.send", self.args), first)
        self.assertEqual(self.upload.call_count, 1)
        self.assertEqual(transport.call_count, 1)
        command = transport.call_args.args[2]
        self.assertEqual(command["attachments"], [self.remote])
        self.assertEqual(command["threadId"], THREAD)
        self.assertIn("Fish flop", command["text"])
        self.assertNotIn("not automatically sent", command["text"])
        saved = self.app.call("manager.get", {"id": self.itch["id"]})
        self.assertEqual(saved["state"], "open")
        self.assertEqual(saved["attachments"], [self.local])
        self.assertEqual(len(saved["handoffs"]), 1)
        self.assertEqual(self.media.read(self.local["id"])[0].read_bytes(), b"image")

    def test_unconfirmed_send_freezes_snapshot_and_reuses_media_command_and_message_ids(self):
        with patch("dumbapi_core.t3.rpc", side_effect=OSError("Lost response")) as first:
            with self.assertRaises(APIError):
                self.app.call("manager.send", self.args)
        self.app.call("manager.update", {"id": self.itch["id"], "changes": '{"title":"Changed meanwhile"}'})
        with patch("dumbapi_core.t3.rpc", return_value={"sequence": 2}) as second:
            self.app.call("manager.send", self.args)
        self.assertEqual(self.upload.call_count, 1)
        self.assertEqual(first.call_args.args[2], second.call_args.args[2])
        self.assertIn("Fish flop", second.call_args.args[2]["text"])

    def test_retry_rejects_changed_destination_or_message(self):
        with patch("dumbapi_core.t3.rpc", return_value={"sequence": 1}):
            self.app.call("manager.send", self.args)
        for change in ({"thread_id": "22345678-1234-4234-8234-123456789abc"}, {"message": "Other text"}, {"video_mode": "original"}):
            with self.assertRaises(APIError) as error:
                self.app.call("manager.send", {**self.args, **change})
            self.assertEqual(error.exception.status, 409)
        self.assertEqual(self.upload.call_count, 1)

    def test_missing_media_fails_before_any_remote_upload(self):
        self.media.read(self.local["id"])[0].unlink()
        with self.assertRaises(APIError):
            self.app.call("manager.send", self.args)
        self.upload.assert_not_called()

    def test_followup_reopens_same_itch_and_preserves_finished_work(self):
        plan=[{'id':'done-before','text':'Original work','done':True}]
        self.app.call('manager.update',{'id':self.itch['id'],'changes':json.dumps({'state':'ready','run_state':'agent_reported_done','plan':plan,'evidence':['Original verification']})})
        args={**self.args,'followup':'Include a small screenshot and blur personal details.'}
        with patch('dumbapi_core.t3.rpc',return_value={'sequence':1}) as transport:
            self.app.call('manager.send',args);self.app.call('manager.send',args)
        saved=self.app.call('manager.get',{'id':self.itch['id']})
        self.assertEqual((saved['state'],saved['run_state']),('open','not_sent'))
        self.assertEqual(saved['plan'],plan);self.assertEqual(saved['evidence'],['Original verification'])
        self.assertEqual(saved['attachments'],[self.local]);self.assertEqual(saved['outcomes'],[])
        self.assertEqual(len(saved['feedback']),1);self.assertEqual(saved['feedback'][0]['text'],args['followup'])
        self.assertEqual(saved['feedback'][0]['request_key'],saved['handoffs'][0]['request_key'])
        self.assertEqual(len(saved['handoffs']),1);transport.assert_called_once();self.upload.assert_called_once()
        message=transport.call_args.args[2]['text']
        self.assertIn('Follow-up request: '+args['followup'],message)
        self.assertIn(self.itch['id'],message);self.assertIn('completed plan steps are history',message)

    def test_followup_failure_and_lost_response_retry_keep_one_note_and_command(self):
        args={**self.args,'followup':'Keep the preview compact.'}
        self.upload.side_effect=OSError('Upload unavailable')
        with self.assertRaises(OSError):self.app.call('manager.send',args)
        saved=self.app.call('manager.get',{'id':self.itch['id']})
        self.assertEqual(len(saved['feedback']),1);self.assertNotIn('handoffs',saved)
        self.upload.side_effect=None
        with patch('dumbapi_core.t3.rpc',side_effect=OSError('Lost response')) as first:
            with self.assertRaises(APIError):self.app.call('manager.send',args)
        with patch('dumbapi_core.t3.rpc',return_value={'sequence':1}) as retry:self.app.call('manager.send',args)
        self.assertEqual(first.call_args.args[2],retry.call_args.args[2])
        saved=self.app.call('manager.get',{'id':self.itch['id']})
        self.assertEqual(len(saved['feedback']),1);self.assertEqual(len(saved['handoffs']),1)
        with self.assertRaises(APIError) as caught:self.app.call('manager.send',{**args,'followup':'Different note'})
        self.assertEqual(caught.exception.status,409)

    def test_invalid_followup_leaves_review_unchanged(self):
        self.app.call('manager.update',{'id':self.itch['id'],'changes':'{"state":"ready","run_state":"agent_reported_done"}'})
        before=self.app.call('manager.get',{'id':self.itch['id']})
        with self.assertRaises(APIError):self.app.call('manager.send',{**self.args,'followup':'x'*2001})
        self.assertEqual(self.app.call('manager.get',{'id':self.itch['id']}),before)
        self.upload.assert_not_called()

    def test_send_lock_does_not_block_capture_and_releases_on_failure(self):
        with sending_lock(self.manager.data / "handoff.lock"):
            self.app.call("manager.capture", {"title": "Still capturing"})
            with self.assertRaises(APIError):
                self.app.call("manager.send", self.args)
        with patch("dumbapi_core.t3.rpc", return_value={"sequence": 1}):
            self.app.call("manager.send", self.args)
