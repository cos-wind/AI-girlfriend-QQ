from __future__ import annotations

PART = r"""  userDirectoryOpenTab('users');
  setTimeout(()=>selectUserDirectoryUser(String(userId || '').replace(/^person:/,''), true), 80);
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

function qzoneDate(value) {
  if(!value) return '—';
  const date = new Date(Number(value) * 1000);
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString();
}
function qzoneSettingValue(key, fallback) {
  const settings = window._qzoneAutomation?.settings || {};
  return settings[key] ?? fallback;
}
function syncQZoneModelSelectors() {
  const profiles=Array.isArray(window._qzoneChatProfiles) ? window._qzoneChatProfiles : [];
  if(!profiles.length) return;
  const options='<option value="">当前聊天模型</option>' + profiles.map(item=>`<option value="${escapeHtml(item.id)}">${escapeHtml(item.name || item.model)} · ${escapeHtml(item.model)}</option>`).join('');
  ['qzoneModelProfile','directoryQzoneModelProfile','qzoneGlobalModelProfile'].forEach(id=>{
    const select=$(id);
    if(!select) return;
    const preferred=select.value || window._qzoneAutomation?.settings?.post_model_profile_id || '';
    select.innerHTML=options;
    if(profiles.some(item=>String(item.id)===String(preferred))) select.value=preferred;
  });
}
function installQZoneModelSelectorSync() {
  if(typeof renderUserDirectory==='function' && !renderUserDirectory.__qzoneModelSync) {
    const baseRenderUserDirectory=renderUserDirectory;
    const wrappedRenderUserDirectory=function(...args) { const result=baseRenderUserDirectory(...args); syncQZoneModelSelectors(); return result; };
    wrappedRenderUserDirectory.__qzoneModelSync=true;
    renderUserDirectory=wrappedRenderUserDirectory;
  }
  if(typeof renderQZoneBrowserFeeds==='function' && !renderQZoneBrowserFeeds.__qzoneModelSync) {
    const baseRenderQZoneBrowserFeeds=renderQZoneBrowserFeeds;
    const wrappedRenderQZoneBrowserFeeds=function(...args) { const result=baseRenderQZoneBrowserFeeds(...args); syncQZoneModelSelectors(); return result; };
    wrappedRenderQZoneBrowserFeeds.__qzoneModelSync=true;
    renderQZoneBrowserFeeds=wrappedRenderQZoneBrowserFeeds;
  }
}
function renderQZoneAutomation() {
  const data = window._qzoneAutomation || {};
  const settings = data.settings || {};
  const next = settings.next_post_at ? ` · 下次发布 ${qzoneDate(settings.next_post_at)}` : '';
  $('qzoneAutoMeta').textContent = `${data.running?'自动任务在线':'自动任务已暂停'} · ${settings.enabled?'总控开启':'总控关闭'} · ${settings.post_enabled?'自动发布开启':'自动发布关闭'}${next}`;
  renderQZoneBrowserFeeds(window._qzoneLatestFeeds || []);
}
function qzoneFeedTimeText(feed) {
  if(feed.time_text) return String(feed.time_text);
  return feed.abstime ? qzoneDate(feed.abstime) : '时间未知';
}
function qzonePolicy(userId) { return (window._qzoneAutomation?.targets || []).find(item=>String(item.user_id)===String(userId)) || null; }
function renderQZoneBrowserFeeds(feeds, updateLatest=true) {
  if(updateLatest) window._qzoneLatestFeeds = feeds || [];
  const visible = feeds || [];
  $('qzoneFeedCount').textContent = `${visible.length} 人`;
  const botId = String(window._qzoneAutomation?.bot_qq || '100000001');
  $('qzoneBrowserFeeds').innerHTML = visible.map(feed=>{
    const identity=(window._userDirectory?.items||[]).find(item=>String(item.user_id)===String(feed.user_id)) || {}; const displayAuthor=identity.canonical_name || feed.author || ('QQ '+feed.user_id); const policy=qzonePolicy(feed.user_id); const isAtri=String(feed.user_id)===botId;
    const nextPost=window._qzoneAutomation?.next_post||{}; const nextItem=nextPost.item||null;
    const detailId=`qzoneDetail-${String(feed.user_id||'').replace(/[^0-9]/g,'')}`;
    return `<article class="qzone-person-row ${feed.pinned?'pinned':''}" data-user-id="${escapeHtml(feed.user_id||'')}">
      <div class="qzone-person-head"><div><div class="qzone-person-name"><strong>${escapeHtml(displayAuthor)}</strong>${feed.pinned?`<span class="badge active">${escapeHtml(feed.pin_label||'置顶')}</span>`:''}</div><div class="memory-meta">最新动态 · ${escapeHtml(qzoneFeedTimeText(feed))} · QQ ${escapeHtml(feed.user_id||'')}</div></div><div class="row" style="margin-top:0"><button class="ghost" onclick="openUserInDirectory('${escapeHtml(feed.user_id||'')}')">用户中心</button><button class="ghost" onclick="openQZonePersonDetail('${escapeHtml(feed.user_id||'')}','${escapeHtml(displayAuthor)}')">详细</button></div></div>
      <div class="qzone-feed-content">${escapeHtml(feed.content || '[无文字动态]')}</div>
      <div class="memory-meta">图片 ${Number(feed.image_count||0)} · 点赞 ${Number(feed.like_count||0)} · 评论 ${Number(feed.comment_count||0)}</div>
      <div class="qzone-person-switches"><label><input type="checkbox" ${policy?.enabled_like===1?'checked':''} onchange="saveQZonePersonPolicy('${escapeHtml(feed.user_id||'')}','enabled_like',this.checked)">自动点赞</label><label><input type="checkbox" ${policy?.enabled_comment===1?'checked':''} onchange="saveQZonePersonPolicy('${escapeHtml(feed.user_id||'')}','enabled_comment',this.checked)">自动评论</label></div>
      <div class="qzone-manual-actions" data-feed-content="${escapeHtml(feed.content || '[无文字动态]')}"><button class="ghost" onclick="manualLikeQZoneFeed('${escapeHtml(feed.user_id||'')}','${escapeHtml(feed.tid||'')}',${Number(feed.abstime||0)},this)">点赞这条动态</button><button class="ghost" onclick="generateQZoneCommentFromButton('${escapeHtml(feed.user_id||'')}','${escapeHtml(feed.tid||'')}',this)">AI生成评论</button><textarea class="qzone-ai-comment" maxlength="200" placeholder="点击“AI生成评论”，生成后可编辑"></textarea><button onclick="publishQZoneGeneratedComment('${escapeHtml(feed.user_id||'')}','${escapeHtml(feed.tid||'')}',${Number(feed.abstime||0)},this.previousElementSibling)">发表生成评论</button></div>
      ${isAtri?`<div class="qzone-atri-publisher" id="qzoneAtriPublisher"><strong>亚托莉自动发布</strong><div class="qzone-next-post"><div class="memory-meta">未来发布 · ${nextPost.scheduled_at?qzoneDate(nextPost.scheduled_at):'尚未排期'}</div><div class="qzone-next-post-content">${escapeHtml(nextItem?.content || (nextPost.auto_generate?'保存设置后将由模型生成下一条动态':'暂无待发布动态'))}</div>${nextItem?`<div class="memory-meta">来源：${nextItem.generated_at?'模型预生成':'动态内容'} · 状态：待发布</div>`:''}</div><div class="form-grid qzone-form-grid"><label class="switch-line"><input id="qzonePostEnabled" type="checkbox">启用自动发布</label><label>每几天发布<input id="qzonePeriodDays" type="number" min="1" max="31" step="1" value="1"></label><label>每周期最多几条<input id="qzonePostsPerPeriod" type="number" min="1" max="20" step="1" value="2"></label><label>开始时间（小时）<input id="qzoneStartHour" type="number" min="0" max="23" step="1" value="9"></label><label>结束时间（小时）<input id="qzoneEndHour" type="number" min="1" max="24" step="1" value="23"></label><label>生成模型<select id="qzoneModelProfile"><option value="">当前聊天模型</option></select></label></div><label class="switch-line"><input id="qzonePostAutoGenerate" type="checkbox">到点自动生成正文并发布</label><textarea id="qzonePostPrompt" class="qzone-comment" maxlength="2000" placeholder="生活趣事、思考感悟、原作剧情、热点观点等主题会按日期轮换">根据当前记忆和情绪，写一条自然、简短、带一点亚托莉口吻的 QQ 空间动态。</textarea><div class="row"><button onclick="saveQZoneAutomationSettings()">保存发布设置</button><button class="ghost" onclick="publishGeneratedQZonePost()">立即生成并发布</button><span class="note" id="qzonePostGenerateMeta"></span></div></div>`:''}
      <div class="qzone-inline-detail" id="${detailId}" hidden></div>
    </article>`;
  }).join('') || '<div class="empty">没有读取到动态，请刷新 Bridge 会话后重试。</div>';
}
function filterQZoneFriends() {
  const search = ($('qzoneFriendSearch')?.value || '').trim().toLowerCase();
  const directory = window._userDirectory?.items || [];
  const feeds = (window._qzoneLatestFeeds || []).filter(item => {
    const identity = directory.find(user=>String(user.user_id)===String(item.user_id)) || {};
    const haystack = [item.user_id,item.author||'',identity.canonical_name||'',...(identity.aliases||[])].join(' ').toLowerCase();
    return !search || haystack.includes(search);
  });
  renderQZoneBrowserFeeds(feeds, false);
}
async function loadQZoneBrowserFeeds() {
  $('qzoneBrowserFeeds').innerHTML = '<div class="empty">正在读取动态...</div>';
  try {
    if(!window._userDirectory?.items?.length) await loadUserDirectory(false);
    const data = await api('/api/qzone/feeds/all?limit=50');
    $('qzoneFeedConnection').textContent = data.errors?.length ? `部分好友读取失败：${data.errors.length} 个` : '动态读取完成，可按用户单独开启自动互动。';
    renderQZoneBrowserFeeds(data.feeds || []);
  } catch(error) { $('qzoneFeedConnection').textContent = `动态读取失败：${error.message}`; renderQZoneBrowserFeeds([]); }
}
async function loadQZoneLoginStatus() {
  const target = $('qzoneBridgeAuth');
  if(!target) return;
  try {
    const data = await api('/api/qzone/login-status');
    if(data.logged_in) {
      target.textContent = `QQ 空间已登录${data.qq ? ' · QQ ' + data.qq : ''}`;
      target.className = 'note ok';
    } else if(data.login_running) {
      target.textContent = '正在等待 QQ 空间登录...';
      target.className = 'note warn';
    } else if(data.reachable) {
      target.textContent = 'Bridge 在线但未登录，请点击“登录 QQ 空间”';
      target.className = 'note warn';
    } else {
      target.textContent = 'QQ 空间 Bridge 未启动';
      target.className = 'note bad';
    }
  } catch(error) {
    target.textContent = '登录状态读取失败：' + error.message;
    target.className = 'note bad';
  }
}
async function startQZoneLogin() {
  const target = $('qzoneBridgeAuth');
  if(target) { target.textContent = '正在打开 QQ 空间登录页...'; target.className = 'note warn'; }
  try {
    await api('/api/qzone/login', {method:'POST', body:JSON.stringify({})});
    if(target) target.textContent = '登录页已打开，请完成 QQ 空间登录';
    const timer = setInterval(async () => {
      await loadQZoneLoginStatus();
      const data = await api('/api/qzone/login-status').catch(() => ({}));
      if(data.logged_in) { clearInterval(timer); await loadQZoneBrowserFeeds(); }
    }, 2000);
    setTimeout(() => clearInterval(timer), 300000);
  } catch(error) {
    if(target) { target.textContent = '无法启动登录：' + error.message; target.className = 'note bad'; }
  }
}
async function openQZonePersonDetail(userId, name='') {
  const detailId=`qzoneDetail-${String(userId||'').replace(/[^0-9]/g,'')}`; const panel=$(detailId); if(!panel) return;
  if(!panel.hidden && panel.dataset.loaded==='1'){ panel.hidden=true; return; }
  panel.hidden=false; panel.dataset.loaded='0'; panel.innerHTML=`<div class="section-head"><div><h3>${escapeHtml(name||('QQ '+userId))} 的完整空间</h3><p class="note">正在读取全部动态…</p></div><button class="ghost" onclick="$('${detailId}').hidden=true">收起</button></div>`;
  try { const data=await api(`/api/qzone/feeds?user_id=${encodeURIComponent(userId)}&limit=50`); const feeds=data.feeds||[]; panel.dataset.loaded='1'; panel.innerHTML=`<div class="section-head"><div><h3>${escapeHtml(name||('QQ '+userId))} 的完整空间</h3><p class="note">共 ${feeds.length} 条可见动态</p></div><button class="ghost" onclick="$('${detailId}').hidden=true">收起</button></div><div class="qzone-detail-list">${feeds.map(feed=>`<article class="qzone-detail-item"><div class="memory-meta">${escapeHtml(qzoneFeedTimeText(feed))} · tid ${escapeHtml(feed.tid||'')}</div><div class="qzone-feed-content">${escapeHtml(feed.content||'[无文字动态]')}</div><div class="memory-meta">图片 ${Number(feed.image_count||0)} · 点赞 ${Number(feed.like_count||0)} · 评论 ${Number(feed.comment_count||0)}</div><div class="qzone-manual-actions" data-feed-content="${escapeHtml(feed.content || '[无文字动态]')}"><button class="ghost" onclick="manualLikeQZoneFeed('${escapeHtml(feed.user_id||userId)}','${escapeHtml(feed.tid||'')}',${Number(feed.abstime||0)},this)">点赞这条动态</button><button class="ghost" onclick="generateQZoneCommentFromButton('${escapeHtml(feed.user_id||userId)}','${escapeHtml(feed.tid||'')}',this)">AI生成评论</button><textarea class="qzone-ai-comment" maxlength="200" placeholder="点击“AI生成评论”，生成后可编辑"></textarea><button onclick="publishQZoneGeneratedComment('${escapeHtml(feed.user_id||userId)}','${escapeHtml(feed.tid||'')}',${Number(feed.abstime||0)},this.previousElementSibling)">发表生成评论</button></div></article>`).join('')||'<div class="empty">这个空间暂无可见动态。</div>'}</div>`; } catch(error) { panel.innerHTML=`<div class="bad">读取完整空间失败：${escapeHtml(error.message)}</div>`; }
}
async function manualLikeQZoneFeed(userId, tid, abstime, button) {
  if(!userId || !tid) return toast('这条动态缺少标识');
  button.disabled=true;
  try { await api('/api/qzone/like',{method:'POST',body:JSON.stringify({user_id:userId,tid,abstime:Number(abstime||0)})}); button.textContent='已点赞'; toast('点赞成功'); }
  catch(error) { button.disabled=false; toast('点赞失败：'+error.message); }
}
async function generateQZoneCommentFromButton(userId, tid, button) {
  const actions = button?.closest('.qzone-manual-actions');
  const input = actions?.querySelector('.qzone-ai-comment');
  if(!actions || !input) return toast('找不到评论编辑框');
  const feedContent = String(actions.dataset.feedContent || '').trim();
  if(!feedContent) return toast('这条动态没有可供模型参考的正文');
  const previous = button.textContent;
  button.disabled = true; button.textContent = '生成中…'; input.value = '正在请亚托莉生成评论…';
  try {
    const profileId = $('qzoneModelProfile')?.value || window._qzoneAutomation?.settings?.post_model_profile_id || '';
    const result = await api('/api/qzone/automation/generate', {method:'POST', body:JSON.stringify({
      kind:'comment', profile_id:profileId,
      prompt:`请根据下面这条 QQ 空间动态，以亚托莉的口吻生成一条自然、简短、真诚、可直接发表的评论。不要复述动态原文，不要解释生成过程，只输出评论正文（不超过80字）。
动态作者：${userId}
动态内容：${feedContent}`
    })});
    const content = String(result.content || result.text || '').trim();
    if(!content) throw new Error('模型没有返回评论内容');
    input.value = content; input.focus(); toast('AI评论已生成，可编辑后发表');
  } catch(error) { input.value = ''; toast('AI评论生成失败：' + error.message); }
  finally { button.disabled = false; button.textContent = previous; }
}
async function publishQZoneGeneratedComment(userId, tid, abstime, input) {
  const button=input?.closest('.qzone-manual-actions')?.querySelector('button:last-child');
  return withButtonBusy(button, ()=>publishQZoneGeneratedCommentCore(userId, tid, abstime, input), '发表中…');
}
async function publishQZoneGeneratedCommentCore(userId, tid, abstime, input) {
  const content=(input?.value||'').trim(); if(!content || content === '正在请亚托莉生成评论…') return toast('请先生成评论');
  try { await api('/api/qzone/comment',{method:'POST',body:JSON.stringify({user_id:userId,tid,abstime:Number(abstime||0),content})}); input.value=''; toast('AI生成评论已发表'); }
  catch(error) { toast('评论发表失败：'+error.message); }
}
async function loadQZoneModelProfiles() {
  try {
    const data = await api('/api/model-profiles');
    const profiles = (data.profiles || []).filter(item => item.model_type === 'chat');
    window._qzoneChatProfiles = profiles;
    const options = '<option value="">当前聊天模型</option>' + profiles.map(item=>`<option value="${escapeHtml(item.id)}">${escapeHtml(item.name || item.model)} · ${escapeHtml(item.model)}</option>`).join('');
    ['qzoneModelProfile','directoryQzoneModelProfile','qzoneGlobalModelProfile'].forEach(id=>{
      const select = $(id);
      if(!select) return;
      const previous = select.value;
      select.innerHTML = options;
      if(profiles.some(item=>item.id===previous)) select.value = previous;
    });
    const selected = profiles.find(item=>item.id===String(window._qzoneAutomation?.settings?.post_model_profile_id||''));
    if($('qzoneGlobalModelMeta')) $('qzoneGlobalModelMeta').textContent = selected ? `当前：${selected.name || selected.model}` : '未指定时使用当前聊天模型';
    syncQZoneModelSelectors();
  } catch(error) {
    if($('qzonePostGenerateMeta')) $('qzonePostGenerateMeta').textContent = '模型列表读取失败：' + error.message;
    if($('qzoneGlobalModelMeta')) $('qzoneGlobalModelMeta').textContent = '模型列表读取失败：' + error.message;
  }
}
function applyQZoneAutomationSettings(settings) {
  const value = settings || {};
  if($('qzonePostEnabled')) $('qzonePostEnabled').checked=!!value.post_enabled;
  if($('qzonePostAutoGenerate')) $('qzonePostAutoGenerate').checked=!!value.post_auto_generate;
  if($('qzonePeriodDays')) $('qzonePeriodDays').value=Number(value.period_days)||1;
  if($('qzonePostsPerPeriod')) $('qzonePostsPerPeriod').value=Number(value.posts_per_period)||2;
  if($('qzoneStartHour')) $('qzoneStartHour').value=Number.isFinite(Number(value.post_start_hour))?Number(value.post_start_hour):9;
  if($('qzoneEndHour')) $('qzoneEndHour').value=Number.isFinite(Number(value.post_end_hour))?Number(value.post_end_hour):23;
  if($('qzonePostPrompt')) $('qzonePostPrompt').value=String(value.post_prompt || '根据当前记忆和情绪，写一条自然、简短、带一点亚托莉口吻的 QQ 空间动态。');
  if($('qzoneModelProfile')) $('qzoneModelProfile').value=value.post_model_profile_id||'';
  if($('directoryQzoneModelProfile')) $('directoryQzoneModelProfile').value=value.post_model_profile_id||'';
  if($('qzoneGlobalModelProfile')) $('qzoneGlobalModelProfile').value=value.post_model_profile_id||'';
}
let qzoneAutomationLoading = false;
async function loadQZoneAutomation() {
  if(qzoneAutomationLoading) return;
  qzoneAutomationLoading = true;
  try {
    await loadQZoneLoginStatus();
    const data = await api('/api/qzone/automation');
    const publishedAt = Number(data.settings?.last_post_at || 0);
    if(publishedAt) window._qzoneLastPostAt = Math.max(Number(window._qzoneLastPostAt || 0), publishedAt);
    // 页面读取只读已保存状态；预生成仅在保存设置、发布成功或明确操作后触发，
    // 避免刷新页面改变内容池和模型调用次数。
    let friends = [];
    let friendError = '';
    try { friends = (await api('/api/qzone/friends')).friends || []; }
    catch(error) { friendError = error.message; }
    window._qzoneAutomation = {...data, friends, friend_error:friendError};
    await loadQZoneBrowserFeeds();
    renderQZoneAutomation();
    renderUserDirectory();
    // Apply values before optional model-list loading so a model endpoint
    // hiccup cannot leave the form visually blank.
    applyQZoneAutomationSettings(window._qzoneAutomation.settings);
    await loadQZoneModelProfiles();
  } catch(error) {
    $('qzoneAutoMeta').textContent = '读取失败：' + error.message;
    toast('QQ 空间配置读取失败：' + error.message);
  } finally {
    qzoneAutomationLoading = false;
  }
}
async function saveQZoneAutomationSettings() {
  const settings=window._qzoneAutomation?.settings||{};
  const body = {enabled:Boolean($('qzonePostEnabled')?.checked || settings.like_enabled || settings.comment_enabled), post_enabled:Boolean($('qzonePostEnabled')?.checked), post_auto_generate:Boolean($('qzonePostAutoGenerate')?.checked), post_prompt:$('qzonePostPrompt')?.value.trim()||'', post_model_profile_id:$('qzoneModelProfile')?.value||$('qzoneGlobalModelProfile')?.value||'', post_mode:'window', period_days:Number($('qzonePeriodDays')?.value||1), posts_per_period:Number($('qzonePostsPerPeriod')?.value||1), post_start_hour:Number($('qzoneStartHour')?.value||8), post_end_hour:Number($('qzoneEndHour')?.value||23), timezone:settings.timezone||'Asia/Shanghai', visibility:Number(settings.visibility??1), like_enabled:Boolean(settings.like_enabled), comment_enabled:Boolean(settings.comment_enabled), like_rule:'target', comment_use_pool:true, max_likes_per_run:Number(settings.max_likes_per_run??10), max_comments_per_run:Number(settings.max_comments_per_run??2), feed_limit:Number(settings.feed_limit??20)};
  try { await api('/api/qzone/automation/settings', {method:'POST', body:JSON.stringify(body)}); if(body.post_enabled && body.post_auto_generate){ try { await api('/api/qzone/automation/prepare-next',{method:'POST',body:'{}'}); } catch(error) { toast('设置已保存，但下一条动态预生成失败：'+error.message); } } toast('QQ 空间自动互动配置已保存'); await loadQZoneAutomation(); } catch(error) { toast('保存失败：' + error.message); }
}
async function refreshDirectoryAutomationState() {
  try { const data=await api('/api/qzone/automation'); window._qzoneAutomation={...(window._qzoneAutomation||{}),...data}; renderUserDirectory(); if(typeof applyQZoneAutomationSettings==='function') applyQZoneAutomationSettings(data.settings||{}); if(typeof loadQZoneModelProfiles==='function') await loadQZoneModelProfiles(); }
  catch(error) { toast('自动发布状态刷新失败：'+error.message); }
}
async function saveDirectoryAtriPublisher(button) {
  return withButtonBusy(button, ()=>saveDirectoryAtriPublisherCore(), '保存中…');
}
async function saveDirectoryAtriPublisherCore() {
  const settings=window._qzoneAutomation?.settings||{};
  const body={...settings, enabled:Boolean($('directoryQzonePostEnabled')?.checked || $('directoryQzoneLikeEnabled')?.checked || $('directoryQzoneCommentEnabled')?.checked), post_enabled:Boolean($('directoryQzonePostEnabled')?.checked), like_enabled:Boolean($('directoryQzoneLikeEnabled')?.checked), comment_enabled:Boolean($('directoryQzoneCommentEnabled')?.checked), like_rule:'target', post_auto_generate:Boolean($('directoryQzonePostAutoGenerate')?.checked), post_prompt:$('directoryQzonePostPrompt')?.value.trim()||'', post_model_profile_id:$('directoryQzoneModelProfile')?.value||$('qzoneGlobalModelProfile')?.value||settings.post_model_profile_id||'', period_days:Number($('directoryQzonePeriodDays')?.value||1), posts_per_period:Number($('directoryQzonePostsPerPeriod')?.value||1), post_start_hour:Number($('directoryQzoneStartHour')?.value||9), post_end_hour:Number($('directoryQzoneEndHour')?.value||23), comment_use_pool:true};
  try { await api('/api/qzone/automation/settings',{method:'POST',body:JSON.stringify(body)}); if(body.post_enabled && body.post_auto_generate) await api('/api/qzone/automation/prepare-next',{method:'POST',body:'{}'}); await refreshDirectoryAutomationState(); toast('亚托莉自动发布设置已保存'); }
  catch(error) { toast('亚托莉发布设置保存失败：'+error.message); }
}
async function publishDirectoryAtriPost(button) {
  return withButtonBusy(button, ()=>publishDirectoryAtriPostCore(), '发布中…');
}
async function publishDirectoryAtriPostCore() {
  try { const result=await api('/api/qzone/automation/publish-generated',{method:'POST',body:JSON.stringify({prompt:$('directoryQzonePostPrompt')?.value.trim()||'',model_profile_id:$('directoryQzoneModelProfile')?.value||$('qzoneGlobalModelProfile')?.value||window._qzoneAutomation?.settings?.post_model_profile_id||''})}); toast(result.ok?'亚托莉动态已生成并发布':'动态发布失败'); await refreshDirectoryAutomationState(); }
  catch(error) { toast('亚托莉动态发布失败：'+error.message); }
}
async function toggleQZoneAll(value) {
  $('qzoneEnabled').checked = !!value; await saveQZoneAutomationSettings();
}
async function saveGlobalQZoneModelProfile(button) {
  const profileId=$('qzoneGlobalModelProfile')?.value||'';
  const settings={...(window._qzoneAutomation?.settings||{}),post_model_profile_id:profileId};
  try {
    if(button) button.disabled=true;
    await api('/api/qzone/automation/settings',{method:'POST',body:JSON.stringify(settings)});
    if(window._qzoneAutomation) window._qzoneAutomation.settings=settings;
    applyQZoneAutomationSettings(settings);
    if($('qzoneGlobalModelMeta')) $('qzoneGlobalModelMeta').textContent=profileId?'模型选择已保存':'未指定时使用当前聊天模型';
    toast('QQ 动态生成模型已保存');
  } catch(error) { toast('模型保存失败：'+error.message); }
  finally { if(button) button.disabled=false; }
}
async function publishGeneratedQZonePost() { const promptText=$('qzonePostPrompt')?.value.trim()||''; try { const result=await api('/api/qzone/automation/publish-generated',{method:'POST',body:JSON.stringify({prompt:promptText,model_profile_id:$('qzoneModelProfile')?.value||$('qzoneGlobalModelProfile')?.value||window._qzoneAutomation?.settings?.post_model_profile_id||''})}); toast(result.ok?'已生成并发布动态':'发布失败'); await loadQZoneAutomation(); } catch(error) { toast('动态发布失败：'+error.message); } }
async function saveQZonePersonPolicy(userId, field, value) { const feeds=window._qzoneLatestFeeds||[]; const feed=feeds.find(item=>String(item.user_id)===String(userId)); const targets=[...(window._qzoneAutomation?.targets||[])]; let target=targets.find(item=>String(item.user_id)===String(userId)); if(!target){target={user_id:String(userId),nickname:feed?.author||`QQ ${userId}`,enabled_like:false,enabled_comment:false}; targets.push(target);} target[field]=!!value; try { const result=await api('/api/qzone/automation/targets',{method:'POST',body:JSON.stringify({targets})}); window._qzoneAutomation.targets=result.targets||targets; const enabledLike=window._qzoneAutomation.targets.some(item=>item.enabled_like); const enabledComment=window._qzoneAutomation.targets.some(item=>item.enabled_comment); await api('/api/qzone/automation/settings',{method:'POST',body:JSON.stringify({...window._qzoneAutomation.settings,enabled:Boolean(enabledLike||enabledComment||window._qzoneAutomation.settings.post_enabled),like_enabled:enabledLike,comment_enabled:enabledComment,like_rule:'target',comment_use_pool:true})}); toast(`${field==='enabled_like'?'自动点赞':'自动评论'}已${value?'开启':'关闭'}`); } catch(error) { toast('保存用户设置失败：'+error.message); } }
"""
