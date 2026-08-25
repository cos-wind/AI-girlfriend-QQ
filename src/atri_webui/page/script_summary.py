from __future__ import annotations

PART = r"""async function loadGroupSummaryWorkspace() {
  try {
    const data = await api('/api/group-summaries/schedules');
    renderSummarySchedules(data.schedules || []);
    renderUserDirectory();
  } catch(error) {
    const target = $('summaryScheduleRows');
    if(target) target.innerHTML = '<tr><td colspan="5" class="bad">' + escapeHtml(error.message) + '</td></tr>';
  }
}
function summaryPlanCell(groupId, kind, row) {
  const enabled = Boolean(Number(row[kind + '_enabled'] || 0));
  const nextAt = row[kind + '_next_at'] || '';
  const lastSent = row[kind + '_last_sent_at'] || '';
  const key = (kind + '_' + groupId).replace(/[^a-zA-Z0-9_-]/g, '_');
  const label = kind === 'daily' ? '日报' : (kind === 'weekly' ? '周报' : '月报');
  return '<div class="summary-plan" data-group="' + escapeHtml(groupId) + '" data-kind="' + kind + '">' +
    '<label class="switch-line"><input id="summary_' + key + '_enabled" type="checkbox" ' + (enabled ? 'checked' : '') + '><span>' + label + '</span></label>' +
    '<input id="summary_' + key + '_next_at" type="datetime-local" value="' + escapeHtml(nextAt) + '" title="下一次自动生成并发送时间">' +
    (lastSent ? '<span class="summary-last-sent">上次成功发送：' + escapeHtml(String(lastSent).replace('T',' ')) + '</span>' : '<span class="summary-last-sent">尚未自动发送</span>') +
    '<button class="ghost mini" data-group="' + escapeHtml(groupId) + '" data-kind="' + kind + '" onclick="generateGroupSummary(this.dataset.group,this.dataset.kind,true)">立即生成并发送</button></div>';
}
function renderSummarySchedules(rows) {
  const target = $('summaryScheduleRows');
  if(!target) return;
  window._summarySchedules = rows || [];
  if(!rows.length) {
    target.innerHTML = '<tr><td colspan="5" class="empty">暂无已归档群聊。</td></tr>';
    return;
  }
  target.innerHTML = rows.map(row => {
    const groupId = String(row.group_id || '');
    const detailId = summaryDetailRowId(groupId);
    const encodedGroupId = encodeURIComponent(groupId);
    const encodedName = encodeURIComponent(row.group_name || '未命名群聊');
    return '<tr><td><strong>' + escapeHtml(row.group_name || '未命名群聊') + '</strong><br><span class="note">已归档 ' +
      Number(row.messages || 0) + ' 条 · 最后消息 ' + escapeHtml(String(row.last_message_at || '').replace('T',' ').slice(0,16)) +
      '</span></td><td>' + summaryPlanCell(groupId,'daily',row) + '</td><td>' + summaryPlanCell(groupId,'weekly',row) +
      '</td><td>' + summaryPlanCell(groupId,'monthly',row) + '</td><td><div class="summary-actions"><button class="primary" data-group="' +
      escapeHtml(encodedGroupId) + '" onclick="saveGroupSummarySchedule(this.dataset.group)">保存本群</button><button class="ghost" data-group="' + escapeHtml(encodedGroupId) + '" data-name="' + escapeHtml(encodedName) + '" data-detail="' + detailId + '" onclick="toggleSummaryGroupDetails(this.dataset.detail,this.dataset.group,this.dataset.name)">详情</button></div></td></tr>' +
      '<tr id="' + detailId + '" class="summary-detail-row" hidden><td colspan="5"><div class="summary-group-details"><div class="empty">点击“详情”查看本群已生成的总结。</div></div></td></tr>';
  }).join('');
}
function summaryControlId(groupId, kind, suffix) {
  const key = (kind + '_' + groupId).replace(/[^a-zA-Z0-9_-]/g, '_');
  return 'summary_' + key + '_' + suffix;
}
function summaryDetailRowId(groupId) {
  return 'summary_detail_' + String(groupId || '').replace(/[^a-zA-Z0-9_-]/g, '_');
}
async function saveGroupSummarySchedule(encodedGroupId) {
  const groupId = decodeURIComponent(encodedGroupId || '');
  const plan = kind => ({
    enabled: Boolean($(summaryControlId(groupId, kind, 'enabled'))?.checked),
    next_at: $(summaryControlId(groupId, kind, 'next_at'))?.value || ''
  });
  try {
    await api('/api/group-summaries/schedules', {
      method:'POST',
      body:JSON.stringify({group_id:groupId,daily:plan('daily'),weekly:plan('weekly'),monthly:plan('monthly')})
    });
    toast('本群总结计划已保存');
    await loadGroupSummaryWorkspace();
  } catch(error) { toast('计划保存失败：' + error.message); }
}
async function generateGroupSummary(groupId, periodType, sendNow=true) {
  try {
    await api('/api/group-summaries/generate', {method:'POST', body:JSON.stringify({group_id:groupId,period_type:periodType,send:Boolean(sendNow)})});
    toast((periodType === 'daily' ? '日报' : (periodType === 'weekly' ? '周报' : '月报')) + (sendNow ? '已进入生成并发送队列' : '已进入生成队列'));
  } catch(error) { toast('生成失败：' + error.message); }
}
function toggleSummaryGroupDetails(detailId, encodedGroupId, encodedName) {
  const row = $(detailId);
  if(!row) return;
  const willShow = row.hidden;
  row.hidden = !willShow;
  if(willShow) loadSummaryGroupDetails(encodedGroupId, encodedName, detailId);
}
async function loadSummaryGroupDetails(encodedGroupId, encodedName, detailId) {
  const groupId = decodeURIComponent(encodedGroupId || '');
  const groupName = decodeURIComponent(encodedName || '') || '未命名群聊';
  const row = $(detailId || summaryDetailRowId(groupId));
  const target = row ? row.querySelector('.summary-group-details') : null;
  if(!target) return;
  target.innerHTML = '<div class="note">正在读取“' + escapeHtml(groupName) + '”的总结详情…</div>';
  try {
    const data = await api('/api/group-summaries?group_id=' + encodeURIComponent(groupId) + '&limit=30');
    const items = data.items || [];
    const content = items.length ? '<div class="summary-detail-list">' + items.map(item => '<div class="summary-detail-item"><div class="entry-head"><strong>' + escapeHtml(item.title || ({daily:'每日总结',weekly:'周报',monthly:'月度总结'}[item.period_type] || '群聊总结')) + '</strong><span class="badge ' + (item.status === 'completed' ? 'active' : (item.status === 'failed' ? 'red' : 'warn')) + '">' + escapeHtml(item.status || '') + '</span></div><div class="note">' + escapeHtml(item.period_label || '') + ' · ' + escapeHtml(String(item.created_at || '').replace('T',' ')) + ' · ' + Number(item.message_count || 0) + ' 条消息 · ' + (item.trigger_type === 'scheduled' ? '自动发送' : (item.trigger_type === 'manual_send' ? '手动生成并发送' : '仅生成')) + '</div><div class="summary-detail-content">' + escapeHtml(item.content || item.error || '报告正在生成…') + '</div><div class="summary-actions"><button class="ghost mini" data-id="' + escapeHtml(encodeURIComponent(item.id || '')) + '" data-detail="' + escapeHtml(detailId || summaryDetailRowId(groupId)) + '" onclick="viewSummaryDetail(this.dataset.id,this.dataset.detail)">查看完整内容</button><button class="ghost mini" data-id="' + escapeHtml(encodeURIComponent(item.id || '')) + '" onclick="openSummaryImage(this.dataset.id)">查看图文</button></div></div>').join('') + '</div>' : '<div class="empty">本群还没有生成总结。</div>';
    target.innerHTML = '<div class="section-head"><div><h3>' + escapeHtml(groupName) + ' · 总结详情</h3><p class="note">显示本群最近生成的日报、周报和月报；发送状态以记录状态为准。</p></div><button class="ghost" data-detail="' + escapeHtml(detailId || summaryDetailRowId(groupId)) + '" onclick="hideSummaryGroupDetails(this.dataset.detail)">收起</button></div>' + content;
  } catch(error) { target.innerHTML = '<div class="bad">详情读取失败：' + escapeHtml(error.message) + '</div>'; }
}
function hideSummaryGroupDetails(detailId) {
  const row = $(detailId);
  if(row) row.hidden = true;
}
async function viewSummaryDetail(encodedId, detailId) {
  const row = $(detailId);
  const target = row ? row.querySelector('.summary-group-details') : null;
  try {
    const data = await api('/api/group-summaries/detail?id=' + encodeURIComponent(decodeURIComponent(encodedId || '')));
    const item = data.summary || {};
    if(target) target.innerHTML = '<div class="section-head"><div><h3>' + escapeHtml(item.title || '群聊总结详情') + '</h3><p class="note">' + escapeHtml(item.period_label || '') + ' · ' + Number(item.message_count || 0) + ' 条消息</p></div><button class="ghost" data-group="' + escapeHtml(encodeURIComponent(item.group_id || '')) + '" data-name="' + escapeHtml(encodeURIComponent(item.group_name || '未命名群聊')) + '" data-detail="' + escapeHtml(detailId || summaryDetailRowId(item.group_id || '')) + '" onclick="loadSummaryGroupDetails(this.dataset.group,this.dataset.name,this.dataset.detail)">返回本群列表</button></div><div class="summary-detail-content">' + escapeHtml(item.content || item.error || '报告尚未完成。') + '</div>';
  } catch(error) { if(target) target.innerHTML = '<div class="bad">完整详情读取失败：' + escapeHtml(error.message) + '</div>'; }
}
function openSummaryImage(encodedId) {
  const id = decodeURIComponent(encodedId || '');
  window.open('/api/group-summaries/export?id=' + encodeURIComponent(id) + '&format=image', '_blank', 'noopener');
}
function showVoiceModule(module) {
"""
