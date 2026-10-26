'use strict';
// Inlined into the HTML with a per-response CSP nonce, so a missed app.js can retry.
document.addEventListener('DOMContentLoaded',async()=>{
  if(window.DMAppStarted)return;
  const dialog=document.createElement('dialog');dialog.id='entry-recovery';dialog.className='startup-recovery';
  dialog.innerHTML='<pre aria-hidden="true">[ .. ]</pre><h2>One sec\u2026</h2><p role="status"></p><button type="button" class="primary" hidden>Try again</button>';
  const message=dialog.querySelector('p'),button=dialog.querySelector('button');
  dialog.addEventListener('cancel',e=>e.preventDefault());document.body.append(dialog);dialog.showModal();
  async function load(attempt){
    await new Promise((resolve,reject)=>{
      const script=document.createElement('script');script.src='/app.js?retry='+attempt;
      script.onload=()=>{script.remove();window.DMAppStarted?resolve():reject(new Error('App unavailable'));};
      script.onerror=()=>{script.remove();reject(new Error('App unavailable'));};document.head.append(script);
    });
  }
  try{
    let attempt=0;
    while(!window.DMAppStarted){
      button.hidden=true;message.textContent='Part of the app missed the connection. Retrying\u2026';
      for(let retry=0;retry<2&&!window.DMAppStarted;retry++)try{await load(++attempt);}catch{}
      if(window.DMAppStarted)break;
      message.textContent='Check your connection, then try again.';button.hidden=false;button.focus();
      await new Promise(resolve=>{button.onclick=resolve;});
    }
  }finally{dialog.close();dialog.remove();}
});
