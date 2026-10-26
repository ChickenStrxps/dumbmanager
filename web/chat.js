'use strict';
window.DMChat=(()=>{
  let enabled=false,workspaceVisible=true,threads=[],target='',snapshot=null,loading=false,sending=false,error='',timer=null,pending=null,readGeneration=0,threadLoad=null;
  const drafts=new Map();
  function keepPending(){if(pending)DMT3.write(sessionStorage,'dm-t3-pending',JSON.stringify(pending));else DMT3.remove(sessionStorage,'dm-t3-pending');}
  function ctx(){return state.contexts.find(c=>c.thread_id===target);}
  function selected(){return threads.find(t=>t.id===target)||snapshot?.thread;}
  function decorate(){if(enabled){$('#context-badge').textContent=target?'TO: '+(selected()?.title||'Selected thread').slice(0,45):'CHOOSE A T3 THREAD';$('#context-badge').title=target?(selected()?.title||'T3')+' · '+target:'';}}
  function candidates(){const c=ctx();return [...(c?.candidates||[]).map(s=>'Help me fix: '+s),...(c?.testing?['Help me test '+c.testing]:[]),...(c?.task?['What should I tackle next in '+c.task+'?']:[]),...state.itches.filter(r=>r.context?.thread_id===target&&DMIntake.usable(r)).map(r=>'Help me fix: '+r.title)];}
  function render(){
    $('#chat-panel').hidden=!enabled;$('#mode-chat').classList.toggle('active',enabled);$('#mode-itch').classList.toggle('active',!enabled);
    $('#mode-chat').setAttribute('aria-pressed',String(enabled));$('#mode-itch').setAttribute('aria-pressed',String(!enabled));
    DMUploads.render();
    if(!enabled)return;
    decorate();
    const select=$('#chat-thread'),value=select.value;
    const opts='<option value="">Choose a thread to chat…</option>'+threads.map(t=>`<option value="${esc(t.id)}">${esc(t.title)} · ${esc(t.project||'T3')}</option>`).join('');
    if(select.innerHTML!==opts){select.innerHTML=opts;select.value=target;}else if(value!==target)select.value=target;
    const row=selected();
    $('#chat-open').hidden=!target;$('#chat-open').href='t3-thread://v1/'+target;
    $('#chat-status').textContent=error||(!target?'Pick the exact thread above.':sending?'Sending your words…':loading?'Reading recent replies…':row?.active?'Agent is building · new messages queue after this run':snapshot?.queued?snapshot.queued+' queued · open T3 for the full run':'Connected · '+(row?.model||'thread model'));
    $('#chat-status').classList.toggle('amber',!!error);
    $('#chat-art').dataset.ascii=sending||loading?'load':row?.active?'scan':'orbit';
    $('#chat-refresh').disabled=loading||sending;
    const messages=snapshot?.messages||[];
    const feed=$('#chat-messages'),nearEnd=feed.scrollHeight-feed.scrollTop-feed.clientHeight<70;
    if(feed.dataset.thread!==target){feed.replaceChildren();feed.dataset.thread=target;}
    if(messages.length){
      feed.querySelector('.chat-empty')?.remove();const wanted=new Set(messages.map(m=>m.id));for(const node of [...feed.children])if(!wanted.has(node.dataset.id))node.remove();
      for(const [i,m]of messages.entries()){
        let node=[...feed.children].find(n=>n.dataset.id===m.id);if(!node){node=document.createElement('article');node.className='chat-message '+(m.role==='user'?'user':'assistant');node.dataset.id=m.id;feed.insertBefore(node,feed.children[i]||null);}
        const signature=JSON.stringify(m);if(node.messageSignature!==signature){node.messageSignature=signature;node.messageText=m.text;node.innerHTML='<header class="message-head"><span>'+ (m.role==='user'?'YOU':'T3')+(m.streaming?' · WRITING':'')+'</span>'+DMRich.time(m.at)+'<button type="button" class="quiet" data-copy-message aria-label="Copy message">Copy</button></header><div class="markdown">'+DMRich.render(m.text)+'</div>'+((m.attachments||[]).length?'<div class="message-files">'+m.attachments.map(a=>'<span>['+(a.type==='image'?'▧':'≡')+'] '+esc(a.name)+'</span>').join('')+'</div>':'')+(m.truncated?'<small>Continues in T3 ↗</small>':'');}
      }
    }else if(!feed.querySelector('.chat-empty'))feed.innerHTML=`<div class="chat-empty">${DMUI.ascii(loading?'load':'buddy')}<p>${target?'Recent replies will land here.':'Pick a thread to start chatting.'}</p></div>`;
    if(nearEnd)feed.scrollTop=feed.scrollHeight;
    DMPreviews.sync(target,snapshot?.previews||[],messages);
    $('#chat-note').textContent=snapshot?.note||'Enter sends your words. Tab accepts a completion. Active work keeps running.';
    $('#chat-retry').hidden=!pending||sending;$('#chat-retry').textContent='Retry same message → '+(pending?.title||'T3');
    $('#chat-dismiss').hidden=!pending||sending;
    DMUI.sync();
  }
  async function loadThreads(){
    if(threadLoad)return threadLoad;
    threadLoad=(async()=>{loading=true;error='';render();try{const data=await call('t3.threads',{limit:200});threads=data.items;if(target&&!threads.some(t=>t.id===target)){const c=state.contexts.find(c=>c.thread_id===target);threads.unshift({id:target,title:c?.task||'Pinned thread',project:c?.project||'T3'});}}catch(e){error=e.message;}finally{loading=false;threadLoad=null;render();updateSuggestions();}})();
    return threadLoad;
  }
  async function read(){
    if(!enabled||!workspaceVisible||!target||loading||document.hidden)return;
    const id=target,generation=++readGeneration;loading=true;error='';render();
    try{const data=await call('t3.read',{thread_id:id});if(target===id&&generation===readGeneration){snapshot=data;const i=threads.findIndex(t=>t.id===id);if(i>=0)threads[i]={...threads[i],...data.thread};}}
    catch(e){if(target===id&&generation===readGeneration)error=e.message;}
    finally{if(generation===readGeneration){loading=false;render();}schedule();}
  }
  function schedule(){clearTimeout(timer);if(enabled&&workspaceVisible&&target)timer=setTimeout(read,error?15000:snapshot?.thread.active?5000:12000);}
  function workspace(visible){if(workspaceVisible===visible)return;workspaceVisible=visible;clearTimeout(timer);if(visible&&enabled)read();}
  async function mode(value){
    if(value&&DMIntake.splitting)DMIntake.split(false);
    const was=enabled;enabled=value;clearTimeout(timer);
    if(enabled&&!was){target=pending?.thread_id||context()?.thread_id||target;if(!threads.some(t=>t.id===target)&&target)threads.unshift({id:target,title:pending?.title||context()?.task||'Pinned thread',project});snapshot=null;error='';}
    renderContext();if(!enabled){$('#context-badge').removeAttribute('title');DMPreviews.pause();}render();updateSuggestions();$('#command').focus();
    if(enabled){await loadThreads();await read();}
  }
  async function send(text,retry=false){
    if(sending)return;
    if(DMUploads.busy)return toast('Receipts still uploading. Give it a sec.');
    if(!retry){if(!target)return toast('Pick a T3 thread first.');if(!text.trim()&&!DMUploads.attachments.length)return;if(text.length>12000)return toast('Keep chat under 12,000 characters.');if(pending)return toast('Retry or dismiss the last message first.');pending={thread_id:target,message:text,attachments:DMUploads.attachments,request_key:uid(),title:selected()?.title||target};}
    const request=pending;if(!request)return;try{keepPending();}catch{return toast('Browser storage is full. Clear space before sending so retries can stay safe.');}sending=true;error='';render();signal('Sending to your exact T3 thread.','T3 · WORKING','load');
    try{
      const result=await call('t3.send',{thread_id:request.thread_id,message:request.message,request_key:request.request_key,attachments:JSON.stringify(request.attachments||[])});
      pending=null;keepPending();DMUploads.commit(request.thread_id,request.attachments||[]);if(target===request.thread_id&&$('#command').value.trim()===request.message)$('#command').value='';drafts.delete(request.thread_id);toast(result.note);await read();
    }catch(e){error=e.message;toast(e.message);}
    finally{sending=false;render();updateSuggestions();}
  }
  function init(){
    DMPreviews.init();
    $('#chat-messages').onclick=async e=>{const b=e.target.closest('[data-copy-code],[data-copy-message]');if(!b)return;const text=b.hasAttribute('data-copy-code')?b.closest('.code-block').querySelector('code').textContent:b.closest('.chat-message').messageText;try{await navigator.clipboard.writeText(text);b.textContent='Copied ✓';setTimeout(()=>{if(b.isConnected)b.textContent=b.hasAttribute('data-copy-code')?'Copy code':'Copy';},1600);}catch{toast('Couldn’t copy. Select the text and copy it.');}};
    try{const p=JSON.parse(DMT3.read(sessionStorage,'dm-t3-pending')||'null');if(p&&typeof p.thread_id==='string'&&typeof p.message==='string'&&p.message.length<=12000&&typeof p.request_key==='string')pending=p;}catch{}
    DMUploads.init(()=>sending||!!pending);if(pending)DMUploads.restore(pending.thread_id,pending.attachments);
    $('#mode-chat').onclick=()=>mode(true);$('#mode-itch').onclick=()=>{DMIntake.split(false);return mode(false);};
    $('#chat-thread').onchange=async()=>{drafts.set(target,$('#command').value);target=$('#chat-thread').value;$('#command').value=drafts.get(target)||'';snapshot=null;readGeneration++;loading=false;error='';render();updateSuggestions();await read();};
    $('#chat-refresh').onclick=async()=>{await loadThreads();await read();};
    $('#chat-retry').onclick=()=>send('',true);
    $('#chat-dismiss').onclick=()=>{pending=null;keepPending();render();toast('Dismissed. Check T3 before sending it again.');};
    document.addEventListener('visibilitychange',()=>{if(document.hidden)clearTimeout(timer);else if(enabled)read();});
  }
  return {init,mode,send,workspace,candidates,decorate,context:ctx,get activityRevision(){return snapshot?.messages?.map(m=>m.id+':'+m.text?.length+':'+m.text?.slice(-80)).join('|')||'';},get enabled(){return enabled;},get target(){return target;},get sending(){return sending;}};
})();
