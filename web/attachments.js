'use strict';
window.DMUploads=(()=>{
  const queues=new Map(),thumbs=new Map(),videoModes={itch:'original',chat:'frameboard'};let busy=false,locked=()=>false,lastMode='',previewURL='',previewGeneration=0;
  const key=()=>DMChat.enabled?DMChat.target:'@itch';
  const blocked=()=>DMChat.enabled?locked():saving;
  const rows=()=>queues.get(key())||[];
  const size=n=>n<1024*1024?Math.ceil(n/1024)+' KB':(n/(1024*1024)).toFixed(1)+' MB';
  function save(){const value={};for(const [key,items]of queues)if(items.length)value[key]=items.map(({attachment,note})=>({attachment,note}));const itch=value['@itch']||[];delete value['@itch'];localStorage.setItem('dm-itch-files',JSON.stringify(itch));DMT3.write(sessionStorage,'dm-t3-files',JSON.stringify(value));}
  function render(){
    const root=$('#chat-attachments');root.hidden=false;root.setAttribute('aria-label',DMChat.enabled?'Chat attachments':'Itch evidence');
    const mode=DMChat.enabled?'chat':'itch';if(mode!==lastMode){$('#video-mode').value=videoModes[mode];lastMode=mode;}
    $('#attachment-input').accept=DMChat.enabled?'':'image/png,image/jpeg,image/webp,image/gif,video/*';
    $('#video-mode option[value=original]').textContent=DMChat.enabled?'Original file · provider dependent':'Keep video · play locally';
    $('#attach-pick span').textContent=DMChat.enabled?'attach files':'images / videos';
    $('#attach-pick').disabled=busy||blocked()||(DMChat.enabled&&!DMChat.target);$('#video-mode').disabled=busy||blocked();
    $('#attach-state').innerHTML=busy?DMUI.ascii('load')+' Uploading / preparing…':(DMChat.enabled?'Paste / drop · up to 8 per message':'Paste / drop · saved with your itch · up to 8');
    const list=$('#attachment-chips');list.replaceChildren();
    for(const row of rows()){
      const a=row.attachment,node=document.createElement('div');node.className='attachment-chip';
      const thumbnail=thumbs.get(a.id);node.innerHTML=(thumbnail&&a.type!=='video'?'<button type="button" class="attachment-thumb" aria-label="View '+esc(a.name)+'"><img alt="" src="'+esc(thumbnail)+'"></button>':'<button type="button" class="attachment-thumb file-art" aria-label="View '+esc(a.name)+'">[ '+(a.type==='video'?'▶':a.type==='image'?'▧':'≡')+' ]</button>')+'<div><b>'+esc(a.name)+'</b><small>'+esc(size(a.sizeBytes)+(row.note?' · '+row.note:''))+'</small></div><button class="quiet attachment-remove" type="button" aria-label="Remove '+esc(a.name)+'">×</button>';
      node.querySelector('.attachment-remove').disabled=busy||blocked();node.querySelector('.attachment-remove').onclick=()=>{queues.set(key(),rows().filter(r=>r!==row));if(thumbnail){URL.revokeObjectURL(thumbnail);thumbs.delete(a.id);}try{save();}catch{}render();updateSuggestions();};
      node.querySelector('.attachment-thumb').onclick=()=>{if(thumbnail||!DMChat.enabled)open(a,thumbnail);else toast('Original preview is available only in this upload session.');};
      list.append(node);
    }
    DMUI.sync();
  }
  async function request(file,id,mode,retry=false){
    const response=await fetch(id==='@itch'?'/api/itch-upload':'/api/upload',{method:'POST',headers:{'X-DumbManager':'1','X-Thread-Id':id,'X-T3-Target':DMT3.target,'X-File-Name':encodeURIComponent(file.name),'X-File-Type':file.type||'application/octet-stream','X-Video-Mode':mode},body:file});
    if(response.status===403&&!retry){await fetch('/');return request(file,id,mode,true);}
    let result;try{result=await response.json();}catch{throw new Error('Upload returned an unexpected response. Your message is kept.');}if(!response.ok)throw new Error(result.error||'Upload failed. Pick the file again.');return result;
  }
  async function add(files){
    if(DMChat.enabled&&!DMChat.target)return toast('Pick a T3 thread before adding files.');
    if(busy||blocked())return toast('Wait for the upload, or retry/dismiss the last message first.');
    const id=key(),mode=$('#video-mode').value;busy=true;render();updateSuggestions();
    try{
      for(const file of files){
        if((queues.get(id)||[]).length>=8){toast('8 files max. Send these first.');break;}
        if(!file.size||file.size>50*1024*1024){toast(file.name+': use a nonempty file up to 50 MiB.');continue;}
        if(['image/png','image/jpeg','image/webp','image/gif'].includes(file.type)&&file.size>10*1024*1024){toast(file.name+': resize images to 10 MiB or less.');continue;}
        if((queues.get(id)||[]).reduce((n,r)=>n+r.attachment.sizeBytes,0)+file.size>80*1024*1024&&!file.type.startsWith('video/')){toast('Keep the whole message under 80 MiB.');break;}
        try{
          const result=await request(file,id,mode),a=result.attachment;
          if((queues.get(id)||[]).reduce((n,r)=>n+r.attachment.sizeBytes,0)+a.sizeBytes>80*1024*1024){toast('Keep the whole message under 80 MiB. Send the current files first.');break;}
          const items=queues.get(id)||[];items.push({attachment:a,note:result.note||''});queues.set(id,items);
          if(result.thumbnail){const bytes=Uint8Array.from(atob(result.thumbnail),c=>c.charCodeAt(0));thumbs.set(a.id,URL.createObjectURL(new Blob([bytes],{type:'image/jpeg'})));}
          else if(a.type==='image'||a.type==='video')thumbs.set(a.id,URL.createObjectURL(file));
          try{save();}catch{toast('File is ready. Browser storage is full; keep this page open until you send.');}
          render();
        }catch(e){toast(file.name+': '+e.message);}
      }
    }finally{busy=false;render();updateSuggestions();}
  }
  function commit(id,attachments){const ids=new Set(attachments.map(a=>a.id));queues.set(id,(queues.get(id)||[]).filter(r=>!ids.has(r.attachment.id)));for(const key of ids)if(thumbs.has(key)){URL.revokeObjectURL(thumbs.get(key));thumbs.delete(key);}try{save();}catch{}render();}
  function restore(id,attachments){if(!Array.isArray(attachments)||!attachments.length)return;const existing=queues.get(id)||[];for(const a of attachments.slice(0,8))if(a&&typeof a.id==='string'&&typeof a.name==='string'&&!existing.some(r=>r.attachment.id===a.id))existing.push({attachment:a,note:id==='@itch'?(a.note||'Saved locally with this itch'):'Unconfirmed send · same attachment IDs retained'});queues.set(id,existing);}
  function resetPreview(){
    previewGeneration++;const dialog=$('#attachment-view'),video=dialog.querySelector('video');video.pause();video.removeAttribute('src');video.load();video.hidden=true;dialog.querySelector('img').removeAttribute('src');dialog.querySelector('img').hidden=true;
    dialog.querySelector('a').hidden=true;dialog.querySelector('a').removeAttribute('href');if(previewURL)URL.revokeObjectURL(previewURL);previewURL='';
    const copy=$('#attachment-copy');copy.hidden=true;copy.disabled=true;copy.textContent='Copy image';
  }
  async function open(a,url){
    resetPreview();const generation=previewGeneration,dialog=$('#attachment-view'),caption=dialog.querySelector('p');caption.innerHTML=DMUI.ascii('load')+' Opening…';if(!dialog.open)dialog.showModal();DMUI.sync();
    try{
      if(!url){
        const blob=await read(a);if(generation!==previewGeneration)return;url=URL.createObjectURL(blob);previewURL=url;
      }
      if(generation!==previewGeneration)return;
      const media=dialog.querySelector(a.type==='video'?'video':'img');media.hidden=false;media.src=url;
      const copy=$('#attachment-copy');copy.hidden=a.type!=='image';copy.disabled=true;
      if(a.type==='image'){
        const ready=()=>{if(generation===previewGeneration)copy.disabled=!navigator.clipboard?.write||!window.ClipboardItem;};
        media.onload=ready;if(media.complete&&media.naturalWidth)ready();
        copy.title=navigator.clipboard?.write&&window.ClipboardItem?'Paste this image into another app.':'Image clipboard unavailable here. Use Save a copy.';
      }
      caption.textContent=a.name+(a.note?' · '+a.note:'');media.onerror=()=>{if(generation===previewGeneration)caption.textContent=a.name+' · Your browser cannot preview this format. Save a copy to open it in another app.';};
      const download=dialog.querySelector('a');download.hidden=false;download.href=url;download.download=a.name;
    }catch(e){if(generation===previewGeneration)caption.textContent=e.message;}
  }
  async function copyImage(){
    const button=$('#attachment-copy'),image=$('#attachment-view img'),generation=previewGeneration;
    if(button.disabled||image.hidden||!image.naturalWidth)return;
    button.disabled=true;button.textContent='Copying…';
    try{
      const canvas=document.createElement('canvas');canvas.width=image.naturalWidth;canvas.height=image.naturalHeight;
      canvas.getContext('2d').drawImage(image,0,0);
      const png=new Promise((resolve,reject)=>canvas.toBlob(blob=>blob?resolve(blob):reject(new Error('Image conversion failed.')),'image/png'));
      // Start the clipboard write inside the click gesture, including on Safari.
      await navigator.clipboard.write([new ClipboardItem({'image/png':png})]);
      if(generation===previewGeneration)toast('Image copied. Paste it anywhere.');
    }catch(e){if(generation===previewGeneration)toast('Couldn’t copy the image. Try again or use Save a copy.');}
    finally{if(generation===previewGeneration){button.disabled=false;button.textContent='Copy image';}}
  }
  async function read(a){
    const request=()=>fetch('/api/itch-media',{method:'POST',headers:{'X-DumbManager':'1','Content-Type':'application/json'},body:JSON.stringify({id:a.id})});
    let response=await request();if(response.status===403){await fetch('/');response=await request();}
    if(!response.ok){const value=await response.json();throw new Error(value.error||'Couldn’t open that file.');}
    return response.blob();
  }
  function evidence(row){return (row.attachments||[]).length?'<section class="itch-evidence"><h3>Receipts <small>'+row.attachments.length+' saved locally</small></h3><div class="evidence-grid">'+row.attachments.map(a=>'<button class="evidence-card secondary" type="button" data-itch-media="'+esc(a.id)+'"><span class="file-art" aria-hidden="true">[ '+(a.type==='video'?'▶':'▧')+' ]</span><span><b>'+esc(a.name)+'</b><small>'+esc(size(a.sizeBytes)+' · '+(a.type==='video'?'Play video':'View image / frameboard'))+'</small></span><span aria-hidden="true">↗</span></button>').join('')+'</div></section>':'';}
  function init(isLocked){
    locked=isLocked;
    try{const saved=JSON.parse(DMT3.read(sessionStorage,'dm-t3-files')||'{}');for(const [id,items]of Object.entries(saved).slice(0,20))if(Array.isArray(items))queues.set(id,items.slice(0,8).filter(r=>r?.attachment?.id&&typeof r.attachment.name==='string'));}catch{}
    try{const items=JSON.parse(localStorage.getItem('dm-itch-files')||'[]');if(Array.isArray(items))restore('@itch',items.map(r=>r.attachment));}catch{}
    $('#video-mode').addEventListener('change',()=>videoModes[DMChat.enabled?'chat':'itch']=$('#video-mode').value);
    $('#attach-pick').onclick=()=>$('#attachment-input').click();$('#attachment-input').onchange=e=>{add([...e.target.files]);e.target.value='';};
    $('#command').addEventListener('paste',e=>{const files=[...(e.clipboardData?.files||[])];if(files.length){e.preventDefault();add(files);}});
    const zone=$('.capture-panel');zone.addEventListener('dragover',e=>{if(e.dataTransfer.types.includes('Files')){e.preventDefault();zone.classList.add('file-hover');}});zone.addEventListener('dragleave',e=>{if(!zone.contains(e.relatedTarget))zone.classList.remove('file-hover');});zone.addEventListener('drop',e=>{zone.classList.remove('file-hover');if(e.dataTransfer.files.length){e.preventDefault();add([...e.dataTransfer.files]);}});
    $('#attachment-close').onclick=()=>$('#attachment-view').close();$('#attachment-view').addEventListener('close',resetPreview);
    $('#attachment-copy').onclick=copyImage;
    $('#detail').addEventListener('click',e=>{const button=e.target.closest('[data-itch-media]');if(!button)return;const attachment=state.itches.flatMap(r=>r.attachments||[]).find(a=>a.id===button.dataset.itchMedia);if(attachment)open(attachment);});
    render();
  }
  return {init,render,add,commit,restore,evidence,read,open,get itchAttachments(){return (queues.get('@itch')||[]).map(r=>r.attachment);},get busy(){return busy;},get attachments(){return rows().map(r=>r.attachment);}};
})();
