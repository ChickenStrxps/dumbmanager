'use strict';
// Background art: glyph-cell sharks, fine-dithered squid and vent smoke, reef life and a pixel planet.
// The background draws on two fixed canvases behind the app; a third overlay canvas
// shows short bursts for taps, stashes and wins. Everything pauses when motion is off,
// the tab is hidden, or the OS asks for reduced motion.
window.DMAquarium=(()=>{
  const sharkCanvas=document.getElementById('px-sharks'),planetCanvas=document.getElementById('px-planet'),fxCanvas=document.getElementById('px-fx');
  if(!sharkCanvas||!planetCanvas)return {};
  const reduced=matchMedia('(prefers-reduced-motion: reduce)');
  const ramp='.,:;+*xs%$#@';
  const ctx=sharkCanvas.getContext('2d'),mask=document.createElement('canvas'),mctx=mask.getContext('2d',{willReadFrequently:true});
  const pctx=planetCanvas.getContext('2d'),fctx=fxCanvas?.getContext('2d');
  if(!ctx||!mctx||!pctx){sharkCanvas.hidden=planetCanvas.hidden=true;if(fxCanvas)fxCanvas.hidden=true;return {};}
  let cell=10,cols=0,rows=0,floor=0,dpr=1,sharks=[],colors={},frame=0,last=0,time=0,ticks=0;
  let squidCache=null,smokeCache=null;

  const css=name=>getComputedStyle(document.body).getPropertyValue(name).trim();
  const hex=v=>{v=v.replace('#','');if(v.length===3)v=v.split('').map(c=>c+c).join('');const n=parseInt(v.slice(0,6),16);return [n>>16&255,n>>8&255,n&255];};
  const mix=(a,b,t)=>a.map((x,i)=>Math.round(x+(b[i]-x)*t));
  const rgb=(c,a=1)=>`rgba(${c[0]},${c[1]},${c[2]},${Math.max(0,Math.min(1,a))})`;
  const light=()=>document.body.classList.contains('light');
  const small=()=>innerWidth<760;
  const R=Math.random,pick=a=>a[R()*a.length|0];
  const moving=()=>!document.hidden&&!reduced.matches&&!document.body.classList.contains('no-motion')&&!document.body.classList.contains('drawer');

  function readColors(){
    colors={text:hex(css('--text')||'#eeedf5'),muted:hex(css('--muted')||'#8d8a9e'),pink:hex(css('--amber')||'#ff5cc8'),blue:hex(css('--accent2')||'#7c86ff'),deep:hex(css('--accent-deep')||'#8a1f6c'),bg:hex(css('--bg')||'#060608')};
    squidCache=null;smokeCache=null;
  }
  const font=(c,size=1.05)=>{c.font=`${Math.round(cell*size)}px Plex, ui-monospace, monospace`;c.textAlign='center';c.textBaseline='middle';};
  const glyph=(c,ch,x,y,color,a)=>{if(a<=.01)return;c.fillStyle=rgb(color,a);c.fillText(ch,x*cell+cell/2,y*cell+cell/2+.5);};

  // ---------- grain (blob URL: CSP allows blob: images, not data:) ----------
  function grain(){
    const g=document.createElement('canvas');g.width=g.height=180;const gx=g.getContext('2d');if(!gx)return;const img=gx.createImageData(180,180);
    for(let i=0;i<img.data.length;i+=4){const v=Math.random()*255|0;img.data[i]=img.data[i+1]=img.data[i+2]=v;img.data[i+3]=255;}
    gx.putImageData(img,0,0);
    g.toBlob(b=>{if(b)document.documentElement.style.setProperty('--grain',`url(${URL.createObjectURL(b)})`);});
  }

  // ---------- planet (continuous drift; bounded half-rate pixel rendering) ----------
  const bayer=[0,8,2,10,12,4,14,6,3,11,1,9,15,7,13,5].map(v=>(v+.5)/16);
  let planetImg=null,planetSpin=0,orbit={cx:0,cy:0,r:0,px:4};
  function planet(){
    const px=small()?3:4,W=Math.ceil(innerWidth/px),H=Math.ceil(innerHeight/px);
    if(planetCanvas.width!==W||planetCanvas.height!==H||!planetImg){planetCanvas.width=W;planetCanvas.height=H;planetImg=pctx.createImageData(W,H);}
    const d=planetImg.data;d.fill(0);
    const R0=Math.min(W,H)*(small()?.5:.36)*(1+.012*Math.sin(time*.85)),cx=W*.97+Math.sin(time*.28)*1.5,cy=H*1.1+Math.sin(time*.43)*2,alpha=light()?70:95;
    orbit={cx:cx*px,cy:cy*px,r:R0*px,px};
    const pal=[colors.deep,mix(colors.deep,colors.blue,.55),colors.blue,mix(colors.blue,colors.pink,.6),colors.pink];
    const lx=-.62+Math.sin(time*.24)*.12,ly=-.58,lz=.53,sp=planetSpin;
    for(let y=Math.max(0,Math.floor(cy-R0*1.12));y<H;y++)for(let x=Math.max(0,Math.floor(cx-R0*1.12));x<W;x++){
      const dx=(x-cx)/R0,dy=(y-cy)/R0,r2=dx*dx+dy*dy,th=bayer[(y&3)*4+(x&3)],o=(y*W+x)*4;
      if(r2<=1){
        const z=Math.sqrt(1-r2),l=Math.max(0,dx*lx+dy*ly+z*lz);
        // longitude-ish coordinate so the swirl drifts around the sphere
        const lon=Math.atan2(dx,z)+sp;
        const band=.5+.5*Math.sin(dy*11+Math.sin(lon*3+dy*3)*1.6+Math.sin(lon*5-dy*7+time*.45)*.22);
        const v=Math.min(.999,l*.82+band*.22-.05);
        const level=Math.floor(v*pal.length+th-.5);
        if(level<0){if(th>.35)continue;const c=pal[0];d[o]=c[0];d[o+1]=c[1];d[o+2]=c[2];d[o+3]=alpha*.5;continue;}
        const c=pal[Math.min(pal.length-1,level)];d[o]=c[0];d[o+1]=c[1];d[o+2]=c[2];d[o+3]=alpha;
      }else if(r2<1.1){
        const glow=1-(Math.sqrt(r2)-1)/.049;if(glow*.55<th)continue;
        const c=colors.pink;d[o]=c[0];d[o+1]=c[1];d[o+2]=c[2];d[o+3]=alpha*.45;
      }
    }
    let seed=7;const rnd=()=>(seed=(seed*16807)%2147483647)/2147483647;
    for(let i=0;i<Math.round(W*H/2600);i++){const x=rnd()*W|0,y=rnd()*H*.8|0,o=(y*W+x)*4;if(d[o+3])continue;const c=rnd()>.7?colors.pink:colors.muted;d[o]=c[0];d[o+1]=c[1];d[o+2]=c[2];d[o+3]=rnd()*90+40;}
    pctx.putImageData(planetImg,0,0);
  }

  // ---------- sharks ----------
  function makeShark(i,hammer){
    const len=small()?22:30+i*3,seg=1;
    const x=cols*(.15+.7*Math.random()),y=rows*(.15+.7*Math.random()),a=Math.random()*Math.PI*2;
    const joints=Array.from({length:len},(_,k)=>({x:x-Math.cos(a)*k*seg,y:y-Math.sin(a)*k*seg}));
    return {joints,seg,angle:a,speed:(small()?5:6.5)+Math.random()*2,turn:0,phase:Math.random()*9,hammer,width:small()?2.6:3.4,wander:Math.random()*100};
  }

  // ---------- squid: dense local glyphs, bounded cached poses ----------
  // A 2.2/2.5px grid is independent of the coarse reef grid. Only the current
  // poses are baked, once each: steady frames blend two atlas tiles, not thousands
  // of fillText calls. One 4x4 atlas is <=12.5MB desktop / 6.7MB phone at 1.5x.
  const squidFrames=16;
  function squidAtlas(){
    if(squidCache)return squidCache;
    const w=small()?80:96,h=small()?120:144,pitch=small()?2.2:2.5,ratio=Math.min(1.5,dpr);
    const sw=Math.ceil(w*pitch*ratio),sh=Math.ceil(h*pitch*ratio);
    const canvas=document.createElement('canvas');canvas.width=sw*4;canvas.height=sh*4;
    const ink=canvas.getContext('2d'),field=document.createElement('canvas');field.width=w;field.height=h;
    const shape=field.getContext('2d',{willReadFrequently:true});
    if(!ink||!shape)return null;
    squidCache={canvas,ink,shape,w,h,pitch,ratio,sw,sh,built:new Uint8Array(squidFrames)};
    return squidCache;
  }
  function squidPose(atlas,index){
    if(atlas.built[index])return;
    const {ink,shape,w,h,pitch,ratio,sw,sh}=atlas,phase=index/squidFrames*Math.PI*2;
    shape.setTransform(1,0,0,1,0,0);shape.clearRect(0,0,w,h);shape.scale(w/96,h/144);
    // Eight curling arms and two longer feeding tentacles.
    shape.lineCap='round';shape.lineJoin='round';
    for(let i=0;i<10;i++){
      const long=i===3||i===6,bx=32+i*32/9,ex=48+(i-4.5)*6.6+Math.sin(phase+i*.67)*7;
      const ey=long?134:109+(i%3)*5,wave=Math.sin(phase+i*.65)*8,curl=i<5?-1:1;
      shape.strokeStyle='rgba(255,255,255,.88)';shape.lineWidth=long?2:2.8;
      shape.beginPath();shape.moveTo(bx,71);shape.bezierCurveTo(bx+wave,88,ex-wave,ey-20,ex,ey);
      shape.quadraticCurveTo(ex+curl*7,ey+4,ex+curl*6,ey-4);shape.stroke();
      if(long){shape.fillStyle='rgba(255,255,255,.9)';shape.beginPath();shape.ellipse(ex+curl*6,ey-4,1.9,3.2,curl*.3,0,Math.PI*2);shape.fill();}
    }
    // Swept fins frame a pointed mantle, rather than a jellyfish bell.
    const fin=Math.sin(phase)*3;
    shape.fillStyle='rgba(255,255,255,.55)';
    for(const side of [-1,1]){
      shape.beginPath();shape.moveTo(48+side*7,20);shape.quadraticCurveTo(48+side*(29+fin),30,48+side*(31+fin),49);
      shape.quadraticCurveTo(48+side*18,47,48+side*13,55);shape.closePath();shape.fill();
    }
    const shade=shape.createLinearGradient(29,0,67,0);
    shade.addColorStop(0,'rgba(255,255,255,.25)');shade.addColorStop(.4,'rgba(255,255,255,1)');shade.addColorStop(1,'rgba(255,255,255,.3)');
    shape.fillStyle=shade;shape.beginPath();shape.moveTo(48,7);
    shape.bezierCurveTo(36,18,29,43,32,59);shape.bezierCurveTo(33,72,40,77,48,77);
    shape.bezierCurveTo(56,77,63,72,64,59);shape.bezierCurveTo(67,43,60,18,48,7);shape.fill();
    for(const x of [38,58]){
      shape.fillStyle='white';shape.beginPath();shape.ellipse(x,65,3.7,3.1,0,0,Math.PI*2);shape.fill();
      shape.globalCompositeOperation='destination-out';shape.beginPath();shape.ellipse(x,65.5,1.9,2.1,0,0,Math.PI*2);shape.fill();shape.globalCompositeOperation='source-over';
    }
    const pixels=shape.getImageData(0,0,w,h).data,ox=index%4*sw,oy=Math.floor(index/4)*sh;
    ink.setTransform(1,0,0,1,0,0);ink.clearRect(ox,oy,sw,sh);ink.setTransform(ratio,0,0,ratio,ox,oy);
    ink.font=`${pitch*1.65}px Plex, ui-monospace, monospace`;ink.textAlign='center';ink.textBaseline='middle';
    const palette=Array.from({length:12},(_,i)=>rgb(mix(colors.blue,colors.pink,i/11),light()?.72:.83));
    for(let y=0;y<h;y++)for(let x=0;x<w;x++){
      const a=pixels[(y*w+x)*4+3]/255;if(a<.08)continue;
      const texture=.84+.1*Math.sin(x*.71+y*.23)+.06*Math.cos(y*.53-x*.31);
      const v=Math.min(1,a*texture),threshold=bayer[(y&3)*4+(x&3)];
      if(v*1.5<threshold)continue;
      const tone=Math.min(11,Math.floor(v*9+threshold*2)),ch=ramp[Math.min(ramp.length-1,Math.floor(v*10+threshold*2))];
      ink.fillStyle=palette[tone];ink.fillText(ch,(x+.5)*pitch,(y+.5)*pitch);
    }
    atlas.built[index]=1;
  }
  function drawSquid(){
    const atlas=squidAtlas();if(!atlas)return;
    const {canvas,w,h,pitch,sw,sh}=atlas,phase=(time*1.55+.4)%(Math.PI*2)/Math.PI/2*squidFrames;
    const first=Math.floor(phase),next=(first+1)%squidFrames,blend=phase-first;
    squidPose(atlas,first);squidPose(atlas,next);
    const width=w*pitch,height=h*pitch,margin=width*.58;
    const x=Math.max(margin,Math.min(innerWidth-margin,innerWidth*(small()?.72:.81)+Math.sin(time*.19)*Math.min(80,innerWidth*.1)));
    const y=Math.max(height*.56,Math.min(floor*cell-height*.53,innerHeight*(small()?.62:.66)+Math.sin(time*.28+.5)*Math.min(65,innerHeight*.08)));
    ctx.save();ctx.translate(x,y);ctx.rotate(Math.sin(time*.35)*.12);
    for(const [index,alpha] of [[first,1-blend],[next,blend]]){
      if(alpha<.01)continue;ctx.globalAlpha=alpha*(light()?.65:.72);
      ctx.drawImage(canvas,index%4*sw,Math.floor(index/4)*sh,sw,sh,-width/2,-height/2,width,height);
    }
    ctx.restore();
  }

  // ---------- reef life ----------
  // Hydrothermal wisps share the cards' ordered-dither field. Only a small local
  // atlas is baked lazily; steady paints blend cached poses, with no new timer,
  // pixel readback or full-screen smoke grid. Existing pause rules govern both.
  function drawSmoke(){
    if(!window.DMAsciiSmoke)return;
    if(!smokeCache)smokeCache=DMAsciiSmoke.create({cols:small()?64:72,rows:small()?112:120,pitch:small()?2.3:2.4,ratio:Math.min(1.25,dpr),frames:small()?24:32,seed:803,
      colors:[rgbHex(mix(colors.deep,colors.blue,.3)),rgbHex(mix(colors.blue,colors.pink,.55)),rgbHex(mix(colors.muted,colors.text,.6))],font:'Plex, ui-monospace, monospace'});
    const t=time/7.68+.19,ground=floor*cell;
    const left=small()?innerWidth*.23-85:Math.max(260,innerWidth*.34)-115;
    smokeCache.draw(ctx,t,left,ground-(small()?340:440),small()?170:230,small()?365:470,light()?.21:.32);
    if(!small())smokeCache.draw(ctx,t+.5,innerWidth*.93-110,ground-395,220,435,light()?.17:.27);
  }
  const rgbHex=c=>'#'+c.map(v=>v.toString(16).padStart(2,'0')).join('');
  const life={dust:[],bubbles:[],kelp:[],schools:[],jelly:null,jellyIn:8,twinkles:[],pings:[],pingIn:6,moon:R()*6};
  const fx={rings:[],sparks:[],floaters:[],dirty:false};
  const pointer={x:-99,y:-99};
  let hype=0;
  const flip=s=>s.split('').reverse().map(c=>({'>':'<','<':'>','(':')',')':'(','{':'}','}':'{'}[c]||c)).join('');
  const fishGlyphs=['><>','><>','><>','>=>','><))°>','>{{°>'];
  function makeSchool(){
    const n=small()?6:8+(R()*6|0),x=R()*cols,y=rows*(.15+.6*R());
    return {x,y,a:R()<.5?0:Math.PI,speed:3.2+R()*1.6,wander:R()*50,scare:0,members:Array.from({length:n},()=>({ox:(R()-.5)*12,oy:(R()-.5)*6,x:x+(R()-.5)*8,y:y+(R()-.5)*4,vx:0,vy:0,p:R()*9,g:R()<.12?pick(fishGlyphs.slice(4)):pick(fishGlyphs.slice(0,4)),pink:R()<.25}))};
  }
  function seedLife(){
    life.dust=Array.from({length:Math.round(cols*rows/(small()?150:115))},()=>({x:R()*cols,y:R()*rows,z:.25+R()*.75,p:R()*9}));
    const n=small()?3:7;life.kelp=[];
    for(let i=0;i<n;i++)life.kelp.push({x:cols*(.04+.9*(i+.2+R()*.6)/n),h:(small()?6:9)+(R()*(small()?6:11)|0),p:R()*9});
    life.schools=Array.from({length:small()?2:3},makeSchool);
  }
  function stepLife(dt,avoid){
    const heads=sharks.map(s=>s.joints[0]);
    // drifting plankton
    for(const p of life.dust){p.y-=dt*.35*p.z;p.x+=Math.sin(time*.3+p.p)*dt*.25*p.z;if(p.y<-1){p.y=rows+1;p.x=R()*cols;}if(p.x<-1)p.x=cols;if(p.x>cols+1)p.x=0;}
    // bubbles from sharks, kelp tips and the sea floor
    const cap=small()?24:48;
    if(life.bubbles.length<cap){
      for(const h of heads)if(R()<dt*.9)life.bubbles.push({x:h.x,y:h.y,age:0,life:2+R()*3,p:R()*9,vy:1.2+R()*1});
      for(const k of life.kelp)if(R()<dt*.12)life.bubbles.push({x:k.x,y:floor-k.h,age:0,life:3+R()*4,p:R()*9,vy:1+R()*.8});
      if(R()<dt*1.2)life.bubbles.push({x:R()*cols,y:floor,age:0,life:4+R()*5,p:R()*9,vy:1+R()*1.4});
    }
    life.bubbles=life.bubbles.filter(b=>{b.age+=dt;b.y-=b.vy*dt*(1+b.age*.15);b.x+=Math.sin(b.age*2.6+b.p)*dt*.6;return b.age<b.life&&b.y>-2;});
    // fish schools: wander, dodge sharks and the pointer
    for(const s of life.schools){
      s.wander+=dt*.3;
      let steer=Math.sin(s.wander*1.1)*.5+Math.sin(s.wander*.37+2)*.35;
      const m=8,tx=s.x<m?1:s.x>cols-m?-1:0,ty=s.y<m?1:s.y>floor-m-4?-1:0;
      let target=(tx||ty)?Math.atan2(ty,tx):null,threat=null,dist=1e9;
      for(const h of heads){const d=Math.hypot(h.x-s.x,h.y-s.y);if(d<dist){dist=d;threat=h;}}
      const pd=Math.hypot(pointer.x-s.x,pointer.y-s.y);if(pd<dist&&pd<14){dist=pd;threat=pointer;}
      if(threat&&dist<16){target=Math.atan2(s.y-threat.y,s.x-threat.x);s.scare=Math.min(1,s.scare+dt*3);}else s.scare=Math.max(0,s.scare-dt*.6);
      if(target===null&&avoid&&Math.abs(s.x-avoid.x)<avoid.w&&Math.abs(s.y-avoid.y)<avoid.h)target=Math.atan2(s.y-avoid.y,s.x-avoid.x);
      if(target!==null){let d=target-s.a;d=Math.atan2(Math.sin(d),Math.cos(d));steer+=d*(2+s.scare*3);}
      s.a+=steer*dt*.8;
      const v=s.speed*(1+s.scare*1.6+hype*.8);
      s.x+=Math.cos(s.a)*v*dt;s.y+=Math.sin(s.a)*v*dt*.7;
      const spread=1+s.scare*.9+hype*.6;
      for(const f of s.members){
        const gx=s.x+f.ox*spread+Math.sin(time*1.7+f.p)*1.2,gy=s.y+f.oy*spread+Math.cos(time*1.3+f.p)*.7;
        f.vx+=((gx-f.x)*2.2-f.vx*1.6)*dt;f.vy+=((gy-f.y)*2.2-f.vy*1.6)*dt;
        f.x+=f.vx*dt+Math.cos(s.a)*v*dt*.15;f.y+=f.vy*dt;
      }
    }
    // a jellyfish now and then
    if(life.jelly){const j=life.jelly;j.t+=dt;const pulse=Math.max(0,Math.sin(j.t*1.8));j.y-=dt*(.35+pulse*2.2);j.x+=Math.sin(j.t*.4+j.p)*dt*.6;if(j.y<-10)life.jelly=null;}
    else if((life.jellyIn-=dt)<=0){life.jelly={x:cols*(.15+.7*R()),y:floor+6,t:0,p:R()*9,pink:R()<.5};life.jellyIn=22+R()*20;}
    // twinkles on the dot grid
    if(R()<dt*(small()?2.5:5))life.twinkles.push({x:R()*cols|0,y:R()*floor|0,age:0,blue:R()<.4});
    life.twinkles=life.twinkles.filter(t=>(t.age+=dt)<.9);
    // sonar pings from a shark now and then
    if((life.pingIn-=dt)<=0&&heads.length){const h=pick(heads);life.pings.push({x:h.x,y:h.y,r:0,max:small()?14:22});life.pingIn=7+R()*9;}
    life.pings=life.pings.filter(p=>(p.r+=dt*(small()?9:13))<p.max);
    life.moon+=dt*.17*(1+hype*.6);
    hype=Math.max(0,hype-dt*.25);
  }
  function drawLife(isLight){
    const k=isLight?.75:1,fade=isLight?.8:1;
    font(ctx,1.05);
    for(const p of life.dust)glyph(ctx,p.z>.8?'·':'.',p.x,p.y,p.z>.85?colors.blue:colors.muted,(.18+.38*p.z)*(.6+.4*Math.sin(time*2+p.p))*k);
    // kelp swaying from the floor
    for(const s of life.kelp){
      let px=s.x;
      for(let j=0;j<s.h;j++){
        const u=j/s.h,x=s.x+Math.sin(time*.9+s.p-j*.28)*Math.pow(u,1.4)*2.6+Math.sin(time*2.1+s.p+j)*.15*u,dx=x-px;px=x;
        const ch=j===s.h-1?'*':dx>.18?'/':dx<-.18?'\\':'|',c=mix(mix(colors.deep,colors.blue,.6),colors.pink,u*u),a=(.35+.45*u)*k;
        glyph(ctx,ch,x,floor-1-j,c,a);
        if(j<s.h-2)glyph(ctx,j%2?')':'(',x+(j%2?1:-1),floor-1-j,c,a*.8);
      }
    }
    // planet orbit + moon (screen space from the planet canvas)
    if(orbit.r){
      const ocx=orbit.cx/cell,ocy=orbit.cy/cell,rx=orbit.r*2.1/cell,ry=orbit.r*.55/cell,tilt=.38,ct=Math.cos(tilt),st=Math.sin(tilt);
      const at=a=>{const ex=Math.cos(a)*rx,ey=Math.sin(a)*ry;return [ocx+ex*ct-ey*st,ocy+ex*st+ey*ct];};
      for(let i=0;i<120;i++){const a=i/120*Math.PI*2;if(Math.sin(a)<0&&Math.hypot(...at(a).map((v,n)=>v-(n?ocy:ocx)))<orbit.r/cell)continue;const [x,y]=at(a);if(x<0||y<0||x>cols||y>rows)continue;glyph(ctx,i%2?'-':'·',x,y,colors.blue,.3*k);}
      const m=life.moon%(Math.PI*2),hidden=Math.sin(m)<0&&Math.hypot(...at(m).map((v,n)=>v-(n?ocy:ocx)))<orbit.r/cell;
      if(!hidden){for(let t=1;t<7;t++){const [x,y]=at(m-t*.035);glyph(ctx,'.',x,y,colors.pink,(.4-t*.05)*k);}const [x,y]=at(m);glyph(ctx,'@',x,y,colors.pink,.95*k);glyph(ctx,'o',x+1.2,y-.6,colors.text,.3*k);}
    }
    drawSquid();
    // fish
    for(const s of life.schools){const right=Math.cos(s.a)>=0;for(const f of s.members){const g=right?f.g:flip(f.g);glyph(ctx,g,f.x,f.y,f.pink?colors.pink:mix(colors.blue,colors.text,.25),(.65+s.scare*.3)*fade);}}
    // jellyfish
    if(life.jelly){
      const j=life.jelly,open=Math.sin(j.t*1.8)>0,c=j.pink?colors.pink:colors.blue,a=.75*fade;
      const bell=open?[' .-~~-. ','(  ..  )']:['  .--.  ',' ( .. ) '];
      bell.forEach((line,i)=>[...line].forEach((ch,n)=>{if(ch!==' ')glyph(ctx,ch,j.x+n-3.5,j.y+i,c,a);}));
      for(let t=0;t<4;t++)for(let r=0;r<4;r++){const sx=j.x-1.5+t+Math.sin(j.t*3+t+r*.9)*.5*(r+1)/2;glyph(ctx,r%2?';':':',sx,j.y+2+r,c,a*(1-r*.2));}
    }
    for(let x=0;x<cols;x++){const w=Math.sin(x*.27-time*1.6)+Math.sin(x*.11+time*.7)*.6;glyph(ctx,w>.7?'~':w>-.2?'-':'_',x,1.2+Math.sin(x*.15+time)*.35,colors.blue,(.1+.08*w)*k);}
    for(const b of life.bubbles){const u=b.age/b.life,ch=u>.92?'°':u>.55?'O':u>.2?'o':'.';glyph(ctx,ch,b.x,b.y,u>.55?colors.blue:colors.muted,(.55-.3*u)*k);}
  }
  function drawLifeTop(isLight){
    const k=isLight?.8:1;
    // Flecks flow around the visible limb, in the same current as the reef life.
    for(let i=0;i<12;i++){
      const a=Math.PI*1.05+i*.075+Math.sin(time*.3+i)*.035,r=orbit.r/cell*(1.04+(i%3)*.025);
      const x=orbit.cx/cell+Math.cos(a)*r,y=orbit.cy/cell+Math.sin(a)*r;
      glyph(ctx,i%4===0?'+':'.',x,y,i%2?colors.pink:colors.blue,(.28+.26*Math.sin(time*1.3+i)**2)*k);
    }
    drawGreg(isLight);
    for(const t of life.twinkles){const ch='.+*+.'[Math.min(4,t.age/.18|0)];glyph(ctx,ch,t.x,t.y,t.blue?colors.blue:colors.pink,.55*Math.sin(t.age/.9*Math.PI)*k);}
    for(const p of life.pings)ring(ctx,p.x,p.y,p.r,1-p.r/p.max,colors.blue,.22*k);
  }
  function drawGreg(isLight){
    // One little desk break in the background. Both props remain in the still
    // frame; only steam, a blink and the phone glint depend on scene time.
    const x=Math.max(5,cols*(small()?.23:.24)),y=floor-9.5,bob=Math.sin(time*1.1)*.09;
    const art=[
      '    .---.    ',
      '    |o o|    ',
      '    | - |    ',
      '    \\___/    ',
      '[_]o--|--[=] ',
      '      |  [ ] ',
      '     / \\     ',
      '    _| |_    '
    ];
    const ink=mix(colors.muted,colors.text,isLight?.45:.6),alpha=isLight?.65:.6;
    font(ctx,.95);
    art.forEach((line,row)=>[...line].forEach((ch,col)=>{
      if(ch===' ')return;
      if(row===1&&ch==='o'&&Math.sin(time*.55)> .995)ch='-';
      const prop=row===4&&(col<4||col>8)||row===5&&col>8;
      glyph(ctx,ch,x+col*.63-4,y+row*.72+bob,prop?colors.pink:ink,alpha);
    }));
    for(let i=0;i<2;i++)glyph(ctx,'~',x-3.4+Math.sin(time*1.3+i)*.2,y+2.3-i*.7-(time*.45+i*.4)%1,colors.muted,.24);
    glyph(ctx,'.',x+2.3,y+3.6,colors.blue,.25+.35*Math.sin(time*.9)**2);
    ctx.font=`${Math.round(cell*.65)}px Plex, ui-monospace, monospace`;
    glyph(ctx,'greg',x,y+6.6,colors.muted,isLight?.55:.45);
  }
  function ring(c,x,y,r,f,color,a){
    const n=Math.max(10,r*5|0),ch=f>.66?'o':f>.33?'+':'.';
    for(let i=0;i<n;i++){const t=i/n*Math.PI*2;glyph(c,ch,x+Math.cos(t)*r,y+Math.sin(t)*r*.6,color,a*f);}
  }

  // ---------- overlay bursts (taps, stashes, wins) ----------
  function burst(x,y,{count=10,speed=12,glyphs='+*x.',up=0,size=1,colorsList=null}={}){
    const cap=small()?120:220;
    for(let i=0;i<count&&fx.sparks.length<cap;i++){const a=R()*Math.PI*2,v=speed*(.35+R()*.65);fx.sparks.push({x,y,vx:Math.cos(a)*v,vy:Math.sin(a)*v*.75-up,age:0,life:.6+R()*.8,g:pick([...glyphs]),c:colorsList?pick(colorsList):pick([colors.pink,colors.blue,colors.text]),size});}
  }
  function cellsOf(el){if(!el||!el.getClientRects?.().length)return [cols/2,rows/2];const r=el.getBoundingClientRect();return [(r.left+r.width/2)/cell,(r.top+r.height/2)/cell];}
  function celebrate(kind,el){
    if(!moving()||!fctx||!cols)return;
    const [x,y]=cellsOf(el);
    if(kind==='tap'){fx.rings.push({x,y,r:0,max:3.2,speed:16});burst(x,y,{count:5,speed:9,glyphs:'.+'});}
    else if(kind==='stash'){
      fx.rings.push({x,y,r:0,max:8,speed:26},{x,y,r:-1.5,max:12,speed:24});
      burst(x,y,{count:28,speed:18,glyphs:'+*x#.',up:4});
      fx.floaters.push({text:'+1 stashed',x,y:y-2,age:0,life:1.4});
      hype=Math.max(hype,.5);
    }else if(kind==='win'){
      const cx=cols/2,cy=rows/2;
      for(let i=0;i<4;i++)fx.rings.push({x:cx,y:cy,r:-i*3,max:22+i*4,speed:30});
      burst(cx,cy,{count:small()?60:110,speed:34,glyphs:'+*x#@%W',up:6});
      burst(cx,cy,{count:small()?10:18,speed:26,glyphs:'W',size:1.8,colorsList:[colors.pink]});
      fx.floaters.push({text:'W',x:cx,y:cy,age:0,life:1.8,big:true});
      hype=1.6;life.schools.forEach(s=>s.scare=1);
    }
    fx.dirty=true;
  }
  function stepFx(dt){
    fx.rings=fx.rings.filter(r=>(r.r+=r.speed*dt)<r.max);
    fx.sparks=fx.sparks.filter(s=>{s.age+=dt;s.vx*=1-dt*1.8;s.vy=s.vy*(1-dt*1.8)+dt*9;s.x+=s.vx*dt;s.y+=s.vy*dt;return s.age<s.life;});
    fx.floaters=fx.floaters.filter(f=>(f.age+=dt)<f.life);
  }
  function drawFx(){
    if(!fctx)return;
    const active=fx.rings.length||fx.sparks.length||fx.floaters.length;
    if(!active&&!fx.dirty)return;
    fctx.setTransform(dpr,0,0,dpr,0,0);fctx.clearRect(0,0,innerWidth,innerHeight);fx.dirty=!!active;
    if(!active)return;
    font(fctx,1.05);
    for(const r of fx.rings)if(r.r>0)ring(fctx,r.x,r.y,r.r,1-r.r/r.max,colors.pink,.85);
    for(const s of fx.sparks){if(s.size!==1)font(fctx,s.size);glyph(fctx,s.g,s.x,s.y,s.c,1-s.age/s.life);if(s.size!==1)font(fctx,1.05);}
    for(const f of fx.floaters){
      const u=f.age/f.life,a=u<.15?u/.15:1-(u-.15)/.85;
      font(fctx,f.big?6+u*3:1.4);glyph(fctx,f.text,f.x,f.y-u*(f.big?3:4),colors.pink,a*(f.big?.9:1));
    }
  }

  function resize(){
    dpr=Math.min(2,devicePixelRatio||1);cell=small()?8:10;
    cols=Math.ceil(innerWidth/cell);rows=Math.ceil(innerHeight/cell);
    const nav=small()?document.querySelector('.rail nav'):null,top=nav?.getBoundingClientRect().top;
    floor=top&&top>innerHeight*.5?Math.floor(top/cell):rows;
    sharkCanvas.width=Math.round(innerWidth*dpr);sharkCanvas.height=Math.round(innerHeight*dpr);
    if(fxCanvas){fxCanvas.width=sharkCanvas.width;fxCanvas.height=sharkCanvas.height;fx.dirty=true;}
    mask.width=cols;mask.height=rows;
    const count=small()?2:3;
    if(sharks.length!==count)sharks=Array.from({length:count},(_,i)=>makeShark(i,i===1));
    sharks.forEach(s=>s.joints.forEach(j=>{j.x=Math.min(Math.max(j.x,-10),cols+10);j.y=Math.min(Math.max(j.y,-10),rows+10);}));
    seedLife();readColors();planet();draw();
  }
  function avoidRect(){
    const panel=document.querySelector('.capture-panel');if(!panel||!panel.getClientRects().length)return null;
    const r=panel.getBoundingClientRect();if(r.bottom<0||r.top>innerHeight)return null;
    return {x:(r.left+r.right)/2/cell,y:(r.top+r.bottom)/2/cell,w:r.width/cell/2+6,h:r.height/cell/2+6};
  }
  function step(dt){
    const avoid=avoidRect();
    sharks.forEach((s,i)=>{
      const h=s.joints[0];s.wander+=dt*.35*(1+hype);
      // gentle wander plus a pull back toward the screen when near an edge
      let steer=Math.sin(s.wander*1.3+i)*.55+Math.sin(s.wander*.47+i*3)*.45;
      const m=10,tx=h.x<m?1:h.x>cols-m?-1:0,ty=h.y<m?1:h.y>rows-m?-1:0;
      const want=(tx||ty)?Math.atan2(ty,tx):null;
      let target=null;
      if(want!==null)target=want;
      else if(avoid&&Math.abs(h.x-avoid.x)<avoid.w&&Math.abs(h.y-avoid.y)<avoid.h)target=Math.atan2(h.y-avoid.y,h.x-avoid.x);
      if(target!==null){let d=target-s.angle;d=Math.atan2(Math.sin(d),Math.cos(d));steer+=d*2.2;}
      s.turn+=(steer-s.turn)*Math.min(1,dt*2);
      s.angle+=s.turn*dt*.9*(1+hype*.6);
      s.phase+=dt*4.2*(1+hype*.8);
      const swim=s.angle+Math.sin(s.phase)*.22,v=s.speed*(1+hype*.9);
      h.x+=Math.cos(swim)*v*dt;h.y+=Math.sin(swim)*v*dt;
      for(let k=1;k<s.joints.length;k++){const a=s.joints[k-1],b=s.joints[k];let dx=b.x-a.x,dy=b.y-a.y;const L=Math.hypot(dx,dy)||1;b.x=a.x+dx/L*s.seg;b.y=a.y+dy/L*s.seg;}
    });
    stepLife(dt,avoid);stepFx(dt);
  }
  // half-width along the body, u=0 at the nose, 1 at the tail
  function profile(u){
    if(u<.12)return .35+.65*Math.sin(u/.12*Math.PI/2);
    if(u<.38)return 1;
    return Math.max(.12,1-(u-.38)/.62*.9);
  }
  function shape(s,scale,alpha){
    const J=s.joints,n=J.length,left=[],right=[];
    for(let k=0;k<n;k++){
      const a=J[Math.max(0,k-1)],b=J[Math.min(n-1,k+1)];let dx=b.x-a.x,dy=b.y-a.y;const L=Math.hypot(dx,dy)||1;dx/=L;dy/=L;
      const w=profile(k/(n-1))*s.width*scale;left.push([J[k].x-dy*w,J[k].y+dx*w]);right.push([J[k].x+dy*w,J[k].y-dx*w]);
    }
    mctx.fillStyle=`rgba(255,255,255,${alpha})`;mctx.beginPath();
    mctx.moveTo(J[0].x,J[0].y);left.forEach(p=>mctx.lineTo(p[0],p[1]));for(let k=n-1;k>=0;k--)mctx.lineTo(right[k][0],right[k][1]);mctx.closePath();mctx.fill();
    if(scale<1)return;
    const dir=(k)=>{const a=J[k],b=J[Math.min(n-1,k+1)];const dx=b.x-a.x,dy=b.y-a.y,L=Math.hypot(dx,dy)||1;return [dx/L,dy/L];};
    // pectoral fins, swept back
    const f=Math.round(n*.3),[fx_,fy]=dir(f),fw=s.width*2.5;
    for(const side of [1,-1]){
      const bx=J[f].x,by=J[f].y,nx=-fy*side,ny=fx_*side;
      mctx.beginPath();mctx.moveTo(bx+fx_*-1.5+nx*s.width*.8,by+fy*-1.5+ny*s.width*.8);mctx.lineTo(bx+fx_*3.5+nx*fw,by+fy*3.5+ny*fw);mctx.lineTo(bx+fx_*2.2+nx*s.width*.7,by+fy*2.2+ny*s.width*.7);mctx.closePath();mctx.fill();
    }
    // forked tail
    const t=n-1,[tx,ty]=dir(t-1),tw=s.width*1.9,flick=Math.sin(s.phase*1.4)*.6;
    for(const side of [1,-1]){
      const bx=J[t].x,by=J[t].y,nx=-ty*side,ny=tx*side;
      mctx.beginPath();mctx.moveTo(bx-tx*1.5,by-ty*1.5);mctx.lineTo(bx+tx*(3.4+flick*side)+nx*tw,by+ty*(3.4+flick*side)+ny*tw);mctx.lineTo(bx+tx*1.2,by+ty*1.2);mctx.closePath();mctx.fill();
    }
    if(s.hammer){
      const [hx,hy]=dir(0),hw=s.width*2.4,th=1.2,cx=J[0].x+hx*.6,cy=J[0].y+hy*.6;
      mctx.beginPath();mctx.moveTo(cx-hy*hw-hx*th,cy+hx*hw-hy*th);mctx.lineTo(cx-hy*hw+hx*th,cy+hx*hw+hy*th);mctx.lineTo(cx+hy*hw+hx*th,cy-hx*hw+hy*th);mctx.lineTo(cx+hy*hw-hx*th,cy-hx*hw-hy*th);mctx.closePath();mctx.fill();
    }
  }
  function draw(){
    if(!cols)return;
    mctx.clearRect(0,0,cols,rows);mctx.globalCompositeOperation='lighter';
    sharks.forEach(s=>{shape(s,1,.5);shape(s,.5,.5);});
    mctx.globalCompositeOperation='source-over';
    const data=mctx.getImageData(0,0,cols,rows).data,isLight=light();
    ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,innerWidth,innerHeight);
    drawSmoke();
    drawLife(isLight);
    font(ctx,1.05);
    const base=isLight?.55:.62,tile=rgb(colors.pink,isLight?.05:.04),hot=Math.min(1,hype);
    for(let y=0;y<rows;y++)for(let x=0;x<cols;x++){
      const a=data[(y*cols+x)*4+3]/255;if(a<.07)continue;
      const jitter=((x*73856093^y*19349663)>>>0)%100/100;
      ctx.fillStyle=tile;ctx.fillRect(x*cell,y*cell,cell-1,cell-1);
      let c=mix(colors.muted,colors.text,Math.min(1,a*1.1));
      if(a>.8)c=mix(c,colors.pink,.35+jitter*.4);else if(jitter>.86)c=mix(c,colors.blue,.5);
      if(hot)c=mix(c,colors.pink,hot*.5);
      ctx.fillStyle=rgb(c,base*(.45+a*.55));
      ctx.fillText(ramp[Math.min(ramp.length-1,Math.floor(a*ramp.length))],x*cell+cell/2,y*cell+cell/2+.5);
    }
    drawLifeTop(isLight);
    drawFx();
  }
  function tick(now){
    frame=0;if(!moving())return;
    if(!last)last=now;
    if(now-last>=50){
      const dt=Math.min(.1,(now-last)/1000);last=now;time+=dt;ticks++;
      planetSpin+=dt*.18*(1+hype*1.6);if(ticks%2===0)planet();
      step(dt);draw();
    }
    frame=requestAnimationFrame(tick);
  }
  function sync(){
    if(moving()){if(!frame){last=0;frame=requestAnimationFrame(tick);}}
    else{cancelAnimationFrame(frame);frame=0;fx.rings=[];fx.sparks=[];fx.floaters=[];draw();}
  }
  let themeWas=null;
  new MutationObserver(()=>{const t=light();if(t!==themeWas){themeWas=t;readColors();planet();draw();}sync();}).observe(document.body,{attributes:true,attributeFilter:['class']});
  let resizeTimer=0;addEventListener('resize',()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(resize,120);});
  document.addEventListener('visibilitychange',sync);reduced.addEventListener('change',sync);
  addEventListener('pointermove',e=>{pointer.x=e.clientX/cell;pointer.y=e.clientY/cell;},{passive:true});
  document.addEventListener('pointerleave',()=>{pointer.x=pointer.y=-99;});
  addEventListener('pointerdown',e=>{if(e.isPrimary&&e.button===0){const x=e.clientX/cell,y=e.clientY/cell;if(moving()&&fctx){fx.rings.push({x,y,r:0,max:3.2,speed:16});burst(x,y,{count:5,speed:9,glyphs:'.+'});fx.dirty=true;}}},{passive:true});
  themeWas=light();grain();resize();
  // let the sharks settle into a natural curve before the first still frame
  for(let i=0;i<40;i++)step(.05);draw();sync();
  document.fonts?.ready?.then(()=>{squidCache=null;smokeCache=null;draw();});
  return {redraw:()=>{readColors();planet();draw();},celebrate};
})();
