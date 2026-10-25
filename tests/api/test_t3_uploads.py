import io
import json
import shutil
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from dumbapi_core.common import APIError, Config, atomic_json
from dumbapi_core.t3_uploads import upload, frameboard


class UploadTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name);hub=self.base/'DumbAPI';hub.mkdir()
        self.config=Config(hub,self.base/'state')
        atomic_json(self.config.data/'t3-connection.json',{'url':'http://127.0.0.1:3773','token':'private-fixture'})

    def test_streamed_file_uses_signed_fixed_route_and_cleans_temporary_bytes(self):
        received=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*_):pass
            def do_POST(self):
                received.append((self.path,self.headers.get('Authorization'),self.rfile.read(int(self.headers['Content-Length']))))
                self.send_response(200);self.send_header('Content-Length','2');self.end_headers();self.wfile.write(b'{}')
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        atomic_json(self.config.data/'t3-connection.json',{'url':'http://127.0.0.1:'+str(server.server_port),'token':'private-fixture'})
        with patch('dumbapi_core.t3_uploads.rpc',return_value={'relativeUrl':'/api/attachments/upload/fixture.signature','attachmentId':'fixture-id'}) as transport:
            result=upload(self.config,io.BytesIO(b'hello'),5,'notes.txt','text/plain')
        self.assertEqual(received,[('/api/attachments/upload/fixture.signature',None,b'hello')])
        self.assertEqual(result['attachment']['type'],'file')
        self.assertEqual(transport.call_args.args[1],'attachments.createUploadUrl')
        self.assertFalse(list((self.config.data/'upload-temp').iterdir()))

    def test_failed_upload_cleans_bytes_and_disallows_redirect_or_external_url(self):
        with patch('dumbapi_core.t3_uploads.rpc',return_value={'relativeUrl':'http://elsewhere/upload','attachmentId':'fixture'}):
            with self.assertRaises(APIError):upload(self.config,io.BytesIO(b'hi'),2,'notes.txt','text/plain')
        self.assertFalse(list((self.config.data/'upload-temp').iterdir()))
        for size,mime in ((0,'text/plain'),(51*1024*1024,'video/mp4'),(11*1024*1024,'image/png')):
            with self.assertRaises(APIError):upload(self.config,io.BytesIO(b''),size,'test',mime)
        with self.assertRaises(APIError):upload(self.config,io.BytesIO(b'partial'),20,'notes.txt','text/plain')
        self.assertFalse(list((self.config.data/'upload-temp').iterdir()))

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'Optional FFmpeg missing')
    def test_actual_video_frameboard_has_nine_timestamped_samples_and_small_output(self):
        font=Path(__file__).resolve().parents[2]/'dumbmanager/web/fonts/IBMPlexMono.ttf'
        if not font.is_file():self.skipTest('Bundled UI font missing')
        target=self.base/'dumbmanager/web/fonts/IBMPlexMono.ttf';target.parent.mkdir(parents=True);shutil.copyfile(font,target)
        source=self.base/'fixture.mp4'
        subprocess.run([shutil.which('ffmpeg'),'-v','error','-f','lavfi','-i','testsrc2=size=320x180:rate=12','-t','2','-an','-threads','1',str(source)],check=True,capture_output=True,timeout=20,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        board,duration=frameboard(source,self.base,self.config.root)
        self.assertAlmostEqual(duration,2,places=1)
        self.assertLess(board.stat().st_size,2*1024*1024)
        probe=subprocess.run([shutil.which('ffprobe'),'-v','error','-show_entries','stream=width,height','-of','json',str(board)],capture_output=True,check=True,timeout=10,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        stream=json.loads(probe.stdout)['streams'][0]
        self.assertEqual((stream['width'],stream['height']),(1464,834))
