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
    main > section { min-width:0; }
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
    .model-workspace { display:grid; grid-template-columns:minmax(360px,.9fr) minmax(460px,1.1fr); gap:14px; align-items:start; }
    .model-profile-surface { margin-top:14px; }
    #modelProfileEditor { position:sticky; top:84px; }
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
    .current-models { display:grid; gap:10px; }
    .profile-columns { display:grid; grid-template-columns:repeat(auto-fit,minmax(300px,1fr)); gap:12px; align-items:start; }
    .profile-column { display:grid; gap:10px; border:1px solid var(--line); border-radius:7px; padding:10px; background:#f8fafc; min-width:0; }
    .profile-column h3 { margin:0; display:flex; justify-content:space-between; gap:8px; align-items:center; }
    .profile-column .profile { background:#fff; }
    .profile { border:1px solid var(--line); border-radius:7px; padding:12px; background:#fff; display:grid; gap:7px; }
    .profile.active { border-color:var(--blue); box-shadow:0 0 0 2px rgba(37,99,235,.12); }
    .profile-title { display:flex; justify-content:space-between; gap:10px; align-items:flex-start; }
    .section-head { display:flex; justify-content:space-between; gap:12px; align-items:flex-start; margin-bottom:10px; }
    .section-head h2 { margin:0; }
    .section-head .row { margin:0; }
    .preset-panel { border:1px solid var(--line); border-radius:7px; background:#f8fafc; padding:12px; margin-bottom:14px; display:grid; gap:10px; }
    .preset-panel h3 { margin:0; }
    .model-card { border:1px solid var(--line); border-radius:7px; background:#fff; padding:10px; display:grid; gap:8px; }
    .model-card.selected { border-color:var(--blue); box-shadow:0 0 0 2px rgba(37,99,235,.12); }
    .model-card-head { display:flex; justify-content:space-between; gap:10px; align-items:flex-start; }
    .model-card strong { overflow-wrap:anywhere; }
    .model-card .row { margin-top:2px; }
    .model-feedback { display:none; border:1px solid #bfdbfe; background:#eff6ff; color:#1d4ed8; border-radius:7px; padding:9px 10px; margin:10px 0 0; }
    .model-feedback.show { display:block; }
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
    .fact-grid { display:grid; grid-template-columns:repeat(2,minmax(220px,1fr)); gap:10px; margin:12px 0; }
    .fact { border:1px solid var(--line); border-radius:7px; background:#fff; padding:10px 12px; min-width:0; }
    .fact span { display:block; color:var(--muted); font-size:12px; margin-bottom:4px; }
    .fact strong { display:block; font-size:14px; overflow-wrap:anywhere; }
    .group-info-list { display:grid; gap:10px; margin-top:8px; }
    .group-info { border:1px solid var(--line); border-radius:7px; background:#fff; padding:12px; display:grid; gap:8px; }
    .group-info-head { display:flex; justify-content:space-between; gap:10px; align-items:flex-start; }
    .group-info-title { font-weight:800; overflow-wrap:anywhere; }
    .entry-list { display:grid; gap:10px; }
    .entry { border:1px solid var(--line); border-radius:7px; background:#fff; padding:12px; display:grid; gap:10px; }
    .entry-head { display:flex; justify-content:space-between; gap:10px; align-items:center; }
    .entry-grid { display:grid; grid-template-columns:180px 1fr 130px 130px; gap:10px; }
    .history-item { border:1px solid var(--line); border-radius:7px; background:#fff; padding:10px; display:grid; gap:8px; margin-bottom:8px; }
    .dirty { color:var(--amber); font-weight:700; }
    .saved { color:var(--green); font-weight:700; }
    .settings-section { border-top:1px solid var(--line); padding:18px 0 4px; margin-top:18px; }
    .settings-section h3 { margin-top:0; }
    .proactive-layout { display:grid; grid-template-columns:minmax(0,1.18fr) minmax(320px,.82fr); gap:14px; align-items:start; }
    .proactive-layout > * { min-width:0; }
    .proactive-block { border:1px solid var(--line); border-radius:7px; padding:14px; background:#fff; min-width:0; }
    .proactive-block h3 { margin-top:0; }
    .proactive-block .grid { grid-template-columns:repeat(2,minmax(0,1fr)); }
    .proactive-block label { min-width:0; }
    .voice-policy-grid .proactive-block { border:0; border-left:3px solid var(--line); border-radius:0; padding:0 0 0 14px; }
    .compact-input { min-width:84px; }
    .weight-grid { display:grid; grid-template-columns:repeat(2,minmax(150px,1fr)); gap:10px; }
    .switch-line { display:flex; align-items:center; gap:9px; min-height:38px; }
    .switch-line input { width:18px; height:18px; }
    .memory-score { font-weight:800; margin-bottom:6px; }
    .memory-plan { display:grid; gap:5px; margin-top:7px; }
    .plan-time-row { display:grid; grid-template-columns:minmax(120px,1fr) auto; gap:6px; align-items:center; }
    .plan-time-row input { min-width:0; padding:6px 8px; font-size:12px; }
    .plan-time-row button { padding:6px 9px; font-size:12px; }
    .relationship-controls { border-top:1px solid var(--line); border-bottom:1px solid var(--line); padding:14px 0; margin:14px 0; }
    .relationship-controls h3 { margin-top:0; }
    .voice-status { display:grid; grid-template-columns:repeat(3,minmax(160px,1fr)); gap:10px; }
    .voice-compare { display:grid; grid-template-columns:repeat(2,minmax(260px,1fr)); gap:12px; margin-top:14px; }
    .voice-result { border:1px solid var(--line); border-radius:7px; padding:12px; min-width:0; }
    .voice-result h3 { margin:0 0 10px; }
    .voice-result audio { margin-top:10px; }
    audio { width:100%; min-height:42px; }
    @media (max-width:1280px) {
      main { grid-template-columns:1fr; }
      #modelProfileEditor { position:static; }
    }
    @media (max-width:980px) {
      .model-workspace,.split { grid-template-columns:1fr; }
      .grid,.three,.profile-columns,.stat-grid,.fact-grid,.entry-grid,.proactive-layout,.weight-grid,.voice-status,.voice-compare { grid-template-columns:1fr; }
      .proactive-block .grid { grid-template-columns:1fr; }
      .section-head { flex-direction:column; }
      .section-head .row { width:100%; }
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
        <button class="tab" onclick="showTab(event,'voice')">语音</button>
        <button class="tab" onclick="showTab(event,'stickers')">表情包</button>
        <button class="tab" onclick="showTab(event,'memory')">记忆</button>
        <button class="tab" onclick="showTab(event,'test')">测试</button>
        <button class="tab" onclick="showTab(event,'advanced')">高级</button>
      </div>

      <div id="model" class="panel active">
        <div class="model-workspace">
          <div class="stack">
            <div class="surface">
              <h2>当前启用模型</h2>
              <div id="currentModel" class="current-models">读取中...</div>
              <div class="row">
                <button class="ghost" onclick="testCurrentChatModel()">测试当前聊天模型</button>
              </div>
            </div>
            <div class="surface">
              <div class="section-head">
                <div>
                  <h2>本机已部署模型</h2>
                  <p class="note" id="localModelInfo">读取中...</p>
                </div>
                <div class="row">
                  <button class="ghost" onclick="loadLocalModels({manual:true})">刷新</button>
                </div>
              </div>
              <div class="profile-list" id="localModelList"></div>
              <p class="model-feedback" id="localModelAction"></p>
            </div>
          </div>
          <div class="surface" id="modelProfileEditor">
            <h2 id="profileFormTitle">新建模型档案</h2>
            <p class="model-feedback" id="modelFillFeedback"></p>
            <input id="profileId" type="hidden">
            <div class="preset-panel">
              <h3>从厂商模型库填入</h3>
              <div class="grid">
                <label>厂商<select id="providerPreset" onchange="selectProviderPreset()"></select></label>
                <label>模型<select id="providerModelPreset" onchange="selectProviderModelPreset()"></select></label>
              </div>
              <div class="row">
                <button class="ghost" onclick="applySelectedProviderModel()">填入到下方档案</button>
              </div>
              <p class="note">这里只负责自动填接口地址、模型名和推荐参数；保存、启用仍由你手动确认。</p>
            </div>
            <h3>档案参数</h3>
            <div class="grid">
              <label>档案名称<input id="profileName" placeholder="例如：DeepSeek 官方"></label>
              <label>用途<select id="profileModelType">
                <option value="chat">聊天模型</option>
                <option value="vision">视觉模型</option>
                <option value="embedding">向量模型</option>
              </select></label>
              <label>服务商<input id="profileProvider" placeholder="例如：DeepSeek / Ollama / OpenAI兼容"></label>
              <label>接口地址<input id="profileBaseUrl" placeholder="https://api.deepseek.com/v1"></label>
              <label>模型名称<input id="profileModel" placeholder="deepseek-v4-flash"></label>
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
        <div class="surface model-profile-surface">
          <div class="section-head">
            <div>
              <h2>模型档案</h2>
              <p class="note">同一类模型只启用一个；聊天、视觉、向量互不挤占。点“编辑”会把档案带到右上表单。</p>
            </div>
            <div class="row">
              <button class="secondary" onclick="newProfile()">新建空档案</button>
            </div>
          </div>
          <div class="profile-list" id="profileList"></div>
        </div>
      </div>

      <div id="voice" class="panel">
        <div class="stack">
          <div class="surface">
            <div class="section-head">
              <div>
                <h2>语音服务</h2>
                <p class="note">识别与合成在独立进程运行。未就绪或推理失败时，QQ 回复会自动回退为文字。</p>
              </div>
              <div class="row"><button class="ghost" onclick="loadVoice()">刷新</button></div>
            </div>
            <div id="voiceServiceStatus" class="voice-status"></div>
          </div>
          <div class="split">
            <div class="surface">
              <h2>使用策略</h2>
              <div class="grid">
                <label class="switch-line"><input id="voiceAsrEnabled" type="checkbox">识别用户语音</label>
                <label class="switch-line"><input id="voiceTtsEnabled" type="checkbox">允许模型自主发语音</label>
                <label class="switch-line"><input id="voiceGroupEnabled" type="checkbox">允许群聊语音</label>
                <label class="switch-line"><input id="voiceReplyToVoice" type="checkbox">语音消息优先考虑语音回复</label>
                <label>语音服务地址<input id="voiceServiceUrl" value="http://127.0.0.1:8790"></label>
                <label>当前角色档案<select id="voiceProfileId" onchange="loadSelectedVoiceProfile()"></select></label>
                <label>单条最大字数<input id="voiceMaxChars" type="number" min="20" max="500"></label>
                <label>同会话冷却秒数<input id="voiceCooldown" type="number" min="0" max="3600"></label>
              </div>
              <div class="row"><button onclick="saveVoice()">保存语音配置</button></div>
            </div>
            <div class="surface">
              <h2>亚托莉语音档案</h2>
              <div class="grid">
                <label>显示名称<input id="voiceDisplayName" value="亚托莉"></label>
                <label>合成引擎<select id="voiceProvider"><option value="gpt_sovits">GPT-SoVITS</option></select></label>
                <label>引擎接口<input id="voiceApiUrl" value="http://127.0.0.1:9880/tts"></label>
                <label>参考音频语言<select id="voicePromptLanguage"><option value="ja">日语</option><option value="zh">中文</option><option value="en">英语</option></select></label>
              </div>
              <label>参考音频原文<textarea id="voicePromptText" placeholder="必须与参考音频实际台词一致"></textarea></label>
              <label>参考音频路径<input id="voiceReferencePath" readonly placeholder="尚未上传"></label>
              <div class="row">
                <input id="voiceReferenceFile" type="file" accept=".wav,.flac,.mp3,.ogg,.m4a,.aac,audio/*">
                <button class="ghost" onclick="uploadVoiceReference()">上传参考音频</button>
              </div>
              <p class="note">只使用你有权使用的清晰、单人、无背景音乐音频。参考原文和音频不一致会明显降低音色与发音质量。</p>
            </div>
          </div>
          <div class="surface">
            <div class="section-head">
              <div>
                <h2>自主语音与通话</h2>
                <p class="note">模型负责判断语境是否适合；这里仅设置边界。明确要求语音可独立放行，自主语音仍需达到关系阈值。</p>
              </div>
            </div>
            <div class="three voice-policy-grid">
              <div class="proactive-block">
                <h3>触发方式</h3>
                <div class="grid">
                  <label class="switch-line"><input id="voiceBehaviorEnabled" type="checkbox">启用语音决策策略</label>
                  <label class="switch-line"><input id="voiceExplicitEnabled" type="checkbox">明确要求时允许语音</label>
                  <label class="switch-line"><input id="voiceExplicitGuardEnabled" type="checkbox">模型漏调工具时仍强制语音</label>
                  <label class="switch-line"><input id="voiceInputReplyEnabled" type="checkbox">允许用语音回应语音</label>
                  <label class="switch-line"><input id="voiceProactiveEnabled" type="checkbox">主动消息可自主使用语音</label>
                  <label class="switch-line"><input id="voiceOriginalClipEnabled" type="checkbox">优先使用匹配的完整原声</label>
                  <label class="switch-line"><input id="voiceQualityGateEnabled" type="checkbox">发送前检查漏字错字</label>
                  <label class="switch-line"><input id="voiceSingingEnabled" type="checkbox">启用歌唱素材回复</label>
                  <label>允许回读错误率<input id="voiceQualityMaxError" type="number" min="0" max="1" step="0.01"></label>
                  <label>质量检查重试次数<input id="voiceQualityRetries" type="number" min="0" max="3"></label>
                  <label>免打扰开始<input id="voiceQuietStart" type="time"></label>
                  <label>免打扰结束<input id="voiceQuietEnd" type="time"></label>
                </div>
              </div>
              <div class="proactive-block">
                <h3>关系阈值</h3>
                <div class="grid">
                  <label class="switch-line"><input id="voicePrivateAutoEnabled" type="checkbox">私聊可自主发语音</label>
                  <label>私聊最低好感<input id="voicePrivateAffection" type="number" min="0" max="100" step="1"></label>
                  <label>私聊最低消息量<input id="voicePrivateMessages" type="number" min="0" max="100000"></label>
                  <label class="switch-line"><input id="voiceGroupAutoEnabled" type="checkbox">群聊可自主发语音</label>
                  <label>群最低活跃度<input id="voiceGroupActivity" type="number" min="0" max="100" step="1"></label>
                  <label>群最低消息量<input id="voiceGroupMessages" type="number" min="0" max="100000"></label>
                </div>
              </div>
              <div class="proactive-block">
                <h3>浏览器通话</h3>
                <div class="grid">
                  <label class="switch-line"><input id="voiceCallsEnabled" type="checkbox">允许模型邀请私聊通话</label>
                  <label>通话最低好感<input id="voiceCallAffection" type="number" min="0" max="100" step="1"></label>
                  <label>通话最低消息量<input id="voiceCallMessages" type="number" min="0" max="100000"></label>
                  <label>邀请有效分钟<input id="voiceCallExpiry" type="number" min="1" max="1440"></label>
                  <label>最长通话分钟<input id="voiceCallMaxMinutes" type="number" min="1" max="240"></label>
                </div>
                <label>用户可访问的通话地址<input id="voiceCallBaseUrl" placeholder="http://127.0.0.1:8787"></label>
                <p class="note">跨设备使用需填写 HTTPS 公网地址，否则浏览器通常无法授权麦克风。</p>
                <div class="row"><button class="ghost" onclick="createVoiceCallTest()">创建本机测试通话</button></div>
                <div class="natural-box" id="voiceCallTestOut">保存配置后可生成一次性测试链接，不会发送 QQ 消息。</div>
              </div>
            </div>
          </div>
          <div class="surface">
            <div class="section-head">
              <div>
                <h2>语音识别优化</h2>
                <p class="note">每行填写“正确词 = 常见误识别1, 常见误识别2”，保存后立即生效。</p>
              </div>
            </div>
            <label>角色名与专有词纠错<textarea id="voiceAsrLexicon" rows="6" placeholder="亚托莉 = 亚托利, 亚托丽"></textarea></label>
            <p class="note">音频会先统一为 16kHz 单声道 PCM，再由 VAD 去除长停顿并分段；此处只纠正明确别名，不会改写普通句子。</p>
          </div>
          <div class="surface">
            <div class="section-head">
              <div>
                <h2>语音合成优化</h2>
                <p class="note">每行填写“原文 = 中文读法 | English pronunciation | 日本語の読み方”。</p>
              </div>
            </div>
            <label>中英日发音词典<textarea id="voiceTtsPronunciations" rows="6" placeholder="ATRI = 亚托莉 | Atri | アトリ"></textarea></label>
            <p class="note">保存后立即生效。合成结果会自动裁掉异常首尾静音，并在不削波的前提下统一响度。</p>
          </div>
          <div class="surface">
            <h2>合成试听</h2>
            <div class="grid">
              <label>试听文本<input id="voicePreviewText" value="主人，我一直都在这里哦。"></label>
              <label>情绪<select id="voicePreviewEmotion"><option value="gentle">温柔</option><option value="neutral">自然</option><option value="happy">开心</option><option value="shy">害羞</option><option value="sad">难过</option><option value="sleepy">困倦</option><option value="serious">认真</option><option value="surprised">惊讶</option></select></label>
              <label>表达方式<select id="voicePreviewMode"><option value="speech">普通语音</option><option value="singing">歌唱素材</option></select></label>
            </div>
            <div class="row"><button onclick="previewVoice()">生成试听</button></div>
            <p class="note" id="voicePreviewInfo">试听不会发送到 QQ。</p>
            <audio id="voicePreviewAudio" controls></audio>
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
            <option value="person">人物档案</option>
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
        <div class="stack">
          <div class="surface">
            <h2>聊天回复测试</h2>
            <textarea id="testText" placeholder="例如：我今天好累，亚托莉你会怎么回？"></textarea>
            <div class="row"><button onclick="testChat()">生成回复</button></div>
            <div class="out" id="testOut"></div>
          </div>
          <div class="surface">
            <div class="section-head">
              <div><h2>语音识别测试</h2><p class="note" id="testVoiceState">读取语音服务状态...</p></div>
              <div class="row"><button class="ghost" onclick="loadVoiceTestState()">刷新状态</button></div>
            </div>
            <div class="row">
              <label>识别语言<select id="testAsrLanguage"><option value="auto">自动检测</option><option value="zh">中文</option><option value="en">English</option><option value="ja">日本語</option></select></label>
              <input id="testAsrFile" type="file" accept=".wav,.flac,.mp3,.ogg,.m4a,.aac,audio/*" onchange="window._recordedAsrFile=null">
              <button onclick="testVoiceRecognition()">识别文件</button>
              <button id="testAsrRecordButton" class="ghost" onclick="startAsrRecording()">开始说话</button>
              <button id="testAsrStopButton" class="ghost" onclick="stopAsrRecording()" disabled>停止并识别</button>
            </div>
            <div class="natural-box" id="testAsrOut">等待选择音频。</div>
          </div>
          <div class="surface">
            <h2>语音合成测试</h2>
            <div class="grid">
              <label>测试文本<input id="testTtsText" value="主人，今天也请让我陪在你身边。"></label>
              <label>语言<select id="testTtsLanguage" onchange="useVoiceLanguageSample()"><option value="zh">中文</option><option value="en">English</option><option value="ja">日本語</option></select></label>
              <label>情绪<select id="testTtsEmotion"><option value="gentle">温柔</option><option value="neutral">自然</option><option value="happy">开心</option><option value="shy">害羞</option><option value="sad">难过</option><option value="sleepy">困倦</option><option value="serious">认真</option><option value="surprised">惊讶</option></select></label>
              <label>情绪强度<input id="testTtsIntensity" type="range" min="0" max="1" step="0.05" value="0.55"></label>
            </div>
            <div class="row"><button id="testTtsCompareButton" onclick="testVoiceComparison()">生成 A/B 试听</button></div>
            <p class="note" id="testTtsOut">同一文本会依次合成，避免两套模型同时占用显存。</p>
            <div class="voice-compare">
              <div class="voice-result">
                <h3>候选 A</h3>
                <label>语音档案<select id="testTtsProfileA"></select></label>
                <p class="note" id="testTtsOutA">等待生成。</p>
                <audio id="testTtsAudioA" controls></audio>
              </div>
              <div class="voice-result">
                <h3>候选 B</h3>
                <label>语音档案<select id="testTtsProfileB"></select></label>
                <p class="note" id="testTtsOutB">等待生成。</p>
                <audio id="testTtsAudioB" controls></audio>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div id="advanced" class="panel">
        <div class="section-head">
          <div>
            <h2>高级配置</h2>
            <p class="note">集中管理消息发送方式和主动互动策略。模型、接口和视觉能力统一在“模型”页面配置。</p>
          </div>
        </div>
        <div class="settings-section">
          <h3>回复与发送</h3>
          <div class="grid" id="configForm"></div>
          <p class="note">语音概率仅影响普通消息；用户明显难受或疲惫时会提高到至少 70%。明确要求语音和回应用户语音不受该概率限制。</p>
          <div class="row">
            <button onclick="saveConfig()">保存回复配置</button>
            <button class="ghost" onclick="loadConfig()">放弃页面修改</button>
          </div>
        </div>
        <div class="settings-section">
          <div class="section-head">
            <div>
              <h3>主动互动</h3>
              <p class="note">按亲密度和活跃度随机安排；用户与群聊的具体计划统一在“记忆”页面查看。</p>
            </div>
            <div class="row"><button class="ghost" onclick="loadProactive()">刷新状态</button></div>
          </div>
          <div class="proactive-layout">
            <div class="stack">
              <div class="proactive-block">
                <h3>运行规则</h3>
                <p class="note" id="proactiveFeatureState">读取中...</p>
                <div class="grid">
                  <label class="switch-line"><input id="proactiveEngineEnabled" type="checkbox">启用新版主动调度器</label>
                  <label class="switch-line"><input id="proactiveEnabled" type="checkbox">允许发送主动消息</label>
                  <label class="switch-line"><input id="proactiveOwnerOnly" type="checkbox">私聊仅限主人</label>
                  <label class="switch-line"><input id="proactiveUseAi" type="checkbox">优先由聊天模型生成</label>
                  <label class="switch-line"><input id="proactiveGuidedTopics" type="checkbox">话题使用引导式开场</label>
                  <label>时区<input id="proactiveTimezone" value="Asia/Shanghai"></label>
                  <label>免打扰开始<input id="proactiveQuietStart" type="time"></label>
                  <label>免打扰结束<input id="proactiveQuietEnd" type="time"></label>
                  <label>检查间隔（秒）<input id="proactiveCheckSeconds" type="number" min="15" max="3600"></label>
                  <label>连续未回复倍率<input id="proactiveBackoff" type="number" min="1" max="3" step="0.1"></label>
                  <label>参考最近消息数<input id="proactiveHistoryLimit" type="number" min="0" max="20"></label>
                  <label>主动消息最大字数<input id="proactiveMaxChars" type="number" min="20" max="240"></label>
                </div>
              </div>
              <div class="proactive-block">
                <h3>受众门槛</h3>
                <p class="note">主人不受私聊门槛限制；其他用户必须同时满足好感、近期活跃和消息量条件。群聊只读取群内公开上下文。</p>
                <div class="grid">
                  <label>其他用户最低好感<input id="proactivePrivateMinAffection" type="number" min="0" max="100" step="1"></label>
                  <label>私聊活跃期（天）<input id="proactivePrivateActiveDays" type="number" min="1" max="365"></label>
                  <label>私聊最低消息量<input id="proactivePrivateMinMessages" type="number" min="1" max="10000"></label>
                  <label class="switch-line"><input id="proactiveGroupEnabled" type="checkbox">启用活跃群聊</label>
                  <label>群最低活跃度<input id="proactiveGroupMinActivity" type="number" min="0" max="100" step="1"></label>
                  <label>群活跃期（天）<input id="proactiveGroupActiveDays" type="number" min="1" max="90"></label>
                  <label>群最低消息量<input id="proactiveGroupMinMessages" type="number" min="1" max="100000"></label>
                  <label>群随机间隔下限（小时）<input id="proactiveGroupMinHours" type="number" min="0.25" max="168" step="0.25"></label>
                  <label>群随机间隔上限（小时）<input id="proactiveGroupMaxHours" type="number" min="0.25" max="336" step="0.25"></label>
                  <label>单群每日上限<input id="proactiveGroupDailyLimit" type="number" min="0" max="12"></label>
                </div>
              </div>
              <div class="proactive-block">
                <h3>亲密度与频率</h3>
                <div class="scroll"><table>
                  <thead><tr><th>阶段</th><th>启用</th><th>好感范围</th><th>随机间隔（小时）</th><th>每日上限</th></tr></thead>
                  <tbody id="proactiveTierRows"></tbody>
                </table></div>
              </div>
              <div class="proactive-block">
                <h3>私聊内容权重</h3>
                <div class="weight-grid" id="proactiveWeights"></div>
                <p class="note">早安和晚安只在对应时段参与抽取；权重为 0 表示禁用该类型。</p>
              </div>
              <div class="proactive-block">
                <h3>群聊内容权重</h3>
                <div class="weight-grid" id="proactiveGroupWeights"></div>
              </div>
              <div class="row">
                <button onclick="saveProactive()">保存主动互动配置</button>
                <button class="ghost" onclick="loadProactive()">放弃页面修改</button>
              </div>
            </div>
            <div class="stack">
              <div class="proactive-block">
                <h3>文案预览</h3>
                <div class="grid">
                  <label>预览场景<select id="proactivePreviewScope" onchange="renderProactivePreviewTypes()"><option value="private">私聊</option><option value="group">群聊</option></select></label>
                  <label>内容类型<select id="proactivePreviewType"></select></label>
                  <label>QQ / 群号（可留空）<input id="proactivePreviewUser" inputmode="numeric" placeholder="默认使用首个入选目标"></label>
                </div>
                <div class="row"><button onclick="previewProactive()">生成预览</button></div>
                <div class="out" id="proactivePreviewOut">预览不会发送 QQ 消息。</div>
              </div>
              <div class="proactive-block">
                <h3>计划说明</h3>
                <p class="note">每个用户和群聊只保留一份计划。修改门槛或频率后，记忆页会显示最新的入选结果、下次时间、内容类型和未入选原因。</p>
              </div>
            </div>
          </div>
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
  ["REPLY_MODE","回复模式","select"],
  ["MESSAGE_SPLIT_MAX_CHARS","单条字数","number"],
  ["MESSAGE_SPLIT_MAX_PARTS","最多分条","number"],
  ["MESSAGE_SEND_DELAY_MIN","最短发送间隔","number"],
  ["MESSAGE_SEND_DELAY_MAX","最长发送间隔","number"],
  ["STICKER_CHANCE","表情概率","number"],
  ["STICKER_COOLDOWN_SECONDS","表情冷却秒数","number"],
  ["REPLY_VOICE_PROBABILITY","语音概率（%）","voice-probability"]
];
const categoryLabels = {
  interest:"兴趣爱好", preference:"偏好/忌口", profile_fact:"用户资料", habit:"生活习惯", communication_style:"聊天习惯",
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
window._localModels = [];
window._selectedLocalModelName = "";
window._activeProfileIds = {};
window._profileTypes = [];
window._proactive = null;
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
  if(id==='advanced') { loadConfig(); loadReplyVoiceProbability(); loadProactive(); }
  if(id==='model') loadProfiles();
  if(id==='voice') loadVoice();
  if(id==='test') loadVoiceTestState();
}

function voiceConfigValue(cfg, key) {
  const item = cfg[key] || {};
  return item.raw !== '' && item.raw !== undefined ? item.raw : item.value;
}
async function loadVoice() {
  const data = await api('/api/voice');
  window._voiceData = data;
  const cfg = data.config || {};
  const service = data.service || {};
  const asr = service.asr || {};
  const configuredProfile = String(voiceConfigValue(cfg,'VOICE_PROFILE') || 'atri');
  const profileSelect = $('voiceProfileId');
  profileSelect.innerHTML = (data.profiles || []).map(profile=>`<option value="${escapeHtml(profile.id)}">${escapeHtml(profile.display_name || profile.id)}${profile.ready ? '' : ' · 未就绪'}</option>`).join('');
  const fallbackProfile = (data.profiles || []).find(profile=>profile.ready)?.id || (data.profiles || [])[0]?.id || 'atri';
  profileSelect.value = (data.profiles || []).some(profile=>profile.id===configuredProfile) ? configuredProfile : fallbackProfile;
  $('voiceAsrEnabled').checked = String(voiceConfigValue(cfg,'VOICE_ASR_ENABLED')).toLowerCase()==='true';
  $('voiceTtsEnabled').checked = String(voiceConfigValue(cfg,'VOICE_TTS_ENABLED')).toLowerCase()==='true';
  $('voiceGroupEnabled').checked = String(voiceConfigValue(cfg,'VOICE_GROUP_ENABLED')).toLowerCase()==='true';
  $('voiceReplyToVoice').checked = String(voiceConfigValue(cfg,'VOICE_REPLY_TO_VOICE')).toLowerCase()==='true';
  $('voiceServiceUrl').value = voiceConfigValue(cfg,'VOICE_SERVICE_URL') || 'http://127.0.0.1:8790';
  $('voiceMaxChars').value = voiceConfigValue(cfg,'VOICE_MAX_CHARS') || 160;
  $('voiceCooldown').value = voiceConfigValue(cfg,'VOICE_COOLDOWN_SECONDS') || 30;
  $('voiceAsrLexicon').value = data.asr_lexicon_text || '';
  $('voiceTtsPronunciations').value = data.tts_pronunciation_text || '';
  const behavior = data.behavior || {};
  $('voiceBehaviorEnabled').checked = behavior.enabled !== false;
  $('voiceExplicitEnabled').checked = behavior.explicit_requests_enabled !== false;
  $('voiceExplicitGuardEnabled').checked = behavior.explicit_delivery_guard_enabled !== false;
  $('voiceInputReplyEnabled').checked = behavior.reply_to_voice_enabled !== false;
  $('voiceProactiveEnabled').checked = !!behavior.proactive_voice_enabled;
  $('voiceOriginalClipEnabled').checked = behavior.original_clip_enabled !== false;
  $('voiceQualityGateEnabled').checked = behavior.quality_gate_enabled !== false;
  $('voiceSingingEnabled').checked = behavior.singing_enabled !== false;
  $('voiceQualityMaxError').value = behavior.quality_max_error_rate ?? 0.22;
  $('voiceQualityRetries').value = behavior.quality_retries ?? 1;
  $('voicePrivateAutoEnabled').checked = behavior.private_autonomous_enabled !== false;
  $('voicePrivateAffection').value = behavior.private_min_affection ?? 70;
  $('voicePrivateMessages').value = behavior.private_min_messages ?? 5;
  $('voiceGroupAutoEnabled').checked = !!behavior.group_autonomous_enabled;
  $('voiceGroupActivity').value = behavior.group_min_activity ?? 65;
  $('voiceGroupMessages').value = behavior.group_min_messages ?? 20;
  $('voiceQuietStart').value = behavior.quiet_start || '00:30';
  $('voiceQuietEnd').value = behavior.quiet_end || '07:00';
  $('voiceCallsEnabled').checked = !!behavior.calls_enabled;
  $('voiceCallAffection').value = behavior.call_min_affection ?? 85;
  $('voiceCallMessages').value = behavior.call_min_messages ?? 20;
  $('voiceCallBaseUrl').value = behavior.call_base_url || 'http://127.0.0.1:8787';
  $('voiceCallExpiry').value = behavior.call_expiry_minutes ?? 10;
  $('voiceCallMaxMinutes').value = behavior.call_max_minutes ?? 30;
  loadSelectedVoiceProfile();
  const profile = (data.profiles || []).find(p=>p.id===profileSelect.value) || {};
  const library = service.original_library || {};
  const quality = service.quality_gate || {};
  const singing = service.singing || {};
  $('voiceServiceStatus').innerHTML = [
    ['独立服务', service.ok, service.error || '127.0.0.1'],
    ['语音识别', asr.dependency_available && !asr.load_error, asr.loaded ? `模型已加载 · ${asr.audio_format || '原始音频'} · ${Number((asr.hotwords || []).length)} 个专有词` : (asr.loading ? '模型正在预热' : (asr.load_error || asr.model || '依赖未安装'))],
    ['角色音色', profile.ready, profile.ready ? '参考音频有效' : '等待参考音频'],
    ['原声素材库', library.available, library.available ? `${Number(library.clips || 0)} 条可检索原声` : (library.root || '素材目录不存在')],
    ['语音质量门', quality.enabled, quality.enabled ? `回读错误率上限 ${Math.round(Number(quality.maximum_error_rate || 0)*100)}% · 最多重试 ${Number(quality.retries || 0)} 次` : '服务端未启用'],
    ['歌唱素材', singing.ready, singing.ready ? `${Number(singing.clips || 0)} 条完整歌声` : '等待在歌唱目录加入完整素材']
  ].map(([name,ok,detail])=>`<div class="pill"><div><strong>${escapeHtml(name)}</strong><div class="memory-meta">${escapeHtml(detail)}</div></div><span class="${ok?'ok':'bad'}">${ok?'就绪':'未就绪'}</span></div>`).join('');
}
function loadSelectedVoiceProfile() {
  const profile = (window._voiceData?.profiles || []).find(item=>item.id===$('voiceProfileId').value) || {};
  $('voiceDisplayName').value = profile.display_name || '亚托莉';
  $('voiceProvider').value = profile.tts_provider || 'gpt_sovits';
  $('voiceApiUrl').value = profile.api_url || 'http://127.0.0.1:9880/tts';
  $('voicePromptLanguage').value = profile.prompt_language || 'ja';
  $('voicePromptText').value = profile.prompt_text || '';
  $('voiceReferencePath').value = profile.reference_audio || '';
}
async function saveVoice() {
  const profileId = $('voiceProfileId').value.trim() || 'atri';
  const body = {
    config: {
      VOICE_ASR_ENABLED:$('voiceAsrEnabled').checked,
      VOICE_TTS_ENABLED:$('voiceTtsEnabled').checked,
      VOICE_GROUP_ENABLED:$('voiceGroupEnabled').checked,
      VOICE_REPLY_TO_VOICE:$('voiceReplyToVoice').checked,
      VOICE_SERVICE_URL:$('voiceServiceUrl').value.trim(),
      VOICE_PROFILE:profileId,
      VOICE_MAX_CHARS:$('voiceMaxChars').value,
      VOICE_COOLDOWN_SECONDS:$('voiceCooldown').value
    },
    asr_lexicon_text:$('voiceAsrLexicon').value,
    tts_pronunciation_text:$('voiceTtsPronunciations').value,
    behavior: {
      enabled:$('voiceBehaviorEnabled').checked,
      explicit_requests_enabled:$('voiceExplicitEnabled').checked,
      explicit_delivery_guard_enabled:$('voiceExplicitGuardEnabled').checked,
      reply_to_voice_enabled:$('voiceInputReplyEnabled').checked,
      reply_voice_probability:Number(window._voiceData?.behavior?.reply_voice_probability ?? 35),
      emotional_reply_voice_probability:Number(window._voiceData?.behavior?.emotional_reply_voice_probability ?? 70),
      private_autonomous_enabled:$('voicePrivateAutoEnabled').checked,
      private_min_affection:Number($('voicePrivateAffection').value),
      private_min_messages:Number($('voicePrivateMessages').value),
      group_autonomous_enabled:$('voiceGroupAutoEnabled').checked,
      group_min_activity:Number($('voiceGroupActivity').value),
      group_min_messages:Number($('voiceGroupMessages').value),
      proactive_voice_enabled:$('voiceProactiveEnabled').checked,
      original_clip_enabled:$('voiceOriginalClipEnabled').checked,
      quality_gate_enabled:$('voiceQualityGateEnabled').checked,
      quality_max_error_rate:Number($('voiceQualityMaxError').value),
      quality_retries:Number($('voiceQualityRetries').value),
      singing_enabled:$('voiceSingingEnabled').checked,
      quiet_start:$('voiceQuietStart').value,
      quiet_end:$('voiceQuietEnd').value,
      timezone:'Asia/Shanghai',
      calls_enabled:$('voiceCallsEnabled').checked,
      call_min_affection:Number($('voiceCallAffection').value),
      call_min_messages:Number($('voiceCallMessages').value),
      call_base_url:$('voiceCallBaseUrl').value.trim(),
      call_expiry_minutes:Number($('voiceCallExpiry').value),
      call_max_minutes:Number($('voiceCallMaxMinutes').value)
    },
    profile: {
      id:profileId,
      display_name:$('voiceDisplayName').value.trim() || '亚托莉',
      tts_provider:$('voiceProvider').value,
      api_url:$('voiceApiUrl').value.trim(),
      prompt_language:$('voicePromptLanguage').value,
      prompt_text:$('voicePromptText').value.trim()
    }
  };
  await api('/api/voice/save', {method:'POST', body:JSON.stringify(body)});
  await loadVoice();
  toast('语音配置已保存，新消息立即使用');
}
async function uploadVoiceReference() {
  const file = $('voiceReferenceFile').files[0];
  if(!file) return toast('先选择参考音频');
  const form = new FormData();
  form.append('profile_id', $('voiceProfileId').value.trim() || 'atri');
  form.append('file', file);
  await api('/api/voice/reference', {method:'POST', body:form});
  await loadVoice();
  toast('参考音频已保存');
}
async function createVoiceCallTest() {
  const out = $('voiceCallTestOut');
  out.textContent = '正在保存配置并创建通话...';
  try {
    await saveVoice();
    const result = await api('/api/voice-call/test-invite', {method:'POST', body:'{}'});
    out.innerHTML = `测试邀请已创建，十分钟内有效：<a href="${escapeHtml(result.call_url)}" target="_blank" rel="noopener">打开通话页面</a>`;
  } catch(error) {
    out.textContent = '创建失败：' + error.message;
  }
}
async function previewVoice() {
  const out = $('voicePreviewInfo');
  const started = Date.now();
  out.textContent = '正在切换模型并合成 · 0 秒';
  const ticker = setInterval(()=>{ out.textContent = `正在切换模型并合成 · ${Math.floor((Date.now()-started)/1000)} 秒`; }, 1000);
  try {
    const result = await api('/api/voice/preview', {method:'POST', body:JSON.stringify({
      text:$('voicePreviewText').value,
      emotion:$('voicePreviewEmotion').value,
      mode:$('voicePreviewMode').value,
      profile:$('voiceProfileId').value.trim() || 'atri'
    })});
    $('voicePreviewAudio').src = result.audio_url;
    $('voicePreviewAudio').load();
    const quality = result.quality;
    const qualityText = quality ? ` · 回读错误率 ${Math.round(Number(quality.error_rate || 0)*100)}%` : '';
    const source = result.source === 'original_clip' ? '完整原声' : '模型合成';
    out.textContent = `${source}完成 · ${result.elapsed_ms} ms${qualityText}，可以直接播放。`;
  } catch(error) {
    out.textContent = '试听失败：' + error.message;
  } finally {
    clearInterval(ticker);
  }
}
async function loadStatus() {
  const s = await api('/api/status');
  $('status').innerHTML = [
    ['Atri 服务', s.atri], ['NapCat 连接', s.napcat], ['Ollama', s.ollama], ['语音服务', s.voice], ['WebUI', s.webui]
  ].map(([k,v])=>`<div class="pill"><span>${k}</span><span class="${v?'ok':'bad'}">${v?'正常':'未连接'}</span></div>`).join('')
  + `<p class="note">机器人 QQ：${escapeHtml(s.bot_qq)}<br>模型：${escapeHtml(s.model)}<br>接口：${escapeHtml(s.base_url)}<br>回复模式：${escapeHtml(s.reply_mode)}</p>`;
}
async function testCurrentChatModel() {
  const feedback = $('modelFillFeedback');
  if(feedback) {
    feedback.textContent = '正在测试当前聊天模型...';
    feedback.classList.add('show');
  }
  try {
    const r = await api('/api/test-chat', {method:'POST', body:JSON.stringify({text:'只回复 OK，用来测试当前聊天模型是否可用。'})});
    const text = r.used_ai
      ? `当前聊天模型可用。测试回复：${r.reply || ''}`
      : `当前聊天模型没有连上，正在走兜底。错误：${r.error || '未知错误'}\n兜底回复：${r.reply || ''}`;
    if(feedback) feedback.textContent = text;
    toast(r.used_ai ? '当前聊天模型测试通过' : '当前聊天模型未连上，已显示错误');
  } catch(e) {
    const text = '当前聊天模型测试失败：' + (e.message || '未知错误');
    if(feedback) feedback.textContent = text;
    toast(text);
  }
}
async function loadProfiles() {
  const data = await api('/api/model-profiles');
  window._profiles = data.profiles || [];
  window._providerCatalog = data.provider_catalog || [];
  window._activeProfileIds = data.active_ids || {};
  window._profileTypes = data.profile_types || [];
  $('currentModel').innerHTML = renderCurrentModels(data.current_by_type || {chat:data.current || {}});
  $('profileList').innerHTML = renderProfileColumns(window._profiles);
  renderProviderSelectors();
  await loadLocalModels();
}
function renderProfileColumns(profiles) {
  const types = [
    {id:'chat', name:'聊天模型'},
    {id:'vision', name:'视觉模型'},
    {id:'embedding', name:'向量模型'}
  ];
  return `<div class="profile-columns">${types.map(type=>{
    const rows = profiles
      .map((profile,index)=>({profile,index}))
      .filter(item=>(item.profile.model_type || 'chat') === type.id);
    return `<div class="profile-column">
      <h3><span>${escapeHtml(type.name)}</span><span class="badge">${rows.length}</span></h3>
      ${rows.map(item=>renderProfileCard(item.profile, item.index)).join('') || '<p class="note">暂无此类档案。</p>'}
    </div>`;
  }).join('')}</div>`;
}
function renderProfileCard(p, index) {
  const active = p.id===(window._activeProfileIds || {})[p.model_type];
  return `
    <div class="profile ${active?'active':''}">
      <div class="profile-title">
        <div><strong>${escapeHtml(p.name)}</strong><br><span class="note">${escapeHtml(modelTypeLabel(p.model_type))} · ${escapeHtml(p.provider)} · ${escapeHtml(p.model)}</span></div>
        <span class="badge ${active?'active':''}">${active?'当前启用':'可选择'}</span>
      </div>
      <div class="note">接口：${escapeHtml(p.base_url)}<br>API Key：${p.has_api_key ? '已保存（' + escapeHtml(p.api_key_masked) + '）' : '未填写'}</div>
      <div class="row">
        <button class="ghost" onclick="selectProfileByIndex(${index})">编辑</button>
        ${modelTypeCanActivate(p.model_type) ? `<button onclick="activateProfileByIndex(${index})">启用为${escapeHtml(modelTypeLabel(p.model_type))}</button>` : '<button class="secondary" disabled>仅保存档案</button>'}
        <button class="danger" onclick="deleteProfileByIndex(${index})">删除</button>
      </div>
    </div>`;
}
function renderCurrentModels(currentByType) {
  return ['chat','vision'].map(type=>{
    const c = currentByType[type] || {};
    const enabled = type === 'chat' ? true : !!c.enabled;
    const title = modelTypeLabel(type);
    const status = enabled && c.model ? '已启用' : '未配置';
    return `<div class="profile ${enabled && c.model ? 'active' : ''}" style="margin-bottom:10px">
      <div class="profile-title">
        <div><strong>${escapeHtml(title)}</strong><br><span class="note">${escapeHtml(c.name || '未配置')} · ${escapeHtml(c.model || '未填写')}</span></div>
        <span class="badge ${enabled && c.model ? 'active' : 'warn'}">${status}</span>
      </div>
      <div class="note">接口：${escapeHtml(c.base_url || '未填写')}<br>API Key：${c.has_api_key ? '已保存（' + escapeHtml(c.api_key_masked) + '）' : '未填写'}${type === 'chat' ? `<br>参数：温度 ${escapeHtml(c.temperature ?? '')}，重复惩罚 ${escapeHtml(c.frequency_penalty ?? '')}，最大输出 ${escapeHtml(c.max_tokens ?? '')}` : ''}</div>
    </div>`;
  }).join('');
}
function modelTypeLabel(type) {
  if(type === 'vision') return '视觉模型';
  if(type === 'embedding') return '向量模型';
  return '聊天模型';
}
function modelTypeCanActivate(type) {
  return type === 'chat' || type === 'vision';
}
function renderProviderSelectors() {
  const providers = window._providerCatalog || [];
  const providerSelect = $('providerPreset');
  const modelSelect = $('providerModelPreset');
  if(!providerSelect || !modelSelect) return;
  providerSelect.innerHTML = providers.map(p=>`<option value="${escapeHtml(p.id)}">${escapeHtml(p.name)}</option>`).join('');
  if(providers.length && !providers.some(p=>p.id === providerSelect.value)) providerSelect.value = providers[0].id;
  renderProviderModelOptions();
}
function selectedProviderPreset() {
  const id = $('providerPreset')?.value || '';
  return (window._providerCatalog || []).find(p=>p.id === id) || null;
}
function renderProviderModelOptions() {
  const provider = selectedProviderPreset();
  const modelSelect = $('providerModelPreset');
  if(!modelSelect) return;
  const models = provider && Array.isArray(provider.models) ? provider.models : [];
  modelSelect.innerHTML = models.map(m=>`<option value="${escapeHtml(m.id)}">${escapeHtml(m.label || m.id)}</option>`).join('');
}
function selectProviderPreset() {
  renderProviderModelOptions();
}
function selectProviderModelPreset() {
  applySelectedProviderModel();
}
function applySelectedProviderModel() {
  const provider = selectedProviderPreset();
  if(!provider) return toast('没有可用厂商预设');
  const model = $('providerModelPreset')?.value || ((provider.models || [])[0] || {}).id || '';
  const modelItem = (provider.models || []).find(m=>m.id === model) || {};
  beginNewModelProfileFromFill();
  fillModelForm({
    name: `${provider.name} ${model}`.trim(),
    model_type: modelItem.model_type || inferModelType(model),
    provider: provider.provider || provider.name,
    base_url: provider.base_url || '',
    model,
    api_key: provider.api_key || '',
    temperature: provider.temperature || '0.65',
    frequency_penalty: provider.frequency_penalty || '0.35',
    max_tokens: provider.max_tokens || '260'
  }, false);
  showProfileFillFeedback(`${provider.name} ${model}`.trim());
}
async function loadLocalModels(options={}) {
  const infoEl = $('localModelInfo');
  const listEl = $('localModelList');
  if(!infoEl || !listEl) return;
  const manual = !!options.manual;
  infoEl.textContent = '正在刷新本机模型...';
  try {
    const data = await api('/api/local-models');
    window._localModels = data.models || [];
    const refreshedAt = new Date().toLocaleTimeString();
    infoEl.textContent = `目录：${data.models_path || ''} · ${data.models_path_exists ? '目录存在' : '目录不存在'} · ${data.ollama_running ? 'Ollama 已连接' : 'Ollama 未连接'} · ${window._localModels.length} 个模型 · ${refreshedAt}`;
    listEl.innerHTML = window._localModels.map((model,index)=>{
      const modelType = inferModelType(model.name);
      const kind = localModelKind(model.name);
      const selected = model.name === window._selectedLocalModelName;
      const runnable = model.source === 'ollama_api' || model.runnable === true;
      const stateText = runnable ? 'Ollama 可运行' : '仅发现模型文件';
      return `
      <div class="model-card ${selected ? 'selected' : ''}" data-model-name="${escapeHtml(model.name)}">
        <div class="model-card-head">
          <div>
            <strong>${escapeHtml(model.name)}</strong>
            <div class="note">${escapeHtml(model.parameter_size || model.family || model.source || 'local')}</div>
          </div>
          <span class="badge ${runnable && modelTypeCanActivate(modelType) ? 'active' : 'warn'}">${escapeHtml(kind)}</span>
        </div>
        <div class="note">来源：${escapeHtml(model.source || 'local')} · ${stateText}</div>
        <div class="row">
          <button class="ghost" onclick="fillLocalModelByIndex(${index})">${runnable ? '填入' : '仅填入'}${escapeHtml(modelTypeLabel(modelType))}档案</button>
        </div>
      </div>`}).join('') || '<p class="note">没有发现本机 Ollama 模型。</p>';
    if(window._selectedLocalModelName) {
      showLocalModelAction(`已填入：${window._selectedLocalModelName}。右侧档案参数已更新，确认后保存或启用。`);
    }
    if(manual) toast(`已刷新本机模型，发现 ${window._localModels.length} 个`);
  } catch(e) {
    infoEl.textContent = '读取本机模型失败：' + e.message;
    listEl.innerHTML = '';
    showLocalModelAction('');
    if(manual) toast('读取本机模型失败：' + e.message);
  }
}
function localModelKind(name) {
  const modelType = inferModelType(name);
  if(modelType === 'embedding') return '向量模型';
  if(modelType === 'vision') return '视觉模型';
  const lower = String(name || '').toLowerCase();
  if(lower.includes('r1') || lower.includes('reason')) return '推理模型';
  return '聊天模型';
}
function inferModelType(name) {
  const lower = String(name || '').toLowerCase();
  if(lower.includes('bge') || lower.includes('embed')) return 'embedding';
  if(lower.includes('vl') || lower.includes('vision')) return 'vision';
  return 'chat';
}
function fillLocalModelByIndex(index) {
  const model = (window._localModels || [])[index];
  if(!model) return;
  const modelType = inferModelType(model.name);
  const runnable = model.source === 'ollama_api' || model.runnable === true;
  window._selectedLocalModelName = model.name;
  beginNewModelProfileFromFill();
  fillModelForm({
    name: `本地 Ollama ${model.name}`,
    model_type: modelType,
    provider: 'Ollama',
    base_url: 'http://127.0.0.1:11434/v1',
    model: model.name,
    api_key: 'ollama',
    temperature: '0.60',
    frequency_penalty: '0.35',
    max_tokens: '260'
  }, false);
  markLocalModelSelected(model.name);
  showLocalModelAction(`已填入：${model.name}（${modelTypeLabel(modelType)}）。${runnable ? 'Ollama 当前可运行。' : '但 Ollama 当前没有注册这个模型，启用后可能仍会兜底。'}右侧档案参数已更新，确认后保存${modelTypeCanActivate(modelType) ? '或启用' : ''}。`);
  showProfileFillFeedback(`本地 Ollama ${model.name}`);
}
function fillModelForm(values, keepExistingName=true) {
  if(!keepExistingName || !$('profileName').value.trim()) $('profileName').value = values.name || '';
  $('profileModelType').value = values.model_type || inferModelType(values.model || '');
  $('profileProvider').value = values.provider || '';
  $('profileBaseUrl').value = values.base_url || '';
  $('profileModel').value = values.model || '';
  if(values.api_key) $('profileApiKey').value = values.api_key;
  $('profileTemperature').value = values.temperature || '0.65';
  $('profileFrequencyPenalty').value = values.frequency_penalty || '0.35';
  $('profileMaxTokens').value = values.max_tokens || '260';
}
function beginNewModelProfileFromFill() {
  selectedProfileId = "";
  $('profileId').value = "";
  $('profileFormTitle').textContent = '新建模型档案';
  for (const id of ['profileName','profileProvider','profileBaseUrl','profileModel','profileApiKey']) $(id).value = '';
  $('profileModelType').value = 'chat';
  $('profileTemperature').value = "0.65";
  $('profileFrequencyPenalty').value = "0.35";
  $('profileMaxTokens').value = "260";
  $('profileApiKey').placeholder = '输入 API Key；本地 Ollama 可填 ollama';
}
function markLocalModelSelected(name) {
  document.querySelectorAll('.model-card').forEach(card=>{
    card.classList.toggle('selected', card.dataset.modelName === name);
  });
}
function showLocalModelAction(text) {
  const el = $('localModelAction');
  if(!el) return;
  el.textContent = text || '';
  el.classList.toggle('show', !!text);
}
function showProfileFillFeedback(label) {
  const type = $('profileModelType')?.value || 'chat';
  const activateHint = modelTypeCanActivate(type)
    ? `检查参数后点击“保存档案”，需要立即生效再点“启用档案”；只会替换当前${modelTypeLabel(type)}。`
    : '当前项目还没有独立向量模型启用配置，可先保存档案备用。';
  const text = `已填入：${label}（${modelTypeLabel(type)}）。${activateHint}`;
  const el = $('modelFillFeedback');
  if(el) {
    el.textContent = text;
    el.classList.add('show');
  }
  toast(text);
  $('modelProfileEditor')?.scrollIntoView({behavior:'smooth', block:'start'});
  setTimeout(()=>$('profileName')?.focus({preventScroll:true}), 180);
}
function selectProfileByIndex(index) { const p = window._profiles[index]; if(p) selectProfile(p); }
function activateProfileByIndex(index) { const p = window._profiles[index]; if(p) activateProfile(p.id); }
function selectProfile(p) {
  selectedProfileId = p.id || "";
  $('profileFormTitle').textContent = '编辑模型档案';
  $('profileId').value = p.id || "";
  $('profileName').value = p.name || "";
  $('profileModelType').value = p.model_type || inferModelType(p.model || "");
  $('profileProvider').value = p.provider || "";
  $('profileBaseUrl').value = p.base_url || "";
  $('profileModel').value = p.model || "";
  $('profileApiKey').value = "";
  $('profileApiKey').placeholder = p.has_api_key ? '已保存，留空保持原值' : '未填写，请输入 API Key';
  $('profileTemperature').value = p.temperature || "0.65";
  $('profileFrequencyPenalty').value = p.frequency_penalty || "0.35";
  $('profileMaxTokens').value = p.max_tokens || "260";
  const feedback = $('modelFillFeedback');
  if(feedback) {
    feedback.textContent = `正在编辑：${p.name}。修改后点“保存档案”；需要生效再点“启用档案”。`;
    feedback.classList.add('show');
  }
  $('modelProfileEditor')?.scrollIntoView({behavior:'smooth', block:'start'});
  setTimeout(()=>$('profileName')?.focus({preventScroll:true}), 180);
}
function profilePayload() {
  return {
    id: $('profileId').value.trim(),
    name: $('profileName').value.trim(),
    model_type: $('profileModelType').value,
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
  try {
    const r = await api('/api/model-profiles/activate', {method:'POST', body:JSON.stringify({id})});
    await loadProfiles(); await loadStatus(); await loadConfig();
    toast(`已启用为${modelTypeLabel(r.profile.model_type)}：${r.profile.name}`);
  } catch(e) {
    toast(e.message || '启用模型档案失败');
  }
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
async function deleteProfileByIndex(index) {
  const p = window._profiles[index];
  if(!p) return toast('没有找到这个模型档案');
  if(!confirm(`确认删除模型档案“${p.name}”？不会删除 Ollama 模型文件，也不会修改当前 .env 配置。`)) return;
  try {
    await api('/api/model-profiles/delete', {method:'POST', body:JSON.stringify({id:p.id})});
    if(($('profileId').value.trim() || selectedProfileId) === p.id) newProfile();
    await loadProfiles();
    toast('模型档案已删除');
  } catch(e) {
    toast(e.message || '删除模型档案失败');
  }
}
function newProfile() {
  selectedProfileId = "";
  $('profileFormTitle').textContent = '新建模型档案';
  for (const id of ['profileId','profileName','profileProvider','profileBaseUrl','profileModel','profileApiKey']) $(id).value = '';
  $('profileModelType').value = 'chat';
  $('profileApiKey').placeholder = '输入 API Key；本地 Ollama 可填 ollama';
  $('profileTemperature').value = "0.65";
  $('profileFrequencyPenalty').value = "0.35";
  $('profileMaxTokens').value = "260";
  const feedback = $('modelFillFeedback');
  if(feedback) {
    feedback.textContent = '';
    feedback.classList.remove('show');
  }
}
function quickFillDeepSeek() {
  beginNewModelProfileFromFill();
  $('profileName').value = $('profileName').value || 'DeepSeek 官方';
  $('profileModelType').value = 'chat';
  $('profileProvider').value = 'DeepSeek';
  $('profileBaseUrl').value = 'https://api.deepseek.com/v1';
  $('profileModel').value = 'deepseek-v4-flash';
  $('profileTemperature').value = '0.65';
  $('profileFrequencyPenalty').value = '0.35';
  $('profileMaxTokens').value = '260';
  showProfileFillFeedback('DeepSeek 官方 deepseek-v4-flash');
}
function quickFillOllama() {
  beginNewModelProfileFromFill();
  $('profileName').value = $('profileName').value || '本地 Ollama Qwen3 4B';
  $('profileModelType').value = 'chat';
  $('profileProvider').value = 'Ollama';
  $('profileBaseUrl').value = 'http://127.0.0.1:11434/v1';
  $('profileModel').value = 'qwen3:4b-instruct';
  $('profileApiKey').value = 'ollama';
  $('profileTemperature').value = '0.60';
  $('profileFrequencyPenalty').value = '0.35';
  $('profileMaxTokens').value = '180';
  showProfileFillFeedback('本地 Ollama qwen3:4b-instruct');
}
function quickFillOpenAICompatible() {
  beginNewModelProfileFromFill();
  $('profileName').value = $('profileName').value || 'OpenAI 兼容模型';
  $('profileModelType').value = 'chat';
  $('profileProvider').value = 'OpenAI 兼容';
  $('profileBaseUrl').value = 'https://api.openai.com/v1';
  $('profileModel').value = 'gpt-4.1-mini';
  $('profileTemperature').value = '0.65';
  $('profileFrequencyPenalty').value = '0.35';
  $('profileMaxTokens').value = '260';
  showProfileFillFeedback('OpenAI 兼容 gpt-4.1-mini');
}
const proactiveWeightLabels = {
  morning:'早安', goodnight:'晚安', check_in:'关心近况', continue_topic:'继续上次话题',
  interest_topic:'兴趣话题', guided_topic:'引导式新话题', daily_share:'轻松分享', affection:'想念与亲近', encouragement:'鼓励'
};
function formatProactiveTime(value, timezone) {
  if(!value) return '尚未安排';
  try { return new Date(Number(value) * 1000).toLocaleString('zh-CN', {timeZone:timezone, hour12:false}); }
  catch (_) { return new Date(Number(value) * 1000).toLocaleString('zh-CN', {hour12:false}); }
}
async function loadProactive() {
  const [data, cfg] = await Promise.all([api('/api/proactive'), api('/api/config')]);
  window._proactive = data;
  const p = data.policy || {};
  const engineValue = cfg.PROACTIVE_V2_ENABLED?.raw || cfg.PROACTIVE_V2_ENABLED?.value || '';
  $('proactiveEngineEnabled').checked = String(engineValue).toLowerCase() === 'true';
  $('proactiveEnabled').checked = !!p.enabled;
  $('proactiveOwnerOnly').checked = !!p.owner_only;
  $('proactiveUseAi').checked = !!p.use_ai;
  $('proactiveGuidedTopics').checked = !!p.guided_topics;
  $('proactivePrivateMinAffection').value = p.private_min_affection ?? 70;
  $('proactivePrivateActiveDays').value = p.private_active_days ?? 14;
  $('proactivePrivateMinMessages').value = p.private_min_messages ?? 5;
  $('proactiveGroupEnabled').checked = !!p.group_enabled;
  $('proactiveGroupMinActivity').value = p.group_min_activity ?? 55;
  $('proactiveGroupActiveDays').value = p.group_active_days ?? 3;
  $('proactiveGroupMinMessages').value = p.group_min_messages ?? 12;
  $('proactiveGroupMinHours').value = p.group_min_hours ?? 3;
  $('proactiveGroupMaxHours').value = p.group_max_hours ?? 9;
  $('proactiveGroupDailyLimit').value = p.group_daily_limit ?? 2;
  $('proactiveTimezone').value = p.timezone || 'Asia/Shanghai';
  $('proactiveQuietStart').value = p.quiet_start || '00:30';
  $('proactiveQuietEnd').value = p.quiet_end || '07:00';
  $('proactiveCheckSeconds').value = p.check_seconds || 60;
  $('proactiveBackoff').value = p.ignored_backoff || 1.5;
  $('proactiveHistoryLimit').value = p.history_limit ?? 8;
  $('proactiveMaxChars').value = p.max_chars || 90;
  $('proactiveFeatureState').innerHTML = data.feature_enabled
    ? '<span class="ok">新版调度器已接管私聊、早安及已启用的群聊主动消息；旧版循环处于回退待命状态。</span>'
    : '<span class="bad">新版调度器未启用，当前仍由旧版私聊/早安规则运行。</span>';
  $('proactiveTierRows').innerHTML = (p.tiers || []).map((tier,index)=>`<tr data-tier-index="${index}">
    <td><strong>${escapeHtml(tier.name)}</strong><div class="memory-meta mono">${escapeHtml(tier.id)}</div></td>
    <td><input class="tier-enabled" type="checkbox" ${tier.enabled?'checked':''}></td>
    <td><div class="row" style="margin:0"><input class="tier-min compact-input" type="number" min="0" max="100" step="1" value="${tier.min_affection}"><span>至</span><input class="tier-max compact-input" type="number" min="0" max="101" step="1" value="${tier.max_affection}"></div></td>
    <td><div class="row" style="margin:0"><input class="tier-min-hours compact-input" type="number" min="0.25" max="168" step="0.25" value="${tier.min_hours}"><span>至</span><input class="tier-max-hours compact-input" type="number" min="0.25" max="336" step="0.25" value="${tier.max_hours}"></div></td>
    <td><input class="tier-limit compact-input" type="number" min="0" max="12" step="1" value="${tier.daily_limit}"></td>
  </tr>`).join('');
  $('proactiveWeights').innerHTML = Object.entries(p.content_weights || {}).map(([key,value])=>
    `<label>${escapeHtml(proactiveWeightLabels[key] || key)}<input data-weight="${escapeHtml(key)}" type="number" min="0" max="100" step="1" value="${value}"></label>`
  ).join('');
  $('proactiveGroupWeights').innerHTML = Object.entries(p.group_content_weights || {}).map(([key,value])=>
    `<label>${escapeHtml(proactiveWeightLabels[key] || key)}<input data-group-weight="${escapeHtml(key)}" type="number" min="0" max="100" step="1" value="${value}"></label>`
  ).join('');
  renderProactivePreviewTypes();
  const schedule = data.schedule || {};
  const items = schedule.items || [];
  if(items.length && !$('proactivePreviewUser').value) {
    const firstEligible = items.find(item=>item.eligible) || items[0];
    $('proactivePreviewScope').value = firstEligible.target_type || 'private';
    $('proactivePreviewUser').value = firstEligible.target_id || '';
    renderProactivePreviewTypes();
  }
}
function renderProactivePreviewTypes() {
  const p = (window._proactive || {}).policy || {};
  const scope = $('proactivePreviewScope')?.value || 'private';
  const weights = scope==='group' ? (p.group_content_weights || {}) : (p.content_weights || {});
  const previous = $('proactivePreviewType')?.value;
  $('proactivePreviewType').innerHTML = Object.keys(weights).map(key=>
    `<option value="${escapeHtml(key)}">${escapeHtml(proactiveWeightLabels[key] || key)}</option>`
  ).join('');
  if(previous && Object.hasOwn(weights, previous)) $('proactivePreviewType').value = previous;
  const items = ((window._proactive || {}).schedule || {}).items || [];
  const matching = items.find(item=>item.target_type===scope && item.eligible) || items.find(item=>item.target_type===scope);
  if(matching) $('proactivePreviewUser').value = matching.target_id || '';
}
function collectProactivePolicy() {
  const base = JSON.parse(JSON.stringify((window._proactive || {}).policy || {}));
  base.enabled = $('proactiveEnabled').checked;
  base.owner_only = $('proactiveOwnerOnly').checked;
  base.use_ai = $('proactiveUseAi').checked;
  base.guided_topics = $('proactiveGuidedTopics').checked;
  base.private_min_affection = Number($('proactivePrivateMinAffection').value);
  base.private_active_days = Number($('proactivePrivateActiveDays').value);
  base.private_min_messages = Number($('proactivePrivateMinMessages').value);
  base.group_enabled = $('proactiveGroupEnabled').checked;
  base.group_min_activity = Number($('proactiveGroupMinActivity').value);
  base.group_active_days = Number($('proactiveGroupActiveDays').value);
  base.group_min_messages = Number($('proactiveGroupMinMessages').value);
  base.group_min_hours = Number($('proactiveGroupMinHours').value);
  base.group_max_hours = Number($('proactiveGroupMaxHours').value);
  base.group_daily_limit = Number($('proactiveGroupDailyLimit').value);
  base.timezone = $('proactiveTimezone').value.trim();
  base.quiet_start = $('proactiveQuietStart').value;
  base.quiet_end = $('proactiveQuietEnd').value;
  base.check_seconds = Number($('proactiveCheckSeconds').value);
  base.ignored_backoff = Number($('proactiveBackoff').value);
  base.history_limit = Number($('proactiveHistoryLimit').value);
  base.max_chars = Number($('proactiveMaxChars').value);
  base.tiers = Array.from(document.querySelectorAll('#proactiveTierRows tr')).map((row,index)=>({
    ...(base.tiers[index] || {}),
    enabled:row.querySelector('.tier-enabled').checked,
    min_affection:Number(row.querySelector('.tier-min').value),
    max_affection:Number(row.querySelector('.tier-max').value),
    min_hours:Number(row.querySelector('.tier-min-hours').value),
    max_hours:Number(row.querySelector('.tier-max-hours').value),
    daily_limit:Number(row.querySelector('.tier-limit').value)
  }));
  base.content_weights = {};
  document.querySelectorAll('[data-weight]').forEach(input=>base.content_weights[input.dataset.weight]=Number(input.value));
  base.group_content_weights = {};
  document.querySelectorAll('[data-group-weight]').forEach(input=>base.group_content_weights[input.dataset.groupWeight]=Number(input.value));
  return base;
}
async function saveProactive() {
  await api('/api/config', {method:'POST', body:JSON.stringify({PROACTIVE_V2_ENABLED:$('proactiveEngineEnabled').checked})});
  await api('/api/proactive/save', {method:'POST', body:JSON.stringify(collectProactivePolicy())});
  await loadProactive();
  await loadMemory();
  toast('主动互动配置已保存，记忆页计划已同步更新');
}
async function previewProactive() {
  $('proactivePreviewOut').textContent = '正在生成预览...';
  try {
    const body = {event_type:$('proactivePreviewType').value, scope:$('proactivePreviewScope').value, target_id:$('proactivePreviewUser').value.trim()};
    const result = await api('/api/proactive/preview', {method:'POST', body:JSON.stringify(body)});
    $('proactivePreviewOut').textContent = `${result.reply || result.text || ''}\n\n来源：${result.source || '未知'}${result.error ? `\n模型错误：${result.error}` : ''}`;
  } catch (error) {
    $('proactivePreviewOut').textContent = `预览失败：${error.message}`;
  }
}
async function loadConfig() {
  const cfg = await api('/api/config');
  $('configForm').innerHTML = fields.map(([key,label,type])=>{
    const item = cfg[key] || {}; const value = item.raw || item.value || '';
    if(type==='select') return `<label>${label}<select id="${key}"><option>private</option><option>mention</option><option>smart</option><option>all</option></select></label>`;
    if(type==='checkbox') return `<label>${label}<input id="${key}" type="checkbox" ${String(value).toLowerCase()==='true'?'checked':''}></label>`;
    if(type==='password') return `<label>${label}<input id="${key}" type="password" placeholder="${item.has_secret ? '已保存，留空保持原值' : '未填写'}"></label>`;
    if(type==='voice-probability') {
      const probability = Number(window._advancedVoiceBehavior?.reply_voice_probability ?? 35);
      return `<label>${label}<input id="replyVoiceProbabilityNumber" type="number" min="0" max="100" step="1" value="${probability}"></label>`;
    }
    return `<label>${label}<input id="${key}" type="${type}" step="0.01" value="${escapeHtml(value)}"></label>`;
  }).join('');
  for (const [key,,type] of fields) if(type==='select' && cfg[key]) $(key).value = cfg[key].raw || cfg[key].value;
}
async function loadReplyVoiceProbability() {
  try {
    const data = await api('/api/voice/behavior');
    window._advancedVoiceBehavior = data.behavior || {};
    const value = Number(window._advancedVoiceBehavior.reply_voice_probability ?? 35);
    const input = $('replyVoiceProbabilityNumber');
    if(input) input.value = value;
  } catch(error) {
    toast(`语音概率读取失败：${error.message}`);
  }
}
async function saveReplyVoiceProbability() {
  if(!window._advancedVoiceBehavior) {
    const data = await api('/api/voice/behavior');
    window._advancedVoiceBehavior = data.behavior || {};
  }
  const probability = Math.min(100, Math.max(0, Math.round(Number($('replyVoiceProbabilityNumber').value) || 0)));
  const behavior = {...window._advancedVoiceBehavior, reply_voice_probability:probability};
  await api('/api/voice/save', {method:'POST', body:JSON.stringify({behavior})});
  window._advancedVoiceBehavior = behavior;
  if(window._voiceData) window._voiceData.behavior = behavior;
}
async function saveConfig() {
  const body = {};
  for (const [key,,type] of fields) {
    const el = $(key); if(!el) continue;
    if(type==='voice-probability') continue;
    body[key] = type==='checkbox' ? el.checked : el.value;
  }
  await api('/api/config', {method:'POST', body:JSON.stringify(body)});
  await saveReplyVoiceProbability();
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
  const [m, proactive] = await Promise.all([api('/api/memory'), api('/api/proactive')]);
  window._proactive = proactive;
  const plans = new Map(((proactive.schedule || {}).items || []).map(item=>[String(item.conversation_id || ''), item]));
  window._memoryItems = (m.items || []).map(item=>{
    const planId = item.kind === 'person' ? `private:${String(item.id).replace(/^person:/, '')}` : item.id;
    return {...item, proactive_plan:plans.get(planId) || null};
  });
  const planItems = (proactive.schedule || {}).items || [];
  const eligibleCount = planItems.filter(item=>item.eligible).length;
  $('memoryInfo').textContent = `记忆文件：${m.path}，显示对象：${m.conversations}，底层记录：${m.raw_conversations || m.conversations}；主动计划入选 ${eligibleCount}/${planItems.length}`;
  renderMemoryRows();
}
function formatScore(value) {
  if(value === null || value === undefined || value === '') return '暂无';
  const score = Number(value);
  return Number.isFinite(score) ? score.toFixed(1) : '暂无';
}
function renderMemoryPlan(item) {
  if((window._proactive || {}).feature_enabled === false) {
    return '<div class="memory-plan"><span class="badge red">新版主动调度已关闭</span></div>';
  }
  const plan = item.proactive_plan;
  if(!plan) {
    return item.proactive_state
      ? `<div class="memory-plan"><span class="badge ${item.proactive_blocked?'red':'active'}">${escapeHtml(item.proactive_state)}</span></div>`
      : '<div class="memory-meta">暂无主动互动计划</div>';
  }
  const timezone = ((window._proactive || {}).schedule || {}).timezone || ((window._proactive || {}).policy || {}).timezone;
  const nextType = proactiveWeightLabels[plan.next_event_type] || plan.next_event_type || '';
  const nextTime = formatProactiveTime(plan.next_at, timezone);
  const detail = plan.eligible
    ? `<div class="memory-meta">下次内容：${escapeHtml(nextType || '由模型决定')}</div>
       <div class="plan-time-row">
         <input type="password" readonly aria-label="下次主动消息发送时间" value="${escapeHtml(nextTime)}">
         <button type="button" class="ghost" title="显示下次主动消息发送时间" aria-pressed="false" onclick="toggleProactiveTime(this)">查看</button>
       </div>`
    : `<div class="memory-meta">${escapeHtml(plan.eligibility_reason || '未满足当前门槛')}</div>`;
  return `<div class="memory-plan">
    <span class="badge ${plan.eligible?'active':'warn'}">主动互动 ${plan.eligible?'已入选':'未入选'}</span>
    ${detail}
    ${plan.ignored_streak ? `<div class="memory-meta">连续未回应 ${escapeHtml(plan.ignored_streak)} 次</div>` : ''}
  </div>`;
}
function toggleProactiveTime(button) {
  const input = button.parentElement?.querySelector('input');
  if(!input) return;
  const reveal = input.type === 'password';
  input.type = reveal ? 'text' : 'password';
  button.textContent = reveal ? '隐藏' : '查看';
  button.title = reveal ? '隐藏下次主动消息发送时间' : '显示下次主动消息发送时间';
  button.setAttribute('aria-pressed', String(reveal));
}
function memoryMatchesFilter(item) {
  const filter = $('memoryTypeFilter')?.value || 'all';
  if(filter === 'person' && item.kind !== 'person') return false;
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
        <div class="memory-score">${x.kind==='group' ? `活跃度 ${formatScore(x.activity)} · ${escapeHtml(x.activity_label || '普通')}` : `好感 ${formatScore(x.affection)} · ${escapeHtml(x.affection_label || '普通')}`}</div>
        ${renderMemoryPlan(x)}
        <div class="memory-meta" style="margin-top:6px">消息 ${x.messages||0} · 记忆 ${(x.memory_counts||{}).total||0}${x.related_count ? ' · 来源 ' + x.related_count : ''}</div>
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
  $('memoryModalMeta').textContent = `${d.type || ''} · ${id}${d.storage_id ? ' · 保存到 ' + d.storage_id : ''}`;
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
function formatMemoryTime(value) {
  const n = Number(value || 0);
  if(!Number.isFinite(n) || n <= 0) return '暂无';
  return new Date(n * 1000).toLocaleString();
}
function memoryCountText(counts) {
  counts = counts || {};
  return `长期 ${counts.l1 || 0} / 事件 ${counts.l2 || 0} / 待确认 ${counts.candidates || 0}`;
}
function renderFactGrid(items) {
  return `<div class="fact-grid">${items.map(item=>`
    <div class="fact"><span>${escapeHtml(item.label)}</span><strong>${escapeHtml(item.value ?? '暂无')}</strong></div>
  `).join('')}</div>`;
}
function renderRelationshipControls() {
  const isPerson = selectedMemory.kind === 'person' || selectedMemory.kind === 'private';
  const override = ['allow','deny'].includes(selectedMemoryContent.proactive_override)
    ? selectedMemoryContent.proactive_override
    : 'auto';
  return `<div class="relationship-controls">
    <h3>关系与主动互动</h3>
    <div class="grid">
      ${isPerson ? `<label>好感度（0–100）<input id="memoryAffectionScore" type="number" min="0" max="100" step="0.1" value="${escapeHtml(selectedMemoryContent.affection_score ?? 0)}"></label>` : ''}
      ${!isPerson ? `<label>群聊活跃度（0–100）<input id="memoryGroupActivityScore" type="number" min="0" max="100" step="0.1" value="${escapeHtml(selectedMemoryContent.group_activity_score ?? 0)}"></label>` : ''}
      <label>主动互动<select id="memoryProactiveOverride">
        <option value="auto" ${override==='auto'?'selected':''}>跟随全局策略</option>
        <option value="allow" ${override==='allow'?'selected':''}>强制允许</option>
        <option value="deny" ${override==='deny'?'selected':''}>强制禁止</option>
      </select></label>
    </div>
    <div class="row"><button type="button" class="ghost" onclick="saveRelationshipControls()">保存关系设置</button></div>
    <p class="note">强制允许会跳过该对象的好感、活跃期和消息量门槛，但仍遵守总开关、免打扰时段和当前频率设置；强制禁止的优先级最高。</p>
  </div>`;
}
async function saveRelationshipControls() {
  if(!currentMemoryId || !selectedMemoryContent) return toast('先打开一条记忆');
  const override = $('memoryProactiveOverride')?.value || 'auto';
  const scoreInput = $('memoryAffectionScore');
  const activityInput = $('memoryGroupActivityScore');
  const score = scoreInput ? Number(scoreInput.value) : null;
  const activity = activityInput ? Number(activityInput.value) : null;
  if(scoreInput && (!Number.isFinite(score) || score < 0 || score > 100)) {
    return toast('好感度必须在 0 到 100 之间');
  }
  if(activityInput && (!Number.isFinite(activity) || activity < 0 || activity > 100)) {
    return toast('群聊活跃度必须在 0 到 100 之间');
  }
  try {
    const result = await api('/api/memory/relationship', {method:'POST', body:JSON.stringify({
      id:currentMemoryId,
      affection_score:score,
      group_activity_score:activity,
      proactive_override:override
    })});
    const relationship = result.relationship || {};
    if(scoreInput) {
      selectedMemoryContent.affection_score = relationship.affection_score;
      selectedMemoryContent.affection_initialized = true;
    }
    if(activityInput) {
      selectedMemoryContent.group_activity_score = relationship.group_activity_score;
    }
    selectedMemoryContent.proactive_override = relationship.proactive_override || 'auto';
    await loadMemory();
    const summary = (window._memoryItems || []).find(item=>item.id===currentMemoryId);
    if(summary) selectedMemory.affection_label = summary.affection_label;
    renderMemoryModal();
    toast('关系设置已保存，主动计划已重新评估');
  } catch(error) {
    toast('关系设置保存失败：' + error.message);
  }
}
function renderPersonOverview(counts) {
  const target = selectedMemoryContent.target || {};
  const userId = String(target.user_id || currentMemoryId.replace(/^person:/, '') || '').replace(/^private:/, '');
  const sources = selectedMemory.related_conversations || [];
  return `
    <h3>基本数据</h3>
    ${renderFactGrid([
      {label:'QQ', value:userId || '未知'},
      {label:'底层保存位置', value:selectedMemory.storage_id || currentMemoryId},
      {label:'来源记录', value:String(sources.length || 1)},
      {label:'消息数量', value:String(selectedMemoryContent.message_count || 0)},
      {label:'结构化记忆', value:memoryCountText(counts)},
      {label:'最近互动', value:formatMemoryTime(selectedMemoryContent.last_user_at)},
      {label:'亲密状态', value:`${selectedMemory.affection_label || '普通'}（好感 ${formatScore(selectedMemoryContent.affection_score)}）`},
      {label:'历史条数', value:String(selectedMemory.history_count || 0)}
    ])}
    ${renderRelationshipControls()}
    <div class="natural-box">${escapeHtml(selectedMemory.natural || '暂无可读摘要。')}</div>
    <h3>所在群聊</h3>
    ${renderGroupInfoList(selectedMemory.group_infos || [])}
    <p class="note">人物档案按 QQ 聚合；保存会写回 ${escapeHtml(selectedMemory.storage_id || currentMemoryId)}，并清理同一人的过期群成员旧值。</p>`;
}
function renderGroupInfoList(groups) {
  if(!groups.length) return '<div class="empty">暂无群聊来源。</div>';
  return `<div class="group-info-list">${groups.map(group=>`
    <div class="group-info">
      <div class="group-info-head">
        <div>
          <div class="group-info-title">群 ${escapeHtml(group.group_id || '未知')}</div>
          <div class="memory-meta">${escapeHtml(group.nickname ? '群内昵称：' + group.nickname : group.display_name || group.id)}</div>
        </div>
        <span class="badge">${escapeHtml(group.last_user_at_text || '暂无时间')}</span>
      </div>
      ${renderFactGrid([
        {label:'底层记录', value:group.id || ''},
        {label:'消息数量', value:String(group.messages || 0)},
        {label:'结构化记忆', value:memoryCountText(group.memory_counts || {})},
        {label:'最近互动', value:group.last_user_at_text || formatMemoryTime(group.last_user_at)}
      ])}
      <div class="natural-box">${escapeHtml(group.summary || '暂无可读摘要。')}</div>
    </div>
  `).join('')}</div>`;
}
function renderMemoryModal() {
  if(!selectedMemory || !selectedMemoryContent) return;
  const counts = selectedMemory.memory_counts || {};
  $('memoryOverview').innerHTML = selectedMemory.kind === 'person' ? renderPersonOverview(counts) : `
    <div class="natural-box">${escapeHtml(selectedMemory.natural || '暂无可读摘要。')}</div>
    ${selectedMemory.related_conversations ? `<p class="note">统一人物档案会聚合同一 QQ 的私聊和群成员公开来源；保存会写回 ${escapeHtml(selectedMemory.storage_id || currentMemoryId)}，并清理同一人的过期群成员旧值。</p>` : ''}
    <div class="stat-grid">
      <div class="stat"><strong>${selectedMemoryContent.message_count || 0}</strong><span class="note">消息数量</span></div>
      <div class="stat"><strong>${counts.total || 0}</strong><span class="note">结构化记忆</span></div>
      <div class="stat"><strong>${selectedMemory.history_count || 0}</strong><span class="note">历史条数</span></div>
      <div class="stat"><strong>${selectedMemory.kind==='group' ? formatScore(selectedMemoryContent.group_activity_score) : formatScore(selectedMemoryContent.affection_score)}</strong><span class="note">${selectedMemory.kind==='group'?'群活跃度':'好感度'}</span></div>
    </div>
    ${renderRelationshipControls()}
    <p class="note">编辑下面的档案、事件、习惯或最近聊天后，点击底部“保存修改”。保存前会自动备份。</p>`;
  $('memoryProfile').innerHTML = renderEntryEditor('l1', ['profile_fact','interest','preference','habit'], '用户档案、兴趣与习惯');
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
  $('testOut').textContent = r.used_ai
    ? r.reply
    : `当前聊天模型没有连上，正在走兜底。\n错误：${r.error || '未知错误'}\n\n兜底回复：${r.reply}`;
}
async function loadVoiceTestState() {
  const out = $('testVoiceState');
  try {
    const data = await api('/api/voice');
    window._voiceData = data;
    populateVoiceCandidateSelects(data);
    const service = data.service || {};
    const asr = service.asr || {};
    const profileId = $('testTtsProfileA')?.value || 'atri';
    const profile = (data.profiles || []).find(item=>item.id===profileId) || {};
    const asrState = asr.loaded ? '模型已加载，中英日自动识别可用' : (asr.loading ? '模型预热中' : (asr.load_error ? `加载失败：${asr.load_error}` : (asr.dependency_available ? '等待模型加载' : '依赖不可用')));
    out.textContent = `服务：${service.ok?'已连接':'未连接'} · 识别：${asrState} · 音色：${profile.ready?'参考音频已就绪':'未就绪'}`;
  } catch(error) {
    out.textContent = '状态读取失败：' + error.message;
  }
}
function populateVoiceCandidateSelects(data) {
  const profiles = data.profiles || [];
  const candidates = data.candidates || [];
  const preferred = candidates.filter(item=>item.ready).map(item=>item.profile_id);
  const available = preferred.length ? profiles.filter(item=>preferred.includes(item.id)) : profiles;
  const options = available.map(item=>`<option value="${escapeHtml(item.id)}">${escapeHtml(item.display_name || item.id)}${item.model_version ? ` · ${escapeHtml(item.model_version)}` : ''}${item.ready ? '' : ' · 未就绪'}</option>`).join('');
  for(const id of ['testTtsProfileA','testTtsProfileB']) {
    const select = $(id);
    if(!select) continue;
    const previous = select.value;
    select.innerHTML = options;
    if(available.some(item=>item.id===previous)) select.value = previous;
  }
  const second = $('testTtsProfileB');
  if(second && available.length > 1 && !second.dataset.initialized) {
    second.selectedIndex = 1;
    second.dataset.initialized = 'true';
  }
}
function useVoiceLanguageSample() {
  const samples = {
    zh:'主人，今天也请让我陪在你身边。',
    en:'Master, please let me stay by your side today.',
    ja:'マスター、今日もあなたのそばにいさせてください。'
  };
  $('testTtsText').value = samples[$('testTtsLanguage').value] || samples.zh;
}
function encodeWaveFile(audioBuffer) {
  const channels = audioBuffer.numberOfChannels;
  const frames = audioBuffer.length;
  const mono = new Float32Array(frames);
  for(let channel=0; channel<channels; channel++) {
    const source = audioBuffer.getChannelData(channel);
    for(let i=0; i<frames; i++) mono[i] += source[i] / channels;
  }
  const buffer = new ArrayBuffer(44 + frames * 2);
  const view = new DataView(buffer);
  const write = (offset, value) => { for(let i=0; i<value.length; i++) view.setUint8(offset+i, value.charCodeAt(i)); };
  write(0, 'RIFF'); view.setUint32(4, 36 + frames * 2, true); write(8, 'WAVE');
  write(12, 'fmt '); view.setUint32(16, 16, true); view.setUint16(20, 1, true);
  view.setUint16(22, 1, true); view.setUint32(24, audioBuffer.sampleRate, true);
  view.setUint32(28, audioBuffer.sampleRate * 2, true); view.setUint16(32, 2, true);
  view.setUint16(34, 16, true); write(36, 'data'); view.setUint32(40, frames * 2, true);
  for(let i=0; i<frames; i++) {
    const sample = Math.max(-1, Math.min(1, mono[i]));
    view.setInt16(44 + i * 2, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true);
  }
  return new Blob([buffer], {type:'audio/wav'});
}
async function recordedBlobToWave(blob) {
  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  if(!AudioContextClass) throw new Error('当前浏览器不支持音频解码');
  const context = new AudioContextClass();
  try {
    const decoded = await context.decodeAudioData(await blob.arrayBuffer());
    return encodeWaveFile(decoded);
  } finally {
    await context.close();
  }
}
async function startAsrRecording() {
  const out = $('testAsrOut');
  if(!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
    out.textContent = '当前浏览器不支持麦克风录音。';
    return;
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({audio:true});
    const mimeType = ['audio/webm;codecs=opus','audio/webm','audio/ogg;codecs=opus','audio/ogg'].find(type=>MediaRecorder.isTypeSupported(type)) || '';
    const recorder = new MediaRecorder(stream, mimeType ? {mimeType} : undefined);
    window._asrRecorder = recorder;
    window._asrChunks = [];
    window._recordedAsrFile = null;
    recorder.ondataavailable = event => { if(event.data?.size) window._asrChunks.push(event.data); };
    recorder.onstop = async () => {
      clearTimeout(window._asrAutoStop);
      stream.getTracks().forEach(track=>track.stop());
      $('testAsrRecordButton').disabled = false;
      $('testAsrStopButton').disabled = true;
      try {
        out.textContent = '正在处理录音...';
        const captured = new Blob(window._asrChunks, {type:recorder.mimeType || 'audio/webm'});
        const wav = await recordedBlobToWave(captured);
        const file = new File([wav], `microphone-${Date.now()}.wav`, {type:'audio/wav'});
        window._recordedAsrFile = file;
        await testVoiceRecognition(file);
      } catch(error) {
        out.textContent = '录音处理失败：' + error.message;
      }
    };
    recorder.start(250);
    $('testAsrRecordButton').disabled = true;
    $('testAsrStopButton').disabled = false;
    out.textContent = '正在听你说话 · 0 秒';
    const started = Date.now();
    window._asrRecordTicker = setInterval(()=>{ out.textContent = `正在听你说话 · ${Math.floor((Date.now()-started)/1000)} 秒`; }, 1000);
    window._asrAutoStop = setTimeout(stopAsrRecording, 60000);
  } catch(error) {
    out.textContent = '无法使用麦克风：' + error.message;
  }
}
function stopAsrRecording() {
  clearInterval(window._asrRecordTicker);
  const recorder = window._asrRecorder;
  if(recorder && recorder.state==='recording') recorder.stop();
}
async function testVoiceRecognition(fileOverride=null) {
  const file = fileOverride || window._recordedAsrFile || $('testAsrFile').files[0];
  if(!file) return toast('先选择要识别的音频');
  const out = $('testAsrOut');
  const started = Date.now();
  out.textContent = '正在识别 · 0 秒';
  const ticker = setInterval(()=>{ out.textContent = `正在识别 · ${Math.floor((Date.now()-started)/1000)} 秒${window._voiceData?.service?.asr?.loaded ? '' : ' · 首次加载模型'}`; }, 1000);
  const form = new FormData();
  form.append('file', file);
  form.append('language', $('testAsrLanguage').value || 'auto');
  try {
    const result = await api('/api/voice/test-asr', {method:'POST', body:form});
    const confidence = result.confidence == null ? '未提供' : Number(result.confidence).toFixed(3);
    out.textContent = `识别文本：${result.text}\n语言：${result.language || '未知'}\n情绪：${result.emotion || 'neutral'}\n置信度：${confidence}\n耗时：${result.elapsed_ms} ms`;
  } catch(error) {
    out.textContent = '识别失败：' + error.message;
  } finally {
    clearInterval(ticker);
    loadVoiceTestState();
  }
}
async function synthesizeVoiceCandidate(profileId, audioId, outputId) {
  const out = $(outputId);
  const started = Date.now();
  out.textContent = '正在切换模型并合成 · 0 秒';
  const ticker = setInterval(()=>{ out.textContent = `正在切换模型并合成 · ${Math.floor((Date.now()-started)/1000)} 秒`; }, 1000);
  try {
    const result = await api('/api/voice/preview', {method:'POST', body:JSON.stringify({
      text:$('testTtsText').value,
      profile:profileId,
      language:$('testTtsLanguage').value,
      emotion:$('testTtsEmotion').value,
      intensity:Number($('testTtsIntensity').value)
    })});
    const audio = $(audioId);
    audio.src = result.audio_url;
    audio.load();
    out.textContent = `${result.elapsed_ms} ms${result.duration_seconds == null ? '' : ` · 音频 ${result.duration_seconds} 秒`}`;
    return result;
  } finally {
    clearInterval(ticker);
  }
}
async function testVoiceComparison() {
  const out = $('testTtsOut');
  const button = $('testTtsCompareButton');
  const profileA = $('testTtsProfileA').value;
  const profileB = $('testTtsProfileB').value;
  if(!profileA || !profileB) return toast('需要两套已就绪的候选语音档案');
  button.disabled = true;
  out.textContent = '正在生成候选 A...';
  try {
    await synthesizeVoiceCandidate(profileA, 'testTtsAudioA', 'testTtsOutA');
    out.textContent = '正在切换模型并生成候选 B...';
    await synthesizeVoiceCandidate(profileB, 'testTtsAudioB', 'testTtsOutB');
    out.textContent = 'A/B 试听已完成，请分别播放比较。';
  } catch(error) {
    out.textContent = '合成失败：' + error.message;
  } finally {
    button.disabled = false;
  }
}
async function testVoiceSynthesis() { return testVoiceComparison(); }
async function restartServices() {
  const r = await api('/api/restart', {method:'POST', body:'{}'});
  toast(r.message || r.error || '已执行');
}
loadStatus(); loadProfiles(); loadConfig(); loadReplyVoiceProbability(); loadProactive();
</script>
</body>
</html>"""
