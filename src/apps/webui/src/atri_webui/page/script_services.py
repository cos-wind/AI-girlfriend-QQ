from __future__ import annotations

# 后台服务的手动开关。
#
# 语音服务（8790）仍由本项目托管：它平时只在 QQ 语音链路按需拉起，这里给用户
# 一个明确的启动 / 停止入口。停止会直接结束 8790 进程（含正在进行的合成），
# 下一条语音重新冷启动——这是点「停止」时明确选择的行为。
#
# 歌曲工作台（AI_music）已迁出本项目，这里只调用对方自己的启动脚本并跳转；
# 桥接（8793）与前端（3000）的生命周期都由那个项目负责。
#
# 三个服务的运行状态统一由 `loadStatus()` 写进顶部「运行状态」，卡片里不再显示。
PART = r"""function updateVoiceServiceButton() {
  const button = $('voiceServiceStartButton');
  if(!button) return;
  const running = !!window._voiceServiceSwitch?.running;
  button.disabled = false;
  button.classList.toggle('danger', running);
  button.textContent = running ? '停止语音服务' : '启动语音服务';
}
async function loadVoiceServiceSwitch() {
  const button = $('voiceServiceStartButton');
  if(!button) return null;
  try {
    const data = await api('/api/voice/service');
    window._voiceServiceSwitch = data;
    updateVoiceServiceButton();
    return data;
  } catch(error) {
    button.disabled = false;
    button.textContent = '启动语音服务';
    return null;
  }
}
async function toggleVoiceService(button) {
  const running = !!window._voiceServiceSwitch?.running;
  button.disabled = true;
  button.textContent = running ? '停止中…' : '启动中…';
  try {
    const result = await api('/api/voice/service', {method:'POST', body:JSON.stringify({action: running ? 'stop' : 'start'})});
    toast(result.message || (running ? '语音服务停止命令已发出' : '语音服务启动命令已发出'));
  } catch(error) {
    toast((running ? '语音服务停止失败：' : '语音服务启动失败：') + error.message);
  } finally {
    updateVoiceServiceButton();
  }
  await loadVoiceServiceSwitch();
  await loadStatus();
}
async function loadMusicWorkbench() {
  try {
    const data = await api('/api/music/entry-status');
    window._musicWorkbench = data;
    return data;
  } catch(error) {
    window._musicWorkbench = null;
    return null;
  }
}
function openMusicWorkbench() {
  const url = (window._musicWorkbench?.web?.url || '').trim() || 'http://127.0.0.1:3000/workbench';
  window.open(url, '_blank', 'noopener');
}
async function startMusicWorkbench(button) {
  if(button) { button.disabled = true; button.textContent = '启动中…'; }
  try {
    const result = await api('/api/music/entry-start', {method:'POST', body:'{}'});
    toast(result.message || '工作台启动命令已发出');
  } catch(error) {
    toast('工作台启动失败：' + error.message);
  } finally {
    if(button) { button.disabled = false; button.textContent = '启动歌曲工作台'; }
  }
  await loadMusicWorkbench();
  await loadStatus();
}
"""
