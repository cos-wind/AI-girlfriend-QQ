from __future__ import annotations

PART = r"""  return ({memory:'记忆',qzone:'QQ好友',qzone_target:'QQ动态策略',insights:'群聊总结',modality:'视觉/语音权限',config:'配置'})[source] || source || '未知来源';
}
function userDirectoryCapabilityLabel(capability) {
  return ({like:'自动点赞',comment:'自动评论',vision:'视觉模型',voice:'语音模型',memory:'记忆'})[capability] || capability;
}
function userDirectoryTimeText(value) {
  if(value === null || value === undefined || value === '') return '暂无';
  const raw = Number(value);
  if(Number.isFinite(raw) && raw > 0) {
    const date = new Date((raw > 100000000000 ? raw : raw * 1000));
    if(!Number.isNaN(date.getTime())) return date.toLocaleString();
  }
  return String(value).replace('T',' ').slice(0,19) || '暂无';
}
function userDirectoryBadge(text, kind='') {
  return `<span class="badge ${kind ? escapeHtml(kind) : ''}">${escapeHtml(text)}</span>`;
}
function userDirectoryEntityKey(item) { return item.entity_type === 'group' ? `group:${item.group_id}` : String(item.user_id || ''); }
function userDirectoryMemory(item) {
  const userId = String(item?.user_id || '');
  return (window._memoryItems || []).find(row=>String(row.target?.user_id || '')===userId)
    || (window._memoryItems || []).find(row=>String(row.id || '')===`person:${userId}` || String(row.id || '')===`private:${userId}`)
    || null;
}
function userDirectoryMemoryCardMarkup(item) {
  const memory=userDirectoryMemory(item);
  const relation=item?.relationship || {};
  // The directory endpoint already carries the compact relationship read
  // model.  Render it immediately, then replace the placeholder with the
  // richer memory record when the lazy memory request finishes.
  if(!memory && !Object.keys(relation).length) return '';
  const data=memory || {...relation, messages:item?.message_count || 0};
  const plan=memory?.proactive_plan || {};
  const nextType=proactiveWeightLabels[plan.next_event_type] || plan.next_event_type || (data.proactive_override ? '按计划' : '暂无');
  const nextAt=plan.next_at ? formatProactiveTime(plan.next_at, ((window._proactive||{}).schedule||{}).timezone) : '暂无';
  const counts=data.memory_counts || {};
  const summary=data.summary || (memory ? '暂无可读摘要' : '记忆摘要加载中…');
  const proactive=plan.eligible===false?'未入选':(plan.eligible?'已入选':(data.proactive_override ? '按计划' : '暂无计划'));
  return `<span class="user-directory-inline-memory"><strong>记忆关系与上下文</strong><span class="card-context-values"><span>好感 ${formatScore(data.affection)}</span><span>信任 ${escapeHtml(data.trust_label || data.trust_tier || '观察中')}</span><span>记忆 ${memoryCountText(counts)}</span><span>消息 ${Number(data.messages||item?.message_count||0)}</span></span><span class="card-context-summary">${escapeHtml(summary)}</span><span class="memory-meta">主动互动：${escapeHtml(proactive)} · 下次内容：${escapeHtml(nextType)} · ${escapeHtml(nextAt)}</span></span>`;
}
function userDirectoryFeed(item) {
  const userId = String(item?.user_id || '');
  return (window._qzoneLatestFeeds || []).find(row=>String(row.user_id || '')===userId) || null;
}
async function loadDirectoryQZoneLoginStatus() {
  const target=$('directoryQzoneBridgeAuth');
  if(window._directoryQzoneStatusPromise) return window._directoryQzoneStatusPromise;
  const request=(async()=>{
    try {
      const data=await api('/api/qzone/login-status');
      window._directoryQzoneLoggedIn=Boolean(data.logged_in);
      if(target) {
        target.textContent=data.logged_in ? `QQ 空间已登录${data.qq?' · QQ '+data.qq:''}` : (data.login_running?'正在等待 QQ 空间登录…':(data.reachable?'Bridge 在线但未登录':'QQ 空间 Bridge 未启动'));
        target.className='note '+(data.logged_in?'ok':(data.reachable?'warn':'bad'));
      }
      return data;
    } catch(error) {
      window._directoryQzoneLoggedIn=false;
      if(target) { target.textContent='登录状态读取失败：'+error.message; target.className='note bad'; }
      return {logged_in:false,reachable:false,error:String(error?.message||error)};
    }
  })();
  window._directoryQzoneStatusPromise=request;
  try { return await request; }
  finally { if(window._directoryQzoneStatusPromise===request) window._directoryQzoneStatusPromise=null; }
}
function directoryWithTimeout(promise, timeoutMs=2200) {
  return Promise.race([promise,new Promise((_,reject)=>setTimeout(()=>reject(new Error('timeout')),timeoutMs))]);
}
async function refreshDirectoryQZoneData() {
  // 先读本地群聊总结计划；它不依赖 QQ 空间 Bridge。
  const schedules=await directoryWithTimeout(api('/api/group-summaries/schedules'),1800).catch(()=>({schedules:[]}));
  window._summarySchedules=schedules.schedules||window._summarySchedules||[];
  renderUserDirectory();
  try {
    // 复用首屏已经发出的状态请求，避免同时向 Bridge 发两次 /status。
    const status=await loadDirectoryQZoneLoginStatus();
    window._directoryQzoneLoggedIn=Boolean(status.logged_in);
    // 即使 /status 暂时误报或超时，也尝试读取动态；动态接口本身才是最终登录判据。
    // Bridge 分页通常需要 10–20 秒，因此在后台给足时间，不阻塞用户目录首屏。
    const feeds=await api('/api/qzone/feeds/all?limit=50');
    const freshFeeds=Array.isArray(feeds.feeds) ? feeds.feeds : [];
    if(freshFeeds.length) {
      window._directoryQzoneLoggedIn=true;
      window._qzoneLatestFeeds=freshFeeds;
    } else if(!window._qzoneLatestFeeds) window._qzoneLatestFeeds=[];
    const feedErrors=Array.isArray(feeds.errors) ? feeds.errors.filter(Boolean) : [];
    if(window._userDirectory) window._userDirectory.sourceStatus={...(window._userDirectory.sourceStatus||{}),qzone:freshFeeds.length?(feedErrors.length?'partial':'ready'):(status.logged_in?'partial':'login_required')};
    try { localStorage.setItem('atri.qzone.latestFeeds', JSON.stringify(window._qzoneLatestFeeds)); } catch(error) { /* private mode/storage quota */ }
    window._directoryQzoneFeedError=feedErrors.length ? feedErrors.join('；') : '';
    renderUserDirectory();
  } catch(error) { window._directoryQzoneFeedError=String(error?.message||error); await loadDirectoryQZoneLoginStatus(); renderUserDirectory(); }
}
async function loadDirectoryAutomationState(retry=true) {
  // 这是本地 SQLite 数据，和 Bridge 无关。首屏后台读取即可，不应使用过短
  // 超时把一次有效响应丢掉；同时合并并发调用，避免保存/刷新时覆盖状态。
  if(window._directoryAutomationPromise) return window._directoryAutomationPromise;
  window._directoryAutomationLoading=true;
  window._directoryAutomationError='';
  const request=(async()=>{
    try {
      const data=await api('/api/qzone/automation');
      window._qzoneAutomation={...(window._qzoneAutomation||{}),...data};
      return data;
    } catch(error) {
      window._directoryAutomationError=String(error?.message||error);
      if(retry) setTimeout(()=>loadDirectoryAutomationState(false),3000);
      return null;
    } finally {
      window._directoryAutomationLoading=false;
      renderUserDirectory();
    }
  })();
  window._directoryAutomationPromise=request;
  try { return await request; }
  finally { if(window._directoryAutomationPromise===request) window._directoryAutomationPromise=null; }
}
async function directoryStartQZoneLogin() {
  const target=$('directoryQzoneBridgeAuth');
  if(target) { target.textContent='正在打开 QQ 空间登录页…'; target.className='note warn'; }
  try {
    await api('/api/qzone/login',{method:'POST',body:JSON.stringify({})});
    if(target) target.textContent='登录页已打开，请完成 QQ 空间登录';
    const timer=setInterval(async()=>{ await loadDirectoryQZoneLoginStatus(); const data=await api('/api/qzone/login-status').catch(()=>({})); if(data.logged_in){clearInterval(timer); await loadUserDirectory(true);} },2000);
    setTimeout(()=>clearInterval(timer),300000);
  } catch(error) { if(target) { target.textContent='无法启动登录：'+error.message; target.className='note bad'; } }
}
function renderDirectoryProactiveState() {
  const state=window._proactive||{}; const policy=state.policy||{}; const enabled=state.feature_enabled!==false && policy.enabled!==false;
  if($('directoryProactiveEnabled')) $('directoryProactiveEnabled').checked=enabled;
  if($('directoryProactiveState')) $('directoryProactiveState').textContent=state.feature_enabled===false?'新版主动消息已关闭':(enabled?'主动消息运行中':'主动消息已暂停');
}
async function saveDirectoryProactiveToggle() {
  const enabled=Boolean($('directoryProactiveEnabled')?.checked); const current=JSON.parse(JSON.stringify(window._proactive?.policy||{})); current.enabled=enabled;
  try { await api('/api/config',{method:'POST',body:JSON.stringify({PROACTIVE_V2_ENABLED:enabled})}); await api('/api/proactive/save',{method:'POST',body:JSON.stringify(current)}); window._proactive={...(window._proactive||{}),policy:current,feature_enabled:enabled}; renderDirectoryProactiveState(); toast(enabled?'主动消息已启用':'主动消息已暂停'); }
  catch(error) { toast('主动消息设置保存失败：'+error.message); renderDirectoryProactiveState(); }
}
function userDirectoryInlineFeedMarkup(item) {
  if(window._directoryQzoneLoggedIn===false) return '';
  const feed = userDirectoryFeed(item);
  if(!feed) return `<div class="user-directory-context qzone-context"><h4>QQ 动态</h4><p class="note">尚未读取到该用户的最新动态；QQ 空间登录后将在此处补齐。</p></div>`;
  const userId = String(feed.user_id || item.user_id || '');
  const tid = String(feed.tid || '');
  const policy=qzonePolicy(userId) || {};
  return `<div class="user-directory-context qzone-context"><div class="section-head"><h4>最新 QQ 动态</h4><span class="memory-meta">${escapeHtml(qzoneFeedTimeText(feed))}</span></div><div class="qzone-feed-content">${escapeHtml(feed.content || '[无文字动态]')}</div><p class="memory-meta">点赞 ${Number(feed.like_count||0)} · 评论 ${Number(feed.comment_count||0)} · 图片 ${Number(feed.image_count||0)}</p><div class="qzone-auto-switches"><strong>自动互动</strong><label><input type="checkbox" ${policy.enabled_like?'checked':''} onchange="saveQZonePersonPolicy('${escapeHtml(userId)}','enabled_like',this.checked)">自动点赞</label><label><input type="checkbox" ${policy.enabled_comment?'checked':''} onchange="saveQZonePersonPolicy('${escapeHtml(userId)}','enabled_comment',this.checked)">自动评论</label></div><div class="qzone-manual-actions" data-feed-content="${escapeHtml(feed.content || '[无文字动态]')}"><button class="ghost" onclick="manualLikeQZoneFeed('${escapeHtml(userId)}','${escapeHtml(tid)}',${Number(feed.abstime||0)},this)">点赞这条动态</button><button class="ghost" onclick="generateQZoneCommentFromButton('${escapeHtml(userId)}','${escapeHtml(tid)}',this)">AI生成评论</button><textarea class="qzone-ai-comment" maxlength="200" placeholder="模型生成后可编辑"></textarea><button onclick="publishQZoneGeneratedComment('${escapeHtml(userId)}','${escapeHtml(tid)}',${Number(feed.abstime||0)},this.previousElementSibling)">发表评论</button></div><button class="ghost" onclick="loadUserDirectoryFullQZone(this,'${escapeHtml(userId)}')">在此卡片展开完整空间</button><div class="user-directory-full-qzone"></div></div>`;
}
async function loadUserDirectoryFullQZone(button, userId) {
  const panel=button?.parentElement?.querySelector('.user-directory-full-qzone');
  if(!panel) return;
  if(panel.dataset.loaded==='1') { panel.hidden=!panel.hidden; return; }
  panel.hidden=false; panel.innerHTML='<p class="note">正在读取完整空间动态…</p>';
  try {
    const data=await api(`/api/qzone/feeds?user_id=${encodeURIComponent(userId)}&limit=50`); const feeds=data.feeds||[];
    panel.dataset.loaded='1'; panel.innerHTML=feeds.map(feed=>`<article class="qzone-detail-item"><div class="memory-meta">${escapeHtml(qzoneFeedTimeText(feed))}</div><div class="qzone-feed-content">${escapeHtml(feed.content||'[无文字动态]')}</div><div class="memory-meta">点赞 ${Number(feed.like_count||0)} · 评论 ${Number(feed.comment_count||0)}</div><div class="qzone-manual-actions" data-feed-content="${escapeHtml(feed.content||'[无文字动态]')}"><button class="ghost" onclick="manualLikeQZoneFeed('${escapeHtml(userId)}','${escapeHtml(feed.tid||'')}',${Number(feed.abstime||0)},this)">点赞这条动态</button><button class="ghost" onclick="generateQZoneCommentFromButton('${escapeHtml(userId)}','${escapeHtml(feed.tid||'')}',this)">AI生成评论</button><textarea class="qzone-ai-comment" maxlength="200" placeholder="模型生成后可编辑"></textarea><button onclick="publishQZoneGeneratedComment('${escapeHtml(userId)}','${escapeHtml(feed.tid||'')}',${Number(feed.abstime||0)},this.previousElementSibling)">发表评论</button></div></article>`).join('') || '<p class="note">暂无可见动态。</p>';
  } catch(error) { panel.innerHTML=`<p class="bad">读取完整空间失败：${escapeHtml(error.message)}</p>`; }
}
function directorySummaryControlId(groupId, kind, suffix) {
  return ('directory_summary_' + kind + '_' + groupId + '_' + suffix).replace(/[^a-zA-Z0-9_-]/g,'_');
}
function userDirectoryGroupSummaryCompactMarkup(item) {
  const row=(window._summarySchedules||[]).find(value=>String(value.group_id)===String(item.group_id));
  const relation=item?.relationship||{};
  const counts=relation.memory_counts||{};
  const activity=relation.activity;
  const activityText=(activity===null||activity===undefined||activity==='')?'暂无':formatScore(activity);
  const summary=relation.summary||'暂无可读群聊摘要';
  const state=(key,label)=>`${label} ${Number(row[key+'_enabled']||0)?'已启用':'未启用'}`;
  const next=row ? [row.daily_next_at&&`日报 ${String(row.daily_next_at).replace('T',' ')}`,row.weekly_next_at&&`周报 ${String(row.weekly_next_at).replace('T',' ')}`,row.monthly_next_at&&`月报 ${String(row.monthly_next_at).replace('T',' ')}`].filter(Boolean).join(' · ') || '暂无下次计划' : '总结计划读取中…';
  const plans=row ? `<span class="card-context-values group-summary-plan-values"><span>${state('daily','日报')}</span><span>${state('weekly','周报')}</span><span>${state('monthly','月报')}</span></span>` : '';
  return `<span class="user-directory-inline-memory group-directory-memory"><strong>群聊状态与记忆</strong><span class="card-context-values"><span>活跃度 ${escapeHtml(activityText)} · ${escapeHtml(relation.activity_label||'暂无评级')}</span><span>消息 ${Number(item.message_count||0)}</span><span>记忆 ${escapeHtml(memoryCountText(counts))}</span><span>最近 ${escapeHtml(userDirectoryTimeText(item.last_seen_at))}</span></span><span class="card-context-summary">${escapeHtml(summary)}</span>${plans}<span class="memory-meta">${escapeHtml(next)}</span></span>`;
}
function userDirectoryGroupSummaryMarkup(item) {
  const row=(window._summarySchedules||[]).find(value=>String(value.group_id)===String(item.group_id));
  if(!row) return `<div class="user-directory-context user-directory-group-summary"><h4>群聊总结</h4><p class="note">尚未读取到该群的总结计划，刷新用户中心后会同步。</p></div>`;
  const plan=(kind,label)=>{ const enabled=Boolean(Number(row[kind+'_enabled']||0)); const next=row[kind+'_next_at']||''; return `<div class="summary-plan"><label class="switch-line"><input id="${directorySummaryControlId(item.group_id,kind,'enabled')}" type="checkbox" ${enabled?'checked':''}>${label}</label><input id="${directorySummaryControlId(item.group_id,kind,'next_at')}" type="datetime-local" value="${escapeHtml(next)}"><span class="summary-last-sent">${row[kind+'_last_sent_at']?'上次发送：'+escapeHtml(String(row[kind+'_last_sent_at']).replace('T',' ')):'尚未自动发送'}</span><button class="ghost mini" onclick="generateGroupSummary('${escapeHtml(item.group_id)}','${kind}',true)">立即生成并发送</button></div>`; };
  return `<div class="user-directory-context summary-context user-directory-group-summary"><div class="section-head"><div><h4>群聊总结计划</h4><p class="note">日报、周报、月报均在此卡片中设置。</p></div><div class="row"><button class="ghost" onclick="saveDirectoryGroupSummary(this,'${escapeHtml(item.group_id)}')">保存本群计划</button><button class="ghost" onclick="loadDirectoryGroupSummaries(this,'${escapeHtml(item.group_id)}')">加载近期总结</button></div></div><div class="summary-plan-grid">${plan('daily','日报')}${plan('weekly','周报')}${plan('monthly','月报')}</div><div class="directory-group-summary-history"></div></div>`;
}
async function loadDirectoryGroupSummaries(button, groupId) {
  const panel=button?.closest('.user-directory-group-summary')?.querySelector('.directory-group-summary-history');
  if(!panel) return;
  panel.innerHTML='<p class="note">正在读取近期总结…</p>';
  try {
    const data=await api('/api/group-summaries?group_id='+encodeURIComponent(groupId)+'&limit=20'); const items=data.items||[];
    panel.innerHTML=items.length ? items.map(item=>`<article class="summary-detail-item"><div class="entry-head"><strong>${escapeHtml(item.title||'群聊总结')}</strong><span class="badge ${item.status==='completed'?'active':(item.status==='failed'?'red':'warn')}" >${escapeHtml(item.status||'')}</span></div><p class="note">${escapeHtml(item.period_label||'')} · ${escapeHtml(String(item.created_at||'').replace('T',' '))} · ${Number(item.message_count||0)} 条消息</p><div class="summary-detail-content">${escapeHtml(item.content||item.error||'报告正在生成…')}</div></article>`).join('') : '<p class="note">本群暂无已生成总结。</p>';
  } catch(error) { panel.innerHTML='<p class="bad">读取群聊总结失败：'+escapeHtml(error.message)+'</p>'; }
}
async function saveDirectoryGroupSummary(button, groupId) {
  if(typeof button === 'string') { groupId=button; button=null; }
  return withButtonBusy(button, ()=>saveDirectoryGroupSummaryCore(groupId), '保存中…');
}
async function saveDirectoryGroupSummaryCore(groupId) {
  const plan=kind=>({enabled:Boolean($(directorySummaryControlId(groupId,kind,'enabled'))?.checked),next_at:$(directorySummaryControlId(groupId,kind,'next_at'))?.value||''});
  try { await api('/api/group-summaries/schedules',{method:'POST',body:JSON.stringify({group_id:String(groupId),daily:plan('daily'),weekly:plan('weekly'),monthly:plan('monthly')})}); toast('群聊总结计划已保存'); const data=await api('/api/group-summaries/schedules'); window._summarySchedules=data.schedules||[]; renderUserDirectory(); }
  catch(error) { toast('群聊总结计划保存失败：'+error.message); }
}
function userDirectoryAtriPublisherMarkup() {
  if(!window._qzoneAutomation) {
    const error=String(window._directoryAutomationError||'');
    return `<div class="user-directory-context proactive-context atri-directory-publisher"><div class="section-head"><h4>亚托莉专属：自动发布动态</h4><span class="badge ${error?'red':'warn'}">${error?'读取失败':'读取中'}</span></div><p class="note">${error?'自动发布配置读取失败：'+escapeHtml(error):'正在读取已保存的发布设置、下一条动态和历史记录…'}</p>${error?'<button class="ghost" onclick="loadDirectoryAutomationState(false)">重新读取</button>':''}</div>`;
  }
  const settings = window._qzoneAutomation?.settings || {};
  const next = window._qzoneAutomation?.next_post || {};
  const item = next.item || {};
  const pool=Array.isArray(window._qzoneAutomation?.content_pool) ? window._qzoneAutomation.content_pool : [];
  const visiblePool=pool.filter(row=>row && row.content).slice(0,8);
  const poolStatus=(status)=>status==='published'?'已发布':(status==='rejected'?'未发布 · 已拒绝':(status==='failed'?'未发布 · 失败':(status==='pending'?'未发布 · 待发布':'未发布')));
  const poolStatusClass=(status)=>status==='published'?'active':(status==='rejected'||status==='failed'?'red':'warn');
  const poolMarkup=visiblePool.length ? `<div class="atri-pool">${visiblePool.map(row=>`<article class="atri-pool-item"><div class="pool-head"><span class="badge ${poolStatusClass(row.status)}">${poolStatus(row.status)}</span><span class="memory-meta">${row.published_at?qzoneDate(row.published_at):(row.scheduled_at?'计划 '+qzoneDate(row.scheduled_at):'')}</span></div><div class="pool-content">${escapeHtml(row.content)}</div>${row.last_error?`<div class="memory-meta">原因：${escapeHtml(row.last_error)}</div>`:''}</article>`).join('')}</div>` : '<div class="memory-meta">暂无内容池记录。</div>';
  const commentPool=Array.isArray(window._qzoneAutomation?.comment_pool) ? window._qzoneAutomation.comment_pool.filter(row=>row && row.content).slice(0,6) : [];
  const commentPoolMarkup=commentPool.length ? `<div class="atri-pool">${commentPool.map(row=>`<article class="atri-pool-item"><div class="pool-head"><span class="badge ${poolStatusClass(row.status)}">${poolStatus(row.status)}</span><span class="memory-meta">${row.generated_at?qzoneDate(row.generated_at):''}</span></div><div class="pool-content">${escapeHtml(row.content)}</div></article>`).join('')}</div>` : '<div class="memory-meta">暂无评论池内容；评论会根据动态列表由模型生成。</div>';
  const postLogs=(window._qzoneAutomation?.logs||[]).filter(row=>row.action==='post').slice(0,5);
  const logMarkup=postLogs.length ? `<div class="atri-pool">${postLogs.map(row=>`<article class="atri-pool-item"><div class="pool-head"><span class="badge ${row.status==='success'?'active':'red'}">${row.status==='success'?'发布成功':'发布失败'}</span><span class="memory-meta">${qzoneDate(row.created_at)}</span></div><div class="pool-content">${escapeHtml(row.content||row.error||'无正文')}</div></article>`).join('')}</div>` : '<div class="memory-meta">暂无发布日志。</div>';
  const nextContent=item.content || (next.auto_generate?'到达计划时间后由模型生成正文并发布':'暂无待发布动态');
  return `<div class="user-directory-context proactive-context atri-directory-publisher"><div class="section-head"><div><h4>亚托莉专属：自动发布动态</h4><p class="note">发布配置、下一条内容、内容池和发布记录均在此卡片内。</p></div><span class="badge ${settings.post_enabled?'active':'warn'}">${settings.post_enabled?'已启用':'已暂停'}</span></div><div class="qzone-next-post"><div class="memory-meta">下一条：${next.scheduled_at?qzoneDate(next.scheduled_at):'尚未排期'}</div><div class="qzone-next-post-content">${escapeHtml(nextContent)}</div><div class="memory-meta">${next.auto_generate?'到点自动生成':'已准备正文'} · ${settings.post_model_profile_id?escapeHtml(settings.post_model_profile_id):'当前聊天模型'}</div></div><div class="qzone-auto-switches"><strong>自动互动</strong><label><input id="directoryQzoneLikeEnabled" type="checkbox" ${settings.like_enabled?'checked':''}>自动点赞</label><label><input id="directoryQzoneCommentEnabled" type="checkbox" ${settings.comment_enabled?'checked':''}>自动评论</label><span class="memory-meta">保存后生效</span></div><div class="card-context-values"><span>今日发布：${Number(window._qzoneAutomation?.today?.post||0)}</span><span>今日点赞：${Number(window._qzoneAutomation?.today?.like||0)}</span><span>今日评论：${Number(window._qzoneAutomation?.today?.comment||0)}</span></div><details open><summary>内容池（${visiblePool.length} 条）</summary>${poolMarkup}</details><details><summary>评论池（${commentPool.length} 条）</summary>${commentPoolMarkup}</details><details open><summary>已发布记录（${postLogs.length} 条）</summary>${logMarkup}</details><div class="form-grid qzone-form-grid"><label class="switch-line"><input id="directoryQzonePostEnabled" type="checkbox" ${settings.post_enabled?'checked':''}>启用自动发布</label><label>每几天发布<input id="directoryQzonePeriodDays" type="number" min="1" max="31" value="${Number(settings.period_days||1)}"></label><label>每周期最多几条<input id="directoryQzonePostsPerPeriod" type="number" min="1" max="20" value="${Number(settings.posts_per_period||2)}"></label><label>开始时间<input id="directoryQzoneStartHour" type="number" min="0" max="23" value="${Number.isFinite(Number(settings.post_start_hour))?Number(settings.post_start_hour):9}"></label><label>结束时间<input id="directoryQzoneEndHour" type="number" min="1" max="24" value="${Number.isFinite(Number(settings.post_end_hour))?Number(settings.post_end_hour):23}"></label></div><label class="switch-line"><input id="directoryQzonePostAutoGenerate" type="checkbox" ${settings.post_auto_generate?'checked':''}>到点由模型生成正文并发布</label><textarea id="directoryQzonePostPrompt" class="qzone-comment" maxlength="2000" placeholder="生活趣事、思考感悟、原作剧情、热点观点等主题会按日期轮换">${escapeHtml(settings.post_prompt || '根据当前记忆和情绪，写一条自然、简短、带一点亚托莉口吻的 QQ 空间动态。')}</textarea><div class="row"><button onclick="saveDirectoryAtriPublisher(this)">保存发布设置</button><button class="ghost" onclick="publishDirectoryAtriPost(this)">立即生成并发布</button></div></div>`;
}
function userDirectoryDetailMarkup(item) {
  if(item.entity_type === 'group') {
    return `<div class="user-directory-inline-detail">${userDirectoryGroupSummaryMarkup(item)}</div>`;
  }
  const roles = item.roles || [];
  const modalityPolicy = window._modalityAccess?.policy?.users?.[String(item.user_id)] || {};
  const memory = userDirectoryMemory(item);
  const atriMarkup = roles.includes('bot') ? userDirectoryAtriPublisherMarkup() : '';
  const modalityMarkup = roles.includes('bot') ? '' : `<div class="row"><label class="switch-line"><input class="user-directory-vision" type="checkbox" ${modalityPolicy.vision?'checked':''}>视觉模型</label><label class="switch-line"><input class="user-directory-voice" type="checkbox" ${modalityPolicy.voice?'checked':''}>语音模型</label><button class="ghost" onclick="saveUserDirectoryModality(this,'user:${escapeHtml(item.user_id)}')">保存权限</button></div>`;
  const memoryAction = memory ? `<div class="row"><button class="ghost" onclick="openMemory('${escapeHtml(memory.id)}')">编辑记忆</button></div>` : '';
  return `<div class="user-directory-inline-detail">${memoryAction}${modalityMarkup}${userDirectoryInlineFeedMarkup(item)}${atriMarkup}</div>`;
}
function renderUserDirectory() {
  const state = window._userDirectory || {items:[],groups:[]};
  const query = String($('userDirectorySearch')?.value || '').trim().toLowerCase();
  const source = String($('userDirectorySource')?.value || '');
  const entityType = String($('userDirectoryEntityType')?.value || 'all');
  const matches = item => {
    const haystack = [item.user_id,item.group_id,item.canonical_name,...(item.aliases||[]),...(item.sources||[]),...(item.contexts||[])].join(' ').toLowerCase();
    return (!query || haystack.includes(query)) && (!source || (item.sources||[]).includes(source));
  };
  const users = entityType === 'group' ? [] : (state.items || []).filter(matches);
  const groups = entityType === 'user' ? [] : (state.groups || []).filter(matches);
  // 保留亚托莉与主人两个置顶卡片的原有顺序，其余用户按好感度降序排列。
  // 好感度来自统一用户目录的 relationship，兼容旧接口直接返回 affection 的情况。
  const affectionOf = item => {
    const relationship = item.relationship || {};
    const value = relationship.affection ?? relationship.affection_score ?? item.affection ?? item.affection_score;
    const score = Number(value);
    return Number.isFinite(score) ? score : -Infinity;
  };
  const sortedUsers = users.map((item, index) => ({item, index})).sort((left, right) => {
    const a = left.item;
    const b = right.item;
    const aPin = Number.isFinite(Number(a.pin_order)) ? Number(a.pin_order) : (a.roles?.includes('bot') ? 0 : (a.roles?.includes('owner') ? 1 : 2));
    const bPin = Number.isFinite(Number(b.pin_order)) ? Number(b.pin_order) : (b.roles?.includes('bot') ? 0 : (b.roles?.includes('owner') ? 1 : 2));
    if(aPin < 2 || bPin < 2) return aPin - bPin || left.index - right.index;
    return affectionOf(b) - affectionOf(a)
      || Number(b.message_count || 0) - Number(a.message_count || 0)
      || left.index - right.index;
  }).map(entry => entry.item);
  const card = item => {
    const key = userDirectoryEntityKey(item); const selected = (state.selectedIds || []).includes(key);
    const isGroup = item.entity_type === 'group'; const roles = item.roles || [];
    const roleLabel = roles.includes('bot') ? '机器人' : (roles.includes('owner') ? '所有者' : '');
    const special = roles.includes('bot') ? userDirectoryBadge('自动发布','active') : '';
    const title = isGroup ? `群聊 · ${item.canonical_name}` : item.canonical_name;
    const rowClass = `${isGroup?'group-row':''} ${roles.includes('bot')?'bot-row':''} ${roles.includes('owner')?'owner-row':''}`;
    // 亚托莉不是普通用户档案：主卡只显示运行身份、消息和最近活动，
    // 专属发布/互动能力在展开详情中呈现。
    const cardContext = isGroup ? userDirectoryGroupSummaryCompactMarkup(item) : (roles.includes('bot') ? '' : userDirectoryMemoryCardMarkup(item));
    const activity=item.last_seen_at || (roles.includes('bot') ? userDirectoryFeed(item)?.abstime : '');
    return `<div class="user-directory-entry"><button type="button" class="user-directory-row ${selected?'selected':''} ${rowClass}" onclick="selectUserDirectoryUser('${escapeHtml(key)}')"><strong>${escapeHtml(title)} ${roleLabel?userDirectoryBadge(roleLabel,'active'):''} ${special}</strong><span class="memory-meta">${isGroup?'群号 '+escapeHtml(item.group_id):'QQ '+escapeHtml(item.user_id)} · ${Number(item.message_count||0)} 条消息${activity ? ' · 最近 '+escapeHtml(userDirectoryTimeText(activity)) : ''}</span>${cardContext}</button>${selected ? userDirectoryDetailMarkup(item) : ''}</div>`;
  };
  const target = $('userDirectoryRows');
  if(!target) return;
  const html = [sortedUsers.length ? `<div class="user-directory-section-title">用户（${sortedUsers.length}）</div>${sortedUsers.map(card).join('')}` : '', groups.length ? `<div class="user-directory-section-title">群聊（${groups.length}）</div>${groups.map(card).join('')}` : ''].join('');
  target.innerHTML = html || '<div class="empty">没有匹配的用户或群聊。</div>';
  const status = state.sourceStatus || {};
  const qzoneStatus = status.qzone || '未刷新';
  const qzoneDetail = window._directoryQzoneFeedError ? `（${window._directoryQzoneFeedError.slice(0,120)}）` : '';
   if($('userDirectoryStatus')) $('userDirectoryStatus').textContent = `用户 ${users.length}/${Number(state.total || state.items?.length || 0)} · 群聊 ${groups.length}/${Number(state.groupTotal || state.groups?.length || 0)} · 记忆 ${status.memory || '—'} · 摘要 ${status.insights || '—'} · QQ好友 ${qzoneStatus}${qzoneDetail}`;
}
function userDirectoryOpenTab(id) {
  const button = Array.from(document.querySelectorAll('.tab')).find(item => item.getAttribute('onclick') === `showTab(event,'${id}')`);
  if(button) button.click();
}
async function selectUserDirectoryUser(userId, forceOpen=false) {
  const state = window._userDirectory || {};
  const key = String(userId || '');
  state.selectedIds = Array.isArray(state.selectedIds) ? state.selectedIds : [];
  const index = state.selectedIds.indexOf(key);
  if(forceOpen) { if(index < 0) state.selectedIds.push(key); }
  else if(index >= 0) state.selectedIds.splice(index, 1);
  else state.selectedIds.push(key);
  renderUserDirectory();
}
async function saveUserDirectoryModality(button, entityKey) {
  return withButtonBusy(button, ()=>saveUserDirectoryModalityCore(button, entityKey), '保存中…');
}
async function saveUserDirectoryModalityCore(button, entityKey) {
  const key = String(entityKey || '').trim();
  const isGroup = key.startsWith('group:');
  const id = key.replace(/^(user:|group:)/, '');
  if(!/^\d+$/.test(id)) return toast('对象编号无效');
  try {
    const data = window._modalityAccess || await api('/api/modality-access');
    const policy = JSON.parse(JSON.stringify(data.policy || {version:1,vision_allowlist_enabled:false,voice_allowlist_enabled:false,users:{}}));
    const container = button?.closest('.user-directory-inline-detail');
    const vision = Boolean(container?.querySelector('.user-directory-vision')?.checked);
    const voice = Boolean(container?.querySelector('.user-directory-voice')?.checked);
    if(isGroup) {
      policy.groups = policy.groups || {};
      const current = policy.groups[id] || {};
      const item = (window._userDirectory?.groups || []).find(row=>String(row.group_id)===id);
      policy.groups[id] = {name:String(current.name || item?.canonical_name || id), vision, voice};
    } else {
      policy.users = policy.users || {};
      const current = policy.users[id] || {};
      const item = (window._userDirectory?.items || []).find(row=>String(row.user_id)===id);
      policy.users[id] = {name:String(current.name || item?.canonical_name || id), vision, voice};
    }
    const result = await api('/api/modality-access',{method:'POST',body:JSON.stringify(policy)});
    window._modalityAccess = {...data, policy:result.policy};
    await loadUserDirectory(false);
    await selectUserDirectoryUser(`${isGroup?'group':'user'}:${id}`, true);
    toast(`${isGroup?'群聊':'用户'}视觉 / 语音权限已保存`);
  } catch(error) { toast('权限保存失败：'+error.message); }
}
async function loadUserDirectory(syncQZone=false) {
  const target = $('userDirectoryRows');
  if(target && !window._userDirectory?.items?.length) {
    // 上一次成功读取的核心目录先用于首屏，网络慢时不再让整个用户中心空白。
    try {
      const cached=JSON.parse(localStorage.getItem('atri.userDirectory.core') || 'null');
      if(cached?.items?.length || cached?.groups?.length) {
        window._userDirectory={...cached, selectedIds:[]};
        renderUserDirectory();
      } else target.innerHTML = '<div class="empty">正在读取...</div>';
    } catch(error) { target.innerHTML = '<div class="empty">正在读取...</div>'; }
  }
  if(!window._qzoneLatestFeeds?.length) {
    try {
      const cachedFeeds=JSON.parse(localStorage.getItem('atri.qzone.latestFeeds') || '[]');
      if(Array.isArray(cachedFeeds) && cachedFeeds.length) window._qzoneLatestFeeds=cachedFeeds;
    } catch(error) { /* private mode/storage quota */ }
  }
  try {
    loadDirectoryQZoneLoginStatus();
    const data = await api('/api/users?limit=1000');
    const previousQzoneStatus=window._userDirectory?.sourceStatus?.qzone;
    const sourceStatus={...(data.source_status||{})};
    if(['ready','partial'].includes(previousQzoneStatus) && sourceStatus.qzone==='not_refreshed') sourceStatus.qzone=previousQzoneStatus;
    window._userDirectory = {items:data.items || [], groups:data.groups || [], total:Number(data.total||0), groupTotal:Number(data.group_total||data.groups?.length||0), selectedIds:Array.isArray(window._userDirectory?.selectedIds) ? window._userDirectory.selectedIds : [], sourceStatus};
    try { localStorage.setItem('atri.userDirectory.core', JSON.stringify(window._userDirectory)); } catch(error) { /* private mode/storage quota */ }
    if(syncQZone) {
      await refreshDirectoryQZoneData();
    }
    renderUserDirectory();
  } catch(error) {
    if($('userDirectoryStatus')) $('userDirectoryStatus').textContent = '用户目录读取失败：' + error.message;
    if(target) target.innerHTML = `<div class="empty">读取失败：${escapeHtml(error.message)}</div>`;
  }
}
async function runUserDirectoryRefresh(button) {
  await withButtonBusy(button, async()=>{ await loadUserDirectory(true); toast('用户目录已刷新'); }, '刷新中…');
}
function openUserInDirectory(userId) {
"""
