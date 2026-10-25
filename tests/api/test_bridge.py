import base64
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from dumbapi_core.app import App
from dumbapi_core.bridge import Bridge
from dumbapi_core.common import APIError, Config
from dumbapi_core.manager import Manager


class BridgeTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();base=Path(self.temp.name)
        hub=base/'projects/DumbAPI';hub.mkdir(parents=True);(hub.parent/'Fish').mkdir()
        (hub/'settings.json').write_text(json.dumps({'projects_root':'..'}))
        self.config=Config(hub,base/'data');self.bridge=Bridge(self.config);self.manager=self.bridge.manager
        self.actor='discord:123456789';self.serial=0

    def tearDown(self):self.temp.cleanup()

    def draft(self,**overrides):
        self.serial+=1
        source={'platform':'discord','channel_id':'987654321','text':'Let fish swim through an ASCII reef.',
                'url':'https://discord.com/channels/@me/987654321/123456789','message_id':'123456789',**overrides}
        return self.bridge.create(source,self.actor,'event-'+str(self.serial))

    def test_registry_uses_real_shared_operations_and_configuration_is_offline(self):
        app=App(self.config)
        self.assertFalse(app.call('bridge.status')['configured'])
        with patch('dumbapi_core.bridge.remote',side_effect=AssertionError('No network')):
            result=app.call('bridge.configure',{'application_id':'123456789','public_key':'ab'*32,
                'users':'123456789,123456789','expected_version':0,'enabled':True})
            self.assertEqual(result['users'],['123456789']);self.assertEqual(result['version'],1)
        self.assertNotIn('bot_token',result)
        with self.assertRaises(APIError):self.bridge.configure(expected_version=0)
        self.assertEqual(app.call('bridge.discord.commands')['commands'][0]['type'],3)

    def test_immutable_source_event_identity_owner_and_bad_attachments(self):
        row=self.draft(text=' One\nTwo ')
        self.assertEqual(row['source']['text'],' One\nTwo ')
        source=dict(row['source'])
        again=self.bridge.create(source,self.actor,'event-1');self.assertEqual(again,row)
        with self.assertRaises(APIError):self.bridge.create({**source,'text':'Changed'},self.actor,'event-1')
        with self.assertRaises(APIError):self.bridge.get(row['id'],'discord:111111111')
        changed=self.bridge.edit(row['id'],self.actor,{'title':'Readable title'},row['version'])
        self.assertEqual(changed['source'],source)
        with self.assertRaises(APIError):self.bridge.edit(row['id'],self.actor,{'goal':'Stale'},row['version'])
        for url in ['http://cdn.discordapp.com/attachments/a','https://127.0.0.1/attachments/a',
                    'https://cdn.discordapp.com.evil.test/attachments/a','https://cdn.discordapp.com/not-attachments/a']:
            with self.subTest(url=url),self.assertRaises(APIError):self.draft(attachments=[{'url':url}])

    def test_choices_persist_per_user_channel_without_selecting_context(self):
        row=self.draft()
        exact='mcp:12345678-1234-4234-8234-123456789abc'
        with patch('dumbapi_core.t3.T3.read',return_value={'thread':{'id':exact,'title':'Daily scout'}}):
            self.bridge.bind(row['id'],self.actor,project='fish',thread_id=exact)
        restored=Bridge(self.config).create({**row['source'],'message_id':'222222222'},self.actor,'next')
        self.assertEqual((restored['project'],restored['thread_id']),('fish',exact))
        self.assertEqual(self.draft(channel_id='111111111')['thread_id'],'')
        with self.manager.db() as db:self.assertIsNone(self.manager.setting(db,'active_context',None))

    def test_generation_cannot_overwrite_a_newer_manual_edit(self):
        row=self.draft()
        def response(config,old):
            self.bridge.edit(old['id'],self.actor,{'title':'My words'},old['version'])
            return {'title':'Late AI','generation':'mercury'}
        with patch('dumbapi_core.bridge_ai.intake',response),self.assertRaises(APIError):
            self.bridge.generate(row['id'],self.actor)
        self.assertEqual(self.bridge.get(row['id'],self.actor)['title'],'My words')
        with patch('dumbapi_core.typing_generator.settings',return_value={'provider':'off'}):
            untouched=self.draft();generated=self.bridge.generate(untouched['id'],self.actor)
        self.assertEqual(generated['generation'],'original_only')
        self.assertEqual(generated['source'],untouched['source'])

    def test_stash_recovers_both_lost_responses_without_duplicate_itches(self):
        for fail_on in ['manager.capture','manager.update']:
            with self.subTest(fail_on=fail_on):
                row=self.draft(text='Original details. '*200)
                row=self.bridge.edit(row['id'],self.actor,{'goal':'A usable reef','why':'Inferred: easier navigation'},row['version'])
                original_call=self.manager.call;lost=[False]
                def drop_response(name,args):
                    result=original_call(name,args)
                    if name==fail_on and not lost[0]:lost[0]=True;raise APIError('Connection lost','unavailable',503)
                    return result
                with patch.object(self.manager,'call',drop_response),self.assertRaises(APIError):
                    self.bridge.stash(row['id'],self.actor,row['version'])
                kept=self.bridge.get(row['id'],self.actor)
                with self.assertRaises(APIError):self.bridge.edit(row['id'],self.actor,{'title':'Different'},kept['version'])
                saved=self.bridge.stash(row['id'],self.actor,kept['version'])
                itch=original_call('manager.get',{'id':saved['itch_id']})
                self.assertEqual(itch['state'],'open');self.assertEqual(itch['desired_outcome'],'A usable reef')
                self.assertEqual(len(saved['source']['text']),len(row['source']['text']))
                markers=[e for e in itch['evidence'] if e.get('type')=='bridge_intake']
                self.assertEqual(len(markers),1)
                self.assertEqual(self.bridge.stash(row['id'],self.actor,saved['version'])['itch_id'],saved['itch_id'])
        with self.manager.db() as db:self.assertEqual(self.manager.op_list(db,limit=100)['total'],2)

    def test_attachment_failure_keeps_source_and_success_reuses_retained_media(self):
        row=self.draft(attachments=[{'id':'123','url':'https://cdn.discordapp.com/attachments/a/b.png','filename':'image.png','content_type':'image/png'}])
        with patch('dumbapi_core.bridge.remote',side_effect=OSError()),self.assertRaises(APIError):
            self.bridge.stash(row['id'],self.actor,row['version'])
        self.assertEqual(self.bridge.get(row['id'],self.actor)['source'],row['source'])
        with patch('dumbapi_core.bridge.remote',return_value=b'png'),patch('dumbapi_core.manager_media.Media.upload',return_value={'attachment':{'id':'media-1'}}) as upload:
            current=self.bridge.get(row['id'],self.actor)
            retained=self.bridge.import_media(current);self.bridge.import_media(retained)
        self.assertEqual(upload.call_count,1)

    def test_t3_send_freezes_content_destination_and_stable_retry(self):
        row=self.draft();thread='12345678-1234-4234-8234-123456789abc'
        with patch('dumbapi_core.t3.T3.read',return_value={'thread':{'id':thread,'title':'Exact thread'}}):
            row=self.bridge.bind(row['id'],self.actor,thread_id=thread)
            calls=[]
            def send(*args):
                calls.append(args)
                if len(calls)==1:raise APIError('Response lost','unavailable',503)
                return {'sent':True,'thread_id':thread}
            with patch('dumbapi_core.t3.T3.send',side_effect=send):
                with self.assertRaises(APIError):self.bridge.send(row['id'],self.actor,row['version'])
                current=self.bridge.get(row['id'],self.actor)
                with self.assertRaises(APIError):self.bridge.bind(row['id'],self.actor,thread_id=thread)
                with self.assertRaises(APIError):self.bridge.edit(row['id'],self.actor,{'title':'Changed'},current['version'])
                done=self.bridge.send(row['id'],self.actor,current['version'])
                self.bridge.send(row['id'],self.actor,done['version'])
            self.assertEqual(calls[0],calls[1]);self.assertEqual(len(calls),2)
            self.assertEqual(done['status'],'sent')

    def test_related_retrieval_and_link_preserve_state_and_do_not_merge(self):
        itch=self.manager.call('manager.capture',{'title':'ASCII reef fish navigation','use_active':False})
        row=self.draft()
        with patch('dumbapi_core.bridge_ai.ask',return_value=None):row=self.bridge.related(row['id'],self.actor)
        self.assertEqual(row['related'][0]['id'],itch['id'])
        self.assertEqual(row['related'][0]['basis'],'word_overlap')
        linked=self.bridge.link(row['id'],self.actor,itch['id']);self.bridge.link(row['id'],self.actor,itch['id'])
        after=self.manager.call('manager.get',{'id':itch['id']})
        self.assertEqual(after['state'],itch['state'])
        self.assertEqual(sum(e.get('bridge_id')==row['id'] for e in after['evidence']),1)
        self.assertEqual(linked['status'],'linked')

    def test_research_pauses_for_review_in_an_isolated_browser_and_is_cancellable(self):
        from dumbapi_core import bridge_research
        row=self.draft();instances=[]
        class Browser:
            def __init__(self,config):self.suggestion=None;self.observed={};self.applied=[];self.stopped=False;instances.append(self)
            def status(self):return {'running':False}
            def start(self,url):pass
            def snapshot(self):self.observed={'url':'https://example.org/source','title':'Real observed page','text':'Observed excerpt'};return {'snapshot':'s1'}
            def plan(self,*args):
                if not self.applied:
                    self.suggestion={'id':'review','label':'Submit search','needs_review':True,'action':True};return self.suggestion
                return {'label':'Source says what it supports.','action':False}
            def apply(self,id,reviewed=False):self.applied.append((id,reviewed))
            def stop(self):self.stopped=True
        try:
            with patch('dumbapi_core.browser.Browser',Browser):
                paused=self.bridge.research(row['id'],self.actor)
                self.assertTrue(paused['research']['needs_review']);self.assertEqual(instances[0].applied,[])
                done=self.bridge.research(row['id'],self.actor,True)
                self.assertEqual(instances[0].applied,[('review',True)])
                self.assertEqual(done['research']['sources'][0]['url'],'https://example.org/source')
                self.assertTrue(instances[0].stopped);self.assertEqual(len(instances),1)
                def cancel_during_plan(*args):
                    self.bridge.mutate(row['id'],self.actor,{'cancelled':True,'status':'cancelled'})
                    return {'id':'unsafe-after-stop','label':'Click','action':True}
                with patch.object(Browser,'plan',cancel_during_plan):self.bridge.research(row['id'],self.actor)
                self.assertEqual(instances[1].applied,[]);self.assertTrue(instances[1].stopped)
        finally:bridge_research.cancel(self.bridge,row['id'])

    def test_cards_use_truthful_brand_state_dense_renderer_cache_and_still_fallback(self):
        row=self.draft();calls=[]
        def render(folder,payload,vibe,force,**kwargs):
            calls.append((payload,force,kwargs))
            if not kwargs.get('still'):raise APIError('Render unavailable')
            return b'\x89PNG\r\n\x1a\nfixture',{'width':1200,'height':675,'frames':1,'seconds':0}
        with patch('dumbapi_core.bridge_cards.draw',render):
            card=self.bridge.card(row['id'],self.actor)
            self.bridge.mutate(row['id'],self.actor,{'notice':'Text update'})
            cached=self.bridge.card(row['id'],self.actor)
        self.assertFalse(card['animated']);self.assertEqual(len(calls),2)
        self.assertEqual(calls[0][0]['brand'],'DUMBBRIDGE');self.assertEqual(calls[0][0]['stage'],'draft')
        self.assertIsNone(calls[0][0]['image']);self.assertNotIn('lightning',calls[0][1]['events'])
        self.assertEqual(cached['draft_version'],row['version']+1)
        self.assertTrue(base64.b64decode(card['data']).startswith(b'\x89PNG'))


if __name__=='__main__':unittest.main()
