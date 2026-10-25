/* Webhook delivery is explicit and separate from social-account posting evidence. */
window.DMWebhook=(()=>{
  let config=null,loading=false,saving=false,settingsError='',settingsNote='',form={},active=null,preview=null,previewKey='',pendingPreview='',receipt=null,sending=false,receiptRun=0;
  const key=r=>r?`${r.id}:${r.version}`:'';
  function redraw(){if(view==='setup'&&settingsTab==='posting')renderSetup();else if(view==='tools'&&toolTab==='social')renderTools();}
  const signature=()=>JSON.stringify([config,loading,saving,settingsError,settingsNote]);
  async function loadSettings(){
    if(loading)return;
    loading=true;settingsError='';redraw();
    try{config=await call('manager.social.webhook_settings');}
    catch(e){settingsError=e.message;}
    finally{loading=false;redraw();}
    if(active)loadPreview(active);
  }
  function settingsMarkup(){
    const data={format:'discord',layout:'embed',bullets:true,markdown:true,...config,...form};
    return `<div class="tool-card webhook-settings"><h3>Webhook posts</h3><p>Send a looping card and its text from the post preview.</p>${settingsError?`<p role="alert">${esc(settingsError)}</p>`:''}<form id="webhook-settings"><label for="webhook-url">Webhook URL</label><input id="webhook-url" type="password" autocomplete="new-password" maxlength="2000" placeholder="${config?.configured?'Saved for '+esc(config.destination)+' · paste to replace':'https://…'}" value="${esc(form.url||'')}" ${saving?'disabled':''}><small>Saved on this PC with Windows encryption. Leave blank to keep it.</small><label for="webhook-format">Receiver</label><select id="webhook-format" ${saving?'disabled':''}><option value="discord" ${data.format==='discord'?'selected':''}>Discord-compatible</option><option value="generic" ${data.format==='generic'?'selected':''}>Generic multipart webhook</option></select><label for="webhook-layout">Text style</label><select id="webhook-layout" ${saving?'disabled':''}><option value="embed" ${data.layout==='embed'?'selected':''}>Embedded title + changes</option><option value="plain" ${data.layout==='plain'?'selected':''}>Plain message from caption</option></select><label class="webhook-check"><input id="webhook-bullets" type="checkbox" ${saving?'disabled':''} ${data.bullets?'checked':''}> Use bullets for changes</label><label class="webhook-check"><input id="webhook-markdown" type="checkbox" ${saving?'disabled':''} ${data.markdown?'checked':''}> Keep Markdown formatting</label><div class="detail-actions"><button class="primary" type="submit" ${saving||!config?'disabled':''}>${saving?'Saving…':'Save webhook'}</button><button class="secondary" type="button" data-webhook="forget" ${saving||!config?.configured?'disabled':''}>Forget URL</button><button class="quiet" type="button" data-webhook="reload" ${loading||saving?'disabled':''}>Reload settings</button></div><p role="status">${esc(settingsNote|| (loading?'Loading settings…':config?.configured?'Saved for '+config.destination+'. Nothing sends until you tap Send to webhook.':'Add a URL to connect.'))}</p><details><summary>Receiver details</summary><p>Discord gets the GIF as a file attachment and the chosen text style. Generic receivers get multipart fields named payload_json and file. Markdown is rendered by the destination. HTTP is supported for localhost receivers; other URLs use HTTPS.</p></details></form></div>`;
  }
  function captureForm(){
    if(!$('#webhook-settings'))return;
    form={url:$('#webhook-url').value,format:$('#webhook-format').value,layout:$('#webhook-layout').value,bullets:$('#webhook-bullets').checked,markdown:$('#webhook-markdown').checked};
  }
  async function saveSettings(clear=false){
    if(saving||!config)return;
    captureForm();saving=true;settingsError='';settingsNote='';redraw();
    try{
      config=await call('manager.social.webhook_configure',{expected_version:config.version,...form,...(clear?{url:'',clear_url:true}:{})});
      form={};settingsNote=clear?'Webhook URL forgotten.':'Webhook saved.';preview=null;previewKey='';
    }catch(e){settingsError=e.message;}
    finally{saving=false;redraw();}
    if(active)loadPreview(active);
  }
  async function loadPreview(row){
    if(!config)return;
    const expected=key(row)+':'+config.version;
    if(previewKey===expected||pendingPreview===expected)return;
    pendingPreview=expected;preview=null;redraw();
    try{
      const result=await call('manager.social.webhook_preview',{id:row.id,expected_version:row.version});
      if(key(active)===key(row)){
        config=result.settings;preview=result;previewKey=key(row)+':'+config.version;
      }
    }catch(e){if(key(active)===key(row))preview={error:e.message};}
    finally{if(pendingPreview===expected)pendingPreview='';redraw();}
  }
  async function open(row){
    const run=++receiptRun;
    if(key(active)!==key(row)){active={id:row.id,version:row.version};preview=null;previewKey='';receipt=null;}
    if(!config)await loadSettings();else loadPreview(row);
    const expected=key(row);
    try{const r=await call('manager.social.webhook_status',{id:row.id});if(run===receiptRun&&key(active)===expected&&!sending){receipt=r;redraw();}}
    catch{ /* A receipt read cannot trigger a retry or hide the draft. */ }
  }
  function cardMarkup(row,gif,blocked){
    if(key(active)===key(row))active={...active,gif,blocked};
    const fresh=previewKey===key(row)+':'+config?.version,body=fresh?preview?.payload:null;
    const embed=body?.embeds?.[0]||body?.embed;
    const text=embed?.description||body?.content||body?.text||'';
    const sameReceipt=receipt?.version===row.version;
    const state=receipt?.state,done=state==='sent',uncertain=['sending','unknown'].includes(state);
    const again=sameReceipt&&(done||uncertain);
    const disabled=blocked||!gif||sending||!config?.configured||!fresh||!!preview?.error;
    return `<section class="webhook-card" aria-label="Webhook post"><div class="tool-launch"><strong>Webhook</strong><button class="text-link" data-webhook="settings">Posting settings ↗</button></div>${config?.configured?`<small>${esc(config.destination)} · ${config.layout==='embed'?'Embedded text':'Plain message'}</small>`:'<p>Add your webhook in Settings → Posting.</p>'}${embed?`<p class="webhook-title">${esc(embed.title)}</p>`:''}${text?`<pre class="webhook-text">${esc(text)}</pre>`:''}${embed?.footer?`<small>${esc(embed.footer.text)}</small>`:''}${preview?.error?`<p role="alert">${esc(preview.error)}</p>`:''}<div class="detail-actions"><button class="secondary" data-webhook="send" ${disabled?'disabled':''}>${sending?'Sending GIF…':again?'Send another copy':'Send to webhook ↗'}</button>${uncertain?'<button class="quiet" data-webhook="receipt">Check receipt</button>':''}</div><p id="webhook-delivery" role="status">${sending?'Uploading the previewed GIF and text…':receipt&&state!=='not_sent'?esc((!sameReceipt?'Earlier draft · ':'')+(done?'Sent to '+receipt.destination+' · '+new Date(receipt.updated_at).toLocaleString():receipt.note||'No receipt yet. Check the destination before sending again.')):'Sends the animated GIF shown above. X posting status stays separate.'}</p>${receipt?.message_url?`<a href="${esc(receipt.message_url)}" target="_blank" rel="noopener noreferrer">Open Discord message ↗</a>`:''}</section>`;
  }
  async function send(){
    if(sending||!active||active.blocked||!active.gif||!config?.configured||previewKey!==key(active)+':'+config.version)return;
    const row={...active},expected=key(row),requestKey=uid();
    const args={id:row.id,expected_version:row.version,settings_version:config.version,sha256:row.gif.sha256,vibe:row.gif.vibe,theme:row.gif.requested_theme||'',request_key:requestKey,confirm:true};
    ++receiptRun;sending=true;redraw();
    try{
      const result=await call('manager.social.webhook_send',args);
      if(key(active)===expected)receipt=result;
    }catch(e){
      let result;
      try{result=await call('manager.social.webhook_status',{request_key:requestKey});}catch{}
      if(key(active)===expected)receipt=result&&result.state!=='not_sent'?result:{version:row.version,state:e.network?'unknown':'failed',note:e.message};
    }finally{sending=false;redraw();}
  }
  function sync(blocked){
    if(!active)return;
    active.blocked=blocked;
    const button=$('[data-webhook=send]');
    if(button)button.disabled=blocked||!active.gif||sending||!config?.configured||previewKey!==key(active)+':'+config.version||!!preview?.error;
  }
  document.addEventListener('submit',e=>{if(e.target.id==='webhook-settings'){e.preventDefault();saveSettings();}});
  for(const event of ['input','change'])document.addEventListener(event,e=>{if(e.target.closest('#webhook-settings'))captureForm();});
  document.addEventListener('click',e=>{
    const b=e.target.closest('[data-webhook]');if(!b||b.disabled)return;
    const action=b.dataset.webhook;
    if(action==='settings'){settingsTab='posting';setView('setup');return;}
    if(action==='send'){send();return;}
    if(action==='forget'){saveSettings(true);return;}
    if(action==='reload'){loadSettings();return;}
    if(action==='receipt'&&active)call('manager.social.webhook_status',{id:active.id}).then(r=>{receipt=r;redraw();}).catch(e=>toast(e.message));
  });
  return {settingsMarkup,signature,loadSettings,cardMarkup,open,sync};
})();
