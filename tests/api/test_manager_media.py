import io
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dumbapi_core.app import App
from dumbapi_core.common import APIError, Config
from dumbapi_core.manager import Manager
from dumbapi_core.manager_media import Media


class MediaTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        hub = self.base / "DumbAPICommunity"
        hub.mkdir()
        self.config = Config(hub, self.base / "state")
        self.app = App(self.config)
        self.manager = Manager(self.config)
        self.media = Media(self.manager)

    def upload(self, data=b"image fixture", name="fish.png", mime="image/png", mode="original"):
        return self.media.upload(self.config, io.BytesIO(data), len(data), name, mime, mode)["attachment"]

    def test_local_evidence_survives_reload_without_t3_and_capture_retry_is_exact(self):
        with patch("dumbapi_core.t3.T3.connection", side_effect=AssertionError("Must stay local")):
            image = self.upload()
            video = self.upload(b"video fixture", "clip.mp4", "video/mp4")
            args = {"attachments": json.dumps([image["id"], video["id"]]), "request_key": "media-once", "use_active": False}
            saved = self.app.call("manager.capture", args)
            self.assertEqual(self.app.call("manager.capture", args), saved)
        self.assertEqual(saved["attachments"], [image, video])
        self.assertEqual(saved["state"], "needs_description")
        self.assertTrue(saved["title"].startswith("Evidence:"))
        reader = Media(Manager(self.config))
        file, _ = reader.read(video["id"])
        self.assertEqual(file.read_bytes(), b"video fixture")
        self.assertEqual(self.app.call("manager.get", {"id": saved["id"]})["attachments"], [image, video])
        self.assertIn(video["id"], self.app.call("manager.brief", {"id": saved["id"]})["brief"])

    def test_missing_wrong_kind_duplicate_and_oversized_reference_lists_are_rejected(self):
        image = self.upload()
        itch = self.app.call("manager.capture", {"title": "Existing"})
        for ids in ([image["id"]]*2, [itch["id"]], ["bad"], [str(i) for i in range(9)]):
            with self.assertRaises(APIError):
                self.app.call("manager.capture", {"title": "Bad", "attachments": json.dumps(ids)})
        self.media.read(image["id"])[0].unlink()
        with self.assertRaises(APIError):
            self.app.call("manager.capture", {"attachments": json.dumps([image["id"]])})
        with self.assertRaises(APIError):
            self.media.read("../../desktop.token")

    def test_append_evidence_is_retry_safe_and_preserves_other_edits(self):
        first,second=self.upload(),self.upload(b'second')
        row=self.app.call('manager.capture',{'title':'Original','attachments':json.dumps([first['id']])})
        self.app.call('manager.update',{'id':row['id'],'changes':json.dumps({'title':'Renamed','state':'ready'})})
        args={'id':row['id'],'attachments':json.dumps([second['id']])}
        added=self.app.call('manager.attach',args)
        self.assertEqual(added['title'],'Renamed');self.assertEqual(added['state'],'ready')
        self.assertEqual(added['attachments'],[first,second])
        self.assertEqual(self.app.call('manager.attach',args),added)
        self.assertEqual(self.app.call('manager.get',{'id':row['id']})['attachments'],[first,second])
        with self.assertRaises(APIError):self.app.call('manager.attach',{'id':row['id'],'attachments':'["missing"]'})
        self.assertEqual(self.app.call('manager.get',{'id':row['id']}),added)

    def test_append_limit_never_drops_existing_receipts(self):
        images=[self.upload(str(i).encode()) for i in range(9)]
        row=self.app.call('manager.capture',{'title':'Full','attachments':json.dumps([a['id'] for a in images[:8]])})
        with self.assertRaises(APIError):self.app.call('manager.attach',{'id':row['id'],'attachments':json.dumps([images[8]['id']])})
        self.assertEqual(self.app.call('manager.get',{'id':row['id']})['attachments'],images[:8])

    def test_interrupted_upload_and_conversion_failure_leave_no_files(self):
        with self.assertRaises(APIError):
            self.media.upload(self.config, io.BytesIO(b"short"), 500, "fish.png", "image/png")
        with patch("dumbapi_core.manager_media.frameboard", side_effect=APIError("Bad clip")):
            with self.assertRaises(APIError):
                self.upload(b"clip", "clip.mp4", "video/mp4", "frameboard")
        self.assertEqual(list(self.media.folder.iterdir()), [])

    def test_type_size_and_budget_guards(self):
        for size, mime in ((0, "image/png"), (51*1024*1024, "video/mp4"), (11*1024*1024, "image/png"), (10, "text/html")):
            with self.assertRaises(APIError):
                self.media.upload(self.config, io.BytesIO(), size, "bad", mime)
        image = self.upload()
        self.app.call("manager.capture", {"title": "Keep", "attachments": json.dumps([image["id"]])})
        with patch("dumbapi_core.manager_media.MAX_TOTAL", 20):
            with self.assertRaises(APIError):
                self.upload(b"x"*20)
        self.assertEqual(self.media.read(image["id"])[0].read_bytes(), b"image fixture")

    def test_cleanup_expires_only_unclaimed_uploads(self):
        staged, kept = self.upload(), self.upload()
        self.app.call("manager.capture", {"attachments": json.dumps([kept["id"]])})
        with self.manager.db() as db:
            for id in (staged["id"], kept["id"]):
                row = self.manager.get(db, id, "media")
                row["created_at"] = "2020-01-01T00:00:00+00:00"
                self.manager.put(db, "media", row)
        self.upload()
        with self.assertRaises(APIError):
            self.media.read(staged["id"])
        self.assertTrue(self.media.read(kept["id"])[0].is_file())

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "Optional FFmpeg tools unavailable")
    def test_real_short_video_generates_persisted_timestamped_frameboard(self):
        clip = self.base / "clip.mp4"
        subprocess.run([shutil.which("ffmpeg"), "-v", "error", "-f", "lavfi", "-i", "color=c=gold:s=160x90:d=1", "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(clip)],
                       check=True, capture_output=True, timeout=20, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.config.root = (Path(__file__).resolve().parents[2]/"backend")
        attachment = self.upload(clip.read_bytes(), "clip.mp4", "video/mp4", "frameboard")
        self.assertEqual(attachment["mimeType"], "image/jpeg")
        self.assertIn("no-audio", attachment["name"])
        content = self.media.read(attachment["id"])[0].read_bytes()
        self.assertTrue(content.startswith(b"\xff\xd8"))
        self.assertLess(len(content), 2*1024*1024)
        self.assertEqual(list((self.media.folder / attachment["id"]).iterdir()), [self.media.folder / attachment["id"] / "content"])
