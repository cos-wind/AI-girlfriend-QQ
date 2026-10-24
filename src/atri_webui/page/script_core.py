from __future__ import annotations

PART = r"""const fields = [
  ["REPLY_MODE","回复模式","select"],
  ["MESSAGE_SPLIT_MAX_CHARS","单条字数","number"],
  ["MESSAGE_SPLIT_MAX_PARTS","最多分条","number"],
  ["MESSAGE_SEND_DELAY_MIN","最短发送间隔","number"],
  ["MESSAGE_SEND_DELAY_MAX","最长发送间隔","number"],
  ["TYPING_CHARS_PER_SECOND","打字速度（字/秒）","number"],
  ["TYPING_MAX_DELAY_SECONDS","单条最长等待（秒）","number"],
  ["REPLY_FIRST_DELAY_MIN","首条最短停顿（秒）","number"],
  ["REPLY_FIRST_DELAY_MAX","首条最长停顿（秒）","number"],
  ["STICKER_CHANCE","表情概率","number"],
  ["STICKER_COOLDOWN_SECONDS","表情冷却秒数","number"],
  ["REPLY_VOICE_PROBABILITY","语音概率（%）","voice-probability"],
  ["WEB_SEARCH_ENABLED","启用联网搜索","checkbox"],
  ["TAVILY_API_KEY","Tavily API Key（留空保留）","password"],
  ["SERPAPI_API_KEY","SerpAPI API Key（留空保留）","password"],
  ["ATRI_SEARXNG_INSTANCES","SearXNG 地址（英文逗号分隔）","text"],
  ["WEB_SEARCH_TIMEOUT_SECONDS","搜索单次请求超时（秒）","number"],
  ["WEB_SEARCH_MAX_RESULTS","搜索结果条数（1–8）","number"],
  ["TOOLBOX_OCR_ENABLED","启用图片 OCR 文字识别","checkbox"],
  ["TOOLBOX_VIDEO_FRAME_ANALYSIS_ENABLED","启用视频抽帧分析","checkbox"],
  ["TOOLBOX_VIDEO_MAX_FRAMES","视频抽样帧数（1–8）","number"],
  ["TOOLBOX_VIDEO_DEADLINE_SECONDS","视频分析时间预算（20–60秒）","number"]
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
// 「亲密度分档」是回复策略与主动互动共用的一张表，只渲染一次，避免两个 load
// 互相覆盖用户正在编辑的输入框。
let replyStrategyTiersLoaded = false;
window._qzoneFeeds = [];
window._modalityAccess = null;
window._userDirectory = {items:[], groups:[], selectedIds:[], sourceStatus:{}};
function $(id) { return document.getElementById(id); }
function toast(text) {
  const el = $('toast'); el.textContent = text; el.classList.add('show');
  setTimeout(()=>el.classList.remove('show'), 2600);
}
async function withButtonBusy(button, task, pending='处理中…') {
  if(!button) return task();
  const original=button.textContent; button.disabled=true; button.dataset.originalText=original; button.textContent=pending;
  try { return await task(); }
  finally { button.disabled=false; button.textContent=button.dataset.originalText || original; }
}
async function api(path, opts={}) {
  const headers = opts.body instanceof FormData ? {} : {'Content-Type':'application/json'};
  const res = await fetch(path, {headers, ...opts});
  let data;
  try {
    data = await res.json();
  } catch (error) {
    // 后端崩了或返回非 JSON 时把状态码带出来，否则只看到 "Unexpected token"。
    throw new Error(`${path} 返回了非 JSON 响应（HTTP ${res.status}）`);
  }
  if(!res.ok || data.ok === false) {
    // 带上路径与状态码：以前只报 error 字段，分不清是 400 参数问题还是 503 服务不可用。
    throw new Error(`${path}（HTTP ${res.status}）：${data.error || res.statusText}`);
  }
  return data;
}
function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, s => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[s]));
}
function showTab(event, id) {
  document.querySelectorAll('.tab').forEach(b=>b.classList.remove('active'));
  document.querySelectorAll('.panel').forEach(p=>p.classList.remove('active'));
  (event.currentTarget || event.target).classList.add('active'); $(id).classList.add('active');
  if(id==='users') { loadUserDirectory(true); loadMemory(); loadModalityAccess(); }
  if(id==='memory') loadMemory();
  if(id==='advanced') { loadConfig(); loadReplyVoiceProbability(); loadProactive(); loadReplyStrategy(); loadQQSongs(); loadStatus(); }
  if(id==='model') loadProfiles();
  if(id==='test') { loadVoiceTestState(); loadDeveloper(false); loadProactive(); }
  if(id==='evaluation') loadEvaluation(false);
}
const evaluationLabels = {
  relevancy:'相关性', accuracy:'准确性', completeness:'完整性', coherence:'连贯性',
  faithfulness:'忠实度', hallucination:'无幻觉程度'
};
const evaluationModelLabels = {chat:'聊天模型', vision:'视觉模型', voice:'语音模型'};
function scoreClass(value) {
  const score = Number(value);
  return score >= 4 ? 'score-high' : (score >= 3 ? 'score-mid' : 'score-low');
}
function showInsightPanel(name) {
  // 群聊总结已统一迁移到“用户中心”，评测页只保留评测看板。
  $('evaluationDashboardPanel')?.classList.add('active');
  loadEvaluation(false);
}
"""
