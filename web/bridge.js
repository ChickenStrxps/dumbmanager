/* Discord configuration only. Shared workflows live in DumbAPI. */
window.DMBridge=(()=>{
  let data=null,form={},busy=false,error='',note='',preview=null,revision=0;
  const themes=['dumb','windows','mac','nvidia','t3','dog','cat','fish','shark','penguin','ohmypi','chill','nature','beach','desert','flow','smoke'];
  function redraw(){revision++;if(view==='setup'&&settingsTab==='bridge')renderSetup();}
  async function load(){
    if(busy)return;busy=true;error='';redraw();
    try{data=await call('bridge.status');}catch(e){error=e.message;}finally{busy=false;redraw();}
  }
  function capture(){
    if(!$('#bridge-config'))return;
    for(const key of ['enabled','animated','flashes'])form[key]=$('#bridge-'+key).checked;
    for(const key of ['application_id','public_key','users','channels','theme','bot_token'])form[key]=$('#bridge-'+key).value;
  }
  function settingsMarkup(){
    if(!data)return `<section class="tool-card"><h3>DumbBridge · Discord</h3><p role="status">${esc(error||'Loading bridge settings…')}</p><button class="secondary" data-bridge="reload" ${busy?'disabled':''}>Reload</button></section>`;
    const f={...data,users:data.users.join('\n'),channels:data.channels.join('\n'),...form};
    return `<section class="bridge-settings"><div class="tool-card"><span class="eyebrow">CHAT → SOMETHING REAL</span><h3>DumbBridge · Discord</h3><p>Turn a message into an itch, research it with Jev, find related ideas or send it to your T3 thread.</p><p>Fine-detail looping ASCII cards, changing critters and a rare Greg. Each card shows what actually happened.</p><p class="bridge-state" role="status">${data.enabled?'Enabled':'Disabled'} · ${data.configured?'Configured':'Not configured'} · ${data.last_verified_interaction?'Last signed Discord check: '+esc(new Date(data.last_verified_interaction).toLocaleString()):'No signed Discord check received'}</p>${!data.signature_verifier?'<p role="alert">OpenSSL is missing. Install Git for Windows or OpenSSL 3 before connecting.</p>':''}${error?`<p role="alert">${esc(error)}</p>`:''}
    <form id="bridge-config" class="ai-config"><label class="ai-check"><input id="bridge-enabled" type="checkbox" ${f.enabled?'checked':''}> Enable Discord interactions</label><label for="bridge-application_id">Discord application ID</label><input id="bridge-application_id" inputmode="numeric" maxlength="24" value="${esc(f.application_id)}"><label for="bridge-public_key">Application public key</label><input id="bridge-public_key" maxlength="64" value="${esc(f.public_key)}" spellcheck="false"><label for="bridge-users">Allowed user IDs</label><textarea id="bridge-users" rows="2" maxlength="2600" placeholder="Your Discord user ID">${esc(f.users)}</textarea><small>Only these users can use the bridge. One ID per line or separated by commas.</small><label for="bridge-channels">Allowed channel IDs (optional)</label><textarea id="bridge-channels" rows="2" maxlength="2600" placeholder="Leave blank to allow the listed users in any channel">${esc(f.channels)}</textarea>
    <label for="bridge-bot_token">Bot token · only for registering commands</label><input id="bridge-bot_token" type="password" maxlength="500" autocomplete="new-password" placeholder="${data.bot_key_saved?'Saved · leave blank to keep it':'Enter privately here'}"><small>Encrypted on this PC. Saved tokens never return to the form. Replies use signed, short-lived Discord interaction tokens.</small>
    <label for="bridge-theme">ASCII card style</label><select id="bridge-theme"><option value="">Surprise me</option>${themes.map(t=>`<option value="${t}" ${f.theme===t?'selected':''}>${esc(t==='smoke'?'Dithered smoke':t==='flow'?'Water flow':t[0].toUpperCase()+t.slice(1))}</option>`).join('')}</select><label class="ai-check"><input id="bridge-animated" type="checkbox" ${f.animated?'checked':''}> Animated GIF cards</label><label class="ai-check"><input id="bridge-flashes" type="checkbox" ${f.flashes?'checked':''}> Allow occasional lightning and light flickers</label><small>Flashes start off. Turning animation off uses a still ASCII card.</small>
    <div class="detail-actions"><button type="submit" class="primary">${busy?'Working…':'Save bridge'}</button><button type="button" class="secondary" data-bridge="forget" ${!data.bot_key_saved?'disabled':''}>Forget bot token</button><button type="button" class="quiet" data-bridge="reload">Reload</button></div></form><p role="status">${esc(note||'Saving settings does not start a listener or contact Discord.')}</p></div>
    <section class="tool-card"><h3>Connect your Discord app</h3><ol><li>Create an application in the <a href="https://discord.com/developers/applications" target="_blank" rel="noopener noreferrer">Discord developer portal ↗</a>. Copy its ID and public key above.</li><li>Start the listener on this PC:<pre class="bridge-code">py -3.14 dumbbridge.py serve</pre>Run this from the DumbAPI folder. Forward only <code>/interactions</code> from your own HTTPS address to <code>127.0.0.1:8780</code>, then set that URL as the app’s Interactions Endpoint URL.</li><li>Enable User Install in Discord’s Installation settings. Save a bot token privately above to register the two commands, then install the app.</li></ol><p>The PC and listener need to stay on. A configured adapter still needs a real signed Discord check and live flow test.</p><div class="detail-actions"><button type="button" class="secondary" data-bridge="preview" ${busy||!data.application_id?'disabled':''}>Review Discord commands</button></div>${preview?`<div class="bridge-command-preview"><h4>Commands for application ${esc(data.application_id)}</h4><ul><li>Message menu → Apps → DumbBridge</li><li><code>/dumbbridge message:</code> with an optional attachment</li></ul><p>Registering updates these two named commands. Existing app commands are preserved.</p><button type="button" class="primary" data-bridge="register" ${busy||!data.bot_key_saved?'disabled':''}>Register these two commands</button><p><a href="${esc(preview.install_url)}" target="_blank" rel="noopener noreferrer">Install this app to your Discord account ↗</a></p></div>`:''}</section></section>`;
  }
  function sync(){
    if($('#bridge-bot_token'))$('#bridge-bot_token').value=form.bot_token||'';
    for(const field of document.querySelectorAll('#bridge-config input,#bridge-config textarea,#bridge-config select,#bridge-config button'))field.disabled=busy||(field.dataset.bridge==='forget'&&!data?.bot_key_saved);
  }
  async function save(forget=false){
    if(busy||!data)return;capture();busy=true;error='';note='';preview=null;redraw();
    try{
      const args={...data, ...form,users:form.users??data.users.join('\n'),channels:form.channels??data.channels.join('\n'),bot_token:forget?'':form.bot_token||'',forget_token:forget,expected_version:data.version};
      for(const key of Object.keys(args))if(!['enabled','application_id','public_key','users','channels','animated','flashes','theme','bot_token','forget_token','expected_version'].includes(key))delete args[key];
      data=await call('bridge.configure',args);form={};note=forget?'Bot token forgotten.':'Saved. The listener and command registration are separate explicit steps.';
    }catch(e){error=e.message;}finally{busy=false;redraw();}
  }
  document.addEventListener('submit',e=>{if(e.target.id==='bridge-config'){e.preventDefault();save();}});
  for(const type of ['input','change'])document.addEventListener(type,e=>{if(e.target.closest('#bridge-config')){capture();preview=null;document.querySelector('.bridge-command-preview')?.remove();}});
  document.addEventListener('click',async e=>{
    const b=e.target.closest('[data-bridge]');if(!b||b.disabled||busy)return;
    const action=b.dataset.bridge;
    if(action==='reload'){await load();return;}
    if(action==='forget'){await save(true);return;}
    if(action==='preview'||action==='register'){
      busy=true;error='';note='';redraw();
      try{const result=await call('bridge.discord.register',{confirm:action==='register'});preview=result;note=result.registered?'Discord confirmed both command registrations. Install the app, then test its private message actions.':'Review the app ID and commands before registering.';}
      catch(err){error=err.message;}finally{busy=false;redraw();}
    }
  });
  return {load,settingsMarkup,sync,signature:()=>revision};
})();
