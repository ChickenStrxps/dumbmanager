"""Exercise the actual packaged UI after its short-lived launcher exits."""
import http.cookiejar
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
def main():
    exe=ROOT/'dist'/'DumbManager.exe'
    report={'signed':False,'clean_machine_tested':False,'live_integrations_tested':False,'success':False}
    errors=[];external=[]
    with tempfile.TemporaryDirectory() as temp:
        base=Path(temp);env={**os.environ,'DUMBAPI_DATA_DIR':str(base/'api'),'DUMBMANAGER_DATA_DIR':str(base/'manager')}
        origin='http://127.0.0.1:8783'
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        try:
            start=subprocess.run([str(exe),'--no-open','--no-native'],env=env,capture_output=True,text=True,timeout=45)
            report['start_exit']=start.returncode
            assert start.returncode==0,(start.stdout,start.stderr)
            with opener.open(origin+'/health',timeout=10) as response:health=json.load(response)
            assert health['name']=='DumbManager';report['health']=True
            # The launcher is already gone: every resource must still be present.
            assets=['/','/app.js','/t3-settings.js','/style.css','/fonts/IBMPlexMono.ttf','/ascii-smoke.js']
            for path in assets:
                with opener.open(origin+path,timeout=10) as response:assert response.status==200,path
            report['assets']=assets
            with sync_playwright() as p:
                browser=p.chromium.launch(channel='msedge',headless=True)
                page=browser.new_page(viewport={'width':1280,'height':900},reduced_motion='reduce')
                page.on('pageerror',lambda error:errors.append(str(error)))
                page.route('**/*',lambda route:route.continue_() if route.request.url.startswith((origin,'data:','blob:')) else (external.append(route.request.url),route.abort())[-1])
                page.goto(origin);page.wait_for_function("()=>typeof appReady!=='undefined'&&appReady",timeout=45000)
                assert page.locator('#workspace-path').is_visible()
                project=base/'Packaged Example';project.mkdir()
                page.locator('#workspace-path').fill(str(project))
                with page.expect_navigation():page.locator('#workspace-form button[type=submit]').click()
                page.wait_for_function("()=>typeof appReady!=='undefined'&&appReady",timeout=45000)
                page.locator('[data-view=now]').first.click()
                page.locator('#command').fill('Keep an itch in the packaged app')
                page.locator('#stash').click();page.wait_for_function('()=>state.itches.length===1')
                page.reload();page.wait_for_function("()=>typeof appReady!=='undefined'&&appReady")
                assert page.evaluate('state.itches.length')==1
                page.screenshot(path=str(ROOT/'dist'/'frozen-window.png'),full_page=True)
                assert not errors,errors
                browser.close()
            report.update(packaged_workspace_select=True,packaged_stash_reload=True,javascript_errors=errors,external_requests_blocked=len(external),success=True)
        finally:
            stop=subprocess.run([str(exe),'stop'],env=env,capture_output=True,text=True,timeout=30)
            report['stop_exit']=stop.returncode
            (ROOT/'dist'/'BUILD-VALIDATION.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
            assert stop.returncode==0,(stop.stdout,stop.stderr)
            for _ in range(100):
                try:
                    with opener.open(origin+'/health',timeout=.5):pass
                except (OSError,urllib.error.URLError):break
                time.sleep(.1)
            else:raise AssertionError('Packaged host did not stop')
    print(json.dumps(report))
if __name__=='__main__':main()
