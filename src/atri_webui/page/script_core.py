from __future__ import annotations

PART = r"""const fields = [
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
window._minecraftData = null;
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
  (event.currentTarget || event.target).classList.add('active'); $(id).classList.add('active');
  if(id==='users') { loadUserDirectory(true); loadMemory(); loadModalityAccess(); }
  if(id==='memory') loadMemory();
  if(id==='advanced') { loadConfig(); loadReplyVoiceProbability(); loadProactive(); }
  if(id==='model') loadProfiles();
  if(id==='voice') loadVoice();
  if(id==='test') { loadVoiceTestState(); loadDeveloper(false); }
  if(id==='evaluation') loadEvaluation(false);
  if(id==='minecraft') loadMinecraft();
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
async function loadEvaluation(force=false) {
"""
