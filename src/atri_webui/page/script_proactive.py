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
    $('proactivePreviewOut').textContent = `${result.reply || result.text || ''}

来源：${result.source || '未知'}${result.error ? `
模型错误：${result.error}` : ''}`;
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

function userDirectorySourceLabel(source) {
"""
