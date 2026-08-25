from __future__ import annotations

PART = r"""  return ({queued:'等待',running:'处理中',succeeded:'完成',failed:'失败',cancelled:'已取消'})[state] || state || '未知';
}
function renderSingingJobs(jobs) {
  const out = $('singingJobList');
  if(!out) return;
  if(!jobs.length) {
    out.innerHTML = '<div class="note">还没有歌声转换任务。</div>';
    return;
  }
  out.innerHTML = jobs.slice(0,8).map(job=>{
    const state = String(job.state || '');
    const canCancel = state==='queued' || state==='running';
    const canPlay = state==='succeeded' && job.audio_path;
    const action = canCancel
      ? `<button class="danger" onclick="cancelSingingJob('${job.id}')">取消</button>`
      : (canPlay ? `<button onclick="playSingingJob('${job.id}','${encodeURIComponent(job.audio_path)}')">播放</button>` : '<span></span>');
    return `<div class="singing-job">
      <div><strong>${escapeHtml(job.request?.text || '未命名歌曲')}</strong><small>${escapeHtml(job.message || job.error || '')}</small><div class="singing-progress"><span style="width:${Math.max(0,Math.min(100,Number(job.progress || 0)))}%"></span></div></div>
      <span class="singing-state ${escapeHtml(state)}">${escapeHtml(singingStateText(state))}</span>
      <strong>${Number(job.progress || 0)}%</strong>
      ${action}
    </div>`;
  }).join('');
  const active = jobs.find(job=>job.state==='queued' || job.state==='running');
  clearTimeout(window._singingJobsTimer);
  if(active) window._singingJobsTimer = setTimeout(loadSingingJobs, 1800);
}
async function loadSingingJobs() {
  const out = $('singingJobList');
  if(!out) return;
  try {
    const result = await api('/api/voice/singing/jobs');
    const jobs = Array.isArray(result.jobs) ? result.jobs : [];
    window._singingJobs = jobs;
    renderSingingJobs(jobs);
    const newest = jobs[0];
    if(newest?.state==='succeeded' && newest.audio_path && window._activeSingingJob===newest.id) {
      playSingingJob(newest.id, encodeURIComponent(newest.audio_path), false);
      $('singingTestState').textContent = `转换完成：${newest.source || 'Seed-VC'} · 可以播放试听`;
      window._activeSingingJob = '';
    } else if(newest?.state==='failed' && window._activeSingingJob===newest.id) {
      $('singingTestState').textContent = '转换失败：' + (newest.error || newest.message || '未知错误');
      window._activeSingingJob = '';
    }
  } catch(error) {
    out.innerHTML = `<div class="note">任务读取失败：${escapeHtml(error.message)}</div>`;
  }
}
async function createSingingTest() {
  const source = $('singingSourcePath').value.trim();
  const reference = $('singingReferencePath').value.trim();
  if(!source) return toast('请上传导唱，或填写本机音频绝对路径');
  if(!reference) return toast('没有可用的亚托莉歌声参考');
  const out = $('singingTestState');
  const button = $('singingCreateButton');
  button.disabled = true;
  out.textContent = '正在提交歌声转换任务...';
  try {
    const result = await api('/api/voice/singing/create', {method:'POST', body:JSON.stringify({
      text:$('singingSongName').value.trim() || '亚托莉歌声测试',
      source_audio_path:source,
      reference_audio_path:reference,
      profile:$('voiceProfileId').value.trim() || 'atri',
      preview_seconds:Number($('singingPreviewSeconds').value || 15),
      pitch_shift:Number($('singingPitchShift').value || 0)
    })});
    window._activeSingingJob = result.id;
    out.textContent = `任务已提交：${result.message || '等待处理'}`;
    await loadSingingJobs();
  } catch(error) {
    out.textContent = '提交失败：' + error.message;
  } finally {
    button.disabled = false;
  }
}
async function cancelSingingJob(jobId) {
  try {
    await api('/api/voice/singing/cancel', {method:'POST', body:JSON.stringify({id:jobId})});
    if(window._activeSingingJob===jobId) window._activeSingingJob = '';
    $('singingTestState').textContent = '任务已取消';
    await loadSingingJobs();
  } catch(error) {
    $('singingTestState').textContent = '取消失败：' + error.message;
  }
}
function playSingingJob(jobId, encodedPath, announce=true) {
  const audio = $('singingPreviewAudio');
  audio.src = 'http://127.0.0.1:8793/api/jobs/' + encodeURIComponent(jobId) + '/audio';
  audio.load();
  if(announce) $('singingTestState').textContent = `正在试听任务 ${jobId.slice(0,8)}`;
}
async function createVoiceCallTest() {
  const out = $('voiceCallTestOut');
  out.textContent = '正在保存配置并创建通话...';
  try {
    await saveVoice();
    const result = await api('/api/voice-call/test-invite', {method:'POST', body:'{}'});
    out.innerHTML = `测试邀请已创建，十分钟内有效：<a href="${escapeHtml(result.call_url)}" target="_blank" rel="noopener">打开通话页面</a>`;
  } catch(error) {
    out.textContent = '创建失败：' + error.message;
  }
}
async function previewVoice() {
  const out = $('voicePreviewInfo');
  const button = $('voicePreviewButton');
  const text = $('voicePreviewText').value.trim();
  if(!text) return toast('请输入试听文本');
  button.disabled = true;
  const started = Date.now();
  out.textContent = '正在切换模型并合成 · 0 秒';
  const ticker = setInterval(()=>{ out.textContent = `正在切换模型并合成 · ${Math.floor((Date.now()-started)/1000)} 秒`; }, 1000);
  try {
    const result = await api('/api/voice/preview', {method:'POST', body:JSON.stringify({
      text,
      language:$('voicePreviewLanguage').value,
      emotion:$('voicePreviewEmotion').value,
      mode:$('voicePreviewMode').value,
      profile:$('voiceProfileId').value.trim() || 'atri'
    })});
    $('voicePreviewAudio').src = result.audio_url;
    $('voicePreviewAudio').load();
    const quality = result.quality;
    const qualityText = quality ? ` · 回读错误率 ${Math.round(Number(quality.error_rate || 0)*100)}%` : '';
    const source = result.source === 'original_clip' ? '完整原声' : '模型合成';
    out.textContent = `${source}完成 · ${result.elapsed_ms} ms${qualityText}，可以直接播放。`;
  } catch(error) {
    out.textContent = '试听失败：' + error.message;
  } finally {
    clearInterval(ticker);
    button.disabled = false;
  }
}
async function loadStatus() {
"""
