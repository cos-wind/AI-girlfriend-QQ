from __future__ import annotations

PART = r"""  morning:'早安', goodnight:'晚安', check_in:'关心近况', continue_topic:'继续上次话题',
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
  // 这个函数同时服务「高级配置」页和「测试」页（后者只用主动消息预览），
  // 所以每个写入点都要容忍元素不在当前页面。
  const write = (id, action) => { const node = $(id); if(node) action(node); };
  write('proactiveEngineEnabled', node=>{ node.checked = String(engineValue).toLowerCase() === 'true'; });
  write('proactiveEnabled', node=>{ node.checked = !!p.enabled; });
  write('proactiveOwnerOnly', node=>{ node.checked = !!p.owner_only; });
  write('proactiveUseAi', node=>{ node.checked = !!p.use_ai; });
  write('proactiveGuidedTopics', node=>{ node.checked = !!p.guided_topics; });
  write('proactiveGroupEnabled', node=>{ node.checked = !!p.group_enabled; });
  write('proactivePrivateMinHours', node=>{ node.value = p.private_min_hours ?? 0.75; });
  write('proactivePrivateMaxHours', node=>{ node.value = p.private_max_hours ?? 2; });
  write('proactiveGroupMinHours', node=>{ node.value = p.group_min_hours ?? 1.5; });
  write('proactiveGroupMaxHours', node=>{ node.value = p.group_max_hours ?? 3; });
  write('proactiveGroupHotMinHours', node=>{ node.value = p.group_hot_min_hours ?? 0.75; });
  write('proactiveGroupHotMaxHours', node=>{ node.value = p.group_hot_max_hours ?? 1.5; });
  write('proactiveMaxUnanswered', node=>{ node.value = p.max_unanswered ?? 2; });
  write('proactiveGlobalGapMinutes', node=>{ node.value = p.global_gap_minutes ?? 7; });
  write('proactiveConversationCooldownMinutes', node=>{ node.value = p.conversation_cooldown_minutes ?? 10; });
  write('proactiveTimezone', node=>{ node.value = p.timezone || 'Asia/Shanghai'; });
  write('proactiveQuietStart', node=>{ node.value = p.quiet_start || '00:30'; });
  write('proactiveQuietEnd', node=>{ node.value = p.quiet_end || '07:00'; });
  write('proactiveCheckSeconds', node=>{ node.value = p.check_seconds || 60; });
  write('proactiveBackoff', node=>{ node.value = p.ignored_backoff || 1.5; });
  write('proactiveHistoryLimit', node=>{ node.value = p.history_limit ?? 8; });
  write('proactiveMaxChars', node=>{ node.value = p.max_chars || 90; });
  write('proactiveFeatureState', node=>{
    node.innerHTML = data.feature_enabled
      ? '<span class="ok">新版调度器已接管私聊、早安及已启用的群聊主动消息；旧版循环处于回退待命状态。</span>'
      : '<span class="bad">新版调度器未启用，当前仍由旧版私聊/早安规则运行。</span>';
  });
  // 亲密度分档：服务端返回的就是合并后的整张表（reply_strategy 的档位 + 主动侧字段），
  // 这里渲染一次即可，两个页面共用同一个 tbody。
  if($('affectionTierRows')) {
    replyStrategyRenderTiers(p.tiers || []);
    replyStrategyTiersLoaded = true;
  }
  // 同步被动表格快照；主动频率由上方独立控件维护。
  if($('replyActivityTierRows')) {
    renderReplyStrategyActivityTiers(p.activity_tiers || []);
  }
  write('proactiveWeights', node=>{
    node.innerHTML = Object.entries(p.content_weights || {}).map(([key,value])=>
      `<label>${escapeHtml(proactiveWeightLabels[key] || key)}<input data-weight="${escapeHtml(key)}" type="number" min="0" max="100" step="1" value="${value}"></label>`
    ).join('');
  });
  write('proactiveGroupWeights', node=>{
    node.innerHTML = Object.entries(p.group_content_weights || {}).map(([key,value])=>
      `<label>${escapeHtml(proactiveWeightLabels[key] || key)}<input data-group-weight="${escapeHtml(key)}" type="number" min="0" max="100" step="1" value="${value}"></label>`
    ).join('');
  });
  renderProactivePreviewTypes();
  const schedule = data.schedule || {};
  const items = schedule.items || [];
  if(items.length && $('proactivePreviewUser') && !$('proactivePreviewUser').value) {
    const firstEligible = items.find(item=>item.eligible) || items[0];
    $('proactivePreviewScope').value = firstEligible.target_type || 'private';
    $('proactivePreviewUser').value = firstEligible.target_id || '';
    renderProactivePreviewTypes();
  }
}
// 「分档面板」在用户分档 / 群聊分档之间切换。主动消息那个面板已删除：
// 主动侧的门槛与权重是卡片上的普通表单项，不需要再占一个只读页签。
function showTierPane(name) {
  const target = ['user','group'].includes(name) ? name : 'user';
  document.querySelectorAll('.tier-tab').forEach(tab=>{
    tab.classList.toggle('active', tab.dataset.tierTab === target);
  });
  ['user','group'].forEach(key=>{
    const pane = $('tierPane' + key.charAt(0).toUpperCase() + key.slice(1));
    if(pane) pane.classList.toggle('active', key === target);
  });
}
// 档位按钮上的小徽标：一眼看出这一档有没有启用。
// 回复策略本身常开（运行规则卡片已删除），所以徽标只报「几档启用」。
function renderTierTabBadges(tiers) {
  const counts = {on:0, total:0};
  (Array.isArray(tiers) ? tiers : []).forEach(tier=>{
    counts.total += 1;
    if(tier && tier.enabled) counts.on += 1;
  });
  const badge = `${counts.on}/${counts.total} 档启用`;
  document.querySelectorAll('.tier-tab-badge').forEach(node=>{ node.textContent = badge; });
}
function renderProactivePreviewTypes() {
  // 主动消息预览挪到了「测试」页的聊天回复测试里，作为扩展项；元素可能还不存在。
  if(!$('proactivePreviewType')) return;
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
  if(matching && !$('proactivePreviewUser').value) $('proactivePreviewUser').value = matching.target_id || '';
  const hint = $('proactivePreviewTierHint');
  if(hint) {
    hint.textContent = p.enabled === false
      ? '主动消息当前已关闭，预览只是看看文案会怎么写；要真正发出需要在「高级配置」里开启。'
      : '评估间隔在「高级配置 → 主动发起」调整；没有合适内容时允许不发。';
  }
}
function collectProactivePolicy() {
  // 保留未显示的设置，仅收集现存控件。
  const base = JSON.parse(JSON.stringify((window._proactive || {}).policy || {}));
  base.enabled = $('proactiveEnabled').checked;
  base.owner_only = $('proactiveOwnerOnly').checked;
  base.use_ai = $('proactiveUseAi').checked;
  base.guided_topics = $('proactiveGuidedTopics').checked;
  base.group_enabled = $('proactiveGroupEnabled').checked;
  if($('proactivePrivateMinHours')) base.private_min_hours = Number($('proactivePrivateMinHours').value);
  if($('proactivePrivateMaxHours')) base.private_max_hours = Number($('proactivePrivateMaxHours').value);
  if($('proactiveGroupMinHours')) base.group_min_hours = Number($('proactiveGroupMinHours').value);
  if($('proactiveGroupMaxHours')) base.group_max_hours = Number($('proactiveGroupMaxHours').value);
  if($('proactiveGroupHotMinHours')) base.group_hot_min_hours = Number($('proactiveGroupHotMinHours').value);
  if($('proactiveGroupHotMaxHours')) base.group_hot_max_hours = Number($('proactiveGroupHotMaxHours').value);
  if($('proactiveMaxUnanswered')) base.max_unanswered = Number($('proactiveMaxUnanswered').value);
  if($('proactiveGlobalGapMinutes')) base.global_gap_minutes = Number($('proactiveGlobalGapMinutes').value);
  if($('proactiveConversationCooldownMinutes')) base.conversation_cooldown_minutes = Number($('proactiveConversationCooldownMinutes').value);
  base.timezone = $('proactiveTimezone').value.trim();
  base.quiet_start = $('proactiveQuietStart').value;
  base.quiet_end = $('proactiveQuietEnd').value;
  base.check_seconds = Number($('proactiveCheckSeconds').value);
  base.ignored_backoff = Number($('proactiveBackoff').value);
  base.history_limit = Number($('proactiveHistoryLimit').value);
  base.max_chars = Number($('proactiveMaxChars').value);
  // 两张档位表都提交同一份快照，避免只写一半。
  base.tiers = collectAffectionTiers();
  base.activity_tiers = collectReplyStrategyActivityTiers(
    ((window._replyStrategy || {}).policy || {}).activity_tiers || []
  );
  base.content_weights = {};
  document.querySelectorAll('[data-weight]').forEach(input=>base.content_weights[input.dataset.weight]=Number(input.value));
  base.group_content_weights = {};
  document.querySelectorAll('[data-group-weight]').forEach(input=>base.group_content_weights[input.dataset.groupWeight]=Number(input.value));
  return base;
}
async function saveProactive(button) {
  // 档位表与回复策略共用，两个保存按钮都走同一条「一起落盘」的路径。
  return saveReplyAndProactive(button, '保存中…');
}
async function previewProactive(button) {
  const out = $('proactivePreviewOut');
  if(!out) return;
  return withButtonBusy(button, async () => {
    out.textContent = '正在生成预览...';
    if(!$('proactivePreviewType').value) await loadProactive();
    try {
      const body = {event_type:$('proactivePreviewType').value, scope:$('proactivePreviewScope').value, target_id:$('proactivePreviewUser').value.trim()};
      const result = await api('/api/proactive/preview', {method:'POST', body:JSON.stringify(body)});
      out.textContent = `${result.reply || result.text || ''}

来源：${result.source || '未知'}${result.error ? `
模型错误：${result.error}` : ''}`;
    } catch (error) {
      out.textContent = `预览失败：${error.message}`;
    }
  }, '生成中…');
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
async function loadModalityAccess() {
  try {
    const policyData = await api('/api/modality-access');
    const directory = window._userDirectory || {items:[],groups:[]};
    window._modalityAccess = {...policyData, users:directory.items || [], groups:directory.groups || []};
    if($('directoryVisionAllowlistEnabled')) $('directoryVisionAllowlistEnabled').checked = Boolean(policyData.policy?.vision_allowlist_enabled);
    if($('directoryVoiceAllowlistEnabled')) $('directoryVoiceAllowlistEnabled').checked = Boolean(policyData.policy?.voice_allowlist_enabled);
    if($('directoryModalityAccessState')) $('directoryModalityAccessState').textContent = '已加载；白名单关闭时不会限制用户';
  } catch(error) {
    if($('directoryModalityAccessState')) $('directoryModalityAccessState').textContent = '读取失败：' + error.message;
  }
}
async function saveDirectoryModalityPolicy() {
  const current = window._modalityAccess || await api('/api/modality-access');
  const policy = JSON.parse(JSON.stringify(current.policy || {}));
  policy.vision_allowlist_enabled = Boolean($('directoryVisionAllowlistEnabled')?.checked);
  policy.voice_allowlist_enabled = Boolean($('directoryVoiceAllowlistEnabled')?.checked);
  try {
    const result = await api('/api/modality-access',{method:'POST',body:JSON.stringify(policy)});
    window._modalityAccess = {...current, policy:result.policy};
    if($('directoryModalityAccessState')) $('directoryModalityAccessState').textContent = '已保存，新的 QQ 消息立即生效';
    toast('视觉 / 语音白名单策略已保存');
  } catch(error) {
    if($('directoryModalityAccessState')) $('directoryModalityAccessState').textContent = '保存失败：' + error.message;
    toast('权限策略保存失败：' + error.message);
  }
}

async function loadQZoneBridge() {
  // 运行状态统一显示在顶部「运行状态」，卡片里不再重复显示。
  await loadStatus();
}
async function startQZoneBridge(button) {
  return withButtonBusy(button, async () => {
    const result = await api('/api/qzone/bridge',{method:'POST',body:JSON.stringify({action:'start'})});
    toast(result.message || 'Bridge 已启动');
    await loadQZoneBridge();
  }, '启动中…');
}
async function stopQZoneBridge(button) {
  return withButtonBusy(button, async () => {
    const result = await api('/api/qzone/bridge',{method:'POST',body:JSON.stringify({action:'stop'})});
    toast(result.message || 'Bridge 已停止');
    await loadQZoneBridge();
  }, '停止中…');
}

function userDirectorySourceLabel(source) {
"""
