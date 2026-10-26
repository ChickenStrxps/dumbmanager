'use strict';
window.DMResearch=(()=>{
  let id='',pack=null,section='findings',runId='',reportId='',busy=false,generation=0,loadSeq=0,timer=null,prepareKey='',prepareArgs=null,threads=[],controlsSignature='';
  const dialog=()=>$('#research-view');
  const report=()=>pack?.run?.reports.find(r=>r.id===reportId)||pack?.run?.reports.at(-1);
  const page=()=>dialog()?.open?{itch:id,run:runId,report:reportId,section,question:$('#research-question').value}:null;
  function status(message){$('#research-status').textContent=message;}
  function sourceLink(s){return s.url?'<a href="'+esc(s.url)+'" target="_blank" rel="noopener noreferrer">'+esc(s.title||s.url)+' ↗</a>':'<b>'+esc(s.title||s.path)+'</b><code>'+esc(s.path)+'</code>';}
  function paint(){
    if(!pack)return;
    const run=pack.run,r=report(),body=$('#research-body');
    const signature=(run?.id||'')+':'+!!r;if(signature!==controlsSignature){controlsSignature=signature;$('#research-controls').open=!r;}
    $('#research-refresh').disabled=busy;
    runId=run?.id||'';reportId=r?.id||'';
    $('#research-itch-title').textContent=pack.title;
    $('#research-stale').hidden=!pack.stale;
    $('#research-pass').innerHTML=pack.history.map(h=>'<option value="'+esc(h.id)+'">'+esc(new Date(h.created_at).toLocaleString()+' · '+h.question.slice(0,85)+' · '+h.reports+' report'+(h.reports===1?'':'s'))+'</option>').join('');
    $('#research-pass').value=runId;$('#research-pass').disabled=busy||!run;
    $('#research-report').innerHTML=(run?.reports||[]).map((r,i)=>'<option value="'+esc(r.id)+'">Report '+(i+1)+' · '+esc(new Date(r.at).toLocaleString())+'</option>').join('');
    $('#research-report').value=reportId;$('#research-report').disabled=busy||!r;
    $('#research-report-label').hidden=!r;
    $('#research-state').textContent=run?({prepared:'Brief prepared · nothing sent',send_unconfirmed:'Send unconfirmed · recover the same request',awaiting_report:'Sent to T3 · waiting for a saved report',reported:'Research report saved'}[run.state]||run.state):'No research pass yet';
    const pending=run?.send&&!run.send.receipt;
    $('#research-prepare').disabled=busy||!!pending;
    $('#research-prepare').textContent=run?'Prepare another pass':'Prepare research brief';
    $('#research-question').disabled=busy||!!pending;
    $('#research-thread').disabled=busy||!!run?.send;
    $('#research-send').disabled=busy||!run||!!r||(!pending&&pack.stale)||!$('#research-thread').value||!!run?.send?.receipt;
    $('#research-send').textContent=busy?'Working…':pending?'Recover research send ↗':'Send research to T3 ↗';
    const link=$('#research-sent');link.hidden=!run?.send?.receipt;if(!link.hidden)link.href=run.send.receipt.thread_url;
    $('#research-copy').disabled=busy||!run;
    document.querySelectorAll('[data-research-section]').forEach(b=>b.setAttribute('aria-pressed',b.dataset.researchSection===section));
    if(!run){body.innerHTML='<div class="research-empty"><pre aria-hidden="true">     . · .\n  ──( ? )──\n     ˙ · ˙</pre><h3>Give the itch a closer look.</h3><p>Prepare a research brief, choose a T3 thread, then send it when you’re ready. Findings and sources return here when the researching agent saves its report.</p><p>Preparing is local. It starts no browser, model or task.</p></div>';return;}
    if(section==='brief'){
      body.innerHTML='<h3>The research brief</h3><p>This exact brief is frozen for this pass. It asks for research only and includes the instructions for saving findings back here.</p><pre class="research-brief">'+esc(run.brief)+'</pre>';return;
    }
    if(!r){
      body.innerHTML='<h3>'+esc(run.send?'Waiting for findings':'Opening questions')+'</h3><ol>'+run.outline.map(t=>'<li>'+esc(t)+'</li>').join('')+'</ol><h4>Optional existing tools</h4><p>These are starting aids, not a completed tool assessment. The research report can recommend none.</p><ul>'+run.suggested_tools.map(t=>'<li><code>'+esc(t.capability)+'</code> — '+esc(t.reason)+'</li>').join('')+'</ul>'+(run.send?'<p>The agent must save through <code>manager.research.record</code>. A sent receipt alone does not mean research is finished. Refresh checks saved reports, not chat history.</p>':'<p>Review the brief, then send it or copy it into your own research session.</p>');return;
    }
    if(section==='sources'){
      body.innerHTML='<h3>Sources kept with this report</h3><p>Reported excerpts · source pages were not fetched by this view.</p>'+(r.sources.length?r.sources.map(s=>'<article class="research-source" id="research-source-'+esc(s.id)+'"><span class="eyebrow">'+esc(s.id)+'</span>'+sourceLink(s)+'<pre>'+esc(s.excerpt)+'</pre></article>').join(''):'<p>No sources were recorded. Check the limitations before relying on this report.</p>');return;
    }
    if(section==='plan'){
      const adopted=pack.run.adopted,locked=pack.stale||['resolved','archived','suggested','declined'].includes(pack.itch_state);
      body.innerHTML='<h3>Proposed next moves</h3><p>Choose useful steps to add to the implementation plan. Existing steps stay intact. Adding steps reopens ready work; it sends nothing.</p>'+(r.plan.length?'<div class="research-steps">'+r.plan.map(p=>{const done=adopted.includes(r.id+':'+p.id);return '<label><input type="checkbox" data-research-step="'+esc(p.id)+'" '+(done||locked?'disabled':'')+'><span><code>'+esc(p.id)+'</code> '+esc(p.text)+(done?' <small>Added to plan</small>':'')+'</span></label>';}).join('')+'</div><button type="button" class="secondary" id="research-adopt" '+(locked?'disabled':'')+'>Add selected steps to plan</button>':'<p>No implementation steps proposed.</p>')+(locked?'<p>Recheck changed research or reopen the itch before adding steps.</p>':'')+'<h3>Useful tools</h3>'+(r.tools.length?'<ul>'+r.tools.map(t=>'<li><code>'+esc(t.capability)+'</code> — '+esc(t.reason)+'</li>').join('')+'</ul>':'<p>No additional tools recommended.</p>')+(r.tool_ideas.length?'<h4>Tool ideas · not implemented</h4><ul>'+r.tool_ideas.map(t=>'<li>'+esc(t)+'</li>').join('')+'</ul>':'');return;
    }
    body.innerHTML='<h3>What the research found</h3><p class="research-summary">'+esc(r.summary)+'</p><p class="research-provenance">Agent report · '+esc(new Date(r.at).toLocaleString())+'. Exact quotes match the saved excerpts; this does not independently verify the claims.</p>'+r.findings.map(f=>'<article class="research-finding"><span class="eyebrow">'+esc(f.kind)+'</span><p>'+esc(f.text)+'</p>'+f.citations.map(c=>'<details><summary>Source '+esc(c.source_id)+'</summary><blockquote>'+esc(c.quote)+'</blockquote>'+sourceLink(r.sources.find(s=>s.id===c.source_id))+'</details>').join('')+'</article>').join('')+(r.open_questions.length?'<h4>Still open</h4><ul>'+r.open_questions.map(t=>'<li>'+esc(t)+'</li>').join('')+'</ul>':'')+(r.limitations.length?'<h4>Limits of this research</h4><ul>'+r.limitations.map(t=>'<li>'+esc(t)+'</li>').join('')+'</ul>':'');
  }
  function destinations(){
    const preferred=pack?.run?.send?.thread_id||$('#research-thread').value||pack?.thread_id||'';
    const list=[...threads];if(preferred&&!list.some(t=>t.id===preferred))list.unshift({id:preferred,title:'Saved research thread · '+preferred});
    $('#research-thread').innerHTML='<option value="">Choose a research thread</option>'+list.map(t=>'<option value="'+esc(t.id)+'">'+esc(t.title)+'</option>').join('');$('#research-thread').value=preferred;DMUI.sync();
  }
  function schedule(){clearTimeout(timer);if(dialog().open&&pack?.run?.state==='awaiting_report')timer=setTimeout(()=>load(false),4000);}
  async function load(withThreads=true){
    const token=generation,seq=++loadSeq,wanted=id;$('#research-refresh').disabled=true;
    try{
      const data=await call('manager.research.get',{id:wanted,run_id:runId});
      if(token!==generation||seq!==loadSeq||!dialog().open)return;
      pack=data;destinations();paint();
      if(withThreads){try{const data=await call('t3.threads',{limit:200});if(token!==generation||seq!==loadSeq)return;threads=data.items||[];destinations();paint();$('#research-thread-note').textContent=data.connected===false?'T3 is unavailable. Connect it in Settings, or copy the brief.':'Research remembers its own last destination.';}catch(e){if(token===generation&&seq===loadSeq)$('#research-thread-note').textContent=e.message+' You can still copy the brief.';}}
    }catch(e){if(token===generation&&dialog().open)status(e.message+' Use Refresh to try again.');}
    finally{if(token===generation&&seq===loadSeq){$('#research-refresh').disabled=busy;schedule();}}
  }
  async function open(itch,restore={}){
    clearTimeout(timer);generation++;id=itch;pack=null;controlsSignature='';runId=restore.run||'';reportId=restore.report||'';section=['findings','plan','sources','brief'].includes(restore.section)?restore.section:'findings';busy=false;threads=[];prepareArgs=null;prepareKey='';
    $('#research-question').value=restore.question||state.itches.find(r=>r.id===id)?.desired_outcome||state.itches.find(r=>r.id===id)?.title||'';
    $('#research-body').innerHTML='<p>Reading saved research…</p>';$('#research-thread').innerHTML='<option value="">Choose a research thread</option>';$('#research-thread-note').textContent='';status('');
    for(const s of ['#research-prepare','#research-send','#research-copy'])$(s).disabled=true;
    if(!dialog().open)dialog().showModal();rememberPage();await load();rememberPage();
  }
  async function operation(fn){
    if(busy||!pack)return;const token=generation;clearTimeout(timer);busy=true;paint();status('');
    try{const result=await fn();if(token!==generation||!dialog().open)return;pack=result;destinations();paint();rememberPage();schedule();}
    catch(e){if(token===generation&&dialog().open){status(e.message+' Refresh to check saved state before retrying.');await load(false);}}
    finally{if(token===generation){busy=false;paint();schedule();}}
  }
  async function prepare(){
    if(!prepareArgs){prepareKey=uid();prepareArgs={id,question:$('#research-question').value,expected_version:pack.itch_version,request_key:prepareKey};}
    await operation(async()=>{const data=await call('manager.research.prepare',prepareArgs);prepareArgs=null;prepareKey='';reportId='';section='brief';status('Brief saved. Review it before sending.');return data;});
  }
  async function send(){
    const run=pack.run;let pending;try{pending=JSON.parse(DMT3.read(localStorage,'dm-research-send:'+id));}catch{}
    const args=run.send?{id,run_id:run.id,thread_id:run.send.thread_id,request_key:run.send.request_key,expected_version:run.version}:pending?.run_id===run.id?pending:{id,run_id:run.id,thread_id:$('#research-thread').value,request_key:uid(),expected_version:run.version};
    try{DMT3.write(localStorage,'dm-research-send:'+id,JSON.stringify(args));}catch{}
    await operation(async()=>{const data=await call('manager.research.send',args);try{DMT3.remove(localStorage,'dm-research-send:'+id);}catch{}status('Sent for research. Findings appear here when saved by the agent.');return data;});
  }
  async function copy(){
    const token=generation,button=$('#research-copy');button.disabled=true;status('Copying research brief…');
    try{await Promise.race([navigator.clipboard.writeText(pack.run.brief),new Promise((_,reject)=>setTimeout(()=>reject(new Error('Copy timed out')),2500))]);if(token===generation&&dialog().open)status('Research brief copied.');}
    catch{if(token!==generation||!dialog().open)return;section='brief';paint();const el=$('.research-brief');el.tabIndex=0;el.focus();const range=document.createRange();range.selectNodeContents(el);const sel=getSelection();sel.removeAllRanges();sel.addRange(range);status('Copy was blocked. The brief is selected for manual copying.');}
    finally{if(token===generation){button.disabled=false;rememberPage();}}
  }
  function init(){
    $('#itch-research').onclick=()=>open(selected);
    $('#research-close').onclick=()=>dialog().close();dialog().addEventListener('close',()=>{generation++;clearTimeout(timer);rememberPage();$('#itch-research').focus();});
    dialog().addEventListener('keydown',e=>{if(e.key!=='Tab')return;const items=[...dialog().querySelectorAll('button:not(:disabled),a[href],input:not(:disabled),textarea:not(:disabled),select:not(:disabled),summary,[tabindex="0"]')].filter(el=>el.getClientRects().length);const first=items[0],last=items.at(-1);if(!first)return;if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus();}});
    $('#research-refresh').onclick=()=>load();$('#research-prepare').onclick=prepare;$('#research-send').onclick=send;$('#research-copy').onclick=copy;
    $('#research-thread').onchange=()=>paint();
    $('#research-question').oninput=()=>{prepareArgs=null;prepareKey='';rememberPage();};
    $('#research-pass').onchange=e=>{runId=e.target.value;reportId='';status('');load(false).then(rememberPage);};
    $('#research-report').onchange=e=>{reportId=e.target.value;paint();rememberPage();};
    $('#research-navigation').onclick=e=>{const button=e.target.closest('[data-research-section]');if(button){section=button.dataset.researchSection;paint();rememberPage();}};
    $('#research-body').onclick=e=>{if(!e.target.closest('#research-adopt'))return;const ids=[...document.querySelectorAll('[data-research-step]:checked')].map(b=>b.dataset.researchStep);if(!ids.length){status('Choose at least one proposed step.');return;}
      const run=pack.run,r=report();operation(async()=>{const data=await call('manager.research.adopt',{id,run_id:run.id,report_id:r.id,step_ids:JSON.stringify(ids),expected_version:run.version,itch_version:pack.itch_version,request_key:uid()});await refresh();status('Selected steps added. Nothing sent to T3.');return data;});};
  }
  return {init,open,page};
})();
