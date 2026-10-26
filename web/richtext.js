'use strict';
// Small, bounded Markdown view. Source HTML is always text; only this renderer
// creates markup. No remote renderer, model call or runtime dependency.
window.DMRich=(()=>{
  const escape=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function url(raw){
    if(/[\s\u0000-\u001f\u007f]/.test(raw))return null;
    try{const u=new URL(raw);return ['http:','https:'].includes(u.protocol)&&!u.username&&!u.password?u.href:/^mailto:[^<>]+$/i.test(raw)?raw:/^t3-thread:\/\/v1\/[\da-f-]{36}$/i.test(raw)?raw:null;}catch{return null;}
  }
  function inline(source,depth=0){
    if(depth>6)return escape(source);
    let out='',i=0;
    while(i<source.length){
      const rest=source.slice(i);let m;
      if((m=/^\\([\\`*_{}\[\]()#+.!>|~-])/.exec(rest))){out+=escape(m[1]);i+=m[0].length;continue;}
      if((m=/^(`+)([\s\S]*?)\1(?!`)/.exec(rest))){out+='<code>'+escape(m[2])+'</code>';i+=m[0].length;continue;}
      if((m=/^(!?)\[([^\]\n]{1,600})\]\(([^\s()]+)(?:\s+"[^"\n]*")?\)/.exec(rest))){
        const href=url(m[3]);out+=href?'<a href="'+escape(href)+'" target="_blank" rel="noopener noreferrer">'+(m[1]?'[image] ':'')+inline(m[2],depth+1)+'</a>':escape(m[0]);i+=m[0].length;continue;
      }
      if((m=/^<(https?:\/\/[^<>\s]+)>/.exec(rest))){const href=url(m[1]);out+=href?'<a href="'+escape(href)+'" target="_blank" rel="noopener noreferrer">'+escape(m[1])+'</a>':escape(m[0]);i+=m[0].length;continue;}
      if((i===0||/[\s(]/.test(source[i-1]))&&(m=/^https?:\/\/[^\s<>]+/.exec(rest))){
        const raw=m[0].replace(/[.,;!?)]+$/,'');const href=url(raw);if(href){out+='<a href="'+escape(href)+'" target="_blank" rel="noopener noreferrer">'+escape(raw)+'</a>';i+=raw.length;continue;}
      }
      const marker=['**','__','~~','*','_'].find(s=>rest.startsWith(s)&&rest.indexOf(s,s.length)>s.length);
      if(marker){const end=rest.indexOf(marker,marker.length),tag=marker.length===1?'em':marker==='~~'?'del':'strong';out+='<'+tag+'>'+inline(rest.slice(marker.length,end),depth+1)+'</'+tag+'>';i+=end+marker.length;continue;}
      out+=source[i]==='\n'?'<br>':escape(source[i]);i++;
    }
    return out;
  }
  function cells(line){
    // Pipes within inline code and escaped pipes are not column boundaries.
    const result=[];let value='',ticks=0;
    for(let i=0;i<line.length;i++){const c=line[i];if(c==='\\'&&line[i+1]==='|'){value+='|';i++;continue;}if(c==='`')ticks^=1;if(c==='|'&&!ticks){result.push(value.trim());value='';}else value+=c;}
    result.push(value.trim());if(line.trim().startsWith('|'))result.shift();if(line.trim().endsWith('|'))result.pop();return result.slice(0,16);
  }
  const list=line=>/^(\s*)([-+*]|\d+[.)])\s+(.*)$/.exec(line);
  const divider=line=>cells(line).length>0&&cells(line).every(c=>/^:?-{3,}:?$/.test(c));
  function blocks(lines,depth=0){
    if(depth>8)return '<p>'+inline(lines.join('\n'))+'</p>';
    let out='',i=0;
    const special=j=>/^\s*$|^ {0,3}(`{3,}|~{3,})|^#{1,6}\s|^>\s?|^ {0,3}(?:-{3,}|\*{3,}|_{3,})\s*$/.test(lines[j])||list(lines[j])||(j+1<lines.length&&lines[j].includes('|')&&divider(lines[j+1]));
    while(i<lines.length){
      let line=lines[i],m;if(!line.trim()){i++;continue;}
      if((m=/^ {0,3}(`{3,}|~{3,})([^`]*)$/.exec(line))){
        const fence=m[1],lang=m[2].trim().slice(0,40);i++;const content=[];
        while(i<lines.length&&!new RegExp('^ {0,3}'+fence[0]+'{'+fence.length+',}\\s*$').test(lines[i]))content.push(lines[i++]);
        if(i<lines.length)i++;
        out+='<div class="code-block"><div class="code-head"><span>'+escape(lang||'TEXT')+'</span><button type="button" class="quiet" data-copy-code>Copy code</button></div><pre tabindex="0"><code>'+escape(content.join('\n'))+'</code></pre></div>';continue;
      }
      if((m=/^(#{1,6})\s+(.*)$/.exec(line))){const level=Math.min(6,m[1].length+1);out+='<h'+level+'>'+inline(m[2].replace(/\s+#+\s*$/,''))+'</h'+level+'>';i++;continue;}
      if(/^ {0,3}(?:-{3,}|\*{3,}|_{3,})\s*$/.test(line)){out+='<hr>';i++;continue;}
      if(/^>\s?/.test(line)){const quote=[];while(i<lines.length&&/^>\s?/.test(lines[i]))quote.push(lines[i++].replace(/^>\s?/,''));out+='<blockquote>'+blocks(quote,depth+1)+'</blockquote>';continue;}
      if(i+1<lines.length&&line.includes('|')&&divider(lines[i+1])){
        const header=cells(line),align=cells(lines[i+1]).map(c=>c.startsWith(':')&&c.endsWith(':')?'center':c.endsWith(':')?'right':'left');
        out+='<div class="table-scroll" role="region" aria-label="Message table" tabindex="0"><table><thead><tr>'+header.map((c,n)=>'<th class="align-'+align[n]+'">'+inline(c)+'</th>').join('')+'</tr></thead><tbody>';i+=2;
        while(i<lines.length&&lines[i].trim()&&lines[i].includes('|')&&!divider(lines[i])){const row=cells(lines[i++]);out+='<tr>'+header.map((_,n)=>'<td class="align-'+align[n]+'">'+inline(row[n]||'')+'</td>').join('')+'</tr>';}
        out+='</tbody></table></div>';continue;
      }
      if((m=list(line))){
        const indent=m[1].length,ordered=/^\d/.test(m[2]),tag=ordered?'ol':'ul';out+='<'+tag+(ordered?' start="'+Number.parseInt(m[2],10)+'"':'')+'>';
        while(i<lines.length){const current=list(lines[i]);if(!current||current[1].length!==indent||/^\d/.test(current[2])!==ordered)break;
          const body=[current[3]],padding=current[1].length+current[2].length+1;i++;
          while(i<lines.length){const next=list(lines[i]);if(next&&next[1].length<=indent)break;if(lines[i].trim()&&lines[i].search(/\S/)>indent){body.push(lines[i].slice(Math.min(padding,lines[i].search(/\S/))));i++;}else if(!lines[i].trim()&&i+1<lines.length&&lines[i+1].search(/\S/)>indent){body.push('');i++;}else break;}
          const task=/^\[([ xX])\]\s+/.exec(body[0]);if(task)body[0]=body[0].slice(task[0].length);
          out+='<li'+(task?' class="markdown-task"':'')+'>'+(task?'<span class="task-mark" aria-label="'+(task[1].trim()?'Completed':'Not completed')+'">'+(task[1].trim()?'[x]':'[ ]')+'</span>':'')+blocks(body,depth+1)+'</li>';
        }
        out+='</'+tag+'>';continue;
      }
      const paragraph=[line];i++;while(i<lines.length&&!special(i))paragraph.push(lines[i++]);out+='<p>'+inline(paragraph.join('\n'))+'</p>';
    }
    return out;
  }
  function render(text){return blocks(String(text||'').slice(0,12000).replace(/\r\n?/g,'\n').replace(/\t/g,'    ').split('\n'));}
  function time(at){const date=new Date(at);if(!at||!Number.isFinite(date.valueOf()))return '<span class="message-time">Time unavailable</span>';const same=date.toDateString()===new Date().toDateString();return '<time class="message-time" datetime="'+escape(date.toISOString())+'" title="'+escape(date.toLocaleString(undefined,{dateStyle:'full',timeStyle:'long'}))+'">'+escape((same?'':date.toLocaleDateString(undefined,{month:'short',day:'numeric'})+' · ')+date.toLocaleTimeString(undefined,{hour:'2-digit',minute:'2-digit'}))+'</time>';}
  return {render,inline,url,time};
})();
