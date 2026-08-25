from __future__ import annotations

PART = r"""  if(window._evaluationLoading) return;
  window._evaluationLoading = true;
  try {
    const selectedModelType = $('evaluationModelType')?.value || '';
    const [status, dashboard, modelData] = await Promise.all([
      api('/api/insights/status'),
      api('/api/evaluations/dashboard?days=30' + (selectedModelType ? '&model_type=' + encodeURIComponent(selectedModelType) : '')),
      api('/api/model-profiles')
    ]);
    const evaluation = status.evaluation || {};
    $('evaluationState').innerHTML = `
      <strong>${evaluation.enabled ? '异步评测已启用' : '异步评测总开关已关闭'}</strong><br>
      评测模型：${escapeHtml(evaluation.model || '未配置')} · ${escapeHtml(evaluation.judge_ready ? (status.config?.judge_source === 'selected_model_profile' ? '使用已选模型档案，凭据就绪' : '使用当前聊天模型，凭据就绪') : '评测模型未配置凭据')} ·
      队列 ${Number(evaluation.queue_size || 0)} · Worker ${Number(evaluation.workers || 0)}<br>
      <span class="note">维度：${(evaluation.dimensions || []).map(key=>escapeHtml(evaluationLabels[key] || key)).join('、')}</span>`;
    const profileSelect = $('evaluationModelProfile');
    const chatProfiles = (modelData.profiles || []).filter(profile => profile.model_type === 'chat' && profile.has_api_key);
    const selectedProfile = status.config?.judge_profile_id || '';
    profileSelect.innerHTML = '<option value="">跟随当前聊天模型</option>' + chatProfiles.map(profile =>
      `<option value="${escapeHtml(profile.id)}">${escapeHtml(profile.name || profile.model)} · ${escapeHtml(profile.provider || '')}</option>`
    ).join('');
    profileSelect.value = chatProfiles.some(profile => profile.id === selectedProfile) ? selectedProfile : '';
    const counts = dashboard.counts || {};
    const stats = [
      ['总记录', counts.total || 0], ['已完成', counts.completed || 0],
      ['待处理', counts.pending || 0], ['失败', counts.failed || 0]
    ];
    $('evaluationStats').innerHTML = stats.map(([label,value])=>`<div class="stat"><span class="note">${label}</span><strong>${Number(value || 0)}</strong></div>`).join('');
    const modelRows = Object.fromEntries((dashboard.model_types || []).map(item=>[item.model_type,item]));
    $('evaluationModelStats').innerHTML = Object.keys(evaluationModelLabels).map(key=>{
      const item = modelRows[key] || {};
      const average = item.average == null ? '—' : Number(item.average).toFixed(2);
      return `<div class="evaluation-model-card"><span class="note">${evaluationModelLabels[key]}</span><strong>${average}</strong><div class="mini-stats"><span>总 ${Number(item.total||0)}</span><span>完成 ${Number(item.completed||0)}</span><span>失败 ${Number(item.failed||0)}</span><span>待处理 ${Number(item.pending||0)}</span></div></div>`;
    }).join('');
    const delivery = dashboard.delivery || {};
    const deliveryRows = Object.fromEntries((delivery.by_model || []).map(item=>[item.model_type,item]));
    $('evaluationDeliveryStats').innerHTML = [
      `<div class="delivery-card"><span class="note">消息发送总数</span><strong>${Number(delivery.total||0)}</strong><div class="mini-stats"><span class="delivery-success">成功 ${Number(delivery.success||0)}</span><span class="delivery-failed">失败 ${Number(delivery.failed||0)}</span></div></div>`,
      ...Object.keys(evaluationModelLabels).map(key=>{ const item=deliveryRows[key]||{}; return `<div class="delivery-card"><span class="note">${evaluationModelLabels[key]}发送</span><strong>${Number(item.total||0)}</strong><div class="mini-stats"><span class="delivery-success">成功 ${Number(item.success||0)}</span><span class="delivery-failed">失败 ${Number(item.failed||0)}</span></div></div>`; })
    ].join('');
    const dimensionMap = Object.fromEntries((dashboard.dimensions || []).map(item=>[item.dimension,item]));
    $('evaluationDimensions').innerHTML = Object.keys(evaluationLabels).map(key=>{
      const item = dimensionMap[key];
      const value = item && item.average != null ? Number(item.average).toFixed(2) : '—';
      return `<div class="score-card"><span>${evaluationLabels[key]}</span><strong class="${item ? scoreClass(item.average) : ''}">${value}</strong><small class="note">${item ? item.samples : 0} 个样本</small></div>`;
    }).join('');
    renderEvaluationTrend(dashboard.trend || [], dashboard.trend_meta || {});
    renderEvaluationTrendDetails(dashboard.trend || [], dashboard.trend_meta || {});
    $('evaluationIssues').innerHTML = (dashboard.top_issues || []).length
      ? dashboard.top_issues.map(item=>`<div class="entry"><div class="entry-head"><span>${escapeHtml(item.issue)}</span><span class="badge warn">${Number(item.count)} 次</span></div></div>`).join('')
      : '<div class="empty">最近 30 天暂无集中问题。</div>';
    await loadEvaluationRecords();
    if(force) toast('评测看板已刷新');
  } catch(error) {
    $('evaluationState').textContent = '评测看板读取失败：' + error.message;
  } finally {
    window._evaluationLoading = false;
  }
}
async function saveEvaluationModelProfile() {
  try {
    await api('/api/insights/config',{method:'POST',body:JSON.stringify({
      EVALUATION_MODEL_PROFILE_ID:$('evaluationModelProfile').value
    })});
    toast('评测模型已切换');
    await loadEvaluation(true);
  } catch(error) {
    toast('评测模型切换失败：' + error.message);
  }
}
function renderEvaluationTrend(items, meta) {
  const svg = $('evaluationTrend');
  if(!items.length) {
    svg.innerHTML = '<text x="450" y="120" text-anchor="middle" fill="#6f6680">暂无已完成评测</text>';
    return;
  }
  const left=58, right=875, top=28, bottom=190;
  const number = (item,key,fallback)=>{ const value=Number(item?.[key]); return Number.isFinite(value) ? value : fallback; };
  const quality = items.map(item=>number(item,'quality_index',number(item,'median',number(item,'average',0))));
  const low = items.map((item,index)=>number(item,'p25',quality[index]));
  const high = items.map((item,index)=>number(item,'p75',quality[index]));
  const rawMin=Math.min(...low,...quality), rawMax=Math.max(...high,...quality);
  const span=Math.max(rawMax-rawMin,0.25), pad=Math.max(0.12,span*0.18);
  let yMin=Math.max(0,Math.floor((rawMin-pad)*10)/10), yMax=Math.min(5,Math.ceil((rawMax+pad)*10)/10);
  if(yMax-yMin<0.5) { yMin=Math.max(0,yMin-0.25); yMax=Math.min(5,yMax+0.25); }
  const yOf=value=>bottom-(Math.max(yMin,Math.min(yMax,value))-yMin)/(yMax-yMin)*(bottom-top);
  const points = items.map((item,index)=>{
    const x = items.length === 1 ? (left+right)/2 : left + (right-left)*index/(items.length-1);
    return {x,y:yOf(quality[index]),value:quality[index],average:number(item,'average',quality[index]),day:String(item.day || ''),low:low[index],high:high[index],delta:number(item,'delta',0)};
  });
  const grid = [0,1,2,3,4].map(index=>{
    const value=yMin+(yMax-yMin)*index/4, y=yOf(value);
    return `<line x1="${left}" y1="${y}" x2="${right}" y2="${y}" stroke="rgba(167,139,250,.18)"/><text x="44" y="${y+4}" text-anchor="end" fill="#6f6680" font-size="11">${value.toFixed(1)}</text>`;
  }).join('');
  const band = [...points.map(point=>point.x+','+yOf(point.high)), ...[...points].reverse().map(point=>point.x+','+yOf(point.low))].join(' ');
  const labels = points.filter((_,index)=>index===0 || index===points.length-1 || index%Math.max(1,Math.ceil(points.length/6))===0)
    .map(point=>`<text x="${point.x}" y="218" text-anchor="middle" fill="#6f6680" font-size="10">${escapeHtml(point.day.slice(5))}</text>`).join('');
  const baseline=number(meta,'average',0);
  svg.innerHTML = `${grid}<line x1="${left}" y1="${yOf(baseline)}" x2="${right}" y2="${yOf(baseline)}" stroke="#f59e0b" stroke-dasharray="5 4"/><polygon points="${band}" fill="rgba(56,189,248,.18)"/><polyline fill="none" stroke="#8b5cf6" stroke-width="3" points="${points.map(point=>point.x+','+point.y).join(' ')}"/>${points.map(point=>`<circle cx="${point.x}" cy="${point.y}" r="4" fill="#38bdf8"><title>${escapeHtml(point.day)} · 质量指数 ${point.value.toFixed(2)} · 平均 ${point.average.toFixed(2)} · 波动 ${point.delta>=0?'+':''}${point.delta.toFixed(2)}</title></circle>`).join('')}${labels}<text x="62" y="16" fill="#8b5cf6" font-size="11">质量指数</text><text x="150" y="16" fill="#38bdf8" font-size="11">P25–P75 区间</text><text x="290" y="16" fill="#f59e0b" font-size="11">窗口平均线</text><text x="870" y="16" text-anchor="end" fill="#6f6680" font-size="11">局部刻度 ${yMin.toFixed(1)}–${yMax.toFixed(1)}</text>`;
}
function renderEvaluationTrendDetails(items, meta) {
  const target = $('evaluationTrendDetails');
  if(!items.length) {
    target.innerHTML = '<div class="empty">暂无按日明细。</div>';
    return;
  }
  const rows = [...items].reverse().map(item => {
    const lowRate=item.low_score_rate == null ? '—' : `${(Number(item.low_score_rate)*100).toFixed(0)}%`;
    const delta=item.delta == null ? '—' : `${Number(item.delta)>=0?'+':''}${Number(item.delta).toFixed(2)}`;
    return `<tr><td>${escapeHtml(item.day || '')}</td><td>${Number(item.samples || 0)}</td><td><strong>${item.quality_index == null ? '—' : Number(item.quality_index).toFixed(2)}</strong></td><td>${item.average == null ? '—' : Number(item.average).toFixed(2)} / ${item.median == null ? '—' : Number(item.median).toFixed(2)}</td><td>${item.p25 == null ? '—' : Number(item.p25).toFixed(2)}–${item.p75 == null ? '—' : Number(item.p75).toFixed(2)}</td><td>${lowRate}</td><td>${item.volatility == null ? '—' : Number(item.volatility).toFixed(2)}</td><td>${delta}</td></tr>`;
  }).join('');
  const windowText = meta && meta.average != null ? `窗口平均 ${Number(meta.average).toFixed(2)} · 中位数 ${Number(meta.median || 0).toFixed(2)} · 波动 ${Number(meta.volatility || 0).toFixed(2)}` : '';
  target.innerHTML = `<div class="note" style="margin-bottom:8px">${windowText}；质量指数更关注低分尾部，点击圆点可查看当日明细。</div><table><thead><tr><th>日期</th><th>样本</th><th>质量指数</th><th>平均 / 中位</th><th>P25–P75</th><th>低分率</th><th>波动</th><th>较前日</th></tr></thead><tbody>${rows}</tbody></table>`;
}
async function loadEvaluationRecords() {
  const params = new URLSearchParams();
  const status = $('evaluationStatus')?.value || '';
  const dimension = $('evaluationDimension')?.value || '';
  const modelType = $('evaluationModelType')?.value || '';
  const maxScore = $('evaluationMaxScore')?.value || '';
  const query = $('evaluationQuery')?.value.trim() || '';
  if(status) params.set('status',status);
  if(dimension) params.set('dimension',dimension);
  if(modelType) params.set('model_type',modelType);
  if(maxScore) params.set('max_score',maxScore);
  if(query) params.set('q',query);
  params.set('limit','120');
  try {
    const data = await api('/api/evaluations?' + params.toString());
    const rows = data.items || [];
    $('evaluationRows').innerHTML = rows.length ? rows.map(item=>{
      const scores = Object.entries(item.scores || {}).map(([key,value])=>`<span class="score-mini ${value == null ? '' : scoreClass(value)}">${escapeHtml(evaluationLabels[key] || key)} ${value == null ? 'N/A' : Number(value).toFixed(1)}</span>`).join('');
      const actions = `<button class="ghost" onclick="openEvaluation('${item.id}')">详情</button>` + (item.status==='failed' ? `<button class="warn" onclick="retryEvaluation('${item.id}')">重试</button>` : '');
      return `<tr><td>${escapeHtml(String(item.created_at || '').replace('T',' '))}<br><span class="badge active">${escapeHtml(evaluationModelLabels[item.model_type] || '聊天模型')}</span> <span class="badge ${item.status==='failed'?'red':(item.status==='completed'?'active':'warn')}">${escapeHtml(item.status)}</span></td><td><strong>${escapeHtml(item.question)}</strong><br><span class="note">${escapeHtml(item.answer)}</span></td><td><div class="score-pills">${scores || '—'}</div></td><td class="${item.overall_score == null ? '' : scoreClass(item.overall_score)}"><strong>${item.overall_score == null ? '—' : Number(item.overall_score).toFixed(2)}</strong></td><td><div class="row">${actions}</div></td></tr>`;
    }).join('') : '<tr><td colspan="5" class="empty">没有符合条件的评测记录。</td></tr>';
  } catch(error) {
    $('evaluationRows').innerHTML = `<tr><td colspan="5" class="bad">${escapeHtml(error.message)}</td></tr>`;
  }
}
async function openEvaluation(id) {
  try {
    const data = await api('/api/evaluations/detail?id=' + encodeURIComponent(id));
    const item = data.evaluation;
    const lines = [
      `问题：${item.question}`, `\n回答：${item.answer}`,
      `\n检索上下文：${item.context || '[无]'}`, `\n总分：${item.overall_score ?? 'N/A'}`
    ];
    for(const [key,value] of Object.entries(item.scores || {})) {
      lines.push(`\n[${evaluationLabels[key] || key}] ${value.score ?? 'N/A'}\n${value.reason || ''}`);
    }
    if((item.issues || []).length) lines.push('\n主要问题：\n- ' + item.issues.join('\n- '));
    if(item.error) lines.push('\n错误：' + item.error);
    $('evaluationDetail').textContent = lines.join('\n');
    $('evaluationDetail').scrollIntoView({behavior:'smooth',block:'nearest'});
  } catch(error) { toast('详情读取失败：' + error.message); }
}
async function retryEvaluation(id) {
  try {
    await api('/api/evaluations/retry',{method:'POST',body:JSON.stringify({id})});
    toast('已重新加入评测队列');
    await loadEvaluationRecords();
  } catch(error) { toast('重试失败：' + error.message); }
}
async function retryFailedEvaluations() {
  const source = $('evaluationSource')?.value || '';
  try {
    const result = await api('/api/evaluations/retry-failed',{method:'POST',body:JSON.stringify({source})});
    toast(`已重新排队 ${Number(result.count || 0)} 条失败记录`);
    await loadEvaluation(true);
  } catch(error) { toast('批量重试失败：' + error.message); }
}
// 群聊总结计划面板：每个群聊独立设置日报、周报、月报和自动发送时间。
"""
