"""Disposable first-run host smoke. Never reads real runtime storage."""
import http.client
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'backend')]

def main():
    with tempfile.TemporaryDirectory() as temp:
        base=Path(temp)
        os.environ['DUMBMANAGER_DATA_DIR']=str(base/'manager')
        os.environ['DUMBAPI_DATA_DIR']=str(base/'api')
        from app import make_server
        from dumbapi_core.common import Config
        server=make_server(0,Config(base,base/'api'))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        def req(path,value=None,headers=None):
            c=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=10)
            c.request('GET' if value is None else 'POST',path,None if value is None else json.dumps(value),headers or {})
            r=c.getresponse();out=(r.status,dict(r.getheaders()),r.read());c.close();return out
        try:
            status,headers,body=req('/')
            assert status==200 and b'DumbManager' in body
            auth={'Cookie':headers['Set-Cookie'].split(';')[0],'X-DumbManager':'1','Content-Type':'application/json'}
            assert req('/api/call',{'name':'manager.state','args':{} })[0]==403
            def call(name,args=None):
                status,_,body=req('/api/call',{'name':name,'args':args or {}},auth)
                assert status==200,(name,status)
                return json.loads(body)
            state=call('manager.state');assert state['itches']==[] and state['contexts']==[]
            assert not call('workspace.status')['configured']
            assert call('projects.list')['items']==[]
            folder=base/'Example Workspace';folder.mkdir();(folder/'README.md').write_text('Synthetic workspace only.')
            call('workspace.configure',{'path':str(folder)})
            assert len(call('projects.list')['items'])==1
            row=call('manager.capture',{'title':'Keep the little fix','project':'example-workspace','use_active':False})
            assert row['state']=='open'
            assert not call('manager.typing_status')['configured']
            for asset in ('/app.js','/social.js','/inspiration.js','/fonts/IBMPlexMono.ttf','/ascii-smoke.js'):
                assert req(asset)[0]==200,asset
            call('workspace.configure',{'path':''});assert call('projects.list')['items']==[]
            report={'fresh_empty_state':True,'auth_boundary':True,'workspace_select_clear':True,'itch_capture':True,'assets_served':True,'providers_contacted':False}
            out=ROOT/'dist';out.mkdir(exist_ok=True)
            (out/'first-run-checks.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
            print(json.dumps(report))
        finally:
            server.shutdown();server.replay.disarm();server.server_close();thread.join()
if __name__=='__main__':main()
