'use strict';
window.DMT3=(()=>{
  let data=null,choice='',busy=false,error='',target='';
  const legacyOwner='dm-t3-legacy-owner';
  const key=name=>target?name+':target:'+target:name;
  function read(storage,name){
    const value=storage.getItem(key(name));
    return value===null&&localStorage.getItem(legacyOwner)===target?storage.getItem(name):value;
  }
  function write(storage,name,value){storage.setItem(key(name),value);if(localStorage.getItem(legacyOwner)===target)storage.removeItem(name);}
  function remove(storage,name){storage.removeItem(key(name));if(localStorage.getItem(legacyOwner)===target)storage.removeItem(name);}
  async function init(){
    try{
      data=await call('t3.distributions');target=data.target;choice=data.selected||'t3';
      if(!localStorage.getItem(legacyOwner))localStorage.setItem(legacyOwner,target);
      const draft=read(sessionStorage,'dm-t3-command');if(draft)$('#command').value=draft;
    }catch(e){error=e.message;}
  }
  function markup(){
    const current=data?.items.find(r=>r.selected),selected=data?.items.find(r=>r.id===choice);
    return `<div class="tool-card" id="t3-distribution-card"><h3>T3 distribution</h3>
      <p>Open the standard local T3 Code installation before connecting.</p>
      <p id="t3-current"><strong>Current: ${esc(current?.label||'Not connected')}</strong>${current?'<br><small>'+esc(current.endpoint)+'</small>':''}</p>
      <label for="t3-distribution">Send T3 work to</label>
      <select id="t3-distribution" ${busy||!data?'disabled':''}>${(data?.items||[{id:'t3',label:'T3 Code'}]).map(r=>`<option value="${esc(r.id)}" ${r.id===choice?'selected':''}>${esc(r.label)}${!r.installed&&!r.configured?' · not installed':''}</option>`).join('')}</select>
      <div class="detail-actions"><button type="button" class="primary" id="t3-switch" ${busy||!data?'disabled':''}>${busy?'Checking connection…':choice===data?.selected?'Test connection':'Switch & connect'}</button><button type="button" class="secondary" id="t3-reconnect" ${busy||!data?'disabled':''}>Reconnect</button></div>
      <p id="t3-distribution-status" role="status" aria-live="polite">${esc(error||(!data?'Connection choices unavailable. Reopen settings to retry.':busy?'Verifying the selected installation.':selected?.verified_at?'Last verified '+new Date(selected.verified_at).toLocaleString()+'. Verify again to check now.':selected?.configured?'Session saved. Test connection to check it now.':selected&&!selected.installed?'This installation’s local CLI was not found. Open it with its launcher first.':'No session saved for this installation yet.'))}</p>
      <p>Thread choices and pending sends stay with each installation. Switching sends no message and keeps your itches.</p>
      <details><summary>Connection details</summary><p>Pairing uses that installation’s own profile and a dedicated 30-day local session. A failed check keeps the current connection. This setting changes DumbManager’s connection; use each app’s launcher to open or close it. </p></details></div>`;
  }
  function sync(){
    const select=$('#t3-distribution');if(!select)return;
    select.onchange=()=>{choice=select.value;error='';renderSetup();$('#t3-distribution-trigger')?.focus();};
    $('#t3-switch').onclick=()=>selectDistribution(false);
    $('#t3-reconnect').onclick=()=>selectDistribution(true);
  }
  async function load(){
    if(busy)return;
    try{const result=await call('t3.distributions');if(target&&result.target!==target){changed();return;}data=result;choice=result.selected||'t3';error='';}
    catch(e){error=e.message;}
    renderSetup();
  }
  function changed(){
    let banner=$('#t3-changed');if(banner)return;
    banner=document.createElement('div');banner.id='t3-changed';banner.className='notice';banner.setAttribute('role','alert');
    banner.innerHTML='The T3 installation changed. Reload to use its thread choices. <button type="button" class="secondary">Save draft & reload</button>';
    banner.querySelector('button').onclick=()=>{try{write(sessionStorage,'dm-t3-command',$('#command').value);}catch{}location.reload();};
    document.querySelector('main').prepend(banner);
  }
  async function selectDistribution(reconnect){
    if(busy||!data)return;
    if(DMChat.sending||DMUploads.busy){error='Let the current send or upload finish before switching.';renderSetup();return;}
    // Save unsent words before the server changes connection; a reload clears old thread caches.
    try{write(sessionStorage,'dm-t3-command',$('#command').value);}catch{error='Browser storage is full. Save your draft before switching.';renderSetup();return;}
    busy=true;error='';renderSetup();
    try{
      const result=await call('t3.select_distribution',{distribution:choice,reconnect,expected_target:target});
      const different=result.target!==target;
      data=result;
      if(different){location.reload();return;}
      toast(result.note);
    }catch(e){error=e.message;}
    finally{busy=false;renderSetup();}
  }
  return {init,load,markup,sync,read,write,remove,changed,get target(){return target;},signature:()=>JSON.stringify([data,choice,busy,error])};
})();
