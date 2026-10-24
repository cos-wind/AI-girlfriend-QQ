"""Small standalone workbench. Evidence is rendered as text, never executable HTML."""

PAGE = r'''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Qbot · 共同记忆与知识库</title>
<style>
:root{font:15px/1.6 system-ui;color:#263747;background:#f3f6fa}*{box-sizing:border-box}
body{max-width:1250px;margin:0 auto;padding:28px}h1{font-size:25px;margin:8px 0}h2{font-size:18px}
a{color:#226e90}header{margin-bottom:24px}.note,small{color:#62768a}.bar{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
main{display:grid;grid-template-columns:1fr 1fr;gap:18px}section{background:white;border:1px solid #dce5ee;border-radius:16px;padding:22px;min-width:0}
input,textarea,button{font:inherit;border:1px solid #cad7e3;border-radius:8px;padding:8px 12px}input,textarea{background:#fbfdff;color:inherit}
textarea{width:100%;min-height:150px;margin:8px 0;resize:vertical}button{background:#eaf4fa;cursor:pointer;color:#185879}button:disabled{opacity:.5;cursor:default}
pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit;max-height:480px;overflow:auto;background:#f6f8fb;padding:12px;border-radius:8px}
.item{border-bottom:1px solid #e6edf4;padding:12px 0}.item button{display:block;max-width:100%;text-align:left;overflow-wrap:anywhere}#status{min-height:28px;white-space:pre-wrap}#status[role=alert]{color:#a23b39}
label{display:block}#scope{min-width:220px}#results{max-height:400px;overflow:auto}.wide{grid-column:1/-1} @media(max-width:800px){main{grid-template-columns:1fr}body{padding:16px}.wide{grid-column:auto}}
</style>
<header><a href="/">← 返回控制台</a><h1>共同记忆与知识库</h1>
<p class="note">保存经历和资料原文，按天回顾，带来源检索。自动草稿摘录聊天，手写日记由你保留。</p>
<div class="bar"><label>会话范围 <input id="scope" list="scopes" placeholder="private:QQ号"></label><datalist id="scopes"></datalist>
<label>北京时间日期 <input id="day" type="date"></label><button id="refresh">刷新记录</button><a id="export" href="#">导出当天 Markdown 与附件</a></div>
<p id="accountHint" class="note"></p><p id="status" role="status" aria-live="polite"></p></header>
<main>
<section><h2>资料与经历</h2><div class="bar"><input id="query" aria-label="检索关键词" placeholder="关键词，例如 傅里叶、游戏"><button id="search">检索当天</button><button id="searchAll">检索所有日期</button></div><div id="results"></div><div id="sources"></div></section>
<section><h2>来源与纠正</h2><p id="sourceMeta" class="note">点击记录查看原文和解析覆盖范围。</p><pre id="blocks"></pre>
<label>当前正文<textarea id="sourceText" placeholder="选择来源后可修改。纠正保留修订历史，后续检索使用新版本。"></textarea></label>
<div class="bar"><button id="revise" data-write>保存纠正</button><button id="remove" data-write>删除来源及原件</button><button id="retry" data-write>重试解析</button></div></section>
<section><h2>导入资料</h2><label>标题 <input id="title" placeholder="今天的学习笔记"></label><label>文字 / Markdown / 代码<textarea id="importText"></textarea></label>
<button id="importTextButton" data-write>保存文字</button><hr><label>附件（最多 20MB）<input id="file" type="file"></label><button id="upload" data-write>保存原件并解析</button>
<p class="note">支持现有文档、OCR、视频抽帧解析。失败仍保留原件，可重试。扫描 PDF、公式、抽帧的识别范围以来源详情为准。</p></section>
<section><h2>当天日记</h2><label>我的日记<textarea id="diaryText" placeholder="自己的感受、总结和计划"></textarea></label><button id="saveDiary" data-write>保存手写日记</button>
<h2>原文摘录草稿</h2><pre id="draft">加载日期后显示。</pre><p class="note">草稿随来源修订实时变化；不会作为独立证据重复进入检索。</p></section>
</main>
<script>
const el=id=>document.getElementById(id);let chosen=null,diaryRevision=0,readOnly=false;
el('day').value=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
function message(s,error=false){el('status').textContent=s;el('status').setAttribute('role',error?'alert':'status')}
function scope(){const s=el('scope').value.trim();if(!s)throw Error('先选择或填写会话范围');return s}
function params(extra={}){return new URLSearchParams({scope:scope(),day:el('day').value,...extra})}
async function api(path,payload){const r=await fetch('/api/knowledge/'+path,payload?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({scope:scope(),...payload})}:{});const j=await r.json();if(!r.ok||j.ok===false)throw Error(j.error||j.message||'操作失败');return j}
function action(id,fn){el(id).onclick=async()=>{const b=el(id);b.disabled=true;try{await fn()}catch(e){message(e.message,true)}finally{b.disabled=readOnly&&b.hasAttribute('data-write')}}}
function rows(target,items,hits=false){el(target).replaceChildren();for(const i of items){const row=document.createElement('div');row.className='item';const b=document.createElement('button');b.textContent=i.title+' · '+i.day+' · r'+i.revision;b.onclick=()=>openSource(i.id).catch(e=>message(e.message,true));row.append(b);const meta=document.createElement('small');meta.textContent=hits?(i.anchor+' · '+i.coverage):i.kind+(i.job_status?' · '+i.job_status:'')+(i.job_error?' · '+i.job_error:'');row.append(meta);if(hits){const p=document.createElement('p');p.textContent=i.content;row.append(p)}el(target).append(row)}}
async function openSource(id){const j=await api('source?'+params({id}));chosen=j.source;el('sourceText').value=chosen.text;el('sourceMeta').textContent=chosen.title+' · '+chosen.id+'@r'+chosen.revision+' · '+chosen.coverage+' · 原件 '+(chosen.raw_bytes||0)+' 字节'+(chosen.locator?' · '+chosen.locator:'')+(chosen.job_error?' · '+chosen.job_error:'');el('blocks').textContent=chosen.blocks.map(b=>b.anchor+'\n'+b.text.slice(0,500)).join('\n\n')}
async function loadDiary(){const d=(await api('diary?'+params())).diary;el('draft').textContent=d.draft;el('diaryText').value=d.authored?.text||'';diaryRevision=d.authored?.revision||0}
async function refresh(){el('results').replaceChildren();const j=await api('sources?'+params());rows('sources',j.items);await loadDiary();el('export').href='/api/knowledge/export?'+params();message('已加载 '+j.items.length+' 条记录（最多显示最近 100 条）')}
async function updateSource(payload){const j=await api('revise',payload);await openSource(j.source.id);await refresh();message('纠正已保存，检索与摘录草稿已更新')}
action('refresh',refresh);action('search',async()=>{rows('results',(await api('search?'+params({q:el('query').value}))).items,true)});
action('searchAll',async()=>{rows('results',(await api('search?'+params({day:'',q:el('query').value}))).items,true)});
action('importTextButton',async()=>{const j=await api('import',{title:el('title').value,text:el('importText').value});await refresh();await openSource(j.source.id);message('文字原文已保存')});
action('upload',async()=>{const f=el('file').files[0];if(!f)throw Error('请选择附件');if(f.size>20000000)throw Error('附件超过 20MB');const data=await new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(String(r.result).split(',')[1]);r.onerror=reject;r.readAsDataURL(f)});const j=await api('import',{title:el('title').value||f.name,filename:f.name,data});await refresh();await openSource(j.source.id);message('原件已保存，解析任务在后台运行。稍后刷新查看结果。')});
action('revise',async()=>{if(!chosen)throw Error('先选择来源');await updateSource({id:chosen.id,revision:chosen.revision,text:el('sourceText').value})});
action('remove',async()=>{if(!chosen)throw Error('先选择来源');if(!confirm('永久删除此来源、修订和原始附件？'))return;await api('delete',{id:chosen.id});chosen=null;el('sourceText').value='';el('blocks').textContent='';el('sourceMeta').textContent='已删除';el('results').replaceChildren();await refresh()});
action('retry',async()=>{if(!chosen)throw Error('先选择来源');await api('retry',{id:chosen.id});await refresh();message('已安排重试')});
action('saveDiary',async()=>{const j=await api('diary',{day:el('day').value,text:el('diaryText').value,revision:diaryRevision});diaryRevision=j.source.revision;await refresh();message('手写日记已保存，可通过关键词检索')});
el('scope').onchange=()=>{chosen=null;el('sourceText').value='';el('blocks').textContent='';el('sourceMeta').textContent='点击记录查看原文';el('results').replaceChildren();el('sources').replaceChildren();el('draft').textContent='';el('diaryText').value='';diaryRevision=0;refresh().catch(e=>message(e.message,true))};
el('day').onchange=()=>{chosen=null;el('sourceText').value='';el('blocks').textContent='';el('sourceMeta').textContent='点击记录查看原文';refresh().catch(e=>message(e.message,true))};
(async()=>{try{const j=await api('scopes');readOnly=j.read_only;el('accountHint').textContent=readOnly?'当前查看其他账号：只读。':'跟随控制台当前运行账号。自动记录仅接入 QQ 私聊；其他资料可手动导入。';for(const s of j.scopes){const o=document.createElement('option');o.value=s;el('scopes').append(o)}for(const b of document.querySelectorAll('[data-write]'))b.disabled=readOnly;if(j.scopes.length){el('scope').value=j.scopes[0];await refresh()}else message('暂无记录。输入 private:QQ号 后可导入资料。')}catch(e){message(e.message,true)}})();
</script></html>'''
