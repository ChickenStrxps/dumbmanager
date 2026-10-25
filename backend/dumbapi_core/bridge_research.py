"""Bounded, cancellable research. Each draft owns an isolated Browser object."""
import atexit
import json
import threading
import time
from .common import APIError

_sessions, _lock = {}, threading.RLock()


def cancel(bridge,id):
    with _lock: session=_sessions.pop((str(bridge.config.data),id),None)
    if session:
        session['browser'].stop()
        atexit.unregister(session['browser'].stop)


def run(bridge,id,actor,reviewed=False,progress=None):
    from .browser import Browser
    row=bridge.get(id,actor);key=(str(bridge.config.data),id)
    with _lock:
        # Paused sessions expire; never retain a permanent research browser.
        for old,value in list(_sessions.items()):
            if value['until']<time.monotonic() and not value['running']:
                value['browser'].stop();atexit.unregister(value['browser'].stop);del _sessions[old]
        session=_sessions.get(key)
        if session and session['running']:raise APIError('This research is already running.','busy',409)
        if not session:
            if reviewed:raise APIError('That research session expired. Start a fresh research pass.')
            session={'browser':Browser(bridge.config),'history':[],'sources':[],'running':False,'until':time.monotonic()+600}
            _sessions[key]=session
        session['running']=True
    browser=session['browser'];history=session['history'];sources=session['sources']
    try:
        started=bridge.mutate(id,actor,{'status':'research','cancelled':False,'panel':'research'},row['version'])
        if progress:progress(started)
        if reviewed:
            suggestion=browser.suggestion
            if not suggestion or not suggestion.get('needs_review'):raise APIError('No reviewed research step is pending.')
            browser.apply(suggestion['id'],reviewed=True)
            history.append({'operation':suggestion.get('operation',''),'label':suggestion['label'][:500]})
        elif not browser.status()['running']:browser.start('https://www.google.com')
        answer='';needs_review=False
        deadline=time.monotonic()+120
        for _ in range(max(0,8-len(history))):
            if time.monotonic()>deadline:break
            if bridge.get(id,actor)['cancelled']:return bridge.get(id,actor)
            preview=browser.snapshot()
            page=browser.observed or {}
            if page.get('url','').startswith('https://'):
                source={'url':page['url'],'title':str(page.get('title',''))[:160],
                        'excerpt':str(page.get('text',''))[:600]}
                if source not in sources:sources.append(source)
            plan=browser.plan('Research this message using public sources. Do not post, sign in, buy, send or change accounts. '+row['source']['text'][:1500],preview['snapshot'],json.dumps(history))
            if bridge.get(id,actor)['cancelled']:return bridge.get(id,actor)
            if plan.get('needs_review'):
                answer='Review the next step: '+plan.get('label','');needs_review=True;break
            if not plan.get('action'):
                answer=plan.get('label') or plan.get('detail') or 'No further supported move.';break
            browser.apply(plan['id'])
            history.append({'operation':plan.get('operation',plan.get('choice','')),'label':plan.get('label','')[:500],
                            'url':page.get('url','')[:500]})
        result={'summary':answer or 'Step limit reached. Review the observed sources; research is incomplete.',
                'sources':sources[:8],'moves':len(history),'needs_review':needs_review,'scope':'Observed pages only; not exhaustive.'}
        if bridge.get(id,actor)['cancelled']:return bridge.get(id,actor)
        saved=bridge.mutate(id,actor,{'research':result,'status':'needs_input' if needs_review else 'researched'})
        if not needs_review:cancel(bridge,id)
        return saved
    except Exception:
        cancel(bridge,id)
        raise
    finally:
        with _lock:session.update(running=False,until=time.monotonic()+600)
        if bridge.get(id,actor)['cancelled']:cancel(bridge,id)
