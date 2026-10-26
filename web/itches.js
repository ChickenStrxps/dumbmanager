'use strict';
window.DMItches=(()=>{
  const drafts=new Map(),owner=crypto.randomUUID();let pending={},threads=[],generation=0,mediaGeneration=0,mediaURL='',busyId='',targetQueue=Promise.resolve(),targetTimer=null,pollTimer=null,lastPublished=0,kitchenSignature='';
  const row=()=>state.itches.find(r=>r.id===selected);
  function persist(){DMT3.write(localStorage,'dm-itch-sends',JSON.stringify(pending));}
  function clearMedia(){mediaGeneration++;const stage=$('#itch-media-stage');stage.querySelector('video')?.pause();stage.replaceChildren();if(mediaURL)URL.revokeObjectURL(mediaURL);mediaURL='';}
  async function showMedia(index=0){
    clearMedia();const r=row(),files=r?.attachments||[],a=files[index];$('#itch-media').hidden=!a;if(!a)return;
    const token=mediaGeneration;$('#itch-media-position').textContent=files.length>1?(index+1)+' / '+files.length:'';
    $('#itch-media-choices').hidden=files.length<2;
    $('#itch-media-choices').innerHTML=files.map((f,i)=>'<button type="button" class="'+(i===index?'primary':'secondary')+'" data-popup-media="'+i+'" aria-pressed="'+(i===index)+'">'+esc(f.name)+'</button>').join('');
    const stage=$('#itch-media-stage');stage.innerHTML='<p class="media-loading">'+DMUI.ascii('load')+' Pulling up the receipts…</p>';
    try{
      const blob=await DMUploads.read(a);if(token!==mediaGeneration)return;
      mediaURL=URL.createObjectURL(blob);stage.replaceChildren();const media=document.createElement(a.type==='video'?'video':'img');
      if(a.type==='video'){media.muted=true;media.playsInline=true;media.preload='metadata';}else media.alt=a.name;
      const button=document.createElement('button');button.type='button';button.className='itch-media-thumb';button.dataset.itchMedia=a.id;button.setAttribute('aria-label',(a.type==='video'?'Play video: ':'Enlarge image: ')+a.name);
      media.src=mediaURL;button.append(media);stage.append(button);
      const caption=document.createElement('p');caption.textContent=a.name;const hint=document.createElement('small');hint.textContent=a.type==='video'?'Tap to play video ↗':'Tap to enlarge ↗';caption.append(hint);stage.append(caption);
      media.onerror=()=>{caption.textContent=a.name+' · This browser cannot preview it. Save a copy to open elsewhere.';};
    }catch(e){if(token===mediaGeneration)stage.textContent=e.message;}
  }
  function open(id,cook=false){
    const r=state.itches.find(r=>r.id===id);if(!r)return;
    generation++;selected=id;render();const modal=$('#itch-view');$('#itch-more').open=false;$('#itch-brief-options').open=false;$('#itch-notes').open=false;$('#itch-plan-details').open=false;
    if(!modal.open)modal.showModal();modal.scrollTop=0;showMedia();
    rememberPage();
    const focusGeneration=generation;targetQueue=targetQueue.catch(()=>{}).then(()=>{if(modal.open&&generation===focusGeneration)return post('/api/cook',{action:'focus',owner,id,activate:true});});schedulePoll();
    $('#itch-shortcut').textContent='';
    const current=generation;post('/api/native',{action:'status'}).then(value=>{
      if(current!==generation)return;const key=value.running&&value.bindings?.['4'];
      $('#itch-shortcut').textContent=key||'';
      $('#itch-shortcut').title=key?'Sends this itch to the thread above.':'Turn on global keys in Settings → Shortcuts.';
    }).catch(()=>{});
    prepare();
  }
  function draft(){
    const r=row();if(!r)return null;
    if(!drafts.has(r.id)){
      const old=pending[r.id];
      drafts.set(r.id,{thread_id:r.handoffs?.at(-1)?.thread_id||r.context?.thread_id||'',message:'',video_mode:'frameboard',ready:!!old,...(old?.args||{}),scope:old?.scope||'next',recook:!!old?.recook,refactoring:!!old?.refactoring,followup:old?.args?.followup||'',...(old?.draft_message!==undefined?{message:old.draft_message}:{})});
    }
    return drafts.get(r.id);
  }
  function scopedMessage(r,d){
    const moves=r.plan.filter(t=>!t.done),chosen=d.scope==='all'?moves:moves.slice(0,1);
    if(!chosen.length||d.recook)return d.message;
    return `Execution scope: ${d.scope==='all'?'all remaining moves in this itch':'the next unfinished move only'}.\nSelected stable task IDs: ${JSON.stringify(chosen.map(t=>t.id))}\n${chosen.map(t=>'['+t.id+'] '+t.text).join('\n')}\nRecheck these moves before edits. Other plan steps are context; do not execute or mark unselected tasks done. Report reviewable results, leaving acceptance to the user.\n\n${d.message}`;
  }
  function paint(){
    if(!$('#itch-view').open)return;
    const r=row(),d=draft(),p=pending[r.id];if(!d)return;
    const mode={...kitchenMode(r,d.recook||p?.started),refactoring:d.refactoring},signature=JSON.stringify([r.id,r.version,!!d.recook,!!p?.started,!!d.refactoring]);
    if(kitchenSignature!==signature){kitchenSignature=signature;$('#itch-next').innerHTML=kitchenMarkup(r,mode);}
    const values=p?.started?p.args:d,items=[...threads];
    if(values.thread_id&&!items.some(t=>t.id===values.thread_id))items.unshift({id:values.thread_id,title:r.context?.thread_id===values.thread_id?(r.context.task||'Saved itch thread'):values.thread_id});
    const select=$('#itch-thread');select.innerHTML='<option value="">Pick a T3 thread</option>'+items.map(t=>'<option value="'+esc(t.id)+'">'+esc(t.title+(t.project?' · '+t.project:''))+'</option>').join('');select.value=values.thread_id;
    $('#itch-message').value=values.message;$('#itch-video').value=values.video_mode;
    const locked=!!p?.started||!!busyId;select.disabled=locked;$('#itch-message').disabled=locked;$('#itch-video').disabled=locked;
    $('#itch-refactor').hidden=!d.refactoring;$('#itch-followup').value=d.followup;$('#itch-followup').disabled=locked;$('#itch-refactor-cancel').disabled=locked;
    const count=(r.attachments||[]).length;
    $('#itch-thread-note').textContent=(count?count+' receipt'+(count===1?'':'s')+' · ':'')+(d.refactoring?'Same itch. Another pass.':mode.moves.length&&!d.recook?'Sends the next step. “Send all” sends every step.':'Queues in T3.');
    const inactive=mode.review||mode.active;
    $('.itch-send-row').hidden=inactive;$('#itch-thread-note').hidden=inactive;$('#itch-shortcut').hidden=inactive;
    $('#itch-video-options').hidden=!(r.attachments||[]).some(a=>a.type==='video');
    const send=$('#itch-send-now');send.disabled=inactive||!!busyId||(!p&&!d.ready)||!values.thread_id||!!d.receipt||(d.refactoring&&!d.followup.trim());
    send.innerHTML=busyId===r.id?DMUI.ascii('load')+' Sending…':d.receipt?'Sent ✓':p?.started?'Retry send ↗':d.refactoring?'Back to kitchen ↗':'Send to T3 ↗';
    const all=$('#itch-send-all');all.hidden=inactive||mode.moves.length<2||!!d.recook||!!p?.started||!!d.receipt;
    all.disabled=send.disabled;all.textContent='Send all · '+mode.moves.length;all.title='Send every remaining step to the selected T3 thread.';
    $('#itch-send-state').hidden=!(busyId===r.id||d.error||d.receipt||p?.started||!d.ready);
    $('#itch-send-state').innerHTML=busyId===r.id?DMUI.ascii('scan')+' Sending…':esc(d.error||(d.receipt?'Sent. T3 is on it.':p?.started?'Didn’t get a reply. Retry is safe, it won’t double-send.':d.ready?'':'Preparing…'));
    const sent=$('#itch-sent-link'),threadURL=d.receipt?.thread_url||((inactive&&r.handoffs?.length)?'t3-thread://v1/'+r.handoffs.at(-1).thread_id:'');sent.hidden=!threadURL;if(threadURL)sent.href=threadURL;
    $('#itch-send-new').hidden=!!p?.started||(!d.receipt&&!inactive);DMUI.sync();
  }
  async function prepare(){
    const r=row();if(!r)return;const id=r.id,token=generation,d=draft();
    paint();
    const results=await Promise.allSettled([d.ready?Promise.resolve(null):call('manager.brief',{id}),call('t3.threads',{limit:200})]);
    if(results[0].status==='fulfilled'){
      if(results[0].value&&!d.ready)d.message=results[0].value.brief.replace('Open this itch in DumbManager to inspect it. These local files are not automatically sent to T3.','The visual evidence is attached to this message. Video frameboards contain sampled timestamps and no audio.');
      d.ready=true;
    }else d.error=results[0].reason.message;
    if(results[1].status==='fulfilled')threads=results[1].value.items;else if(!d.error)d.error=results[1].reason.message;
    if(token===generation&&selected===id){paint();await publish(true);schedulePoll();}
  }
  function clearTarget(){targetQueue=targetQueue.catch(()=>{}).then(()=>post('/api/cook',{action:'clear',owner}));return targetQueue;}
  function publish(activate=false){
    clearTimeout(targetTimer);const id=selected,token=generation;
    targetQueue=targetQueue.catch(()=>{}).then(async()=>{
      if(!$('#itch-view').open||token!==generation||selected!==id)return;
      await post('/api/cook',{action:'focus',owner,id,activate});lastPublished=Date.now();
      const d=draft(),mode=kitchenMode(row(),d?.recook||pending[id]?.started);
      if(d?.refactoring&&!d.followup.trim()&&!pending[id]?.started){delete pending[id];persist();}
      if(!d?.ready||!d.thread_id||d.receipt||mode.review||mode.active||(d.refactoring&&!d.followup.trim()))return post('/api/cook',{action:'clear',owner});
      const old=pending[id],args=old?.started?old.args:{id,thread_id:d.thread_id,message:scopedMessage(row(),d),video_mode:d.video_mode,...(d.refactoring?{followup:d.followup.trim()}:{})};
      if(args.message.length>12000)throw new Error('Too long. Keep the message under 12,000 characters.');
      if(!args.request_key){const comparable={...old?.args};delete comparable.request_key;args.request_key=old&&JSON.stringify(comparable)===JSON.stringify(args)?old.args.request_key:uid();}
      pending[id]={args,started:!!old?.started,scope:d.scope,recook:!!d.recook,refactoring:!!d.refactoring,draft_message:d.message};persist();
      lastPublished=Date.now();return post('/api/cook',{action:'prepare',owner,args,activate,t3_target:window.DMT3?.target});
    });
    return targetQueue.catch(e=>{const d=drafts.get(id);if(d)d.error=e.message;paint();return false;});
  }
  function edited(){clearTarget().catch(()=>{});clearTimeout(targetTimer);targetTimer=setTimeout(()=>publish(true),250);}
  async function settle(id,status){
    const p=pending[id],d=drafts.get(id);if(!p||!d)return;
    if(status.busy){if(!p.started){p.started=true;persist();}busyId=id;if(selected===id&&$('#itch-view').open)paint();}
    else if(status.result){d.receipt=status.result;d.error='';if(d.refactoring){d.refactoring=false;d.recook=false;d.followup='';}delete pending[id];persist();if(busyId===id)busyId='';await refresh();paint();toast('Sent to T3 with receipts.');}
    else if(status.error){p.started=true;persist();d.error=status.error+' Retry is safe.';if(busyId===id)busyId='';paint();}
  }
  function schedulePoll(){clearTimeout(pollTimer);pollTimer=setTimeout(poll,800);}
  async function poll(){
    const id=busyId||($('#itch-view').open?selected:null),p=pending[id];
    try{if(p)await settle(id,await post('/api/cook',{action:'status',request_key:p.args.request_key}));if($('#itch-view').open&&Date.now()-lastPublished>5000){
      const token=generation,itchId=selected,old=row(),fresh=await call('manager.get',{id:itchId});merge(fresh);if(token!==generation||selected!==itchId||!$('#itch-view').open)return;renderDetail();paint();if((old?.attachments||[]).map(a=>a.id).join()!==(fresh.attachments||[]).map(a=>a.id).join())showMedia(fresh.attachments.length-1);await publish();
    }}catch{}
    if(busyId||$('#itch-view').open)schedulePoll();
  }
  async function send(scope){
    const r=row(),d=draft();if(!r||!d||busyId)return;
    const mode=kitchenMode(r,d.recook||pending[r.id]?.started);if(mode.review||mode.active)return;
    if(scope&&!pending[r.id]?.started)d.scope=scope;
    if(!d.ready||!d.thread_id)return toast('Pick the T3 thread first.');
    if(await publish(true)===false)return;const p=pending[r.id];if(!p)return;
    p.started=true;try{persist();}catch{return toast('Browser storage is full. Free up space so the send can retry safely.');}
    busyId=r.id;d.error='';paint();
    try{
      await settle(r.id,await post('/api/cook',{action:'send',owner,request_key:p.args.request_key}));
    }catch(e){busyId='';d.error=e.message+' Retry is safe.';paint();}
    finally{schedulePoll();}
  }
  function refactor(){
    const r=row(),d=draft();if(!r||!d||busyId||pending[r.id]?.started)return;
    clearTarget().catch(()=>{});delete pending[r.id];persist();delete d.receipt;
    d.recook=true;d.refactoring=true;d.error='';d.ready=false;d.message='';
    d.thread_id=r.handoffs?.at(-1)?.thread_id||d.thread_id||r.context?.thread_id||'';
    paint();prepare();$('#itch-followup').focus();
  }
  function init(){
    $('#itch-research').onclick=()=>DMResearch.open(selected);
    try{const saved=JSON.parse(DMT3.read(localStorage,'dm-itch-sends')||'{}');for(const [id,value]of Object.entries(saved).slice(0,20))if(value?.args?.id===id&&typeof value.args.thread_id==='string'&&typeof value.args.message==='string'&&typeof value.args.request_key==='string')pending[id]=value;}catch{}
    $('#itch-close').onclick=()=>{$('#itch-view').close();rememberPage();};$('#itch-view').addEventListener('cancel',e=>{e.preventDefault();$('#itch-view').close();rememberPage();});$('#itch-view').addEventListener('close',()=>{if($('#itch-view').open)return;generation++;clearTimeout(targetTimer);clearTarget();targetQueue=targetQueue.catch(()=>{}).then(()=>post('/api/cook',{action:'unfocus',owner}));targetQueue.catch(()=>{});DMUI.close();clearMedia();rememberPage();});
    $('#itch-snip').onclick=async()=>{const button=$('#itch-snip');button.disabled=true;try{await post('/api/native',{action:'snip',itch_id:selected});toast('Drag a box on your PC. Esc cancels.');}catch(e){toast(e.message);}finally{button.disabled=false;}};
    $('#itch-send-now').onclick=()=>send('next');$('#itch-send-all').onclick=()=>send('all');
    $('#itch-next').onclick=e=>{if(e.target.closest('[data-review-learn]'))return DMLearning.open(selected);if(e.target.closest('[data-review-refactor]'))return refactor();if(e.target.closest('[data-review-accept]'))action('accept').catch(e=>toast(e.message));};
    $('#itch-followup').oninput=e=>{draft().followup=e.target.value;paint();edited();};
    $('#itch-refactor-cancel').onclick=()=>{const d=draft();if(!d||busyId||pending[selected]?.started)return;clearTimeout(targetTimer);clearTarget().catch(()=>{});d.refactoring=false;d.recook=false;d.error='';delete pending[selected];persist();paint();publish(true);};
    $('#itch-send-new').onclick=refactor;
    $('#itch-extra-actions').onclick=()=>{$('#itch-more').open=false;};
    $('#itch-view').addEventListener('keydown',e=>{if(e.key==='Escape'&&$('#itch-more').open){e.preventDefault();e.stopPropagation();$('#itch-more').open=false;$('#itch-more > summary').focus();}});
    $('#itch-thread').onchange=e=>{draft().thread_id=e.target.value;paint();edited();};
    $('#itch-message').oninput=e=>{draft().message=e.target.value;edited();};$('#itch-video').onchange=e=>{draft().video_mode=e.target.value;edited();};
    $('#itch-media-choices').onclick=e=>{const button=e.target.closest('[data-popup-media]');if(button)showMedia(Number(button.dataset.popupMedia));};
    $('#itch-media-stage').onclick=e=>{const button=e.target.closest('[data-itch-media]');if(!button)return;const a=row()?.attachments?.find(a=>a.id===button.dataset.itchMedia);if(a)DMUploads.open(a);};
    window.addEventListener('focus',()=>{if($('#itch-view').open)publish(true);});
    window.addEventListener('pagehide',()=>{for(const action of ['clear','unfocus'])fetch('/api/cook',{method:'POST',headers:{'Content-Type':'application/json','X-DumbManager':'1'},body:JSON.stringify({action,owner}),keepalive:true}).catch(()=>{});});
  }
  return {init,open,cook:id=>open(id,true),decorate:paint};
})();
