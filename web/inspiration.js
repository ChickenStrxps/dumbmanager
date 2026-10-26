'use strict';
window.DMInspiration=(()=>{
  const categories={all:'For you',showcases:'Showcases',models:'Models',cad:'CAD & making',science:'Research',docs:'Docs'};
  const creatures={showcases:' /\\_/\\\n( o.o )  .:+\n > ^ < .:*+',models:'  .---.\n [ o o ] ::\n  |___| .:+',cad:'  .+---+.\n /  / /| :+\n+---+  | .*',science:' .o.  .o.\n  \\ / .:+\n  / \\ .:*',docs:' .-----.\n | >_  | .:\n |_____| .+'};
  const radar='           . . : . .\n       . : + * | * + : .\n     . + * :   |   : * + .\n    : * :   .--+--.   : * :\n   . + .   / . | . \\   . + .\n---:+*----(----+----)----*+:---\n   . + .   \\ . | . /   . + .\n    : * :   `--+--\'   : * :\n     . + * :   |   : * + .\n       . : + * | * + : .\n           . . : . .';
  let data=null,loading=false,busy=false,error='',message='',category='all',query='',saved=false,offset=0,seq=0,searchTimer=null,entered=false;
  let refreshing=null;try{refreshing=JSON.parse(localStorage.getItem('dm-inspiration-refresh'));}catch{}
  if(!refreshing||typeof refreshing.key!=='string'||typeof refreshing.source!=='string')refreshing=null;
  const active=()=>view==='tools'&&toolTab==='inspiration';
  const page=()=>({category,query,saved,offset});
  const date=value=>value?new Date(value).toLocaleDateString(undefined,{month:'short',day:'numeric',year:'numeric'}):'Date not supplied';
  const relative=value=>value?new Date(value).toLocaleString(undefined,{month:'short',day:'numeric',hour:'numeric',minute:'2-digit'}):'Not checked yet';
  const find=id=>data?.items.find(r=>r.id===id);
  function paint(){if(active()){renderTools();rememberPage();}}
  function keepRefresh(value){refreshing=value;try{if(value)localStorage.setItem('dm-inspiration-refresh',JSON.stringify(value));else localStorage.removeItem('dm-inspiration-refresh');}catch{}}
  async function api(name,args={}){
    const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),35000);
    try{
      const send=()=>fetch('/api/call',{method:'POST',headers:{'Content-Type':'application/json','X-DumbManager':'1'},body:JSON.stringify({name:'manager.inspiration.'+name,args}),signal:controller.signal});
      let response=await send();if(response.status===403){await fetch('/',{signal:controller.signal});response=await send();}
      const result=await response.json();if(!response.ok){const e=new Error(result.error||'Could not read Inspiration.');e.code=result.code;e.status=response.status;throw e;}return result;
    }catch(e){if(e.name==='AbortError')throw new Error('This request took too long. Your draft is kept; retry checks the same request.');throw e;}
    finally{clearTimeout(timer);}
  }
  async function load(){
    const token=++seq;loading=true;error='';paint();
    try{
      const result=await api('get',{category,query,saved,offset,limit:6});if(token!==seq)return;
      if(offset&&offset>=result.total){offset=0;return load();}
      data=result;
    }catch(e){if(token===seq)error=e.message;}
    finally{if(token===seq){loading=false;paint();}}
  }
  async function enter(value){
    entered=true;
    if(value){category=Object.hasOwn(categories,value.category)?value.category:'all';query=typeof value.query==='string'?value.query.slice(0,150):'';saved=value.saved===true;offset=Number.isInteger(value.offset)?Math.max(0,Math.min(396,value.offset)):0;}
    await load();
  }
  function mounted(){if(!entered){entered=true;queueMicrotask(()=>{if(!loading)load();});}}
  function sourceSummary(){
    if(!data)return 'Your sources, in one place.';
    const sources=data.sources.filter(s=>s.enabled&&s.kind!=='reference'),good=sources.filter(s=>s.state==='ok'),bad=sources.filter(s=>s.state==='unavailable');
    const latest=good.map(s=>s.last_success_at).filter(Boolean).sort().at(-1);
    return latest?'Checked '+relative(latest)+(bad.length?' · '+bad.length+' source'+(bad.length===1?'':'s')+' unavailable':''):'Choose your sources, then refresh now.';
  }
  function card(r,index){
    const mark=(r.id.charCodeAt(r.id.length-1)+index)%3,labels=['a new rabbit hole','worth a closer look','follow the signal'];
    const hasItch=Object.keys(r.itches||{}).length>0;
    return '<article class="inspire-card" data-category="'+esc(r.category)+'"><div class="inspire-card-top"><span class="inspire-topic">'+esc(categories[r.category])+'</span><span class="inspire-number">'+String(offset+index+1).padStart(2,'0')+'</span></div><div class="inspire-card-content"><pre class="inspire-critter" aria-hidden="true">'+esc(creatures[r.category]||creatures.showcases)+'</pre><div class="inspire-provenance">'+esc(r.source_name)+' · '+esc(date(r.published_at))+'</div><h3><a href="'+esc(r.url)+'" target="_blank" rel="noopener noreferrer">'+esc(r.title)+' <span aria-hidden="true">↗</span></a></h3>'+(r.excerpt?'<p class="inspire-excerpt">'+esc(r.excerpt)+'</p>':'<p class="inspire-excerpt inspire-no-excerpt">Open the source for the project and details.</p>')+'</div><div class="inspire-card-foot"><span>'+esc(r.provenance)+(r.relevance>=2.3?' · Jev pick':'')+'</span><span class="inspire-whisper" aria-hidden="true">'+labels[mark]+'</span></div><div class="inspire-card-actions"><button class="secondary" data-inspire-stash="'+esc(r.id)+'">'+(hasItch?'View / stash itch':'Stash as itch')+' <span aria-hidden="true">↗</span></button><button class="quiet" id="inspire-save-'+esc(r.id)+'" data-inspire-save="'+esc(r.id)+'" aria-pressed="'+!!r.saved+'">'+(r.saved?'Saved ✓':'Save')+'</button><button class="quiet inspire-hide" data-inspire-hide="'+esc(r.id)+'" aria-label="Hide '+esc(r.title)+'">Hide</button></div></article>';
  }
  function markup(){
    const total=data?.total||0;
    return '<div class="inspiration"><header class="inspire-hero"><div class="inspire-intro"><span class="inspire-kicker">SIDE QUEST  /  SIGNAL ROOM</span><h2>Something worth<br><em>making time for.</em></h2><p>Fresh builds. New primitives. Good rabbit holes.</p><div class="inspire-hero-actions"><button type="button" class="primary" id="inspire-refresh" '+(busy?'disabled':'')+'>'+(busy?'Reading sources…':refreshing?'Check refresh ↻':'Refresh now ↻')+'</button><button type="button" class="secondary" id="inspire-sources" '+(!data||busy?'disabled':'')+'>Sources <span aria-hidden="true">'+(data?data.sources.filter(s=>s.enabled).length:'')+'</span></button></div></div><div class="inspire-radar" aria-hidden="true"><pre>'+esc(radar)+'</pre><span class="inspire-scan"></span><span class="inspire-radar-label">[ STAY CURIOUS ]</span></div></header><div class="inspire-health" role="status" aria-live="polite"><span class="inspire-dot '+(busy?'reading':'')+'" aria-hidden="true"></span><span>'+esc(message||sourceSummary())+'</span></div>'+(error?'<div class="inspire-error" role="alert"><span>'+esc(error)+'</span><button class="secondary" id="inspire-retry">Try again</button></div>':'')+'<nav class="inspire-categories" aria-label="Inspiration topics">'+Object.entries(categories).map(([key,label])=>'<button type="button" data-inspire-category="'+key+'" aria-pressed="'+(category===key)+'">'+label+(key!=='all'&&data?' <small>'+data.counts[key]+'</small>':'')+'</button>').join('')+'</nav><div class="inspire-toolbar"><label class="sr" for="inspire-query">Search cached inspiration</label><input id="inspire-query" type="search" maxlength="150" placeholder="Find a spark…" value="'+esc(query)+'"><button type="button" id="inspire-shelf" class="secondary" aria-pressed="'+saved+'">Saved'+(data?' · '+data.saved_count:'')+'</button></div>'+(category==='docs'?'<p class="inspire-context">THE FIELD GUIDE <span>Curated references, ready when you need them.</span></p>':category==='science'?'<p class="inspire-context">FOLLOW THE EVIDENCE <span>Previews report the source’s claims. Open the paper or article to inspect them.</span></p>':category==='showcases'?'<p class="inspire-context">BUILT BY HUMANS <span>Show HN projects and captured X posts. <a href="https://x.com/search?q=vibecoding%20filter%3Alinks&f=live" target="_blank" rel="noopener noreferrer">Explore X ↗</a></span></p>':'')+'<div class="inspire-stream" aria-busy="'+loading+'">'+(data?.items.length?data.items.map(card).join(''):'<div class="inspire-empty"><pre aria-hidden="true">  .  +  .\n  \\ | /\n-- [*] --\n  / | \\</pre><h3>'+(loading?'Tuning in…':saved?'Your next obsession goes here.':query?'No matching signals.':category==='docs'?'No references selected.':'A little curiosity goes a long way.')+'</h3><p>'+(loading?'Reading your local cache.':query?'Try fewer words or another topic.':saved?'Save a card to keep it on this shelf.':category==='docs'?'Enable Field guide under Sources.':'Refresh now to check the selected sources. Opening this page starts no background scan.')+'</p></div>')+'</div><footer class="inspire-bottom"><span>'+(total?(offset+1)+'–'+Math.min(offset+6,total)+' / '+total+' signals':loading?'Reading cache':'No cached items in this view')+'</span><div><button type="button" class="quiet" id="inspire-prev" '+(!offset||loading?'disabled':'')+'>← Back</button><button type="button" class="secondary" id="inspire-next" '+(offset+6>=total||loading?'disabled':'')+'>More sparks →</button></div></footer><p class="inspire-scope">'+esc(data?.coverage||'Source previews stay linked to the original. No posts or jobs start here.')+'</p></div>';
  }
  async function refreshSources(source=''){
    if(busy)return;busy=true;error='';message='Reading selected sources. Your saved shelf stays put.';keepRefresh(refreshing||{key:uid(),source});paint();
    try{
      const result=await api('refresh',{request_key:refreshing.key,source:refreshing.source});keepRefresh(null);
      message=result.refreshed.length?'Checked '+result.refreshed.length+' sources · '+result.received+' previews'+(result.unavailable.length?' · '+result.unavailable.length+' unavailable, previous items kept':''):'Sources were checked recently. Cached previews are ready; see Sources for retry times.';
      await load();
    }catch(e){error=e.message;message='Refresh is unconfirmed. Check refresh recovers the same request.';}
    finally{busy=false;paint();}
  }
  function sources(){
    if(!data||busy)return;
    const prefs=data.settings;
    dialog('Tune your signal', '<p>Choose what comes in. Refresh checks enabled sources at most every 15 minutes; failed sources can retry after a minute. Cached previews stay available.</p><div class="inspire-source-list">'+data.sources.map(s=>'<label class="inspire-source"><input type="checkbox" data-inspire-source="'+esc(s.id)+'" '+(s.enabled?'checked':'')+'><span><b>'+esc(s.name)+'</b><small>'+esc(s.description||s.note)+'</small><small>'+esc(s.state==='unavailable'?'Unavailable · previous items retained':s.last_success_at?'Checked '+relative(s.last_success_at):s.kind==='reference'?'Reference shelf':'Not checked yet')+(s.retry_after_seconds?' · next check in '+Math.ceil(s.retry_after_seconds/60)+'m':'')+'</small><a href="'+esc(s.home)+'" target="_blank" rel="noopener noreferrer">Visit source ↗</a></span></label>').join('')+'</div><label class="inspire-rank"><input id="inspire-rank" type="checkbox" '+(prefs.rank?'checked':'')+'><span>Let Jev help pick relevant previews</span></label><p>On your next refresh, sends up to 12 public titles/previews and the interests below through your saved TypeSafe connection. No project files or chat history. Source order works without it.</p><p class="inspire-ranking-state">'+esc(data.ranking?.note||'Jev ranking is off.')+'</p><label for="inspire-interests">What catches your eye?</label><textarea id="inspire-interests" maxlength="500" rows="3">'+esc(prefs.interests)+'</textarea>','Save sources',async()=>{
      await api('configure',{sources:JSON.stringify([...document.querySelectorAll('[data-inspire-source]:checked')].map(n=>n.dataset.inspireSource)),rank:$('#inspire-rank').checked,interests:$('#inspire-interests').value,expected_version:prefs.version});message='Sources saved. Refresh now when you’re ready.';await load();
    });
  }
  function stash(r){
    if(!r)return;
    const storage='dm-inspiration-stash-'+r.id;let pending=null;try{pending=JSON.parse(localStorage.getItem(storage));}catch{}
    if(pending&&(!pending.args||pending.args.id!==r.id||typeof pending.key!=='string'))pending=null;
    const projects=[...$('#project').options].map(o=>({id:o.value,title:o.textContent})),draft=pending?.args||{title:'Explore: '+r.title,goal:'',project:project||'unsorted'};
    dialog('Keep the spark', '<p class="inspire-stash-source">'+esc(r.source_name)+' · <a href="'+esc(r.url)+'" target="_blank" rel="noopener noreferrer">Open original ↗</a></p><blockquote class="inspire-stash-preview">'+esc(r.excerpt||r.title)+'</blockquote>'+(pending?'<p>A save may already have finished. This recovers the same draft; edit the itch after recovery.</p>':'<p>Make it your idea. The original source stays attached as context.</p>')+'<label for="inspire-stash-title">Itch title</label><input id="inspire-stash-title" maxlength="500" value="'+esc(draft.title)+'" '+(pending?'readonly':'')+'><label for="inspire-stash-project">Project</label><select id="inspire-stash-project" '+(pending?'disabled':'')+'>'+projects.map(p=>'<option value="'+esc(p.id)+'" '+(p.id===draft.project?'selected':'')+'>'+esc(p.title)+'</option>').join('')+'</select><label for="inspire-stash-goal">What would you like to try or learn?</label><textarea id="inspire-stash-goal" maxlength="1500" rows="3" '+(pending?'readonly':'')+'>'+esc(draft.goal)+'</textarea>'+Object.entries(r.itches||{}).map(([p,id])=>'<p><button type="button" class="quiet" data-inspire-existing="'+esc(id)+'">Open the itch already saved for '+esc(p)+' ↗</button></p>').join(''),'Stash itch ↗',async()=>{
      const args=pending?.args||{id:r.id,title:$('#inspire-stash-title').value,goal:$('#inspire-stash-goal').value,project:$('#inspire-stash-project').value};
      if(!args.title.trim())throw new Error('Give this itch a title.');
      pending=pending||{key:uid(),args};try{localStorage.setItem(storage,JSON.stringify(pending));}catch{}
      let result;
      try{result=await api('stash',{...args,request_key:pending.key});}
      catch(e){
        if([400,404,422].includes(e.status)){
          pending=null;try{localStorage.removeItem(storage);}catch{}
          for(const id of ['inspire-stash-title','inspire-stash-goal'])$('#'+id).readOnly=false;
          $('#inspire-stash-project').disabled=false;
        }else{
          for(const id of ['inspire-stash-title','inspire-stash-goal'])$('#'+id).readOnly=true;
          $('#inspire-stash-project').disabled=true;
          $('#dialog-save').textContent='Check saved itch ↻';
          e.message+=' Retry checks this same draft; your fields are kept.';
        }
        DMUI.sync();throw e;
      }
      try{localStorage.removeItem(storage);}catch{}
      merge(result.itch);message=result.existing?'Opened the existing itch.':'Spark stashed. Original source kept with the itch.';await load();toast(message);
    });DMUI.sync();
  }
  document.addEventListener('click',async event=>{
    const b=event.target.closest('button');if(!b)return;
    if(b.dataset.inspireExisting){$('#editor').close();DMItches.open(b.dataset.inspireExisting);return;}
    if(!active())return;
    try{
      if(b.id==='inspire-refresh')return refreshSources();
      if(b.id==='inspire-sources')return sources();
      if(b.id==='inspire-retry')return refreshing?refreshSources():load();
      if(b.dataset.inspireCategory){category=b.dataset.inspireCategory;offset=0;message='';return load();}
      if(b.id==='inspire-shelf'){saved=!saved;offset=0;return load();}
      if(b.id==='inspire-next'||b.id==='inspire-prev'){offset=Math.max(0,offset+(b.id==='inspire-next'?6:-6));await load();$('#inspire-query')?.scrollIntoView({block:'nearest'});return;}
      if(b.dataset.inspireStash)return stash(find(b.dataset.inspireStash));
      if(b.dataset.inspireSave){const r=find(b.dataset.inspireSave);b.disabled=true;await api('mark',{id:r.id,action:r.saved?'unsave':'save'});return load();}
      if(b.dataset.inspireHide){const id=b.dataset.inspireHide;b.disabled=true;await api('mark',{id,action:'hide'});await load();toast('Hidden from your signal.',async()=>{await api('mark',{id,action:'show'});await load();});}
    }catch(e){error=e.message;paint();}
  });
  document.addEventListener('input',event=>{if(event.target.id!=='inspire-query')return;query=event.target.value;offset=0;clearTimeout(searchTimer);searchTimer=setTimeout(()=>load(),220);rememberPage();});
  return {markup,mounted,enter,page};
})();
