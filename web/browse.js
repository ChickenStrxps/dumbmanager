'use strict';
// Installed browser and Jev run in DumbAPI. This module only presents fixed controls.
window.DMBrowse=(()=>{
  let data=null,status=null,busy=false,initialized=false,imageURL='',error='',suggestion=null,notice='',searching=false,stopRequested=false;
  let retryAt=0,retryTimer=null;
  let resumableTask=null;
  let live=true,liveTimer=null,transport=null,manual=[],frameFailures=0,inflightInput=false;
  let touch=null,paint=0;
  const active=()=>initialized&&view==='browse'&&!document.hidden&&!!data;
  function schedule(delay=160){
    clearTimeout(liveTimer);liveTimer=null;
    if(active()&&!busy&&(manual.length||live&&!suggestion))liveTimer=setTimeout(pump,delay);
  }
  function point(event){
    const r=el('image').getBoundingClientRect();
    return {x:Math.max(0,Math.min(data.width-1,Math.floor((event.clientX-r.left)*data.width/r.width))),y:Math.max(0,Math.min(data.height-1,Math.floor((event.clientY-r.top)*data.height/r.height)))};
  }
  function fit(){
    if(!data)return;const stage=el('image').parentElement;
    const scale=Math.min(stage.clientWidth/data.width,stage.clientHeight/data.height);
    el('image').style.width=Math.floor(data.width*scale)+'px';el('image').style.height=Math.floor(data.height*scale)+'px';
  }
  function input(operation,args={}){
    if(!data||busy)return;
    if(operation==='click'&&(manual.length||inflightInput))return toast('Let the page catch up before the next click.');
    if(manual.length>=32)return toast('Input queue is full. Let the page catch up.');
    suggestion=null;resumableTask=null;error='';frameFailures=0;
    if(operation==='scroll'){args.delta_x=Math.max(-1400,Math.min(1400,args.delta_x));args.delta_y=Math.max(-1400,Math.min(1400,args.delta_y));}
    const last=manual.at(-1);
    if(operation==='scroll'&&last?.operation==='scroll'&&Math.abs(last.args.x-args.x)<4&&Math.abs(last.args.y-args.y)<4&&Math.abs(last.args.delta_x+args.delta_x)<=1400&&Math.abs(last.args.delta_y+args.delta_y)<=1400){
      last.args={...args,delta_x:last.args.delta_x+args.delta_x,delta_y:last.args.delta_y+args.delta_y};
    }else if(operation==='type'&&last?.operation==='type'&&last.args.text.length+args.text.length<=4000)last.args.text+=args.text;
    else manual.push({operation,args,frame:operation==='click'?data.frame:null});
    render();schedule(0);
  }
  async function pump(){
    liveTimer=null;if(!active()||busy)return;if(transport)return;
    const item=manual.shift();if(!item&&(!live||suggestion))return;
    inflightInput=!!item;
    const started=performance.now();
    transport=(async()=>{
      try{
        const next=await call(item?'browser.interact':'browser.frame',item?{operation:item.operation,frame:item.frame||data.frame,...item.args}:{});
        await accept(next,true);frameFailures=0;
      }catch(e){
        frameFailures++;manual=[];
        if(e.code==='browser_stopped')reset();
        else if(item){error=e.message;try{await accept(await call('browser.frame'),true);}catch{}}
        else if(frameFailures>=3){live=false;error='Live preview disconnected. Refresh to reconnect.';}
      }finally{transport=null;inflightInput=false;render(!!data);schedule(manual.length?0:Math.max(80,200-(performance.now()-started)));}
    })();
    await transport;
  }
  function planError(e){
    error=e.message;
    if(e.code!=='mercury_rate_limited')return;
    const delay=Number(e.retryAfterMs);
    if(!Number.isFinite(delay)||delay<=0)return;
    const message=e.message;
    retryAt=Date.now()+Math.min(delay,3600000);clearInterval(retryTimer);
    retryTimer=setInterval(()=>{
      if(Date.now()>=retryAt){clearInterval(retryTimer);retryTimer=null;retryAt=0;if(error===message)error='Ready to retry. Your goal is kept.';}
      render();
    },1000);
  }
  const root=()=>$('#browse-workspace'),el=id=>$('#browse-'+id);
  const btn=(action,label,cls='secondary',extra='')=>`<button type="button" data-browse="${action}" class="${cls}" ${extra}>${label}</button>`;
  function init(){
    root().innerHTML=`<form id="browse-address-form" class="browse-address"><div class="browse-history">${btn('back','←','quiet','aria-label="Go back"')}${btn('forward','→','quiet','aria-label="Go forward"')}</div><label class="sr" for="browse-url">Page address</label><input id="browse-url" placeholder="Paste a link or search…" autocomplete="off" spellcheck="false"><button type="submit" id="browse-go" class="primary">Go ↗</button>${btn('refresh','↻','secondary','aria-label="Refresh page preview"')}</form>
      <div class="browse-session"><label class="sr" for="browse-tabs">Browser tab</label><select id="browse-tabs"><option value="">No tabs yet</option></select>${btn('new','+','quiet','aria-label="New browser tab"')}${btn('close-tab','×','quiet','aria-label="Close browser tab"')}${btn('viewport','Phone view','quiet')}${btn('stop','Stop','quiet')}<span id="browse-status" role="status"></span></div>
      <div class="browse-stage"><div id="browse-empty" class="browse-empty"><pre data-ascii="orbit" aria-hidden="true">[ · + · ]</pre><h3>Browser’s off.</h3><p>Open a page without leaving DumbManager.</p>${btn('start','Start browsing ↗','primary')}<small>Private temporary Edge session · stops after 15 idle minutes.</small></div><img id="browse-image" alt="Interactive browser page preview" hidden tabindex="0" aria-label="Browser page preview. Click to interact; use the type field for text and key controls below."><div id="browse-working" hidden><span data-ascii="scan" aria-hidden="true">[ / ··· ]</span><span id="browse-working-label">Loading page…</span></div></div>
      <div class="browse-page-tools"><form id="browse-type-form"><label class="sr" for="browse-type">Text to enter in the focused page field</label><input id="browse-type" autocomplete="off" placeholder="Click a field above, type here…" maxlength="4000"><button class="secondary" type="submit">Type ↗</button></form><div class="browse-key-tools">${btn('enter','Enter','quiet')}${btn('tab','Tab','quiet')}${btn('up','↑','quiet','aria-label="Scroll page up"')}${btn('down','↓','quiet','aria-label="Scroll page down"')}<details id="browse-more"><summary>More ···</summary><div>${btn('escape','Escape')}${btn('select-all','Select all')}${btn('backspace','Backspace')}${btn('secret','Hide typed text')}${btn('reload','Reload site')}${btn('targets','Page controls')}</div></details>${btn('stash','Stash page ▧','primary')}</div></div>
      <form id="browse-jev-form" class="browse-jev"><span class="browse-jev-mark" data-ascii="spark" aria-hidden="true">· + ·</span><label class="sr" for="browse-goal">Goal for Jev</label><input id="browse-goal" maxlength="2000" placeholder="Find grok on Wikipedia…" autocomplete="off"><button type="submit" id="browse-ask" class="secondary">Ask Jev ↗</button>${btn('connect','Connect Jev','quiet')}</form><div id="browse-suggestion" class="browse-suggestion" hidden></div><p id="browse-error" class="browse-error" role="alert" hidden></p>`;
    root().addEventListener('click',click);
    el('address-form').onsubmit=e=>{e.preventDefault();run(data?'navigate':'start',{url:el('url').value.trim()||'about:blank'});};
    el('type-form').onsubmit=e=>{e.preventDefault();const text=el('type').value;if(text&&!busy){input('type',{text});el('type').value='';}};
    el('jev-form').onsubmit=e=>{e.preventDefault();ask();};
    const cancel=document.createElement('button');cancel.type='button';cancel.id='browse-cancel';cancel.className='quiet';cancel.textContent='Stop';cancel.hidden=true;
    cancel.onclick=()=>{stopRequested=true;notice='Stopping…';render();};el('jev-form').append(cancel);
    el('tabs').onchange=()=>run('switch_tab',{tab:el('tabs').value});
    el('image').onclick=e=>{
      if(!data||busy||touch?.moved)return;el('image').focus({preventScroll:true});input('click',point(e));
    };
    el('image').onkeydown=e=>{
      if(e.shiftKey&&e.key==='Tab')return;
      if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='a'){e.preventDefault();input('key',{key:'SelectAll'});}
      else if(!e.ctrlKey&&!e.metaKey&&!e.altKey){
        if(['Enter','Tab','Escape','ArrowUp','ArrowDown','ArrowLeft','ArrowRight','Backspace','Delete','Home','End','PageUp','PageDown',' '].includes(e.key)){e.preventDefault();input('key',{key:e.key});}
        else if(e.key.length===1){e.preventDefault();input('type',{text:e.key});}
      }
    };
    el('image').onpaste=e=>{const text=e.clipboardData?.getData('text/plain');if(text){e.preventDefault();input('type',{text:text.slice(0,4000)});}};
    el('image').addEventListener('wheel',e=>{
      if(!data||busy||e.ctrlKey)return;e.preventDefault();const factor=e.deltaMode===1?18:e.deltaMode===2?data.height:1;
      input('scroll',{...point(e),delta_x:Math.round(e.deltaX*factor),delta_y:Math.round(e.deltaY*factor)});
    },{passive:false});
    el('image').addEventListener('touchstart',e=>{if(e.touches.length===1)touch={...point(e.touches[0]),clientX:e.touches[0].clientX,clientY:e.touches[0].clientY,moved:false};},{passive:true});
    el('image').addEventListener('touchmove',e=>{
      if(!touch||e.touches.length!==1||busy)return;
      const t=e.touches[0],dx=touch.clientX-t.clientX,dy=touch.clientY-t.clientY;if(!touch.moved&&Math.hypot(dx,dy)<6)return;
      e.preventDefault();touch.moved=true;const scale=data.height/el('image').getBoundingClientRect().height;
      input('scroll',{x:touch.x,y:touch.y,delta_x:Math.round(dx*scale),delta_y:Math.round(dy*scale)});touch.clientX=t.clientX;touch.clientY=t.clientY;
    },{passive:false});
    el('image').addEventListener('touchend',e=>{if(touch?.moved)e.preventDefault();setTimeout(()=>{touch=null;},0);},{passive:false});
    el('image').addEventListener('touchcancel',()=>{touch=null;});
    el('image').draggable=false;
    const liveButton=document.createElement('button');liveButton.type='button';liveButton.className='quiet';liveButton.dataset.browse='live';el('status').before(liveButton);
    new ResizeObserver(fit).observe(el('image').parentElement);
    document.addEventListener('visibilitychange',()=>schedule(0));
    window.addEventListener('pagehide',()=>{clearTimeout(liveTimer);manual=[];});
    // Live pixels are model-free and stop while hidden, away from Browse or idle-expired.
    const focus=document.createElementNS('http://www.w3.org/2000/svg','svg');focus.id='browse-focus';focus.setAttribute('aria-hidden','true');focus.setAttribute('hidden','');
    focus.innerHTML='<rect rx="3" vector-effect="non-scaling-stroke" />';el('image').after(focus);
    initialized=true;render();
  }
  function render(quiet=false){
    if(!initialized)return;
    if(view==='browse')$('#feed-count').textContent=busy?'LOADING':data?'LIVE':'OFF';
    el('empty').hidden=!!data;el('image').hidden=!data;el('working').hidden=!busy||!!data;
    el('working-label').textContent=notice||'Loading page…';
    el('error').textContent=error;el('error').hidden=!error;
    el('status').textContent=busy?notice||'Working…':manual.length?'Catching up…':data?(live?'Live preview':'Preview paused'):status?.installed===false?'Edge required':'Off';
    root().querySelector('[data-browse="live"]').textContent=live?'Pause preview':'Resume preview';
    root().querySelector('[data-browse="live"]').setAttribute('aria-pressed',String(!live));
    root().querySelector('[data-browse="live"]').hidden=!data;
    el('image').setAttribute('aria-busy',String(busy||manual.length>0||inflightInput));
    if(quiet){fit();schedule();return;}
    for(const node of root().querySelectorAll('button,input,select'))node.disabled=busy;
    const wait=Math.max(0,Math.ceil((retryAt-Date.now())/1000));
    el('ask').textContent=wait?`Wait ${wait}s`:'Ask Jev ↗';el('ask').disabled=busy||wait>0;
    for(const node of root().querySelectorAll('.browse-page-tools button,.browse-page-tools input,.browse-history button,[data-browse="refresh"],[data-browse="stop"],[data-browse="new"],[data-browse="close-tab"],[data-browse="viewport"],#browse-tabs'))node.disabled=busy||!data;
    root().querySelector('[data-browse="connect"]').textContent=status?.jev_connected?'Jev connected':'Connect Jev';
    root().querySelector('[data-browse="viewport"]').textContent=data?.width===390?'Desktop view':'Phone view';
    el('go').textContent=data?'Go ↗':'Start ↗';
    el('suggestion').hidden=!suggestion;
    el('cancel').hidden=!searching;el('cancel').disabled=stopRequested;el('cancel').textContent='Stop';
    if(suggestion)el('suggestion').innerHTML=`<span><b>${esc(suggestion.label)}</b>${suggestion.detail?`<${suggestion.kind==='passage'?'blockquote class="browse-quote"':'small class="browse-move-detail"'}>${esc(suggestion.detail)}</${suggestion.kind==='passage'?'blockquote':'small'}>`:''}<small>${suggestion.kind==='passage'?'Visible text · ':''}${suggestion.engine==='mercury-3'?'Mercury 3':'Jev · '+Math.round(suggestion.confidence*100)+'% confidence'} · ${suggestion.milliseconds} ms</small></span>`;
    if(suggestion?.needs_review&&suggestion.action)el('suggestion').innerHTML+=btn('review-move','Review & run ↗','primary');
    const focus=el('focus'),bounds=suggestion?.kind==='passage'&&suggestion.snapshot===data?.snapshot&&!busy?suggestion.bounds:null;
    focus.toggleAttribute('hidden',!bounds);
    if(bounds){focus.setAttribute('viewBox',`0 0 ${data.width} ${data.height}`);for(const key of ['x','y','width','height'])focus.firstElementChild.setAttribute(key,String(bounds[key]));}
    DMUI.sync();
    fit();schedule();
  }
  async function accept(next,visual=false){
    const serial=++paint;
    const bytes=Uint8Array.from(atob(next.image),c=>c.charCodeAt(0));const url=URL.createObjectURL(new Blob([bytes],{type:next.mime}));
    const decoded=new Image();decoded.src=url;
    try{await decoded.decode();}catch{URL.revokeObjectURL(url);throw new Error('Could not display this browser frame.');}
    if(serial!==paint){URL.revokeObjectURL(url);return;}
    const changed=data?.tab!==next.tab||data?.url!==next.url;
    data=visual?{...data,...next}:next;status={...(status||{}),running:true,jev_connected:data.jev_connected};
    if(!visual)suggestion=null;
    el('image').src=url;el('image').width=next.width;el('image').height=next.height;fit();
    if(imageURL)URL.revokeObjectURL(imageURL);imageURL=url;
    if(document.activeElement!==el('url'))el('url').value=next.url;
    if(next.tabs)el('tabs').innerHTML=next.tabs.map(t=>`<option value="${esc(t.id)}" ${t.id===next.tab?'selected':''}>${esc(t.title||t.url||'New tab')}</option>`).join('');
    else if(changed){const selected=el('tabs').selectedOptions[0];if(selected)selected.textContent=next.url;}
  }
  async function enter(){
    if(busy)return;busy=true;manual=[];await transport;error='';notice='Checking the browser…';render();
    try{status=await call('browser.status');if(status.running)await accept(await call('browser.snapshot'));else reset();}
    catch(e){error=e.message;}finally{busy=false;render();}
  }
  function reset(){paint++;data=null;suggestion=null;manual=[];clearTimeout(liveTimer);el('tabs').innerHTML='<option value="">No tabs yet</option>';el('image').removeAttribute('src');if(imageURL)URL.revokeObjectURL(imageURL);imageURL='';}
  async function run(operation,args={},after=null){
    if(busy)return;busy=true;error='';notice=operation==='start'?'Starting your browser…':'Loading page…';render();
    manual=[];await transport;live=true;frameFailures=0;
    resumableTask=null;
    try{
      if(operation==='stop'){status={...(status||{}),...await call('browser.stop')};reset();return;}
      let next=operation==='start'?await call('browser.start',args):operation==='refresh'?await call('browser.snapshot'):operation==='apply'?await call('browser.apply',{suggestion:suggestion.id}):await call('browser.action',{operation,snapshot:data?.snapshot||'',...args});
      if(operation==='start'&&matchMedia('(max-width:700px)').matches)next=await call('browser.action',{operation:'viewport',text:'phone'});
      await accept(next);after?.();
    }catch(e){error=e.message;suggestion=null;if(e.code==='browser_stopped'){reset();}else if(data&&operation!=='refresh'){
      // Refresh observes an uncertain action; it never repeats the action itself.
      try{await accept(await call('browser.snapshot'));}catch{}
    }}finally{busy=false;render();}
  }
  async function ask(){
    if(busy||Date.now()<retryAt)return;if(status?.mercury_connected)return askMercury();if(!status?.jev_connected)return connect();
    const goal=el('goal').value.trim();if(!goal)return el('goal').focus();
    busy=true;manual=[];await transport;searching=true;stopRequested=false;error='';suggestion=null;notice='Jev is finding the next move…';render();
    try{
      if(!data){
        await accept(await call('browser.start'));
        if(matchMedia('(max-width:700px)').matches)await accept(await call('browser.action',{operation:'viewport',text:'phone'}));
      }
      let scrolls=0,rechecks=0;const seen=new Set();
      for(;;){
        if(stopRequested||view!=='browse')break;
        let next;
        try{next=await call('browser.suggest',{goal,snapshot:data.snapshot});}
        catch(e){if(e.code==='browser_changed'&&rechecks++<1)continue;throw e;}
        if(next.preview){await accept(next.preview);delete next.preview;}
        if(stopRequested||view!=='browse')break;
        if(!next.action){suggestion=next;break;}
        // Continue only the fixed scroll/read branch, up to three scrolls.
        if(next.continuation){
          if(scrolls>=3||seen.has(data.viewport_token)){
            suggestion={...next,action:null,label:scrolls>=3?'No match in the next three scrolls.':'Reached the end of this view.'};break;
          }
          seen.add(data.viewport_token);notice=`Looking further · ${scrolls+1}/3`;render();
        }else{notice='Making the move…';render();}
        try{
          await accept(await call('browser.apply',{suggestion:next.id}));
        }catch(e){
          // Only an explicit pre-dispatch rejection permits another judgment.
          if(e.code==='browser_stale'&&rechecks++<1)continue;
          throw e;
        }
        if(!next.continuation){suggestion={...next,action:null,snapshot:data.snapshot,label:'Done · '+next.label};break;}
        scrolls++;
        if(seen.has(data.viewport_token)){
          suggestion={...next,action:null,snapshot:data.snapshot,label:'Reached the end of this view.'};break;
        }
      }
    }
    catch(e){error=e.message;suggestion=null;try{await accept(await call('browser.snapshot'));}catch{}}
    finally{if(stopRequested)notice='Stopped.';busy=false;searching=false;render();el('goal').focus();}
  }
  async function askMercury(){
    const goal=el('goal').value.trim();if(!goal)return el('goal').focus();
    busy=true;manual=[];await transport;searching=true;stopRequested=false;error='';suggestion=null;notice='Finding the next move…';render();
    const history=resumableTask?.goal===goal?[...resumableTask.history]:[],seen=new Set();let stale=0,planning=false;
    resumableTask=null;
    try{
      if(!data){await accept(await call('browser.start'));if(matchMedia('(max-width:700px)').matches)await accept(await call('browser.action',{operation:'viewport',text:'phone'}));}
      for(let step=0;step<=8;){
        if(stopRequested||view!=='browse')break;
        planning=true;
        const next=await call('browser.plan',{goal,snapshot:data.snapshot,history:JSON.stringify(history)});
        planning=false;
        if(next.preview){await accept(next.preview);delete next.preview;}
        if(stopRequested||view!=='browse')break;
        if(!next.action||next.needs_review){suggestion=next;break;}
        if(step===8){suggestion={...next,action:null,label:'Eight moves done. Ask again to keep going.'};break;}
        const key=JSON.stringify(next.action)+'|'+data.viewport_token;
        if(seen.has(key)){suggestion={...next,action:null,label:'That move repeated. Check the page before continuing.'};break;}
        notice=`${step+1}/8 · ${next.label}`;render();
        try{await accept(await call('browser.apply',{suggestion:next.id}));}
        catch(e){if(e.code==='browser_stale'&&stale++<2)continue;throw e;}
        seen.add(key);history.push({operation:next.action.operation,node:next.action.node||'',text:(next.action.text||'').slice(0,600),url:(next.action.url||'').slice(0,300),label:next.label.slice(0,200)});if(history.length>8)history.shift();step++;
      }
    }catch(e){if(planning&&['mercury_rate_limited','mercury_generation_limited','mercury_unavailable'].includes(e.code))resumableTask={goal,history};planError(e);suggestion=null;try{await accept(await call('browser.snapshot'));}catch{}}
    finally{if(stopRequested){suggestion={label:'Stopped.',engine:'mercury-3',kind:'answer',milliseconds:0,action:null};}notice='';busy=false;searching=false;render();el('goal').focus();}
  }
  async function reviewMove(){
    if(busy||!suggestion?.needs_review||!suggestion.action)return;
    const next=suggestion;busy=true;manual=[];await transport;error='';notice='Running the reviewed move…';render();
    try{await accept(await call('browser.apply',{suggestion:next.id,reviewed:true}));suggestion={...next,action:null,needs_review:false,label:'Move sent. Check the page for the result.'};}
    catch(e){error=e.message;suggestion=null;try{await accept(await call('browser.snapshot'));}catch{}}
    finally{notice='';busy=false;render();}
  }
  function connect(){
    let pending=false;
    const saved=status?.key_saved;
    dialog('Plug in Jev.',`<p>Enter or Ask Jev runs your requested move. Your goal + visible page text go to TypeSafe when you ask.</p><label for="browse-key">TypeSafe API key</label><input id="browse-key" type="password" autocomplete="off" spellcheck="false" placeholder="${saved?'Saved — enter a replacement':'Saved with Windows encryption'}"><p class="muted">${saved?'Remembered on this PC, including after restarts.':status?.key_notice?esc(status.key_notice):'Remembered on this PC with your Windows account.'}</p>${status?.jev_connected||status?.key_notice?'<button type="button" id="browse-forget" class="quiet">Forget key</button>':''}`,'Save key',async()=>{
      if(pending)return false;
      const key=$('#browse-key').value;
      if(!key){if(status?.jev_connected)return true;throw new Error('Enter your TypeSafe API key.');}
      pending=true;
      try{const next=await call('browser.connect',{api_key:key});$('#browse-key').value='';status={...(status||{}),...next};render();toast(next.note);return true;}
      finally{pending=false;}
    });
    const forget=$('#browse-forget');
    if(forget)forget.onclick=async()=>{
      if(pending)return;pending=true;forget.disabled=true;$('#dialog-save').disabled=true;
      try{const next=await call('browser.connect',{api_key:''});$('#browse-key').value='';status={...(status||{}),...next};render();toast(next.note);$('#editor').close();}
      catch(e){toast(e.message);}finally{pending=false;forget.disabled=false;$('#dialog-save').disabled=false;}
    };
    $('#editor').addEventListener('close',()=>{const field=$('#browse-key');if(field)field.value='';},{once:true});
  }
  async function targets(){
    await run('refresh');
    const snapshot=data?.snapshot;if(!snapshot)return;
    dialog('Pick the thing.',`<p class="muted">Visible page controls · useful when the preview is small.</p><div class="browse-targets">${data.nodes.map(n=>`<button type="button" class="secondary" data-browse-node="${esc(n.id)}"><small>${esc(n.kind)}</small>${esc(n.label)}</button>`).join('')||'<p>No visible controls. Try scrolling.</p>'}</div>`,'Done',()=>true);
    $('#dialog-content').onclick=e=>{const button=e.target.closest('[data-browse-node]');if(!button)return;$('#editor').close();$('#dialog-content').onclick=null;if(data?.snapshot!==snapshot)return toast('Page changed. Open the controls again.');run('node',{node:button.dataset.browseNode});};
    $('#editor').addEventListener('close',()=>{$('#dialog-content').onclick=null;},{once:true});
  }
  function stash(){
    if(!data||busy)return;
    const page=data,ctx=context(),chosenProject=project,stamp=new Date().toISOString(),request_key=uid();let upload=null,pending=null;
    dialog('Catch the scuffed.',`<p class="browse-stash-source">${esc(page.title||page.url)}</p><label for="browse-itch-note">What’s the itch?</label><input id="browse-itch-note" maxlength="500" placeholder="What needs fixing?" autocomplete="off"><p class="muted">Saves this preview + page address with your itch.</p>`,'Stash it',async()=>{
      const title=$('#browse-itch-note').value.trim();if(!title)throw new Error('Give the itch a few words.');
      if(!upload){
        const image=new Blob([Uint8Array.from(atob(page.image),c=>c.charCodeAt(0))],{type:'image/jpeg'});
        const send=()=>fetch('/api/itch-upload',{method:'POST',headers:{'X-DumbManager':'1','X-File-Name':'browser-page.jpg','X-File-Type':'image/jpeg'},body:image});
        let response=await send();if(response.status===403){await fetch('/');response=await send();}
        const result=await response.json();if(!response.ok)throw new Error(result.error||'Screenshot upload failed. Your note is saved.');upload=result.attachment;
      }
      // Preserve exact capture arguments across lost responses. Existing outbox syncs the same key.
      pending ||= {title,original:`Observed in browser: ${page.url}\n${page.title}\nPreview captured ${page.time}`.slice(0,2000),attachments:JSON.stringify([upload.id]),project:chosenProject,context_id:ctx?.id||'',context_snapshot:JSON.stringify(ctx||{}),use_active:false,event_at:stamp,request_key};
      if(outbox.length>=32)throw new Error('Outbox is full. Reconnect before saving more.');
      if(!outbox.some(x=>x.request_key===request_key)){outbox.push(pending);stashOutbox();}
      let row;
      try{row=await call('manager.capture',pending);}catch(e){if(e.network){toast('Stashed locally · syncs when connected');return true;}if(e.status&&e.status<500){outbox=outbox.filter(x=>x.request_key!==request_key);stashOutbox();pending=null;}throw e;}
      outbox=outbox.filter(x=>x.request_key!==request_key);stashOutbox();merge(row);window.DMAquarium?.celebrate?.('stash');toast('Stashed with a screenshot.');
      // Open the normal itch popup, including its Send to T3 button.
      setTimeout(()=>DMItches.open(row.id),0);return true;
    });
  }
  function click(e){
    const b=e.target.closest('[data-browse]');if(!b||busy)return;
    const action=b.dataset.browse;
    if(action==='live'){live=!live;render();return;}
    if(action==='review-move')return reviewMove();
    if(action==='connect')return connect();if(action==='stash')return stash();if(action==='targets')return targets();
    if(action==='secret'){el('type').type=el('type').type==='password'?'text':'password';b.textContent=el('type').type==='password'?'Show typed text':'Hide typed text';el('more').open=false;return;}
    if(action==='viewport')return run('viewport',{text:data.width===390?'desktop':'phone'});
    const keys={enter:'Enter',tab:'Tab',escape:'Escape','select-all':'SelectAll',backspace:'Backspace'};
    if(keys[action])return input('key',{key:keys[action]});
    if(action==='up'||action==='down')return input('scroll',{x:Math.floor(data.width/2),y:Math.floor(data.height/2),delta_x:0,delta_y:action==='up'?-300:300});
    const operations={new:'new_tab','close-tab':'close_tab',up:'scroll_up',down:'scroll_down'};
    el('more').open=false;run(operations[action]||action,action==='close-tab'?{tab:data.tab}:action==='start'?{url:el('url').value.trim()||'about:blank'}:{});
  }
  return {init,render,enter};
})();
