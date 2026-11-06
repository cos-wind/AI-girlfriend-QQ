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
    '<button class="ghost mini" data-group="' + escapeHtml(groupId) + '" data-kind="' + kind + '" onclick="generateGroupSummary(this.dataset.group,this.dataset.kind,true,false,this)">立即生成并发送</button><button class="ghost mini" title="生成图文报告并下载，不发送到 QQ" data-group="' + escapeHtml(encodeURIComponent(groupId)) + '" data-kind="' + kind + '" onclick="generateAndDownloadSavedGroupSummary(this)">立即生成并保存</button></div>';
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
function summaryProgressHost(button) {
  const context=button?.closest?.('.summary-context') || document.querySelector('.summary-context') || $('summaryScheduleRows')?.closest?.('.surface');
  if(!context) return null;
  let host=context.querySelector('.summary-task-progress');
  if(!host) { host=document.createElement('div'); host.className='summary-task-progress'; context.prepend(host); }
  return host;
}
function renderSummaryProgress(host, detail, label) {
  if(!host) return;
  const percent=Math.max(0,Math.min(100,Number(detail?.progress_percent||0)));
  const status=String(detail?.status||'queued');
  const stage=detail?.progress_stage || (status==='queued'?'已排队':status);
  const extra=detail?.progress_detail || '';
  host.innerHTML='<div class="entry-head"><strong>'+escapeHtml(label)+'</strong><span class="badge '+(status==='completed'?'active':(status==='failed'?'red':'warn'))+'">'+escapeHtml(stage)+'</span></div><div class="summary-progress-track"><span style="width:'+percent+'%"></span></div><div class="note">'+percent+'% · '+escapeHtml(extra || '正在等待任务状态…')+'</div>';
}
async function watchSummaryTask(summaryId, label, options={}) {
  const host=options.host || null;
  for(;;) {
    try {
      const data=await api('/api/group-summaries/detail?id='+encodeURIComponent(summaryId));
      const detail=data.summary||{};
      renderSummaryProgress(host,detail,label);
      const status=String(detail.status||'');
      if(status==='completed') {
        if(options.download) downloadGroupSummaryImage(summaryId);
        toast(label+(options.download?'已生成并开始下载':(options.send?'已生成并发送到群':'已生成')));
        return detail;
      }
      if(status==='failed') {
        const message=detail.error||detail.progress_detail||'生成失败';
        if(host) host.innerHTML='<div class="bad">'+escapeHtml(label+'失败：'+message)+'</div>';
        toast(label+'失败：'+message); return null;
      }
    } catch(error) {
      // WebUI 短暂刷新或网络波动不能把仍在后台运行的任务误报为失败。
      if(host) host.innerHTML='<div class="note">'+escapeHtml(label+'仍在后台运行，正在重新连接状态…')+'</div>';
    }
    await new Promise(resolve=>setTimeout(resolve,1200));
  }
}
async function generateGroupSummary(groupId, periodType, sendNow=true, saveImage=false, button=null) {
  try {
    const result=await api('/api/group-summaries/generate', {method:'POST', body:JSON.stringify({group_id:groupId,period_type:periodType,send:Boolean(sendNow),save_image:Boolean(saveImage)})});
    const periodLabel = periodType === 'daily' ? '日报' : (periodType === 'weekly' ? '周报' : '月报');
    const label=periodLabel+(sendNow?'生成并发送':(saveImage?'生成并保存':'生成'));
    toast(label+'已开始，正在读取 QQ 客户端历史');
    void watchSummaryTask(String(result.id||''),label,{send:sendNow,download:false,host:summaryProgressHost(button)});
  } catch(error) { toast('生成失败：' + error.message); }
}
function groupSummaryPeriodLabel(periodType) {
  return periodType === 'daily' ? '日报' : (periodType === 'weekly' ? '周报' : '月报');
}
function downloadGroupSummaryImage(summaryId) {
  const link = document.createElement('a');
  link.href = '/api/group-summaries/export?id=' + encodeURIComponent(summaryId) + '&format=image&download=1';
  link.download = 'group-summary.png';
  link.style.display = 'none';
  document.body.appendChild(link);
  link.click();
  link.remove();
}
async function generateAndDownloadSavedGroupSummary(button) {
  const groupId = decodeURIComponent(button?.dataset?.group || '');
  const periodType = button?.dataset?.kind || 'daily';
  const label = groupSummaryPeriodLabel(periodType);
  try {
    const result = await api('/api/group-summaries/generate', {
      method:'POST', body:JSON.stringify({group_id:groupId,period_type:periodType,send:false,save_image:true})
    });
    const summaryId = String(result.id || '');
    if(!summaryId) throw new Error('未返回总结任务编号');
    toast(label + '正在生成图文报告，完成后会自动下载');
    await watchSummaryTask(summaryId,label+'生成并保存',{download:true,host:summaryProgressHost(button)});
  } catch(error) { toast('生成并保存失败：' + error.message); }
}
function summaryTimeCoordinate(item) {
  return String(item?.period_end || item?.created_at || '').replace('T',' ').slice(0,16) || '未记录时间';
}
function summaryTimelineMarkup(items, detailId, groupId, groupName) {
  const ordered=[...items].sort((a,b)=>String(b.period_end||b.created_at||'').localeCompare(String(a.period_end||a.created_at||'')));
  const groups=new Map();
  ordered.forEach(item=>{ const date=summaryTimeCoordinate(item).slice(0,10)||'未记录日期'; if(!groups.has(date)) groups.set(date,[]); groups.get(date).push(item); });
  return '<div class="summary-timeline">'+[...groups.entries()].map(([date,rows])=>'<section class="summary-timeline-day"><h4>'+escapeHtml(date)+'</h4>'+rows.map(item=>'<article class="summary-timeline-item"><div><strong>'+escapeHtml(({daily:'日报',weekly:'周报',monthly:'月报'}[item.period_type] || '群聊总结'))+'</strong><span class="note"> · '+escapeHtml(summaryTimeCoordinate(item))+' · '+Number(item.message_count||0)+' 条消息</span></div><div class="summary-actions"><span class="badge '+(item.status==='completed'?'active':(item.status==='failed'?'red':'warn'))+'">'+escapeHtml(item.progress_stage||item.status||'')+'</span><button class="ghost mini" data-id="'+escapeHtml(encodeURIComponent(item.id||''))+'" data-detail="'+escapeHtml(detailId||'')+'" onclick="viewSummaryDetail(this.dataset.id,this.dataset.detail)">展开</button><button class="ghost mini" data-id="'+escapeHtml(encodeURIComponent(item.id||''))+'" onclick="openSummaryImage(this.dataset.id)">图文</button></div></article>').join('')+'</section>').join('')+'</div>';
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
    const content = items.length ? summaryTimelineMarkup(items,detailId || summaryDetailRowId(groupId),groupId,groupName) : '<div class="empty">本群还没有生成总结。</div>';
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
"""
