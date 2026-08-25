from __future__ import annotations

PART = r"""  const speech = module !== 'music';
  $('voiceSpeechTab').classList.toggle('active', speech);
  $('voiceMusicTab').classList.toggle('active', !speech);
  $('voiceSpeechPanel').classList.toggle('active', speech);
  $('voiceMusicPanel').classList.toggle('active', !speech);
  $('voiceSpeechTab').setAttribute('aria-selected', String(speech));
  $('voiceMusicTab').setAttribute('aria-selected', String(!speech));
  window._voiceMusicActive = !speech;
  if(speech) {
    clearTimeout(window._musicProjectTimer);
    releaseMusicMedia();
  } else if(!window._musicProjectsLoaded) {
    loadMusicSources();
    loadMusicProjects();
    loadDeliverySongs();
  } else {
    loadDeliverySongs();
  }
}

function minecraftMaidTelemetry() {
  const state = window._minecraftData?.bridge?.state || {};
  const telemetry = state.telemetry || {};
  return Array.isArray(telemetry.maids) ? telemetry.maids : [];
}
function renderMinecraftMaidSelection() {
  const maids = minecraftMaidTelemetry();
  const selected = $('minecraftMaidSelect')?.value || '';
  const out = $('minecraftMaidList');
  if(!out) return;
  if(!maids.length) {
    out.innerHTML = '<div class="note">当前没有收到属于玩家的 UMU 女仆。1.21.11 冒烟测试只验证连接，不会显示女仆。</div>';
    return;
  }
  out.innerHTML = maids.map(maid=>{
    const active = maid.uuid===selected;
    const health = Number(maid.health ?? 0);
    const maxHealth = Number(maid.maxHealth ?? 0);
    return `<div class="minecraft-maid ${active?'selected':''}">
      <div class="minecraft-maid-head">
        <div><strong>${escapeHtml(maid.name || 'UMU 女仆')}</strong><div class="memory-meta mono">${escapeHtml(maid.uuid || '')}</div></div>
        <span class="badge ${String(maid.mode || '').toUpperCase()==='FOLLOW'?'active':''}">${escapeHtml(maid.mode || 'UNKNOWN')}</span>
      </div>
      <div class="minecraft-maid-meta">
        <div><span>职业</span><strong>${escapeHtml(maid.job || 'UNKNOWN')}</strong></div>
        <div><span>生命</span><strong>${health.toFixed(1)} / ${maxHealth.toFixed(1)}</strong></div>
        <div><span>距离</span><strong>${Number(maid.distance || 0).toFixed(1)} 格</strong></div>
        <div><span>坐标</span><strong>${Number(maid.x || 0).toFixed(0)}, ${Number(maid.y || 0).toFixed(0)}, ${Number(maid.z || 0).toFixed(0)}</strong></div>
      </div>
      ${active ? '<div class="ok">当前控制对象</div>' : `<button class="ghost" onclick="selectMinecraftMaid('${escapeHtml(maid.uuid || '')}')">选择</button>`}
    </div>`;
  }).join('');
}
function selectMinecraftMaid(uuid) {
  $('minecraftMaidSelect').value = uuid;
  renderMinecraftMaidSelection();
}
function renderMinecraft(data) {
  window._minecraftData = data;
  const config = data.config || {};
  const bridge = data.bridge || {};
  const health = bridge.health || {};
  const state = bridge.state || {};
  const telemetry = state.telemetry || {};
  const maids = minecraftMaidTelemetry();
  $('minecraftEnabled').checked = !!config.enabled;
  $('minecraftBridgeUrl').value = config.bridge_url || 'http://127.0.0.1:8792';
  const connected = !!(health.minecraftConnected || state.minecraftConnected);
  $('minecraftStatusText').textContent = !bridge.reachable
    ? `桥接服务不可达：${bridge.error || '请先启动本地桥接'}`
    : (connected ? 'Minecraft 已连接，遥测正常。' : '桥接服务已启动，等待 Minecraft 客户端连接。');
  $('minecraftStatusCards').innerHTML = [
    ['控制开关', !!config.enabled, config.enabled ? '已允许' : '已禁用'],
    ['本地桥接', !!bridge.reachable, bridge.reachable ? '在线' : '离线'],
    ['Minecraft', connected, connected ? '已连接' : '未连接']
  ].map(([name,ok,text])=>`<div class="stat"><span class="${ok?'ok':'bad'}">${escapeHtml(text)}</span><div class="memory-meta">${escapeHtml(name)}</div></div>`).join('');
  const select = $('minecraftMaidSelect');
  const previous = select.value;
  select.innerHTML = maids.map(maid=>`<option value="${escapeHtml(maid.uuid)}">${escapeHtml(maid.name || 'UMU 女仆')} · ${escapeHtml(maid.mode || 'UNKNOWN')} · ${Number(maid.distance || 0).toFixed(1)}格</option>`).join('');
  if(maids.some(maid=>maid.uuid===previous)) select.value = previous;
  if(!select.options.length) select.innerHTML = '<option value="">没有可控制的女仆</option>';
  renderMinecraftMaidSelection();
  const lastResult = state.lastResult || {};
  if(lastResult.requestId) {
    $('minecraftCommandOut').textContent = `${lastResult.ok ? '执行成功' : '执行失败'}
${lastResult.detail || ''}
请求：${lastResult.requestId}`;
  } else if(telemetry.smokeTest) {
    $('minecraftCommandOut').textContent = `1.21.11 冒烟连接成功
Minecraft ${telemetry.minecraftVersion || ''}
下一步可以进入 UMU 3.11a 隔离副本测试。`;
  }
  clearTimeout(window._minecraftRefreshTimer);
  if($('minecraft').classList.contains('active')) {
    window._minecraftRefreshTimer = setTimeout(loadMinecraft, connected ? 1800 : 3500);
  }
}
async function loadMinecraft() {
  try {
    renderMinecraft(await api('/api/minecraft'));
  } catch(error) {
    $('minecraftStatusText').textContent = '后台读取失败：' + error.message;
  }
}
async function saveMinecraftConfig() {
  try {
    await api('/api/minecraft/config', {method:'POST', body:JSON.stringify({
      enabled:$('minecraftEnabled').checked,
      bridge_url:$('minecraftBridgeUrl').value.trim()
    })});
    toast('Minecraft 桥接配置已保存');
    await loadMinecraft();
  } catch(error) {
    toast('保存失败：' + error.message);
  }
}
async function sendMinecraftCommand(command) {
  const maidUuid = $('minecraftMaidSelect').value || null;
  const out = $('minecraftCommandOut');
  out.textContent = `正在发送 ${command}...`;
  try {
    const result = await api('/api/minecraft/command', {method:'POST', body:JSON.stringify({
      command,
      maidUuid
    })});
    out.textContent = `命令已接收
请求：${result.result?.requestId || '状态刷新'}`;
    setTimeout(loadMinecraft, 650);
  } catch(error) {
    out.textContent = '发送失败：' + error.message;
  }
}

function voiceConfigValue(cfg, key) {
"""
