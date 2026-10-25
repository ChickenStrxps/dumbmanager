'use strict';
// Small native-free pickers and one shared ASCII clock; no animation dependencies.
window.DMUI=(()=>{
  const instances=new WeakMap();let opened=null,tick=0,motion=()=>true;
  const frames={
    cook:['   .  ~\n  ~  .\n .----- .\n | ::: |\n  `---\'','  ~  .\n   .  ~\n .----- .\n | .:: |\n  `---\'','   ~  .\n  .  ~\n .----- .\n | ::. |\n  `---\'','  .  ~\n   ~  .\n .----- .\n | :.: |\n  `---\''],
    orbit:['·  ◇  ·',' · ◇ · ','  ·◇·  ',' · ◇ · '],
    scan:['░▒▓█▓▒░','▒▓█▓▒░░','▓█▓▒░░▒','█▓▒░░▒▓','▓▒░░▒▓█','▒░░▒▓█▓'],
    spark:['· + ·','+ ✳ +','· × ·','  +  '],
    load:['[■···]','[·■··]','[··■·]','[···■]','[··■·]','[·■··]'],
    deck:['[/ ···]','[ / ··]','[· / ·]','[·· / ]','[··· /]','[·· / ]'],
    buddy:['  .  +  .\n /|_[]_|\\\n    ─┴─','  +  .  ·\n /|_[]_|\\\n    ─┴─','  .  ·  +\n /|_[░]|\\\n    ─┴─'],
    prompt:['›','›','»','›']
  };
  // 9x9 pixel icons, drawn as crisp SVG rects in the current text colour.
  const icons={
    now:['....#####','.......##','......#.#','.....#..#','....#....','...#.....','..#......','.#.......','#........'],
    pile:['.........','..#####..','.........','.#######.','.........','#########','#.......#','#########','.........'],
    wins:['....#....','.#..#..#.','..#.#.#..','...###...','#########','...###...','..#.#.#..','.#..#..#.','....#....'],
    quests:['.#.......','.######..','.#######.','.######..','.#.......','.#.......','.#.......','###......','.........'],
    browse:['..#####..','.#..#..#.','#..#.#..#','#########','#..#.#..#','#########','#..#.#..#','.#..#..#.','..#####..'],
    git:['..#...#..','.###.###.','..#...#..','..#...#..','..#..#...','..#.#....','..##.....','.###.....','..#......'],
    settings:['....#....','.#.###.#.','..#####..','.##...##.','###...###','.##...##.','..#####..','.#.###.#.','....#....'],
    stats:['.........','.......#.','.......#.','....#..#.','....#..#.','.#..#..#.','.#..#..#.','.........','#########'],
    batch:['##.##.##.','##.##.##.','.........','##.##.##.','##.##.##.','.........','##.##.##.','##.##.##.','.........'],
    find:['.####....','#....#...','#....#...','#....#...','#....#...','.####....','.....##..','......##.','.......##'],
    chat:['.........','#########','#.......#','#.#.#.#.#','#.......#','#########','..##.....','.#.......','.........']
  };
  function pixel(name){const grid=icons[name];if(!grid)return '';let rects='';grid.forEach((row,y)=>{for(let x=0;x<row.length;x++)if(row[x]==='#')rects+=`<rect x="${x}" y="${y}" width="1" height="1"/>`;});return `<svg viewBox="0 0 9 9" fill="currentColor" aria-hidden="true" focusable="false">${rects}</svg>`;}
  function syncIcons(root=document){root.querySelectorAll('i[data-px]').forEach(node=>{if(node.dataset.pxDone===node.dataset.px)return;node.innerHTML=pixel(node.dataset.px);node.dataset.pxDone=node.dataset.px;node.setAttribute('aria-hidden','true');});}
  const safe=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function ascii(kind='load',className=''){return `<span class="ascii-token ${className}" data-ascii="${kind}" aria-hidden="true">${safe(frames[kind]?.[0]||frames.load[0])}</span>`;}
  // Tiny glyph particles use compositor motion rather than snapping between text frames.
  const sparks=new Set(),sparkView=new IntersectionObserver(entries=>{
    for(const entry of entries)entry.target.classList.toggle('ascii-spark-visible',entry.isIntersecting);
  });
  function syncSparks(){
    for(const node of sparks)if(!node.isConnected){sparkView.unobserve(node);sparks.delete(node);}
    document.querySelectorAll('[data-ascii="spark"]').forEach(node=>{
      if(sparks.has(node))return;
      node.classList.add('ascii-spark');
      node.innerHTML='<span class="spark-core">+</span>'+['.','.',':','.','.','.'].map(glyph=>`<span class="spark-particle">${glyph}</span>`).join('');
      sparks.add(node);sparkView.observe(node);
    });
  }
  function syncSparkVisibility(){
    document.documentElement.classList.toggle('ascii-page-hidden',document.hidden);
  }
  document.addEventListener('visibilitychange',syncSparkVisibility);syncSparkVisibility();
  function close(restore=false){if(!opened)return;const item=opened;opened=null;item.popup.remove();item.trigger.setAttribute('aria-expanded','false');item.trigger.classList.remove('is-open');if(restore&&item.trigger.isConnected)item.trigger.focus();}
  function position(){if(!opened)return;const {trigger,popup}=opened,rect=trigger.getBoundingClientRect();const width=Math.min(Math.max(rect.width,290),innerWidth-24);const below=innerHeight-rect.bottom-12,above=rect.top-12;const up=below<230&&above>below;const height=Math.min(360,Math.max(130,up?above:below));Object.assign(popup.style,{width:width+'px',maxHeight:height+'px',left:Math.max(12,Math.min(rect.left,innerWidth-width-12))+'px',top:(up?Math.max(12,rect.top-height-7):rect.bottom+7)+'px'});}
  function enhance(select){
    if(instances.has(select))return instances.get(select);
    const kind=['social-style','bridge-theme'].includes(select.id)?'CARD STYLE':select.id==='ai-voice'?'VOICE':select.id==='voice-provider'?'VOICE PROVIDER':select.id==='voice-project'?'PROJECT':select.id==='t3-distribution'?'T3 DISTRIBUTION':select.id==='webhook-format'?'RECEIVER':select.id==='webhook-layout'?'TEXT STYLE':['project','scout-project'].includes(select.id)?'PROJECT':select.id==='git-project'?'GIT PROJECT':select.id==='browse-tabs'?'BROWSER TAB':select.id==='context'?'T3 THREAD':['chat-thread','itch-thread','scout-thread','research-thread'].includes(select.id)?'SEND TO':['video-mode','itch-video'].includes(select.id)?'VIDEO MODE':select.id==='research-pass'?'RESEARCH PASS':select.id==='research-report'?'RESEARCH REPORT':'TEST WINDOW';
    const name=select.getAttribute('aria-label')||document.querySelector(`label[for="${select.id}"]`)?.textContent||kind;
    const trigger=document.createElement('button');trigger.type='button';trigger.className='select-trigger';trigger.id=select.id+'-trigger';trigger.setAttribute('role','combobox');trigger.setAttribute('aria-haspopup','listbox');trigger.setAttribute('aria-expanded','false');trigger.setAttribute('aria-controls',select.id+'-choices');
    select.hidden=true;select.after(trigger);
    const item={select,trigger,kind,name,popup:null,query:'',index:0,options:[]};instances.set(select,item);
    item.sync=()=>{const option=select.selectedOptions[0];trigger.disabled=select.disabled;trigger.setAttribute('aria-label',name+': '+(option?.textContent||'Choose…'));trigger.title=option?.textContent||'';trigger.innerHTML=`<span class="select-caption">${kind}</span><span class="select-current"><span class="select-symbol" aria-hidden="true">${kind==='PROJECT'?'▦':kind==='T3 THREAD'?'↗':'▣'}</span><span>${safe(option?.textContent||'Choose…')}</span><span class="select-chevron" aria-hidden="true">⌄</span></span>`;if(opened===item)draw(item);};
    item.sync();new MutationObserver(item.sync).observe(select,{childList:true,subtree:true,characterData:true,attributes:true,attributeFilter:['disabled','selected','label']});
    select.addEventListener('change',item.sync);
    trigger.onclick=()=>{if(opened===item)return close();open(item);};
    trigger.onkeydown=e=>{if(['ArrowDown','ArrowUp','Home','End'].includes(e.key)){e.preventDefault();open(item);if(e.key==='End'){item.index=item.options.length-1;highlight(item);}}else if(e.key.length===1&&!e.ctrlKey&&!e.metaKey&&e.key!==' '){e.preventDefault();open(item);item.popup.querySelector('input').value=e.key;filter(item,e.key);}};
    return item;
  }
  function highlight(item){const input=item.popup.querySelector('input');item.popup.querySelectorAll('[role=option]').forEach((node,i)=>node.classList.toggle('focused',i===item.index));const active=item.popup.querySelectorAll('[role=option]')[item.index];if(active){input.setAttribute('aria-activedescendant',active.id);active.scrollIntoView({block:'nearest'});}else input.removeAttribute('aria-activedescendant');}
  function filter(item,value){item.query=value.toLowerCase().trim();item.index=0;draw(item);item.select.dispatchEvent(new CustomEvent('dm-select-search',{detail:{query:value}}));}
  function draw(item){
    if(!item.popup)return;
    item.options=Array.from(item.select.options).filter(o=>!o.disabled&&(o.textContent+' '+(o.dataset.search||'')).toLowerCase().includes(item.query));
    item.index=Math.max(0,Math.min(item.index,item.options.length-1));
    item.popup.querySelector('.select-count').textContent=String(item.options.length).padStart(2,'0')+' FOUND';
    item.popup.querySelector('.select-options').innerHTML=item.options.map((o,i)=>`<button type="button" role="option" aria-selected="${o.selected}" id="${item.select.id}-choice-${i}" data-choice="${i}" tabindex="-1"><span class="option-check" aria-hidden="true">${o.selected?'◆':'·'}</span><span>${safe(o.textContent)}${o.dataset.detail?`<small class="select-option-detail">${safe(o.dataset.detail)}</small>`:''}</span>${o.selected?'<small>✓</small>':''}</button>`).join('')||`<p class="select-empty">[ · · · ]<br>${safe(item.select.dataset.empty||'Nothing. Try fewer letters.')}</p>`;
    const note=item.popup.querySelector('.select-note');if(note){note.hidden=!item.select.dataset.note;note.textContent=item.select.dataset.note||'';}
    item.popup.querySelectorAll('[data-choice]').forEach(button=>{button.onclick=()=>{const option=item.options[Number(button.dataset.choice)];if(!option)return;item.select.value=option.value;item.sync();close(true);item.select.dispatchEvent(new Event('change',{bubbles:true}));};});
    highlight(item);
  }
  function open(item){
    close();item.query='';item.index=0;const popup=document.createElement('div');popup.className='select-popover';popup.innerHTML=`<div class="select-menu-head">${ascii('orbit')}<span>${item.kind}</span><span class="select-count"></span></div><div class="select-search"><span aria-hidden="true">/</span><input role="combobox" aria-label="Search ${item.name}" aria-controls="${item.select.id}-choices" aria-expanded="true" aria-autocomplete="list" placeholder="Search…" autocomplete="off" spellcheck="false"><kbd>Esc</kbd></div><p class="select-note" role="status" hidden></p><div class="select-options" role="listbox" aria-label="${safe(item.name)}" id="${item.select.id}-choices"></div><div class="select-menu-foot">↑ ↓ move <span>↵ choose</span></div>`;
    item.popup=popup;opened=item;(item.select.closest('dialog[open]')||document.body).append(popup);item.trigger.setAttribute('aria-expanded','true');item.trigger.classList.add('is-open');draw(item);position();const input=popup.querySelector('input');input.focus();
    input.oninput=()=>filter(item,input.value);
    input.onkeydown=e=>{if(e.key==='Escape'){e.preventDefault();e.stopPropagation();close(true);}else if(e.key==='Tab'){close(true);}else if(['ArrowDown','ArrowUp','Home','End'].includes(e.key)){e.preventDefault();if(e.key==='Home')item.index=0;else if(e.key==='End')item.index=item.options.length-1;else item.index=(item.index+(e.key==='ArrowDown'?1:-1)+item.options.length)%Math.max(1,item.options.length);highlight(item);}else if(e.key==='Enter'){e.preventDefault();popup.querySelectorAll('[data-choice]')[item.index]?.click();}};
    item.select.dispatchEvent(new CustomEvent('dm-select-open'));
  }
  function sync(){document.querySelectorAll('select').forEach(s=>enhance(s).sync());syncSparks();syncIcons();}
  document.addEventListener('pointerdown',e=>{if(opened&&!opened.popup.contains(e.target)&&!opened.trigger.contains(e.target))close();});
  window.addEventListener('resize',position);document.addEventListener('scroll',e=>{if(opened&&!opened.popup.contains(e.target))position();},true);
  setInterval(()=>{if(document.hidden||!motion()||matchMedia('(prefers-reduced-motion: reduce)').matches)return;tick++;document.querySelectorAll('[data-ascii]').forEach(node=>{if(node.classList.contains('ascii-spark')||node.closest('[hidden]')||!node.getClientRects().length)return;const rect=node.getBoundingClientRect();if(rect.bottom<0||rect.top>innerHeight)return;const set=frames[node.dataset.ascii];if(set)node.textContent=set[Math.floor(tick/(node.dataset.ascii==='buddy'?3:1))%set.length];});},240);
  syncIcons();
  return {ascii,sync,pixel,syncIcons,close,isOpen:()=>!!opened,configure:fn=>{motion=fn;}};
})();

