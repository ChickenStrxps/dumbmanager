import base64
import copy
import json
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from dumbapi_core.bridge import Bridge, remote
from dumbapi_core.common import APIError, Config, json_text
from dumbapi_core.discord_bridge import Discord, commands, form_values, modal, panel, register, verifier, verify


class DiscordTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not verifier():raise unittest.SkipTest('Installed OpenSSL is required for real Ed25519 signature checks.')
        cls.sign_temp=tempfile.TemporaryDirectory();cls.sign_folder=Path(cls.sign_temp.name)
        cls.private=cls.sign_folder/'private.pem';public=cls.sign_folder/'public.der'
        cls.openssl(['genpkey','-algorithm','ED25519','-out',str(cls.private)])
        cls.openssl(['pkey','-in',str(cls.private),'-pubout','-outform','DER','-out',str(public)])
        cls.public=public.read_bytes()[-32:].hex()

    @classmethod
    def tearDownClass(cls):cls.sign_temp.cleanup()

    @staticmethod
    def openssl(args):
        result=subprocess.run([verifier(),*args],capture_output=True,timeout=5,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if result.returncode:raise AssertionError('OpenSSL test fixture failed')

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();base=Path(self.temp.name)
        hub=base/'projects/DumbAPI';hub.mkdir(parents=True);(hub.parent/'Fish').mkdir()
        (hub/'settings.json').write_text(json.dumps({'projects_root':'..'}))
        self.bridge=Bridge(Config(hub,base/'data'))
        self.bridge.configure(application_id='333333333',public_key=self.public,users='123456789',enabled=True)
        self.discord=Discord(self.bridge);self.event=100000000;self.delivered=[]
        self.delivery_patch=patch.object(self.discord,'deliver',side_effect=lambda event,payload,card=None:self.delivered.append((payload,card)))
        self.delivery_patch.start()
        self.card_patch=patch.object(self.bridge,'card',side_effect=APIError('No renderer in protocol unit fixture'))
        self.card_patch.start()

    def tearDown(self):
        self.discord.close();self.card_patch.stop();self.delivery_patch.stop();self.temp.cleanup()

    def value(self,**changes):
        self.event+=1
        return {'id':str(self.event),'application_id':'333333333','type':2,'token':'unit-fixture-token',
            'user':{'id':'123456789'},'channel_id':'987654321','data':{'name':'dumbbridge','type':1,
                'options':[{'name':'message','value':'Make an ASCII fish reef.'}]},**changes}

    def signed(self,value,timestamp=None):
        body=json_text(value).encode();timestamp=timestamp or str(int(time.time()))
        # Native OpenSSL signs the fixture; production code verifies, never signs.
        message=self.sign_folder/'message';signature=self.sign_folder/'signature'
        message.write_bytes(timestamp.encode()+body)
        self.openssl(['pkeyutl','-sign','-rawin','-inkey',str(self.private),'-in',str(message),'-out',str(signature)])
        return body,{'X-Signature-Ed25519':signature.read_bytes().hex(),'X-Signature-Timestamp':timestamp}

    def receive(self,value,work=False):
        response,event=self.discord.receive(*self.signed(value))
        if work and event:self.discord.work(event)
        return response,event

    def draft(self):
        response,event=self.receive(self.value(),True)
        id=response['data']['components'][0]['components'][0]['custom_id'].split(':')[2]
        return self.bridge.get(id,'discord:123456789')

    def click(self,row,action,values=None,kind=3,components=None,work=True):
        data={'custom_id':f'db:{action}:{row["id"]}:{row["version"]}'}
        if values is not None:data['values']=values
        if components is not None:data['components']=components
        return self.receive(self.value(type=kind,data=data),work)

    def test_inspector_is_private_transient_and_accepts_whitespace(self):
        def counts():
            with self.bridge.manager.db() as db:
                names=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
                return {name:db.execute('SELECT COUNT(*) FROM "'+name+'"').fetchone()[0] for name in names}
        before=counts()
        value=self.value(data={'name':'dbinspect','type':1,'options':[{'name':'text','value':'private-inspector-source\t\r\n\u202e'}]})
        with patch.object(self.bridge,'create',side_effect=AssertionError('No intake')),patch('dumbapi_core.discord_bridge.remote',side_effect=AssertionError('No outgoing request')):
            for _ in range(2):
                response,event=self.receive(value)
                self.assertIsNone(event);self.assertEqual(response['data']['flags'],64)
                self.assertEqual(response['data']['allowed_mentions'],{'parse':[]})
                self.assertIn('U+202E',response['data']['content']);self.assertIn('CRLF: 1',response['data']['content'])
                self.assertNotIn('private-inspector-source',response['data']['content'])
            selected=self.value(data={'name':'Inspect characters','type':3,'target_id':'777777777','resolved':{'messages':{'777777777':{'id':'777777777','content':'\t \n'}}}})
            self.assertIn('Tab: 1',self.receive(selected)[0]['data']['content'])
        self.assertEqual(before,counts());self.assertEqual(self.delivered,[])

    def test_inspector_errors_are_private_and_current_authorization_applies(self):
        for data in [
            {'name':'dbinspect','type':1,'options':[{'name':'text','value':'x'*4001}]},
            {'name':'dbinspect','type':1,'options':[{'name':'text','value':''}]},
            {'name':'Inspect characters','type':3,'target_id':'777777777','resolved':{'messages':{'777777777':{'id':'777777777'}}}},
            {'name':'dbinspect','type':1,'options':[{'name':'text','value':'a'},{'name':'text','value':'b'}]}]:
            response,event=self.receive(self.value(data=data));self.assertIsNone(event);self.assertEqual(response['data']['flags'],64)
        command={'name':'dbinspect','type':1,'options':[{'name':'text','value':'\t'}]}
        with self.assertRaises(APIError):self.receive(self.value(data=command,user={'id':'999999999'}))
        with self.assertRaises(APIError):self.receive(self.value(data=command,application_id='999999999'))
        value=self.value(data=command);body,headers=self.signed(value)
        with self.assertRaises(APIError):self.discord.receive(body+b' ',headers)
        options=self.bridge.options();self.bridge.configure(application_id=options['application_id'],public_key=options['public_key'],users='123456789',channels='222222222',enabled=True,expected_version=options['version'])
        with self.assertRaises(APIError):self.receive(self.value(data=command))

    def test_brief_private_controls_and_complete_file(self):
        row=self.draft()
        response,_=self.click(row,'brief')
        self.assertEqual(response['type'],7)
        row=self.bridge.get(row['id'],'discord:123456789')
        response,_=self.click(row,'briefedit')
        self.assertEqual(len(response['data']['components']),5)
        response,_=self.click(row,'brieffile',work=True)
        self.assertEqual(response['type'],6)
        payload,file=self.delivered[-1]
        self.assertEqual(payload['allowed_mentions'],{'parse':[]})
        self.assertEqual(file['filename'],'repro-brief.md')
        text=base64.b64decode(file['data']).decode('utf-8')
        self.assertNotIn('ASCII fish reef',text)
        self.assertIn('Unknown',text)

    def test_followup_review_save_and_cross_channel_inbox(self):
        row=self.draft();response,_=self.click(row,'followedit')
        self.assertEqual(response['type'],9)
        fields=[{'type':4,'custom_id':'note','value':'check later'},{'type':4,'custom_id':'excerpt','value':'reviewed excerpt'}]
        response,_=self.click(row,'followreview',kind=5,components=fields)
        self.assertIn('reviewed excerpt',str(response))
        row=self.bridge.get(row['id'],'discord:123456789')
        response,_=self.click(row,'followsave')
        self.assertIn('Captured excerpt (not live)',response['data']['content'])
        inbox=self.value(channel_id='222222222',data={'name':'dumbbridge','type':1,'options':[{'name':'inbox','value':True}]})
        response,_=self.receive(inbox)
        self.assertEqual(response['data']['flags'],64)
        self.assertIn('check later',str(response))
        self.assertNotIn('reviewed excerpt',str(response))
        self.assertIsNone(self.bridge.get(row['id'],'discord:123456789').get('followup_pending'))
        self.assertEqual(response['data']['allowed_mentions'],{'parse':[]})
        opts=self.bridge.options()
        self.bridge.configure(application_id=opts['application_id'],public_key=opts['public_key'],users='123456789',channels='987654321',enabled=True,expected_version=opts['version'])
        with self.assertRaises(APIError):self.receive(inbox)
        with self.assertRaises(APIError):self.discord.dispatch(self.value(channel_id='222222222',type=3,data={'custom_id':f'db:brief:{row["id"]}:{row["version"]}'}),'discord:123456789','222222222')

    def test_brief_scope_and_stale_edit_recovery(self):
        row=self.draft()
        # App and guild checks are additional to actor/current channel checks.
        stale_id=f'db:brief:{row["id"]}:{row["version"]}'
        response,_=self.receive(self.value(type=3,guild_id='444444444',data={'custom_id':stale_id}))
        self.assertIn('another app/server',response['data']['content'])
        self.bridge.mutate(row['id'],row['actor'],{'discord_app':'444444444'},row['version'])
        current=self.bridge.get(row['id'],row['actor'])
        response,_=self.click(current,'brief')
        self.assertIn('another app/server',response['data']['content'])
        row=self.bridge.mutate(row['id'],row['actor'],{'discord_app':'333333333'},current['version'])
        # A stale modal saves a separate recovery buffer, never overwrites current fields.
        self.bridge.mutate(row['id'],row['actor'],{'notice':'new edit'},row['version'])
        fields=[{'type':18,'component':{'type':4,'custom_id':'steps','value':'recovered\n'*140}}]
        response,_=self.click(row,'briefedited',kind=5,components=fields)
        current=self.bridge.get(row['id'],row['actor'])
        self.assertEqual(current['brief_recovery']['steps'],'recovered\n'*140)
        self.assertNotIn('steps',current.get('repro_brief',{}))
        self.click(current,'briefrecovery')
        payload,file=self.delivered[-1]
        self.assertIn('recovered\n',base64.b64decode(file['data']).decode())
        self.assertEqual(payload['allowed_mentions'],{'parse':[]})
        row=self.bridge.get(row['id'],row['actor'])
        self.click(row,'clearbriefrecovery');row=self.bridge.get(row['id'],row['actor'])
        self.assertIsNone(row['brief_recovery'])

    def test_followup_atomic_cleanup_private_receipts_and_recreation(self):
        row=self.draft()
        # Save and clear pending review in the same transaction. A failure rolls back both.
        fields=[{'type':18,'component':{'type':4,'custom_id':'note','value':'unique review note'}},
                {'type':18,'component':{'type':4,'custom_id':'excerpt','value':'unique reviewed private excerpt'}}]
        self.click(row,'followreview',kind=5,components=fields);row=self.bridge.get(row['id'],row['actor'])
        view=panel(self.bridge,row)
        labels=[c.get('label') for r in view['components'] for c in r['components']]
        self.assertNotIn('Stash as Itch',labels)
        original_put=self.bridge.manager.put
        def fail_draft(db,kind,record):
            if kind=='bridge_draft':raise APIError('Injected isolated rollback')
            return original_put(db,kind,record)
        with patch.object(self.bridge.manager,'put',side_effect=fail_draft):
            response,_=self.click(row,'followsave')
            self.assertIn('Injected isolated rollback',response['data']['content'])
        with self.bridge.manager.db() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM bridge_followups').fetchone()[0],0)
        self.assertIsNotNone(self.bridge.get(row['id'],row['actor'])['followup_pending'])
        self.click(row,'followsave')
        self.assertIsNone(self.bridge.get(row['id'],row['actor'])['followup_pending'])
        with self.bridge.manager.db() as db:
            saved=json.loads(db.execute('SELECT data FROM bridge_followups').fetchone()[0])
            replay=''.join(r[0] for r in db.execute('SELECT response FROM bridge_events'))
            self.assertNotIn('unique reviewed private excerpt',replay)
        delete=f'fi:delete:{saved["id"]}:{saved["version"]}'
        self.receive(self.value(type=3,data={'custom_id':delete}))
        with self.bridge.manager.db() as db:
            all_data=''.join(r[0] for r in db.execute('SELECT data FROM records'))+''.join(r[0] for r in db.execute('SELECT response FROM bridge_events'))
            self.assertNotIn('unique reviewed private excerpt',all_data)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM bridge_followups').fetchone()[0],0)
        # Recreating a bookmark creates a new identity, so prior controls cannot affect it.
        row=self.bridge.get(row['id'],row['actor']);self.click(row,'followreview',kind=5,components=fields)
        row=self.bridge.get(row['id'],row['actor']);self.click(row,'followsave')
        with self.bridge.manager.db() as db:new=json.loads(db.execute('SELECT data FROM bridge_followups').fetchone()[0])
        self.assertNotEqual(new['id'],saved['id'])
        response,_=self.receive(self.value(type=3,data={'custom_id':delete}))
        self.assertIn('not found',response['data']['content'])

    def test_native_signature_rejects_tampering_wrong_key_and_stale_time(self):
        body,headers=self.signed(self.value(type=1))
        self.assertTrue(verify(self.public,headers['X-Signature-Ed25519'],headers['X-Signature-Timestamp'],body))
        for key,sig,stamp,content in [
            (self.public,headers['X-Signature-Ed25519'],headers['X-Signature-Timestamp'],body+b' '),
            ('ab'*32,headers['X-Signature-Ed25519'],headers['X-Signature-Timestamp'],body),
            (self.public,'00'*64,headers['X-Signature-Timestamp'],body),
            (self.public,'zz',headers['X-Signature-Timestamp'],body)]:
            self.assertFalse(verify(key,sig,stamp,content))
        expired=self.signed(self.value(type=1),str(int(time.time())-601))
        with self.assertRaises(APIError) as cm:self.discord.receive(*expired)
        self.assertEqual(cm.exception.status,401)

    def test_ping_initial_ack_and_access_control_are_real_and_fast(self):
        body,headers=self.signed(self.value(type=1))
        start=time.monotonic();response,event=self.discord.receive(body,headers)
        self.assertLess(time.monotonic()-start,3);self.assertEqual(response,{'type':1});self.assertIsNone(event)
        self.assertIsNotNone(self.bridge.status()['last_verified_interaction'])
        for changes in [{'application_id':'444444444'},{'user':{'id':'777777777'}}]:
            with self.assertRaises(APIError) as cm:self.receive(self.value(**changes))
            self.assertEqual(cm.exception.status,403)
        settings=self.bridge.options()
        self.bridge.configure(application_id='333333333',public_key=self.public,users='123456789',channels='555555555',enabled=True,expected_version=settings['version'])
        with self.assertRaises(APIError):self.receive(self.value())

    def test_database_contention_returns_private_recovery_before_discord_deadline(self):
        body,headers=self.signed(self.value())
        with self.bridge.manager.db() as db:
            db.execute('BEGIN IMMEDIATE')
            started=time.monotonic();response,event=self.discord.receive(body,headers)
        self.assertLess(time.monotonic()-started,3)
        self.assertEqual(response['type'],4);self.assertEqual(response['data']['flags'],64)
        self.assertIn('busy',response['data']['content']);self.assertIsNone(event)

    def test_draft_lock_contention_also_acknowledges_before_deadline(self):
        from dumbapi_core.bridge import _LOCKS
        acquired=threading.Event();release=threading.Event()
        def hold():
            for lock in _LOCKS:lock.acquire()
            acquired.set();release.wait(5)
            for lock in reversed(_LOCKS):lock.release()
        worker=threading.Thread(target=hold);worker.start();self.assertTrue(acquired.wait(2))
        try:
            body,headers=self.signed(self.value());started=time.monotonic()
            response,event=self.discord.receive(body,headers)
            self.assertLess(time.monotonic()-started,3);self.assertIn('busy',response['data']['content'])
            self.assertIsNone(event)
        finally:release.set();worker.join(timeout=5)

    def test_disabling_bridge_cancels_a_queued_write(self):
        row=self.draft();response,event=self.click(row,'save',work=False)
        options=self.bridge.options()
        self.bridge.configure(application_id=options['application_id'],public_key=options['public_key'],
            users='123456789',enabled=False,expected_version=options['version'])
        self.discord.work(event)
        current=self.bridge.get(row['id'],row['actor'])
        self.assertEqual(current['itch_id'],'');self.assertEqual(current.get('notice'),row.get('notice'))

    def test_native_context_message_and_slash_replay_keep_private_source(self):
        value=self.value(data={'type':3,'name':'DumbBridge','target_id':'222222222','resolved':{'messages':{
            '222222222':{'id':'222222222','content':'Selected idea, with its author.', 'author':{'id':'555555555'},
                         'timestamp':'2026-10-22T12:00:00Z','attachments':[]}}}})
        body,headers=self.signed(value)
        response,event=self.discord.receive(body,headers)
        self.assertEqual(response['type'],4);self.assertEqual(response['data']['flags'],64)
        duplicate,again=self.discord.receive(body,headers)
        self.assertEqual(duplicate,response);self.assertIsNone(again)
        with self.bridge.manager.db() as db:
            saved=db.execute('SELECT * FROM bridge_events WHERE id=?',(value['id'],)).fetchone()
        self.assertNotIn(value['token'],saved['secret']);self.assertNotIn(value['token'],saved['task'])
        self.discord.work(event)
        row_id=response['data']['components'][0]['components'][0]['custom_id'].split(':')[2]
        row=self.bridge.get(row_id,'discord:123456789')
        self.assertEqual(row['source']['author_id'],'555555555')
        self.assertIn('/222222222',row['source']['url'])
        with self.assertRaises(APIError):self.receive({**value,'data':{**value['data'],'target_id':'bogus'}})

    def test_modal_edit_save_and_project_flow_use_latest_versions(self):
        row=self.draft();reply,event=self.click(row,'edit')
        self.assertEqual(reply['type'],9);self.assertEqual(reply['data']['components'][0]['type'],18)
        components=[{'type':18,'component':{'type':4,'custom_id':k,'value':v}} for k,v in
                    [('title','An ASCII reef'),('observation','Fish need a home'),('goal','A lively reef'),('why','Inferred: clearer navigation'),('questions','')]]
        edited,event=self.click(row,'edited',kind=5,components=components)
        current=self.bridge.get(row['id'],row['actor']);self.assertEqual(current['title'],'An ASCII reef')
        self.assertEqual(edited['type'],7)
        self.click(current,'projects');current=self.bridge.get(row['id'],row['actor'])
        self.assertEqual(current['panel'],'projects')
        self.click(current,'project',['fish']);current=self.bridge.get(row['id'],row['actor'])
        self.assertEqual(current['project'],'fish')
        self.click(current,'save');saved=self.bridge.get(row['id'],row['actor'])
        self.assertTrue(saved['itch_id']);self.assertEqual(saved['status'],'stashed')
        stale,event=self.click(row,'save');self.assertEqual(stale['type'],7);self.assertIsNone(event)
        itch=self.bridge.manager.call('manager.get',{'id':saved['itch_id']})
        self.assertEqual(itch['state'],'open');self.assertEqual(itch['desired_outcome'],'A lively reef')

    def test_thread_search_remembers_exact_destination_and_explicit_send(self):
        row=self.draft();thread='mcp:12345678-1234-4234-8234-123456789abc'
        with patch('dumbapi_core.t3.T3.threads',return_value={'items':[{'id':thread,'title':'Daily scout'}]}),\
             patch('dumbapi_core.t3.T3.read',return_value={'thread':{'id':thread,'title':'Daily scout'},'messages':[]}),\
             patch('dumbapi_core.t3.T3.send',return_value={'sent':True}) as send:
            self.click(row,'threads');row=self.bridge.get(row['id'],row['actor'])
            self.click(row,'thread',[thread]);row=self.bridge.get(row['id'],row['actor'])
            self.assertEqual(row['thread_id'],thread);send.assert_not_called()
            self.click(row,'send');row=self.bridge.get(row['id'],row['actor'])
            self.assertEqual(send.call_args.args[0],thread);self.assertEqual(row['status'],'sent')
            self.click(row,'replies');row=self.bridge.get(row['id'],row['actor'])
            self.assertIn('No assistant reply',row['t3_reply'])

    def test_stop_is_immediate_without_waiting_for_workers_or_renderer(self):
        row=self.draft();row=self.bridge.mutate(row['id'],row['actor'],{'panel':'research','status':'research'})
        # No queue task is returned: cancellation cannot sit behind a running render/read.
        response,event=self.click(row,'cancel',work=False)
        self.assertEqual(response['type'],7);self.assertIsNone(event)
        current=self.bridge.get(row['id'],row['actor']);self.assertTrue(current['cancelled'])

    def test_payload_budget_modes_and_mentions(self):
        row=self.draft();row.update(title='t'*240,observation='o'*1500,goal='g'*1500,why='w'*1500,questions='q'*1500,notice='n'*600)
        row['related']=[{'id':str(i),'title':'r'*180,'state':'open','basis':'word_overlap'} for i in range(5)]
        for mode in ['menu','projects','threads','related','research','chat']:
            with self.subTest(mode=mode):
                row['panel']=mode;payload=panel(self.bridge,row)
                self.assertEqual(payload['allowed_mentions'],{'parse':[]});self.assertLessEqual(len(payload['components']),5)
                embed=payload['embeds'][0];size=len(embed['title'])+len(embed['description'])+len(embed['footer']['text'])
                size+=sum(len(f['name'])+len(f['value']) for f in embed['fields'])
                self.assertLess(size,6000);self.assertTrue(all(len(f['value'])<=1024 for f in embed['fields']))

    def test_multipart_gif_uses_exact_bytes_and_original_private_reply(self):
        row=self.draft();data=b'GIF89a-unit-fixture;'
        card={'filename':'dumbbridge-fixture.gif','mime':'image/gif','data':base64.b64encode(data).decode()}
        value=self.value();response,event=self.receive(value)
        with self.bridge.manager.db() as db:hit=db.execute('SELECT * FROM bridge_events WHERE id=?',(event,)).fetchone()
        self.delivery_patch.stop()
        try:
            with patch('dumbapi_core.discord_bridge.remote',return_value=b'{}') as remote:
                self.discord.deliver(hit,panel(self.bridge,row,card),card)
            args=remote.call_args
            self.assertIn('/messages/@original',args.args[0]);self.assertEqual(args.kwargs['method'],'PATCH')
            self.assertIn(data,args.kwargs['body']);self.assertIn(b'attachment://dumbbridge-fixture.gif',args.kwargs['body'])
            self.assertIn('multipart/form-data',args.kwargs['headers']['Content-Type'])
        finally:self.delivery_patch.start()

    def test_registration_previews_without_network_and_upserts_only_named_commands(self):
        with patch('dumbapi_core.discord_bridge.remote',side_effect=AssertionError('No call during preview')):
            preview=register(self.bridge);self.assertFalse(preview['registered']);self.assertIn('integration_type=1',preview['install_url'])
        def reply(url,**kwargs):
            command=json.loads(kwargs['body']);return json.dumps({'id':'123456789','name':command['name']}).encode()
        with patch('dumbapi_core.discord_bridge.BotKey.load',return_value='unit-fixture'),patch('dumbapi_core.discord_bridge.remote',side_effect=reply) as remote:
            result=register(self.bridge,True)
        self.assertTrue(result['registered']);self.assertEqual(remote.call_count,4)
        self.assertTrue(all(c.kwargs['method']=='POST' for c in remote.call_args_list))

    def test_outbound_requests_identify_client_for_commands_and_interaction_replies(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        received=[]
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body=self.rfile.read(int(self.headers.get('Content-Length',0)))
                received.append({'agent':self.headers.get('User-Agent'),
                    'authorization':self.headers.get('Authorization'),
                    'content_type':self.headers.get('Content-Type'),'body':body})
                self.send_response(200);self.end_headers();self.wfile.write(b'{}')
            do_PATCH=do_POST
            def log_message(self,*args):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            url=f'http://127.0.0.1:{server.server_port}/commands'
            for method in ['POST','PATCH']:
                remote(url,method=method,body=b'{"name":"DumbBridge"}',
                    headers={'Authorization':'Bot unit-fixture','Content-Type':'application/json'})
            self.assertEqual(len(received),2)
            for request in received:
                self.assertRegex(request['agent'],r'^DiscordBot \(https?://[^,]+, [^)]+\) DumbBridge$')
                self.assertEqual(request['authorization'],'Bot unit-fixture')
                self.assertEqual(request['content_type'],'application/json')
                self.assertEqual(json.loads(request['body']),{'name':'DumbBridge'})
        finally:server.shutdown();server.server_close();thread.join(timeout=5)

    def test_dedicated_http_listener_exposes_only_signed_interactions(self):
        from dumbbridge import make_server
        server=make_server(0,self.bridge.config);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            address=f'http://127.0.0.1:{server.server_port}'
            with urlopen(address+'/health') as response:self.assertTrue(json.load(response)['listener'])
            with self.assertRaises(HTTPError) as cm:urlopen(address+'/api/call')
            self.assertEqual(cm.exception.code,404)
            cm.exception.close()
            with self.assertRaises(HTTPError) as cm:urlopen(Request(address+'/interactions',data=b'{}',method='POST'))
            self.assertEqual(cm.exception.code,401)
            cm.exception.close()
            body,headers=self.signed(self.value(type=1))
            with urlopen(Request(address+'/interactions',data=body,headers=headers,method='POST')) as response:
                self.assertEqual(json.load(response),{'type':1})
        finally:server.shutdown();server.server_close();server.discord.close();thread.join(timeout=5)


    def test_queued_revocation_returns_no_private_draft(self):
        with patch.object(self.discord,'queue_card'):row=self.draft()
        before=dict(row)
        self.delivered.clear()
        _,event=self.click(row,'brieffile',work=False)
        options=self.bridge.options();self.bridge.configure(application_id=options['application_id'],public_key=options['public_key'],users='222222222',enabled=True,expected_version=options['version'])
        self.discord.work(event)
        self.assertEqual(self.delivered,[])
        self.assertEqual(self.bridge.get(row['id'],row['actor']),before)
        with self.bridge.manager.db() as db:
            receipt=db.execute('SELECT state,secret FROM bridge_events WHERE id=?',(event,)).fetchone()
        self.assertEqual(receipt['state'],'done');self.assertIsNone(receipt['secret'])

    def test_queued_card_revocation_skips_render_and_delivery(self):
        with patch.object(self.discord,'queue_card'):row=self.draft()
        self.delivered.clear()
        with self.bridge.manager.db() as db:
            event=db.execute("SELECT * FROM bridge_events WHERE task IS NOT NULL ORDER BY rowid LIMIT 1").fetchone()
        options=self.bridge.options();self.bridge.configure(application_id=options['application_id'],public_key=options['public_key'],users='123456789',channels='222222222',enabled=True,expected_version=options['version'])
        self.discord.card_queue[row['id']]=(event,row['actor'],row['version'],time.monotonic())
        self.discord.render_cards()
        self.assertEqual(self.delivered,[])

    def test_stale_and_deleted_note_submissions_return_private_recovery(self):
        from dumbapi_core.bridge_followups import save,change,get
        row=self.draft()
        with self.bridge.manager.db() as db:
            item=save(db,'333333333',row['actor'],row,{'note':'before','excerpt':'private capture'})
            change(db,'333333333',row['actor'],item['id'],item['version'],'done')
        note='keep my note ~~~ @everyone'
        def submit():
            return self.receive(self.value(type=5,data={'custom_id':f'fi:edited:{item["id"]}:{item["version"]}',
                'components':[{'type':4,'custom_id':'note','value':note}]}))[0]
        response=submit()
        self.assertEqual(response['type'],4);self.assertEqual(response['data']['flags'],64)
        self.assertEqual(response['data']['allowed_mentions'],{'parse':[]})
        self.assertIn(note,response['data']['embeds'][0]['description'])
        with self.bridge.manager.db() as db:
            current=get(db,'333333333',row['actor'],item['id']);self.assertEqual(current['note'],'before')
            change(db,'333333333',row['actor'],item['id'],current['version'],'delete')
        response=submit();self.assertIn(note,response['data']['embeds'][0]['description'])
        with self.bridge.manager.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM bridge_followups').fetchone()[0],0)
            self.assertNotIn(note,' '.join(x[0] for x in db.execute('SELECT response FROM bridge_events')))

if __name__=='__main__':unittest.main()
