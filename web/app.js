'use strict';
window.DMAppStarted=true;
const $ = s => document.querySelector(s);
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const uid = () => crypto.randomUUID();
const label = s => ({open:'stashed',needs_description:'add words',working:'cooking',ready:'ready to test',resolved:'handled',archived:'archived'}[s] || s);
function itchStatus(r){
  if(r.state==='resolved')return {step:3,label:'We’re so back',kind:'resolved',note:'Accepted by you.'};
  if(r.state==='archived')return {step:0,label:'archived',kind:'archived',note:'Archived.'};
  if(r.state==='ready'||r.run_state==='agent_reported_done')return {step:2,label:'Ready to test',kind:'ready',note:'T3 says it’s done. Your call.'};
  if(r.run_state==='failed')return {step:1,label:'Needs a nudge',kind:'failed',note:'T3 hit a problem. Open it for details.'};
  if(r.state==='working'||r.run_state==='agent_reported_running')return {step:1,label:'Cooking',kind:'working',note:'T3 is working on it.'};
  const handoff=r.handoffs?.at(-1),occurrence=r.occurrences?.at(-1),feedback=r.feedback?.at(-1);
  // A previous pass must not make a repeated itch look as if it is still cooking.
  const includedFeedback=feedback?.request_key&&feedback.request_key===handoff?.request_key;
  const sent=handoff&&!(feedback?.at&&Date.parse(feedback.at)>=Date.parse(handoff.at)&&!includedFeedback)&&
    (!occurrence||Date.parse(handoff.at)>Date.parse(occurrence.at)||(r.occurrences?.length||0)<=1);
  if(sent)return {step:1,label:'Sent to T3',kind:'queued',note:'Delivered. Waiting for T3 to start.'};
  return {step:0,label:label(r.state),kind:r.state,note:'Stashed. Send it when you’re ready.'};
}
function progressMarkup(status){
  const steps=['Stashed','Cooking','Ready to test','We’re so back'];
  return `<span class="itch-progress ${status.kind}" role="img" aria-label="${esc(status.label)} · stage ${status.step+1} of 4. ${esc(status.note)}">${steps.map((name,i)=>`<span class="progress-dot ${i<status.step?'done':i===status.step?'current':''}" title="${esc(name+(i===status.step?' · '+status.note:''))}"></span>`).join('')}</span>`;
}
const age = s => { const n = Math.max(0,(Date.now()-new Date(s))/60000); return n<1?'just now':n<60?Math.floor(n)+'m ago':n<1440?Math.floor(n/60)+'h ago':Math.floor(n/1440)+'d ago'; };
const today = s => new Date(s).toDateString() === new Date().toDateString();
const fmt = n => n === null || n === undefined ? 'Unknown' : new Intl.NumberFormat(undefined,{maximumFractionDigits:2}).format(n);
let state={itches:[],contexts:[],preferences:{motion:true}}, view='now', filter='all', selected=null, project='unsorted';
let suggestions=[], suggestionIndex=-1, sources={}, sourceStatus={}, toastTimer, syncing=false, saving=false;
let replayState={}, nativeState={}, replayWindows=[], selectedReplayWindow='', toolResult=null, frameObject=null, lastInputMode='', commandsLoaded=false;
let renderedDetailId=null, renderedDetailVersion=0, renderedPosting="";
let outbox;
let dialogSequence=0;
let commandLoadPromise=null, sourceLoading=false;
// T3 titles are separate from the task notes that agents publish for typing.
const contextThreads=new Map(),contextSearches=new Map();
let contextThreadLoad=null,contextThreadQuery='',contextThreadError='',contextThreadPartial=false,contextSearchTimer;
const contextTitle=c=>contextThreads.get(c.thread_id)?.title||c.task;
async function loadContextThreads(query=''){
  query=query.trim().slice(0,200);contextThreadQuery=query;
  if(contextThreadLoad)return contextThreadLoad;
  if(Date.now()-(contextSearches.get(query)||0)<60000)return;
  contextThreadError='';
  contextThreadLoad=(async()=>{
    try{
      const data=await call('t3.threads',{query,limit:200});
      for(const row of data.items||[])if(row.id&&row.title){contextThreads.delete(row.id);contextThreads.set(row.id,row);}
      while(contextThreads.size>500)contextThreads.delete(contextThreads.keys().next().value);
      contextThreadPartial=!!data.partial;
      if(data.connected===false)contextThreadError=data.error||'T3 is unavailable. Saved contexts are still here.';
      else{contextSearches.delete(query);contextSearches.set(query,Date.now());while(contextSearches.size>50)contextSearches.delete(contextSearches.keys().next().value);}
    }catch(e){contextThreadError='T3 titles unavailable. '+e.message;}
    finally{
      contextThreadLoad=null;renderContext();
      if(contextThreadQuery!==query)loadContextThreads(contextThreadQuery);
    }
  })();
  renderContext();return contextThreadLoad;
}
let nativeTimer=null,nativeBusy=false;
let settingsTab='connections',workspaceView='now',workspaceScroll=0;
let appReady=false;
let toolTab='inspiration',toolResults={social:null,inspiration:null},toolPages={},jobItems=[],feedPage=0;
const pageKey='dm-page-v1',pageViews=['now','inbox','wins','tools','git','browse','setup'];
let restoringPage=true,pageTimer=null;
function pageHash(page){
  if(page.drawer&&page.view==='now')return '#drawer';
  const query=new URLSearchParams();
  if(page.view==='tools'){query.set('tab',page.toolTab);if(page.toolTab==='social'&&page.social?.itch)query.set('post',page.social.itch);}
  if(page.view==='tools'&&page.toolTab==='inspiration'){query.set('topic',page.inspiration.category);if(page.inspiration.query)query.set('spark',page.inspiration.query);if(page.inspiration.saved)query.set('shelf','1');if(page.inspiration.offset)query.set('signal_page',String(page.inspiration.offset));}
  if(page.view==='setup')query.set('tab',page.settingsTab);
  if(page.itch)query.set('itch',page.itch);
  if(page.itch&&page.learning?.itch===page.itch){query.set('learn',page.learning.section);if(page.learning.lesson)query.set('lesson',page.learning.lesson);}
  if(page.itch&&page.research?.itch===page.itch){query.set('research',page.research.section);if(page.research.run)query.set('research_run',page.research.run);if(page.research.report)query.set('research_report',page.research.report);}
  return '#'+page.view+(query.size?'?'+query:'');
}
function rememberPage(){
  if(restoringPage||!appReady)return;
  const page={version:1,view,toolTab,settingsTab,workspaceView,workspaceScroll,project,filter,feedPage,
    search:$('#search').value.slice(0,500),social:DMSocial.page(),git:DMGit.page(),inspiration:DMInspiration.page(),
    itch:$('#itch-view').open?selected:'',learning:DMLearning.page(),research:DMResearch.page(),drawer:document.body.classList.contains('drawer'),
    scroll:{window:scrollY,feed:$('#feed-items').scrollTop,tool:$('#tool-panel')?.scrollTop||0,itch:$('#itch-view').scrollTop}};
  page.hash=pageHash(page);
  try{sessionStorage.setItem(pageKey,JSON.stringify(page));}catch{}
  // Replace the current address: a previous #browse must never win on reload.
  try{if(location.hash!==page.hash)history.replaceState(history.state,'',location.pathname+location.search+page.hash);}catch{}
}
function savedPage(){
  const hash=location.hash;let page=null;
  try{const value=JSON.parse(sessionStorage.getItem(pageKey));if(value?.version===1&&value.hash===hash&&pageViews.includes(value.view))page=value;}catch{}
  if(page)return page;
  if(hash==='#drawer')return {view:'now',drawer:true};
  if(hash.startsWith('#itch='))return {view:'inbox',itch:hash.slice(6)};
  const [next,query='']=hash.slice(1).split('?'),params=new URLSearchParams(query);
  return {view:pageViews.includes(next)?next:'now',toolTab:params.get('tab'),settingsTab:params.get('tab'),inspiration:{category:params.get('topic'),query:params.get('spark'),saved:params.get('shelf')==='1',offset:Number(params.get('signal_page')||0)},
    social:{itch:params.get('post')},itch:params.get('itch'),learning:params.get('itch')&&['learn','commands','tools'].includes(params.get('learn'))?{itch:params.get('itch'),section:params.get('learn'),lesson:params.get('lesson')}:null,research:params.get('itch')&&['findings','plan','sources','brief'].includes(params.get('research'))?{itch:params.get('itch'),section:params.get('research'),run:params.get('research_run'),report:params.get('research_report')}:null};
}
async function restorePage(page){
  if(['social','inspiration'].includes(page.toolTab))toolTab=page.toolTab;
  if(['shortcuts','replay','appearance','connections','ai','bridge','posting','data'].includes(page.settingsTab))settingsTab=page.settingsTab;
  if(!context()&&typeof page.project==='string'&&[...$('#project').options].some(o=>o.value===page.project))project=page.project;
  await setView(page.view,page);
  if(pageViews.includes(page.workspaceView)&&page.workspaceView!=='setup')workspaceView=page.workspaceView;
  workspaceScroll=Number.isFinite(page.workspaceScroll)?Math.max(0,page.workspaceScroll):0;
  if(['all','ready','needs_description','suggested','open','working'].includes(page.filter))filter=page.filter;
  feedPage=Number.isInteger(page.feedPage)?Math.max(0,Math.min(page.feedPage,100000)):0;
  $('#search').value=typeof page.search==='string'?page.search.slice(0,500):'';
  document.querySelectorAll('[data-filter]').forEach(b=>b.classList.toggle('active',b.dataset.filter===filter));
  renderContext();render();
  if(view==='tools'){
    if(toolTab==='social')await DMSocial.restorePage(page.social);
    if(toolTab==='queue')await jobs();
  }
  if(page.drawer){document.body.classList.add('drawer');$('#command').focus();}
  if(typeof page.itch==='string'&&state.itches.some(r=>r.id===page.itch))DMItches.open(page.itch);
  if($('#itch-view').open&&page.learning?.itch===page.itch)await DMLearning.open(page.itch,page.learning);
  if($('#itch-view').open&&page.research?.itch===page.itch)await DMResearch.open(page.itch,page.research);
  // Wait for the selected panel's final layout before restoring its position.
  await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
  const position=n=>Number.isFinite(n)?Math.max(0,Math.min(n,10000000)):0;
  window.scrollTo(0,position(page.scroll?.window));$('#feed-items').scrollTop=position(page.scroll?.feed);
  if($('#tool-panel'))$('#tool-panel').scrollTop=position(page.scroll?.tool);
  $('#itch-view').scrollTop=position(page.scroll?.itch);
}
function paged(items,key,size=3){
  const count=Math.max(1,Math.ceil(items.length/size)),page=Math.min(Math.max(0,toolPages[key]||0),count-1);toolPages[key]=page;
  return {items:items.slice(page*size,(page+1)*size),nav:items.length>size?`<nav class="result-pages" aria-label="${esc(key)} pages"><button class="secondary" data-tool-page="${esc(key)}" data-page="${page-1}" ${page===0?'disabled':''}>← Back</button><span>${page*size+1}–${Math.min(items.length,(page+1)*size)} / ${items.length}</span><button class="secondary" data-tool-page="${esc(key)}" data-page="${page+1}" ${page===count-1?'disabled':''}>More →</button></nav>`:''};
}
function selectTool(tab){
  if(!['social','inspiration'].includes(tab))return;
  toolTab=tab;toolResult=toolResults[tab];
  if(tab==='inspiration')DMInspiration.enter();
  renderTools();if(tab==='social')DMSocial.resume();rememberPage();
}
function toolAnswer(tab,result){toolResults[tab]=result;if(toolTab===tab){toolResult=result;renderTools();}}
async function ensureModules(){
  const modules=[['ui','DMUI'],['aquarium','DMAquarium'],['richtext','DMRich'],['previews','DMPreviews'],['t3-settings','DMT3'],['attachments','DMUploads'],['chat','DMChat'],['itches','DMItches'],['learning','DMLearning'],['research','DMResearch'],['inspiration','DMInspiration'],['git','DMGit'],['browse','DMBrowse'],['intake','DMIntake'],['social','DMSocial'],['webhook','DMWebhook'],['ai','DMAI'],['voice','DMVoice'],['bridge','DMBridge']];
  const missing=()=>modules.filter(([,name])=>!window[name]);
  if(!missing().length)return;
  const dialog=document.createElement('dialog');dialog.id='startup-recovery';dialog.className='startup-recovery';
  dialog.innerHTML='<pre aria-hidden="true">[ .. ]</pre><h2>One sec\u2026</h2><p role="status"></p><button type="button" class="primary" hidden>Try again</button>';
  const message=dialog.querySelector('p'),button=dialog.querySelector('button');
  dialog.addEventListener('cancel',e=>e.preventDefault());document.body.append(dialog);dialog.showModal();
  async function load([file,name],attempt){
    await new Promise((resolve,reject)=>{
      const script=document.createElement('script');script.src='/'+file+'.js?retry='+attempt;
      script.onload=()=>{script.remove();window[name]?resolve():reject(new Error('Module unavailable'));};
      script.onerror=()=>{script.remove();reject(new Error('Module unavailable'));};document.head.append(script);
    });
  }
  try{
    let attempt=0;
    while(missing().length){
      button.hidden=true;message.textContent='Part of the app missed the connection. Retrying\u2026';
      for(let retry=0;retry<2&&missing().length;retry++)await Promise.allSettled(missing().map(module=>load(module,++attempt)));
      if(!missing().length)break;
      message.textContent='Check your connection, then try again.';button.hidden=false;button.focus();
      await new Promise(resolve=>{button.onclick=resolve;});
    }
  }finally{dialog.close();dialog.remove();}
}
function signal(text,detail='LOCAL',kind='orbit'){
  $('#signal-label').textContent=text;$('#signal-detail').textContent=detail;$('#signal-art').dataset.ascii=kind;
}
try { outbox=JSON.parse(localStorage.getItem('dm-outbox') || '[]'); if(!Array.isArray(outbox)) outbox=[]; } catch { outbox=[]; }
function stashOutbox(){ localStorage.setItem('dm-outbox',JSON.stringify(outbox)); showOutbox(); }
async function post(path,value,blob=false,retried=false){
  let response;
  try { response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-DumbManager':'1'},body:JSON.stringify(value)}); }
  catch(e){ e.network=true; throw e; }
  if(response.status===403&&!retried){await fetch('/');return post(path,value,blob,true);}
  if(blob){if(!response.ok) throw new Error('Frame unavailable');return response.blob();}
  let result;
  try { result=JSON.parse(await response.text()); }
  catch { const e=new Error('DumbManager returned an unexpected reply. Your text is kept; try Stash again.');e.status=response.status;throw e; }
  if(!response.ok){const e=new Error(result.error || 'Request failed');e.status=response.status;e.code=result.code;e.retryAfterMs=result.retry_after_ms;if(e.code==='t3_target_changed')DMT3.changed();throw e;}
  return result;
}
const call=(name,args={},idempotency_key)=>post('/api/call',{name,args,idempotency_key,t3_target:window.DMT3?.target});
const replay=(action,args={})=>post('/api/replay',{action,...args});
function toast(message,undo){
  clearTimeout(toastTimer); $('#toast span').textContent=message; $('#toast').hidden=false;
  const b=$('#toast button'); b.hidden=!undo; b.onclick=async()=>{b.disabled=true;try{await undo();$('#toast').hidden=true;}catch(e){toast(e.message);}finally{b.disabled=false;}};
  toastTimer=setTimeout(()=>$('#toast').hidden=true,undo?9000:5000);
}
function showOutbox(){
  $('#outbox').hidden=!outbox.length;
  $('#outbox').textContent=outbox.length+' itch'+(outbox.length===1?'':'es')+' saved in this browser. They sync when DumbAPI is back.';
}
function context(){return state.contexts.find(c=>c.id===state.active_context);}
function merge(row){const index=state.itches.findIndex(r=>r.id===row.id);if(index>=0)state.itches[index]={...row,posting:row.posting||state.itches[index].posting};else state.itches.unshift(row);}
async function change(id,changes,version){
  const row=await call('manager.update',{id,changes:JSON.stringify(changes),expected_version:version || 0,request_key:uid()});merge(row);render();return row;
}
async function refresh(){
  if(syncing)return; syncing=true;
  try{
    const next=await call('manager.state');state=next;
    const ctx=context(); if(ctx)project=ctx.project;
    $('#connection').textContent='DumbAPI · local';$('#connection-dot').classList.remove('offline');
    renderContext();render();
    if(view==='wins'||view==='tools'&&toolTab==='social')DMSocial.checkPosts(false);
    if(outbox.length){
      for(const pending of [...outbox]){
        try{const row=await call('manager.capture',pending);merge(row);outbox=outbox.filter(x=>x.request_key!==pending.request_key);stashOutbox();}
        catch(e){if(!e.network)toast('Pending itch needs attention: '+e.message);break;}
      }
      render();
    }
  }catch(e){$('#connection').textContent='Offline · stashes queue locally';$('#connection-dot').classList.add('offline');}
  finally{syncing=false;}
}
function renderContext(){
  const opts=[...$('#project').options].map(o=>o.value);
  const ctx=context();
  if(!opts.includes(project))$('#project').add(new Option(project,project));
  $('#project').value=project;
  const contexts=state.contexts.filter(c=>project==='unsorted'||c.project===project||c.id===state.active_context);
  const saved=new Map(state.contexts.map(c=>[c.thread_id,c]));
  $('#context').innerHTML='<option value="">No pinned thread</option>'+contexts.map(c=>`<option value="${esc(c.id)}" data-search="${esc([contextTitle(c),c.task,c.project,c.thread_id].join(' '))}" data-detail="${esc(c.project+' · '+c.task)}">${esc(contextTitle(c))}</option>`).join('')+
    [...contextThreads.values()].filter(t=>!saved.has(t.id)).map(t=>`<option value="thread:${esc(t.id)}" data-search="${esc([t.title,t.project,t.id].join(' '))}" data-detail="${esc((t.project||'T3')+' · Set up context')}">${esc(t.title)}</option>`).join('');
  $('#context').dataset.empty=contextThreadLoad?'Looking for T3 threads…':contextThreadError||'No matching threads or saved tasks.';
  $('#context').dataset.note=contextThreadLoad?'Loading T3 titles…':contextThreadError||(contextThreadPartial?'Recent threads shown. Search a title to look further.':'Search a thread title, saved task or exact ID.');
  $('#context').value=state.active_context||'';
  const stale=ctx && Date.now()-new Date(ctx.updated_at)>3600000;
  $('#context-badge').textContent=ctx?(stale?'CONTEXT STALE':'CONTEXT ✓'):'NO CONTEXT';$('#context-badge').className='badge '+(ctx?(stale?'stale':'ok'):'');
  $('#hero-context').textContent=ctx?(stale?'!':'✓'):'—';$('#hero-context-label').textContent=ctx?(stale?'context stale':'context set'):'no context';
  $('#context-description').textContent=ctx?`${stale?'Kinda stale':'Fresh'} · ${age(ctx.updated_at)}`:'Pin a thread so suggestions know what you’re testing.';
  $('#context-notes').hidden=!ctx;
  $('#context-full').textContent=ctx?ctx.task+'\n\n'+(ctx.testing||'')+'\n\n'+(ctx.source==='user_entered'?'Saved by you.':'Published by T3.'):'';
  $('#thread-link').hidden=!ctx;
  if(ctx)$('#thread-link').href='t3-thread://v1/'+ctx.thread_id;
  document.body.classList.toggle('no-motion',!state.preferences.motion);
  $('#motion').textContent=state.preferences.motion?'Motion on':'Motion paused';
  DMUI.sync();
  DMChat.decorate();
}
function render(){
  document.body.classList.toggle('now-view',view==='now');
  document.body.classList.toggle('settings-view',view==='setup');
  document.body.classList.toggle('browse-view',view==='browse');
  document.body.classList.toggle('tools-view',['tools','git','browse'].includes(view));
  $('#capture-section').hidden=view!=='now';
  const wins=state.itches.reduce((n,r)=>n+r.outcomes.filter(o=>today(o.at)).length,0);
  $('#wins-count').textContent=String(wins).padStart(2,'0');
  const open=state.itches.filter(r=>!['resolved','archived','suggested','declined'].includes(r.state)).length;
  $('#open-count').textContent=open;$('#open-count').toggleAttribute('data-zero',!open);$('#hero-open').textContent=String(open).padStart(2,'0');
  const tools=['tools','setup','git','browse'].includes(view);
  $('#filters').hidden=tools;$('#feed-items').hidden=tools;$('#tool-results').hidden=!tools||['git','browse'].includes(view);$('#git-workspace').hidden=view!=='git';$('#browse-workspace').hidden=view!=='browse';
  $('#feed-title').textContent=({now:'Open itches',inbox:'Itch pile',wins:'Today’s W’s',tools:'Side quests',git:'Git',browse:'Browse',setup:'Settings'})[view];
  $('#feed-eyebrow').textContent='';
  if(tools){if(view==='browse')DMBrowse.render();else if(view==='git')DMGit.render();else if(view==='tools')renderTools();else renderSetup();}
  else{
    const words=$('#search').value.toLowerCase().split(/\s+/).filter(Boolean);
    const ideaFilter=filter==='suggested'&&view!=='wins',stashFilter=filter==='open'&&view!=='wins';
    document.querySelectorAll('[data-filter]').forEach(b=>{const active=b.dataset.filter===filter;b.classList.toggle('active',active);b.setAttribute('aria-pressed',String(active));});
    $('#filter-stashed').textContent='Stashed · '+state.itches.filter(r=>itchStatus(r).kind==='open'&&(project==='unsorted'||r.project===project)).length;
    $('#filter-suggested').textContent='Suggested · '+state.itches.filter(r=>r.state==='suggested'&&(project==='unsorted'||r.project===project)).length;
    $('#filter-stashed').hidden=view==='wins';$('#filter-suggested').hidden=view==='wins';$('#find-dupes').hidden=view==='wins';
    if(ideaFilter)$('#feed-title').textContent='Suggested';
    if(stashFilter){$('#feed-title').textContent='Stashed itches';$('#feed-eyebrow').textContent='Saved for later · waiting to send';}
    const rows=state.itches.filter(r=>(ideaFilter?r.state==='suggested':!['archived','suggested','declined'].includes(r.state))&&(project==='unsorted'||view==='wins'||r.project===project)&&
      (view==='wins'?r.outcomes.some(o=>today(o.at)):r.state!=='resolved')&&
      (filter==='all'||(stashFilter?itchStatus(r).kind==='open':r.state===filter)||(filter==='ready'&&itchStatus(r).kind==='ready'))&&words.every(w=>(r.title+' '+r.key+' '+r.project).toLowerCase().includes(w)));
    $('#feed-count').textContent=rows.length+(ideaFilter?' SUGGESTED':stashFilter?' STASHED':view==='wins'?' W’S':' OPEN');
    toolPages.itches=feedPage;const page=paged(rows,'itches',view==='now'?5:8);feedPage=toolPages.itches;
    $('#feed-items').innerHTML=ideaFilter?DMIntake.suggestedMarkup(page.items)+page.nav:rows.length?page.items.map(r=>{const status=itchStatus(r),action=status.step===1?'Check on it':status.step===2?'Test it':status.step===3?'See the W':'Cook it';return `<div class="itch-entry">${progressMarkup(status)}<button class="itch ${r.id===selected?'selected':''}" data-itch="${r.id}"><span class="itch-icon">${r.state==='resolved'?'✳':r.state==='needs_description'?'!':'↗'}</span><span class="itch-copy"><h3>${esc(r.title)}</h3><span class="itch-meta"><span>${esc(r.project)}</span><span>·</span><span>${age(r.updated_at)}</span><span class="itch-state ${status.kind}" title="${esc(status.note)}">${status.label}</span>${DMSocial.badge(r)}${r.occurrences.length>1?'<span>×'+r.occurrences.length+'</span>':''}</span></span><span class="arrow">↗</span></button><button type="button" class="itch-cook secondary" data-send-itch="${r.id}" aria-label="${action}: open this itch">${action} ↗</button></div>`;}).join('')+page.nav:
      `<div class="empty"><pre data-ascii="${view==='wins'?'spark':'buddy'}" aria-hidden="true">${view==='wins'?'· + ·':'  .  +  .\n /|_[]_|\\\n    ─┴─'}</pre><h3>${stashFilter?(words.length?'No matching stashed itches.':'Nothing stashed yet.'):view==='wins'?'No W’s yet today.':'Nothing open. W.'}</h3><p>${stashFilter?(words.length?'Try different words, or choose All to search other stages.':'Stash an itch from Now. It appears here while waiting to be sent to T3.'):view==='wins'?'Test a fix, then hit “We’re so back” when it slaps.':'Stash an itch up top, or hit THAT. to bookmark the moment.'}</p></div>`;
  }
  if(selected)renderDetail();
  DMUI.sync();
}
function setView(next,pageData=null){
  if(!pageViews.includes(next))return;
  const wasSettings=view==='setup';if(next==='setup'&&!wasSettings){workspaceView=view;workspaceScroll=scrollY;}
  DMIntake.cancelSuggestions();view=next;filter='all';feedPage=0;
  document.querySelectorAll('[data-view]').forEach(b=>b.classList.toggle('active',b.dataset.view===view));
  $('#view-name').textContent=({now:'Now',inbox:'Itch pile',wins:'W’s',tools:'Side quests',git:'Git',browse:'Browse',setup:'Settings'})[view];
  document.querySelectorAll('[data-filter]').forEach(b=>b.classList.toggle('active',b.dataset.filter===filter));
  render();
  let entering;
  if(view==='git')entering=DMGit.enter(pageData?.git);
  if(view==='browse')entering=DMBrowse.enter();
  if(view==='tools'){if(toolTab==='inspiration')entering=DMInspiration.enter(pageData?.inspiration);else{entering=loadCommands(true).then(()=>renderTools()).catch(e=>toast(e.message));}}
  if(view==='wins')DMSocial.checkPosts(false);
  DMChat.workspace(view==='now');
  if(view==='setup'){window.scrollTo(0,0);if(settingsTab==='replay')loadWindows();else if(settingsTab==='shortcuts')nativeControl();else if(settingsTab==='posting')DMWebhook.loadSettings();else if(settingsTab==='ai')DMAI.load();else if(settingsTab==='bridge')DMBridge.load();else if(settingsTab==='connections')DMT3.load();}
  else if(wasSettings)window.scrollTo(0,workspaceScroll);
  else window.scrollTo(0,0);
  rememberPage();return entering;
}
function rank(query,candidate){
  const q=query.toLowerCase().trim().replace(/^@/,''), c=candidate.toLowerCase();
  if(!q)return 0;
  if(c.startsWith(q))return 100-q.length/100;
  const words=q.split(/\s+/), target=c.match(/[\p{L}\p{N}]+/gu)||[];
  let from=0;
  for(const w of words){const index=target.findIndex((t,i)=>i>=from&&t.startsWith(w));if(index<0)return c.includes(q)?65:0;from=index+1;}
  return 80-from/10;
}
async function loadCommands(){commandsLoaded=true;}
function commandMode(){const t=$('#command').value;return /^\/share(?:\s|$)/.test(t)?'share':t.startsWith('/find ')?'find':t.startsWith('/open ')?'open':t.startsWith('/chat ')?'chat-entry':t.startsWith('/')?'command':DMChat.enabled?'chat':DMIntake.splitting?'split':'itch';}
function updateSuggestions(){
  const started=performance.now(), input=$('#command').value, mode=commandMode();
  let pool=[],query=input;
  if(mode==='chat'){
    pool=DMChat.candidates().map(label=>({type:'T3 context',label,value:label}));
  }else if(mode==='chat-entry'){
    query='';pool=[{type:'T3 chat',label:'Chat in the pinned T3 thread',value:'/chat '}];
  }else if(mode==='find'){
    query=input.slice(6);pool=state.itches.filter(DMIntake.usable).map(r=>({type:'saved itch',label:r.title,value:r.id,search:r.title+' '+r.key}));
  }else if(mode==='share'){
    query=input.slice(6).trim();pool=state.itches.filter(DMSocial.eligible).map(r=>({type:'completion',label:r.title,value:r.id,search:r.title+' '+r.id}));
  }else if(mode==='open'){
    query=input.slice(6);pool=state.contexts.map(c=>({type:'T3 thread',label:contextTitle(c),value:c.id,search:[c.project,c.task,c.thread_id,contextTitle(c)].join(' ')}));
  }else if(mode==='command'){
    pool=[{type:'social',label:'/share ? preview a completion post',value:'/share '},{type:'T3 chat',label:'/chat — talk to a T3 thread',value:'/chat '},{type:'find',label:'/find — search saved itches',value:'/find '},{type:'T3 thread',label:'/open — jump to a T3 thread',value:'/open '}];query=input.slice(1);
  }else{
    const ctx=context();
    pool=[...(ctx?.candidates||[]).map(label=>({type:'context',label,value:label})),
      ...state.itches.filter(r=>r.project===project&&DMIntake.usable(r)).map(r=>({type:'this again',label:r.title,value:r.title,data:r}))];
  }
  const seen=new Set();
  suggestions=pool.map(p=>({...p,score:query.trim()?Math.max(rank(query,p.search||p.label),['itch','chat'].includes(mode)?DMIntake.fuzzy(query,p.label):0):70})).filter(p=>p.score>0&&(!['itch','chat'].includes(mode)||p.value.trim().toLowerCase()!==input.trim().toLowerCase())&&!seen.has(p.label)&&seen.add(p.label)).sort((a,b)=>b.score-a.score).slice(0,5);
  suggestions=[...suggestions,...DMIntake.localWords(input,mode,pool)].sort((a,b)=>b.score-a.score).filter((s,i,all)=>all.findIndex(p=>p.value===s.value)===i).slice(0,5);
  const assisted=DMIntake.offer(input,mode,pool);
  if(assisted?.items?.length)suggestions=assisted.items.slice(0,5).map(s=>({label:s.text,value:s.text,kind:s.kind,quality:s.quality,type:s.kind==='idea'?'idea':s.source==='jev'?'Jev':s.kind==='word'?'word':'context'}));
  if(mode==='split'||(['itch','chat'].includes(mode)&&input.trim().length<2))suggestions=[];
  suggestionIndex=-1;
  $('#stash').innerHTML=mode==='split'?'Split it ↵':mode==='chat'?(DMChat.sending?'Sending…':'Send to T3 ↵'):mode==='chat-entry'?'Open chat ↗':mode==='find'?'Find it ↵':mode==='open'?'Open thread ↗':'Stash it <span>↵</span>';
  $('#stash').disabled=saving||DMUploads.busy||DMIntake.splitBusy||(mode==='chat'&&DMChat.sending);
  $('#command').maxLength=mode==='split'?4000:mode==='chat'?12000:500;
  $('#command').placeholder=mode==='split'?'fix the login, add search, make the buttons bigger…':mode==='chat'?'message your T3 thread…':'a few words… or / for commands';
  $('#command-label').textContent=mode==='split'?'drop the whole batch':mode==='chat'?'say it to T3':mode==='itch'?'what’s scuffed?':mode==='find'?'search itches':'pick a command';
  DMIntake.decorate();
  if(mode==='split')$('#input-hint').innerHTML='<kbd>Enter</kbd> preview separate itches';
  else $('#input-hint').innerHTML=['itch','chat'].includes(mode)?'<kbd>Tab</kbd> autocomplete <span>·</span> <kbd>Enter</kbd> '+(mode==='chat'?'send':'stash'):'<kbd>↑ ↓</kbd> pick <span>·</span> <kbd>Enter</kbd> run it';
  drawSuggestions();
  signal(DMIntake.pending?'Finding continuations…':DMIntake.notice|| (mode==='split'?'Separate itches. Preview before saving.':mode==='chat'?(DMChat.sending?'Sending…':suggestions.length?suggestions.length+' matches · Tab to use one':input.trim()?'Enter sends exactly what you typed.':'Type to message T3.'):mode==='itch'?(suggestions.length?suggestions.length+' matches · Tab to use one':'Type a couple letters for suggestions.'):
    suggestions.length+' '+(mode==='command'?'commands':'matches')),DMIntake.pending?(state.typing_generator?.configured?'MERCURY':'JEV'):DMIntake.source==='mercury'?'MERCURY':mode==='itch'?'LOCAL':'COMMANDS',DMIntake.pending?'load':mode==='itch'?'orbit':'deck');
  $('#command').dataset.rankMs=(performance.now()-started).toFixed(2);
  lastInputMode=mode;
}
function suggestionLabel(s){
  if(s.kind==='idea')return s.quality||s.label;
  if(s.kind==='word')return s.value.match(/\S+$/)?.[0]||s.label;
  if(s.kind==='continuation'){const input=$('#command').value,start=input.match(/\S+$/)?.index??input.length;return '… '+s.value.slice(start);}
  return s.label;
}
function drawSuggestions(){
  const mode=commandMode(), pending=DMIntake.pending;
  const visible=(suggestions.length>0||pending)&&document.activeElement===$('#command');
  $('#suggestions').hidden=!visible;$('#command').setAttribute('aria-expanded',String(visible));
  $('#suggestions').setAttribute('aria-busy',String(pending));
  if(suggestionIndex>=0)$('#command').setAttribute('aria-activedescendant','suggestion-'+suggestionIndex);else $('#command').removeAttribute('aria-activedescendant');
  $('#suggestions').innerHTML=`<div class="suggestion-heading" role="presentation">${DMUI.ascii(pending?'load':mode==='command'?'deck':'orbit')}<span>${pending?'LOADING':mode==='command'?'COMMANDS':'SUGGESTIONS'}</span><small>${pending?'…':suggestions.length+' FOUND'}</small></div>`+suggestions.map((s,i)=>`<button id="suggestion-${i}" class="suggestion ${i===suggestionIndex?'selected':''}" data-suggestion="${i}" data-kind="${esc(s.kind||'phrase')}" role="option" aria-selected="${i===suggestionIndex}" tabindex="-1"><small>${esc(s.type)}</small><span>${esc(suggestionLabel(s))}</span><kbd>${i===suggestionIndex?'Enter':'Tab'}</kbd></button>`).join('');
  if(pending&&!suggestions.length)$('#suggestions').innerHTML+='<div class="suggestion-loading">'+DMUI.ascii('scan')+'<span>'+(DMIntake.pending?'Thinking of useful directions…':'Finding suggestions…')+'</span></div>';
  DMIntake.renderGhost();
}
async function choose(index,run=false){
  const s=suggestions[index];if(!s)return;
  const mode=commandMode();
  if(['itch','chat'].includes(mode)){ DMIntake.cancelSuggestions();$('#command').value=s.value;$('#command').focus();$('#suggestions').hidden=true;suggestions=[];suggestionIndex=-1;return; }
  if(mode==='chat-entry'){const text=$('#command').value.slice(6);$('#command').value=text;return DMChat.mode(true);}
  if(mode==='command'){if(s.value==='/share '&&run)return DMSocial.show();if(s.value==='/chat '){$('#command').value='';return DMChat.mode(true);}$('#command').value=s.value;$('#command').focus();updateSuggestions();return;}
  if(mode==='share')return DMSocial.show('',s.value);
  if(mode==='find'){setView('inbox');DMItches.open(s.value);$('#command').value='';$('#suggestions').hidden=true;return;}
  if(mode==='open'){const c=state.contexts.find(x=>x.id===s.value);if(c)location.href='t3-thread://v1/'+c.thread_id;}
}
async function submit(){
  const input=$('#command').value.trim(), mode=commandMode();
  DMIntake.cancelSuggestions();
  if(mode==='split')return DMIntake.previewSplit();
  if(mode==='chat')return DMChat.send(input);
  if(mode==='chat-entry'){$('#command').value=input.slice(6).trim();return DMChat.mode(true);}
  if(mode==='share'){const query=input.slice(6).trim();return DMSocial.show(query,/^[a-f0-9]{32}$/.test(query)?query:'');}
  if(mode==='find'){$('#search').value=input.slice(6);setView('inbox');return;}
  if(mode==='open'){if(suggestions.length)return choose(0,true);return toast('No published thread matches.');}
  if(mode==='command'){if(suggestions.length)return choose(0,true);return;}
  if(input||DMUploads.itchAttachments.length)await capture(false);
}
async function capture(moment){
  if(saving)return;
  if(!moment&&DMUploads.busy)return toast('Receipts still uploading. Give it a sec.');
  const attachments=moment?[]:DMUploads.itchAttachments;
  const title=moment?'':$('#command').value.trim();if(!title&&!moment&&!attachments.length)return;
  if(title.length>500)return toast('Keep it under 500 characters. Add details after.');
  const args={title,moment,attachments:JSON.stringify(attachments.map(a=>a.id)),project,context_id:context()?.id||'',context_snapshot:JSON.stringify(context()||{}),use_active:false,event_at:new Date().toISOString(),request_key:uid()};
  saving=true;$('#stash').disabled=true;DMUploads.render();
  if(!moment){$('#command').value='';updateSuggestions();}
  try{
    let row;
    try {row=await call('manager.capture',args);}
    catch(e){
      if(!e.network)throw e;
      if(outbox.length>=32)throw new Error('Browser outbox is full. Reconnect DumbAPI before saving more.');
      outbox.push(args);stashOutbox();toast('Stashed locally · syncs when DumbAPI is back');
    }
    if(!moment)DMUploads.commit('@itch',attachments);
    if(row){merge(row);selected=row.id;render();window.DMAquarium?.celebrate?.('stash',$('#stash'));toast(moment?'THAT. Moment saved.':'Stashed. Back to it.',()=>change(row.id,{state:'archived'}));}
  }catch(e){if(!moment&&!$('#command').value){$('#command').value=title;updateSuggestions();}toast(e.message);}
  finally{saving=false;DMUploads.render();updateSuggestions();}
}
function planMarkup(row){
  if(!row.plan.length)return '<p>No plan yet. Send it to T3 to get one.</p>';
  if(row.plan.length===1)return '<p>'+esc(row.plan[0].text)+'</p>';
  if(row.plan.length<=3)return '<ol>'+row.plan.map(t=>'<li>'+esc(t.text)+'</li>').join('')+'</ol>';
  return row.plan.map(t=>`<label class="task"><input type="checkbox" data-task="${esc(t.id)}" ${t.done?'checked':''}><span>${esc(t.text)}</span></label>`).join('');
}
function kitchenMode(r,recook=false){
  const moves=r.plan.filter(t=>!t.done),status=itchStatus(r);
  const active=!recook&&['working','queued'].includes(status.kind);
  const review=!recook&&!active&&(status.kind==='ready'||r.state==='resolved'||(r.plan.length>0&&!moves.length));
  return {moves,review,active,status};
}
function kitchenMarkup(r,mode){
  const {moves,review,active,status,refactoring}=mode,accepted=r.state==='resolved';
  const title=refactoring?'One more pass.':review?(accepted?'Handled. W.':'Ready to test.') :active?status.label:moves.length?'Next move':'No plan yet.';
  const copy=refactoring?'What should change?':review?(accepted?'One less dumb thing.':r.plan.length?`${r.plan.length} steps done. Try it, then call it.`:'Try it, then call it.') :active?'T3 has it.':moves.length?moves[0].text:'Send it to T3 to get a fix cooking.';
  const actions=review?`<div class="review-actions">${['ready','resolved'].includes(status.kind)?'<button type="button" class="secondary" data-review-learn>Learn this itch &#8599;</button>':''}${r.test_url?`<a class="secondary" href="${esc(r.test_url)}" target="_blank" rel="noopener">Test it ↗</a>`:''}<button type="button" class="primary" data-review-refactor>Refactor ↗</button>${!accepted?`<button type="button" class="secondary" data-review-accept>We’re so back ✳</button>`:''}</div>`:'';
  return `<div class="cook-heading">${DMUI.ascii(review?'spark':'cook','cook-art')}<div><span class="eyebrow">${review?'YOUR CALL':active?'COOKING':'NEXT MOVE'}</span><h3 id="itch-next-title">${esc(title)}</h3><p class="cook-preview" title="${esc(copy)}">${esc(copy)}</p>${actions}</div></div>`;
}
function renderDetail(){
  const r=state.itches.find(i=>i.id===selected);if(!r)return;
  const postingSignature=JSON.stringify(r.posting);
  if(renderedDetailId===r.id&&renderedDetailVersion===r.version&&renderedPosting===postingSignature)return;
  renderedPosting=postingSignature;
  renderedDetailId=r.id;renderedDetailVersion=r.version;
  const c=r.context;
  $('#detail').innerHTML=`<span class="eyebrow">${esc(r.project)} / ${itchStatus(r).label}</span><h2 id="itch-title">${esc(r.title)}</h2>${DMSocial.badge(r,true)}`;
  $('#itch-plan-details').hidden=!r.plan.length;
  $('#itch-plan-summary').textContent=`Plan · ${r.plan.filter(t=>t.done).length}/${r.plan.length} done`;
  $('#itch-plan').innerHTML=planMarkup(r);
  $('#itch-notes-content').innerHTML=`<h3>What you typed</h3><p>${esc(r.original||r.title)}</p><span class="key">${esc(r.key)}</span>
  <h3>Context</h3><p>${c?esc(c.testing||c.task)+' · '+age(c.updated_at):'No thread pinned.'}</p>
  ${r.recheck?'<h3>Recheck · '+esc(r.recheck.status.replaceAll('_',' '))+'</h3><p>'+esc(r.recheck.summary||r.recheck.evidence||'')+'</p>':''}
  ${r.next_step?'<h3>Next step from T3</h3><p>'+esc(r.next_step)+'</p>':''}
  ${r.feedback.length?'<h3>Last feedback</h3><p>'+esc(typeof r.feedback.at(-1)==='string'?r.feedback.at(-1):r.feedback.at(-1).text||JSON.stringify(r.feedback.at(-1)))+'</p>':''}
  ${r.evidence.length?'<h3>Receipts</h3><p>'+esc(r.evidence.map(x=>typeof x==='string'?x:JSON.stringify(x)).join('\n'))+'</p>':''}
  ${r.outcomes.length?'<h3>W’s</h3><p>'+esc(r.outcomes.map(o=>o.summary+' · '+age(o.at)).join('\n'))+'</p>':''}`;
  $('#replay-detail').replaceChildren();$('#replay-detail').hidden=true;
  $('#itch-extra-actions').innerHTML=`<button data-action="accept" ${r.state==='resolved'?'disabled':''}>We're so back &#10035;</button><button data-action="feedback">Still scuffed</button><button data-action="repeat">Happened again</button>${r.test_url?'<a href="'+esc(r.test_url)+'" target="_blank" rel="noopener">Test it &#8599;</a>':'<button data-action="edit">Add test link</button>'}<button data-action="replay">Replay</button><button data-action="brief">Copy brief &#8599;</button><button data-action="feel">Change the vibe&#8230;</button>${c?'<a href="t3-thread://v1/'+esc(c.thread_id)+'">Open in T3 &#8599;</a>':''}<button class="itch-archive" data-action="archive">Archive</button>`;
  DMItches.decorate();
}
function dialog(title,html,saveLabel,handler){
  const sequence=++dialogSequence;$('#dialog-content').onclick=null;
  $('#dialog-title').textContent=title;$('#dialog-content').innerHTML=html;$('#dialog-save').textContent=saveLabel;
  $('#dialog-save').onclick=async()=>{
    const button=$('#dialog-save');button.disabled=true;
    try{const result=await handler();if(result!==false&&sequence===dialogSequence&&$('#editor').open)$('#editor').close();}
    catch(e){toast(e.message);}
    finally{button.disabled=false;}
  };
  $('#editor').showModal();
}
async function copy(text){try{await navigator.clipboard.writeText(text);toast('Copied.');return true;}catch{toast('Couldn’t copy. Select the text and copy it.');return false;}}
async function brief(direction=''){
  const r=await call('manager.brief',{id:selected,direction});
  await change(selected,{run_state:'brief_ready'});
  dialog('Brief for T3',`<p>Paste this into the T3 thread to start work.</p><textarea id="brief-text" rows="12" readonly>${esc(r.brief)}</textarea>${r.thread_url?'<p><a href="'+esc(r.thread_url)+'">Open in T3 ↗</a></p>':''}`,'Copy',()=>copy(r.brief));
}
function editItch(){
  const r=state.itches.find(x=>x.id===selected);
  dialog('Edit itch',`<label for="edit-title">What happened?</label><input id="edit-title" maxlength="500" value="${esc(r.title)}"><label for="edit-outcome">What should happen instead?</label><textarea id="edit-outcome">${esc(r.desired_outcome)}</textarea><label for="edit-plan">Steps · one per line</label><textarea id="edit-plan">${esc(r.plan.map(t=>t.text).join('\n'))}</textarea><p>4+ steps turn into a checklist.</p><label for="edit-next">Next step</label><input id="edit-next" value="${esc(r.next_step)}"><label for="edit-test">Test link</label><input id="edit-test" value="${esc(r.test_url)}" placeholder="http://127.0.0.1:…">`,'Save',async()=>{
    const lines=$('#edit-plan').value.split('\n').map(t=>t.trim()).filter(Boolean);
    const taken=new Set();
    const plan=lines.map(text=>{const old=r.plan.find(t=>t.text===text&&!taken.has(t.id));if(old){taken.add(old.id);return old;}return {id:uid(),text,done:false};});
    await change(r.id,{title:$('#edit-title').value,desired_outcome:$('#edit-outcome').value,plan,next_step:$('#edit-next').value,test_url:$('#edit-test').value},r.version);toast('Saved.');
  });
}
function editContext(seed){
  const c=seed?.thread_id?seed:context();
  dialog('What are you testing?',`<p>Keeps suggestions on-topic. Project: ${esc(project)}.</p><label for="ctx-thread">Exact T3 thread ID</label><input id="ctx-thread" value="${esc(c?.thread_id||'')}"><label for="ctx-task">Current task</label><input id="ctx-task" value="${esc(c?.task||'')}"><label for="ctx-testing">Testing right now</label><input id="ctx-testing" value="${esc(c?.testing||'')}"><label for="ctx-candidates">Likely itches · one per line</label><textarea id="ctx-candidates">${esc((c?.candidates||[]).join('\n'))}</textarea>`,'Pin it',async()=>{
    await call('manager.context.publish',{project,thread_id:$('#ctx-thread').value,task:$('#ctx-task').value,testing:$('#ctx-testing').value,candidates:JSON.stringify($('#ctx-candidates').value.split('\n').map(t=>t.trim()).filter(Boolean)),workspace:c?.workspace||'',source:'user_entered',select:true,request_key:uid()});
    await refresh();toast('Context pinned.');
  });
}



// View-only tools deck. Domain operations continue through DumbAPI.
const toolQueries={};



function renderTools(){
  if(view!=='tools')return;
  const root=$('#tool-results'),same=root.dataset.tab===toolTab;
  if(same&&toolTab==='social')DMSocial.capture();
  const open=same?[...root.querySelectorAll('details[open]')].map(n=>n.id).filter(Boolean):[];
  const active=root.contains(document.activeElement)?document.activeElement:null,key=active?.id,caret=active?.selectionStart;
  const scroll=root.querySelector('#tool-panel')?.scrollTop||0;
  $('#feed-count').textContent='[ '+toolTab.toUpperCase()+' ]';
  const tabs=[['inspiration','Inspiration'],['social','Social']];
  const html='<div class="tool-tabs" role="tablist" aria-label="Side quests">'+tabs.map(([id,label])=>`<button type="button" id="tool-tab-${id}" role="tab" data-tool-tab="${id}" aria-selected="${toolTab===id}" aria-controls="tool-panel" tabindex="${toolTab===id?0:-1}">${label}</button>`).join('')+'</div>';
  root.innerHTML=html+`<section id="tool-panel" class="tool-panel" role="tabpanel" aria-labelledby="tool-tab-${toolTab}">${toolTab==='inspiration'?DMInspiration.markup():DMSocial.markup()}</section>`;
  root.dataset.tab=toolTab;
  for(const id of open){const el=document.getElementById(id);if(el?.tagName==='DETAILS')el.open=true;}
  if(key){const el=document.getElementById(key);if(el){el.focus({preventScroll:true});if(caret!=null&&el.setSelectionRange)try{el.setSelectionRange(caret,caret);}catch{}}}
  $('#tool-panel').scrollTop=scroll;
  DMUI.sync();if(toolTab==='social')DMSocial.mounted();if(toolTab==='inspiration')DMInspiration.mounted();
}
function renderSetup(){
  $('#feed-count').textContent='[ '+settingsTab.toUpperCase()+' ]';
  const root=$('#tool-results'),signature=JSON.stringify([settingsTab,state.preferences.motion,document.body.classList.contains('light'),replayWindows,selectedReplayWindow,state.typing_generator,DMT3.signature(),DMWebhook.signature(),DMAI.signature(),DMBridge.signature()]);
  if(root.dataset.settingsSignature===signature&&$('#settings-panel')){renderShortcuts();return;}
  root.dataset.settingsSignature=signature;
  const tabs={shortcuts:'Shortcuts',replay:'Replay',appearance:'Appearance',connections:'Connections',ai:'AI integrations',bridge:'DumbBridge',posting:'Posting',data:'Data'};
  const content={
    shortcuts:'<div class="tool-card shortcut-card" id="shortcut-card"></div>',
    replay:`<div class="tool-card"><h3>Replay</h3><p>Records a short clip of the app you’re testing so you can show what broke. Pick the window, then turn it on.</p><select id="replay-window" aria-label="Test window">${replayWindows.map(w=>'<option value="'+esc(w.hwnd)+'" '+(selectedReplayWindow===w.hwnd?'selected':'')+'>'+esc(w.title)+'</option>').join('')||'<option value="">Refresh apps to choose one</option>'}</select><div class="detail-actions"><button class="primary" data-action="arm">Turn replay on</button><button class="secondary" data-action="disarm">Turn off</button><button class="secondary" data-action="windows">Refresh apps</button></div><p>6 seconds before · up to 18 during · 6 after. One selected window, no audio. Check the frames: some games may appear blank.</p><details><summary>Storage & capture details</summary><p>640×360 at 10 fps. Temporary boards expire after 24 hours. 20 MiB per event, 256 MiB total; kept boards share a 128 MiB budget.</p></details><p id="replay-error">${esc(replayState.error||'')}</p></div>`,
    appearance:`<div class="tool-card"><h3>Appearance</h3><div class="setting-row"><div><strong>Theme</strong><p>Dark or light.</p></div><button class="secondary" data-action="theme">${document.body.classList.contains('light')?'Switch to dark':'Switch to light'}</button></div><div class="setting-row"><div><strong>Motion</strong><p>Sharks and little animations. Respects reduced motion.</p></div><button class="secondary" data-action="motion">${state.preferences.motion?'Pause motion':'Turn motion on'}</button></div></div>`,
    connections:DMT3.markup(),
    data:'<div class="tool-card"><h3>Your data</h3><p>Saved locally through DumbAPI. Unsynced stashes wait in this browser.</p><button class="secondary" data-action="export">Export my itches</button><details><summary>What powers suggestions?</summary><p>Your pinned task, testing notes and recent messages from the selected T3 thread. Words appear immediately. Mercury 3 finishes unfinished sentences and creates fresh qualities after a typing pause; Jev ranks source matches. Recent selected-thread context and matching ideas are cached briefly. Local word/source matches work offline. Tab accepts; Enter keeps your words.</p></details></div>'
  };
  content.connections='<div class="tool-card"><h3>Workspace</h3><p>Choose the folder you want source tools and scouts to read. Nothing is selected on a fresh install.</p><form id="workspace-form"><label for="workspace-path">Existing folder</label><input id="workspace-path" autocomplete="off" placeholder="Absolute path to your project"><button class="secondary" type="submit">Use folder</button><button class="quiet" type="button" id="workspace-forget">Clear selection</button></form><p id="workspace-status" role="status"></p></div>'+content.connections;
  content.posting=DMWebhook.settingsMarkup();
  content.ai=DMAI.settingsMarkup();
  content.bridge=DMBridge.settingsMarkup();
  content.connections+='<div class="tool-card"><h3>Fresh ideas</h3><p>Mercury 3 · '+(state.typing_generator?.configured?'connected':'off')+'. New suggestions from your current project and thread.</p><button class="secondary" data-action="typing-model">'+(state.typing_generator?.configured?'Manage Mercury':'Connect Mercury')+'</button></div>';
  $('#tool-results').innerHTML='<div class="settings-navigation"><button class="text-link" data-action="back-to-work">← Back</button><div class="settings-tabs" role="tablist" aria-label="Settings categories">'+Object.entries(tabs).map(([id,name])=>'<button id="settings-tab-'+id+'" role="tab" aria-selected="'+(id===settingsTab)+'" aria-controls="settings-panel" tabindex="'+(id===settingsTab?'0':'-1')+'" data-settings="'+id+'">'+name+'</button>').join('')+'</div></div><section id="settings-panel" role="tabpanel" aria-labelledby="settings-tab-'+settingsTab+'">'+content[settingsTab]+'</section>';
  if($('#replay-window'))$('#replay-window').insertAdjacentHTML('beforebegin','<p id="settings-replay-state" class="amber">'+(replayState.armed?'[ ● ] Replay on · '+esc(replayState.window?.title):'[ ○ ] Replay off')+'</p>');
  renderShortcuts();DMUI.sync();DMAI.sync();DMBridge.sync();DMT3.sync();
}
function selectSettings(tab){
  if(!['shortcuts','replay','appearance','connections','ai','bridge','posting','data'].includes(tab))return;
  settingsTab=tab;renderSetup();rememberPage();
  if(tab==='shortcuts')nativeControl();
  if(tab==='replay')loadWindows();
  if(tab==='posting')DMWebhook.loadSettings();
  if(tab==='ai')DMAI.load();
  if(tab==='bridge')DMBridge.load();
  if(tab==='connections')DMT3.load();
  $('#settings-tab-'+tab).focus({preventScroll:true});
}
function renderShortcuts(){
  const root=$('#shortcut-card');if(!root)return;
  const expanded=root.querySelector('details')?.open,focused=root.contains(document.activeElement)?document.activeElement.dataset.action:null;
  const running=nativeState.running,test=nativeState.test_remaining||0,hits=nativeState.test_hits||[],key=id=>nativeState.bindings?.[id],names={1:'Stash an itch',2:'Mark the moment',3:'Quick panel',4:'Let it cook',5:'Snip evidence'};
  const row=(id,description)=>`<div class="shortcut-row"><div><strong>${names[id]}</strong><span>${description}</span></div><div class="shortcut-key"><kbd>${esc(key(id)||'Not available')}</kbd>${hits.includes(id)?'<small>✓ Detected</small>':''}</div></div>`;
  root.innerHTML=`<div class="shortcut-heading"><h3>Global shortcuts</h3><span class="key ${running?'amber':''}">${running?'[ + ] Helper connected':'[ — ] Off'}</span></div><p>Catch it. Note it. Snip it. From any app.</p>${row(1,'Opens a small box. Describe it, then Enter to save.')}${row(2,'Saves the moment, then opens a quick note popup.')}${row(5,'Drag a box. Adds a receipt to the open itch or a new draft.')}${row(4,'Sends the open itch + evidence to its chosen T3 thread. Open its popup first.')}<div class="detail-actions"><button class="${running?'secondary':'primary'}" data-action="native-start" ${nativeBusy?'disabled':''}>${nativeBusy?'Connecting…':running?'Refresh status':'Fix / enable keys'}</button><button class="primary" data-action="native-test" ${nativeBusy||test?'disabled':''}>${test?'Listening… '+test+'s':'Test shortcuts'}</button></div><p class="shortcut-check" role="status" aria-live="polite">${test?DMUI.ascii('scan')+' Switch to another app and press a shortcut. Nothing is saved during this '+test+'s check.':hits.length?'Detected: '+hits.map(id=>names[id]).join(', ')+'. Press again to use normally.':nativeState.note?esc(nativeState.note):'Start a check, then press the keys from any app. The results appear here.'}</p>${nativeState.shortcut_conflicts?.length?'<p class="amber">Some keys are busy: '+esc(nativeState.shortcut_conflicts.join(', '))+'. Other available shortcuts still work.</p>':''}<details><summary>More shortcuts & help</summary>${row(3,'Opens capture with your recent itches.')}<p><kbd>Ctrl K</kbd> Jump to the chat/stash line · this page only.</p><p>The displayed keys are the ones Windows assigned. If a key is busy, a backup combination is shown. Keep DumbManager running.</p><button class="secondary" data-action="context">Change testing context</button></details>`;
  if(expanded)root.querySelector('details').open=true;
  if(focused)root.querySelector('[data-action="'+focused+'"]')?.focus({preventScroll:true});
  DMUI.sync();
}
async function nativeControl(action='status'){
  if(action==='status'&&(view!=='setup'||settingsTab!=='shortcuts'))return;
  if(nativeBusy)return;nativeBusy=true;renderShortcuts();
  try{nativeState=await post('/api/native',{action});renderShortcuts();}
  catch(e){toast(e.message);}
  finally{nativeBusy=false;renderShortcuts();clearTimeout(nativeTimer);if(view==='setup'&&settingsTab==='shortcuts')nativeTimer=setTimeout(()=>nativeControl(),nativeState.test_remaining?1000:5000);}
}
async function loadWindows(){
  try{await nativeControl();const data=await replay('windows');replayWindows=data.items;if(!replayWindows.some(w=>w.hwnd===selectedReplayWindow))selectedReplayWindow=replayWindows.find(w=>w.hwnd===replayState.window?.hwnd)?.hwnd||replayWindows[0]?.hwnd||'';if(view==='setup')renderSetup();}
  catch(e){toast(e.message);}
}
async function replayStatus(){
  try{
    replayState=await replay('status');$('#replay-dot').textContent=replayState.armed?'●':'○';
    $('#replay-label').textContent=replayState.armed?'Replay on':'Replay off';$('#replay-dot').classList.toggle('on',!!replayState.armed);
    const replaySummary=replayState.error||(replayState.armed?(replayState.window?.title||'')+' · '+replayState.buffer_seconds+'s buffered':'Turn on in Settings when testing.');
    $('#replay-summary').textContent=replaySummary;$('#replay-dot').closest('button')?.setAttribute('title',replaySummary);
    if($('#settings-replay-state'))$('#settings-replay-state').textContent=replayState.armed?'[ ● ] Replay on · '+replayState.window.title:'[ ○ ] Replay off';
  }catch{}
}
async function frameboard(){
  const id=selected;
  const data=await replay('item',{id});
  if(!data.available){toast(data.pending?'Finishing the last 6 seconds…':'No replay for this itch. Turn replay on before it happens.');return;}
  const area=$('#replay-detail');area.hidden=false;
  area.innerHTML=`<h3>Replay · ${data.duration.toFixed(1)}s</h3><p>${data.frames.length} frames · ${(data.bytes/1048576).toFixed(1)} MiB${data.truncated?' · capture truncated':''}${data.keep?' · kept':' · expires after 24h'}</p><img class="frameboard" alt="Selected test-window replay" id="replay-image"><input id="frame-index" class="frame-slider" type="range" min="0" max="${data.frames.length-1}" value="0" aria-label="Replay frame"><span id="frame-time" class="key"></span><div class="detail-actions"><button class="secondary" id="replay-play">Play</button><button class="secondary" id="replay-keep">${data.keep?'Unpin':'Keep clip'}</button><button class="quiet" id="replay-delete">Delete replay</button></div>`;
  let loading=false, playing=false,timer;
  async function show(index){if(loading)return;loading=true;try{const blob=await post('/api/replay',{action:'frame',id,index},true);if(frameObject)URL.revokeObjectURL(frameObject);frameObject=URL.createObjectURL(blob);if($('#replay-image')){$('#replay-image').src=frameObject;$('#frame-time').textContent=data.frames[index].toFixed(1)+'s';}}finally{loading=false;}}
  $('#frame-index').oninput=e=>show(Number(e.target.value));
  $('#replay-play').onclick=()=>{playing=!playing;if(!playing){clearInterval(timer);$('#replay-play').textContent='Play';return;}$('#replay-play').textContent='Pause';timer=setInterval(()=>{if(selected!==id||!$('#frame-index')||document.hidden){clearInterval(timer);return;}let i=Number($('#frame-index').value)+1;if(i>=data.frames.length)i=0;$('#frame-index').value=i;show(i);},100);};
  $('#replay-keep').onclick=async()=>{try{await replay('keep',{id,keep:!data.keep});clearInterval(timer);await frameboard();}catch(e){toast(e.message);}};
  $('#replay-delete').onclick=async()=>{clearInterval(timer);await replay('delete',{id});area.innerHTML='';toast('Replay deleted.');};
  await show(0);
}
async function action(name){
  if(name==='tool-home'){toolResults[toolTab]=null;toolResult=null;renderTools();return;}
  const r=state.itches.find(x=>x.id===selected);
  if(name==='connect-t3'){const b=$('#connect-t3');if(b?.disabled)return;if(b){b.disabled=true;b.innerHTML=DMUI.ascii('load')+' Connecting…';}try{toast((await call('t3.connect')).note);}finally{if(b?.isConnected){b.disabled=false;b.textContent='Reconnect local T3';}}return;}
  if(name==='chat-mode'){if(view!=='now')setView('now');return DMChat.mode(true);}
  if(name==='context')return editContext();
  if(name==='back-to-work')return setView(workspaceView);
  if(name==='native-start')return nativeControl('start');
  if(name==='native-test')return nativeControl('test');
  if(name==='send-itch')return DMItches.cook(selected);
  if(name==='brief')return brief();
  if(name==='edit')return editItch();
  if(name==='feel')return dialog('Change the vibe','<label for="feel">How should it feel?</label><input id="feel" placeholder="snappier, softer, more chaotic…"><p>Makes a follow-up brief. The original itch stays.</p>','Make brief',async()=>{const dir=$('#feel').value;$('#editor').close();await brief(dir);});
  if(name==='accept')return dialog('We’re so back.','<label for="accept-summary">What feels better now?</label><input id="accept-summary" value="'+esc(r.desired_outcome||r.title)+'"><label for="accept-evidence">How did you test it? (optional)</label><input id="accept-evidence" placeholder="Tried it in the test window…">','Call it ✳',async()=>{
    const row=await call('manager.complete',{id:r.id,summary:$('#accept-summary').value,evidence:$('#accept-evidence').value,accepted:true,request_key:uid()});merge(row);document.body.classList.add('reward');setTimeout(()=>document.body.classList.remove('reward'),2500);render();window.DMAquarium?.celebrate?.('win');toast('One less dumb thing. ✳');
  });
  if(name==='feedback')return dialog('Still scuffed?','<label for="feedback">What’s still off?</label><textarea id="feedback" placeholder="A few words is enough…"></textarea>','Keep the feedback',async()=>{const text=$('#feedback').value.trim();if(!text)throw new Error('Add a few words.');await change(r.id,{state:'open',run_state:'not_sent',feedback:[...r.feedback,{at:new Date().toISOString(),text}]},r.version);toast('Noted. Back in the pile.');});
  if(name==='repeat'){merge(await call('manager.repeat',{id:r.id,request_key:uid()}));render();return toast('Counted. Happened again.');}
  if(name==='archive'){await change(r.id,{state:'archived'});return toast('Archived.',()=>change(r.id,{state:r.state}));}
  if(name==='replay')return frameboard();
  if(name==='jobs')return jobs();
  if(name==='copy-job')return copy($('#job-brief').value);
  if(name==='windows')return loadWindows();
  if(name==='arm'){replayState=await replay('arm',{hwnd:$('#replay-window').value});await replayStatus();return toast('Replay on.');}
  if(name==='disarm'){await replay('disarm');await replayStatus();return toast('Replay off.');}
  if(name==='motion'){await call('manager.settings',{motion:!state.preferences.motion});return refresh();}
  if(name==='theme'){const light=!document.body.classList.contains('light');document.body.classList.toggle('light',light);localStorage.setItem('dm-theme',light?'light':'dark');$('#theme').textContent=light?'Dark mode':'Light mode';if(view==='setup'&&settingsTab==='appearance')renderSetup();return;}
  if(name==='export'){const result=await call('manager.export');const url=URL.createObjectURL(new Blob([JSON.stringify(result,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='dumbmanager-'+new Date().toISOString().slice(0,10)+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
  if(name==='typing-model'){
    dialog('Fresh ideas',`<p>Mercury 3 creates suggestions from your typed phrase, task/testing notes and recent selected-thread messages.</p><label for="typing-key">Inception API key</label><input id="typing-key" type="password" autocomplete="off" placeholder="${state.typing_generator?.key_saved?'Saved — blank keeps it':'Inception key'}"><p>Remembered on this PC.</p>${state.typing_generator?.key_saved?'<button type="button" id="typing-off" class="quiet">Turn off</button><button type="button" id="typing-forget" class="quiet">Forget key</button>':''}`,'Save',async()=>{await call('manager.typing_configure',{api_key:$('#typing-key').value,enabled:true});$('#typing-key').value='';await refresh();toast('Fresh ideas connected.');});
    const stop=async forget=>{await call('manager.typing_configure',{enabled:false,forget});$('#typing-key').value='';$('#editor').close();await refresh();toast(forget?'Mercury key forgotten.':'Fresh ideas off.');};
    if($('#typing-off'))$('#typing-off').onclick=()=>stop(false).catch(e=>toast(e.message));if($('#typing-forget'))$('#typing-forget').onclick=()=>stop(true).catch(e=>toast(e.message));return;
  }
}
document.addEventListener('click',async e=>{
  if(!appReady)return;
  const target=e.target.closest('button,[data-itch]');if(!target)return;
  try{
    if(target.dataset.view){if(target.dataset.settingsTarget)settingsTab=target.dataset.settingsTarget;return setView(target.dataset.view);}
    if(target.dataset.settings)return selectSettings(target.dataset.settings);
    if(target.dataset.toolTab)return selectTool(target.dataset.toolTab);
    if(target.dataset.toolPage){toolPages[target.dataset.toolPage]=Number(target.dataset.page);if(target.dataset.toolPage==='itches'){feedPage=Number(target.dataset.page);render();$('#feed-items').scrollTop=0;}else{renderTools();$('#tool-panel').scrollTop=0;}return;}
    if(target.dataset.command!==undefined){if(view!=='now')setView('now');$('#command').value=target.dataset.command;$('#command').focus();updateSuggestions();return;}
    if(target.dataset.sendItch)return DMItches.cook(target.dataset.sendItch);
    if(target.dataset.itch)return DMItches.open(target.dataset.itch);
    if(target.dataset.filter){feedPage=0;filter=target.dataset.filter;document.querySelectorAll('[data-filter]').forEach(b=>b.classList.toggle('active',b.dataset.filter===filter));render();return;}
    if(target.dataset.suggestion!==undefined)return await choose(Number(target.dataset.suggestion),true);
    if(target.dataset.action)return await action(target.dataset.action);
  }catch(error){toast(error.message);}
});
$('#command').addEventListener('input',updateSuggestions);
$('#command').addEventListener('focus',()=>{replay('begin').catch(()=>{});updateSuggestions();});
$('#command').addEventListener('blur',()=>{DMIntake.cancelSuggestions();setTimeout(()=>{$('#suggestions').hidden=true;$('#command').setAttribute('aria-expanded','false');},160);});
$('#command').addEventListener('keydown',async e=>{
  try{
    if(e.key==='ArrowDown'||e.key==='ArrowUp'){if(!suggestions.length)return;e.preventDefault();suggestionIndex=(suggestionIndex+(e.key==='ArrowDown'?1:-1)+suggestions.length)%suggestions.length;drawSuggestions();}
    if(e.key==='Tab'&&suggestions.length){e.preventDefault();await choose(suggestionIndex>=0?suggestionIndex:0);}
    if(e.key==='Escape'){DMIntake.cancelSuggestions();$('#suggestions').hidden=true;suggestions=[];suggestionIndex=-1;}
    if(e.key==='Enter'){e.preventDefault();if(suggestionIndex>=0)await choose(suggestionIndex,true);else await submit();}
  }catch(error){toast(error.message);}
});
$('#stash').onclick=()=>submit().catch(e=>toast(e.message));
$('#moment').onclick=()=>capture(true);
$('#search').oninput=()=>{feedPage=0;render();};
document.addEventListener('keydown',e=>{if(e.target.matches('[data-tool-tab]')&&['ArrowLeft','ArrowRight','Home','End'].includes(e.key)){e.preventDefault();const tabs=['inspiration','social'],i=tabs.indexOf(toolTab);selectTool(tabs[e.key==='Home'?0:e.key==='End'?tabs.length-1:(i+(e.key==='ArrowRight'?1:tabs.length-1))%tabs.length]);$('#tool-tab-'+toolTab).focus();}});
$('#project').onchange=async()=>{project=$('#project').value;feedPage=0;await call('manager.context.select',{id:''});state.active_context='';renderContext();render();updateSuggestions();};
$('#context').onchange=async()=>{
  const id=$('#context').value;
  if(id.startsWith('thread:')){
    const t=contextThreads.get(id.slice(7));renderContext();
    if(t)editContext({thread_id:t.id,task:t.title});return;
  }
  try{await call('manager.context.select',{id});await refresh();updateSuggestions();}
  catch(e){renderContext();toast(e.message);}
};
$('#context').addEventListener('dm-select-open',()=>loadContextThreads());
$('#context').addEventListener('dm-select-search',e=>{clearTimeout(contextSearchTimer);const q=e.detail.query;contextSearchTimer=setTimeout(()=>loadContextThreads(q),250);});
$('#context-edit').onclick=editContext;
$('#motion').onclick=()=>action('motion').catch(e=>toast(e.message));
$('#theme').onclick=()=>action('theme');
document.addEventListener('change',async e=>{if(e.target.dataset.task){const r=state.itches.find(x=>x.id===selected);try{await change(r.id,{plan:r.plan.map(t=>t.id===e.target.dataset.task?{...t,done:e.target.checked}:t)},r.version);}catch(error){toast(error.message);await refresh();}}});
document.addEventListener('change',e=>{if(e.target.id==='replay-window')selectedReplayWindow=e.target.value;});
document.addEventListener('keydown',e=>{if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='k'){e.preventDefault();if(view!=='now')setView('now');$('#command').focus();}if(e.target.matches('[data-settings]')&&['ArrowLeft','ArrowRight','Home','End'].includes(e.key)){e.preventDefault();const tabs=['shortcuts','replay','appearance','connections','ai','bridge','posting','data'],i=tabs.indexOf(settingsTab);selectSettings(tabs[e.key==='Home'?0:e.key==='End'?tabs.length-1:(i+(e.key==='ArrowRight'?1:tabs.length-1))%tabs.length]);}});
$('#editor').addEventListener('keydown',e=>{if(e.key==='Enter'&&e.target.tagName==='INPUT'){e.preventDefault();$('#dialog-save').click();}});
document.addEventListener('visibilitychange',()=>{if(appReady&&!document.hidden){refresh();replayStatus();}});
document.addEventListener('scroll',()=>{clearTimeout(pageTimer);pageTimer=setTimeout(rememberPage,100);},true);
document.addEventListener('input',e=>{if(e.target.id==='search')rememberPage();});
document.addEventListener('click',()=>{setTimeout(rememberPage,0);});
window.addEventListener('pagehide',rememberPage);
setInterval(()=>{if(appReady&&!document.hidden&&!$('#editor').open&&!DMUI.isOpen()){refresh();replayStatus();}},15000);
async function init(){
  const page=savedPage();
  await ensureModules();DMUI.configure(()=>state.preferences.motion);
  await DMT3.init();
  DMChat.init();DMIntake.init();DMItches.init();DMLearning.init();DMResearch.init();DMGit.init();DMBrowse.init();
  if(localStorage.getItem('dm-theme')==='light'){document.body.classList.add('light');$('#theme').textContent='Dark mode';}
  showOutbox();
  try{
    const data=await call('projects.list',{limit:50});$('#project').innerHTML='<option value="unsorted">All / unsorted</option>'+data.items.map(p=>`<option value="${esc(p.id)}">${esc(p.name)}</option>`).join('');
  }catch{}
  await refresh();await replayStatus();loadCommands().catch(()=>{});
  const workspace=await call('workspace.status').catch(()=>({configured:false}));
  if(!workspace.configured){page.view='setup';page.settingsTab='connections';}
  await restorePage(page);
  restoringPage=false;appReady=true;rememberPage();
  loadContextThreads();
}
init();


document.addEventListener('submit',async e=>{
  if(e.target.id!=='workspace-form')return;e.preventDefault();
  try{await call('workspace.configure',{path:$('#workspace-path').value.trim()});location.reload();}catch(error){$('#workspace-status').textContent=error.message;}
});
document.addEventListener('click',async e=>{
  if(e.target.id!=='workspace-forget')return;
  try{await call('workspace.configure',{path:''});location.reload();}catch(error){toast(error.message);}
});
