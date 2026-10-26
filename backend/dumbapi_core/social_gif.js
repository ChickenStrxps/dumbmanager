/* DumbAPI animated share cards (rendered in a throwaway headless Edge by
   manager_social_gif.py): seeded ASCII scenes rendered on canvas, encoded as a
   seamless looping GIF. Every motion is periodic over the loop, so frame N
   flows straight back into frame 0. Copy is drawn whole (never truncated). */
window.DMCardGif=(()=>{
  const W=1200,H=675,MONO='"Cascadia Mono", Consolas, monospace',SANS='Bahnschrift, "Segoe UI", sans-serif';
  const TAU=Math.PI*2;
  let FRAMES=72,DELAY=5;

  // ---------- seeded randomness ----------
  function hash(text){let h=2166136261;for(const ch of String(text)){h^=ch.codePointAt(0);h=Math.imul(h,16777619);}return h>>>0;}
  function rng(seed){let s=seed>>>0||1;return()=>{s^=s<<13;s>>>=0;s^=s>>>17;s^=s<<5;s>>>=0;return s/4294967296;};}
  const pick=(r,list)=>list[Math.floor(r()*list.length)];
  function weighted(r,table){const total=table.reduce((n,[,w])=>n+w,0);let x=r()*total;for(const [v,w] of table){if((x-=w)<0)return v;}return table[0][0];}

  // ---------- ASCII cast (drawn facing right unless noted) ----------
  const FLIP={'(':')',')':'(','/':'\\','\\':'/','<':'>','>':'<','[':']',']':'[','{':'}','}':'{','`':"'","'":'`','d':'b','b':'d','p':'q','q':'p'};
  function mirror(frames){return frames.map(lines=>{const w=Math.max(...lines.map(l=>l.length));return lines.map(l=>[...l.padEnd(w)].reverse().map(c=>FLIP[c]||c).join(''));});}
  const CAST={
    dog:{face:'l',frames:[['  __','o\'\')}____','  \\_/     )~','   ||---||'],['  __','o\'\')}____','  \\_/     )~','   /\\---/\\']]},
    cat:{face:'l',frames:[[' /\\_/\\',' ( o.o )____',' > ^ <     )~','    ||  ||'],[' /\\_/\\',' ( o.o )____',' > ^ <     )~','    /\\  /\\']]},
    fish:{face:'r',frames:[['><(((\'>'],['>< (((\'>']]},
    bigfish:{face:'r',frames:[['   _____',' /  \\  o\\','<    |   >',' \\__/___/'],['   _____',' /  \\  o\\','>    |   >',' \\__/___/']]},
    shark:{face:'r',frames:[['          /|','    _____/ |_____','><(_________  o  \\>','          \\|'],['          /|','    _____/ |_____','<>(_________  o  \\>','          \\|']]},
    fin:{face:'r',frames:[['   /|','  / |','~~~~~~~'],['   /|','  / |','~^~~^~~']]},
    penguin:{face:'r',frames:[['   _','  (\'v\')',' /(   )\\','  ^^ ^^'],['   _','  (\'v\')','  (   )\\','   ^^  ^^']]},
    crab:{face:'r',frames:[['(\\/)(o,,o)(\\/)'],['(/\\)(o,,o)(/\\)']]},
    duck:{face:'l',frames:[['  __','<(o )___',' ( ._> /','  `---\''],['  __','<(o )___',' ( ._> /','  `-^-\'']]},
    frog:{face:'r',frames:[['  @..@',' (----)','( >__< )','^^ ~~ ^^'],['  @..@',' (----)','( >__< )',' ^^~~^^']]},
    bunny:{face:'r',frames:[['(\\_/)','(o.o)','(> <)'],['(\\_/)','(o.o)','/> <\\']]},
    mouse:{face:'l',frames:[['<:3 )~~'],['<:3 )~-']]},
    snail:{face:'l',frames:[['   @','_@_/\'-\''],['   @','_@_/\'-.']]},
    bird:{face:'r',frames:[['\\v/'],['-v-']]},
    bat:{face:'r',frames:[['/^v^\\'],['\\^v^/']]},
    moth:{face:'r',frames:[['\\oo/'],['/oo\\']]},
    robot:{face:'r',frames:[[' [o_o]',' /|_|\\','  d b'],[' [o_o]',' \\|_|/','  b d']]},
    agent:{face:'r',frames:[['(>o_o)>'],['<(o_o<)']]},
    window:{face:'r',frames:[[' _ _  ','|_|_|=~','|_|_|~='],[' _ _  ','|_|_|~=','|_|_|=~']]},
    clippy:{face:'r',frames:[[' __','/  \\','|@@|','|| |/','|\\_/|','\\___/'],[' __','/  \\','|@@|','\\| ||','|\\_/|','\\___/']]},
    happymac:{face:'r',frames:[[' ____','|.--.|','||:)||','|\'--\'|',' |__|'],[' ____','|.--.|','||;)||','|\'--\'|',' |__|']]},
    chip:{face:'r',frames:[['  _||||_',' -|GPU |-',' -|_RTX|-','  /\\  /\\'],['  _||||_',' -|GPU |-',' -|_RTX|-','  \\/  \\/']]},
    cursor:{face:'r',frames:[['[>_]'],['[> ]']]},
    hourglass:{face:'r',frames:[['[X]'],['[+]']]},
    pi:{face:'r',frames:[['  _______',' (__o_o__)','   |   |','  _|   |_'],['  _______',' (__o_o__)','   |   |','   /|   |\\']]},
    deer:{face:'l',frames:[['\\|/ \\|/','  \\\\ //','  (o o)____','   \\_/    )','     ||--||'],['\\|/ \\|/','  \\\\ //','  (o o)____','   \\_/    )','     /\\--/\\']]},
    butterfly:{face:'r',frames:[['}i{'],['>i<']]},
    camel:{face:'l',frames:[['   __','  (o \\_____','   \\_  ^ ^ )~','     ||   ||'],['   __','  (o \\_____','   \\_  ^ ^ )~','     /\\  /\\']]},
    lizard:{face:'r',frames:[['~~=:>'],['~-=:>']]},
    tumbleweed:{face:'r',frames:[[' .@@.','(@%@@)',' `@@\''],[' .@%.','(@@%@)',' `%@\'']]},
    scorpion:{face:'l',frames:[['   _','  ( \\','(oo)=/~'],['   _','  ( )','(oo)=\\~']]},
    cactus:{face:'r',frames:[['    _','   | |',' _ | | _','| || || |',' \\_   _/','   | |'],['    _','   | |',' _ | |  ','| || |_|',' \\_   _/','   | |']]},
    palm:{face:'r',frames:[['  __\\|/__','   /|\\','    |','    |','   /_\\'],['  _\\\\|//_','   /|\\','    |','    |','   /_\\']]},
    mug:{face:'r',frames:[['  ( (','   ) )',' .....','|     |]','\\     /',' `---\''],['   ) )','  ( (',' .....','|     |]','\\     /',' `---\'']]},
    ghost:{face:'r',frames:[[' .-.','(o o)','| O |','\'~~~\''],[' .-.','(o o)','| o |','~\'~\'~']]}
  };
  const cast=(name,dir)=>{const c=CAST[name];return (c.face==='r')===(dir>0)?c.frames:mirror(c.frames);};

  // ---------- themes ----------
  // Each theme: colors, static backdrop, static chrome, lanes (walkers / flyers) and ambient motion.
  const THEMES={
    dumb:{name:'DumbManager',weight:30,bg:'#090a12',ink:'#fcfaff',body:'#d7d7e8',dim:'#3a3b5c',accents:[['#ff5ccc','#8b8fff'],['#69f5ce','#a6a0ff'],['#ffc166','#ff74b8'],['#b9a1ff','#65e5f4']],
      walkers:['cat','crab','frog','ghost','duck','robot','bunny','snail'],flyers:['moth','bat','bird'],ambient:'stars',tag:'DEV / LOG'},
    windows:{name:'Windows',weight:8,bg:'#008080',ink:'#ffffff',body:'#d8e8e8',dim:'#0b5f5f',accents:[['#ffff55','#c0c0c0']],
      walkers:['clippy','window','mouse'],flyers:['cursor','hourglass'],ambient:'windows',hero:'clippy',tag:'C:\\DUMB>'},
    mac:{name:'Mac',weight:8,bg:'#1c1b2e',ink:'#ffffff',body:'#dcdcf0',dim:'#3b3a5e',accents:[['#28c840','#febc2e'],['#ff5f57','#5ac8fa']],
      walkers:['happymac','mouse'],flyers:['bird'],ambient:'mac',hero:'happymac',tag:'⌘ BUILD'},
    nvidia:{name:'NVIDIA',weight:8,bg:'#050605',ink:'#f2fff0',body:'#c9d8c4',dim:'#16300a',accents:[['#76b900','#b6ff3b']],
      walkers:['chip','robot'],flyers:['moth'],ambient:'nvidia',tag:'RTX ON'},
    t3:{name:'T3 Code',weight:8,bg:'#0b0b10',ink:'#f5f5fa',body:'#c8c8d8',dim:'#26263a',accents:[['#ff5ca8','#a78bfa']],
      walkers:['agent','robot','agent'],flyers:['moth'],ambient:'t3',tag:'T3 CODE'},
    dog:{name:'Dog park',weight:8,bg:'#0c1424',ink:'#fffaf0',body:'#e2dccd',dim:'#28405a',accents:[['#ffb347','#7fd3ff']],
      walkers:['dog','dog','duck'],flyers:['bird'],ambient:'dog',hero:'dog',tag:'GOOD BOY'},
    cat:{name:'Cat night',weight:8,bg:'#0d0a1c',ink:'#fff8ff',body:'#ddd3ee',dim:'#2c2350',accents:[['#ffd166','#c49bff']],
      walkers:['cat','cat','mouse'],flyers:['bat'],ambient:'cat',hero:'cat',tag:'MEOW.EXE'},
    fish:{name:'Aquarium',weight:8,bg:'#031a2c',ink:'#f0fbff',body:'#c4e4f2',dim:'#0d3a58',accents:[['#ff8a5c','#5ce1ff']],
      walkers:['fish','bigfish','fish','crab'],flyers:['fish'],ambient:'fish',hero:'bigfish',tag:'BLUB'},
    shark:{name:'Shark week',weight:8,bg:'#02101f',ink:'#f2f8ff',body:'#bcd2e8',dim:'#0c2c4a',accents:[['#5cc8ff','#ff4f6d']],
      walkers:['shark','fish','fin'],flyers:['bird'],ambient:'shark',hero:'shark',tag:'DUN DUN'},
    penguin:{name:'Ice shelf',weight:8,bg:'#0a1626',ink:'#ffffff',body:'#d4e6f6',dim:'#22405e',accents:[['#ffcf3f','#9fe8ff']],
      walkers:['penguin','penguin','penguin'],flyers:['bird'],ambient:'penguin',hero:'penguin',tag:'NOOT NOOT'},
    ohmypi:{name:'Oh My Pi',weight:8,bg:'#0d0b14',ink:'#f6f0ff',body:'#d6cce8',dim:'#2a2440',accents:[['#ff79c6','#8be9fd'],['#bd93f9','#50fa7b']],
      walkers:['pi','agent','pi','robot'],flyers:['moth'],ambient:'ohmypi',hero:'pi',tag:'π OH MY PI'},
    chill:{name:'Lofi chill',weight:8,bg:'#1a1428',ink:'#fff4ec',body:'#e6d6d0',dim:'#3a2e4a',accents:[['#ffb4a2','#b5a8ff'],['#f6c177','#9ccfd8']],
      walkers:['cat','snail','cat'],flyers:['moth'],ambient:'chill',hero:'mug',tag:'LOFI BEATS TO SHIP TO',frames:96,delay:6,crowd:3},
    nature:{name:'Forest',weight:8,bg:'#0b1a12',ink:'#f4fff2',body:'#cfe6cc',dim:'#1d3a26',accents:[['#9be15d','#ffd166'],['#7bdcb5','#f78c6b']],
      walkers:['deer','bunny','snail','frog'],flyers:['butterfly','bird'],ambient:'nature',hero:'deer',tag:'TOUCH GRASS'},
    beach:{name:'Beach day',weight:8,bg:'#1b1035',ink:'#fff8f0',body:'#f0dccd',dim:'#3b2a5a',accents:[['#ff9e64','#7dcfff'],['#ffd166','#ff6b9d']],
      walkers:['crab','crab','duck'],flyers:['bird','bird'],ambient:'beach',hero:'palm',tag:'OUT OF OFFICE'},
    desert:{name:'Desert',weight:8,bg:'#1f120c',ink:'#fff3e0',body:'#ead2b8',dim:'#4a2e1c',accents:[['#ff9f43','#ffd57e'],['#e17055','#fdcb6e']],
      walkers:['camel','lizard','tumbleweed','scorpion'],flyers:['bird'],ambient:'desert',hero:'cactus',tag:'NO BUGS OUT HERE'},
    flow:{name:'Water flow',weight:12,bg:'#060c18',ink:'#fff9ee',body:'#d3e0e5',dim:'#20364b',accents:[['#ffc477','#72e6ed'],['#ffa777','#a0e8d2']],
      walkers:['fish','fish','crab'],flyers:['fish'],ambient:'flow',hero:'fish',tag:'GO WITH THE FLOW',frames:96,delay:6,crowd:3},
    smoke:{name:'Dithered smoke',weight:12,bg:'#0c0b14',ink:'#fff6e8',body:'#ded5df',dim:'#302940',accents:[['#ffc28b','#b59cff'],['#efadcf','#94d9db']],
      walkers:['cat','robot','snail'],flyers:['moth'],ambient:'smoke',hero:'mug',tag:'LET IT COOK',frames:96,delay:6,crowd:3}
  };

  function plan(id,vibe=0,force={}){
    const r=rng(hash(id+':'+vibe));
    let key=weighted(r,Object.entries(THEMES).map(([k,t])=>[k,t.weight]));if(THEMES[force.theme])key=force.theme;
    const theme=THEMES[key],[accent,secondary]=pick(r,theme.accents);
    const events=[];
    if(r()<.22)events.push('greg');
    if(r()<.28)events.push('flicker');
    if(r()<.24)events.push('lightning');
    // Calm water and smoke have no random full-card flashes. Greg can still visit.
    if(key==='flow'||key==='smoke')events.splice(0,events.length,...events.filter(e=>e==='greg'));
    if(force.events)events.splice(0,events.length,...force.events);
    const dir=r()<.5?1:-1,walkers=[0,1,2,3].slice(0,theme.crowd||4).map(i=>({name:pick(r,theme.walkers),dir:i===3?-dir:dir,laps:i===3?2:1,phase:(i/3+r()*.15)%1}));
    const flyers=[0,1].map(i=>({name:pick(r,theme.flyers),dir:r()<.5?1:-1,laps:1+(r()<.5?1:0),phase:(i/2+r()*.3)%1,bob:r()*TAU}));
    return {key,theme,accent,secondary,events,walkers,flyers,hero:theme.hero||pick(r,['cat','frog','ghost','duck','robot','crab']),seed:r()*1e9|0,
      greg:Math.floor(r()*24),flick:12+Math.floor(r()*40),bolt:{x:760+r()*360,at:6+Math.floor(r()*50),seed:r()*1e9|0}};
  }

  // ---------- drawing helpers ----------
  function font(c,size,weight=700,family=MONO){c.font=`${weight} ${size}px ${family}`;}
  function art(c,lines,x,y,size,color,alpha=1){
    font(c,size);c.globalAlpha=alpha;const lead=Math.round(size*1.08);
    lines.forEach((l,i)=>{c.fillStyle=Array.isArray(color)?color[i%color.length]:color;c.fillText(l,Math.round(x),Math.round(y+i*lead));});
    c.globalAlpha=1;
  }
  function wrap(c,text,width){
    const out=[];
    for(const para of String(text).split('\n')){
      let line='';
      for(const word of para.split(/(\s+)/)){
        if(!word)continue;
        const next=line+word;
        if(c.measureText(next).width<=width){line=next;continue;}
        if(line.trim())out.push(line.trimEnd());
        line=word.trimStart();
        while(c.measureText(line).width>width){ // unbroken runs: cut by glyph
          let cut=1;while(cut<line.length&&c.measureText(line.slice(0,cut+1)).width<=width)cut++;
          out.push(line.slice(0,cut));line=line.slice(cut);
        }
      }
      out.push(line.trimEnd());
    }
    while(out.length>1&&!out[out.length-1])out.pop();
    return out;
  }
  function fit(c,text,width,height,max,weight,family){
    for(let size=max;size>=8;size--){
      font(c,size,weight,family);const lines=wrap(c,text,width),lead=Math.round(size*1.22);
      if(lines.length*lead<=height)return {size,lines,lead};
    }
    font(c,8,weight,family);return {size:8,lines:wrap(c,text,width),lead:10};
  }
  const wave=(t,k=1,p=0)=>Math.sin(TAU*(t*k+p));

  // ---------- static backdrop per theme ----------
  function backdrop(c,p){
    const {theme,accent,secondary}=p,r=rng(p.seed);
    c.fillStyle=theme.bg;c.fillRect(0,0,W,H);
    font(c,12,400);
    if(p.key==='windows'){
      // Classic window over a teal desktop.
      c.fillStyle='#c0c0c0';c.fillRect(14,14,W-28,H-62);
      c.fillStyle='#ffffff';c.fillRect(14,14,W-28,2);c.fillRect(14,14,2,H-62);c.fillStyle='#404040';c.fillRect(W-16,14,2,H-62);c.fillRect(14,H-50,W-28,2);
      const bar=c.createLinearGradient(20,0,W-20,0);bar.addColorStop(0,'#000080');bar.addColorStop(1,'#1084d0');c.fillStyle=bar;c.fillRect(20,20,W-40,30);
      c.fillStyle='#000000';c.fillRect(22,56,W-44,H-112);
      ['_','□','X'].forEach((g,i)=>{const x=W-112+i*30;c.fillStyle='#c0c0c0';c.fillRect(x,24,24,22);c.fillStyle='#000';font(c,15);c.fillText(g,x+6,27);});
      c.fillStyle='#c0c0c0';c.fillRect(0,H-36,W,36);c.fillStyle='#ffffff';c.fillRect(0,H-36,W,2);
      c.fillStyle='#c0c0c0';c.fillRect(6,H-31,92,26);c.strokeStyle='#000';c.strokeRect(6.5,H-30.5,91,25);c.fillStyle='#000';font(c,15);c.fillText('▶ Start',16,H-26);
      c.strokeStyle='#808080';c.strokeRect(W-118.5,H-30.5,110,25);
      return;
    }
    if(p.key==='mac'){
      const sky=c.createLinearGradient(0,0,W,H);sky.addColorStop(0,'#2a1f5c');sky.addColorStop(.55,'#4b2f7a');sky.addColorStop(1,'#d0587a');
      c.fillStyle=sky;c.fillRect(0,0,W,H);
      c.fillStyle='#0000004d';c.fillRect(0,0,W,24);c.fillStyle='#fff';font(c,13);c.fillText('  DumbManager   File   Edit   View   Itch   Window   Help',10,5);
      c.fillStyle='#14131fe8';rounded(c,24,36,W-48,H-120,14);c.fill();
      c.fillStyle='#232236';rounded(c,24,36,W-48,34,14);c.fill();c.fillRect(24,56,W-48,14);
      ['#ff5f57','#febc2e','#28c840'].forEach((col,i)=>{c.fillStyle=col;c.beginPath();c.arc(48+i*22,53,7,0,TAU);c.fill();});
      c.fillStyle='#ffffff26';rounded(c,W/2-220,H-74,440,62,16);c.fill();
      return;
    }
    if(p.key==='t3'){
      c.fillStyle='#111118';c.fillRect(0,0,W,H);c.fillStyle='#0b0b10';c.fillRect(0,0,W,36);
      ['#ff5f57','#febc2e','#28c840'].forEach((col,i)=>{c.fillStyle=col;c.beginPath();c.arc(22+i*20,18,6,0,TAU);c.fill();});
      c.fillStyle='#6b6b80';font(c,13,700);c.fillText('t3 code — dumbmanager',W/2-90,10);
      c.fillStyle='#0e0e14';c.fillRect(0,36,40,H-36);
      ['◆','#','⌘','▸'].forEach((g,i)=>{c.fillStyle=i===0?accent:'#4a4a60';font(c,16);c.fillText(g,13,58+i*40);});
      c.strokeStyle='#26263a';c.beginPath();c.moveTo(40.5,36);c.lineTo(40.5,H);c.moveTo(0,36.5);c.lineTo(W,36.5);c.stroke();
      c.fillStyle='#15151f';rounded(c,62,H-66,W-90,46,10);c.fill();c.strokeStyle='#2c2c44';rounded(c,62.5,H-65.5,W-91,45,10);c.stroke();
      return;
    }
    c.strokeStyle=accent;c.lineWidth=3;c.beginPath();
    c.moveTo(24,122);c.lineTo(24,24);c.lineTo(122,24);c.moveTo(1078,24);c.lineTo(1176,24);c.lineTo(1176,122);
    c.moveTo(1176,H-122);c.lineTo(1176,H-24);c.lineTo(1078,H-24);c.moveTo(122,H-24);c.lineTo(24,H-24);c.lineTo(24,H-122);c.stroke();c.lineWidth=1;
  }
  function rounded(c,x,y,w,h,r){c.beginPath();c.moveTo(x+r,y);c.arcTo(x+w,y,x+w,y+h,r);c.arcTo(x+w,y+h,x,y+h,r);c.arcTo(x,y+h,x,y,r);c.arcTo(x,y,x+w,y,r);c.closePath();}

  // ---------- static copy layer ----------
  const LABELS={accepted:'WE’RE SO BACK',review:'READY TO TEST',changed:'WORK IN PROGRESS',draft:'IDEA INCOMING',stashed:'ITCH STASHED',linked:'SOURCE LINKED',research:'RESEARCH IN MOTION',researched:'SOURCES GATHERED',related:'CONNECTED THE DOTS',sent:'SENT TO T3',needs_input:'YOUR NEXT MOVE',cancelled:'RESEARCH STOPPED'};
  // Vertical bands: logo/header, sky lane, copy, label, ground lane. Lanes never cross copy.
  const LAYOUT={
    windows:{x:44,logo:0,tag:0,sky:62,divider:104,label:500,ground:612},
    mac:{x:56,logo:0,tag:46,sky:78,divider:112,label:496,ground:584},
    t3:{x:70,logo:76,tag:82,sky:44,divider:122,label:488,ground:600},
    other:{x:64,logo:44,tag:51,sky:84,divider:124,label:516,ground:640}};
  const box=p=>LAYOUT[p.key]||LAYOUT.other;
  function copy(c,p,data,picture){
    const {theme,accent,secondary}=p,L=box(p),right=picture?706:722,x=L.x;
    const bridge=data.brand==='DUMBBRIDGE';
    c.textBaseline='top';
    if(p.key==='windows'){font(c,16);c.fillStyle='#fff';c.fillText((bridge?'DumbBridge.exe - ':'DumbManager.exe - ')+(data.project||(bridge?'idea file':'dev log')),30,27);}
    else if(p.key==='mac'){font(c,14);c.fillStyle='#c8c8e0';c.fillText((bridge?'dumbbridge - ':'dumbmanager - ')+(data.project||(bridge?'idea file':'dev log')),118,46);}
    if(L.logo){
      const y=L.logo;
      c.fillStyle=accent;c.fillRect(x,y,32,32);c.fillStyle=theme.bg;c.fillRect(x+8,y+8,8,8);c.fillRect(x+16,y+16,8,8);
      const brand=data.brand==='DUMBBRIDGE'?'DUMBBRIDGE':'DUMBMANAGER';
      font(c,19);c.fillStyle=theme.ink;c.fillText(brand,x+46,y+7);const end=x+46+c.measureText(brand).width+12;
      if(data.project){font(c,14,400);c.fillStyle=secondary;c.fillText('/ '+data.project.slice(0,28),end,y+10);}
    }
    if(L.tag){font(c,15,400);c.fillStyle=secondary;c.fillText(theme.tag,1136-c.measureText(theme.tag).width,L.tag);}
    c.fillStyle=secondary;c.globalAlpha=.3;c.fillRect(x,L.divider,1136-x,1);c.globalAlpha=1;
    font(c,13,400);c.fillStyle=accent;c.fillText(bridge?'S H A P E   T H E   I D E A':'W H A T   C H A N G E D',x,L.divider+14);
    const width=right-x,hTop=L.divider+38,base=L.label;
    const headline=fit(c,data.headline,width,Math.min(150,(base-hTop)*.45),44,700,SANS);
    font(c,headline.size,700,SANS);c.fillStyle=theme.ink;headline.lines.forEach((l,i)=>c.fillText(l,x,hTop+i*headline.lead));
    let y=hTop+headline.lines.length*headline.lead+10;
    c.fillStyle=accent;c.fillRect(x,y,60,4);c.fillStyle=secondary;c.fillRect(x+66,y,10,4);y+=16;
    const summary=fit(c,data.summary,width,base-y-16,24,400,MONO);
    font(c,summary.size,400);c.fillStyle=theme.body;summary.lines.forEach((l,i)=>c.fillText(l,x,y+i*summary.lead));
    const label='[+] '+(LABELS[data.stage]||LABELS.changed);font(c,18);
    const lw=c.measureText(label).width+36;c.fillStyle=accent;c.fillRect(x,base,lw,40);c.fillStyle='#090a12';c.fillText(label,x+18,base+11);
    return {headline:{...headline,x,y:hTop,width},summary:{...summary,x,y,width},label:{x,y:base}};
  }
  const PANEL={x:744,y:176,w:392,h:298};
  function panel(c,p,picture,data={}){
    const {theme,accent,secondary}=p,{x,y,w,h}=PANEL;
    c.fillStyle=accent;c.globalAlpha=.25;c.fillRect(x+8,y+8,w,h);c.globalAlpha=1;
    c.fillStyle=p.key==='windows'?'#c0c0c0':'#12131f';c.fillRect(x,y,w,h);c.strokeStyle=secondary;c.lineWidth=2;c.strokeRect(x+1,y+1,w-2,h-2);c.lineWidth=1;
    c.fillStyle='#080910';c.fillRect(x+12,y+12,w-24,h-24);
    font(c,13,400);c.fillStyle=secondary;c.fillText(picture?'O N   S C R E E N':data.brand==='DUMBBRIDGE'?'[ A S C I I   C R E W ]':'[ B U I L D   L O G ]',x+2,y-22);
    if(picture){
      const s=Math.min((w-24)/picture.width,(h-24)/picture.height),dw=picture.width*s,dh=picture.height*s;
      c.imageSmoothingQuality='high';c.drawImage(picture,x+12+(w-24-dw)/2,y+12+(h-24-dh)/2,dw,dh);
    }
  }

  // ---------- animated layers ----------
  function ambient(c,p,t,f){
    const {accent,secondary,key}=p;
    if(key==='dog'){const u=(t*2)%1,bx=60+(1-Math.abs(1-2*t))*(W-120),by=H-56-Math.abs(Math.sin(Math.PI*u))*80;art(c,['o'],bx,by,13,'#ffdd55',1);}
    if(key==='cat'){for(let i=0;i<3;i++){const u=(t+i/3)%1;art(c,[['z','Z','z'][i]],1044+u*34,150-u*54,9+u*9,secondary,1-u);}}
    if(key==='windows'){ // moving cursor, taskbar clock, progress
      const cx=900+wave(t,1)*180,cy=360+wave(t,2,.25)*90;art(c,['|\\','| \\','|  \\','|_/'],cx,cy,10,'#ffffff',1);
      font(c,15);c.fillStyle='#000';c.fillText((f%24<12?'4:20':'4 20')+' PM',W-104,H-26);
      c.fillStyle='#808080';c.fillRect(110,H-28,300,20);const n=Math.floor((t*30)%15)+1;c.fillStyle='#000080';for(let i=0;i<n;i++)c.fillRect(113+i*20,H-25,16,14);
    }
    if(key==='mac'){ // dock bounce + beachball
      font(c,24);const icons=['[:)]','{ }','<#>','[=]','(*)','~$_'];
      icons.forEach((g,i)=>{const hop=i===Math.floor(t*6)%6?Math.abs(Math.sin(Math.PI*((t*6)%1)))*16:0;c.fillStyle=[accent,secondary,'#fff','#ff5f57','#5ac8fa','#c49bff'][i];c.fillText(g,W/2-200+i*70,H-60-hop);});
      art(c,[['|','/','-','\\'][Math.floor(t*FRAMES/2)%4]],W-50,4,14,'#ffffff',1);
      font(c,13);c.fillStyle='#fff';c.fillText(f%24<12?'4:20':'4 20',W-110,5);
    }
    if(key==='ohmypi'){ // scrolling pi ticker along the top edge
      const digits='3.14159265358979323846264338327950288419716939937510 π ';font(c,11);const cw=c.measureText('0').width,period=digits.length*cw,off=(t*period*2)%period;
      let line='';while(line.length*cw<W+period*2)line+=digits;c.globalAlpha=.55;c.fillStyle=secondary;c.fillText(line,-off,6);c.globalAlpha=1;
    }
    if(key==='chill'){const bars=[0,1,2,3,4,5,6,7].map(i=>'▁▂▃▄▅▆▇'[Math.floor((wave(t,2+i%3,i*.13)+1)/2*6.99)]).join('');art(c,['♪ '+bars],W-200,H-34,14,accent,.9);}
    if(key==='beach'){const u=(t*3)%1;art(c,['(O)'],820,H-140-Math.abs(Math.sin(Math.PI*u))*80,14,'#ff6b9d');}
    if(key==='t3'){ // composer typing + spinner
      const prompt='make the share cards way cooler',n=Math.min(prompt.length,Math.floor(((t*2)%1)*prompt.length*1.4));
      font(c,16,400);c.fillStyle='#d0d0e0';c.fillText('> '+prompt.slice(0,n)+(f%12<6?'█':' '),80,H-52);
      art(c,[['|','/','-','\\'][f%4]+' working'],W-150,H-52,14,secondary,1);
    }
  }
  const TERRAIN={ohmypi:'3.14159265 ',nature:",;'\",.,",beach:'',desert:'_.-~-._',chill:'',dumb:'_.-^-._.-~-._',dog:",;'\",.,'`;",fish:'_.,_~_,._',penguin:'=_-=__-=_',nvidia:'-=[]=-=||=-',cat:'^ ^  ^   ^',shark:'',windows:'',mac:'',t3:''};
  function field(c,p,t){ // scrolling ground line under the walkers
    const {secondary,key}=p,pat=TERRAIN[key];if(!pat)return;
    const {ground}=box(p);font(c,10);const cw=c.measureText('_').width,period=pat.length*cw,off=(t*period)%period;
    let line='';while(line.length*cw<W+period*2)line+=pat;
    c.fillStyle=key==='dog'||key==='nature'?'#3f9a4a':key==='desert'?'#c98a4b':key==='penguin'?'#9cc8ee':secondary;c.globalAlpha=.7;c.fillText(line,-off,ground+2);c.globalAlpha=1;
  }

  // ---------- fine ASCII scenes ----------
  // Each theme paints light on a tiny canvas (one pixel per character cell) in card
  // coordinates; asciiLayer turns brightness into a glyph ramp and hue into an ink.
  const CW=6,CH=9,COLS=W/CW,ROWS=H/CH,RAMP=' .`,:-~=+*xo%#@';
  const rgbOf=hex=>{const v=parseInt(hex.slice(1,7),16);return [v>>16,v>>8&255,v&255];};
  const rgba=(hex,a)=>{const [r,g,b]=rgbOf(hex);return `rgba(${r},${g},${b},${Math.max(0,Math.min(1,a))})`;};
  function glow(c,x,y,r,col,a=1){const g=c.createRadialGradient(x,y,0,x,y,r);g.addColorStop(0,rgba(col,a));g.addColorStop(1,rgba(col,0));c.fillStyle=g;c.fillRect(x-r,y-r,r*2,r*2);}
  function vgrad(c,y0,y1,stops){const g=c.createLinearGradient(0,y0,0,y1);stops.forEach(([o,col,a])=>g.addColorStop(o,rgba(col,a)));return g;}
  const cell=(c,x,y)=>c.fillRect(Math.floor(x/CW)*CW,Math.floor(y/CH)*CH,CW,CH);
  // Periodic height-field normals: restrained refraction, not a physics solver.
  // Integer temporal frequencies close both position and velocity at the seam.
  function water(x,y,t,phase=0){
    const a=x*.028+y*.041+TAU*t+phase,b=x*.053-y*.019-TAU*t*2+phase*.7;
    const bend=Math.sin(x*.009+y*.016+TAU*t)*.8,d=x*.016-y*.034+TAU*t+bend;
    const rx=x-184-Math.sin(TAU*t)*85,ry=y-137-Math.cos(TAU*t)*54,r=Math.hypot(rx,ry),e=Math.exp(-r*r/9000);
    const curl=Math.cos(r*.065-TAU*t*2)*e*12;
    return {dx:Math.cos(a)*5+Math.cos(b)*2.5+Math.cos(d)*3+(rx-ry*.4)/Math.max(r,1)*curl,
      dy:Math.cos(a)*6-Math.cos(b)*2+Math.cos(d)*4+(ry+rx*.4)/Math.max(r,1)*curl,
      light:Math.pow(Math.max(0,(Math.cos(a)+Math.cos(d))*.5),12)};
  }
  function dots(c,seed,n,col,t,{x0=0,y0=0,x1=W,y1=H,tw=.35,a=.8}={}){a*=.5;
    const r=rng(seed);c.fillStyle=col;
    for(let i=0;i<n;i++){const x=x0+r()*(x1-x0),y=y0+r()*(y1-y0),k=1+Math.floor(r()*3),ph=r(),big=r();
      c.globalAlpha=i<n*tw?a*(.3+.7*(wave(t,k,ph)+1)/2):a*(.3+big*.7);cell(c,x,y);}
    c.globalAlpha=1;
  }
  function ridge(c,base,amp,seed,fill){
    const r=rng(seed),f=[r()*.004+.002,r()*.01+.006,r()*.03+.02],ph=[r()*9,r()*9,r()*9];
    c.beginPath();c.moveTo(0,H);for(let x=0;x<=W;x+=8)c.lineTo(x,base-amp*(Math.sin(x*f[0]+ph[0])*.6+Math.sin(x*f[1]+ph[1])*.3+Math.sin(x*f[2]+ph[2])*.1));
    c.lineTo(W,H);c.closePath();c.fillStyle=fill;c.fill();
  }
  function along(pts,u){
    const seg=[];let total=0;for(let i=1;i<pts.length;i++){const l=Math.hypot(pts[i][0]-pts[i-1][0],pts[i][1]-pts[i-1][1]);seg.push(l);total+=l;}
    let d=u*total;for(let i=0;i<seg.length;i++){if(d<=seg[i]||i===seg.length-1){const k=seg[i]?Math.min(1,d/seg[i]):0;return [pts[i][0]+(pts[i+1][0]-pts[i][0])*k,pts[i][1]+(pts[i+1][1]-pts[i][1])*k];}d-=seg[i];}
    return pts[0];
  }
  function curtains(c,t,bands,depth){ // aurora-style vertical light ribbons
    bands.forEach(([col,ph,base])=>{for(let x=0;x<W;x+=12){
      const y=base+Math.sin(x*.005+TAU*(t+ph))*34+Math.sin(x*.013-TAU*t+ph*5)*12,a=.16+.22*(Math.sin(x*.021-TAU*t*2+ph*7)+1)/2;
      c.fillStyle=vgrad(c,y,y+depth,[[0,col,a*1.7],[.18,col,a],[1,col,0]]);c.fillRect(x,y,12,depth);}});
  }
  const SCENE={
    smoke:{inks:p=>[p.accent,p.secondary,'#fff6e8'],draw(c,p,t){
      dots(c,p.seed,65,p.secondary,t,{tw:0,a:.32});
    }},
    flow:{ramp:' .,:~+=o',gain:1.35,inks:p=>[p.secondary,'#d8ffff',p.accent,'#467a96','#e9e0d0','#dba96c','#ac6538','#71abb8','#b8d9d3','#345d74'],draw(c,p,t){
      c.globalCompositeOperation='lighter';
      glow(c,1010,350,410,p.secondary,.12);glow(c,930,120,250,p.accent,.08);
      dots(c,p.seed,70,p.secondary,t,{tw:0,a:.35});
    },cell(x,y,t,p){
      const w=water(x,y,t,p.seed%19),edge=Math.min(1,Math.abs(x-480)/540+.12),k=(w.light*.55+.035)*edge;
      return [80*k,190*k,220*k];
    }},
    dumb:{inks:p=>[p.accent,p.secondary,'#ffffff','#ffd166','#69f5ce'],draw(c,p,t){
      c.globalCompositeOperation='lighter';
      [[260,180,360,p.accent,.55,0],[880,430,420,p.secondary,.46,.3],[560,640,300,p.accent,.36,.6],[1060,110,280,p.secondary,.44,.8],[120,560,240,p.secondary,.36,.45]]
        .forEach(([x,y,r,col,a,ph])=>glow(c,x+wave(t,1,ph)*28,y+wave(t,1,ph+.25)*16,r,col,a));
      dots(c,p.seed,260,'#ffffff',t,{tw:.3,a:.85});
      const px=1074,py=560,ring=(a0,a1)=>{c.strokeStyle=rgba(p.accent,.85);c.lineWidth=7;c.beginPath();c.ellipse(px,py,98,20,-.22,a0,a1);c.stroke();};
      c.globalCompositeOperation='source-over';ring(Math.PI,TAU);
      const g=c.createRadialGradient(px-16,py-16,4,px,py,46);g.addColorStop(0,'#ffffff');g.addColorStop(.45,p.secondary);g.addColorStop(1,'#000000');c.fillStyle=g;c.beginPath();c.arc(px,py,46,0,TAU);c.fill();
      ring(0,Math.PI);
      const a=TAU*t,mx=px+Math.cos(a)*132,my=py+Math.sin(a)*30;if(Math.sin(a)>=0||Math.hypot(mx-px,my-py)>48){c.fillStyle='#ffffff';c.beginPath();c.arc(mx,my,8,0,TAU);c.fill();}
      const u=(t*2+.3)%1;if(u<.22){const k=u/.22,x=180+k*720,y=30+k*170,gr=c.createLinearGradient(x-170,y-40,x,y);c.globalCompositeOperation='lighter';
        gr.addColorStop(0,rgba('#ffffff',0));gr.addColorStop(1,rgba('#ffffff',.95));c.strokeStyle=gr;c.lineWidth=7;c.beginPath();c.moveTo(x-170,y-40);c.lineTo(x,y);c.stroke();}
    }},
    windows:{inks:p=>['#ffffff','#ffff55','#c0c0c0','#55ffff'],draw(c,p,t){ // starfield screensaver
      const r=rng(p.seed^0x77);c.globalCompositeOperation='lighter';
      for(let i=0;i<320;i++){const ang=r()*TAU,sp=1+Math.floor(r()*2),z=(r()+t*sp)%1,d=16+z*z*z*780,x=600+Math.cos(ang)*d*1.4,y=338+Math.sin(ang)*d*.8,
        col=i%9===0?'#ffff55':i%13===0?'#55ffff':'#ffffff',sz=.5+z*1.5,tail=d*.14*z;
        c.strokeStyle=rgba(col,z*1.3);c.lineWidth=4*sz;c.beginPath();c.moveTo(x,y);c.lineTo(x-Math.cos(ang)*tail*1.4,y-Math.sin(ang)*tail*.8);c.stroke();
        c.fillStyle=rgba(col,z*1.6);c.fillRect(x-3*sz,y-4.5*sz,6*sz,9*sz);}
    }},
    mac:{inks:p=>['#ff6fb5','#c86bff','#6f7bff','#5ac8fa','#ffb86b','#ffffff'],gain:1.1,draw(c,p,t){ // flowing wallpaper ribbons
      c.globalCompositeOperation='lighter';
      ['#ff6fb5','#c86bff','#6f7bff','#5ac8fa','#ffb86b','#ff5f57'].forEach((col,k)=>{c.beginPath();c.moveTo(0,H);
        for(let x=0;x<=W;x+=12)c.lineTo(x,70+k*92+Math.sin(x*.004+k*.9+TAU*t)*46+Math.sin(x*.011-TAU*t*2+k)*14);
        c.lineTo(W,H);c.closePath();c.fillStyle=vgrad(c,30+k*92,250+k*92,[[0,col,.55],[1,col,0]]);c.fill();});
    }},
    nvidia:{ramp:' .:-=+*01#',inks:p=>['#76b900','#b6ff3b','#d8ff9c','#3f6f00'],draw(c,p,t){ // circuit pulses + data rain
      const r=rng(p.seed^0x91),paths=[];c.globalCompositeOperation='lighter';
      for(let i=0;i<30;i++){let x=Math.round(r()*W/24)*24,y=Math.round(r()*H/18)*18;const pts=[[x,y]];
        for(let k=0;k<5;k++){if(r()<.5)x+=(r()<.5?-1:1)*24*(1+Math.floor(r()*5));else y+=(r()<.5?-1:1)*18*(1+Math.floor(r()*4));pts.push([x,y]);}paths.push(pts);}
      c.strokeStyle=rgba('#76b900',.42);c.lineWidth=5;
      paths.forEach(pts=>{c.beginPath();pts.forEach(([x,y],i)=>i?c.lineTo(x,y):c.moveTo(x,y));c.stroke();const [ex,ey]=pts[pts.length-1];c.fillStyle=rgba('#b6ff3b',.7);c.fillRect(ex-6,ey-9,12,18);});
      paths.forEach((pts,i)=>{const [x,y]=along(pts,(t*(1+i%2)+i*.137)%1);glow(c,x,y,22,'#d8ff9c',.95);});
      for(let col=0;col<COLS;col++){const h=hash('rain'+col+':'+p.seed);if(h%4)continue;
        const sp=1+(h>>3)%2,len=90+(h>>5)%180,ph=((h>>8)%1000)/1000,head=((t*sp+ph)%1)*(H+len+40)-20;
        const g=c.createLinearGradient(0,head-len,0,head);g.addColorStop(0,rgba('#76b900',0));g.addColorStop(1,rgba('#76b900',.75));
        c.fillStyle=g;c.fillRect(col*CW,head-len,CW,len);c.fillStyle='#d8ff9c';c.fillRect(col*CW,Math.floor(head/CH)*CH-CH,CW,CH);}
    }},
    t3:{inks:p=>[p.accent,p.secondary,'#ffffff','#5ac8fa'],draw(c,p,t){ // aurora + scanline
      c.globalCompositeOperation='lighter';
      curtains(c,t,[[p.accent,0,60],[p.secondary,.33,110],['#5ac8fa',.66,160]],240);
      const y=t*(H+80)-40;c.fillStyle=vgrad(c,y-30,y+30,[[0,'#ffffff',0],[.5,'#ffffff',.35],[1,'#ffffff',0]]);c.fillRect(0,y-30,W,60);
      c.fillStyle=rgba('#ffffff',.16);for(let x=72;x<W;x+=48)for(let yy=72;yy<H;yy+=45)cell(c,x,yy);
    }},
    dog:{inks:p=>['#ffcc55','#ffffff','#7fd3ff','#3f9a4a','#9be15d','#ff8fa3'],draw(c,p,t){ // sunny park
      c.globalCompositeOperation='lighter';
      c.fillStyle=vgrad(c,0,H,[[0,'#7fd3ff',.13],[.7,'#7fd3ff',.04],[1,'#7fd3ff',0]]);c.fillRect(0,0,W,H);
      const sx=1080,sy=82;glow(c,sx,sy,150,'#ffcc55',.5);c.strokeStyle=rgba('#ffcc55',.75);c.lineWidth=5;
      for(let i=0;i<12;i++){const a=i/12*TAU+t*TAU/3,l=78+(i%2)*22;c.beginPath();c.moveTo(sx+Math.cos(a)*46,sy+Math.sin(a)*46);c.lineTo(sx+Math.cos(a)*l,sy+Math.sin(a)*l);c.stroke();}
      c.fillStyle='#ffdd77';c.beginPath();c.arc(sx,sy,32,0,TAU);c.fill();
      const r=rng(p.seed^0x33);for(let i=0;i<4;i++){const y=60+r()*140,ph=r(),sc=.7+r()*.6,x=((ph+t)%1)*(W+360)-180;
        [[0,0,34],[30,-12,30],[60,0,36],[90,4,26],[-28,6,24]].forEach(([dx,dy,rr])=>glow(c,x+dx*sc,y+dy*sc,rr*sc*1.4,'#ffffff',.26));}
      c.globalCompositeOperation='source-over';
      ridge(c,H-150,40,p.seed^5,vgrad(c,H-200,H,[[0,'#9be15d',.55],[1,'#3f9a4a',.22]]));
      ridge(c,H-80,26,p.seed^9,vgrad(c,H-110,H,[[0,'#9be15d',.8],[1,'#3f9a4a',.4]]));
      c.globalCompositeOperation='lighter';c.strokeStyle=rgba('#9be15d',.8);c.lineWidth=3;
      for(let x=0;x<W;x+=9){const h=8+hash('g'+x)%14,sw=wave(t,1,x*.0021)*6;c.beginPath();c.moveTo(x,H-28);c.quadraticCurveTo(x,H-28-h*.6,x+sw,H-28-h);c.stroke();}
      for(let i=0;i<26;i++){c.fillStyle=['#ff8fa3','#ffffff','#ffcc55'][i%3];cell(c,hash('f'+i+p.seed)%W,H-64+hash('fy'+i)%34);}
    }},
    cat:{inks:p=>['#ffd166','#c49bff','#fff6c8','#ffffff','#7a6aa8'],draw(c,p,t){ // night skyline
      c.globalCompositeOperation='lighter';
      c.fillStyle=vgrad(c,0,H,[[0,'#c49bff',0],[1,'#c49bff',.2]]);c.fillRect(0,0,W,H);
      dots(c,p.seed,170,'#ffffff',t,{y1:H*.62,tw:.35,a:.8});
      glow(c,1100,96,150,'#fff6c8',.35);c.globalCompositeOperation='source-over';
      c.fillStyle='#fff6c8';c.beginPath();c.arc(1100,96,32,0,TAU);c.fill();c.fillStyle='#000';c.beginPath();c.arc(1114,86,28,0,TAU);c.fill();
      const r=rng(p.seed^0x44);let x=-10,b=0;
      while(x<W){const w=48+Math.floor(r()*5)*12,h=90+Math.floor(r()*9)*22,top=H-h;
        c.fillStyle='#000';c.fillRect(x,top,w,h);c.fillStyle=rgba('#7a6aa8',.16);c.fillRect(x,top,w,h);c.fillStyle=rgba('#c49bff',.55);c.fillRect(x,top,w,4);
        if(r()<.35){c.fillRect(x+w/2,top-30,4,30);c.fillStyle=Math.floor(t*4)%2?'#ff5f57':'#000';cell(c,x+w/2,top-34);}
        for(let wy=top+12;wy<H-16;wy+=18)for(let wx=x+8;wx<x+w-8;wx+=12){const h2=hash(b+','+wx+','+wy);
          const lit=h2%3===0||(h2%11===1&&(Math.floor(t*4)+h2)%4<2);if(!lit)continue;c.fillStyle=h2%5?'#ffd166':'#fff6c8';c.globalAlpha=.55+(h2%7)/14;cell(c,wx,wy);c.globalAlpha=1;}
        x+=w+Math.floor(r()*3)*6;b++;}
    }},
    fish:{ramp:' .,-~:=+oO@',inks:p=>['#5ce1ff','#ffffff','#2fbf71','#d7c38a','#ff8a5c','#1d6fa3'],draw(c,p,t){ // caustics, rays, kelp, bubbles
      c.globalCompositeOperation='lighter';
      c.fillStyle=vgrad(c,0,H,[[0,'#5ce1ff',.3],[.5,'#1d6fa3',.12],[1,'#1d6fa3',0]]);c.fillRect(0,0,W,H);
      for(let i=0;i<6;i++){const x=120+i*200+wave(t,1,i*.17)*40;c.fillStyle=vgrad(c,0,H,[[0,'#ffffff',.16],[1,'#ffffff',0]]);
        c.beginPath();c.moveTo(x-30,0);c.lineTo(x+30,0);c.lineTo(x+160,H);c.lineTo(x+60,H);c.closePath();c.fill();}
      const r=rng(p.seed^0x55);
      for(let i=0;i<12;i++){const bx=r()*W,len=140+r()*200,ph=r();c.strokeStyle=rgba('#2fbf71',.78);c.lineWidth=8+r()*6;c.beginPath();c.moveTo(bx,H-16);
        for(let k=1;k<=10;k++)c.lineTo(bx+Math.sin(TAU*(t+ph)+k*.5)*k*2.2,H-16-len*k/10);c.stroke();}
      c.fillStyle=vgrad(c,H-40,H,[[0,'#d7c38a',.3],[1,'#d7c38a',.7]]);c.fillRect(0,H-40,W,40);
      c.strokeStyle=rgba('#ffffff',.85);c.lineWidth=2.5;
      for(let i=0;i<46;i++){const x0=r()*W,sp=1+Math.floor(r()*2),ph=r(),rr=3+r()*5,y=H-((t*sp+ph)%1)*(H+40);c.beginPath();c.arc(x0+wave(t,2,ph)*8,y,rr,0,TAU);c.stroke();}
    },cell(x,y,t){if(y>270)return null;const v=Math.sin(x*.021+TAU*t)+Math.sin(y*.05-TAU*t)+Math.sin((x*.7+y)*.017+TAU*2*t),k=Math.max(0,v-1.5)*(1-y/270)*230;return k?[k*.6,k,k]:null;}},
    shark:{ramp:' .,-~:=+oO@',inks:p=>['#5cc8ff','#ffffff','#9fd8ff','#ff4f6d','#3d6f9a'],draw(c,p,t){ // deep water + passing shadow
      c.globalCompositeOperation='lighter';
      c.fillStyle=vgrad(c,0,H,[[0,'#5cc8ff',.34],[.6,'#5cc8ff',.05],[1,'#5cc8ff',0]]);c.fillRect(0,0,W,H);
      for(let i=0;i<7;i++){const x=80+i*170+wave(t,1,i*.21)*50;c.fillStyle=vgrad(c,0,H,[[0,'#9fd8ff',.2],[1,'#9fd8ff',0]]);
        c.beginPath();c.moveTo(x-24,0);c.lineTo(x+24,0);c.lineTo(x-60,H);c.lineTo(x-150,H);c.closePath();c.fill();}
      c.strokeStyle=rgba('#ffffff',.85);c.lineWidth=5;c.beginPath();
      for(let x=0;x<=W;x+=10){const y=16+Math.sin(x*.025+TAU*t*2)*6+Math.sin(x*.06-TAU*t*3)*3;x?c.lineTo(x,y):c.moveTo(x,y);}c.stroke();
      dots(c,p.seed,30,'#ffffff',t,{y0:30,tw:0,a:.5});
      const r=rng(p.seed^0x5a);c.fillStyle='#ffffff';
      for(let i=0;i<120;i++){const x=r()*W,ph=r(),y=((t+ph)%1)*(H+20)-10,a=.25+r()*.5;c.globalAlpha=a;cell(c,x+wave(t,1,ph)*10,y);}c.globalAlpha=1;
      const sx=-420+t*(W+840),sy=572+Math.sin(TAU*t)*12,wig=wave(t,6)*14;c.globalCompositeOperation='source-over';c.fillStyle=vgrad(c,sy-84,sy+66,[[0,'#9fd8ff',.8],[1,'#3d6f9a',.6]]);c.beginPath();
      c.ellipse(sx,sy,150,28,0,0,TAU);c.moveTo(sx-10,sy-24);c.lineTo(sx-60,sy-84);c.lineTo(sx+40,sy-24);
      c.moveTo(sx-140,sy);c.lineTo(sx-230,sy-58+wig);c.lineTo(sx-200,sy);c.lineTo(sx-230,sy+46+wig);c.closePath();
      c.moveTo(sx+10,sy+20);c.lineTo(sx-40,sy+66);c.lineTo(sx-10,sy+20);c.fill();
      c.fillStyle='#000';cell(c,sx+104,sy-8);
    }},
    penguin:{ramp:" .'`*+=x%#@",inks:p=>['#ffffff','#9fe8ff','#50fa9b','#c49bff','#ffcf3f'],draw(c,p,t){ // aurora, icebergs, snow
      c.globalCompositeOperation='lighter';
      dots(c,p.seed,90,'#ffffff',t,{y1:H*.55,tw:.3,a:.7});
      curtains(c,t,[['#50fa9b',0,60],['#9fe8ff',.3,92],['#c49bff',.6,124]],170);
      c.globalCompositeOperation='source-over';
      const r=rng(p.seed^0x66);for(let i=0;i<7;i++){const x=r()*W,w=60+r()*120,h=40+r()*90,b=H-38;
        c.fillStyle=vgrad(c,b-h,b,[[0,'#e8f4ff',.75],[1,'#9fc8ee',.3]]);c.beginPath();c.moveTo(x-w/2,b);c.lineTo(x-w*.2,b-h);c.lineTo(x+w*.15,b-h*.8);c.lineTo(x+w/2,b);c.closePath();c.fill();}
      c.fillStyle=vgrad(c,H-40,H,[[0,'#ffffff',.5],[1,'#9fc8ee',.3]]);c.fillRect(0,H-40,W,40);
      c.globalCompositeOperation='lighter';const s=rng(p.seed^0x67);c.fillStyle='#ffffff';
      for(let i=0;i<200;i++){const x0=s()*W,sp=1+Math.floor(s()*2),ph=s(),y=((t*sp+ph)%1)*(H+20)-10;c.globalAlpha=.35+s()*.6;cell(c,x0+wave(t,1,ph)*14,y);}c.globalAlpha=1;
    }},
    ohmypi:{ramp:' .,:;=+*π#@',inks:p=>[p.accent,p.secondary,'#ffffff','#50fa7b','#ff79c6'],draw(c,p,t){ // plasma + rotating spiral
      c.globalCompositeOperation='lighter';
      for(let i=0;i<190;i++){const a=i*.29+TAU*t,rr=24+i*3.1;c.fillStyle=i%2?p.accent:p.secondary;c.globalAlpha=i%5?.6:1;cell(c,980+Math.cos(a)*rr*1.25,330+Math.sin(a)*rr*.85);}
      c.globalAlpha=1;dots(c,p.seed,80,'#ffffff',t,{tw:.4,a:.6});
    },cell(x,y,t,p){
      const v=Math.sin(x*.011+TAU*t)+Math.sin(y*.019-TAU*t)+Math.sin(Math.hypot(x-980,y-330)*.016-TAU*t),k=Math.pow((v+3)/6,3)*.85;
      const A=p._a||(p._a=rgbOf(p.accent)),B=p._b||(p._b=rgbOf(p.secondary)),m=(Math.sin(x*.004-y*.003+TAU*t)+1)/2;
      return [(A[0]*m+B[0]*(1-m))*k,(A[1]*m+B[1]*(1-m))*k,(A[2]*m+B[2]*(1-m))*k];}},
    chill:{ramp:" .`'-~:+=*#",inks:p=>[p.accent,p.secondary,'#ffffff','#f6c177','#ff7eb6'],draw(c,p,t){ // retro sunset, bokeh, rain
      c.globalCompositeOperation='lighter';
      c.fillStyle=vgrad(c,0,H,[[0,p.secondary,.08],[.65,p.accent,.16],[1,'#f6c177',.16]]);c.fillRect(0,0,W,H);
      const sx=1000,sy=636;glow(c,sx,sy,280,'#f6c177',.16);
      c.save();c.beginPath();c.rect(0,0,W,sy);c.clip();c.globalCompositeOperation='source-over';
      c.fillStyle=vgrad(c,sy-110,sy,[[0,'#f6c177',.95],[1,'#ff7eb6',.9]]);c.beginPath();c.arc(sx,sy,110,0,TAU);c.fill();
      c.fillStyle='#000';for(let k=0;k<5;k++){const rel=((k+t*2)%5)/5;c.fillRect(sx-120,Math.floor((sy-rel*110)/CH)*CH,240,CH*(rel<.4?2:1));}c.restore();
      c.globalCompositeOperation='lighter';const r=rng(p.seed^0x71);
      for(let i=0;i<14;i++)glow(c,r()*W,r()*H*.8,18+r()*30,i%2?p.accent:p.secondary,.2+.1*wave(t,1,r()));
      c.strokeStyle=rgba('#ffffff',.4);c.lineWidth=2.5;
      for(let i=0;i<120;i++){const x0=r()*W,sp=1+Math.floor(r()*2),u=(t*sp+r())%1,x=x0+u*60,y=u*(H+80)-40;c.beginPath();c.moveTo(x,y);c.lineTo(x-10,y-42);c.stroke();}
      c.globalCompositeOperation='source-over';c.fillStyle='rgba(0,0,0,.75)';c.fillRect(0,H-38,W,38);
    }},
    nature:{ramp:" .,'`;:+*#%@",inks:p=>['#9be15d','#ffd166','#7bdcb5','#2f7a3a','#ffffff','#f78c6b','#eaff8a'],draw(c,p,t){ // ridges, mist, pines
      c.globalCompositeOperation='lighter';
      c.fillStyle=vgrad(c,0,H*.75,[[0,'#7bdcb5',.06],[1,'#ffd166',.3]]);c.fillRect(0,0,W,H);
      const sx=1090,sy=92;glow(c,sx,sy,170,'#ffd166',.55);c.strokeStyle=rgba('#ffd166',.5);c.lineWidth=4;
      for(let i=0;i<10;i++){const a=i/10*TAU+t*TAU/2;c.beginPath();c.moveTo(sx+Math.cos(a)*44,sy+Math.sin(a)*44);c.lineTo(sx+Math.cos(a)*(96+(i%2)*26),sy+Math.sin(a)*(96+(i%2)*26));c.stroke();}
      c.fillStyle='#fff3c0';c.beginPath();c.arc(sx,sy,30,0,TAU);c.fill();
      c.globalCompositeOperation='source-over';ridge(c,H-250,80,p.seed^1,vgrad(c,H-340,H,[[0,'#7bdcb5',.5],[1,'#7bdcb5',.12]]));
      c.globalCompositeOperation='lighter';for(let i=0;i<4;i++)glow(c,((i*.27+t)%1)*(W+400)-200,H-200+i*14,190,'#ffffff',.16);
      c.globalCompositeOperation='source-over';ridge(c,H-170,60,p.seed^2,vgrad(c,H-230,H,[[0,'#4fae6a',.6],[1,'#2f7a3a',.2]]));
      const r=rng(p.seed^3);for(let x=-10;x<W;x+=22+r()*26){const h=50+r()*90,b=H-30,w=h*.42;
        c.fillStyle=vgrad(c,b-h,b,[[0,'#9be15d',.8],[1,'#2f7a3a',.35]]);c.beginPath();c.moveTo(x,b-h);c.lineTo(x+w/2,b);c.lineTo(x-w/2,b);c.closePath();c.fill();}
      c.fillStyle=rgba('#2f7a3a',.5);c.fillRect(0,H-34,W,34);
      c.globalCompositeOperation='lighter';
      for(let i=0;i<28;i++){const x=r()*W,y=H-220+r()*160,ph=r();c.fillStyle='#eaff8a';c.globalAlpha=Math.max(0,wave(t,2,ph));cell(c,x+wave(t,1,ph)*10,y);}
      for(let i=0;i<22;i++){const x0=r()*W,ph=r(),y=((t+ph)%1)*(H+30)-15;c.fillStyle=['#9be15d','#ffd166','#f78c6b'][i%3];c.globalAlpha=.85;cell(c,x0+wave(t,1,ph)*30,y);}
      c.globalAlpha=1;
    }},
    beach:{ramp:' .,-~=+*o%#',inks:p=>['#ff9e64','#ffd166','#7dcfff','#ffffff','#ff6b9d','#e8c98a'],draw(c,p,t){ // sunset sea
      const hz=H-112;c.globalCompositeOperation='lighter';
      c.fillStyle=vgrad(c,0,hz,[[0,'#ff6b9d',.06],[.7,'#ff9e64',.16],[1,'#ffd166',.22]]);c.fillRect(0,0,W,hz);
      dots(c,p.seed,50,'#ffffff',t,{y1:200,a:.6});glow(c,1070,hz,230,'#ff9e64',.22);
      c.save();c.beginPath();c.rect(0,0,W,hz);c.clip();c.globalCompositeOperation='source-over';
      c.fillStyle=vgrad(c,hz-64,hz,[[0,'#ffd166',1],[1,'#ff6b9d',.95]]);c.beginPath();c.arc(1070,hz,64,0,TAU);c.fill();
      c.fillStyle='#000';for(let k=0;k<3;k++){const rel=((k+t*2)%3)/3;c.fillRect(990,Math.floor((hz-rel*64)/CH)*CH,160,CH);}c.restore();
      c.globalCompositeOperation='source-over';c.fillStyle=vgrad(c,hz,H-54,[[0,'#7dcfff',.35],[1,'#16345c',.25]]);c.fillRect(0,hz,W,58);
      c.globalCompositeOperation='lighter';c.lineWidth=2.5;
      for(let k=0;k<5;k++){const y=hz+6+k*11,dir=k%2?1:-1;c.strokeStyle=rgba('#ffffff',.22+k*.08);c.beginPath();for(let x=0;x<=W;x+=10){const yy=y+Math.sin(x*.03+TAU*t*dir+k)*3;x?c.lineTo(x,yy):c.moveTo(x,yy);}c.stroke();}
      const r=rng(p.seed^0x81);c.fillStyle='#ffd166';
      for(let i=0;i<64;i++){const yy=hz+2+r()*54,spread=30+(yy-hz)*2,x=1070+(r()-.5)*spread*2;c.globalAlpha=Math.max(0,wave(t,2+i%2,r()));cell(c,x,yy);}c.globalAlpha=1;
      c.globalCompositeOperation='source-over';c.fillStyle=vgrad(c,H-54,H,[[0,'#e8c98a',.32],[1,'#c9a86a',.2]]);c.fillRect(0,H-54,W,54);
      c.globalCompositeOperation='lighter';c.strokeStyle=rgba('#ffffff',.8);c.lineWidth=5;c.beginPath();
      for(let x=0;x<=W;x+=10){const y=H-54+wave(t,1)*5+Math.sin(x*.02+TAU*t)*2;x?c.lineTo(x,y):c.moveTo(x,y);}c.stroke();
    }},
    desert:{ramp:' .,`-~=+*%#',inks:p=>['#ffb347','#ffd57e','#e17055','#fff3e0','#c98a4b'],draw(c,p,t){ // dunes, haze, wind
      c.globalCompositeOperation='lighter';
      c.fillStyle=vgrad(c,0,H*.8,[[0,'#e17055',.06],[1,'#ffb347',.32]]);c.fillRect(0,0,W,H);
      const sx=1066,sy=108;glow(c,sx,sy,210,'#ffb347',.5);c.fillStyle='#ffd57e';c.beginPath();c.arc(sx,sy,44,0,TAU);c.fill();
      c.lineWidth=3;for(let k=0;k<3;k++){const u=(t+k/3)%1;c.strokeStyle=rgba('#ffd57e',(1-u)*.5);c.beginPath();c.arc(sx,sy,58+u*90,0,TAU);c.stroke();}
      c.globalCompositeOperation='source-over';
      ridge(c,H-200,50,p.seed^1,vgrad(c,H-260,H,[[0,'#ffd57e',.45],[1,'#c98a4b',.1]]));
      c.globalCompositeOperation='lighter';for(let k=0;k<3;k++){const y=H-236+k*16;c.fillStyle=vgrad(c,y-6,y+6,[[0,'#ffd57e',0],[.5,'#ffd57e',.12+.1*wave(t,1,k*.3)],[1,'#ffd57e',0]]);c.fillRect(0,y-6,W,12);}
      c.globalCompositeOperation='source-over';
      ridge(c,H-120,40,p.seed^2,vgrad(c,H-170,H,[[0,'#ffd57e',.6],[1,'#c98a4b',.2]]));
      ridge(c,H-50,26,p.seed^3,vgrad(c,H-80,H,[[0,'#fff3e0',.7],[1,'#c98a4b',.35]]));
      c.globalCompositeOperation='lighter';const r=rng(p.seed^0x99);c.fillStyle='#ffd57e';
      for(let i=0;i<70;i++){const ph=r(),y=H-200+r()*170,x=((t*(1+i%2)+ph)%1)*(W+40)-20;c.globalAlpha=.5+r()*.4;cell(c,x,y);}c.globalAlpha=1;
    }}
  };
  function maskGrid(p){
    // 1 = full scene, .2 = faint behind copy, 0 = blank (panel, window chrome, dock, composer).
    const L=box(p),m=new Float32Array(COLS*ROWS),k=p.key;
    for(let j=0;j<ROWS;j++)for(let i=0;i<COLS;i++){
      const x=i*CW+3,y=j*CH+4.5,inR=(x0,y0,x1,y1)=>x>=x0&&x<x1&&y>=y0&&y<y1;let w=1;
      if(inR(PANEL.x-14,PANEL.y-30,PANEL.x+PANEL.w+16,PANEL.y+PANEL.h+16))w=0;
      else if(inR(L.x-14,L.divider-8,744,L.label+48))w=k==='flow'||k==='smoke'?0:.2;
      else if(L.logo&&inR(L.x-8,L.logo-8,720,L.logo+40))w=.2;
      else if(L.tag&&inR(880,L.tag-6,1150,L.tag+22))w=.2;
      if(inR(0,L.ground-58,W,L.ground+6))w*=.55;
      if(k==='windows'&&!inR(22,56,W-22,H-56))w=0;
      if(k==='mac'){if(y<26||inR(24,36,W-24,72)||inR(W/2-230,H-82,W/2+230,H-6))w=0;else if(inR(24,36,W-24,H-84))w=Math.min(w,.5);}
      if(k==='t3'&&(y<38||x<42||inR(56,H-72,W-22,H-14)))w=0;
      m[j*COLS+i]=w;
    }
    return m;
  }
  function asciiLayer(p){
    const sc=SCENE[p.key]||SCENE.dumb,ramp=[...(sc.ramp||RAMP)],n=ramp.length,inks=sc.inks(p),mask=maskGrid(p),gain=sc.gain||1.9;
    const small=document.createElement('canvas');small.width=COLS;small.height=ROWS;const s=small.getContext('2d',{willReadFrequently:true});
    const atlas=document.createElement('canvas');atlas.width=n*CW;atlas.height=inks.length*CH;const a=atlas.getContext('2d');
    a.textBaseline='top';font(a,9,400);
    inks.forEach((ink,k)=>ramp.forEach((ch,i)=>{if(ch===' ')return;a.globalAlpha=.55+.45*i/(n-1);a.fillStyle=ink;a.fillText(ch,i*CW+.5,k*CH);}));
    const layer=document.createElement('canvas');layer.width=W;layer.height=H;const l=layer.getContext('2d');
    const norm=inks.map(hex=>{const [r,g,b]=rgbOf(hex),m=Math.max(r,g,b,1);return [r/m,g/m,b/m];});
    const state=new Int16Array(COLS*ROWS).fill(-1),jr=rng(p.seed^0x1234),jitter=Float32Array.from({length:COLS*ROWS},()=>(jr()-.5)*.14); // fixed grain breaks up flat bands
    return {canvas:layer,update(t){
      s.setTransform(1,0,0,1,0,0);s.globalCompositeOperation='source-over';s.globalAlpha=1;s.fillStyle='#000';s.fillRect(0,0,COLS,ROWS);
      s.setTransform(COLS/W,0,0,ROWS/H,0,0);s.save();sc.draw(s,p,t);s.restore();s.setTransform(1,0,0,1,0,0);
      const d=s.getImageData(0,0,COLS,ROWS).data;
      for(let j=0,q=0;j<ROWS;j++)for(let i=0;i<COLS;i++,q++){
        let code=0;
        if(mask[q]>0){
          let r=d[q*4],g=d[q*4+1],b=d[q*4+2];
          if(sc.cell){const e=sc.cell(i*CW+3,j*CH+4.5,t,p);if(e){r+=e[0];g+=e[1];b+=e[2];}}
          const lum=Math.max(0,Math.min(1,(.3*r+.59*g+.11*b)/255*gain+((r|g|b)>6?jitter[q]:0)))*mask[q],lv=Math.min(n-1,Math.floor(Math.pow(lum,.75)*n));
          if(lv>0){const m=Math.max(r,g,b,1),nr=r/m,ng=g/m,nb=b/m;let best=0,bd=9;
            for(let k=0;k<norm.length;k++){const z=norm[k],dd=(z[0]-nr)**2+(z[1]-ng)**2+(z[2]-nb)**2;if(dd<bd){bd=dd;best=k;}}
            code=best*n+lv;}
        }
        if(state[q]===code)continue;state[q]=code;
        const x=i*CW,y=j*CH;l.clearRect(x,y,CW,CH);
        if(code)l.drawImage(atlas,(code%n)*CW,Math.floor(code/n)*CH,CW,CH,x,y,CW,CH);
      }
    }};
  }
  function mascot(c,p,t,f,picture){
    const {key,accent,secondary}=p,{x,y,w,h}=PANEL;
    if(picture){ // tiny lookout on the panel corner
      const name=p.hero==='shark'?'fish':p.hero,fr=cast(name,-1)[Math.floor(f/6)%2];art(c,fr,x+w-80,y+h-14-fr.length*15+wave(t,2)*3,13,[accent,secondary]);return;
    }
    c.save();c.beginPath();c.rect(x+12,y+12,w-24,h-24);c.clip();
    if(key==='nvidia'){
      const spin=['|','/','-','\\'][f%4];
      art(c,['  .-------.','  |  '+spin+'  '+spin+'  |','  | '+spin+' () '+spin+' |','  |  '+spin+'  '+spin+'  |','  \'-------\''],x+60,y+60,22,accent);
      art(c,['FPS '+(240+Math.round(wave(t,3)*12)),'TEMP '+(61+Math.round(wave(t,1)*3))+'C'],x+70,y+210,16,'#d8ff9c');
    }else if(key==='ohmypi'){
      const lines=['$ omp','π read social_gif.js','π edit +5 themes','π bash render --all','✓ 15 vibes, 0 bugs','π ship it'],n=Math.floor(t*lines.length*1.2);
      lines.slice(0,Math.min(n+1,lines.length)).forEach((l,i)=>art(c,[l],x+28,y+30+i*34,16,i===n?accent:i===0?secondary:'#cfc6e6'));
      art(c,cast('pi',1)[Math.floor(f/6)%2],x+w-130,y+h-90+wave(t,2)*4,15,[accent,secondary]);
    }else if(key==='chill'){
      art(c,cast('mug',1)[Math.floor(f/12)%2],x+60,y+90+wave(t,1)*3,22,[secondary,secondary,accent,accent,accent,accent]);
      art(c,['  /\\_/\\','=( -.- )= zz','  (    )~'],x+190,y+150+wave(t,1,.3)*2,18,p.theme.body);
      art(c,['now playing:','lofi beats to ship to'],x+30,y+30,14,p.theme.body,.85);
    }else if(key==='t3'){
      const lines=['◆ reading web/social.js','◆ drawing ascii critters','◆ encoding gif89a','✓ loop is seamless','◆ greg is watching'],n=Math.floor(t*lines.length*1.25);
      lines.slice(0,Math.min(n+1,lines.length)).forEach((l,i)=>art(c,[l],x+28,y+34+i*32,15,i===n?accent:'#b8b8cc'));
    }else{
      const hero=cast(p.hero,1)[Math.floor(f/6)%2],size=hero[0].length>12||hero.length>4?20:28;
      font(c,size);const tw=Math.max(...hero.map(l=>c.measureText(l).width));
      art(c,hero,x+(w-tw)/2+wave(t,1)*24,y+(h-hero.length*size*1.08)/2+wave(t,2,.25)*8,size,[accent,secondary]);
      art(c,['* . +'],x+30+wave(t,1,.5)*10,y+30,14,secondary,.6+.4*wave(t,3));
    }
    c.restore();
  }
  // Original koi silhouettes, sampled through water normals onto a fixed dot grid.
  // The artwork never touches a user's work picture or its flattened privacy masks.
  const BAYER=[0,8,2,10,12,4,14,6,3,11,1,9,15,7,13,5];
  function koi(c,t,cool){
    const tail=Math.sin(TAU*t*3)*9;
    c.fillStyle=cool?'#82b8c1':'#b36b3b';
    c.beginPath();c.moveTo(-27,0);c.bezierCurveTo(-44,-6,-54,-19+tail,-68,-21+tail);
    c.quadraticCurveTo(-62,tail,-68,22+tail);c.bezierCurveTo(-50,19+tail,-38,6,-27,0);c.fill();
    c.fillStyle=cool?'#bfdfdd':'#edb779';
    c.beginPath();c.moveTo(8,-10);c.quadraticCurveTo(-14,-37,-26,-25);c.lineTo(-15,-6);c.fill();
    c.beginPath();c.moveTo(8,10);c.quadraticCurveTo(-13,36,-26,26);c.lineTo(-15,6);c.fill();
    c.save();c.beginPath();c.moveTo(44,0);c.bezierCurveTo(38,-19,8,-26,-16,-15);
    c.quadraticCurveTo(-28,-7,-34,0);c.quadraticCurveTo(-28,7,-16,15);c.bezierCurveTo(8,26,38,19,44,0);c.closePath();
    const g=c.createLinearGradient(0,-20,0,20);g.addColorStop(0,cool?'#90c1c4':'#f7cf99');g.addColorStop(.4,'#fff4db');g.addColorStop(1,cool?'#61949e':'#b56436');
    c.fillStyle=g;c.fill();c.clip();
    c.fillStyle=cool?'#cc6c3d':'#ee8c40';
    [[25,-6,11,10],[-5,7,13,10],[-23,-8,8,8]].forEach(([x,y,rx,ry])=>{c.beginPath();c.ellipse(x,y,rx,ry,.4,0,TAU);c.fill();});
    c.strokeStyle=cool?'#385967':'#794224';c.globalAlpha=.38;c.lineWidth=.7;
    for(let x=-22;x<26;x+=7)for(let y=-15;y<19;y+=7){c.beginPath();c.arc(x+(y%2)*2,y,4,-1.2,1.2);c.stroke();}
    c.restore();c.fillStyle='#0b161e';for(const y of [-7,7]){c.beginPath();c.arc(33,y,2,0,TAU);c.fill();}
  }
  function pond(p){
    const w=PANEL.w-24,h=PANEL.h-24,source=document.createElement('canvas');source.width=w;source.height=h;
    const s=source.getContext('2d',{willReadFrequently:true}),phase=p.seed%19;
    return {draw(c,t){
      s.clearRect(0,0,w,h);
      for(let k=0;k<2;k++){
        const a=TAU*t+k*Math.PI,rx=76,ry=62;
        s.save();s.translate(w/2+Math.cos(a)*rx,h/2+Math.sin(a)*ry);
        s.rotate(Math.atan2(ry*Math.cos(a),-rx*Math.sin(a)));koi(s,t+k/2,k===1);s.restore();
      }
      const pixels=s.getImageData(0,0,w,h).data;
      c.save();c.beginPath();c.rect(PANEL.x+12,PANEL.y+12,w,h);c.clip();c.translate(PANEL.x+12,PANEL.y+12);
      // A fixed Bayer coverage pattern avoids fresh random grain on every frame.
      for(let y=2,j=0;y<h;y+=4,j++)for(let x=2,i=0;x<w;x+=4,i++){
        const f=water(x,y,t,phase),sx=Math.round(x+f.dx),sy=Math.round(y+f.dy);
        let r=0,g=0,b=0,alpha=0;
        if(sx>=0&&sx<w&&sy>=0&&sy<h){const q=(sy*w+sx)*4;r=pixels[q];g=pixels[q+1];b=pixels[q+2];alpha=pixels[q+3]/255;}
        const threshold=(BAYER[(j%4)*4+i%4]+.5)/16;
        if(alpha>threshold){
          const light=1+f.light*.2,lum=(r+g+b)/765;
          c.fillStyle=`rgb(${Math.min(255,Math.round(r*light))},${Math.min(255,Math.round(g*light))},${Math.min(255,Math.round(b*light))})`;
          c.beginPath();c.arc(x,y,lum>.72?1.65:lum>.42?1.4:1.1,0,TAU);c.fill();
        }else if(f.light>.12+threshold*.6){
          c.fillStyle=rgba(p.secondary,.1+f.light*.25);c.fillRect(x-1,y-1,2,2);
        }
      }
      // Fine specular crests move across the dots like transparent glass.
      for(let k=0;k<4;k++){
        const y0=h*(k+.5)/4+Math.sin(TAU*t+k)*18;
        for(const [width,alpha] of [[7,.025],[2,.1],[.65,.25]]){
          c.lineWidth=width;c.strokeStyle=rgba('#d8ffff',alpha);c.beginPath();
          for(let x=-10;x<=w+10;x+=5){const y=y0+Math.sin(x*.019+TAU*t+k)*14+Math.sin(x*.041-TAU*t*2)*4;x===-10?c.moveTo(x,y):c.lineTo(x,y);}c.stroke();
        }
      }
      c.restore();
    }};
  }
  const SWARM={dumb:['*','*'],windows:['▪','▪'],mac:['⌘','⌘'],nvidia:['01','10'],t3:['◆','◆'],dog:['v','v'],cat:['^v^','^v^'],fish:['><>','<><'],shark:['><>','<><'],
    penguin:['v','v'],ohmypi:['π','π'],chill:['♪','♫'],nature:['v','v'],beach:['v','v'],desert:['v','v']};
  function lanes(c,p,t,f){
    const {accent,secondary,theme}=p,{ground,sky,divider}=box(p);
    p.walkers.forEach((wk,i)=>{
      const frames=cast(wk.name,wk.dir),fr=frames[Math.floor(f/[4,6,8,6][i])%2]; // gait alternates
      const S=i===3?10:12;font(c,S);const span=Math.max(...fr.map(l=>c.measureText(l).width))+20,u=(t*wk.laps+wk.phase)%1;
      const x=wk.dir>0?-span+u*(W+span*2):W+span-u*(W+span*2),hop=wk.name==='bunny'||wk.name==='frog'?Math.abs(wave(t,wk.laps*6,wk.phase))*8:0;
      art(c,fr,x,ground-fr.length*Math.round(S*1.08)-hop,S,i%2?[secondary,accent]:[accent,secondary],.95);
    });
    p.flyers.forEach((fl,i)=>{
      const fr=cast(fl.name,fl.dir)[Math.floor(f/3)%2];font(c,11);const span=c.measureText(fr[0]).width+20,u=(t*fl.laps+fl.phase)%1;
      const x=fl.dir>0?-span+u*(W+span*2):W+span-u*(W+span*2);
      art(c,fr,x,sky+i*12+wave(t,2*fl.laps,fl.bob/TAU)*4,11,i?secondary:theme.body,.9);
    });
    // A small flock trails across the sky band once per loop.
    const sw=SWARM[p.key]||SWARM.dumb,r=rng(p.seed^0xabc),dir=r()<.5?1:-1,phase=r(),g=sw[dir>0?0:1],band=Math.max(14,divider-sky-16),u=(t+phase)%1;
    for(let i=0;i<9;i++){const lag=i*26+r()*14,dy=r()*band,x=dir>0?-40+u*(W+300)-lag:W+40-u*(W+300)+lag;
      art(c,[g],x,sky+2+dy+wave(t,2,i*.13)*3,10,[accent,secondary,theme.body][i%3],.9);}
  }
  function greg(c,p,t,f){
    // Rises out of the bottom-right, waves, sinks back before the loop restarts.
    const start=p.greg,len=40,k=(f-start+FRAMES)%FRAMES;if(k>=len)return;
    const rise=Math.min(1,k/8,(len-k)/8),x=1010,y=H-rise*150;
    const arms=Math.floor(k/4)%2?'\\o/':'_o_',ink=p.theme.ink;
    art(c,['  .---.','  |o o|','  | - |','  \\___/',arms.split('').join('  ').padStart(9),'    |'],x,y,15,[ink,ink,ink,ink,p.accent,ink],1);
    if(k>8&&k<len-8){const say=pick(rng(p.seed+7),['hi it’s greg','greg approves','ship it -greg','greg was here']);font(c,14);const bw=c.measureText(say).width+20;
      c.fillStyle='#ffffff';rounded(c,x-bw-8,y-6,bw,30,8);c.fill();c.beginPath();c.moveTo(x-14,y+8);c.lineTo(x+2,y+14);c.lineTo(x-14,y+18);c.fill();c.fillStyle='#090a12';c.fillText(say,x-bw+2,y+2);}
  }
  function lightning(c,p,f){
    const k=(f-p.bolt.at+FRAMES)%FRAMES;if(k>5)return;
    const r=rng(p.bolt.seed);let x=p.bolt.x,y=0;const pts=[[x,y]];
    while(y<H*.75){y+=18+r()*26;x+=(r()-.5)*60;pts.push([x,y]);}
    if(k<=2){
      if(k===0){c.fillStyle='#ffffff';c.globalAlpha=.2;c.fillRect(0,0,W,H);c.globalAlpha=1;}
      c.save();c.shadowColor=p.secondary;c.shadowBlur=18;font(c,20);c.fillStyle=k===1?p.secondary:'#ffffff';
      for(let i=1;i<pts.length;i++){const [ax,ay]=pts[i-1],[bx,by]=pts[i],n=Math.ceil(Math.hypot(bx-ax,by-ay)/14),g=bx>ax?'\\':'/';
        for(let s=0;s<n;s++)c.fillText(Math.abs(bx-ax)<6?'|':g,ax+(bx-ax)*s/n,ay+(by-ay)*s/n);}
      c.restore();
    }
    const [ex,ey]=pts[pts.length-1];
    for(let i=0;i<8;i++){const a=i/8*TAU,d=8+k*10;art(c,[k<3?'*':'+'],ex+Math.cos(a)*d,ey+Math.sin(a)*d*.6,14,p.accent,1-k/6);}
    art(c,['ZAP!'],ex-20,ey-36-k*4,22,'#ffffff',1-k/6);
  }
  function flicker(c,p,f){
    const k=(f-p.flick+FRAMES)%FRAMES;if(![0,1,3,6].includes(k))return;
    c.fillStyle='#000000';c.globalAlpha=k===3?.25:.5;c.fillRect(0,0,W,H);c.globalAlpha=1;
  }

  // ---------- GIF89a encoder ----------
  function palette(p){
    const colors=[[0,0,0]],seen=new Set(),add=hex=>{const v=parseInt(hex.slice(1,7),16),rgb=[v>>16,v>>8&255,v&255],key=rgb.join();if(!seen.has(key)&&colors.length<256){seen.add(key);colors.push(rgb);}};
    const t=p.theme;[t.bg,t.ink,t.body,t.dim,p.accent,p.secondary,...(SCENE[p.key]||SCENE.dumb).inks(p),'#ffffff','#000000','#090a12','#c0c0c0','#808080','#000080','#12131f','#080910','#fff6c8','#2fbf71','#ff5f57','#febc2e','#28c840','#76b900','#d8ff9c'].forEach(add);
    for(const r of [0,51,102,153,204,255])for(const g of [0,51,102,153,204,255])for(const b of [0,51,102,153,204,255])add('#'+[r,g,b].map(v=>v.toString(16).padStart(2,'0')).join(''));
    for(let v=8;colors.length<256;v+=10)add('#'+[v,v,v].map(n=>Math.min(255,n).toString(16).padStart(2,'0')).join(''));
    // Fill remaining slots with tints between theme colors so gradients hold up.
    while(colors.length<256)colors.push([0,0,0]);
    return colors;
  }
  function quantizer(colors){
    const lut=new Int16Array(32768).fill(-1);
    return (data,out)=>{
      for(let i=0,j=0;j<out.length;i+=4,j++){
        const key=(data[i]>>3)<<10|(data[i+1]>>3)<<5|data[i+2]>>3;let v=lut[key];
        if(v<0){const r=(key>>10)*8+4,g=(key>>5&31)*8+4,b=(key&31)*8+4;let best=1,bd=1e9;
          for(let k=1;k<colors.length;k++){const c=colors[k],d=(c[0]-r)**2*3+(c[1]-g)**2*4+(c[2]-b)**2*2;if(d<bd){bd=d;best=k;}}
          v=lut[key]=best;}
        out[j]=v;
      }
    };
  }
  const dict=new Int16Array(4096*256);
  function lzw(pixels,bytes){
    let cur=0,bits=0,size=9,next=258;const used=[];
    const push=code=>{cur|=code<<bits;bits+=size;while(bits>=8){bytes.push(cur&255);cur>>>=8;bits-=8;}};
    push(256);let prefix=pixels[0];
    for(let i=1;i<pixels.length;i++){
      const k=pixels[i],key=prefix<<8|k,code=dict[key];
      if(code){prefix=code;continue;}
      push(prefix);
      if(next===4096){push(256);size=9;next=258;for(const u of used)dict[u]=0;used.length=0;}
      else{if(next>=1<<size)size++;dict[key]=next++;used.push(key);}
      prefix=k;
    }
    push(prefix);push(257);if(bits>0)bytes.push(cur&255);
    for(const u of used)dict[u]=0;
  }
  class Bytes{constructor(){this.buf=new Uint8Array(1<<20);this.n=0;}push(b){if(this.n===this.buf.length){const x=new Uint8Array(this.buf.length*2);x.set(this.buf);this.buf=x;}this.buf[this.n++]=b;}
    word(v){this.push(v&255);this.push(v>>8&255);}str(s){for(const ch of s)this.push(ch.charCodeAt(0));}out(){return this.buf.subarray(0,this.n);}}
  function encoder(colors){
    const out=new Bytes();out.str('GIF89a');out.word(W);out.word(H);out.push(0xF7);out.push(0);out.push(0);
    colors.forEach(([r,g,b])=>{out.push(r);out.push(g);out.push(b);});
    out.push(0x21);out.push(0xFF);out.push(11);out.str('NETSCAPE2.0');out.push(3);out.push(1);out.word(0);out.push(0);
    const frames=[];
    return {
      frame(pixels,prev,delay){
        let x0=0,y0=0,x1=W-1,y1=H-1;
        if(prev){
          x0=W;y0=H;x1=-1;y1=-1;
          for(let y=0;y<H;y++){const row=y*W;for(let x=0;x<W;x++)if(pixels[row+x]!==prev[row+x]){if(x<x0)x0=x;if(x>x1)x1=x;if(y<y0)y0=y;y1=y;}}
          if(x1<0){if(frames.length)frames[frames.length-1].delay+=delay;return;}
        }
        const w=x1-x0+1,h=y1-y0+1,sub=new Uint8Array(w*h);
        for(let y=0;y<h;y++){const row=(y+y0)*W+x0;for(let x=0;x<w;x++){const v=pixels[row+x];sub[y*w+x]=prev&&v===prev[row+x]?0:v;}}
        frames.push({x0,y0,w,h,sub,delay});
      },
      finish(){
        for(const fr of frames){
          out.push(0x21);out.push(0xF9);out.push(4);out.push(1<<2|1);out.word(fr.delay);out.push(0);out.push(0);
          out.push(0x2C);out.word(fr.x0);out.word(fr.y0);out.word(fr.w);out.word(fr.h);out.push(0);
          out.push(8);const data=[];lzw(fr.sub,data);
          for(let i=0;i<data.length;i+=255){const n=Math.min(255,data.length-i);out.push(n);for(let j=0;j<n;j++)out.push(data[i+j]);}
          out.push(0);
        }
        out.push(0x3B);return out.out();
      }
    };
  }

  // ---------- public API ----------
  async function picture(uri){
    const m=/^data:image\/png;base64,([A-Za-z0-9+/=]+)$/.exec(uri||'');if(!m)return null;
    const raw=atob(m[1]),bytes=new Uint8Array(raw.length);for(let i=0;i<raw.length;i++)bytes[i]=raw.charCodeAt(i);
    try{return await createImageBitmap(new Blob([bytes],{type:'image/png'}));}catch{return null;}
  }
  const pause=()=>new Promise(r=>setTimeout(r,0));
  function smokeScene(p){
    const plume=DMAsciiSmoke.create({cols:96,rows:128,pitch:3,seed:p.seed,colors:['#65507d',p.secondary,'#ffdfba'],font:MONO});
    const layer=document.createElement('canvas');layer.width=W;layer.height=H;const l=layer.getContext('2d'),L=box(p);
    return {behind(c,t){
      l.clearRect(0,0,W,H);
      plume.draw(l,t,930,8,270,610,.72);plume.draw(l,t,720,414,320,380,.48);
      // Hard clearances preserve copy and flattened work-picture pixels exactly.
      l.clearRect(L.x-14,L.divider-8,744-(L.x-14),L.label+48-(L.divider-8));
      l.clearRect(PANEL.x-14,PANEL.y-30,PANEL.w+30,PANEL.h+50);
      l.clearRect(L.x-8,L.logo-8,720-(L.x-8),48);l.clearRect(865,L.tag-6,285,28);
      c.drawImage(layer,0,0);
    },hero(c,t){
      c.save();c.beginPath();c.rect(PANEL.x+12,PANEL.y+12,PANEL.w-24,PANEL.h-24);c.clip();
      plume.draw(c,t,PANEL.x+30,PANEL.y+6,PANEL.w-60,246);
      art(c,[' .-----.',' |     |]',' \\     /','  `---\''],PANEL.x+133,PANEL.y+220,19,[p.accent,p.secondary]);
      c.restore();
    }};
  }
  async function prepare({id,headline,summary,stage,project,image,brand},vibe=0,force={}){
    await Promise.all(['700 44px Bahnschrift','400 18px "Cascadia Mono"','700 18px "Cascadia Mono"'].map(f=>document.fonts?.load(f).catch(()=>{})));
    const p=plan(id||headline,vibe,force);FRAMES=p.theme.frames||72;DELAY=p.theme.delay||5;const pic=await picture(image),data={headline,summary,stage,project,brand};
    const base=document.createElement('canvas');base.width=W;base.height=H;const bc=base.getContext('2d');
    bc.textBaseline='top';backdrop(bc,p);
    const top=document.createElement('canvas');top.width=W;top.height=H;const tc=top.getContext('2d');
    const layout=copy(tc,p,data,pic);panel(tc,p,pic,data);
    const frame=document.createElement('canvas');frame.width=W;frame.height=H;const c=frame.getContext('2d',{willReadFrequently:true});
    const ascii=asciiLayer(p),flow=p.key==='flow'&&!pic?pond(p):null,smoke=p.key==='smoke'?smokeScene(p):null,frames=FRAMES,delay=DELAY;
    return {canvas:frame,layout,p,frames,delay,
      draw(t){
        FRAMES=frames;DELAY=delay;const f=Math.floor(t*frames);c.textBaseline='top';
        c.drawImage(base,0,0);ascii.update(t);c.drawImage(ascii.canvas,0,0);smoke?.behind(c,t);field(c,p,t);ambient(c,p,t,f);c.drawImage(top,0,0);
        if(smoke&&!pic)smoke.hero(c,t);else if(flow)flow.draw(c,t);else if(!['flow','smoke'].includes(p.key)||!pic)mascot(c,p,t,f,pic);lanes(c,p,t,f);
        if(p.events.includes('greg'))greg(c,p,t,f);
        if(p.events.includes('lightning'))lightning(c,p,f);
        if(p.events.includes('flicker'))flicker(c,p,f);
      },close(){pic?.close?.();FRAMES=72;DELAY=5;}};
  }
  async function make(data,vibe=0,cancelled=()=>false,force={}){
    const scene=await prepare(data,vibe,force),{p,frames,delay,canvas}=scene;
    const c=canvas.getContext('2d'),colors=palette(p),quantize=quantizer(colors),gif=encoder(colors);let prev=null;
    try{
      for(let f=0;f<frames;f++){
        if(cancelled())return null;
        scene.draw(f/frames);
        const px=new Uint8Array(W*H);quantize(c.getImageData(0,0,W,H).data,px);gif.frame(px,prev,delay);prev=px;
        if(f%4===3)await pause();
      }
      const blob=new Blob([gif.finish()],{type:'image/gif'});
      return {blob,theme:p.theme.name,key:p.key,events:p.events,frames,seconds:frames*delay/100,width:W,height:H};
    }finally{scene.close();}
  }
  return {make,prepare,plan,THEMES,size:{width:W,height:H}};
})();
