'use strict';
window.DMPreviews=(()=>{
  let thread='',refs=[],generation=0;
  const cards=new Map();
  function localURL(raw){
    try{const u=new URL(raw);if(u.protocol!=='http:'||!['127.0.0.1','localhost'].includes(u.hostname)||u.username||u.password||!u.port||Number(u.port)<1024||Number(u.port)>65535||u.port===location.port||[3773,8781].includes(Number(u.port)))return null;return u.href;}catch{return null;}
  }
  function theme(){const s=getComputedStyle(document.body),v=n=>s.getPropertyValue(n).trim();return {appearance:document.body.classList.contains('light')?'light':'dark',variables:{'--background':v('--bg'),'--foreground':v('--text'),'--card':v('--surface'),'--card-foreground':v('--text'),'--secondary':v('--surface2'),'--secondary-foreground':v('--text'),'--muted':v('--surface2'),'--muted-foreground':v('--muted'),'--border':v('--border'),'--input':v('--border'),'--ring':v('--amber'),'--primary':v('--amber'),'--primary-foreground':v('--ink'),'--accent':v('--amber'),'--accent-foreground':v('--ink'),'--accent-surface':v('--surface2'),'--accent-surface-foreground':v('--amber'),'--code-background':v('--surface2'),'--code-foreground':v('--text'),'--radius':'8px','--font-sans':'system-ui, sans-serif','--font-mono':'Consolas, monospace'}};}
  function close(card){card.generation=(card.generation||0)+1;card.box.replaceChildren();card.box.hidden=true;card.button.textContent='Show ↗';card.button.setAttribute('aria-expanded','false');card.open=false;}
  function applyTheme(iframe){const current=theme();iframe.style.colorScheme=current.appearance;iframe.contentWindow?.postMessage({jsonrpc:'2.0',method:'ui/notifications/host-context-changed',params:{theme:current.appearance,styles:{variables:current.variables}}},'*');}
  function frame(card,src,kind){
    card.box.innerHTML='<div class="preview-toolbar"><span class="preview-state">'+DMUI.ascii('load')+' Loading '+(kind==='design'?'visual':'local build')+'…</span><div class="preview-sizes" aria-label="Preview width"><button type="button" aria-pressed="true">Fit</button><button type="button" aria-pressed="false">Phone</button></div><button type="button" class="quiet" data-reload>Reload</button>'+(kind==='build'?'<a class="text-link" target="_blank" rel="noopener noreferrer" href="'+esc(src)+'">Open ↗</a>':'')+'</div><div class="preview-viewport"><iframe title="'+esc(card.title)+'" referrerpolicy="no-referrer" sandbox="allow-scripts'+(kind==='build'?' allow-same-origin allow-forms':'')+'"></iframe></div><p class="preview-note">'+(kind==='build'?'Existing local app · if embedding is blocked, use Open ↗. Loading a frame does not confirm the build is healthy.':'Published T3 visual · design concepts and screenshot demos may contain sample data.')+'</p>';
    const iframe=card.box.querySelector('iframe');iframe.height=String(card.height||560);
    if(kind==='design')iframe.style.colorScheme=theme().appearance;
    iframe.onload=()=>{if(kind==='design')applyTheme(iframe);const status=card.box.querySelector('.preview-state');if(status)status.innerHTML=DMUI.ascii('orbit')+' '+(kind==='build'?'Local build frame':'Published visual');};
    iframe.src=src;
    card.box.querySelector('[data-reload]').onclick=()=>kind==='design'?load(card):frame(card,src,kind);
    const sizes=card.box.querySelectorAll('.preview-sizes button');sizes.forEach((b,i)=>b.onclick=()=>{sizes.forEach(x=>x.setAttribute('aria-pressed',String(x===b)));card.box.querySelector('.preview-viewport').classList.toggle('phone',i===1);});
  }
  async function load(card){
    const run=++card.generation,scope=generation;card.open=true;card.button.textContent='Hide ↑';card.button.setAttribute('aria-expanded','true');card.box.hidden=false;
    card.box.innerHTML='<div class="preview-loading" role="status">'+DMUI.ascii('load')+' Pulling the visual from T3…</div>';
    try{const result=await post('/api/preview',{thread_id:thread,attachment_id:card.id,t3_target:window.DMT3?.target});if(run!==card.generation||scope!==generation||!card.open)return;frame(card,result.url+'#t3-theme='+encodeURIComponent(JSON.stringify(theme())),'design');}
    catch(e){if(run!==card.generation||scope!==generation)return;card.box.innerHTML='<p class="preview-note" role="status">'+esc(e.message)+'</p><button type="button" class="secondary">Try again</button>';card.box.querySelector('button').onclick=()=>load(card);}
  }
  function sync(id,previews,messages){
    const root=$('#chat-previews');if(!root)return;
    if(thread!==id){generation++;thread=id;cards.clear();root.replaceChildren();$('#build-frame').replaceChildren();$('#build-frame').hidden=true;$('#build-url').value='';$('#build-status').textContent='Paste the address of an app that’s already running.';}
    refs=previews||[];
    const wanted=new Set(refs.map(p=>p.id));for(const [key,card]of cards)if(!wanted.has(key)){close(card);card.node.remove();cards.delete(key);}
    for(const p of refs){
      if(cards.has(p.id))continue;
      const node=document.createElement('article');node.className='preview-card';
      node.innerHTML='<div class="preview-card-head"><span class="ascii-token" data-ascii="deck" aria-hidden="true">[ ░ ]</span><div><span class="eyebrow">T3 VISUAL</span><h3>'+esc(p.title)+'</h3>'+DMRich.time(p.at)+'</div><button class="secondary" type="button" aria-expanded="false">Show ↗</button></div><div class="preview-content" hidden></div>';
      const card={...p,node,box:node.querySelector('.preview-content'),button:node.querySelector('button'),generation:0,open:false};card.button.onclick=()=>card.open?close(card):load(card);cards.set(p.id,card);root.append(node);
    }
    $('#visual-count').textContent=refs.length?refs.length+' published':'No published visuals yet';
    const urls=[...new Set((messages||[]).flatMap(m=>(m.text.match(/http:\/\/(?:127\.0\.0\.1|localhost|\[::1\]):\d+[^\s<>"'`]*/g)||[]).map(s=>localURL(s.replace(/[.,;!?)\]]+$/,''))).filter(Boolean)))].slice(0,4);
    const choices=$('#build-suggestions');const key=urls.join('\n');if(choices.dataset.urls!==key){choices.dataset.urls=key;choices.replaceChildren();for(const url of urls){const b=document.createElement('button');b.type='button';b.className='chip';b.textContent=url;b.onclick=()=>{$('#build-url').value=url;$('#build-url').focus();};choices.append(b);}}
  }
  function pause(){generation++;for(const card of cards.values())close(card);$('#build-frame').replaceChildren();$('#build-frame').hidden=true;}
  function init(){
    $('#build-show').onclick=()=>{const url=localURL($('#build-url').value.trim());if(!url){$('#build-status').textContent='Use a local app URL such as http://127.0.0.1:5173. Manager, T3 and DumbAPI control ports cannot be embedded.';return;}
      const box=$('#build-frame');box.hidden=false;$('#build-status').textContent='Previewing '+url;frame({box,title:'Local build · '+url,height:560},url,'build');};
    $('#build-url').onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();$('#build-show').click();}};
    $('#build-close').onclick=()=>{$('#build-frame').replaceChildren();$('#build-frame').hidden=true;$('#build-status').textContent='Preview closed. The app keeps running.';};
    new MutationObserver(()=>{for(const card of cards.values()){const iframe=card.box.querySelector('iframe');if(iframe)applyTheme(iframe);}}).observe(document.body,{attributes:true,attributeFilter:['class']});
    window.addEventListener('message',e=>{const card=[...cards.values()].find(c=>c.box.querySelector('iframe')?.contentWindow===e.source);if(!card||!card.open||e.data?.jsonrpc!=='2.0')return;if(e.data.method==='ui/notifications/size-changed'){const h=e.data.params?.height;if(Number.isFinite(h))card.box.querySelector('iframe').height=String(Math.min(1000,Math.max(160,h)));}if(e.data.method==='ui/open-link'){const href=DMRich.url(e.data.params?.url||'');if(!href)return;let a=card.box.querySelector('.preview-requested-link');if(!a){a=document.createElement('a');a.className='preview-requested-link text-link';a.target='_blank';a.rel='noopener noreferrer';card.box.append(a);}a.href=href;a.textContent='Open link ↗ '+href;}});
  }
  return {init,sync,pause,localURL};
})();
