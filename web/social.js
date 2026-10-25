/* Completion posts are local drafts. A share handoff never means "published". */
window.DMSocial=(()=>{
  let result=null,draft=null,edits={},preview=null,png=null,imageURL='',generation=0,busy=false,error='',search='',offset=0,editOpen=false;
  let exporting=false,handoffNote='',requestedItch='';
  // Animated card: rendered + cached by DumbAPI (manager.social.gif). One vibe counter per draft.
  let gif=null,gifURL='',gifBusy=false,gifError='',gifRun=0;
  const variants=(()=>{try{const v=JSON.parse(sessionStorage.getItem('dm.social.styles.v1')||'{}');return v&&typeof v==='object'&&!Array.isArray(v)?v:{};}catch{return {};}})();
  function variant(id){const v=variants[id]||{};return {vibe:Number.isInteger(v.vibe)&&v.vibe>=0&&v.vibe<=1000000?v.vibe:0,theme:['flow','smoke'].includes(v.theme)?v.theme:''};}
  function rememberVariant(id,value){
    delete variants[id];variants[id]=value;
    for(const key of Object.keys(variants).slice(0,-50))delete variants[key];
    try{sessionStorage.setItem('dm.social.styles.v1',JSON.stringify(variants));}catch{}
  }
  let pictureOpen=false,maskEdits=null,editorBitmap=null,editorKey='',editorLoading='',editorError='',drag=null;
  const masks=()=>maskEdits??draft?.image?.masks??[];
  const masksChanged=()=>!!draft?.image&&JSON.stringify(masks())!==JSON.stringify(draft.image.masks);
  const pictureBlocked=()=>masksChanged(); // only unapplied privacy masks hold sharing
  function resetPicture(){pictureOpen=false;maskEdits=null;editorBitmap?.close();editorBitmap=null;editorKey='';editorLoading='';editorError='';drag=null;}
  function handoff(message){handoffNote=message;const node=$('#social-handoff');if(node){node.textContent=message;node.hidden=!message;}}
  function within(promise,ms,message){
    let timer;return Promise.race([promise,new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error(message)),ms);})]).finally(()=>clearTimeout(timer));
  }
  function revealCheck(kind){
    const picture=kind==='picture',panel=$(picture?'#social-picture':'#social-edit');
    if(picture)pictureOpen=true;else editOpen=true;
    if(panel){panel.open=true;panel.querySelector('summary').focus({preventScroll:true});requestAnimationFrame(()=>panel.scrollIntoView({block:'start'}));}
  }
  function readyToExport(){
    if(busy||exporting||!draft||!png)return false;
    if(gifBusy){handoff('Animating card… one sec.');return false;} // always hand off the animated card once it exists
    if(pictureBlocked()){
      handoff('Apply your privacy masks first.');revealCheck('picture');return false;
    }
    if(changed()||draft.source_changed){
      handoff('Update preview to include your latest changes.');revealCheck('copy');return false;
    }
    return true;
  }
  function exportState(){return {id:draft.id,version:draft.version,stage:draft.stage,source_version:draft.source_version,digest:draft.image?.digest,caption:draft.caption,filename:preview.filename,composers:{...preview.composers},png:freshGif()?.poster||png,generation,gif:gifCopy()||null};}
  function clipboardItem(snapshot,checked,mode){
    const ready=checked.then(()=>snapshot);
    const formats={};
    // Mixed HTML/text/image items are pasted differently by each editor. Some strip
    // data-URL images or insert the caption twice. Export one unambiguous format.
    if(mode==='text')formats['text/plain']=ready.then(s=>new Blob([s.caption],{type:'text/plain'}));
    else formats['image/png']=ready.then(s=>s.png);
    // Begin writing during the click gesture (Safari); verified blobs resolve later.
    // Catch dependent promises even when construction/permission fails immediately.
    Object.values(formats).forEach(p=>p.catch(()=>{}));
    return new ClipboardItem(formats);
  }
  async function copyExport(mode){
    if(!readyToExport())return;
    const snapshot=exportState(),checked=verify(snapshot);checked.catch(()=>{});
    let writing;
    if(mode==='image'&&snapshot.gif){
      try{
        exporting=true;dirty();handoff('Copying GIF…');
        await within(copyGif(snapshot,checked),20000,'Clipboard did not respond. Try again, or use Save image.');
        if(snapshot.generation===generation)handoff('GIF copied. '+pasteHint('GIF'));
      }catch(e){if(snapshot.generation===generation)handoff(/changed|timed out|did not respond|Review the picture/.test(e.message)?e.message:'Couldn’t copy the GIF. Try again, or use Save image.');}
      finally{exporting=false;dirty();}
      return;
    }
    try{
      if(navigator.clipboard?.write&&window.ClipboardItem)writing=navigator.clipboard.write([clipboardItem(snapshot,checked,mode)]);
      else if(mode==='text'&&navigator.clipboard?.writeText)writing=checked.then(()=>navigator.clipboard.writeText(snapshot.caption));
      else throw new Error('Image clipboard unavailable. Use Share post or Save image.');
      writing.catch(()=>{});exporting=true;dirty();handoff('Copying…');
      await Promise.all([checked,within(writing,5000,'Clipboard did not respond. Try again, or use Save image.')]);
      if(snapshot.generation===generation)handoff(mode==='text'?'Caption copied.':'Picture copied. Paste it into your post. Copy caption separately if needed.');
    }catch(e){if(snapshot.generation===generation)handoff(/unavailable|did not respond|timed out/.test(e.message)?e.message:'Couldn’t copy. Try again, or use Share post / Save image.');}
    finally{exporting=false;dirty();}
  }
  async function compose(site){
    if(!readyToExport())return;
    const snapshot=exportState(),checked=verify(snapshot);checked.catch(()=>{});
    let copying=Promise.resolve(false),tab=null;
    try{
      // A denied clipboard must not prevent the caption-only composer handoff.
      if(snapshot.gif)copying=copyGif(snapshot,checked).then(()=>true,()=>false);
      else try{if(navigator.clipboard?.write&&window.ClipboardItem)copying=navigator.clipboard.write([clipboardItem(snapshot,checked,'image')]).then(()=>true,()=>false);}catch{}
      // Reserve a new tab in the click gesture; navigate only after verification.
      tab=window.open('about:blank','_blank');
      if(tab){tab.opener=null;if(tab.document.body)tab.document.body.textContent='Preparing your post…';}
      exporting=true;dirty();handoff('Preparing your post…');
      await checked;const copied=await within(copying,snapshot.gif?20000:3000,'Clipboard did not respond.').catch(()=>false);
      if(snapshot.generation!==generation)throw new Error('This draft changed. Reopen it before sharing.');
      if(!tab){handoff('Popup blocked. Allow popups, then tap '+(site==='x'?'X':'Bluesky')+' again.');return;}
      if(tab.closed){handoff(copied?'Picture copied. The composer tab was closed.':'Composer tab closed.');return;}
      tab.location.replace(snapshot.composers[site]);
      handoff(copied?'Text opened in '+(site==='x'?'X':'Bluesky')+'. '+pasteHint(snapshot.gif?'GIF':'picture'):'Text opened. Picture not copied; use Copy image or Save image to attach it.');
    }catch(e){try{tab?.close();}catch{}if(snapshot.generation===generation)handoff('Couldn’t open the composer. '+e.message);}
    finally{exporting=false;dirty();}
  }
  function pasteHint(kind='picture'){return matchMedia('(pointer:coarse)').matches?'Touch and hold in the post, then Paste to attach the '+kind+'.':'Press '+(/Mac|iPhone|iPad/.test(navigator.platform)?'⌘V':'Ctrl+V')+' in the post to attach the copied '+kind+'.';}
  function pictureMarkup(){
    const image=draft.image;
    return `<details id="social-picture" class="tool-fold"><summary>${image?'Work picture':'Add work picture'}</summary><div class="social-picture-controls"><input id="social-picture-file" type="file" accept="image/png,image/jpeg,image/webp,image/gif" hidden><button class="secondary" data-social="upload-picture" ${busy?'disabled':''}>Choose image</button><button class="secondary" data-social="capture-picture" ${busy?'disabled':''}>Capture Browse</button>${image?'':'<button class="quiet" data-social="receipt-picture" '+(busy?'disabled':'')+'>Use receipt</button>'}<button class="quiet" data-social="remove-picture" ${busy?'disabled':''}>${image?'Remove':'Text only'}</button></div>${image?`<small>${image.automatic_regions} text areas obscured locally. Drag over anything else you want hidden, then Apply masks.</small><canvas id="social-mask-canvas" aria-label="Privacy editor: drag a box to hide a private area" role="img"></canvas><small id="social-mask-status" role="status">${esc(editorError||'Drag a box to hide an area.')}</small><div class="social-picture-controls"><button class="secondary" data-social="undo-mask" ${busy||!masks().length?'disabled':''}>Undo mask</button><button class="secondary" data-social="apply-masks" ${busy||!masksChanged()?'disabled':''}>Apply masks</button></div>`:'<small>A screenshot of the finished work. Originals stay local; detected text is obscured in a separate copy.</small>'}</details>`;
  }
  function paintMasks(){
    const canvas=$('#social-mask-canvas');if(!canvas||!editorBitmap||editorKey!==draft?.image?.source.id)return;
    const image=draft.image,crop=image.crop,ctx=canvas.getContext('2d');
    canvas.width=Math.min(960,image.width);canvas.height=Math.max(1,Math.round(canvas.width*image.height/image.width));
    canvas.style.width=Math.min(960,420*image.width/image.height)+'px';
    ctx.drawImage(editorBitmap,editorBitmap.width*crop.x,editorBitmap.height*crop.y,editorBitmap.width*crop.width,editorBitmap.height*crop.height,0,0,canvas.width,canvas.height);
    ctx.fillStyle='#17131e';
    for(const r of [...image.boxes,...masks(),...(drag?[drag.rectangle]:[])])ctx.fillRect(r.x*canvas.width,r.y*canvas.height,r.width*canvas.width,r.height*canvas.height);
  }
  async function mountPicture(){
    const image=draft?.image,canvas=$('#social-mask-canvas');if(!image||!canvas||!pictureOpen)return;
    if(editorKey===image.source.id&&editorBitmap){paintMasks();return;}
    if(editorLoading===image.source.id)return;
    const key=image.source.id;editorLoading=key;editorError='';
    try{
      const blob=await DMUploads.read(image.source),bitmap=await createImageBitmap(blob);
      if(draft?.image?.source.id!==key){bitmap.close();return;}
      editorBitmap?.close();editorBitmap=bitmap;editorKey=key;paintMasks();
    }catch(e){if(draft?.image?.source.id===key){editorError=e.message;const status=$('#social-mask-status');if(status)status.textContent=e.message;}}
    finally{if(editorLoading===key)editorLoading='';}
  }
  async function uploadPicture(file,retry=false){
    if(!file||busy)return;
    if(!file.type.startsWith('image/')||!file.size||file.size>10*1024*1024)throw new Error('Choose an image up to 10 MiB.');
    const current=++generation,target=draft.id;edits=fields();busy=true;error='';render();
    try{
      const send=()=>fetch('/api/itch-upload',{method:'POST',headers:{'X-DumbManager':'1','X-File-Name':encodeURIComponent(file.name),'X-File-Type':file.type,'X-Video-Mode':'original'},body:file});
      let response=await send();if(response.status===403&&!retry){await fetch('/');response=await send();}
      const answer=await response.json();if(!response.ok)throw new Error(answer.error||'Image upload failed.');
      if(current!==generation||draft?.id!==target)return;
      await changePicture({attachment_id:answer.attachment.id},true);
    }catch(e){if(current===generation)error=e.message;}
    finally{if(current===generation){busy=false;render();}}
  }
  async function changePicture(args,alreadyBusy=false){
    if(!draft||busy&&!alreadyBusy)return;
    const current=++generation;edits=fields();busy=true;error='';pictureOpen=true;render();
    try{
      const row=await call('manager.social.image',{id:draft.id,expected_version:draft.version,...args});
      if(current!==generation)return;draft=row;maskEdits=null;await prepare(current);if(current===generation)animate();
    }catch(e){if(current===generation)error=e.message;}
    finally{if(current===generation){busy=false;render();}}
  }
  const labels={accepted:'Accepted W',review:'Ready to test',changed:'Work in progress'};
  const eligible=r=>['ready','resolved'].includes(r.state);
  let tracking=null,trackingError='',handlesLoading=false,scanBusy=false,scanNote='',handleTimer=null,trackSignature='',postingBusy=false,postError='',lastPostCheck=0,linkText='',postReviewKey='',postReviewOpen=false;
  const platformName=s=>({x:'X',youtube:'YouTube',tiktok:'TikTok',bluesky:'Bluesky'})[s]||s||'Social';
  const basisName=s=>({exact_caption:'Full caption match',formatted_caption:'Caption matches after formatting',changelog_body:'Headline + changes match',user_linked_capture:'Linked by you',ambiguous_caption:'Caption shared by multiple itches',headline_only:'Title only; review the details'})[s]||'Saved post evidence';
  function postDate(value,time=false){
    if(!value)return '';
    const day=typeof value==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(value),d=new Date(typeof value==='number'?value*1000:value);
    if(!Number.isFinite(d.getTime()))return '';
    return d.toLocaleString(undefined,{month:'short',day:'numeric',...(day?{timeZone:'UTC'}:time?{hour:'numeric',minute:'2-digit'}:{}),...(d.getUTCFullYear()!==new Date().getFullYear()?{year:'numeric'}:{})});
  }
  function postingInfo(p){
    return p.posts?.length?{label:'Post link saved',note:'Added by you; availability has not been checked.',kind:'linked',hint:'A saved URL is not verified proof of publication.'}:{label:'No post link',note:'Add your own URL after posting.',kind:'unconfirmed',hint:'Sharing and itch acceptance are separate.'};
  }
  function badge(r,interactive=false){
    const p=r.posting||{},posted=p.state==='posted';
    if(!posted&&!eligible(r))return '';
    const info=postingInfo(p);
    const html=`<span class="posting-status"><span class="posting-badge ${info.kind}" title="${esc(info.hint)}">${esc(info.label)}</span><span class="posting-note">${esc(info.note)}</span></span>`;
    return interactive?`<button class="quiet post-status-link" data-post-itch="${esc(r.id)}" aria-label="${esc(info.label+'. '+info.note+'. View posting evidence')}">${html} ↗</button>`:html;
  }
  function applyPosting(items){
    for(const p of items){const r=state.itches.find(r=>r.id===p.itch_id);if(r)r.posting=p;const listed=result?.items?.find(r=>r.id===p.itch_id);if(listed)listed.posting=p;if(draft?.itch_id===p.itch_id)draft.posting=p;}
    window.render();
  }
  async function checkPosts(force=true){
    if(postingBusy||!force&&Date.now()-lastPostCheck<60000)return;
    postingBusy=true;lastPostCheck=Date.now();postError='';render();
    try{const answer=await call('manager.social.check');applyPosting(answer.items);}
    catch(e){postError=e.message;}
    finally{postingBusy=false;render();}
  }








  function postingMarkup(){
    const p=draft.posting||{};
    return `<section class="social-posting" aria-label="Saved post links">${badge({state:'ready',posting:p})}${postError?`<p role="alert">${esc(postError)}</p>`:''}<p>Save your own post URL after sharing. Links are kept locally and are not checked against an account.</p>${(p.posts||[]).map(s=>`<a class="text-link" href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">Open saved post ↗</a>`).join(' ')}${p.posts?.length?'<button class="quiet" data-social="unlink">Unlink</button>':''}<form id="social-post-link" class="tool-search"><label class="sr" for="social-post-url">Your post URL</label><input id="social-post-url" type="url" placeholder="Paste your post URL…" value="${esc(linkText)}"><button class="secondary" ${postingBusy?'disabled':''}>Save link</button></form></section>`;
  }
  async function linkPost(url){
    if(postingBusy||!draft)return;const itch_id=draft.itch_id;postingBusy=true;postError='';render();
    try{const answer=await call('manager.social.link',{itch_id,url});linkText='';applyPosting(answer.items);}
    catch(e){postError=e.message;}
    finally{postingBusy=false;render();}
  }
  function clearImage(){if(imageURL)URL.revokeObjectURL(imageURL);imageURL='';png=null;preview=null;clearGif();}
  function clearGif(){if(gifURL)URL.revokeObjectURL(gifURL);if(gif?.posterURL)URL.revokeObjectURL(gif.posterURL);gifURL='';gif=null;gifError='';gifBusy=false;gifRun++;}
  const reducedMotion=matchMedia('(prefers-reduced-motion: reduce)');let motionPaused=false,playOverride=false;
  const previewPaused=()=>document.hidden||motionPaused||(!playOverride&&(reducedMotion.matches||document.body.classList.contains('no-motion')));
  const cardSource=()=>freshGif()?(previewPaused()?gif.posterURL||imageURL:gifURL):imageURL;
  function syncMotion(){const image=$('#social-card');if(image)image.src=cardSource();const button=$('[data-social="motion"]');if(button){button.textContent=previewPaused()?'Play motion':'Pause motion';button.setAttribute('aria-pressed',String(!previewPaused()));}}
  reducedMotion.addEventListener('change',()=>{playOverride=false;syncMotion();});
  document.addEventListener('visibilitychange',syncMotion);
  let noMotion=document.body.classList.contains('no-motion');
  new MutationObserver(()=>{const next=document.body.classList.contains('no-motion');if(next!==noMotion){noMotion=next;playOverride=false;syncMotion();}}).observe(document.body,{attributes:true,attributeFilter:['class']});
  async function stillFrame(blob){
    let bitmap;
    try{
      bitmap=await createImageBitmap(blob);const canvas=document.createElement('canvas');canvas.width=2400;canvas.height=1350;
      canvas.getContext('2d').drawImage(bitmap,0,0,canvas.width,canvas.height);
      return await new Promise(resolve=>canvas.toBlob(resolve,'image/png'));
    }catch{return null;}finally{bitmap?.close();}
  }
  const freshGif=()=>gif&&draft&&gif.meta.draft_id===draft.id&&gif.meta.version===draft.version&&(gif.meta.digest??null)===(draft.image?.digest??null)&&gif.meta.vibe===variant(draft.id).vibe&&(gif.meta.requested_theme||'')===variant(draft.id).theme?gif:null;
  const desktopClipboard=()=>['127.0.0.1','localhost'].includes(location.hostname)&&!matchMedia('(pointer:coarse)').matches;
  const gifCopy=()=>desktopClipboard()&&freshGif();
  function copyGif(snapshot,checked){
    const live=snapshot.gif;
    return checked.then(()=>call('manager.social.gif_copy',{id:snapshot.id,expected_version:snapshot.version,vibe:live.meta.vibe,theme:live.meta.requested_theme||''}));
  }
  const EVENT_NAMES={greg:'Greg spotted',lightning:'lightning',flicker:'flicker'};
  async function animate(){
    if(!draft)return;
    const run=++gifRun,id=draft.id,version=draft.version,{vibe,theme}=variant(id);
    gifBusy=true;gifError='';render();
    try{
      const r=await call('manager.social.gif',{id,vibe,theme});
      if(run!==gifRun||draft?.id!==id||draft.version!==version)return;
      const raw=atob(r.gif),bytes=new Uint8Array(raw.length);for(let i=0;i<raw.length;i++)bytes[i]=raw.charCodeAt(i);
      const blob=new Blob([bytes],{type:'image/gif'}),poster=await stillFrame(blob);
      if(run!==gifRun||draft?.id!==id||draft.version!==version)return;
      delete r.gif;if(gifURL)URL.revokeObjectURL(gifURL);if(gif?.posterURL)URL.revokeObjectURL(gif.posterURL);
      gif={blob,meta:r,poster,posterURL:poster?URL.createObjectURL(poster):''};gifURL=URL.createObjectURL(blob);
    }catch(e){if(run===gifRun)gifError=e.message;}
    finally{if(run===gifRun){gifBusy=false;render();}}
  }
  function vibeMarkup(){
    const live=freshGif(),events=(live?.meta.events||[]).map(e=>EVENT_NAMES[e]||e);
    const note=gifBusy?'Animating card…':live?`${live.meta.theme} · ${live.meta.seconds}s loop${events.length?' · '+events.join(' · '):''}`:gifError?'Still card only: '+gifError:'';
    const disabled=gifBusy||busy||exporting||!png,style=variant(draft.id).theme;
    return `<div class="social-vibe"><small id="social-vibe-note" role="status">${esc(note)}</small><div class="social-style-controls"><label for="social-style">Card style</label><select id="social-style" ${disabled?'disabled':''}><option value="" ${!style?'selected':''}>Surprise me</option><option value="flow" ${style==='flow'?'selected':''}>Water flow</option><option value="smoke" ${style==='smoke'?'selected':''}>Dithered smoke</option></select>${live?`<button class="quiet" data-social="motion" aria-pressed="${!previewPaused()}">${previewPaused()?'Play motion':'Pause motion'}</button>`:''}<button class="quiet" data-social="reroll" ${disabled?'disabled':''}>New vibe &#127922;</button></div></div>`;
  }
  function render(){if(view==='tools'&&toolTab==='social')renderTools();}
  async function enter(query='',page=0){
    requestedItch='';
    ++generation;handoffNote='';draft=null;edits={};editOpen=false;resetPicture();clearImage();search=query;offset=page;error='';result=null;
    rememberPage();
    await load();checkPosts(false);
  }
  async function load(){
    const current=++generation;busy=true;error='';render();
    try{const answer=await call('manager.social.list',{query:search,limit:6,offset});if(current===generation)result=answer;}
    catch(e){if(current===generation)error=e.message;}
    finally{if(current===generation){busy=false;render();}}
  }
  async function raster(svg){
    const url=URL.createObjectURL(new Blob([svg],{type:'image/svg+xml'}));
    try{
      const img=new Image();img.src=url;await img.decode();
      const canvas=document.createElement('canvas');canvas.width=2400;canvas.height=1260;
      canvas.getContext('2d').drawImage(img,0,0,canvas.width,canvas.height);
      return await new Promise((resolve,reject)=>canvas.toBlob(b=>b?resolve(b):reject(new Error('Card export failed. Your draft is saved.')),'image/png'));
    }finally{URL.revokeObjectURL(url);}
  }
  async function prepare(current){
    const before={headline:draft.headline,summary:draft.summary,caption:draft.caption};
    const next=await call('manager.social.preview',{id:draft.id});
    const blob=await raster(next.svg);
    if(current!==generation)return;
    // Background redraws can capture the old defaults while automatic copy is
    // being prepared. Discard those defaults, while retaining actual user edits.
    if(Object.keys(edits).every(k=>edits[k]===before[k]))edits={};
    clearImage();preview=next;draft=next.draft;png=blob;imageURL=URL.createObjectURL(blob);DMWebhook.open(draft);
  }
  async function open(id){
    requestedItch=id;
    linkText='';postError='';handoffNote='';
    const current=++generation;busy=true;error='';draft=null;edits={};editOpen=false;resetPicture();clearImage();render();rememberPage();
    try{const row=await call('manager.social.draft',{itch_id:id});if(current!==generation)return;draft=row;await prepare(current);if(current===generation)animate();}
    catch(e){if(current===generation)error=e.message;}
    finally{if(current===generation){busy=false;render();rememberPage();checkPosts(false);}}
  }
  async function show(query='',id=''){
    toolTab='social';setView('tools');$('#command').value='';$('#suggestions').hidden=true;
    if(id)await open(id);else await enter(query);
  }
  function fields(){
    const data={...draft,...edits};
    return {headline:$('#social-headline')?.value??data.headline,summary:$('#social-summary')?.value??data.summary,caption:$('#social-caption')?.value??data.caption};
  }
  function changed(){
    if(!draft)return false;const data=fields();return Object.keys(data).some(k=>data[k]!==draft[k]);
  }
  function dirty(){
    if(!draft||!$('#social-dirty'))return;
    const dirty=changed()||draft.source_changed||pictureBlocked();
    document.querySelectorAll('[data-social="download"],[data-social="share"],[data-social="copy-post"],[data-social="copy-image"]').forEach(b=>b.disabled=dirty||busy||exporting||gifBusy||!png);
    document.querySelectorAll('[data-social="download-still"],[data-social="copy"]').forEach(b=>b.disabled=dirty||busy||exporting||!png);
    document.querySelectorAll('[data-social-link]').forEach(b=>b.disabled=busy||exporting||!png);
    DMWebhook.sync(dirty||busy||exporting||gifBusy||!png);
    document.querySelectorAll('#social-style,[data-social="reroll"]').forEach(b=>b.disabled=busy||exporting||gifBusy||!png);
    $('#social-dirty').textContent=masksChanged()?'Apply your privacy masks first.':dirty?'Check the copy, then update preview.':'Saved locally. Finish posting in your social app.';
    const unlock=$('#social-unlock');if(unlock){unlock.hidden=!dirty;unlock.disabled=busy||exporting||!png;unlock.textContent=pictureBlocked()?'Apply masks':'Review copy';}
  }
  async function save(){
    if(busy||!draft)return;
    const current=++generation,data=fields();busy=true;error='';
    // Capture fields before the loading redraw; retain them after a failed save.
    edits=data;render();
    try{
      const row=await call('manager.social.save',{id:draft.id,expected_version:draft.version,...data});
      if(current!==generation)return;draft=row;edits={};await prepare(current);if(current===generation)animate();
    }catch(e){if(current===generation){error=e.message;clearImage();}}
    finally{if(current===generation){busy=false;render();}}
  }
  function markup(){
    if(!draft)return `<div class="tool-launch"><div class="tool-intro">${DMUI.ascii('spark')}<h3>Share a W</h3></div><div class="social-top-actions"><button class="quiet" data-social="check-posts" ${postingBusy?'disabled':''}>${postingBusy?'Checking…':'Refresh links ↻'}</button><button class="quiet" data-social="handles">Scan handles ↗</button></div></div>${postError?`<small role="alert">${esc(postError)}</small>`:''}<form id="social-search" class="tool-search"><label class="sr" for="social-query">Find a completion</label><input id="social-query" maxlength="500" placeholder="Find a completion…" value="${esc(search)}"><button class="secondary">Find</button></form>${error?`<p role="alert">${esc(error)}</p>`:''}${busy?'<p role="status">Loading…</p>':(result?.items||[]).map(r=>`<button class="content-row" data-social-itch="${esc(r.id)}"><b>${esc(r.title)}</b><small>${esc(r.project)} · ${labels[r.stage]}</small>${badge({state:'ready',posting:r.posting})}</button>`).join('')||'<p>No completions yet. Accepted W’s and itches ready to test appear here.</p>'}${result?.total>6?`<nav class="result-pages" aria-label="Completions"><button class="secondary" data-social-page="${offset-6}" ${offset===0?'disabled':''}>← Back</button><span>${offset+1}–${Math.min(offset+6,result.total)} / ${result.total}</span><button class="secondary" data-social-page="${offset+6}" ${result.next_offset===null?'disabled':''}>More →</button></nav>`:''}`;
    const data={...draft,...edits};
    return `<div class="tool-launch"><button class="text-link" data-social="back">← Completions</button><small>${labels[draft.stage]} · local draft</small></div>${error?`<p role="alert">${esc(error)}</p>`:''}${draft.source_changed?'<p class="social-note">The itch changed since this draft. Check your copy before sharing.</p>':''}${postingMarkup()}<div class="social-editor" data-social-draft="${esc(draft.id)}" data-social-version="${draft.version}"><div class="social-copy"><p class="social-caption-preview">${esc(data.caption)}</p><details id="social-edit" class="tool-fold"><summary>Edit post</summary><div class="social-fields"><label for="social-headline">Title</label><input id="social-headline" maxlength="120" value="${esc(data.headline)}" ${busy?'disabled':''}><label for="social-summary">Changelog</label><textarea id="social-summary" maxlength="600" rows="3" ${busy?'disabled':''}>${esc(data.summary)}</textarea><label for="social-caption">Post caption</label><textarea id="social-caption" maxlength="2000" rows="5" ${busy?'disabled':''}>${esc(data.caption)}</textarea><button class="secondary" data-social="save" ${busy?'disabled':''}>${busy?'Making preview…':'Update preview'}</button></div></details></div><div class="social-visual">${imageURL?`<img id="social-card" src="${cardSource()}" width="1200" height="${freshGif()?675:630}" alt="Share card: ${esc(data.headline)} — ${labels[draft.stage]}">`:'<p role="status">Preview unavailable. Update preview to retry.</p>'}${imageURL?vibeMarkup():''}${pictureMarkup()}<div class="social-export-check"><small id="social-dirty">Saved locally. Finish posting in your social app.</small><button id="social-unlock" class="secondary" data-social="unlock" hidden>Review picture</button></div><div class="social-actions social-composers" aria-label="Post composers"><button class="primary" data-social="share" ${!png||busy?'disabled':''}>Share post &#8599;</button><button class="secondary" data-social="compose-x" data-social-link="x" ${!png||busy?'disabled':''}>X &#8599;</button><button class="secondary" data-social="compose-bluesky" data-social-link="bluesky" ${!png||busy?'disabled':''}>Bluesky &#8599;</button></div><small class="social-composer-hint">X and Bluesky fill the text only. ${pasteHint(gifCopy()?'GIF':'picture')} ${gifCopy()?'Copy, Share and Save all give the looping GIF.':freshGif()?'Share post and Save image give the looping GIF; Copy image copies a still on this device.':'Share post and Save image give the looping GIF once it’s ready.'}</small><div class="social-actions social-copy-actions" aria-label="Copy or save post"><button class="secondary" data-social="copy-image" ${!png||busy?'disabled':''}>${gifCopy()?'Copy GIF':'Copy image'}</button><button class="quiet" data-social="copy" ${!png||busy?'disabled':''}>Copy caption</button><button class="quiet" data-social="download" ${!png||busy?'disabled':''}>Save image &#8595;</button><button class="quiet" data-social="download-still" ${!png||busy?'disabled':''}>Save still</button></div>${DMWebhook.cardMarkup(draft,freshGif()?.meta,busy||exporting||gifBusy||changed()||draft.source_changed||pictureBlocked())}<p id="social-handoff" class="social-handoff" role="status" ${handoffNote?'':'hidden'}>${esc(handoffNote)}</p></div></div>`;
  }
  function download(still=false){
    const live=freshGif(),a=document.createElement('a');
    a.href=live?(still?live.posterURL||imageURL:gifURL):imageURL;a.download=live&&!still?live.meta.filename:preview.filename;a.click();
  }
  async function act(name){
    if(name==='motion'){const paused=previewPaused();motionPaused=!paused;playOverride=paused;syncMotion();return;}
    if(name==='check-posts')return checkPosts();
    if(name==='unlink'){if(postingBusy)return;postingBusy=true;try{applyPosting([await call('manager.social.unlink',{itch_id:draft.itch_id})]);}finally{postingBusy=false;render();}return;}
    if(name==='back'){if(changed()){await save();if(error)return;}return enter(search);}
    if(name==='save')return save();
    if(name==='unlock'){if(!busy&&!exporting)readyToExport();return;}
    if(name==='upload-picture')return $('#social-picture-file').click();
    if(name==='capture-picture')return changePicture({source:'browser'});
    if(name==='receipt-picture')return changePicture({source:'receipt'});
    if(name==='remove-picture')return changePicture({source:'none'});
    if(name==='apply-masks')return changePicture({attachment_id:draft.image.source.id,crop:JSON.stringify(draft.image.crop),masks:JSON.stringify(masks())});
    if(name==='undo-mask'){if(busy)return;edits=fields();maskEdits=masks().slice(0,-1);render();return;}
    if(name==='compose-x'||name==='compose-bluesky')return compose(name.slice(8));
    if(name==='copy-post')return copyExport('image');
    if(name==='copy-image')return copyExport('image');
    if(name==='copy')return copyExport('text');
    if(name==='reroll'){if(!draft||gifBusy||busy||exporting)return;const v=variant(draft.id);rememberVariant(draft.id,{...v,vibe:(v.vibe+1)%1000001});return animate();}
    if(!readyToExport())return;
    // Recheck the source before export; do not call an external publishing API.
    if(name==='download'){await verify();return download();}
    if(name==='download-still'){await verify();return download(true);}
    if(name==='share'){
      await verify();
      const live=freshGif(),still=new File([live?.poster||png],preview.filename,{type:'image/png'});
      let file=live?new File([live.blob],live.meta.filename,{type:'image/gif'}):still;
      if(file!==still&&!navigator.canShare?.({files:[file]}))file=still;
      if(!navigator.canShare?.({files:[file]})||!navigator.share){download();toast('Card saved. Copy the caption or open a web composer.');return;}
      try{await navigator.share({text:draft.caption,files:[file]});}
      catch(e){if(e.name!=='AbortError')toast('Share unavailable. Save the image and copy the caption.');}
    }
  }
  async function verify(snapshot=exportState()){
    const next=await within(call('manager.social.preview',{id:snapshot.id}),15000,'Preview check timed out. Your draft is kept; try again.');
    if(snapshot.generation!==generation||draft?.id!==snapshot.id||changed()||next.draft.stage!==snapshot.stage||next.draft.source_version!==snapshot.source_version||next.draft.version!==snapshot.version||next.draft.source_changed||!next.export_ready||next.draft.image?.digest!==snapshot.digest){
      throw new Error('The itch or draft changed. Reopen this draft and check the copy.');
    }
  }
  // Save edits in memory before ordinary app refresh redraws; server save is explicit.
  function capture(){const review=$('#tool-results .post-review');if(review)postReviewOpen=review.open;if(draft&&document.querySelector('[data-social-draft]')?.dataset.socialDraft===draft.id&&document.querySelector('[data-social-draft]').dataset.socialVersion===String(draft.version)){edits=fields();editOpen=$('#social-edit').open;pictureOpen=$('#social-picture')?.open??pictureOpen;}}
  function mounted(){if($('#social-edit'))$('#social-edit').open=editOpen;if($('#social-picture'))$('#social-picture').open=pictureOpen;const review=$('#tool-results .post-review');if(review)review.open=postReviewOpen;dirty();mountPicture();}
  document.addEventListener('change',e=>{
    if(e.target.id!=='social-style'||!draft||gifBusy||busy||exporting)return;
    rememberVariant(draft.id,{...variant(draft.id),theme:['flow','smoke'].includes(e.target.value)?e.target.value:''});
    animate();
  });
  document.addEventListener('toggle',e=>{if(e.target.id==='social-edit')editOpen=e.target.open;if(e.target.matches('#tool-results .post-review'))postReviewOpen=e.target.open;if(e.target.id==='social-picture'){pictureOpen=e.target.open;mountPicture();}},true);
  document.addEventListener('input',e=>{if(e.target.id==='social-post-url')linkText=e.target.value;if(e.target.matches('#social-headline,#social-summary,#social-caption'))dirty();});

  function point(e){const r=e.target.getBoundingClientRect();return {x:Math.max(0,Math.min(1,(e.clientX-r.left)/r.width)),y:Math.max(0,Math.min(1,(e.clientY-r.top)/r.height))};}
  document.addEventListener('change',e=>{if(e.target.id==='social-picture-file')uploadPicture(e.target.files[0]).catch(e=>toast(e.message));});
  document.addEventListener('pointerdown',e=>{
    if(e.target.id!=='social-mask-canvas'||busy||!editorBitmap||masks().length>=32)return;
    e.preventDefault();const start=point(e);drag={pointer:e.pointerId,start,rectangle:{...start,width:0,height:0}};e.target.setPointerCapture(e.pointerId);paintMasks();
  });
  document.addEventListener('pointermove',e=>{
    if(e.target.id!=='social-mask-canvas'||drag?.pointer!==e.pointerId)return;
    const end=point(e),start=drag.start;drag.rectangle={x:Math.min(start.x,end.x),y:Math.min(start.y,end.y),width:Math.abs(start.x-end.x),height:Math.abs(start.y-end.y)};paintMasks();
  });
  document.addEventListener('pointerup',e=>{
    if(e.target.id!=='social-mask-canvas'||drag?.pointer!==e.pointerId)return;
    const r=drag.rectangle;drag=null;
    if(r.width>=.001&&r.height>=.001){edits=fields();maskEdits=[...masks(),r];render();}else paintMasks();
  });
  document.addEventListener('pointercancel',()=>{drag=null;paintMasks();});
  document.addEventListener('submit',e=>{if(e.target.id==='social-post-link'){e.preventDefault();linkPost($('#social-post-url').value.trim());return;}if(e.target.id==='social-search'){e.preventDefault();search=$('#social-query').value;offset=0;load();}});
  document.addEventListener('click',e=>{
    const post=e.target.closest('[data-post-itch]');if(post){$('#itch-view').close();show('',post.dataset.postItch);return;}
    const linked=e.target.closest('[data-post-link]');if(linked&&!linked.disabled){linkPost(linked.dataset.postLink);return;}
    const b=e.target.closest('[data-social],[data-social-itch],[data-social-page]');if(!b||b.disabled)return;
    if(b.dataset.socialItch)open(b.dataset.socialItch);
    else if(b.dataset.socialPage!==undefined){offset=Math.max(0,Number(b.dataset.socialPage));load();}
    else act(b.dataset.social).catch(e=>toast(e.message));
  });
  function page(){return {itch:draft?.itch_id||requestedItch,search,offset,editOpen:$('#social-edit')?.open??editOpen,pictureOpen:$('#social-picture')?.open??pictureOpen};}
  async function restorePage(saved){
    const query=typeof saved?.search==='string'?saved.search.slice(0,500):'';
    const index=Number.isInteger(saved?.offset)?Math.max(0,Math.min(saved.offset,100000)):0;
    if(typeof saved?.itch==='string'&&state.itches.some(r=>r.id===saved.itch&&eligible(r))){await open(saved.itch);editOpen=!!saved.editOpen;pictureOpen=!!saved.pictureOpen;mounted();}
    else await enter(query,index);
  }
  return {markup,enter,show,open,capture,eligible,mounted,badge,checkPosts,page,restorePage,resume:()=>draft||result?render():enter()};
})();