/* A small, continuous ASCII scene. No images, timers or work while suspended. */
const DMOrbit=(()=>{
  function init(fallback){
    if(!fallback)return;
    const canvas=document.createElement('canvas'),ctx=canvas.getContext('2d');
    if(!ctx)return; // The original text art remains useful without canvas.
    const width=252,height=148,scale=Math.min(window.devicePixelRatio||1,2);
    canvas.width=width*scale;canvas.height=height*scale;
    canvas.className='ascii-orbit';canvas.setAttribute('aria-hidden','true');
    fallback.before(canvas);fallback.hidden=true;ctx.scale(scale,scale);
    const reduced=matchMedia('(prefers-reduced-motion: reduce)');
    const points=Array.from({length:240},(_,i)=>{
      const y=1-2*(i+.5)/240,r=Math.sqrt(1-y*y),a=i*2.399963229728653;
      return {x:Math.cos(a)*r,y,z:Math.sin(a)*r};
    });
    let time=0,last=null,frame=0,inView=false,color='';
    function glyph(text,x,y,alpha){ctx.globalAlpha=alpha;ctx.fillText(text,x,y);}
    function draw(){
      ctx.clearRect(0,0,width,height);ctx.fillStyle=color;
      ctx.font='7.5px monospace';ctx.textAlign='center';ctx.textBaseline='middle';
      const angle=time*.38,c=Math.cos(angle),s=Math.sin(angle),breath=1+.025*Math.sin(time*.8);
      // Stable points rotate as a sphere; no random regeneration or full-frame flicker.
      const surface=points.map(p=>{
        const x=p.x*c+p.z*s,z=p.z*c-p.x*s;
        return {x,y:p.y*.94-z*.23,z};
      }).sort((a,b)=>a.z-b.z);
      for(const p of surface){
        const depth=(p.z+1)/2,flow=.5+.5*Math.sin(p.y*8+time*1.6+p.x*3);
        glyph(depth>.65?':':'.',126+p.x*40*breath,70+p.y*40*breath,
          .2+depth*.6+flow*.15);
      }
      // Small orbiting punctuation with softly fading, spatially continuous trails.
      for(let i=0;i<26;i++){
        const phase=time*(.2+(i%4)*.04)+i*2.39996,radius=47+(i%6)*8;
        for(let trail=2;trail>=0;trail--){
          const a=phase-trail*.024,x=Math.cos(a)*radius,y=Math.sin(a)*radius*.58;
          const alpha=(.3+.4*(.5+.5*Math.sin(time*.8+i)))*(1-trail*.28);
          glyph(trail?'.':i%9===0?'+':i%4===0?':':'.',126+x,70+y-x*.14,alpha);
        }
      }
      // A restrained moving glint through the centre retains the warm dithered core.
      for(let i=0;i<11;i++){
        const x=(i-5)*4,y=Math.sin(i*.52+time*.9)*3;
        glyph(':',126+x,70+y,.45+.3*Math.sin(i*.4+time*.7)**2);
      }
      ctx.globalAlpha=1;
    }
    function running(){return inView&&!document.hidden&&!reduced.matches&&!document.body.classList.contains('no-motion');}
    function tick(now){
      frame=0;
      if(!running()){last=null;return;}
      if(last===null){last=now;}
      else if(now-last>=1000/30){time+=Math.min((now-last)/1000,.05);last=now;draw();}
      frame=requestAnimationFrame(tick);
    }
    function sync(){
      const next=getComputedStyle(canvas).color;
      if(next!==color){color=next;draw();}
      if(running()){if(!frame){last=null;frame=requestAnimationFrame(tick);}}
      else {cancelAnimationFrame(frame);frame=0;last=null;}
    }
    new IntersectionObserver(entries=>{inView=entries[0].isIntersecting;sync();}).observe(canvas);
    new MutationObserver(sync).observe(document.body,{attributes:true,attributeFilter:['class']});
    reduced.addEventListener('change',sync);document.addEventListener('visibilitychange',sync);
    sync();
  }
  return {init};
})();
