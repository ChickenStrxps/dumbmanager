/* Original, periodic smoke artwork shared by cards and the ambient aquarium.
   A small train of expanding, curling puffs is sampled on a fixed glyph grid.
   Ordered 4x4 coverage stays anchored to that grid: no random per-frame grain.
   This is an analytic illustration, not a fluid simulation. No dependencies. */
'use strict';
window.DMAsciiSmoke=(()=>{
  const TAU=Math.PI*2,BAYER=[0,8,2,10,12,4,14,6,3,11,1,9,15,7,13,5],RAMP=' .,:;=+*x%#@';
  const wrap=t=>((t%1)+1)%1;
  const rgb=hex=>{const n=parseInt(hex.slice(1),16);return [n>>16&255,n>>8&255,n&255];};
  function create({cols=72,rows=120,pitch=2.4,ratio=1,colors=['#716392','#cda5d5','#f8dfbd'],seed=0,font='monospace',frames=0}={}){
    ratio=Math.min(1.5,Math.max(1,ratio));
    // Whole device-pixel cells prevent partially cleared edges accumulating
    // when a glyph changes on fractional-DPR displays.
    const unit=Math.max(1,Math.round(pitch*ratio)),w=cols*pitch,h=rows*pitch,sw=cols*unit,sh=rows*unit,n=RAMP.length;
    const tile=document.createElement('canvas');tile.width=n*unit;tile.height=12*unit;
    const ink=tile.getContext('2d');ink.font=`${unit*1.5}px ${font}`;ink.textAlign='center';ink.textBaseline='middle';
    const tones=colors.map(rgb);
    for(let k=0;k<12;k++){
      const u=k/11*2,a=tones[Math.min(1,Math.floor(u))],b=tones[Math.min(2,Math.floor(u)+1)],v=u%1;
      const color=k===11?tones[2]:a.map((x,i)=>Math.round(x+(b[i]-x)*v));
      ink.fillStyle=`rgb(${color.join(',')})`;
      for(let j=1;j<n;j++)ink.fillText(RAMP[j],(j+.5)*unit,(k+.5)*unit);
    }
    const image=document.createElement('canvas');image.width=sw;image.height=sh;
    const c=image.getContext('2d'),state=new Int16Array(cols*rows).fill(-1),density=new Float32Array(cols*rows);
    const phase=(seed>>>0)%997/997,atlas=frames?document.createElement('canvas'):null,ac=atlas?.getContext('2d');
    const across=frames?Math.ceil(Math.sqrt(frames)):1,built=new Uint8Array(frames);
    if(atlas){atlas.width=sw*across;atlas.height=sh*Math.ceil(frames/across);atlas.dataset.dmArt='dither-smoke';}
    let previous=-1;
    function paint(t){
      t=wrap(t);if(t===previous)return;previous=t;density.fill(0);
      for(let i=0;i<7;i++){
        const u=wrap(t+i/7),rise=u*u*(3-2*u),curl=u*6.8+phase*TAU+i*.43;
        const cx=cols*(.48+Math.sin(curl)*(.018+.16*u)),cy=rows*(.98-.96*rise);
        const rx=cols*(.055+.24*u),ry=rows*(.038+.13*u),fade=Math.sin(Math.PI*u)**2;
        // Three lobes per puff roll around one another as the plume rises.
        for(let l=0;l<3;l++){
          const angle=curl+l*TAU/3,px=cx+Math.cos(angle)*rx*.4,py=cy+Math.sin(angle)*ry*.38;
          const x0=Math.max(0,Math.floor(px-rx*1.7)),x1=Math.min(cols-1,Math.ceil(px+rx*1.7));
          const y0=Math.max(0,Math.floor(py-ry*1.7)),y1=Math.min(rows-1,Math.ceil(py+ry*1.7));
          for(let y=y0;y<=y1;y++)for(let x=x0;x<=x1;x++){
            const dx=(x-px)/rx,dy=(y-py)/ry,r2=dx*dx+dy*dy;if(r2>2.9)continue;
            // A hollow curl gives each billow a lit rim and a darker centre.
            const rim=.6+.4*Math.min(1,r2*2.4);
            density[y*cols+x]+=Math.exp(-r2*2.8)*fade*rim*.72;
          }
        }
      }
      for(let y=0,q=0;y<rows;y++)for(let x=0;x<cols;x++,q++){
        const v=Math.min(1,density[q]*1.55),th=(BAYER[(y&3)*4+(x&3)]+.5)/16;
        const cover=Math.min(1,v*1.55),level=Math.min(n-1,Math.max(1,Math.floor(v*(n-2)+th*2)));
        const tone=Math.min(11,Math.floor(v*10+th)),code=cover>th&&v>.018?tone*n+level:0;
        if(state[q]===code)continue;state[q]=code;c.clearRect(x*unit,y*unit,unit,unit);
        if(code)c.drawImage(tile,level*unit,tone*unit,unit,unit,x*unit,y*unit,unit,unit);
      }
    }
    function pose(i){
      if(built[i])return;paint(i/frames);
      ac.drawImage(image,i%across*sw,Math.floor(i/across)*sh);built[i]=1;
    }
    return {draw(ctx,t,x,y,width=w,height=h,alpha=1){
      ctx.save();alpha*=ctx.globalAlpha;ctx.globalAlpha=alpha;
      if(!atlas){paint(t);ctx.drawImage(image,x,y,width,height);}
      else{
        const f=wrap(t)*frames,i=Math.floor(f),j=(i+1)%frames,mix=f-i;
        pose(i);pose(j);
        for(const [index,a] of [[i,1-mix],[j,mix]])if(a>.001){ctx.globalAlpha=alpha*a;ctx.drawImage(atlas,index%across*sw,Math.floor(index/across)*sh,sw,sh,x,y,width,height);}
      }
      ctx.restore();
    }};
  }
  return {create};
})();
