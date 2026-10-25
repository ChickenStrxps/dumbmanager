'use strict';
window.DMVoice=(()=>{
  let dialog=null,run=0,active=null,phase='idle',stream=null,pc=null,dc=null,socket=null,audio=null,context=null,source=null,worklet=null,gain=null;
  let heartbeat=null,deadline=null,opening=null,playAt=0,muted=false,chain=Promise.resolve();
  const sources=new Set(),seen=new Set(),canceled=new Set(),reviews=new Map();
  let transcript='',lastTextType='';
  let responseRunning=false,responseWanted=false,openAITools=0;
  const q=s=>dialog?.querySelector(s);
  const current=n=>n===run&&!!active;
  function message(text){if(q('[data-voice-status]'))q('[data-voice-status]').textContent=text;}
  function controls(){
    if(!dialog)return;
    q('[data-voice=start]').disabled=phase!=='idle';q('[data-voice=stop]').disabled=phase==='idle';
    q('[data-voice=mute]').disabled=phase!=='connected';q('[data-voice=interrupt]').disabled=phase!=='connected';
    q('[data-voice=mute]').textContent=muted?'Unmute mic':'Mute mic';
    q('[data-voice=mute]').setAttribute('aria-pressed',String(muted));
    q('[data-voice-provider]').disabled=phase!=='idle';q('[data-voice-project]').disabled=phase!=='idle';
    dialog.dataset.state=phase;
    document.querySelector('[data-ai-voice-open]')?.classList.toggle('voice-active',phase==='connected');
  }
  async function request(name,args={}){
    const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),22000);
    try{
      const r=await fetch('/api/call',{method:'POST',headers:{'Content-Type':'application/json','X-DumbManager':'1'},
        body:JSON.stringify({name,args}),signal:controller.signal});
      const result=await r.json();if(!r.ok)throw new Error(result.error||'DumbAPI request failed.');return result;
    }catch(e){if(e.name==='AbortError')throw new Error('The request timed out. Check the connection before trying again.');throw e;}
    finally{clearTimeout(timeout);}
  }
  function text(kind,delta){
    if(!delta)return;
    if(lastTextType!==kind){transcript+='\n'+kind+': ';lastTextType=kind;}
    transcript=(transcript+delta).slice(-6000);if(q('[data-voice-transcript]')){q('[data-voice-transcript]').textContent=transcript;q('[data-voice-transcript]').scrollTop=100000;}
  }
  function clearAudio(){for(const node of sources){try{node.stop();}catch{}}sources.clear();playAt=0;}
  async function stop(note='Voice stopped. Microphone off.'){
    const old=active;run++;active=null;phase='idle';clearInterval(heartbeat);clearTimeout(deadline);clearTimeout(opening);
    heartbeat=deadline=opening=null;
    for(const review of reviews.values()){clearTimeout(review.timer);review.resolve({state:'revoked',note:'Voice stopped.'});}reviews.clear();
    q('[data-voice-requests]')?.replaceChildren();
    if(dc){dc.onmessage=dc.onopen=dc.onclose=dc.onerror=null;try{dc.close();}catch{}}dc=null;
    if(pc){pc.onconnectionstatechange=pc.ontrack=null;try{pc.close();}catch{}}pc=null;
    if(socket){socket.onmessage=socket.onopen=socket.onerror=socket.onclose=null;try{socket.close();}catch{}}socket=null;
    stream?.getTracks().forEach(t=>t.stop());stream=null;
    if(worklet){worklet.port.onmessage=null;worklet.disconnect();}worklet=null;
    source?.disconnect();gain?.disconnect();source=gain=null;clearAudio();
    if(context){const closing=context;context=null;closing.close().catch(()=>{});}
    if(audio){audio.pause();audio.srcObject=null;audio.remove();audio=null;}
    muted=false;responseRunning=false;responseWanted=false;openAITools=0;seen.clear();canceled.clear();chain=Promise.resolve();controls();message(note);
    if(old?.session_id)request('ai.sessions.touch',{session_id:old.session_id,state:'closed'}).catch(()=>{});
  }
  async function connected(n){
    if(!current(n)||phase==='connected')return;
    clearTimeout(opening);phase='connected';controls();message('Connected · listening. Stop turns the microphone off.');
    try{await request('ai.sessions.touch',{session_id:active.session_id,state:'connected'});}catch(e){if(current(n))stop(e.message);return;}
    if(!current(n))return;
    heartbeat=setInterval(async()=>{try{await request('ai.sessions.touch',{session_id:active.session_id,state:'connected'});}catch(e){if(current(n))stop(e.message);}},20000);
  }
  function sendOpenAI(value){if(dc?.readyState==='open')dc.send(JSON.stringify(value));}
  function sendGemini(value){if(socket?.readyState===WebSocket.OPEN)socket.send(JSON.stringify(value));}
  function continueOpenAI(){if(responseWanted&&!responseRunning&&openAITools===0&&phase==='connected'){responseWanted=false;sendOpenAI({type:'response.create'});}}
  function result(n,id,name,value){
    if(!current(n)||canceled.has(id))return;
    if(active.provider==='openai_realtime'){
      sendOpenAI({type:'conversation.item.create',item:{type:'function_call_output',call_id:id,output:JSON.stringify(value)}});
      responseWanted=true;continueOpenAI();
    }else sendGemini({toolResponse:{functionResponses:[{id,name,response:{result:value}}]}});
  }
  function reviewMarkup(){
    const root=q('[data-voice-requests]');if(!root)return;root.replaceChildren();
    for(const [id,item] of reviews){
      const card=document.createElement('section');card.className='ai-request';
      const title=document.createElement('strong');title.textContent='Approve '+item.receipt.capability+'?';
      const body=document.createElement('pre');body.textContent=JSON.stringify(item.receipt.arguments,null,2);
      const yes=document.createElement('button');yes.className='primary';yes.textContent='Approve this action';yes.dataset.voiceApprove=id;
      const no=document.createElement('button');no.className='secondary';no.textContent='Decline';no.dataset.voiceDecline=id;
      card.append(title,body,yes,no);root.append(card);
    }
  }
  function finishReview(id,receipt){const item=reviews.get(id);if(!item)return;clearTimeout(item.timer);reviews.delete(id);reviewMarkup();item.resolve(receipt);}
  function review(n,receipt,callId){
    return new Promise(resolve=>{
      const item={receipt,resolve,callId,timer:null};reviews.set(receipt.approval_id,item);reviewMarkup();message('A tool wants to make a change. Review it below.');
      const poll=async()=>{
        if(!current(n)||!reviews.has(receipt.approval_id))return;
        try{const r=await request('ai.approvals.get',{id:receipt.approval_id});if(r.state!=='pending'){finishReview(receipt.approval_id,r);return;}}catch{}
        if(current(n)&&reviews.has(receipt.approval_id))item.timer=setTimeout(poll,3000);
      };
      item.timer=setTimeout(poll,3000);
    });
  }
  async function tool(n,id,name,args){
    if(!current(n)||seen.has(id))return;seen.add(id);
    const openAI=active.provider==='openai_realtime';if(openAI)openAITools++;
    try{
      let value=await request('ai.sessions.tool',{session_id:active.session_id,name,arguments:typeof args==='string'?args:JSON.stringify(args||{}),call_id:id});
      if(!current(n)||canceled.has(id)){
        if(value.state==='pending'&&value.approval_id)request('ai.approvals.decide',{id:value.approval_id,approve:false}).catch(()=>{});
        return;
      }
      if(value.state==='pending'&&value.approval_id)value=await review(n,value,id);
      result(n,id,name,value);
      if(current(n))message(value.state==='uncertain'?'Tool result unconfirmed. Check its destination.':'Connected · listening.');
    }catch(e){result(n,id,name,{error:e.message});if(current(n))message('Tool could not finish: '+e.message);}
    finally{if(current(n)&&openAI){openAITools--;continueOpenAI();}}
  }
  function cancelTools(ids){
    for(const id of ids){canceled.add(id);for(const [aid,item] of reviews)if(item.callId===id){request('ai.approvals.decide',{id:aid,approve:false}).catch(()=>{});finishReview(aid,{state:'declined'});}}
  }
  async function openAI(n,boot){
    const peer=pc=new RTCPeerConnection();
    audio=document.createElement('audio');audio.autoplay=true;audio.controls=true;audio.setAttribute('aria-label','Voice response audio');q('[data-voice-audio]').append(audio);
    peer.ontrack=e=>{if(current(n)&&audio){audio.srcObject=e.streams[0];audio.play().catch(()=>message('Tap Play on the audio controls to hear the response.'));}};
    for(const track of stream.getTracks())peer.addTrack(track,stream);
    const channel=dc=peer.createDataChannel('oai-events');
    channel.onopen=()=>connected(n);
    channel.onclose=()=>{if(current(n))stop('Voice connection closed. Reconnect when ready.');};
    channel.onerror=()=>{if(current(n))stop('The voice data connection failed. Reconnect when ready.');};
    channel.onmessage=e=>{
      if(!current(n))return;let event;try{event=JSON.parse(e.data);}catch{return;}
      if(event.type==='response.created')responseRunning=true;
      if(event.type==='response.done'){responseRunning=false;continueOpenAI();}
      if(event.type==='error'&&event.error?.code==='response_cancel_not_active')return;
      if(event.type==='error'){stop('OpenAI reported a session error. Check model access and settings.');return;}
      if(event.type==='response.function_call_arguments.done')tool(n,event.call_id,event.name,event.arguments);
      if(event.type==='response.output_audio_transcript.delta'||event.type==='response.output_text.delta')text('Assistant',event.delta);
      if(event.type==='conversation.item.input_audio_transcription.completed')text('You',event.transcript+'\n');
      if(event.type==='input_audio_buffer.speech_started')message('Listening…');
    };
    peer.onconnectionstatechange=()=>{if(current(n)&&['failed','closed','disconnected'].includes(peer.connectionState))stop('Voice connection interrupted. Reconnect when ready.');};
    const offer=await peer.createOffer();if(!current(n))return;await peer.setLocalDescription(offer);if(!current(n))return;
    const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),15000);
    try{
      const r=await fetch(boot.endpoint,{method:'POST',body:offer.sdp,headers:{Authorization:'Bearer '+boot.client_secret,'Content-Type':'application/sdp'},signal:controller.signal});
      if(!r.ok)throw new Error('OpenAI could not connect this session. Check your model access.');
      const sdp=await r.text();if(current(n))await peer.setRemoteDescription({type:'answer',sdp});
    }finally{clearTimeout(timeout);boot.client_secret='';}
  }
  function base64(buffer){let result='';for(const byte of new Uint8Array(buffer))result+=String.fromCharCode(byte);return btoa(result);}
  function play(data){
    if(!context)return;const raw=atob(data),pcm=new DataView(new ArrayBuffer(raw.length));for(let i=0;i<raw.length;i++)pcm.setUint8(i,raw.charCodeAt(i));
    const buffer=context.createBuffer(1,Math.floor(raw.length/2),24000),out=buffer.getChannelData(0);
    for(let i=0;i<out.length;i++)out[i]=pcm.getInt16(i*2,true)/32768;
    if(playAt>context.currentTime+5){clearAudio();message('Audio fell behind. Playback caught up.');}
    const node=context.createBufferSource();node.buffer=buffer;node.connect(context.destination);sources.add(node);node.onended=()=>{sources.delete(node);node.disconnect();};
    playAt=Math.max(context.currentTime,playAt);node.start(playAt);playAt+=buffer.duration;
  }
  async function gemini(n,boot){
    const ctx=context;if(!ctx)throw new Error('Audio is unavailable in this browser.');
    await ctx.audioWorklet.addModule('/pcm-worklet.js');if(!current(n))return;
    source=ctx.createMediaStreamSource(stream);worklet=new AudioWorkletNode(ctx,'dumb-pcm');gain=ctx.createGain();gain.gain.value=0;
    source.connect(worklet);worklet.connect(gain);gain.connect(ctx.destination);
    const ws=socket=new WebSocket(boot.endpoint+'?access_token='+encodeURIComponent(boot.client_secret));boot.client_secret='';
    worklet.port.onmessage=e=>{
      if(!current(n)||muted||phase!=='connected'||ws.readyState!==WebSocket.OPEN)return;
      if(ws.bufferedAmount>256000){stop('The connection cannot keep up with microphone audio. Reconnect on a steadier connection.');return;}
      sendGemini({realtimeInput:{audio:{mimeType:'audio/pcm;rate=16000',data:base64(e.data)}}});
    };
    ws.onopen=()=>{if(current(n))sendGemini({setup:boot.setup});};
    ws.onerror=()=>{if(current(n))stop('Gemini could not connect. Check your API key, model access and connection.');};
    ws.onclose=()=>{if(current(n))stop('Gemini session ended. Reconnect when ready.');};
    ws.onmessage=e=>{
      chain=chain.then(async()=>{
        if(!current(n))return;const event=JSON.parse(typeof e.data==='string'?e.data:await e.data.text());
        if(!current(n))return;
        if(event.error){stop('Gemini reported a session error. Check the configured model and settings.');return;}
        if(event.setupComplete){await connected(n);return;}
        if(event.goAway){stop('Gemini is ending this session. Reconnect to continue.');return;}
        if(event.toolCallCancellation)cancelTools(event.toolCallCancellation.ids||[]);
        for(const call of event.toolCall?.functionCalls||[])tool(n,call.id,call.name,call.args);
        const content=event.serverContent;
        if(content?.interrupted){clearAudio();message('Listening…');}
        for(const part of content?.modelTurn?.parts||[]){if(part.inlineData?.mimeType?.startsWith('audio/pcm'))play(part.inlineData.data);if(part.text&&!part.thought)text('Assistant',part.text);}
        if(content?.inputTranscription?.text)text('You',content.inputTranscription.text);
        if(content?.outputTranscription?.text)text('Assistant',content.outputTranscription.text);
      }).catch(()=>{if(current(n))stop('Gemini sent an unsupported session event. Reconnect to try again.');});
    };
  }
  async function start(){
    if(phase!=='idle')return;
    if(!window.isSecureContext||!navigator.mediaDevices?.getUserMedia){message('Microphone access needs HTTPS or localhost in a supported browser.');return;}
    const provider=q('[data-voice-provider]').value,project=q('[data-voice-project]').value;
    const configured=DMAI.providers().find(p=>p.id===provider);
    if(!configured?.configured||!configured.enabled){message('Save a key and enable this provider in AI integrations first.');return;}
    const n=++run;active={provider};phase='starting';controls();message('Connecting… Microphone permission may be needed.');
    transcript='';lastTextType='';q('[data-voice-transcript]').textContent='';
    opening=setTimeout(()=>{if(current(n))stop('Voice did not connect in time. Check access and reconnect.');},30000);
    try{
      if(provider==='gemini_live'){
        const Audio=window.AudioContext||window.webkitAudioContext;
        if(!Audio)throw new Error('This browser does not support the audio interface.');
        context=new Audio();await context.resume();if(!current(n))return;
      }
      const mic=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:true},video:false});
      if(!current(n)){mic.getTracks().forEach(t=>t.stop());return;}stream=mic;
      const boot=await request('ai.sessions.start',{provider,project});
      if(!current(n)){request('ai.sessions.touch',{session_id:boot.session_id,state:'closed'}).catch(()=>{});return;}
      active=boot;deadline=setTimeout(()=>{if(current(n))stop('Session limit reached. Microphone off. Reconnect to continue.');},Math.max(0,boot.expires*1000-Date.now()));
      if(boot.transport==='webrtc')await openAI(n,boot);else if(boot.transport==='websocket')await gemini(n,boot);else throw new Error('This voice transport is not supported.');
    }catch(e){if(current(n))stop(e.name==='NotAllowedError'?'Microphone permission was denied. Allow it in your browser, then reconnect.':e.message||'Voice could not connect.');}
  }
  async function open(preferred=''){
    await DMAI.load();
    if(!dialog){
      dialog=document.createElement('dialog');dialog.className='voice-dialog';dialog.id='voice-dialog';
      dialog.innerHTML='<div class="voice-heading"><h2>Talk to your projects</h2><button type="button" class="quiet" data-voice="close" aria-label="Stop voice and close">Close ×</button></div><div class="ai-pair"><div><label for="voice-provider">Provider</label><select id="voice-provider" data-voice-provider></select></div><div><label for="voice-project">Project context</label><select id="voice-project" data-voice-project><option value="">Ask me which project</option></select></div></div><pre class="voice-orbit" aria-hidden="true">   .  &gt;&lt;(((°&gt;  .\n  [   o   o   ]\n      ~ ~ ~</pre><p data-voice-status role="status" aria-live="polite">Choose a provider, then connect.</p><div class="detail-actions"><button class="primary" data-voice="start">Connect voice</button><button class="secondary" data-voice="mute" aria-pressed="false" disabled>Mute mic</button><button class="secondary" data-voice="interrupt" disabled>Interrupt</button><button class="secondary" data-voice="stop" disabled>Stop voice</button></div><div data-voice-audio></div><div data-voice-requests></div><details><summary>Conversation text · this session only</summary><pre class="voice-transcript" data-voice-transcript></pre></details><p class="muted">Audio goes directly to the chosen provider. DumbAPI handles permitted tool calls. Closing this panel stops the microphone. This uses the provider API, with its own billing and limits.</p><button class="text-link" data-voice="settings">AI integration settings ↗</button>';
      document.body.append(dialog);dialog.addEventListener('cancel',e=>{e.preventDefault();stop();dialog.close();});
      dialog.addEventListener('click',async e=>{
        const b=e.target.closest('[data-voice],[data-voice-approve],[data-voice-decline]');if(!b||b.disabled)return;
        if(b.dataset.voiceApprove||b.dataset.voiceDecline){
          const id=b.dataset.voiceApprove||b.dataset.voiceDecline;b.disabled=true;
          try{finishReview(id,await request('ai.approvals.decide',{id,approve:!!b.dataset.voiceApprove}));}catch(err){message(err.message);b.disabled=false;}return;
        }
        if(b.dataset.voice==='start')start();
        if(b.dataset.voice==='stop')stop();
        if(b.dataset.voice==='close'){stop();dialog.close();}
        if(b.dataset.voice==='settings'){stop();dialog.close();settingsTab='ai';setView('setup');}
        if(b.dataset.voice==='mute'){muted=!muted;stream?.getAudioTracks().forEach(t=>t.enabled=!muted);if(muted&&active?.provider==='gemini_live')sendGemini({realtimeInput:{audioStreamEnd:true}});controls();message(muted?'Microphone muted.':'Connected · listening.');}
        if(b.dataset.voice==='interrupt'){
          clearAudio();cancelTools([...seen]);
          if(active?.provider==='openai_realtime'){responseWanted=false;if(responseRunning)sendOpenAI({type:'response.cancel'});sendOpenAI({type:'output_audio_buffer.clear'});}
          else sendGemini({clientContent:{turns:[{role:'user',parts:[{text:'Stop speaking and wait for my next request.'}]}],turnComplete:true}});
          message('Interrupted · listening.');
        }
      });
    }
    if(phase==='idle'){
      const providers=DMAI.providers().filter(p=>p.kind==='voice');
      q('[data-voice-provider]').innerHTML=providers.map(p=>`<option value="${esc(p.id)}">${esc(p.label)}${p.enabled&&p.configured?'':' · needs setup'}</option>`).join('');
      if(preferred&&providers.some(p=>p.id===preferred))q('[data-voice-provider]').value=preferred;
      else{const ready=providers.find(p=>p.enabled&&p.configured);if(ready)q('[data-voice-provider]').value=ready.id;}
      try{const projects=await call('projects.list',{limit:50});q('[data-voice-project]').innerHTML='<option value="">Ask me which project</option>'+projects.items.map(p=>`<option value="${esc(p.id)}">${esc(p.name||p.id)}</option>`).join('');if(projects.items.some(p=>p.id===project))q('[data-voice-project]').value=project;}catch{}
    }
    if(!dialog.open)dialog.showModal();controls();DMUI.sync();
  }
  document.addEventListener('click',e=>{if(e.target.closest('[data-ai-voice-open]'))open();});
  window.addEventListener('pagehide',()=>stop());
  return {open,start,stop,provider:()=>active?.provider||'',state:()=>phase};
})();
