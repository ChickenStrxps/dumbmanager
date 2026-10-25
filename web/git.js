'use strict';
// UI only: fixed Git operations, repository boundaries and write receipts live in DumbAPI.
window.DMGit=(()=>{
  let projects=[],repo='',data=null,tab='changes',offset=0,historyOffset=0,history=null,revision='',commitFiles=[],diff=null;
  let loading=false,busy=false,error='',notice='',generation=0,signature='',pending=null;
  const drafts=new Map(),tabs={changes:'Changes',history:'History',branches:'Branches',remotes:'Sync',stash:'Stash'};
  const root=()=>$('#git-workspace'),button=(action,text,attrs='',kind='secondary')=>`<button type="button" class="${kind}" data-git="${action}" ${attrs} ${busy||pending||loading?'disabled':''}>${text}</button>`;
  const attr=s=>esc(s),row=(title,sub,actions)=>`<div class="git-row"><div class="git-row-copy"><b title="${attr(title)}">${esc(title)}</b>${sub?`<small>${esc(sub)}</small>`:''}</div><div class="git-row-actions">${actions}</div></div>`;
  const draft=()=>drafts.get(repo)||'';
  function keepPending(value){pending=value;try{value?sessionStorage.setItem('dm-git-pending',JSON.stringify(value)):sessionStorage.removeItem('dm-git-pending');}catch{}}
  function render(force=false){
    if(view!=='git')return;
    const stamp=JSON.stringify([projects,repo,data,tab,offset,history,revision,commitFiles,diff,loading,busy,error,notice,pending]);
    if(!force&&stamp===signature)return;signature=stamp;
    $('#feed-count').textContent=data?.repository?`${data.total} CHANGED`:'PROJECT GIT';
    const options=projects.map(p=>`<option value="${attr(p.id)}" ${p.id===repo?'selected':''}>${esc(p.name)}${p.repository?' · Git':''}</option>`).join('');
    const toolbar=`<div class="git-toolbar"><label class="sr" for="git-project">Git project</label><select id="git-project" ${busy||pending||loading?'disabled':''}>${options||'<option value="">Choose a project</option>'}</select><button data-git="refresh" class="secondary" ${busy||loading?'disabled':''}>Refresh ↻</button>${button('clone','Clone +','','quiet')}</div>`;
    const status=`<div class="git-status" role="status">${loading?'<span class="ascii-token" data-ascii="load" aria-hidden="true">[/ ···]</span> Checking Git…':busy?'<span class="ascii-token" data-ascii="load" aria-hidden="true">[/ ···]</span> Working…':error?esc(error):data?.repository?`<span class="amber">⑂ ${esc(data.branch==='(detached)'?'Detached HEAD':data.branch)}</span><span>${data.ahead} ahead · ${data.behind} behind</span><span>${notice?esc(notice):data.time?'Checked '+age(data.time):''}</span>`:notice?esc(notice):'Your project, your history.'}</div>`;
    const retry=pending?`<div class="git-retry"><span>Reply unconfirmed · ${esc(pending.args.operation||'clone')}. Check status before clearing.</span><button data-git="retry" class="primary" ${busy?'disabled':''}>Retry same action</button><button data-git="clear-retry" class="quiet" ${busy?'disabled':''}>Clear retry</button></div>`:'';
    let content='';
    if(!data)content=`<div class="git-empty"><pre aria-hidden="true">  o──o──o
     ╲
      o</pre><h3>${loading?'Finding your repos…':'Pick a project.'}</h3><p>Changes, commits and branches, in one spot.</p></div>`;
    else if(!data.repository)content=`<div class="git-empty"><pre aria-hidden="true">[ + ] ── o ── o</pre><h3>No Git here yet.</h3><p>Start a history for ${esc(projects.find(p=>p.id===repo)?.name||repo)}.</p>${button('init','Start a repo','','primary')}</div>`;
    else if(tab==='changes'){
      const list=data.files.map(f=>`<div class="git-file ${diff?.path===f.path&&!revision?'selected':''}"><button class="git-file-name" data-git="file" data-path="${attr(f.path)}" ${f.sensitive?'disabled':''}><code>${esc(f.status)}</code><span title="${attr(f.path)}">${esc(f.path)}</span>${f.conflict?'<span class="git-warning">conflict</span>':f.sensitive?'<span>protected</span>':''}</button><div class="git-row-actions">${f.unstaged?button('stage','+ Stage',`data-path="${attr(f.path)}" ${f.sensitive?'disabled':''}`):''}${f.staged?button('unstage','− Unstage',`data-path="${attr(f.path)}" ${f.sensitive?'disabled':''}`,'quiet'):''}</div></div>`).join('');
      content=`<div class="git-change-bar"><span>${data.staged_count} staged${data.conflict_count?' · '+data.conflict_count+' conflicts':''}</span><div>${button('stage-page','Stage shown',data.files.some(f=>f.unstaged&&!f.sensitive)?'':'disabled','quiet')}${button('commit','Commit ↗',data.staged_count&&!data.conflict_count?'':'disabled','primary')}</div></div><div class="git-split ${diff?'has-diff':''}"><section class="git-list" aria-label="Changed files">${list||'<div class="git-empty"><pre data-ascii="spark" aria-hidden="true">· + ·</pre><h3>Clean. Nothing to commit.</h3></div>'}${pager(offset,data.next_offset,'files')}</section>${diffPanel()}</div>`;
    }else if(tab==='history'){
      content=revision?`<div class="git-change-bar">${button('history-back','← History','','quiet')}<code>${esc(revision.slice(0,9))}</code></div><div class="git-split ${diff?'has-diff':''}"><section class="git-list">${commitFiles.map(f=>row(f.path,'',`<button class="secondary" data-git="file" data-path="${attr(f.path)}" ${f.sensitive?'disabled':''}>Diff ↗</button>`)).join('')||'<p class="muted">No file changes in this commit.</p>'}</section>${diffPanel()}</div>`:
        `<div class="git-list">${(history?.items||[]).map(c=>`<button class="git-history" data-git="revision" data-revision="${attr(c.id)}"><code>${esc(c.id.slice(0,8))}</code><span><b>${esc(c.subject)}</b><small>${esc(c.author)} · <time datetime="${attr(c.at)}">${esc(new Date(c.at).toLocaleString())}</time></small></span><span>↗</span></button>`).join('')||'<div class="git-empty"><h3>No commits yet.</h3></div>'}${pager(historyOffset,history?.next_offset,'history')}</div>`;
    }else if(tab==='branches')content=`<div class="git-change-bar"><span>${data.branches_total} local branches</span>${button('branch-new','New branch +','','primary')}</div><div class="git-list">${(data.branches||[]).map(b=>row(b.name,b.name===data.branch?'You are here':b.upstream||b.head.slice(0,8),b.name===data.branch?'<span class="badge">CURRENT</span>':button('branch_switch','Switch',`data-branch="${attr(b.name)}"`)+button('merge_ff','Merge FF',`data-branch="${attr(b.name)}"`,'quiet')+button('branch_delete','Delete',`data-branch="${attr(b.name)}"`,'quiet'))).join('')}${data.branches_total>300?'<p class="muted">Showing the first 300 branches.</p>':''}</div>`;
    else if(tab==='remotes')content=`<div class="git-change-bar"><span>Pull fast-forward · push this branch</span>${button('remote-new','Add remote +','','primary')}</div><div class="git-list">${(data.remotes||[]).map(r=>row(r.name,r.fetch,button('fetch','Fetch',`data-remote="${attr(r.name)}"`)+button('pull','Pull',`data-remote="${attr(r.name)}"`)+button('push','Push ↗',`data-remote="${attr(r.name)}"`,'primary')+button('remote_remove','Remove',`data-remote="${attr(r.name)}"`,'quiet'))+`<p class="git-destination">Push → ${esc(r.push)}</p>`).join('')||'<div class="git-empty"><h3>No remote connected.</h3><p>Add your repository address to sync.</p></div>'}</div>`;
    else if(tab==='stash')content=`<div class="git-change-bar"><span>Git stashes · separate from your itch pile</span>${button('stash-new','Stash changes',data.total?'':'disabled','primary')}</div><div class="git-list">${(data.stashes||[]).map(s=>row(s.message,s.id.slice(0,9),button('stash_apply','Apply',`data-stash="${attr(s.id)}"`)+button('stash_drop','Drop',`data-stash="${attr(s.id)}"`,'quiet'))).join('')||'<div class="git-empty"><pre aria-hidden="true">[ stash ] → [ empty ]</pre><h3>No stashed changes.</h3></div>'}</div>`;
    const nav=data?.repository?`<nav class="git-tabs" role="tablist" aria-label="Git workspace">${Object.entries(tabs).map(([id,name])=>`<button id="git-tab-${id}" role="tab" aria-selected="${id===tab}" aria-controls="git-panel" tabindex="${id===tab?0:-1}" data-git-tab="${id}">${name}</button>`).join('')}</nav>`:'';
    root().innerHTML=toolbar+status+retry+nav+`<section id="git-panel" class="git-panel" ${data?.repository?`role="tabpanel" aria-labelledby="git-tab-${tab}"`:'aria-label="Git project"'} aria-busy="${loading||busy}">${content}</section>`;
    if(loading||busy)root().querySelectorAll('button,select').forEach(el=>el.disabled=true);
    DMUI.sync();
  }
  function pager(current,next,kind){return current||next!=null?`<nav class="result-pages" aria-label="Git ${kind} pages"><button class="secondary" data-git="page" data-kind="${kind}" data-offset="${Math.max(0,current-(kind==='files'?30:15))}" ${!current||loading?'disabled':''}>← Back</button><span>${current+1}+</span><button class="secondary" data-git="page" data-kind="${kind}" data-offset="${next}" ${next==null||loading?'disabled':''}>More →</button></nav>`:'';}
  function diffPanel(){return diff?`<section class="git-diff" aria-label="File diff"><div class="git-diff-head"><button data-git="diff-close" class="quiet">← Files</button><b title="${attr(diff.path)}">${esc(diff.path)}</b>${!revision?`<button data-git="diff-side" class="secondary">${diff.staged?'Staged':'Working tree'} ⇄</button>`:''}</div><pre tabindex="0" aria-label="Diff text">${diff.text.split('\n').map(line=>`<span class="${line.startsWith('+')?'diff-add':line.startsWith('-')?'diff-remove':line.startsWith('@@')?'diff-hunk':''}">${esc(line)}</span>`).join('\n')||'No text changes on this side.'}</pre>${diff.truncated?'<p class="muted">Preview truncated at 160,000 characters.</p>':''}</section>`:'<section class="git-diff git-diff-empty"><pre aria-hidden="true">[-] → [+]</pre><p>Pick a file. See what changed.</p></section>';}
  async function enter(saved){
    if(loading||busy)return;
    if(saved&&typeof saved.repo==='string'&&saved.repo.length<=200)repo=saved.repo;
    if(saved&&Object.hasOwn(tabs,saved.tab))tab=saved.tab;
    if(!repo)repo=pending?.args.project||(project!=='unsorted'?project:'');
    await load(true);
  }
  async function load(refreshProjects=false){
    const token=++generation;loading=true;error='';render();
    try{
      if(refreshProjects){const result=await call('git.projects');if(token!==generation)return;projects=result.items;if(!projects.some(p=>p.id===repo))repo=projects.find(p=>p.repository)?.id||projects[0]?.id||'';}
      if(!repo){data=null;return;}
      const chosen=repo,reply=await call('git.status',{project:chosen,limit:30,offset});
      if(token!==generation||repo!==chosen)return;data=reply;
      if(reply.total&&offset>=reply.total){offset=0;return load();}
      if(tab==='history'&&!revision){const h=await call('git.history',{project:chosen,limit:15,offset:historyOffset});if(token===generation)history=h;}
      if(diff){const d=await call('git.diff',{project:chosen,path:diff.path,staged:diff.staged,revision});if(token===generation)diff=d;}
    }catch(e){if(token===generation)error=e.message;}
    finally{if(token===generation){loading=false;render();}}
  }
  function address(value){
    if(/^https?:\/\//i.test(value)){const u=new URL(value);if(u.protocol!=='https:'||u.username||u.password||u.search||u.hash)throw new Error('Use HTTPS without a password or token in the address.');}
    if(/^ssh:\/\//i.test(value)&&new URL(value).password)throw new Error('Use SSH keys without a password in the address.');
    return value;
  }
  async function execute(operation,args={},saved=null){
    if(busy||(!saved&&pending))return false;
    const record=saved||{name:operation==='clone'?'git.clone':'git.action',args:operation==='clone'?{...args,request_key:uid()}:{project:repo,operation,snapshot:data.snapshot,...args,request_key:uid()}};
    busy=true;error='';notice='';keepPending(record);render();
    try{
      const reply=await call(record.name,record.args);keepPending(null);notice=(reply.replayed?'Already completed · ':'Done · ')+(record.args.operation||'clone').replaceAll('_',' ');
      if(operation==='commit')drafts.delete(record.args.project);
      if(operation==='clone'){repo=reply.project;data=null;offset=historyOffset=0;revision='';}
      diff=null;await load(true);return true;
    }catch(e){
      // A lost response must reuse this key, never silently repeat a write.
      if(!e.network&&e.status&&e.status<500&&!/uncertain|running/i.test(e.message))keepPending(null);
      await load();error=e.message;return false;
    }finally{busy=false;render();}
  }
  function confirm(operation,title,description,args={}){
    const fixed={project:repo,operation,snapshot:data.snapshot,...args,request_key:uid()};
    dialog(title,`<p class="git-confirm-repo">${esc(projects.find(p=>p.id===repo)?.name||repo)} · ${esc(data.branch||'new repo')}</p><p>${esc(description)}</p>`,'Do it ↗',()=>execute(operation,{}, {name:'git.action',args:fixed}));
  }
  function form(operation,title,fields,submit,extra={}){
    const fixedRepo=repo,fixedSnapshot=data?.snapshot;
    dialog(title,fields,submit,async()=>{
      const args={...extra};for(const input of $('#dialog-content').querySelectorAll('[data-git-field]'))args[input.dataset.gitField]=input.value.trim();
      if(args.url)args.url=address(args.url);
      if(operation==='commit'){drafts.set(fixedRepo,args.message);if(!args.message)throw new Error('Add a commit message.');}
      return execute(operation,operation==='clone'?args:{...args,project:fixedRepo,snapshot:fixedSnapshot});
    });
  }
  async function click(e){
    const el=e.target.closest('[data-git],[data-git-tab]');if(!el||!root().contains(el))return;
    if(loading||busy)return;
    try{
      if(el.dataset.gitTab){if(busy)return;tab=el.dataset.gitTab;revision='';diff=null;historyOffset=0;render();if(tab==='history')await load();return;}
      const action=el.dataset.git;
      if(action==='refresh'){await load(true);return;}
      if(action==='diff-close'){diff=null;render();return;}
      if(action==='file'||action==='diff-side'){
        const path=el.dataset.path||diff?.path,staged=action==='diff-side'?!diff.staged:!revision&&!!data.files.find(f=>f.path===path)?.staged&&!data.files.find(f=>f.path===path)?.unstaged;
        const p=repo,r=revision;loading=true;render();try{const answer=await call('git.diff',{project:p,path,staged,revision:r});if(p===repo&&r===revision)diff=answer;}finally{loading=false;render();}return;
      }
      if(action==='history-back'){revision='';diff=null;await load();return;}
      if(action==='revision'){const r=el.dataset.revision,p=repo;loading=true;render();try{const answer=await call('git.history',{project:p,revision:r});if(p===repo){revision=r;commitFiles=answer.files;diff=null;}}finally{loading=false;render();}return;}
      if(action==='page'){if(el.dataset.kind==='files')offset=Number(el.dataset.offset);else historyOffset=Number(el.dataset.offset);diff=null;await load();return;}
      if(busy)return;
      if(action==='retry'){await execute(pending.args.operation||'clone',{},pending);return;}
      if(action==='clear-retry'){dialog('Checked the result?', '<p>Clear this retry only after checking the repository. A running or interrupted action may have already changed it.</p>', 'Clear retry',()=>{keepPending(null);render();});return;}
      if(pending)return;
      if(action==='stage'||action==='unstage'){await execute(action,{paths:JSON.stringify([el.dataset.path])});return;}
      if(action==='stage-page'){await execute('stage',{paths:JSON.stringify(data.files.filter(f=>f.unstaged&&!f.sensitive).map(f=>f.path))});return;}
      if(action==='commit'){form('commit','Ship this checkpoint.',`<p>${data.staged_count} staged files · ${esc(data.branch)}</p><label for="git-message">Commit message</label><textarea id="git-message" data-git-field="message" maxlength="4000" rows="3">${esc(draft())}</textarea><p class="muted">Commits the staged changes. Your Git identity, hooks and signing settings apply.</p>`,'Commit ↗');return;}
      if(action==='init'){form('init','Start your history.', '<label for="git-new-branch">First branch</label><input id="git-new-branch" data-git-field="branch" value="main">','Start repo');return;}
      if(action==='clone'){form('clone','Bring a repo home.', '<label for="git-url">Repository address · HTTPS / SSH</label><input id="git-url" data-git-field="url" autocomplete="off" placeholder="https://github.com/you/project.git"><label for="git-folder">New project folder</label><input id="git-folder" data-git-field="name" placeholder="my-project"><p class="muted">Clones into a new Projects folder using your installed Git authentication.</p>','Clone ↗');return;}
      if(action==='branch-new'){form('branch_create','New branch. Fresh lane.', '<label for="git-new-branch">Branch name</label><input id="git-new-branch" data-git-field="branch" placeholder="feature/my-idea"><p class="muted">Creates and switches to this branch. Current changes stay with you.</p>','Create + switch');return;}
      if(action==='remote-new'){form('remote_add','Connect a remote.', '<label for="git-remote">Name</label><input id="git-remote" data-git-field="remote" value="origin"><label for="git-url">Repository address · HTTPS / SSH</label><input id="git-url" data-git-field="url" autocomplete="off" placeholder="https://github.com/you/project.git">','Connect');return;}
      if(action==='stash-new'){form('stash_save','Stash these changes', '<label for="git-stash-note">Name this Git stash</label><input id="git-stash-note" data-git-field="message" placeholder="Work in progress"><p class="muted">Saves tracked and untracked changes, then clears them from the working tree. Ignored files stay.</p>','Stash changes');return;}
      const branch=el.dataset.branch,remote=el.dataset.remote,stash_id=el.dataset.stash;
      const descriptions={branch_switch:`Switch to ${branch}. Commit or stash current changes first.`,branch_delete:`Delete the merged local branch ${branch}.`,merge_ff:`Fast-forward ${data.branch} to ${branch}. Diverged branches need a separate merge.`,remote_remove:`Remove ${remote} from this repo. The remote repository stays.`,fetch:`Fetch updates from ${remote}. Your working files stay.`,pull:`Pull ${remote}/${data.branch} into ${data.branch}, only if it fast-forwards.`,push:`Push ${data.branch} to ${remote}. This writes to the remote repository.`,stash_apply:'Apply this Git stash, keeping the saved copy.',stash_drop:'Permanently remove this saved Git stash.'};
      if(descriptions[action]){const args={};if(branch)args.branch=branch;if(remote){args.remote=remote;if(['pull','push'].includes(action))args.branch=data.branch;}if(stash_id)args.stash_id=stash_id;
        const destination=data.remotes?.find(r=>r.name===remote);confirm(action,({push:'Ready to push?',pull:'Bring it up to date?',fetch:'Check for updates?',stash_drop:'Drop this Git stash?'})[action]||'Make this move?',descriptions[action]+(destination?' Destination: '+(action==='push'?destination.push:destination.fetch):''),args);}
    }catch(e){error=e.message;render();toast(e.message);}
  }
  function init(){
    try{const value=JSON.parse(sessionStorage.getItem('dm-git-pending')||'null');if(value&&['git.action','git.clone'].includes(value.name)&&value.args?.request_key)pending=value;}catch{}
    document.addEventListener('click',click);
    document.addEventListener('change',e=>{if(e.target.id==='git-project'&&!busy&&!pending){repo=e.target.value;data=null;diff=null;revision='';history=null;offset=historyOffset=0;notice='';load();}});
    document.addEventListener('input',e=>{if(e.target.id==='git-message')drafts.set(repo,e.target.value);});
    document.addEventListener('keydown',e=>{if(e.target.matches('[data-git-tab]')&&['ArrowLeft','ArrowRight','Home','End'].includes(e.key)){e.preventDefault();const ids=Object.keys(tabs),i=ids.indexOf(tab);const id=ids[e.key==='Home'?0:e.key==='End'?ids.length-1:(i+(e.key==='ArrowRight'?1:ids.length-1))%ids.length];root().querySelector(`[data-git-tab="${id}"]`).click();root().querySelector(`[data-git-tab="${id}"]`)?.focus();}});
  }
  return {init,enter,render,page:()=>({repo,tab})};
})();
