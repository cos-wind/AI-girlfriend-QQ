from __future__ import annotations


def render_index() -> str:
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>亚托莉控制台</title>
  <style>
    :root {
      --bg:#f5f6f8; --panel:#fff; --ink:#20242c; --muted:#667085; --line:#d8dde8;
      --blue:#2563eb; --blue-soft:#edf3ff; --green:#16803c; --red:#c02626;
      --amber:#a15c07; --soft:#f8fafc; --dark:#111827;
    }
    * { box-sizing:border-box; }
    body { margin:0; font-family:"Microsoft YaHei UI","Segoe UI",Arial,sans-serif; background:var(--bg); color:var(--ink); }
    header { background:#fff; border-bottom:1px solid var(--line); padding:18px 24px; position:sticky; top:0; z-index:8; }
    h1 { margin:0 0 6px; font-size:22px; letter-spacing:0; }
    h2 { margin:0 0 14px; font-size:17px; }
    h3 { margin:16px 0 10px; font-size:14px; }
    p { margin:8px 0; }
    main { max-width:1480px; margin:0 auto; padding:18px; display:grid; grid-template-columns:310px 1fr; gap:18px; }
    aside, section, .surface { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:16px; }
    .sub,.note,.hint { color:var(--muted); font-size:13px; line-height:1.65; }
    .tabs { display:flex; gap:8px; flex-wrap:wrap; margin-bottom:14px; }
    button { border:0; border-radius:6px; background:var(--blue); color:#fff; padding:9px 13px; cursor:pointer; font-weight:700; }
    button.secondary { background:#475467; }
    button.ghost { background:var(--blue-soft); color:#1e3a8a; }
    button.warn { background:var(--amber); }
    button.danger { background:var(--red); }
    button:disabled { opacity:.55; cursor:not-allowed; }
    .tab { background:#edf0f5; color:#344054; }
    .tab.active { background:var(--blue); color:#fff; }
    .panel { display:none; }
    .panel.active { display:block; }
    .status { display:grid; gap:10px; }
    .pill { display:flex; justify-content:space-between; gap:10px; align-items:center; padding:10px 12px; border:1px solid var(--line); border-radius:6px; background:#fff; }
    .ok { color:var(--green); font-weight:700; }
    .bad { color:var(--red); font-weight:700; }
    .grid { display:grid; grid-template-columns:repeat(2,minmax(220px,1fr)); gap:12px; }
    .three { display:grid; grid-template-columns:repeat(3,minmax(160px,1fr)); gap:12px; }
    .split { display:grid; grid-template-columns:minmax(360px,.95fr) minmax(420px,1.05fr); gap:14px; }
    label { display:grid; gap:6px; color:#344054; font-size:13px; }
    input, select, textarea { width:100%; border:1px solid var(--line); border-radius:6px; padding:9px 10px; font:inherit; background:#fff; }
    textarea { min-height:130px; resize:vertical; line-height:1.5; }
    .json-editor { min-height:340px; font-family:Consolas,"Microsoft YaHei UI",monospace; }
    .row { display:flex; gap:10px; flex-wrap:wrap; align-items:center; margin-top:14px; }
    .stack { display:grid; gap:12px; }
    .toolbar { display:flex; gap:10px; flex-wrap:wrap; align-items:end; margin:10px 0 14px; }
    .toolbar label { min-width:170px; flex:1; }
    .scroll { max-height:640px; overflow:auto; border:1px solid var(--line); border-radius:7px; background:#fff; }
    table { width:100%; border-collapse:collapse; font-size:13px; }
    th,td { text-align:left; border-bottom:1px solid var(--line); padding:9px; vertical-align:top; }
    tr:hover { background:#f8fafc; }
    .profile-list { display:grid; gap:10px; }
    .profile { border:1px solid var(--line); border-radius:7px; padding:12px; background:#fff; display:grid; gap:7px; }
    .profile.active { border-color:var(--blue); box-shadow:0 0 0 2px rgba(37,99,235,.12); }
    .profile-title { display:flex; justify-content:space-between; gap:10px; align-items:flex-start; }
    .badge { display:inline-flex; align-items:center; border-radius:999px; padding:2px 8px; font-size:12px; background:#eef2f6; color:#344054; white-space:nowrap; }
    .badge.active { background:#dcfce7; color:#166534; }
    .badge.warn { background:#fef3c7; color:#92400e; }
    .badge.red { background:#fee2e2; color:#991b1b; }
    .mono { font-family:Consolas,monospace; }
    .out,.natural-box { white-space:pre-wrap; background:#101828; color:#f2f4f7; border-radius:7px; padding:12px; min-height:90px; line-height:1.55; }
    .natural-box { background:#f8fafc; color:#1f2937; border:1px solid var(--line); }
    .thumbs { display:grid; grid-template-columns:repeat(auto-fill,minmax(112px,1fr)); gap:10px; }
    .thumb { border:1px solid var(--line); border-radius:7px; padding:8px; background:#fff; }
    .thumb img { width:100%; height:92px; object-fit:contain; background:#f2f4f7; border-radius:5px; }
    .thumb small { display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:var(--muted); margin:6px 0; }
    details { border:1px solid var(--line); border-radius:7px; padding:10px 12px; background:#fff; }
    summary { cursor:pointer; font-weight:700; }
    .toast { position:fixed; right:18px; bottom:18px; max-width:420px; background:#111827; color:#fff; padding:12px 14px; border-radius:7px; box-shadow:0 10px 28px rgba(15,23,42,.25); opacity:0; pointer-events:none; transform:translateY(8px); transition:.18s ease; z-index:30; }
    .toast.show { opacity:1; transform:translateY(0); }
    .memory-name { font-weight:700; margin-bottom:4px; }
    .memory-meta { color:var(--muted); font-size:12px; line-height:1.55; }
    .memory-summary { line-height:1.6; max-width:620px; }
    .empty { color:var(--muted); padding:22px; text-align:center; }
    .modal { position:fixed; inset:0; display:none; align-items:center; justify-content:center; background:rgba(15,23,42,.46); padding:22px; z-index:20; }
    .modal.show { display:flex; }
    .dialog { width:min(1180px,96vw); max-height:92vh; overflow:hidden; background:#fff; border-radius:8px; border:1px solid var(--line); box-shadow:0 24px 70px rgba(15,23,42,.32); display:grid; grid-template-rows:auto auto 1fr auto; }
    .dialog-head { padding:16px 18px; border-bottom:1px solid var(--line); display:flex; gap:12px; justify-content:space-between; align-items:flex-start; }
    .dialog-title { font-size:18px; font-weight:800; }
    .dialog-body { overflow:auto; padding:16px 18px; background:#fbfcfe; }
    .dialog-foot { padding:12px 18px; border-top:1px solid var(--line); background:#fff; display:flex; justify-content:space-between; gap:12px; align-items:center; }
    .mini-tabs { display:flex; gap:8px; flex-wrap:wrap; padding:10px 18px; border-bottom:1px solid var(--line); background:#fff; }
    .mini-tab { background:#eef2f6; color:#344054; }
    .mini-tab.active { background:var(--blue); color:#fff; }
    .stat-grid { display:grid; grid-template-columns:repeat(4,minmax(130px,1fr)); gap:10px; margin:12px 0; }
    .stat { border:1px solid var(--line); border-radius:7px; background:#fff; padding:10px; }
    .stat strong { display:block; font-size:18px; margin-bottom:2px; }
    .entry-list { display:grid; gap:10px; }
    .entry { border:1px solid var(--line); border-radius:7px; background:#fff; padding:12px; display:grid; gap:10px; }
    .entry-head { display:flex; justify-content:space-between; gap:10px; align-items:center; }
    .entry-grid { display:grid; grid-template-columns:180px 1fr 130px 130px; gap:10px; }
    .history-item { border:1px solid var(--line); border-radius:7px; background:#fff; padding:10px; display:grid; gap:8px; margin-bottom:8px; }
    .dirty { color:var(--amber); font-weight:700; }
    .saved { color:var(--green); font-weight:700; }
    @media (max-width:980px) {
      main,.split { grid-template-columns:1fr; }
      .grid,.three,.stat-grid,.entry-grid { grid-template-columns:1fr; }
      .dialog { width:98vw; }
    }
  </style>
</head>
<body>
  <header>
    <h1>亚托莉控制台</h1>
    <div class="sub">本地 WebUI，只监听 127.0.0.1。这里可以切换模型、管理表情包、查看和编辑记忆。</div>
  </header>
  <main>
    <aside>
      <h2>运行状态</h2>
      <div class="status" id="status"></div>
      <div class="row">
        <button class="ghost" onclick="loadStatus()">刷新</button>
        <button class="secondary" onclick="restartServices()">后台重启</button>
      </div>
      <p class="note">API Key 会隐藏显示。输入框变空不是丢失，显示“已保存”就代表仍在配置里。</p>
    </aside>
    <section>
      <div class="tabs">
        <button class="tab active" onclick="showTab(event,'model')">模型</button>
        <button class="tab" onclick="showTab(event,'stickers')">表情包</button>
        <button class="tab" onclick="showTab(event,'memory')">记忆</button>
        <button class="tab" onclick="showTab(event,'test')">测试</button>
        <button class="tab" onclick="showTab(event,'advanced')">高级</button>
      </div>

      <div id="model" class="panel active">
        <div class="split">
          <div class="stack">
            <div class="surface">
              <h2>当前聊天模型</h2>
              <div id="currentModel" class="natural-box">读取中...</div>
            </div>
            <div class="surface">
              <h2>模型档案</h2>
              <p class="note">新建或点选一个档案。启用档案时，会把 API Key、接口地址、模型名和生成参数一起写入配置。</p>
              <div class="profile-list" id="profileList"></div>
            </div>
          </div>
          <div class="surface">
            <h2 id="profileFormTitle">新建模型档案</h2>
            <input id="profileId" type="hidden">
            <div class="grid">
              <label>档案名称<input id="profileName" placeholder="例如：DeepSeek 官方"></label>
              <label>服务商<input id="profileProvider" placeholder="例如：DeepSeek / Ollama / OpenAI兼容"></label>
              <label>接口地址<input id="profileBaseUrl" placeholder="https://api.deepseek.com/v1"></label>
              <label>模型名称<input id="profileModel" placeholder="deepseek-chat"></label>
              <label>API Key<input id="profileApiKey" type="password" placeholder="已保存时留空可保持原值"></label>
              <label>温度<input id="profileTemperature" type="number" min="0" max="2" step="0.01" value="0.65"></label>
              <label>重复惩罚<input id="profileFrequencyPenalty" type="number" min="0" max="2" step="0.01" value="0.35"></label>
              <label>最大输出<input id="profileMaxTokens" type="number" min="32" max="4096" step="1" value="260"></label>
            </div>
            <div class="row">
              <button onclick="saveProfile()">保存档案</button>
              <button class="ghost" onclick="activateSelectedProfile()">启用档案</button>
              <button class="secondary" onclick="newProfile()">新建空档案</button>
              <button class="danger" onclick="deleteSelectedProfile()">删除档案</button>
            </div>
            <h3>快速填入</h3>
            <div class="row">
              <button class="ghost" onclick="quickFillDeepSeek()">DeepSeek 官方</button>
              <button class="ghost" onclick="quickFillOllama()">本地 Ollama</button>
              <button class="ghost" onclick="quickFillOpenAICompatible()">OpenAI 兼容</button>
            </div>
          </div>
        </div>
      </div>

      <div id="stickers" class="panel">
        <h2>表情包管理</h2>
        <div class="grid">
          <label>新建情绪分类<input id="newCategory" placeholder="例如 happy / comfort / tsundere / 摸摸头"></label>
          <label>上传到分类<select id="uploadCategory"></select></label>
        </div>
        <div class="row">
          <button onclick="createCategory()">新建分类</button>
          <input id="stickerFile" type="file" accept=".jpg,.jpeg,.png,.gif,.webp,image/*">
          <button onclick="uploadSticker()">上传表情包</button>
        </div>
        <p class="note" id="stickerInfo"></p>
        <div class="split">
          <div class="scroll"><table><thead><tr><th>分类</th><th>数量</th><th>位置</th></tr></thead><tbody id="stickerRows"></tbody></table></div>
          <div>
            <h3 id="stickerFolderTitle">预览</h3>
            <div class="thumbs" id="stickerPreview"></div>
          </div>
        </div>
      </div>

      <div id="memory" class="panel">
        <h2>记忆管理</h2>
        <div class="toolbar">
          <label>搜索用户 / QQ / 群 / 关键词<input id="memorySearch" oninput="renderMemoryRows()" placeholder="输入昵称、QQ号、群号或记忆关键词"></label>
          <label>类型筛选<select id="memoryTypeFilter" onchange="renderMemoryRows()">
            <option value="all">全部</option>
            <option value="private">私聊</option>
            <option value="group">群聊</option>
            <option value="member">群内用户</option>
            <option value="important">有重要记忆</option>
          </select></label>
          <label>排序<select id="memorySort" onchange="renderMemoryRows()">
            <option value="recent">最近互动</option>
            <option value="messages">消息数量</option>
            <option value="memories">记忆数量</option>
            <option value="affection">亲密状态</option>
          </select></label>
        </div>
        <div class="row">
          <button class="ghost" onclick="loadMemory()">刷新记忆</button>
          <button class="warn" onclick="backupMemory()">手动备份</button>
        </div>
        <p class="note" id="memoryInfo"></p>
        <div class="scroll">
          <table>
            <thead><tr><th>对象</th><th>核心记忆</th><th>状态</th><th>操作</th></tr></thead>
            <tbody id="memoryRows"></tbody>
          </table>
        </div>
      </div>

      <div id="test" class="panel">
        <h2>测试一句话</h2>
        <textarea id="testText" placeholder="例如：我今天好累，亚托莉你会怎么回？"></textarea>
        <div class="row"><button onclick="testChat()">发送测试</button></div>
        <div class="out" id="testOut"></div>
      </div>

      <div id="advanced" class="panel">
        <h2>高级配置</h2>
        <p class="note">这里适合调整回复频率、分条发送、表情包概率和群聊主动发言规则。群聊沉默天数设为 0 表示不按天数停用主动发言。</p>
        <div class="grid" id="configForm"></div>
        <div class="row">
          <button onclick="saveConfig()">保存高级配置</button>
          <button class="ghost" onclick="loadConfig()">恢复页面当前值</button>
        </div>
      </div>
    </section>
  </main>

  <div id="memoryModal" class="modal" onclick="modalBackdrop(event)">
    <div class="dialog">
      <div class="dialog-head">
        <div>
          <div class="dialog-title" id="memoryModalTitle">记忆详情</div>
          <div class="note" id="memoryModalMeta"></div>
        </div>
        <button class="secondary" onclick="closeMemoryModal()">关闭</button>
      </div>
      <div class="mini-tabs">
        <button class="mini-tab active" onclick="showMemoryPane(event,'memoryOverview')">概览</button>
        <button class="mini-tab" onclick="showMemoryPane(event,'memoryProfile')">用户档案</button>
        <button class="mini-tab" onclick="showMemoryPane(event,'memoryEvents')">事件</button>
        <button class="mini-tab" onclick="showMemoryPane(event,'memoryStyle')">习惯</button>
        <button class="mini-tab" onclick="showMemoryPane(event,'memoryHistory')">最近聊天</button>
        <button class="mini-tab" onclick="showMemoryPane(event,'memoryRaw')">高级 JSON</button>
      </div>
      <div class="dialog-body">
        <div id="memoryOverview" class="memory-pane"></div>
        <div id="memoryProfile" class="memory-pane" style="display:none"></div>
        <div id="memoryEvents" class="memory-pane" style="display:none"></div>
        <div id="memoryStyle" class="memory-pane" style="display:none"></div>
        <div id="memoryHistory" class="memory-pane" style="display:none"></div>
        <div id="memoryRaw" class="memory-pane" style="display:none"></div>
      </div>
      <div class="dialog-foot">
        <span id="memorySaveState" class="saved">未修改</span>
        <div class="row" style="margin:0">
          <button class="ghost" onclick="addMemoryEntryFromActivePane()">新增当前分类</button>
          <button id="memorySaveButton" onclick="saveSelectedMemory()">保存修改</button>
          <button class="danger" onclick="deleteSelectedMemory()">删除此会话记忆</button>
        </div>
      </div>
    </div>
  </div>
  <div id="toast" class="toast"></div>

<script>
const fields = [
  ["OPENAI_API_KEY","API Key","password"],
  ["OPENAI_BASE_URL","接口地址","text"],
  ["OPENAI_MODEL","聊天模型","text"],
  ["TEMPERATURE","温度","number"],
  ["FREQUENCY_PENALTY","重复惩罚","number"],
  ["MAX_TOKENS","最大输出","number"],
  ["REPLY_MODE","回复模式","select"],
  ["MESSAGE_SPLIT_MAX_CHARS","单条字数","number"],
  ["MESSAGE_SPLIT_MAX_PARTS","最多分条","number"],
  ["MESSAGE_SEND_DELAY_MIN","最短发送间隔","number"],
  ["MESSAGE_SEND_DELAY_MAX","最长发送间隔","number"],
  ["STICKER_CHANCE","表情概率","number"],
  ["STICKER_COOLDOWN_SECONDS","表情冷却秒数","number"],
  ["IDLE_PROACTIVE_ENABLED","私聊主动关心","checkbox"],
  ["IDLE_MINUTES","私聊空闲分钟","number"],
  ["IDLE_COOLDOWN_MINUTES","主动关心冷却","number"],
  ["GROUP_PROACTIVE_ENABLED","群聊主动发言","checkbox"],
  ["GROUP_PROACTIVE_IDLE_MINUTES","群聊冷场分钟","number"],
  ["GROUP_PROACTIVE_COOLDOWN_MINUTES","群聊主动冷却","number"],
  ["GROUP_PROACTIVE_DAILY_LIMIT","单群日上限","number"],
  ["GROUP_PROACTIVE_MAX_SILENCE_DAYS","群聊沉默停用天数","number"],
  ["MORNING_GREETING_ENABLED","早安启用","checkbox"],
  ["MORNING_GREETING_TIME","早安时间","text"],
  ["TOOLBOX_VISION_ENABLED","图片识别","checkbox"],
  ["TOOLBOX_VISION_MODEL","视觉模型","text"],
  ["TOOLBOX_VISION_BASE_URL","视觉接口","text"],
  ["TOOLBOX_VISION_API_KEY","视觉 API Key","password"]
];
const categoryLabels = {
  interest:"兴趣爱好", profile_fact:"用户资料", communication_style:"聊天习惯",
  schedule:"日程提醒", event:"事件经历", important_interaction:"重要互动"
};
let selectedProfileId = "";
let currentMemoryId = "";
let selectedMemory = null;
let selectedMemoryContent = null;
let memoryDirty = false;
let activeMemoryPane = "memoryOverview";
window._profiles = [];
window._memoryItems = [];
function $(id) { return document.getElementById(id); }
function toast(text) {
  const el = $('toast'); el.textContent = text; el.classList.add('show');
  setTimeout(()=>el.classList.remove('show'), 2600);
}
async function api(path, opts={}) {
  const headers = opts.body instanceof FormData ? {} : {'Content-Type':'application/json'};
  const res = await fetch(path, {headers, ...opts});
  const data = await res.json();
  if(!res.ok || data.ok === false) throw new Error(data.error || res.statusText);
  return data;
}
function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, s => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[s]));
}
function showTab(event, id) {
  document.querySelectorAll('.tab').forEach(b=>b.classList.remove('active'));
  document.querySelectorAll('.panel').forEach(p=>p.classList.remove('active'));
  event.target.classList.add('active'); $(id).classList.add('active');
  if(id==='stickers') loadStickers();
  if(id==='memory') loadMemory();
  if(id==='advanced') loadConfig();
  if(id==='model') loadProfiles();
}
async function loadStatus() {
  const s = await api('/api/status');
  $('status').innerHTML = [
    ['Atri 服务', s.atri], ['NapCat 连接', s.napcat], ['Ollama', s.ollama], ['WebUI', s.webui]
  ].map(([k,v])=>`<div class="pill"><span>${k}</span><span class="${v?'ok':'bad'}">${v?'正常':'未连接'}</span></div>`).join('')
  + `<p class="note">机器人 QQ：${escapeHtml(s.bot_qq)}<br>模型：${escapeHtml(s.model)}<br>接口：${escapeHtml(s.base_url)}<br>回复模式：${escapeHtml(s.reply_mode)}</p>`;
}
async function loadProfiles() {
  const data = await api('/api/model-profiles');
  window._profiles = data.profiles || [];
  const c = data.current || {};
  $('currentModel').innerHTML = `服务商：${escapeHtml(c.name)}\n模型：${escapeHtml(c.model)}\n接口：${escapeHtml(c.base_url)}\nAPI Key：${c.has_api_key ? '已保存（' + escapeHtml(c.api_key_masked) + '）' : '未填写'}\n参数：温度 ${escapeHtml(c.temperature)}，重复惩罚 ${escapeHtml(c.frequency_penalty)}，最大输出 ${escapeHtml(c.max_tokens)}`;
  $('profileList').innerHTML = window._profiles.map((p, index) => `
    <div class="profile ${p.id===data.active_id?'active':''}">
      <div class="profile-title">
        <div><strong>${escapeHtml(p.name)}</strong><br><span class="note">${escapeHtml(p.provider)} · ${escapeHtml(p.model)}</span></div>
        <span class="badge ${p.id===data.active_id?'active':''}">${p.id===data.active_id?'当前启用':'可选择'}</span>
      </div>
      <div class="note">接口：${escapeHtml(p.base_url)}<br>API Key：${p.has_api_key ? '已保存（' + escapeHtml(p.api_key_masked) + '）' : '未填写'}</div>
      <div class="row">
        <button class="ghost" onclick="selectProfileByIndex(${index})">编辑</button>
        <button onclick="activateProfileByIndex(${index})">启用</button>
      </div>
    </div>`).join('') || '<p class="note">还没有模型档案。</p>';
}
function selectProfileByIndex(index) { const p = window._profiles[index]; if(p) selectProfile(p); }
function activateProfileByIndex(index) { const p = window._profiles[index]; if(p) activateProfile(p.id); }
function selectProfile(p) {
  selectedProfileId = p.id || "";
  $('profileFormTitle').textContent = '编辑模型档案';
  $('profileId').value = p.id || "";
  $('profileName').value = p.name || "";
  $('profileProvider').value = p.provider || "";
  $('profileBaseUrl').value = p.base_url || "";
  $('profileModel').value = p.model || "";
  $('profileApiKey').value = "";
  $('profileApiKey').placeholder = p.has_api_key ? '已保存，留空保持原值' : '未填写，请输入 API Key';
  $('profileTemperature').value = p.temperature || "0.65";
  $('profileFrequencyPenalty').value = p.frequency_penalty || "0.35";
  $('profileMaxTokens').value = p.max_tokens || "260";
}
function profilePayload() {
  return {
    id: $('profileId').value.trim(),
    name: $('profileName').value.trim(),
    provider: $('profileProvider').value.trim(),
    base_url: $('profileBaseUrl').value.trim(),
    model: $('profileModel').value.trim(),
    api_key: $('profileApiKey').value.trim(),
    temperature: $('profileTemperature').value.trim(),
    frequency_penalty: $('profileFrequencyPenalty').value.trim(),
    max_tokens: $('profileMaxTokens').value.trim()
  };
}
async function saveProfile() {
  const r = await api('/api/model-profiles/save', {method:'POST', body:JSON.stringify(profilePayload())});
  selectProfile(r.profile);
  await loadProfiles();
  toast('模型档案已保存');
}
async function activateProfile(id) {
  const r = await api('/api/model-profiles/activate', {method:'POST', body:JSON.stringify({id})});
  await loadProfiles(); await loadStatus(); await loadConfig();
  toast(`已启用：${r.profile.name}`);
}
async function activateSelectedProfile() {
  const id = $('profileId').value.trim() || selectedProfileId;
  if(!id) return toast('先选择或保存一个模型档案');
  await activateProfile(id);
}
async function deleteSelectedProfile() {
  const id = $('profileId').value.trim() || selectedProfileId;
  if(!id) return toast('先选择一个模型档案');
  if(!confirm('确认删除这个模型档案？不会删除 .env 里当前正在使用的配置。')) return;
  await api('/api/model-profiles/delete', {method:'POST', body:JSON.stringify({id})});
  newProfile(); await loadProfiles(); toast('模型档案已删除');
}
function newProfile() {
  selectedProfileId = "";
  $('profileFormTitle').textContent = '新建模型档案';
  for (const id of ['profileId','profileName','profileProvider','profileBaseUrl','profileModel','profileApiKey']) $(id).value = '';
  $('profileApiKey').placeholder = '输入 API Key；本地 Ollama 可填 ollama';
  $('profileTemperature').value = "0.65";
  $('profileFrequencyPenalty').value = "0.35";
  $('profileMaxTokens').value = "260";
}
function quickFillDeepSeek() {
  $('profileName').value = $('profileName').value || 'DeepSeek 官方';
  $('profileProvider').value = 'DeepSeek';
  $('profileBaseUrl').value = 'https://api.deepseek.com/v1';
  $('profileModel').value = 'deepseek-chat';
  $('profileTemperature').value = '0.65';
  $('profileFrequencyPenalty').value = '0.35';
  $('profileMaxTokens').value = '260';
}
function quickFillOllama() {
  $('profileName').value = $('profileName').value || '本地 Ollama Qwen3 4B';
  $('profileProvider').value = 'Ollama';
  $('profileBaseUrl').value = 'http://127.0.0.1:11434/v1';
  $('profileModel').value = 'qwen3:4b-instruct';
  $('profileApiKey').value = 'ollama';
  $('profileTemperature').value = '0.60';
  $('profileFrequencyPenalty').value = '0.35';
  $('profileMaxTokens').value = '180';
}
function quickFillOpenAICompatible() {
  $('profileName').value = $('profileName').value || 'OpenAI 兼容模型';
  $('profileProvider').value = 'OpenAI 兼容';
  $('profileBaseUrl').value = 'https://api.openai.com/v1';
  $('profileModel').value = 'gpt-4.1-mini';
  $('profileTemperature').value = '0.65';
  $('profileFrequencyPenalty').value = '0.35';
  $('profileMaxTokens').value = '260';
}
async function loadConfig() {
  const cfg = await api('/api/config');
  $('configForm').innerHTML = fields.map(([key,label,type])=>{
    const item = cfg[key] || {}; const value = item.raw || item.value || '';
    if(type==='select') return `<label>${label}<select id="${key}"><option>private</option><option>mention</option><option>smart</option><option>all</option></select></label>`;
    if(type==='checkbox') return `<label>${label}<input id="${key}" type="checkbox" ${String(value).toLowerCase()==='true'?'checked':''}></label>`;
    if(type==='password') return `<label>${label}<input id="${key}" type="password" placeholder="${item.has_secret ? '已保存，留空保持原值' : '未填写'}"></label>`;
    return `<label>${label}<input id="${key}" type="${type}" step="0.01" value="${escapeHtml(value)}"></label>`;
  }).join('');
  for (const [key,,type] of fields) if(type==='select' && cfg[key]) $(key).value = cfg[key].raw || cfg[key].value;
}
async function saveConfig() {
  const body = {};
  for (const [key,,type] of fields) {
    const el = $(key); if(!el) continue;
    body[key] = type==='checkbox' ? el.checked : el.value;
  }
  await api('/api/config', {method:'POST', body:JSON.stringify(body)});
  await loadConfig(); await loadStatus(); await loadProfiles();
  toast('高级配置已保存，新的 QQ 消息会使用新配置');
}
async function loadStickers() {
  const s = await api('/api/stickers');
  $('stickerInfo').textContent = `表情包根目录：${s.path}`;
  const folders = (s.folders||[]).filter(f=>!f.name.startsWith('_deleted'));
  $('uploadCategory').innerHTML = folders.map(f=>`<option value="${escapeHtml(f.name)}">${escapeHtml(f.name)} (${f.count})</option>`).join('');
  $('stickerRows').innerHTML = folders.map((f,i)=>`<tr><td><button class="ghost" onclick="previewFolderByIndex(${i})">${escapeHtml(f.name)}</button></td><td>${f.count}</td><td class="mono">${escapeHtml(f.path)}</td></tr>`).join('');
  window._stickerFolders = folders;
  if (folders.length) previewFolderByIndex(0); else $('stickerPreview').innerHTML = '<p class="note">还没有表情包分类。</p>';
}
function previewFolderByIndex(index) {
  const folder = (window._stickerFolders || [])[index];
  if(!folder) return;
  window._stickerFiles = folder.files || [];
  $('stickerFolderTitle').textContent = `预览：${folder.name}`;
  $('stickerPreview').innerHTML = window._stickerFiles.map((file, fileIndex)=>`
    <div class="thumb">
      <img src="${file.url}" alt="${escapeHtml(file.name)}">
      <small title="${escapeHtml(file.path)}">${escapeHtml(file.name)}</small>
      <button class="danger" onclick="deleteStickerByIndex(${fileIndex})">删除</button>
    </div>`).join('') || '<p class="note">这个分类暂时没有图片。</p>';
}
async function createCategory() {
  const name = $('newCategory').value.trim();
  if(!name) return toast('先输入分类名');
  await api('/api/stickers/category', {method:'POST', body:JSON.stringify({name})});
  $('newCategory').value = ''; await loadStickers(); toast('分类已创建');
}
async function uploadSticker() {
  const file = $('stickerFile').files[0];
  if(!file) return toast('先选择图片');
  const form = new FormData();
  form.append('category', $('uploadCategory').value || 'default');
  form.append('file', file);
  await api('/api/stickers/upload', {method:'POST', body:form});
  $('stickerFile').value = ''; await loadStickers(); toast('表情包已上传');
}
async function deleteStickerByIndex(index) {
  const file = (window._stickerFiles || [])[index];
  if(!file) return toast('没有找到这个文件');
  if(!confirm('删除后会移动到 _deleted 备份文件夹，确认吗？')) return;
  await api('/api/stickers/delete', {method:'POST', body:JSON.stringify({path:file.path})});
  await loadStickers(); toast('已移动到 _deleted');
}

async function loadMemory() {
  const m = await api('/api/memory');
  window._memoryItems = m.items || [];
  $('memoryInfo').textContent = `记忆文件：${m.path}，会话数：${m.conversations}`;
  renderMemoryRows();
}
function memoryMatchesFilter(item) {
  const filter = $('memoryTypeFilter')?.value || 'all';
  if(filter === 'private' && item.kind !== 'private') return false;
  if(filter === 'group' && item.kind !== 'group') return false;
  if(filter === 'member' && item.kind !== 'member') return false;
  if(filter === 'important' && !(item.memory_counts && item.memory_counts.total > 0)) return false;
  const q = ($('memorySearch')?.value || '').trim().toLowerCase();
  if(!q) return true;
  return String(item.searchable || '').toLowerCase().includes(q);
}
function renderMemoryRows() {
  const sort = $('memorySort')?.value || 'recent';
  const rows = (window._memoryItems || []).filter(memoryMatchesFilter).sort((a,b)=>{
    if(sort === 'messages') return (b.messages||0) - (a.messages||0);
    if(sort === 'memories') return ((b.memory_counts||{}).total||0) - ((a.memory_counts||{}).total||0);
    if(sort === 'affection') return Number(b.affection||0) - Number(a.affection||0);
    return Number(b.last_user_at||0) - Number(a.last_user_at||0);
  });
  $('memoryRows').innerHTML = rows.map((x)=>`
    <tr>
      <td>
        <div class="memory-name">${escapeHtml(x.display_name || x.id)}</div>
        <div class="memory-meta">${escapeHtml(x.type)} · ${escapeHtml(x.id)}<br>${escapeHtml(x.last_user_at_text || '暂无互动时间')}</div>
      </td>
      <td class="memory-summary">${escapeHtml(x.summary || '暂无可读摘要')}</td>
      <td>
        <span class="badge">${escapeHtml(x.affection_label || '普通')}</span>
        ${x.proactive_state ? `<br><span class="badge ${x.proactive_blocked?'red':'active'}" style="margin-top:6px">${escapeHtml(x.proactive_state)}</span>` : ''}
        <div class="memory-meta" style="margin-top:6px">消息 ${x.messages||0} · 记忆 ${(x.memory_counts||{}).total||0}</div>
      </td>
      <td><button class="ghost" onclick="openMemory('${escapeHtml(x.id)}')">详情 / 编辑</button></td>
    </tr>`).join('') || '<tr><td colspan="4"><div class="empty">没有匹配的记忆。</div></td></tr>';
}
async function openMemory(id) {
  if(memoryDirty && !confirm('当前记忆有未保存修改，确定切换吗？')) return;
  const d = await api('/api/memory/detail?id=' + encodeURIComponent(id));
  currentMemoryId = id;
  selectedMemory = d;
  selectedMemoryContent = JSON.parse(JSON.stringify(d.content || {}));
  memoryDirty = false;
  $('memoryModalTitle').textContent = d.display_name || id;
  $('memoryModalMeta').textContent = `${d.type || ''} · ${id}`;
  $('memoryModal').classList.add('show');
  setSaveState('未修改', false);
  renderMemoryModal();
}
function closeMemoryModal() {
  if(memoryDirty && !confirm('还有未保存修改，确定关闭吗？')) return;
  $('memoryModal').classList.remove('show');
}
function modalBackdrop(event) {
  if(event.target.id === 'memoryModal') closeMemoryModal();
}
function showMemoryPane(event, id) {
  activeMemoryPane = id;
  document.querySelectorAll('.mini-tab').forEach(b=>b.classList.remove('active'));
  document.querySelectorAll('.memory-pane').forEach(p=>p.style.display='none');
  event.target.classList.add('active'); $(id).style.display = 'block';
}
function setSaveState(text, dirty) {
  memoryDirty = dirty;
  const el = $('memorySaveState');
  el.textContent = text;
  el.className = dirty ? 'dirty' : 'saved';
}
function markMemoryDirty() {
  setSaveState('有未保存修改', true);
}
function structuredMemory() {
  selectedMemoryContent.structured_memory = selectedMemoryContent.structured_memory || {};
  for (const key of ['l1','l2','candidates']) {
    if(!Array.isArray(selectedMemoryContent.structured_memory[key])) selectedMemoryContent.structured_memory[key] = [];
  }
  return selectedMemoryContent.structured_memory;
}
function memoryEntryLayerForPane() {
  if(activeMemoryPane === 'memoryEvents') return 'l2';
  if(activeMemoryPane === 'memoryProfile' || activeMemoryPane === 'memoryStyle') return 'l1';
  return 'l1';
}
function renderMemoryModal() {
  if(!selectedMemory || !selectedMemoryContent) return;
  const counts = selectedMemory.memory_counts || {};
  $('memoryOverview').innerHTML = `
    <div class="natural-box">${escapeHtml(selectedMemory.natural || '暂无可读摘要。')}</div>
    <div class="stat-grid">
      <div class="stat"><strong>${selectedMemoryContent.message_count || 0}</strong><span class="note">消息数量</span></div>
      <div class="stat"><strong>${counts.total || 0}</strong><span class="note">结构化记忆</span></div>
      <div class="stat"><strong>${selectedMemory.history_count || 0}</strong><span class="note">历史条数</span></div>
      <div class="stat"><strong>${escapeHtml(selectedMemory.affection_label || '普通')}</strong><span class="note">亲密状态</span></div>
    </div>
    <p class="note">编辑下面的档案、事件、习惯或最近聊天后，点击底部“保存修改”。保存前会自动备份。</p>`;
  $('memoryProfile').innerHTML = renderEntryEditor('l1', ['profile_fact','interest'], '用户档案与兴趣');
  $('memoryEvents').innerHTML = renderEntryEditor('l2', ['event','schedule','important_interaction'], '事件、日程与重要互动');
  $('memoryStyle').innerHTML = renderEntryEditor('l1', ['communication_style'], '聊天习惯') + renderRulesEditor();
  $('memoryHistory').innerHTML = renderHistoryEditor();
  $('memoryRaw').innerHTML = `<p class="note">高级模式会直接保存整个会话 JSON。改错 JSON 会被拦截，不会写入。</p><textarea id="memoryRawEditor" class="json-editor" spellcheck="false">${escapeHtml(JSON.stringify(selectedMemoryContent, null, 2))}</textarea><div class="row"><button class="ghost" onclick="applyRawMemory()">应用 JSON 到编辑器</button></div>`;
}
function renderEntryEditor(layer, categories, title) {
  const memory = structuredMemory();
  const entries = (memory[layer] || []).map((entry, index)=>({entry,index})).filter(({entry})=>categories.includes(entry.category || ''));
  return `<h3>${title}</h3><div class="entry-list">${entries.map(({entry,index})=>renderEntry(layer,index,entry)).join('') || '<div class="empty">暂无内容，可以点击底部“新增当前分类”。</div>'}</div>`;
}
function renderEntry(layer, index, entry) {
  const category = entry.category || '';
  const options = Object.entries(categoryLabels).map(([key,label])=>`<option value="${key}" ${key===category?'selected':''}>${label}</option>`).join('');
  return `<div class="entry">
    <div class="entry-head">
      <strong>${escapeHtml(categoryLabels[category] || category || '未分类')}</strong>
      <button class="danger" onclick="removeMemoryEntry('${layer}',${index})">删除</button>
    </div>
    <div class="entry-grid">
      <label>分类<select onchange="updateMemoryEntry('${layer}',${index},'category',this.value)">${options}</select></label>
      <label>标题 / 键<input value="${escapeHtml(entry.key || entry.memory_key || '')}" oninput="updateMemoryEntry('${layer}',${index},'key',this.value)"></label>
      <label>置信度<input type="number" min="0" max="1" step="0.05" value="${escapeHtml(entry.confidence ?? '')}" oninput="updateMemoryEntry('${layer}',${index},'confidence',this.value,true)"></label>
      <label>状态<select onchange="updateMemoryEntry('${layer}',${index},'state',this.value)">
        <option value="active" ${entry.state !== 'sleeping'?'selected':''}>启用</option>
        <option value="sleeping" ${entry.state === 'sleeping'?'selected':''}>休眠</option>
      </select></label>
    </div>
    <label>内容<textarea oninput="updateMemoryEntry('${layer}',${index},'value',this.value)">${escapeHtml(entry.value || '')}</textarea></label>
  </div>`;
}
function renderRulesEditor() {
  const accepted = selectedMemoryContent.accepted_iteration_rules || [];
  const rejected = selectedMemoryContent.rejected_iteration_rules || [];
  const block = (items, key, label) => `<h3>${label}</h3><div class="entry-list">${items.map((rule,index)=>`
    <div class="entry">
      <div class="entry-head"><strong>${label} ${index+1}</strong><button class="danger" onclick="removeRule('${key}',${index})">删除</button></div>
      <label>规则<textarea oninput="updateRule('${key}',${index},'rule',this.value)">${escapeHtml(rule.rule || '')}</textarea></label>
      <label>原因<input value="${escapeHtml(rule.reason || '')}" oninput="updateRule('${key}',${index},'reason',this.value)"></label>
    </div>`).join('') || '<div class="empty">暂无规则。</div>'}</div><div class="row"><button class="ghost" onclick="addRule('${key}')">新增${label}</button></div>`;
  return block(accepted,'accepted_iteration_rules','已采纳纠错') + block(rejected,'rejected_iteration_rules','已驳回纠错');
}
function renderHistoryEditor() {
  const history = Array.isArray(selectedMemoryContent.history) ? selectedMemoryContent.history : [];
  const recent = history.map((entry,index)=>({entry,index})).slice(-30).reverse();
  return `<h3>最近聊天</h3><p class="note">可删除污染项，也可以修正明显错误文本。这里改的是记忆里的历史上下文，不会撤回 QQ 消息。</p>${recent.map(({entry,index})=>`
    <div class="history-item">
      <div class="entry-head">
        <strong>${entry.role === 'assistant' ? '亚托莉' : '用户'} ${entry.nickname ? ' · ' + escapeHtml(entry.nickname) : ''}</strong>
        <button class="danger" onclick="removeHistory(${index})">删除</button>
      </div>
      <textarea oninput="updateHistory(${index},this.value)">${escapeHtml(entry.text || '')}</textarea>
    </div>`).join('') || '<div class="empty">暂无聊天历史。</div>'}`;
}
function updateMemoryEntry(layer, index, key, value, numeric=false) {
  const memory = structuredMemory();
  if(!memory[layer] || !memory[layer][index]) return;
  memory[layer][index][key] = numeric && value !== '' ? Number(value) : value;
  if(key === 'key') memory[layer][index].memory_key = value;
  markMemoryDirty();
}
function removeMemoryEntry(layer, index) {
  const memory = structuredMemory();
  if(!memory[layer] || !memory[layer][index]) return;
  memory[layer].splice(index, 1);
  markMemoryDirty();
  renderMemoryModal();
}
function addMemoryEntryFromActivePane() {
  if(!selectedMemoryContent) return;
  const layer = memoryEntryLayerForPane();
  const memory = structuredMemory();
  let category = 'profile_fact';
  if(activeMemoryPane === 'memoryEvents') category = 'event';
  if(activeMemoryPane === 'memoryStyle') category = 'communication_style';
  const now = Math.floor(Date.now() / 1000);
  memory[layer].push({
    layer: layer.toUpperCase(),
    category,
    key: category + ':新记忆',
    value: '',
    confidence: layer === 'l1' ? 0.8 : 0.7,
    activity: 1.0,
    source: 'webui',
    created_at: now,
    updated_at: now,
    state: 'active',
    associations: []
  });
  markMemoryDirty();
  renderMemoryModal();
}
function updateRule(bucket, index, key, value) {
  selectedMemoryContent[bucket] = selectedMemoryContent[bucket] || [];
  if(!selectedMemoryContent[bucket][index]) return;
  selectedMemoryContent[bucket][index][key] = value;
  markMemoryDirty();
}
function addRule(bucket) {
  selectedMemoryContent[bucket] = selectedMemoryContent[bucket] || [];
  selectedMemoryContent[bucket].push({at:Math.floor(Date.now()/1000), action: bucket.startsWith('accepted') ? 'accept' : 'reject', rule:'', reason:'webui 手动添加'});
  markMemoryDirty();
  renderMemoryModal();
}
function removeRule(bucket, index) {
  selectedMemoryContent[bucket] = selectedMemoryContent[bucket] || [];
  selectedMemoryContent[bucket].splice(index, 1);
  markMemoryDirty();
  renderMemoryModal();
}
function updateHistory(index, value) {
  if(!Array.isArray(selectedMemoryContent.history) || !selectedMemoryContent.history[index]) return;
  selectedMemoryContent.history[index].text = value;
  markMemoryDirty();
}
function removeHistory(index) {
  if(!Array.isArray(selectedMemoryContent.history)) return;
  selectedMemoryContent.history.splice(index, 1);
  markMemoryDirty();
  renderMemoryModal();
}
function applyRawMemory() {
  try {
    selectedMemoryContent = JSON.parse($('memoryRawEditor').value);
  } catch(e) {
    return toast('JSON 格式错误：' + e.message);
  }
  markMemoryDirty();
  renderMemoryModal();
  toast('JSON 已应用，保存后生效');
}
async function saveSelectedMemory() {
  if(!currentMemoryId || !selectedMemoryContent) return toast('先打开一条记忆');
  const btn = $('memorySaveButton');
  btn.disabled = true; btn.textContent = '保存中...';
  try {
    const r = await api('/api/memory/save', {method:'POST', body:JSON.stringify({id:currentMemoryId, content:selectedMemoryContent})});
    setSaveState('已保存，下一轮聊天生效', false);
    toast('记忆已保存，已自动备份');
    await loadMemory();
    const d = await api('/api/memory/detail?id=' + encodeURIComponent(currentMemoryId));
    selectedMemory = d;
    selectedMemoryContent = JSON.parse(JSON.stringify(d.content || {}));
    renderMemoryModal();
  } catch(e) {
    toast('保存失败：' + e.message);
  } finally {
    btn.disabled = false; btn.textContent = '保存修改';
  }
}
async function deleteSelectedMemory() {
  if(!currentMemoryId) return toast('先打开一条记忆');
  if(!confirm('确认删除这个会话的全部记忆？删除前会自动备份。')) return;
  await api('/api/memory/delete', {method:'POST', body:JSON.stringify({id:currentMemoryId})});
  currentMemoryId = ''; selectedMemory = null; selectedMemoryContent = null; memoryDirty = false;
  $('memoryModal').classList.remove('show');
  await loadMemory(); toast('记忆已删除，已自动备份');
}
async function backupMemory() {
  await api('/api/memory/backup', {method:'POST', body:'{}'});
  toast('记忆已备份');
}
async function testChat() {
  $('testOut').textContent='亚托莉生成中...';
  const r = await api('/api/test-chat', {method:'POST', body:JSON.stringify({text:$('testText').value})});
  $('testOut').textContent = r.reply;
}
async function restartServices() {
  const r = await api('/api/restart', {method:'POST', body:'{}'});
  toast(r.message || r.error || '已执行');
}
loadStatus(); loadProfiles(); loadConfig();
</script>
</body>
</html>"""
