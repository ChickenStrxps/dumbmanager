"""Synthetic public navigation check using installed Edge on a hosted worker."""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'backend')]
from playwright.sync_api import sync_playwright

def main():
    with tempfile.TemporaryDirectory() as temp:
        base=Path(temp);os.environ['DUMBMANAGER_DATA_DIR']=str(base/'manager');os.environ['DUMBAPI_DATA_DIR']=str(base/'api')
        from app import make_server
        from dumbapi_core.common import Config
        from dumbapi_core.app import App
        config=Config(base,base/'api');server=make_server(0,config)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        errors=[];requests=[]
        try:
            with sync_playwright() as p:
                browser=p.chromium.launch(channel='msedge',headless=True)
                context=browser.new_context(viewport={'width':1280,'height':900},reduced_motion='reduce')
                page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
                origin='http://127.0.0.1:'+str(server.server_port)
                page.route('**/*',lambda route:route.continue_() if route.request.url.startswith((origin,'data:','blob:')) else (requests.append(route.request.url),route.abort())[-1])
                page.goto(origin);page.wait_for_function("()=>typeof appReady!=='undefined'&&appReady",timeout=45000)
                assert page.locator('#workspace-path').is_visible()
                folder=base/'Demo Workspace';folder.mkdir();(folder/'README.md').write_text('Synthetic source.')
                page.locator('#workspace-path').fill(str(folder));page.locator('#workspace-form button[type=submit]').click()
                page.wait_for_function("()=>typeof appReady!=='undefined'&&appReady")
                page.locator('[data-view=now]').first.click()
                page.locator('#command').fill('Keep the panel open after saving')
                page.locator('#stash').click()
                page.wait_for_function('()=>state.itches.length===1')
                page.locator('[data-view=tools]').first.click()
                tabs=page.locator('[data-tool-tab]').all_text_contents()
                assert tabs==['Inspiration','Social'],tabs
                assert not page.locator('[data-tool-tab=stats],[data-tool-tab=batches],[data-tool-tab=queue]').count()
                page.locator('[data-tool-tab=social]').click()
                page.locator('[data-tool-tab=inspiration]').click()
                page.reload();page.wait_for_function("()=>typeof appReady!=='undefined'&&appReady")
                assert page.locator('[data-tool-tab=inspiration]').get_attribute('aria-selected')=='true'
                (ROOT/'dist').mkdir(exist_ok=True)
                for width in (1280,390,320):
                    page.set_viewport_size({'width':width,'height':900})
                    page.wait_for_timeout(150)
                    assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth+1'),width
                    page.screenshot(path=str(ROOT/'dist'/('navigation-'+str(width)+'.png')),full_page=True)
                assert not errors,errors
                browser.close()
            report={'first_run_workspace':True,'itch_stash':True,'public_tabs':tabs,'reload':True,'viewport_widths':[1280,390,320],'javascript_errors':errors,'external_requests_blocked':len(requests),'live_integrations_tested':False}
            (ROOT/'dist'/'browser-checks.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
            print(json.dumps(report))
        finally:
            server.shutdown();server.replay.disarm();server.server_close();thread.join()
if __name__=='__main__':main()
