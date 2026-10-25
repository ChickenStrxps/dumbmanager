'use strict';
// A local reading trail. No command execution, chat polling or acceptance actions.
window.DMLearning=(()=>{
  let id='',pack=null,section='learn',lessonId='',generation=0,saving=false;
  const revealed=new Set();
  const dialog=()=>$('#learning-view');
  const current=()=>pack?.lessons.find(l=>l.id===lessonId)||pack?.lessons[0];
  const page=()=>dialog()?.open?{itch:id,section,lesson:lessonId}:null;
  function status(message){$('#learning-status').textContent=message;}
  function sources(ids){
    const list=ids.map(id=>pack.sources.find(s=>s.id===id)).filter(Boolean);
    return '<details class="learning-sources"><summary>Where this comes from</summary>'+list.map(s=>'<div><b>'+esc(s.label)+'</b><pre>'+esc(s.text)+'</pre></div>').join('')+'</details>';
  }
  function paint(){
    const body=$('#learning-body');
    if(!pack)return;
    $('#learning-itch-title').textContent=pack.title;
    $('#learning-stage').textContent=pack.stage;
    $('#learning-coverage').textContent=pack.coverage;
    $('#learning-workspace').textContent=(pack.workspace||'Workspace not recorded')+(pack.environment?' · '+pack.environment:'');
    $('#learning-workspace-note').textContent=pack.workspace_note;
    $('#learning-stale').hidden=!pack.notes_stale;
    $('#learning-navigation').hidden=!pack.eligible;
    $('#learning-commands-count').textContent=pack.commands.length;
    $('#learning-tools-count').textContent=pack.packages.length;
    document.querySelectorAll('[data-learning-section]').forEach(b=>b.setAttribute('aria-pressed',b.dataset.learningSection===section));
    const read=pack.progress.read;
    $('#learning-progress').max=pack.progress.total||1;$('#learning-progress').value=read.length;
    $('#learning-read-count').textContent=read.length+' / '+pack.progress.total+' lessons read';
    if(!pack.eligible){body.innerHTML='<h3 id="learning-section-title">The work is still open</h3><p>A learning trail is available when this itch is ready for review or accepted. Its earlier notes stay saved.</p>';return;}
    if(section==='commands'){
      body.innerHTML='<h3 id="learning-section-title">Commands from this itch</h3><p>Read the arguments and workspace before reusing a command.</p>'+ (pack.commands.length?pack.commands.map((c,i)=>'<article class="learning-tool"><span class="eyebrow">'+esc(c.kind)+'</span><pre><code>'+esc(c.command)+'</code></pre><p>'+esc(c.explanation)+'</p>'+(c.caution?'<p class="learning-caution">'+esc(c.caution)+'</p>':'')+'<button type="button" class="secondary" data-learning-copy="'+i+'">Copy command</button>'+sources(c.source_ids)+'</article>').join(''):'<div class="learning-empty"><b>No command log was saved.</b><p>A report such as “tests passed” does not tell us the exact command. Future working agents are asked to preserve the commands they actually used.</p></div>');
      return;
    }
    if(section==='tools'){
      body.innerHTML='<h3 id="learning-section-title">Tools & package tips</h3><p>Linked to mentions in saved work. Installed versions are not inferred.</p>'+(pack.packages.length?pack.packages.map(p=>'<article class="learning-tool"><span class="eyebrow">'+esc(p.kind)+'</span><h4>'+esc(p.name)+'</h4><p>'+esc(p.tip)+'</p>'+(p.docs?'<a class="text-link" href="'+esc(p.docs)+'" target="_blank" rel="noopener noreferrer">Official reference ↗</a>':'')+sources(p.source_ids)+'</article>').join(''):'<div class="learning-empty"><b>No tool or package tips recorded yet.</b><p>The trail does not guess dependencies from the title. An agent can add tips grounded in this itch’s recorded work.</p></div>');
      return;
    }
    const item=current();if(!item)return;
    lessonId=item.id;const index=pack.lessons.indexOf(item),done=read.includes(item.id),shown=revealed.has(item.id);
    body.innerHTML='<nav class="learning-steps" aria-label="Lessons">'+pack.lessons.map((l,i)=>'<button type="button" data-learning-lesson="'+esc(l.id)+'" '+(l.id===lessonId?'aria-current="step"':'')+'><span aria-hidden="true">'+(read.includes(l.id)?'✓':String(i+1).padStart(2,'0'))+'</span> '+esc(l.title)+'</button>').join('')+'</nav>'+ 
      '<article class="learning-lesson"><span class="eyebrow">LESSON '+(index+1)+' / '+pack.lessons.length+'</span><h3 id="learning-section-title" tabindex="-1">'+esc(item.title)+'</h3><p class="learning-explanation">'+esc(item.explanation)+'</p><div class="learning-practice"><b>Try thinking it through</b><p>'+esc(item.try_this)+'</p></div><div class="learning-check"><b>Quick check</b><p>'+esc(item.question)+'</p><button type="button" class="quiet" data-learning-reveal aria-expanded="'+shown+'" aria-controls="learning-answer">'+(shown?'Hide answer':'Show answer')+'</button><p id="learning-answer" '+(shown?'':'hidden')+'>'+esc(item.answer)+'</p></div>'+sources(item.source_ids)+'<div class="learning-controls"><button type="button" class="secondary" data-learning-prev '+(!index?'disabled':'')+'>← Previous</button><button type="button" class="primary" data-learning-read '+(saving?'disabled':'')+'>'+ (saving?'Saving…':done?'Mark unread':'Mark as read')+'</button><button type="button" class="secondary" data-learning-next '+(index===pack.lessons.length-1?'disabled':'')+'>Next →</button></div></article>';
  }
  async function load(){
    const token=++generation,wanted=id;
    status('Reading this itch’s saved work…');$('#learning-refresh').disabled=true;
    try{
      const data=await call('manager.learning.get',{id:wanted});
      if(token!==generation||!dialog().open)return;
      pack=data;saving=false;paint();status(pack.notes_stale?'The work changed since its authored notes. Showing the current saved-work trail.':'');
    }catch(e){if(token===generation&&dialog().open)status(e.message+' Use Refresh to try again.');}
    finally{if(token===generation)$('#learning-refresh').disabled=false;}
  }
  async function open(itch,restore={}){
    id=itch;pack=null;section=['learn','commands','tools'].includes(restore.section)?restore.section:'learn';lessonId=restore.lesson||'';saving=false;revealed.clear();
    $('#learning-itch-title').textContent=state.itches.find(r=>r.id===id)?.title||'This itch';
    $('#learning-body').replaceChildren();$('#learning-navigation').hidden=true;$('#learning-stale').hidden=true;
    $('#learning-stage').textContent='';$('#learning-workspace').textContent='';$('#learning-workspace-note').textContent='';$('#learning-coverage').textContent='';
    $('#learning-read-count').textContent='';$('#learning-progress').value=0;
    if(!dialog().open)dialog().showModal();dialog().scrollTop=0;
    rememberPage();await load();rememberPage();
  }
  async function mark(){
    if(saving||!pack||!current())return;
    const token=generation,item=current(),old=pack;
    saving=true;status('');paint();
    try{
      const data=await call('manager.learning.progress',{id,revision:old.revision,lesson_id:item.id,
        done:!old.progress.read.includes(item.id),expected_version:old.progress.version,request_key:uid()});
      if(token!==generation||!dialog().open)return;
      pack=data;status((data.progress.read.includes(item.id)?'Lesson marked read.':'Lesson marked unread.')+(data.progress.read.length===data.progress.total?' Trail read. Come back whenever you need it.':''));
    }catch(e){
      if(token!==generation||!dialog().open)return;
      // A lost response may already have committed. Refresh reads the truth;
      // another tap uses the newly read progress, never a blind retry toggle.
      const refreshGeneration=generation+1;await load();if(generation===refreshGeneration&&dialog().open)status(e.message+' Progress refreshed from DumbAPI.');
    }finally{if(token===generation){saving=false;paint();$('[data-learning-read]')?.focus({preventScroll:true});}}
  }
  async function copy(index,button){
    const command=pack?.commands[index]?.command;if(!command)return;
    const token=generation;button.disabled=true;let timer;
    try{
      if(!navigator.clipboard?.writeText)throw new Error('Clipboard unavailable');
      await Promise.race([navigator.clipboard.writeText(command),new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error('Clipboard did not respond')),2500);})]);
      if(token===generation)status('Command copied.');
    }catch{
      if(token!==generation||!dialog().open)return;
      document.getElementById('learning-copy-fallback')?.remove();
      const label=document.createElement('label');label.id='learning-copy-fallback';label.textContent='Clipboard blocked. Select and copy this command:';
      const field=document.createElement('textarea');field.readOnly=true;field.value=command;field.setAttribute('aria-label','Command to copy');label.append(field);button.after(label);field.focus();field.select();
      status('The command is selected for manual copying.');
    }finally{clearTimeout(timer);button.disabled=false;}
  }
  function init(){
    $('#learning-close').onclick=()=>dialog().close();$('#learning-refresh').onclick=load;
    dialog().addEventListener('close',()=>{generation++;saving=false;$('#learning-refresh').disabled=false;rememberPage();});
    $('#learning-navigation').onclick=e=>{const b=e.target.closest('[data-learning-section]');if(!b||!pack)return;section=b.dataset.learningSection;paint();status('');b.focus();rememberPage();};
    $('#learning-body').onclick=e=>{
      const b=e.target.closest('button');if(!b||!pack)return;
      if(b.dataset.learningLesson){lessonId=b.dataset.learningLesson;paint();$('#learning-section-title').focus({preventScroll:true});rememberPage();}
      else if(b.hasAttribute('data-learning-reveal')){revealed.has(lessonId)?revealed.delete(lessonId):revealed.add(lessonId);paint();$('[data-learning-reveal]').focus({preventScroll:true});}
      else if(b.hasAttribute('data-learning-read'))mark();
      else if(b.hasAttribute('data-learning-next')||b.hasAttribute('data-learning-prev')){const i=pack.lessons.indexOf(current())+(b.hasAttribute('data-learning-next')?1:-1);if(pack.lessons[i]){lessonId=pack.lessons[i].id;paint();$('#learning-section-title').focus({preventScroll:true});rememberPage();}}
      else if(b.hasAttribute('data-learning-copy'))copy(Number(b.dataset.learningCopy),b);
    };
  }
  return {init,open,page};
})();
