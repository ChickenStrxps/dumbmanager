import base64
import hashlib
import json
import socketserver
import struct
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from dumbapi_core.app import App
from dumbapi_core.common import APIError, Config, atomic_json
from dumbapi_core.t3 import T3, rpc

THREAD = "12345678-1234-4234-8234-123456789abc"


class T3Test(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        root = base / "DumbAPICommunity"
        root.mkdir()
        self.config = Config(root, base / "state")
        self.bridge = T3(self.config)
        atomic_json(self.config.data / "t3-connection.json", {"url":"http://127.0.0.1:3773", "token":"fixture-only"})

    def test_send_receipt_and_conflicting_words_or_thread(self):
        app = App(self.config)
        with patch("dumbapi_core.t3.rpc", return_value={"sequence":12}) as transport:
            first = app.call("t3.send", {"thread_id":THREAD,"message":"fix the fish","request_key":"once"})
            self.assertEqual(first, app.call("t3.send", {"thread_id":THREAD,"message":"fix the fish","request_key":"once"}))
            self.assertEqual(transport.call_count,1)
            command = transport.call_args.args[2]
            self.assertEqual(command["threadId"],THREAD)
            self.assertEqual(command["dispatchMode"],{"type":"queue_after_active"})
            self.assertEqual(command["text"],"fix the fish")
            for changed in ({"message":"different"},{"thread_id":"22345678-1234-4234-8234-123456789abc"}):
                with self.assertRaises(APIError):
                    app.call("t3.send", {"thread_id":THREAD,"message":"fix the fish","request_key":"once",**changed})
        self.assertNotIn(b"fix the fish",(self.config.data / "t3-receipts.sqlite3").read_bytes())

    def test_unconfirmed_retry_retains_exact_t3_identifiers(self):
        with patch("dumbapi_core.t3.rpc", side_effect=[TimeoutError(),{"sequence":14}]) as transport:
            with self.assertRaises(APIError):
                self.bridge.send(THREAD,"same message","retry")
            self.bridge.send(THREAD,"same message","retry")
            self.assertEqual(transport.call_args_list[0].args[2],transport.call_args_list[1].args[2])

    def test_connection_is_loopback_and_ids_cannot_escape_routes(self):
        for url in ("https://remote.example", "http://127.0.0.1:3773/other", "http://user@127.0.0.1:3773", "http://localhost:3773"):
            atomic_json(self.config.data / "t3-connection.json", {"url":url,"token":"fixture"})
            with self.assertRaises(APIError):self.bridge.connection()
        for id in ("../shell", "", "thread?secret", "mcp:../shell", "mcp:"+THREAD+"/bounded", "mcp:"+THREAD+"?secret", "mcp:mcp:"+THREAD, None):
            with self.assertRaises(APIError):self.bridge.read(id)

    def test_mcp_thread_keeps_exact_id_for_read_send_and_retry(self):
        thread = "mcp:" + THREAD
        projection = {"thread": {"id": thread, "title": "DumbManager daily scout"}}
        with patch.object(self.bridge, "get", return_value={"projection": projection}) as get:
            self.assertEqual(self.bridge.read(thread)["thread"]["id"], thread)
            self.assertEqual(get.call_args.args[0], "/api/orchestration/threads/"+thread+"/bounded?compactTurnItems=1")
        with patch("dumbapi_core.t3.rpc", side_effect=[TimeoutError(), {"sequence": 14}]) as transport:
            with self.assertRaises(APIError):self.bridge.send(thread, "Read one project", "mcp-retry")
            receipt = self.bridge.send(thread, "Read one project", "mcp-retry")
            self.assertEqual(receipt["thread_id"], thread)
            self.assertEqual(transport.call_args.args[2]["threadId"], thread)
            self.assertEqual(transport.call_args_list[0].args[2], transport.call_args_list[1].args[2])
            self.assertEqual(self.bridge.send(thread, "Read one project", "mcp-retry"), receipt)
            self.assertEqual(transport.call_count, 2)

    def test_explicit_pairing_stores_scoped_token_without_returning_it(self):
        from types import SimpleNamespace
        with patch("dumbapi_core.t3.Path.is_file",return_value=True), patch("dumbapi_core.t3.subprocess.run",return_value=SimpleNamespace(returncode=0,stdout=json.dumps({"token":"private-fixture","expiresAt":"later"}))) as process:
            result=self.bridge.connect()
        self.assertNotIn("private-fixture",json.dumps(result))
        self.assertEqual(self.bridge.connection()["token"],"private-fixture")
        argv=process.call_args.args[0]
        self.assertIn("orchestration:read",argv)
        self.assertIn("orchestration:operate",argv)
        self.assertNotIn("access:write",argv)

    def test_read_bounds_text_and_detects_running_work(self):
        projection = {"thread":{"id":THREAD,"title":"Fish"},"runs":[{"status":"running"},{"status":"queued"}],
                      "messages":[{"id":str(i),"role":"assistant","text":"x"*7000,"createdAt":str(i).zfill(2)} for i in range(12)]}
        with patch.object(self.bridge,"get",return_value={"projection":projection,"hasMoreHistory":True}):
            result=self.bridge.read(THREAD)
        self.assertEqual(len(result["messages"]),8)
        self.assertTrue(result["thread"]["active"])
        self.assertTrue(result["messages"][0]["truncated"])
        self.assertEqual(len(result["messages"][0]["text"]),6000)
        self.assertEqual(result["queued"],1)

    def test_published_visuals_only_and_bounded(self):
        def item(n, **changes):
            return {"item":{"type":"dynamic_tool","status":"completed","toolName":"t3-code.html_render",
                            "startedAt":str(n),"output":{"htmlRender":{"attachmentId":"visual-"+str(n),"title":"Concept","height":500}},**changes}}
        entries=[item(n) for n in range(6)]
        entries.extend([item(10,toolName="untrusted.html_fake"),item(11,status="failed"),item(12,output={"isError":True,"htmlRender":{"attachmentId":"bad","height":400}})])
        refs=self.bridge.previews({"visibleTurnItems":entries})
        self.assertEqual([r['id'] for r in refs],['visual-2','visual-3','visual-4','visual-5'])
        self.assertNotIn('html',json.dumps(refs))
        with patch.object(self.bridge,"get",return_value={"projection":{"visibleTurnItems":entries}}),patch('dumbapi_core.t3.rpc') as transport:
            with self.assertRaises(APIError):self.bridge.preview(THREAD,'../unrelated')
            transport.assert_not_called()

    def test_attachment_only_message_and_retry_identity(self):
        attachment={"id":"upload-fixture","type":"image","name":"Fish.png","mimeType":"image/png","sizeBytes":123}
        encoded=json.dumps([attachment])
        with patch('dumbapi_core.t3.rpc',side_effect=[TimeoutError(),{"sequence":15}]) as transport:
            with self.assertRaises(APIError):self.bridge.send(THREAD,'','image-retry',encoded)
            self.bridge.send(THREAD,'','image-retry',encoded)
            self.assertEqual(transport.call_args_list[0].args[2],transport.call_args_list[1].args[2])
            self.assertEqual(transport.call_args.args[2]['attachments'],[attachment])
            with self.assertRaises(APIError):self.bridge.send(THREAD,'','image-retry',json.dumps([{**attachment,'id':'different'}]))
        for rows in ([attachment]*9,[{**attachment,'id':'../escape'}],[{**attachment,'sizeBytes':50*1024*1024}],[{**attachment,'mimeType':'text/html'}]):
            with self.assertRaises(APIError):self.bridge.attachment_list(json.dumps(rows))
        with patch.object(self.bridge,'get',return_value={'projection':{'thread':{'id':THREAD},'messages':[{'id':'m','role':'user','attachments':[attachment],'createdAt':'2026-10-19T12:00:00Z'}]}}):
            self.assertEqual(self.bridge.read(THREAD)['messages'][0]['attachments'],[attachment])

    def test_masked_websocket_rpc_handshake_and_delivery(self):
        received=[]
        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                line=self.rfile.readline().decode()
                self.server.test.assertIn("orchestrationProtocol=2",line)
                headers={}
                while (line:=self.rfile.readline())!=b"\r\n":
                    k,_,v=line.decode().partition(":");headers[k.lower()]=v.strip()
                self.server.test.assertEqual(headers["authorization"],"Bearer fixture-only")
                accept=base64.b64encode(hashlib.sha1((headers['sec-websocket-key']+'258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()).decode()
                self.wfile.write(('HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: '+accept+'\r\n\r\n').encode());self.wfile.flush()
                a,b=self.rfile.read(2);n=b&127
                self.server.test.assertTrue(b&128)
                if n==126:n=struct.unpack('!H',self.rfile.read(2))[0]
                elif n==127:n=struct.unpack('!Q',self.rfile.read(8))[0]
                mask=self.rfile.read(4);raw=self.rfile.read(n)
                received.append(json.loads(bytes(v^mask[i%4]for i,v in enumerate(raw))))
                raw=json.dumps({'_tag':'Exit','requestId':'1','exit':{'_tag':'Success','value':{'sequence':19}}}).encode()
                self.wfile.write(bytes([129,len(raw)])+raw);self.wfile.flush()
                self.rfile.read(8)
        with socketserver.TCPServer(("127.0.0.1",0),Handler) as server:
            server.test=self
            worker=threading.Thread(target=server.handle_request);worker.start()
            result=rpc({"url":"http://127.0.0.1:"+str(server.server_address[1]),"token":"fixture-only"},"test.read",{"text":"🐟"*300})
            worker.join(3)
        self.assertEqual(result,{"sequence":19})
        self.assertEqual(received[0]["payload"]["text"],"🐟"*300)


if __name__ == "__main__":
    unittest.main()
