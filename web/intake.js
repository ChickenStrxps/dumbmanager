'use strict';
// UI for the DumbAPI-owned suggestion, split, review and merge operations.
window.DMIntake=(()=>{
  let splitting=false,wanted=null,timer=null,inflight=false,pending=false,source='local',batch=null,batchBusy=false,splitBusy=false,composing=false;
  const cache=new Map();let notice='',manualNext=false,cooldownUntil=0,cooldownTimer=null;
  let scoutPending=null,scoutReceipt=null,scoutBusy=false;
  function modelNotice(result){return ({not_configured:'Connect Mercury in Settings for fresh ideas.',needs_key:'Reconnect Mercury in Settings for fresh ideas.',unavailable:'Mercury is unavailable. Tap Suggest to retry.',rate_limited:'Mercury is cooling down; your words are kept.',waiting:'Another request is finishing. Tap Suggest to retry.',no_match:'No useful fit yet. Add a detail or try more ideas.',idle:'Keep typing a few words for ideas.'})[result.generation?.status]||'';}
  const usable=r=>!['suggested','declined','archived'].includes(r.state);
  function init(){
    const input=$('#command'),editor=document.createElement('div'),ghost=document.createElement('div');editor.className='command-editor';ghost.id='command-ghost';ghost.className='command-ghost';ghost.setAttribute('aria-hidden','true');ghost.hidden=true;input.replaceWith(editor);editor.append(input,ghost);input.setAttribute('aria-autocomplete','both');
    const tools=document.createElement('div');tools.id='typing-tools';tools.className='typing-tools';tools.hidden=true;
    tools.innerHTML='<button id="typing-suggest" type="button">Suggest ✦</button><span id="typing-note" role="status" aria-live="polite"></span>';
    $('.input-wrap').append(tools,$('#suggestions'));
    $('#typing-suggest').addEventListener('pointerdown',e=>e.preventDefault());$('#typing-suggest').onclick=moreIdeas;
    window.visualViewport?.addEventListener('resize',paintControls);window.addEventListener('resize',paintControls);
    input.addEventListener('compositionstart',()=>{composing=true;cancelSuggestions();});input.addEventListener('compositionend',()=>{composing=false;updateSuggestions();});
    for(const name of ['click','keyup','select','scroll'])input.addEventListener(name,()=>renderGhost());
    const button=document.createElement('button');button.id='mode-split';button.type='button';button.textContent='Split';button.setAttribute('aria-pressed','false');
    button.onclick=async()=>{await DMChat.mode(false);split(true);};$('#mode-chat').before(button);
    const resume=document.createElement('button');resume.id='split-resume';resume.className='text-link';resume.type='button';resume.textContent='Finish split…';resume.hidden=true;
    resume.onclick=()=>reviewBatch();$('.capture-foot').append(resume);
    try{const saved=JSON.parse(sessionStorage.getItem('dm-split-pending')||'null');if(saved?.items?.length&&saved.items.every(i=>i.args?.request_key))batch=saved;}catch{}
    resume.hidden=!batch;
    try{const saved=JSON.parse(DMT3.read(sessionStorage,'dm-scout-pending')||'null');if(saved?.request_key&&typeof saved.thread_id==='string'&&typeof saved.message==='string'&&saved.message.length<=12000)scoutPending=saved;}catch{}
    try{const saved=JSON.parse(DMT3.read(sessionStorage,'dm-scout-receipt')||'null');if(saved?.thread_id&&saved?.project)scoutReceipt=saved;}catch{}
  }
  function split(value){splitting=value;cancelSuggestions();decorate();updateSuggestions();$('#command').focus();}
  function decorate(){
    $('#mode-split')?.classList.toggle('active',splitting&&!DMChat.enabled);
    $('#mode-split')?.setAttribute('aria-pressed',String(splitting&&!DMChat.enabled));
    if(splitting&&!DMChat.enabled){$('#mode-itch').classList.remove('active');$('#mode-itch').setAttribute('aria-pressed','false');}
    if($('#split-resume'))$('#split-resume').hidden=!batch;
  }
  function cancelSuggestions(){clearTimeout(timer);timer=null;wanted=null;pending=false;source='local';notice='';manualNext=false;if($('#command-ghost'))$('#command-ghost').hidden=true;paintControls();}
  function moreIdeas(){
    const input=$('#command');if(pending||cooldownUntil>Date.now()||!atEnd())return;
    input.focus({preventScroll:true});manualNext=true;suggestionIndex=-1;updateSuggestions();
  }
  function paintControls(){
    const tools=$('#typing-tools');if(!tools)return;
    const input=$('#command'),mode=commandMode(),active=['itch','chat'].includes(mode)&&input.value.trim().length>=3&&input.value.length<=500;
    const viewport=window.visualViewport,above=$('.input-wrap').getBoundingClientRect().top-(viewport?.offsetTop||0)-8;
    const tight=active&&document.activeElement===input&&innerWidth<=760&&(viewport?.height||innerHeight)<560&&above>=88;
    document.body.classList.toggle('typing-tight',tight);$('#suggestions').style.setProperty('--typing-height',Math.min(164,Math.max(88,above))+'px');
    tools.hidden=!active;if(!active)return;
    const wait=Math.max(0,Math.ceil((cooldownUntil-Date.now())/1000)),button=$('#typing-suggest');
    button.disabled=pending||!!wait||!atEnd();button.textContent=pending?'Thinking…':wait?'Wait '+wait+'s':source==='mercury'?'More ideas ↻':'Suggest ✦';
    button.title=!atEnd()?'Move to the end of your words to suggest a continuation.':'';
    $('#typing-note').textContent=pending?'Finding useful directions…':wait?'Mercury cooldown. Your words are kept.':notice||(suggestions.length?'Tap an idea to insert it.':mode==='chat'&&!DMChat.target?'Ideas work before you choose a thread.':'Ideas from your words and selected context.');
    clearTimeout(cooldownTimer);if(wait)cooldownTimer=setTimeout(paintControls,1000);
  }
  function atEnd(){const input=$('#command');return !composing&&input.selectionStart===input.value.length&&input.selectionEnd===input.value.length;}
  function localWords(input,mode,pool){
    if(!['itch','chat'].includes(mode)||!atEnd())return [];
    const match=input.match(/(?:^|[^\w./:@-])([a-zA-Z][a-zA-Z0-9'-]*)$/);if(!match||match[1].length<2)return [];
    const ctx=mode==='chat'?DMChat.context():context(),counts=new Map();
    for(const text of [ctx?.task||'',ctx?.testing||'',ctx?.entities||'',...pool.map(p=>p.value)])for(const word of text.match(/[a-zA-Z][a-zA-Z0-9'-]{1,39}/g)||[]){const lower=word.toLowerCase();counts.set(lower,(counts.get(lower)||0)+1);}
    const terms=[...counts].sort((a,b)=>b[1]-a[1]).slice(0,512).map(([w])=>w).concat(state.typing_words||[]),seen=new Set(),fragment=match[1];
    const rows=[];for(const word of terms){const lower=word.toLowerCase();if(lower.length<=fragment.length||!lower.startsWith(fragment.toLowerCase())||seen.has(lower))continue;seen.add(lower);const suffix=lower.slice(fragment.length),value=input+(fragment===fragment.toUpperCase()?suffix.toUpperCase():suffix);if(value.length<=500)rows.push({type:'word',kind:'word',label:value,value,score:90});if(rows.length===8)break;}
    return rows;
  }
  function renderGhost(){
    paintControls();const input=$('#command'),ghost=$('#command-ghost');if(!ghost)return;
    const suggestion=suggestions[suggestionIndex>=0?suggestionIndex:0],tail=suggestion?.value?.startsWith(input.value)?suggestion.value.slice(input.value.length):'';
    const show=!!tail&&['itch','chat'].includes(commandMode())&&atEnd()&&document.activeElement===input&&!$('#suggestions').hidden;
    ghost.hidden=!show;if(!show)return;
    ghost.innerHTML='<span class="ghost-prefix">'+esc(input.value)+'</span><span>'+esc(tail)+'</span><kbd>Tab</kbd>';
    ghost.style.setProperty('--input-scroll',-input.scrollLeft+'px');
  }
  function identity(input,mode,pool){
    const c=mode==='chat'?DMChat.context():context();
    const surface=project.toLowerCase()==='dumbmanager'?JSON.stringify({app:document.title,page:$('#view-name')?.textContent||'',navigation:[...document.querySelectorAll('nav [data-view] .nav-label')].map(n=>n.textContent),panel:[...document.querySelectorAll('#tool-results h2,#tool-results h3,#tool-results [role=tab],#tool-results [data-tool-tab]')].slice(0,12).map(n=>n.textContent.slice(0,100))}).slice(0,1800):'';
    return {text:input.slice(0,500),project,context_id:c?.id||'',mode,thread_id:mode==='chat'?DMChat.target:'',
      candidates:JSON.stringify(mode==='chat'?pool.slice(0,32).map(p=>p.value.slice(0,240)):[]),surface,revision:c?.updated_at||'',activity:mode==='chat'?DMChat.activityRevision:'',generator:state.typing_generator?.revision||'',pool:pool.map(p=>p.value).join('\n')};
  }
  function offer(input,mode,pool){
    if(!['itch','chat'].includes(mode)||!atEnd()||input.trim().length<3||input.length>500||document.hidden||document.activeElement!==$('#command')){cancelSuggestions();return null;}
    const spec=identity(input,mode,pool),key=JSON.stringify(spec),hit=cache.get(key);
    const fresh=manualNext;manualNext=false;
    if(!fresh&&hit&&Date.now()-hit.at<5000){clearTimeout(timer);timer=null;wanted=null;pending=false;source=hit.result.source;notice=modelNotice(hit.result);return hit.result;}
    source='local';notice='';pending=true;
    if(fresh||wanted?.key!==key){if(fresh)cache.delete(key);wanted={key,spec:{...spec,...(fresh?{fresh:true}:{})},due:Date.now()+(fresh?0:450)};clearTimeout(timer);timer=setTimeout(pump,fresh?0:450);}
    return null;
  }
  async function pump(){
    if(inflight||!wanted||document.hidden||document.activeElement!==$('#command'))return;
    const request=wanted;inflight=true;timer=null;
    const {revision,activity,generator,pool,...args}=request.spec;
    let result;
    try{result=await call('manager.suggest',args);}catch{result={items:[],source:'local',generation:{status:'unavailable'}};}
    inflight=false;
    if(result.generation?.status==='waiting'&&wanted===request&&(request.retries||0)<2){request.retries=(request.retries||0)+1;timer=setTimeout(pump,result.generation.retry_after_ms||800);return;}
    if(wanted?.key!==request.key||wanted===request){cache.set(request.key,{result,at:Date.now()});while(cache.size>24)cache.delete(cache.keys().next().value);}
    if(wanted===request){pending=false;source=result.source;notice=modelNotice(result);if(result.generation?.status==='rate_limited'&&result.generation.retry_after_ms>0)cooldownUntil=Math.max(cooldownUntil,Date.now()+result.generation.retry_after_ms);if(suggestionIndex<0)updateSuggestions();else paintControls();}
    else if(wanted){clearTimeout(timer);timer=setTimeout(pump,Math.max(0,wanted.due-Date.now()));}
  }
  function fuzzy(query,text){
    const words=query.toLowerCase().match(/[a-z0-9]+/g)||[],target=text.toLowerCase().match(/[a-z0-9]+/g)||[];
    return words.length&&words.every(w=>target.some(t=>{if(t.startsWith(w))return true;if(w.length<2||w[0]!==t[0])return false;let i=0;for(const c of t)if(c===w[i])i++;return i===w.length;}))?45:0;
  }
  async function previewSplit(){
    if(batch)return reviewBatch();if(splitBusy)return;
    if(DMUploads.busy)return toast('Receipts are still uploading.');
    const original=$('#command').value.trim();if(!original)return $('#command').focus();
    if(original.length>4000)return toast('Keep the batch under 4,000 characters.');
    const ctx=context(),chosenProject=project,attachments=[...DMUploads.itchAttachments];
    splitBusy=true;$('#stash').disabled=true;signal('Splitting the batch…','JEV','load');
    try{
      const result=await call('manager.split',{text:original});
      if(!result.parts.length)return toast('Add a few words to split.');
      let savingPreview=false;
      dialog('Split the batch',`<p class="intake-note">${esc(chosenProject)} · ${result.source==='jev'?'Jev checked the split':'Local split'} · edit or uncheck anything.</p><div class="split-parts">${result.parts.map((part,i)=>`<div class="split-part"><input type="checkbox" id="split-check-${i}" checked aria-label="Save part ${i+1}"><label class="sr" for="split-part-${i}">Itch ${i+1}</label><textarea id="split-part-${i}" rows="2" maxlength="500">${esc(part)}</textarea></div>`).join('')}</div>${attachments.length?'<p class="intake-note">Your receipts stay attached to each saved part.</p>':''}`,'Stash selected',async()=>{
        if(savingPreview)return false;savingPreview=true;
        try{
          if(batch)return await saveBatch();
          const parts=result.parts.map((_,i)=>$('#split-check-'+i).checked?$('#split-part-'+i).value.trim():'').filter(Boolean);
          if(!parts.length)throw new Error('Pick at least one itch.');
          const seen=new Set(),stamp=new Date().toISOString();
          batch={original,attachments,items:parts.filter(p=>!seen.has(p.toLowerCase())&&seen.add(p.toLowerCase())).map(title=>({done:false,args:{title,moment:false,project:chosenProject,context_id:ctx?.id||'',context_snapshot:JSON.stringify(ctx||{}),use_active:false,event_at:stamp,request_key:uid(),attachments:JSON.stringify(attachments.map(a=>a.id))}}))};
          keepBatch();$('#dialog-content').querySelectorAll('textarea,input').forEach(n=>n.disabled=true);$('#dialog-save').textContent='Finish saving';return await saveBatch();
        }finally{savingPreview=false;}
      });
    }catch(e){toast(e.message);}finally{splitBusy=false;updateSuggestions();}
  }
  function keepBatch(){if(batch)sessionStorage.setItem('dm-split-pending',JSON.stringify(batch));else sessionStorage.removeItem('dm-split-pending');decorate();}
  function reviewBatch(){
    if(!batch)return;
    dialog('Finish this split',`<p class="intake-note">${batch.items.filter(i=>i.done).length}/${batch.items.length} saved. Retry uses the same save keys.</p><ol class="split-receipt">${batch.items.map(i=>`<li>${i.done?'✓':'·'} ${esc(i.args.title)}</li>`).join('')}</ol>`,'Finish saving',saveBatch);
  }
  async function saveBatch(){
    if(batchBusy||!batch)return false;batchBusy=true;
    try{
      for(const item of batch.items){if(item.done)continue;const row=await call('manager.capture',item.args);merge(row);item.done=true;keepBatch();}
      const completed=batch;
      // Persist completion before clearing the draft; an interrupted reply reuses exact keys.
      sessionStorage.removeItem('dm-split-pending');batch=null;decorate();
      if($('#command').value.trim()===completed.original)$('#command').value='';
      DMUploads.commit('@itch',completed.attachments);render();updateSuggestions();
      window.DMAquarium?.celebrate?.('stash',$('#stash'));toast(completed.items.length+' itches stashed.');return true;
    }catch(e){toast('Split paused. Your parts are kept—use Finish split to retry.');throw e;}
    finally{batchBusy=false;}
  }
  function suggestedMarkup(rows){
    const toolbar=`<div class="scout-toolbar"><div><button class="secondary" data-action="scout-now" ${scoutBusy?'disabled':''}>${scoutBusy?'Sending…':scoutPending?'Retry scout':'Suggest now'}</button><small>One project · a short look around · your call on each finding.</small></div>${scoutReceipt?`<small>Last request: ${esc(scoutReceipt.project)} · sent ${age(scoutReceipt.at)}. <a href="t3-thread://v1/${esc(scoutReceipt.thread_id)}">Check in T3 ↗</a></small>`:''}</div>`;
    if(!rows.length)return toolbar+'<div class="empty"><pre data-ascii="scan" aria-hidden="true">[ · ? · ]</pre><h3>No suggestions yet.</h3><p>Scout findings land here. You choose what joins the pile.</p></div>';
    return toolbar+rows.map(r=>`<button type="button" class="scout-card" data-review-idea="${r.id}"><span><small>${esc(r.project)} · ${esc(r.scout?.kind||'idea')}</small><h3>${esc(r.title)}</h3><small>${esc(r.scout?.where||'Open to see the source')}</small></span><span>Review ↗</span></button>`).join('');
  }
  async function scoutNow(){
    if(scoutBusy)return;
    let plan=null,choices=[],projects=[],failure='',projectSequence=0;
    const frozen=scoutPending;
    dialog(frozen?'Retry this scout':'Suggest now','<p>Loading the project and your T3 threads…</p>',frozen?'Retry same request':'Start scout',async()=>{
      if(scoutBusy||!plan)return false;
      if(!frozen&&$('#scout-project').value!==plan.project)throw new Error('Wait for this project’s scout brief to load.');
      const thread_id=frozen?.thread_id||$('#scout-thread').value;
      if(!thread_id)throw new Error('Choose a T3 thread for this scout.');
      if(!scoutPending){
        const message=plan.brief;
        if(typeof message!=='string'||!message.trim())throw new Error('Scout brief unavailable. Refresh DumbManager and try again.');
        if(message.length>12000)throw new Error('Scout brief is too long. Nothing sent.');
        scoutPending={thread_id,message,request_key:uid(),project:plan.project,folder:plan.folder,
          thread_title:choices.find(t=>t.id===thread_id)?.title||thread_id};
        try{DMT3.write(sessionStorage,'dm-scout-pending',JSON.stringify(scoutPending));}
        catch{scoutPending=null;throw new Error('Browser storage is full. Nothing sent; clear space before retrying.');}
      }
      $('#scout-thread').disabled=true;$('#scout-project').disabled=true;DMUI.sync();
      scoutBusy=true;render();
      const request=scoutPending;
      try{
        await call('manager.scout.remember',{thread_id:request.thread_id});
        await call('t3.send',{thread_id:request.thread_id,message:request.message,request_key:request.request_key});
        scoutReceipt={thread_id:request.thread_id,project:request.project,at:new Date().toISOString()};
        // Persist the receipt before clearing a pending request, so a storage failure
        // retains its exact retry key rather than silently allowing a new send.
        DMT3.write(sessionStorage,'dm-scout-receipt',JSON.stringify(scoutReceipt));
        DMT3.remove(sessionStorage,'dm-scout-pending');scoutPending=null;
        toast('Sent to T3. Findings land in Suggested when the scout finishes.');return true;
      }catch(e){
        const status=$('#scout-status');if(status)status.textContent=e.message+' Your exact request is kept. Close and use Retry scout.';
        throw e;
      }finally{scoutBusy=false;render();}
    });
    const sequence=dialogSequence;$('#dialog-save').disabled=true;
    if(frozen){
      plan={project:frozen.project,folder:frozen.folder||frozen.project};
      projects=[{id:frozen.project,folder:plan.folder}];
      choices=[{id:frozen.thread_id,title:frozen.thread_title||frozen.thread_id}];
      // Older saved retries did not keep a label. Resolve only that exact ID;
      // an offline/archived destination must never change the retry identity.
      if(!frozen.thread_title)try{const result=await call('t3.read',{thread_id:frozen.thread_id});if(result.thread.id===frozen.thread_id)choices=[result.thread];}catch{}
    }
    else{
      try{
        [plan,{items:choices}]=await Promise.all([call('manager.scout.plan'),call('t3.threads',{limit:200})]);
        projects=plan.projects;
        if(project!==plan.project&&projects.some(p=>p.id===project))plan=await call('manager.scout.plan',{project});
      }
      catch(e){failure=e.message;}
    }
    if(sequence!==dialogSequence||!$('#editor').open)return;
    if(failure){$('#dialog-content').textContent=failure+' Nothing sent. Close and try again.';return;}
    const savedThread=plan.scout_thread_id||scoutReceipt?.thread_id||'';
    const preferred=frozen?.thread_id||(choices.some(t=>t.id===savedThread)?savedThread:'');
    $('#dialog-content').innerHTML=`<p>Check one feature for bugs first, then usability and quality improvements. Up to six reads. No code changes.</p><label for="scout-project">Project to scout</label><select id="scout-project" ${frozen?'disabled':''}>${projects.map(p=>`<option value="${esc(p.id)}" ${p.id===plan.project?'selected':''}>${esc(p.folder)}</option>`).join('')}</select><p id="scout-project-note">Workspace: ${esc(plan.folder)}</p><label for="scout-thread">Send scout to</label><select id="scout-thread" ${frozen?'disabled':''}><option value="">Choose a T3 thread…</option>${choices.map(t=>`<option value="${esc(t.id)}" ${t.id===preferred?'selected':''}>${esc(t.title)} · ${esc(t.project||'T3')}</option>`).join('')}</select><p id="scout-status" role="status">${frozen?'Retry keeps the same project, words, thread and send key.':'Nothing starts until you tap Start scout.'}</p><small>Up to three findings per UTC day across all scouts; 25 pending. Findings need your approval.</small>`;
    if(!frozen)$('#scout-status').textContent=(savedThread&&!preferred?'Last scout thread is unavailable. Choose a thread. ':preferred?'Using your last scout thread. ':'Choose a scout thread. ')+'Start scout remembers it for desktop and phone.';
    $('#scout-thread').onchange=()=>{$('#dialog-save').disabled=!plan||!$('#scout-thread').value;};
    $('#scout-project').onchange=async()=>{
      if(scoutPending)return;
      const chosen=$('#scout-project').value,revision=++projectSequence;
      plan=null;$('#dialog-save').disabled=true;$('#scout-project-note').textContent='Loading this project’s brief…';
      try{
        const result=await call('manager.scout.plan',{project:chosen});
        if(sequence!==dialogSequence||!$('#editor').open||revision!==projectSequence)return;
        plan=result;$('#scout-project-note').textContent='Workspace: '+plan.folder;
        $('#scout-status').textContent='Nothing starts until you tap Start scout.';
        $('#dialog-save').disabled=!$('#scout-thread').value;
      }catch(e){
        if(sequence!==dialogSequence||!$('#editor').open||revision!==projectSequence)return;
        $('#scout-project-note').textContent='Brief unavailable. Choose the project again to retry.';
        $('#scout-status').textContent=e.message+' Nothing sent.';
      }
    };
    if(frozen){const dismiss=document.createElement('button');dismiss.type='button';dismiss.className='quiet';dismiss.textContent='Discard retry';dismiss.onclick=()=>{if(scoutBusy)return;DMT3.remove(sessionStorage,'dm-scout-pending');scoutPending=null;$('#editor').close();render();toast('Retry discarded. Check T3 before starting another scout.');};$('#dialog-content').append(dismiss);}
    $('#dialog-save').disabled=!$('#scout-thread').value;DMUI.sync();
  }
  function reviewIdea(id){
    const row=state.itches.find(r=>r.id===id);if(!row||row.state!=='suggested')return;
    let pendingReview=null,working=false;
    const decide=async decision=>{
      if(working)return false;working=true;
      try{
        if(!pendingReview&&!$('#idea-title').value.trim())throw new Error('Give it a title.');
        pendingReview ||= {id,decision,title:$('#idea-title').value.trim(),reason:$('#idea-reason').value.trim(),request_key:uid()};
        if(pendingReview.decision!==decision)throw new Error('Retry the pending review first.');
        if(!pendingReview.title)throw new Error('Give it a title.');
        const next=await call('manager.review',pendingReview);merge(next);render();toast(decision==='approve'?'Added to your pile.':decision==='edit'?'Edit saved. Still suggested.':'Declined. Scout keeps that in mind.');return true;
      }finally{working=false;}
    };
    dialog('Worth stashing?',`<label for="idea-title">Title</label><input id="idea-title" maxlength="500" value="${esc(row.title)}"><p class="intake-note">${esc(row.project)} · ${esc(row.scout?.kind||'idea')}</p><details class="scout-source"><summary>Where’d this come from?</summary><dl><dt>Source</dt><dd>${esc(row.scout?.where)}</dd><dt>Looked at</dt><dd>${esc(row.scout?.steps||'No steps recorded.')}</dd><dt>Observed</dt><dd>${esc(row.scout?.saw||'No detail recorded.')}</dd></dl></details><label for="idea-reason">Note · optional</label><input id="idea-reason" maxlength="500" placeholder="Why keep or pass?"><button type="button" class="quiet" id="idea-decline">Decline</button>`,'Approve',()=>decide('approve'));
    const edit=document.createElement('button');edit.id='idea-edit';edit.type='button';edit.className='secondary';edit.textContent='Save edit';$('#idea-decline').before(edit);
    edit.onclick=async()=>{try{if(await decide('edit'))$('#editor').close();}catch(e){toast(e.message);}};
    $('#idea-decline').onclick=async()=>{try{if(await decide('decline'))$('#editor').close();}catch(e){toast(e.message);}};
  }
  async function duplicates(){
    const chosen=project;
    let running=true;
    dialog('Find dupes',`<div class="intake-loading">${DMUI.ascii('scan')}<p>Checking the ${chosen==='unsorted'?'whole pile':esc(chosen)+' pile'}…</p></div>`,'Done',()=>true);
    const seq=dialogSequence;$('#dialog-save').disabled=true;
    try{
      const result=await call('manager.duplicates',{project:chosen==='unsorted'?'':chosen});
      if(seq!==dialogSequence||!$('#editor').open)return;
      $('#dialog-content').innerHTML=`<p class="intake-note">${result.source==='jev'?'Jev checked':'Local matches'} · ${result.checked} open itches. Originals stay in history.</p>`+(result.pairs.length?result.pairs.map((pair,i)=>`<div class="duplicate-pair"><strong>${esc(pair.keep.title)}</strong><span>↳ ${esc(pair.drop.title)}</span><button type="button" class="secondary" data-merge-pair="${i}">Review merge ↗</button></div>`).join(''):'<div class="empty"><pre data-ascii="spark" aria-hidden="true">· + ·</pre><h3>No clear dupes.</h3><p>Similar topics stay separate.</p></div>');
      $('#dialog-content').onclick=e=>{const b=e.target.closest('[data-merge-pair]');if(!b)return;$('#dialog-content').onclick=null;confirmMerge(result.pairs[Number(b.dataset.mergePair)]);};
    }catch(e){if(seq===dialogSequence)$('#dialog-content').textContent=e.message;}
    finally{running=false;if(seq===dialogSequence)$('#dialog-save').disabled=false;}
  }
  function confirmMerge(pair){
    const args={id:pair.drop.id,into:pair.keep.id,request_key:uid()};let working=false;
    dialog('Same itch?',`<p class="intake-note">Keep</p><h3>${esc(pair.keep.title)}</h3><p class="intake-note">Archive as its duplicate</p><p>${esc(pair.drop.title)}</p><p class="intake-note">Both originals stay saved. Occurrences and receipts move to the kept itch. Nothing is deleted.</p>`,'Merge these',async()=>{
      if(working)return false;working=true;
      try{const result=await call('manager.merge',args);merge(result.kept);merge(result.archived);render();toast('Merged. Both originals kept.');return true;}finally{working=false;}
    });
  }
  document.addEventListener('click',e=>{const target=e.target.closest('[data-review-idea],[data-action="duplicates"],[data-action="scout-now"]');if(!target||target.disabled)return;if(target.dataset.reviewIdea)reviewIdea(target.dataset.reviewIdea);else if(target.dataset.action==='scout-now')scoutNow().catch(e=>toast(e.message));else duplicates();});
  document.addEventListener('visibilitychange',()=>{if(document.hidden)cancelSuggestions();});
  return {init,split,decorate,offer,fuzzy,localWords,renderGhost,cancelSuggestions,previewSplit,suggestedMarkup,usable,get notice(){return notice;},get splitting(){return splitting;},get pending(){return pending;},get source(){return source;},get splitBusy(){return splitBusy||batchBusy;}};
})();
