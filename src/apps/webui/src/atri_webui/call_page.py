from __future__ import annotations

import html


def render_voice_call(token: str, topic: str = "") -> str:
    safe_token = html.escape(token, quote=True)
    safe_topic = html.escape(topic or "和亚托莉说说话")
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>与亚托莉通话</title>
  <style>
    :root {{ color-scheme:light; --ink:#1f2937; --muted:#64748b; --line:#dbe3ec; --blue:#2563eb; --red:#dc2626; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; min-height:100vh; font-family:"Microsoft YaHei UI",system-ui,sans-serif; color:var(--ink); background:#f6f8fb; }}
    main {{ width:min(760px,100%); min-height:100vh; margin:auto; padding:28px 20px; display:grid; grid-template-rows:auto 1fr auto; gap:18px; }}
    header {{ display:flex; align-items:center; justify-content:space-between; gap:14px; border-bottom:1px solid var(--line); padding-bottom:16px; }}
    h1 {{ margin:0; font-size:24px; letter-spacing:0; }}
    p {{ margin:6px 0 0; color:var(--muted); }}
    #log {{ min-height:260px; overflow:auto; display:flex; flex-direction:column; gap:12px; padding:4px 0; }}
    .turn {{ max-width:86%; padding:10px 12px; border:1px solid var(--line); border-radius:7px; background:#fff; white-space:pre-wrap; }}
    .me {{ align-self:flex-end; border-color:#bfdbfe; background:#eff6ff; }}
    .atri {{ align-self:flex-start; }}
    .label {{ display:block; color:var(--muted); font-size:12px; margin-bottom:4px; }}
    footer {{ border-top:1px solid var(--line); padding-top:16px; }}
    .controls {{ display:flex; justify-content:center; align-items:center; gap:12px; flex-wrap:wrap; }}
    button {{ border:0; border-radius:7px; min-height:44px; padding:0 18px; font:inherit; font-weight:600; cursor:pointer; background:var(--blue); color:#fff; }}
    button.secondary {{ background:#fff; color:var(--ink); border:1px solid var(--line); }}
    button.danger {{ background:var(--red); }}
    button:disabled {{ opacity:.55; cursor:not-allowed; }}
    #state {{ text-align:center; min-height:24px; color:var(--muted); margin-bottom:10px; }}
    audio {{ width:100%; margin-top:12px; }}
  </style>
</head>
<body>
<main>
  <header>
    <div><h1>亚托莉</h1><p>{safe_topic}</p></div>
    <button class="danger" onclick="hangUp()">挂断</button>
  </header>
  <section id="log" aria-live="polite"><div class="turn atri"><span class="label">亚托莉</span>我接通啦。按住下面的按钮说话吧。</div></section>
  <footer>
    <div id="state">等待你说话</div>
    <div class="controls">
      <button id="talk" onpointerdown="startTalking(event)" onpointerup="stopTalking(event)" onpointercancel="stopTalking(event)">按住说话</button>
      <button class="secondary" onclick="replay()">重播亚托莉</button>
    </div>
    <audio id="audio" controls></audio>
  </footer>
</main>
<script>
const token = "{safe_token}";
let recorder = null, chunks = [], stream = null, lastAudio = "";
const $ = id => document.getElementById(id);
function addTurn(who,text) {{
  const el=document.createElement('div'); el.className='turn '+(who==='你'?'me':'atri');
  const label=document.createElement('span'); label.className='label'; label.textContent=who;
  el.append(label,document.createTextNode(text)); $('log').append(el); el.scrollIntoView({{behavior:'smooth'}});
}}
function encodeWave(buffer) {{
  const frames=buffer.length, mono=new Float32Array(frames);
  for(let c=0;c<buffer.numberOfChannels;c++) {{ const src=buffer.getChannelData(c); for(let i=0;i<frames;i++) mono[i]+=src[i]/buffer.numberOfChannels; }}
  const out=new ArrayBuffer(44+frames*2), view=new DataView(out);
  const write=(o,s)=>{{for(let i=0;i<s.length;i++)view.setUint8(o+i,s.charCodeAt(i));}};
  write(0,'RIFF'); view.setUint32(4,36+frames*2,true); write(8,'WAVE'); write(12,'fmt ');
  view.setUint32(16,16,true); view.setUint16(20,1,true); view.setUint16(22,1,true);
  view.setUint32(24,buffer.sampleRate,true); view.setUint32(28,buffer.sampleRate*2,true);
  view.setUint16(32,2,true); view.setUint16(34,16,true); write(36,'data'); view.setUint32(40,frames*2,true);
  for(let i=0;i<frames;i++) {{ const s=Math.max(-1,Math.min(1,mono[i])); view.setInt16(44+i*2,s<0?s*0x8000:s*0x7fff,true); }}
  return new Blob([out],{{type:'audio/wav'}});
}}
async function toWave(blob) {{
  const C=window.AudioContext||window.webkitAudioContext, ctx=new C();
  try {{ return encodeWave(await ctx.decodeAudioData(await blob.arrayBuffer())); }} finally {{ await ctx.close(); }}
}}
async function startTalking(event) {{
  event.preventDefault(); if(recorder) return;
  try {{
    stream=await navigator.mediaDevices.getUserMedia({{audio:true}});
    const type=['audio/webm;codecs=opus','audio/webm','audio/ogg'].find(t=>MediaRecorder.isTypeSupported(t))||'';
    recorder=new MediaRecorder(stream,type?{{mimeType:type}}:undefined); chunks=[];
    recorder.ondataavailable=e=>{{if(e.data.size)chunks.push(e.data);}};
    recorder.start(200); $('talk').textContent='松开发送'; $('state').textContent='正在听你说话';
  }} catch(e) {{ $('state').textContent='麦克风不可用：'+e.message; }}
}}
async function stopTalking(event) {{
  event.preventDefault(); if(!recorder) return;
  const current=recorder; recorder=null;
  const stopped=new Promise(resolve=>current.onstop=resolve); current.stop(); await stopped;
  stream?.getTracks().forEach(t=>t.stop()); $('talk').disabled=true; $('talk').textContent='处理中'; $('state').textContent='亚托莉正在听懂并回答';
  try {{
    const wav=await toWave(new Blob(chunks,{{type:current.mimeType||'audio/webm'}}));
    const form=new FormData(); form.append('token',token); form.append('language','auto'); form.append('file',wav,'call.wav');
    const response=await fetch('/api/voice-call/turn',{{method:'POST',body:form}});
    const data=await response.json(); if(!response.ok||data.ok===false) throw new Error(data.error||response.statusText);
    addTurn('你',data.transcript); addTurn('亚托莉',data.reply);
    lastAudio=data.audio_url; $('audio').src=lastAudio; await $('audio').play().catch(()=>{{}});
    $('state').textContent=`本轮 ${{data.elapsed_ms}} ms`;
  }} catch(e) {{ $('state').textContent='这一轮失败：'+e.message; }}
  finally {{ $('talk').disabled=false; $('talk').textContent='按住说话'; }}
}}
function replay() {{ if(lastAudio) {{ $('audio').currentTime=0; $('audio').play(); }} }}
async function hangUp() {{
  await fetch('/api/voice-call/close',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{token}})}}).catch(()=>{{}});
  recorder?.stop(); stream?.getTracks().forEach(t=>t.stop()); $('talk').disabled=true; $('state').textContent='通话已结束';
}}
</script>
</body>
</html>"""
