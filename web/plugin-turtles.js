'use strict';
// Twelve lazy poses, one atlas, the aquarium's existing clock. No extra RAF loop.
window.DMPluginTurtles=(()=>{
  let atlas=null,key='',built=0;
  const N=12,W=152,H=128,P=2.2,D=1.25;
  const seeds=[[0,-.67],[0,-.32],[0,.05],[0,.42],[0,.72],[-.48,-.48],[.48,-.48],[-.57,-.08],[.57,-.08],[-.54,.32],[.54,.32],[-.37,.65],[.37,.65]];
  const bayer=[0,8,2,10,12,4,14,6,3,11,1,9,15,7,13,5];
  function build(index,colors,isLight){
    if(atlas.poses[index])return;
    const c=atlas.ctx,ox=(index%4)*atlas.w,oy=Math.floor(index/4)*atlas.h,phase=index/N*Math.PI*2;
    c.save();c.translate(ox,oy);c.scale(D,D);c.font='2.6px Plex,monospace';c.textAlign='center';c.textBaseline='middle';
    const ellipse=(x,y,cx,cy,rx,ry,a=0)=>{const co=Math.cos(a),si=Math.sin(a),dx=x-cx,dy=y-cy;return Math.pow((dx*co+dy*si)/rx,2)+Math.pow((-dx*si+dy*co)/ry,2);};
    // Top view: overlapping scutes, domed shell, tapered swept flippers and neck.
    for(let y=2;y<H-2;y++)for(let x=2;x<W-2;x++){
      const X=(x-W/2)/45,Y=(y-H/2)/38,shell=X*X+Y*Y;
      let v=0,surface='';
      for(const side of [-1,1]){
        const sweep=Math.sin(phase+side*.35)*.24;
        const front=ellipse(x,y,76+side*43,46+Math.sin(phase)*4,28,8,side*(.58+sweep));
        const back=ellipse(x,y,76+side*34,91,20,7,side*(-.6-Math.sin(phase+.8)*.12));
        if(Math.min(front,back)<1){v=.28+(1-Math.min(front,back))*.28;surface='skin';}
      }
      const neck=ellipse(x,y,76,27,11,19),head=ellipse(x,y,76,14,12,12);
      if(neck<1||head<1){v=.38+(1-Math.min(neck,head))*.32;surface='skin';}
      if(ellipse(x,y,76,106,4,11)<1){v=.4;surface='skin';}
      if(shell<1){
        surface='shell';const dome=Math.sqrt(1-shell),light=.55-.24*X-.28*Y;
        v=.24+dome*.4+light*.2;
        // Five central vertebral scutes, flanked by four pairs of costal plates.

        let d1=99,d2=99,plate=0;
        seeds.forEach(([a,b],i)=>{const d=(X-a)**2+(Y-b)**2;if(d<d1){d2=d1;d1=d;plate=i;}else if(d<d2)d2=d;});
        if(d2-d1<.035)v*=.38;else if(d2-d1<.075)v+=.11;
        const growth=Math.sin(Math.sqrt(d1)*65+plate*.7);if(growth>.4)v-=.05;
        // Segmented marginal rim and fine mottling follow the shell curvature.
        if(shell>.79){v=.38+(Math.sin(Math.atan2(Y,X)*26)>.2?.18:-.06);if(shell>.94)v*=.65;}
        v+=Math.sin(x*1.7+y*.4)*Math.sin(y*1.4-x*.3)*.045;
      }
      if(!v)continue;
      if(surface==='skin'){
        if(((x+2*y)%7===0)&&((y+x)%3!==0))v*=.55;
        // Eyes and snout, preserved at glyph resolution.
        if((x-68)**2+(y-12)**2<3||(x-84)**2+(y-12)**2<3)v=.08;
        if(y===5&&x>72&&x<80)v=.22;
      }
      const threshold=(bayer[(y&3)*4+(x&3)]+.5)/16;
      if(v<.25&&threshold>.55)continue;
      const t=Math.max(0,Math.min(1,v)),ink=colors.muted.map((a,i)=>Math.round(a+(colors.pink[i]-a)*(surface==='shell'?.45:.14)+(colors.text[i]-a)*t*.35));
      c.fillStyle=`rgba(${ink.join(',')},${(isLight?.65:.83)*(.5+t*.5)})`;
      const glyph='.,:;+*xs%#@'[Math.min(10,Math.floor(t*10+threshold*.9))];
      c.fillText(glyph,x*P,y*P);
    }
    c.restore();atlas.poses[index]=1;built++;
  }
  function draw(ctx,time,colors,isLight){
    const stamp=JSON.stringify([colors,isLight]);
    if(key!==stamp||!atlas){
      key=stamp;const canvas=document.createElement('canvas'),w=Math.ceil(W*P*D),h=Math.ceil(H*P*D);canvas.width=w*4;canvas.height=h*3;
      atlas={canvas,ctx:canvas.getContext('2d'),w,h,poses:new Uint8Array(N)};built=0;
    }
    if(!atlas.ctx)return;
    const pose=Math.floor((time*.55)%1*N),next=(pose+1)%N,blend=(time*.55*N)%1;
    build(pose,colors,isLight);build(next,colors,isLight);
    const mobile=innerWidth<760;
    const turtles=mobile?[[.91,.22,.58,.35]]:[[.87,.17,1.05,.55],[.79,.83,.72,-.55]];
    turtles.forEach(([px,py,scale,angle],i)=>{
      ctx.save();ctx.translate(innerWidth*px+Math.sin(time*.12+i)*38,innerHeight*py+Math.sin(time*.18+i*2)*35);ctx.rotate(angle+Math.sin(time*.15+i)*.12);ctx.scale(scale,scale);
      for(const [index,alpha] of [[pose,1-blend],[next,blend]]){
        ctx.globalAlpha=alpha;ctx.drawImage(atlas.canvas,(index%4)*atlas.w,Math.floor(index/4)*atlas.h,atlas.w,atlas.h,-W*P/2,-H*P/2,W*P,H*P);
      }ctx.restore();
    });
  }
  return {draw,invalidate:()=>{atlas=null;},stats:()=>({poses:built,maxPoses:N,bytes:atlas?atlas.canvas.width*atlas.canvas.height*4:0})};
})();
