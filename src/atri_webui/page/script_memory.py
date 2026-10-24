from __future__ import annotations

PART = r"""async function loadMemory() {
  const [m, proactive] = await Promise.all([api('/api/memory'), api('/api/proactive')]);
  const directory = window._userDirectory || {items:[],groups:[],total:0,groupTotal:0,sourceStatus:{}};
  const directorySourceStatus={...(window._userDirectory?.sourceStatus || {}), ...(directory.sourceStatus || {})};
  if(window._userDirectory?.sourceStatus?.qzone==='ready' && directory.sourceStatus?.qzone==='not_refreshed') directorySourceStatus.qzone='ready';
  window._userDirectory = {items:directory.items || [], groups:directory.groups || [], total:Number(directory.total||0), groupTotal:Number(directory.groupTotal||directory.groups?.length||0), selectedIds:Array.isArray(window._userDirectory?.selectedIds) ? window._userDirectory.selectedIds : [], sourceStatus:directorySourceStatus};
  window._proactive = proactive;
  renderDirectoryProactiveState();
  const plans = new Map(((proactive.schedule || {}).items || []).map(item=>[String(item.conversation_id || ''), item]));
  window._memoryItems = (m.items || []).map(item=>{
    const planId = item.kind === 'person' ? `private:${String(item.id).replace(/^person:/, '')}` : item.id;
    const userId = String(item.target?.user_id || '').trim();
    const identity = userId ? (window._userDirectory.items || []).find(user=>String(user.user_id)===userId) : null;
    return {...item, display_name:identity?.canonical_name || item.display_name, proactive_plan:plans.get(planId) || null};
  });
  const planItems = (proactive.schedule || {}).items || [];
  const eligibleCount = planItems.filter(item=>item.eligible).length;
  const retrieval = m.retrieval || {};
  const retrievalText = retrieval.ready
    ? `；检索索引：FTS5 已就绪（${retrieval.entries || 0} 条）`
    : '；检索索引：将在下一次聊天时轻量建立';
  const memoryInfo = $('memoryInfo');
  if(memoryInfo) memoryInfo.textContent = `记忆文件：${m.path}，显示对象：${m.conversations}，底层记录：${m.raw_conversations || m.conversations}；主动计划入选 ${eligibleCount}/${planItems.length}${retrievalText}`;
  renderMemoryContextSelector();
  // 统一用户中心首屏直接展示记忆关系；记忆接口晚于用户目录返回时也要补绘卡片。
  if(typeof renderUserDirectory === 'function') renderUserDirectory();
}
function renderMemoryContextSelector() {
  const select = $('memoryContextSelector');
  if(!select) return;
  const previous = select.value;
  const users = (window._userDirectory?.items || []).map(item=>({
    value:`person:${item.user_id}`,
    label:`${item.canonical_name || item.user_id} · QQ ${item.user_id}`,
    item
  }));
  const groups = (window._userDirectory?.groups || []).map(item=>({
    value:`group:${item.group_id}`,
    label:`${item.canonical_name || `群 ${item.group_id}`} · 群聊`,
    item
  }));
  const options = [...users, ...groups];
  select.innerHTML = options.length
    ? `<option value="">请选择对象</option>${options.map(option=>`<option value="${escapeHtml(option.value)}">${escapeHtml(option.label)}</option>`).join('')}`
    : '<option value="">暂无可编辑对象</option>';
  if(options.some(option=>option.value===previous)) select.value = previous;
  renderMemoryContextHint();
}
function renderMemoryContextHint() {
  const select = $('memoryContextSelector');
  const hint = $('memoryContextHint');
  if(!select || !hint) return;
  const id = select.value;
  const item = (window._memoryItems || []).find(row=>String(row.id)===id);
  hint.textContent = item
    ? `${item.display_name || id}：${item.summary || '暂无可读摘要'} · ${memoryCountText(item.memory_counts || {})}`
    : '选择用户或群聊后，可打开完整记忆编辑器；身份和能力设置请在用户中心卡片中维护。';
}
function openSelectedMemoryContext() {
  const id = $('memoryContextSelector')?.value || '';
  if(!id) return toast('请先选择用户或群聊');
  openMemory(id);
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
  if($('memoryImportantOnly')?.checked && !(item.memory_counts && item.memory_counts.total > 0)) return false;
  if($('memoryRecentOnly')?.checked) {
    const raw = Number(item.last_user_at || 0);
    const seconds = raw > 100000000000 ? raw / 1000 : raw;
    if(!seconds || (Date.now() / 1000 - seconds) > 7 * 86400) return false;
  }
  const q = ($('memorySearch')?.value || '').trim().toLowerCase();
  if(!q) return true;
  return String(item.searchable || '').toLowerCase().includes(q);
}
function renderMemoryRows() {
  if(!$('memoryRows')) return;
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
        <div class="memory-score">${x.kind==='group' ? `活跃度 ${formatScore(x.activity)} · ${escapeHtml(x.activity_label || '普通')}` : `好感 ${formatScore(x.affection)} · ${escapeHtml(x.affection_label || '普通')} · ${escapeHtml(x.trust_label || '观察中')}`}</div>
        ${x.kind==='group' ? '' : `<div class="memory-meta">信任：${escapeHtml(x.trust_label || '观察中')}</div>`}
        ${renderMemoryPlan(x)}
        <div class="memory-meta" style="margin-top:6px">消息 ${x.messages||0} · L1 ${((x.memory_counts||{}).l1)||0} · L2 ${((x.memory_counts||{}).l2)||0} · L3 ${((x.memory_counts||{}).l3)||0}${((x.memory_counts||{}).candidates) ? ' · 待确认 ' + x.memory_counts.candidates : ''}${x.related_count ? ' · 来源 ' + x.related_count : ''}</div>
      </td>
      <td><div class="row" style="margin-top:0"><button class="ghost" onclick="toggleMemoryInline(this)">展开</button><button class="ghost" onclick="openMemory('${escapeHtml(x.id)}')">详情 / 编辑</button>${x.kind==='person' && x.target?.user_id ? `<button class="ghost" onclick="openUserInDirectory('${escapeHtml(x.target.user_id)}')">用户中心</button>` : ''}</div></td>
    </tr>
    <tr class="memory-inline-row" style="display:none"><td colspan="4"><div class="natural-box"><strong>${escapeHtml(x.display_name || x.id)}</strong><br>${escapeHtml(x.summary || '暂无可读摘要')}<br><span class="memory-meta">${escapeHtml(x.type || '')} · L1 ${((x.memory_counts||{}).l1)||0} · L2 ${((x.memory_counts||{}).l2)||0} · L3 ${((x.memory_counts||{}).l3)||0}</span></div></td></tr>`).join('') || '<tr><td colspan="4"><div class="empty">没有匹配的记忆。</div></td></tr>';
}
function toggleMemoryInline(button) {
  const row = button.closest('tr')?.nextElementSibling;
  if(!row) return;
  const open = row.style.display !== 'none';
  row.style.display = open ? 'none' : 'table-row';
  button.textContent = open ? '展开' : '收起';
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
  (event.currentTarget || event.target).classList.add('active'); $(id).style.display = 'block';
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
  for (const key of ['l1','l2','l3','candidates']) {
    if(!Array.isArray(selectedMemoryContent.structured_memory[key])) selectedMemoryContent.structured_memory[key] = [];
  }
  return selectedMemoryContent.structured_memory;
}
function memoryEntryLayerForPane() {
  if(activeMemoryPane === 'memoryEvents') return 'l2';
  if(activeMemoryPane === 'memoryHistory') return 'l3';
  if(activeMemoryPane === 'memoryProfile') return 'l1';
  return 'l1';
}
function formatMemoryTime(value) {
  const n = Number(value || 0);
  if(!Number.isFinite(n) || n <= 0) return '暂无';
  return new Date(n * 1000).toLocaleString();
}
function memoryCountText(counts) {
  counts = counts || {};
  return `L1 ${counts.l1 || 0} / L2 ${counts.l2 || 0} / L3 ${counts.l3 || 0} / 待确认 ${counts.candidates || 0}`;
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
  const trustTier = ['approved','trusted','blocked'].includes(selectedMemoryContent.trust_tier)
    ? selectedMemoryContent.trust_tier
    : 'probation';
  return `<div class="relationship-controls">
    <h3>关系与主动互动</h3>
    <div class="grid">
      ${isPerson ? `<label>好感度（0–100）<input id="memoryAffectionScore" type="number" min="0" max="100" step="0.1" value="${escapeHtml(selectedMemoryContent.affection_score ?? 0)}"></label>` : ''}
      ${isPerson ? `<label>账号信任层级<select id="memoryTrustTier">
        <option value="probation" ${trustTier==='probation'?'selected':''}>观察中（仅响应消息）</option>
        <option value="approved" ${trustTier==='approved'?'selected':''}>白名单</option>
        <option value="trusted" ${trustTier==='trusted'?'selected':''}>可信用户</option>
        <option value="blocked" ${trustTier==='blocked'?'selected':''}>屏蔽回复</option>
      </select></label>` : ''}
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
  const trustTier = $('memoryTrustTier')?.value || 'probation';
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
      proactive_override:override,
      trust_tier:trustTier
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
    if(scoreInput) selectedMemoryContent.trust_tier = relationship.trust_tier || 'probation';
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
      {label:'L1 / L2 / L3', value:`${counts.l1 || 0} / ${counts.l2 || 0} / ${counts.l3 || 0}`},
      {label:'待确认特点', value:String(counts.candidates || 0)},
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
  $('memoryProfile').innerHTML = renderEntryEditor('l1', ['profile_fact','interest','preference','habit','communication_style'], 'L1 已确认的用户特点') + renderEntryEditor('candidates', ['profile_fact','interest','preference','habit','communication_style'], 'L1 待确认特点') + renderRulesEditor();
  $('memoryEvents').innerHTML = renderEntryEditor('l2', ['event','schedule','important_interaction'], 'L2 事件、日程与重要互动');
  $('memoryHistory').innerHTML = renderEntryEditor('l3', ['session_context'], 'L3 当前会话上下文') + renderHistoryEditor() + '<p class="note">L3 是短上下文；完整消息历史单独展示，供画像提取和人工核对使用，不会把全部历史一次性塞进回复提示词。</p>';
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
    <label>内容<textarea oninput="updateMemoryEntry('${layer}',${index},'value',this.value)${layer === 'l3' ? "; updateMemoryEntry('l3'," + index + ",'text',this.value)" : ''}">${escapeHtml(entry.value || entry.text || '')}</textarea></label>
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
  const recent = history.map((entry,index)=>({entry,index})).slice(-300).reverse();
  return `<h3>完整消息历史（最多保留 300 条）</h3><p class="note">这里展示当前人物档案保留的完整消息窗口，包含用户和亚托莉的消息；可修正或删除记忆副本，不会撤回 QQ 消息。</p>${recent.map(({entry,index})=>`
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
  if(activeMemoryPane === 'memoryHistory') category = 'session_context';
  const now = Math.floor(Date.now() / 1000);
  memory[layer].push({
    layer: layer.toUpperCase(),
    category,
    key: category + ':新记忆',
    value: '',
    text: layer === 'l3' ? '' : undefined,
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
"""
