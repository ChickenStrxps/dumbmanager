'use strict';
window.DMAI=(()=>{
  let data=null,selected='openai_realtime',busy=false,loading=false,error='',note='',revision=0,pending=[],timer=null,tokenOnce='';
  const forms={};
  const row=()=>data?.items.find(r=>r.id===selected);
  const status=s=>({not_configured:'Not configured',configured:'Configured',connected:'Connected',unavailable:'Unavailable',error:'Error'}[s]||s);
  function redraw(){revision++;if(view==='setup'&&settingsTab==='ai'){renderSetup();sync();}}
  function defaults(r){return {enabled:r.enabled,model:r.model,allowed_capabilities:[...r.allowed_capabilities],settings:{...r.settings},credential:''};}
  function form(){return forms[selected]||(forms[selected]=defaults(row()));}
  async function load(force=false){
    if(loading||data&&!force){if(data)poll();return data;}
    loading=true;error='';redraw();
    try{data=await call('ai.integrations.list');if(force)for(const key of Object.keys(forms))delete forms[key];await poll();}
    catch(e){error=e.message;}
    finally{loading=false;redraw();}
    return data;
  }
  function settingsMarkup(){
    if(!data)return `<div class="tool-card"><h3>AI integrations</h3><p role="status">${esc(error||'Loading integrations…')}</p><button class="secondary" data-ai="reload" ${loading?'disabled':''}>Reload</button></div>`;
    const r=row(),f=form(),allowed=new Set(f.allowed_capabilities);
    const permissions=data.capabilities.map(c=>`<label class="ai-permission" data-ai-cap-label="${esc((c.id+' '+c.description).toLowerCase())}"><input type="checkbox" data-ai-cap="${esc(c.id)}" ${allowed.has(c.id)?'checked':''} ${busy?'disabled':''}><span><strong>${esc(c.id)}</strong> <small>${c.mode==='read'?'Read':'Approval required'}</small><span>${esc(c.description)}</span></span></label>`).join('');
    return `<section class="ai-settings"><div class="tool-launch"><div><h3>AI integrations</h3><p>Choose a connection, then choose what it can access.</p></div><button class="primary" data-ai="talk">Talk ↗</button></div><div class="ai-providers" role="group" aria-label="AI integrations">${data.items.map(p=>`<button type="button" class="ai-provider ${selected===p.id?'active':''}" data-ai-provider="${p.id}" aria-pressed="${selected===p.id}" ${busy?'disabled':''}><strong>${esc(p.label)}</strong><span class="ai-state ${p.state}">${status(p.state)}</span></button>`).join('')}</div>
      <div class="tool-card ai-config"><h3>${esc(r.label)}</h3><p>${esc(r.requirements)}</p><p class="ai-test-note">${esc(r.last_test?.note||'Adapter implemented. No connection has been tested.')}${r.last_test?' · '+esc(new Date(r.last_test.at).toLocaleString()):''}</p>${r.connection_observation?`<p>${esc(r.connection_observation)}</p>`:''}${error?`<p role="alert">${esc(error)}</p>`:''}
      <form id="ai-config"><label class="ai-check"><input id="ai-enabled" type="checkbox" ${f.enabled?'checked':''}> Enable this integration</label>
      ${r.kind==='voice'?`<label for="ai-model">Model ID</label><input id="ai-model" maxlength="150" value="${esc(f.model)}" required><label for="ai-credential">API key</label><input id="ai-credential" type="password" maxlength="2000" autocomplete="new-password" placeholder="${r.credential_saved?'Saved · leave blank to keep it':'Paste your provider API key'}"><small>Encrypted on this PC with Windows DPAPI. Saved keys never return to this form.</small><div class="ai-pair"><div><label for="ai-voice">Voice</label><select id="ai-voice">${r.voices.map(v=>`<option ${f.settings.voice===v?'selected':''}>${esc(v)}</option>`).join('')}</select></div><div><label for="ai-minutes">Session limit (minutes)</label><input id="ai-minutes" type="number" min="1" max="30" value="${f.settings.minutes}"></div></div>`:''}
      <label for="ai-instructions">Conversation instructions (optional)</label><textarea id="ai-instructions" rows="3" maxlength="4000">${esc(f.settings.instructions)}</textarea><small>Project context comes from the tools you grant. These instructions do not grant permissions.</small>
      <details class="ai-capabilities"><summary>Capabilities · ${allowed.size} allowed</summary><p>Read access can send the selected capability’s data to this provider. Every action waits for your review. Grants apply across the projects served by that capability.</p><label for="ai-cap-search">Find a capability</label><input id="ai-cap-search" type="search" placeholder="projects, source, manager, analytics, compression…"><div class="ai-permissions">${permissions}</div></details>
      <div class="detail-actions"><button class="primary" type="submit" ${busy?'disabled':''}>${busy?'Working…':'Save integration'}</button><button class="secondary" type="button" data-ai="test" ${busy||!r.enabled?'disabled':''}>Test connection</button>${r.kind==='voice'?`<button type="button" class="quiet" data-ai="forget" ${busy||!r.credential_saved?'disabled':''}>Forget key</button>`:''}<button class="quiet" type="button" data-ai="reload" ${busy||loading?'disabled':''}>Reload saved settings</button></div><p role="status">${esc(note)}</p></form>
      ${r.kind==='mcp'?`<section class="ai-mcp"><h4>Connect an MCP client</h4><p>The four tools share this integration’s allowlist. Local stdio is authenticated by access to this Windows account.</p><pre>${esc(JSON.stringify({command:r.mcp.command[0],args:r.mcp.command.slice(1)},null,2))}</pre><p>Optional stateless HTTP: <code>${esc(r.mcp.http_url)}</code></p><button type="button" class="secondary" data-ai="token" ${busy||!r.enabled?'disabled':''}>${r.http_token_issued?'Rotate HTTP token':'Create HTTP token'}</button>${tokenOnce?'<label for="ai-token-once">Scoped HTTP token · shown once</label><input id="ai-token-once" type="password" readonly autocomplete="off"><button class="quiet" data-ai="copy-token">Copy token</button>':''}<p>Dots: connect this stdio server through an OpenAI Secure MCP Tunnel, then add the custom MCP plugin to your dot. Dots access, tunnel setup and the final client test are still required.</p><a href="https://developers.openai.com/api/docs/guides/secure-mcp-tunnels" target="_blank" rel="noopener noreferrer">Private tunnel setup ↗</a></section>`:''}
      ${r.docs?`<a href="${esc(r.docs)}" target="_blank" rel="noopener noreferrer">Provider setup docs ↗</a>`:''}</div><section class="tool-card"><h3>Tool requests</h3><p>Review the exact action before it runs. Requests expire after 10 minutes.</p><div id="ai-approvals">${approvalMarkup()}</div><button class="quiet" data-ai="requests">Refresh requests</button></section></section>`;
  }
  function capture(){
    if(!row()||!$('#ai-config'))return;
    const f=form();f.enabled=$('#ai-enabled').checked;f.settings.instructions=$('#ai-instructions').value;
    if($('#ai-model')){f.model=$('#ai-model').value.trim();f.settings.voice=$('#ai-voice').value;f.settings.minutes=Number($('#ai-minutes').value);f.credential=$('#ai-credential').value;}
    f.allowed_capabilities=[...document.querySelectorAll('[data-ai-cap]:checked')].map(x=>x.dataset.aiCap);
  }
  function sync(){if($('#ai-credential')&&row())$('#ai-credential').value=form().credential;if($('#ai-token-once'))$('#ai-token-once').value=tokenOnce;for(const field of document.querySelectorAll('#ai-config input,#ai-config select,#ai-config textarea'))field.disabled=busy;}
  async function save(clear=false){
    capture();const r=row(),f=form();busy=true;error='';note='';redraw();
    try{
      if(window.DMVoice?.provider()===r.id)await DMVoice.stop('Settings changed. Start a new voice session.');
      const result=await call('ai.integrations.configure',{provider:r.id,expected_version:r.version,config:JSON.stringify({enabled:f.enabled,model:f.model,allowed_capabilities:f.allowed_capabilities,settings:f.settings}),credential:clear?'':f.credential,clear_credential:clear});
      data.items=data.items.map(p=>p.id===r.id?result:p);delete forms[r.id];note=clear?'Saved key forgotten.':'Saved. Test the connection when you’re ready.';
    }catch(e){error=e.message;}
    finally{busy=false;redraw();}
  }
  function approvalMarkup(){return pending.length?pending.map(r=>`<article class="ai-request"><strong>${esc(r.provider)} · ${esc(r.capability)}</strong><pre>${esc(JSON.stringify(r.arguments,null,2))}</pre><button class="primary" data-ai-approve="${esc(r.approval_id)}">Approve this action</button> <button class="secondary" data-ai-decline="${esc(r.approval_id)}">Decline</button></article>`).join(''):'<p>No pending actions.</p>';}
  async function poll(){
    clearTimeout(timer);
    if(view!=='setup'||settingsTab!=='ai')return;
    try{pending=(await call('ai.approvals.list')).items;if($('#ai-approvals'))$('#ai-approvals').innerHTML=approvalMarkup();}catch{}
    if(view==='setup'&&settingsTab==='ai')timer=setTimeout(poll,5000);
  }
  document.addEventListener('submit',e=>{if(e.target.id==='ai-config'){e.preventDefault();if(!busy)save();}});
  for(const kind of ['input','change'])document.addEventListener(kind,e=>{
    if(e.target.closest('#ai-config'))capture();
    if(e.target.id==='ai-cap-search')for(const label of document.querySelectorAll('[data-ai-cap-label]'))label.hidden=!label.dataset.aiCapLabel.includes(e.target.value.toLowerCase());
    if(e.target.matches('[data-ai-cap]')){const count=form().allowed_capabilities.length;e.target.closest('details').querySelector('summary').textContent='Capabilities · '+count+' allowed';}
  });
  document.addEventListener('click',async e=>{
    const b=e.target.closest('[data-ai],[data-ai-provider],[data-ai-approve],[data-ai-decline]');if(!b||b.disabled)return;
    if(b.dataset.aiProvider){capture();selected=b.dataset.aiProvider;tokenOnce='';note='';error='';redraw();return;}
    if(b.dataset.aiApprove||b.dataset.aiDecline){b.disabled=true;try{const receipt=await call('ai.approvals.decide',{id:b.dataset.aiApprove||b.dataset.aiDecline,approve:!!b.dataset.aiApprove});toast('Action '+receipt.state);await poll();}catch(err){toast(err.message);b.disabled=false;}return;}
    const action=b.dataset.ai;
    if(action==='talk'){DMVoice.open();return;}
    if(action==='reload'){tokenOnce='';await load(true);return;}
    if(action==='requests'){await poll();return;}
    if(action==='forget'){await save(true);return;}
    if(action==='copy-token'){try{await navigator.clipboard.writeText(tokenOnce);tokenOnce='';note='Token copied. Store it in your client’s secret settings.';redraw();}catch{toast('Clipboard unavailable. Select and copy the token field.');}return;}
    if(action==='test'||action==='token'){
      capture();busy=true;error='';note=action==='test'?'Testing the saved configuration…':'';redraw();
      try{
        const r=await call(action==='test'?'ai.integrations.test':'ai.integrations.issue_token',{provider:selected});
        if(action==='test'){data.items=data.items.map(p=>p.id===r.id?r:p);note=r.last_test.note;}else{tokenOnce=r.token;note='New scoped token created. Previous HTTP token revoked.';}
      }catch(err){error=err.message;}finally{busy=false;redraw();}
    }
  });
  return {load,settingsMarkup,sync,signature:()=>revision,providers:()=>data?.items||[],refreshRequests:poll};
})();
