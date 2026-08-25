from __future__ import annotations

PART = r"""  $('testOut').textContent='亚托莉生成中...';
  const r = await api('/api/test-chat', {method:'POST', body:JSON.stringify({text:$('testText').value})});
  $('testOut').textContent = r.used_ai
    ? r.reply
    : `当前聊天模型没有连上，正在走兜底。
错误：${r.error || '未知错误'}

兜底回复：${r.reply}`;
}
async function loadVoiceTestState() {
  const out = $('testVoiceState');
  try {
    const data = await api('/api/voice');
    window._voiceData = data;
    populateVoiceCandidateSelects(data);
    const service = data.service || {};
    const asr = service.asr || {};
    const profileId = $('testTtsProfileA')?.value || 'atri';
    const profile = (data.profiles || []).find(item=>item.id===profileId) || {};
    const asrState = asr.loaded ? '模型已加载，中英日自动识别可用' : (asr.loading ? '模型预热中' : (asr.load_error ? `加载失败：${asr.load_error}` : (asr.dependency_available ? '等待模型加载' : '依赖不可用')));
    out.textContent = `服务：${service.ok?'已连接':'未连接'} · 识别：${asrState} · 音色：${profile.ready?'参考音频已就绪':'未就绪'}`;
  } catch(error) {
    out.textContent = '状态读取失败：' + error.message;
  }
}
function populateVoiceCandidateSelects(data) {
  const profiles = data.profiles || [];
  const candidates = data.candidates || [];
  // The test panel is also the acceptance surface for locally installed packs.
  // Candidates are benchmark metadata, not the complete profile registry.
  const available = profiles.filter(item=>item.ready);
  const options = available.map(item=>`<option value="${escapeHtml(item.id)}">${escapeHtml(item.display_name || item.id)}${item.model_version ? ` · ${escapeHtml(item.model_version)}` : ''}${item.ready ? '' : ' · 未就绪'}</option>`).join('');
  for(const id of ['testTtsProfileA','testTtsProfileB']) {
    const select = $(id);
    if(!select) continue;
    const previous = select.value;
    select.innerHTML = options;
    if(available.some(item=>item.id===previous)) select.value = previous;
  }
  const second = $('testTtsProfileB');
  if(second && available.length > 1 && !second.dataset.initialized) {
    second.selectedIndex = 1;
    second.dataset.initialized = 'true';
  }
}
const voiceLanguageSamples = {
    zh:'主人，今天也请让我陪在你身边。',
    en:'Master, please let me stay by your side today.',
    ja:'マスター、今日もあなたのそばにいさせてください。'
};
function useVoicePreviewLanguageSample() {
  $('voicePreviewText').value = voiceLanguageSamples[$('voicePreviewLanguage').value] || voiceLanguageSamples.zh;
}
function useVoiceLanguageSample() {
  $('testTtsText').value = voiceLanguageSamples[$('testTtsLanguage').value] || voiceLanguageSamples.zh;
}
async function translateVoiceTestText() {
  const text = $('testTtsText').value.trim();
  const targetLanguage = $('testTtsLanguage').value;
  if(!text) return toast('请输入要翻译的文本');
  const button = $('testTtsTranslateButton');
  const out = $('testTtsOut');
  button.disabled = true;
  const previous = out.textContent;
  out.textContent = '正在翻译到目标语言...';
  try {
    const result = await api('/api/voice/translate', {method:'POST', body:JSON.stringify({text, target_language:targetLanguage})});
    $('testTtsText').value = result.text;
    out.textContent = `已翻译：${result.source_language} → ${result.target_language}${result.elapsed_ms ? ` · ${result.elapsed_ms} ms` : ''}`;
  } catch(error) {
    out.textContent = '翻译失败：' + error.message;
    if(previous) setTimeout(()=>{ if(out.textContent.startsWith('翻译失败')) out.textContent = previous; }, 3500);
  } finally {
    button.disabled = false;
  }
}
async function handleVoiceLanguageChange() {
  if($('testTtsAutoTranslate').checked) {
    await translateVoiceTestText();
  } else {
    useVoiceLanguageSample();
  }
}
function encodeWaveFile(audioBuffer) {
  const channels = audioBuffer.numberOfChannels;
  const frames = audioBuffer.length;
  const mono = new Float32Array(frames);
  for(let channel=0; channel<channels; channel++) {
    const source = audioBuffer.getChannelData(channel);
    for(let i=0; i<frames; i++) mono[i] += source[i] / channels;
  }
  const buffer = new ArrayBuffer(44 + frames * 2);
  const view = new DataView(buffer);
  const write = (offset, value) => { for(let i=0; i<value.length; i++) view.setUint8(offset+i, value.charCodeAt(i)); };
  write(0, 'RIFF'); view.setUint32(4, 36 + frames * 2, true); write(8, 'WAVE');
  write(12, 'fmt '); view.setUint32(16, 16, true); view.setUint16(20, 1, true);
  view.setUint16(22, 1, true); view.setUint32(24, audioBuffer.sampleRate, true);
  view.setUint32(28, audioBuffer.sampleRate * 2, true); view.setUint16(32, 2, true);
  view.setUint16(34, 16, true); write(36, 'data'); view.setUint32(40, frames * 2, true);
  for(let i=0; i<frames; i++) {
    const sample = Math.max(-1, Math.min(1, mono[i]));
    view.setInt16(44 + i * 2, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true);
  }
  return new Blob([buffer], {type:'audio/wav'});
}
async function recordedBlobToWave(blob) {
  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  if(!AudioContextClass) throw new Error('当前浏览器不支持音频解码');
  const context = new AudioContextClass();
  try {
    const decoded = await context.decodeAudioData(await blob.arrayBuffer());
    return encodeWaveFile(decoded);
  } finally {
    await context.close();
  }
}
async function startAsrRecording() {
  const out = $('testAsrOut');
  if(!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
    out.textContent = '当前浏览器不支持麦克风录音。';
    return;
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({audio:true});
    const mimeType = ['audio/webm;codecs=opus','audio/webm','audio/ogg;codecs=opus','audio/ogg'].find(type=>MediaRecorder.isTypeSupported(type)) || '';
    const recorder = new MediaRecorder(stream, mimeType ? {mimeType} : undefined);
    window._asrRecorder = recorder;
    window._asrChunks = [];
    window._recordedAsrFile = null;
    recorder.ondataavailable = event => { if(event.data?.size) window._asrChunks.push(event.data); };
    recorder.onstop = async () => {
      clearTimeout(window._asrAutoStop);
      stream.getTracks().forEach(track=>track.stop());
      $('testAsrRecordButton').disabled = false;
      $('testAsrStopButton').disabled = true;
      try {
        out.textContent = '正在处理录音...';
        const captured = new Blob(window._asrChunks, {type:recorder.mimeType || 'audio/webm'});
        const wav = await recordedBlobToWave(captured);
        const file = new File([wav], `microphone-${Date.now()}.wav`, {type:'audio/wav'});
        window._recordedAsrFile = file;
        await testVoiceRecognition(file);
      } catch(error) {
        out.textContent = '录音处理失败：' + error.message;
      }
    };
    recorder.start(250);
    $('testAsrRecordButton').disabled = true;
    $('testAsrStopButton').disabled = false;
    out.textContent = '正在听你说话 · 0 秒';
    const started = Date.now();
    window._asrRecordTicker = setInterval(()=>{ out.textContent = `正在听你说话 · ${Math.floor((Date.now()-started)/1000)} 秒`; }, 1000);
    window._asrAutoStop = setTimeout(stopAsrRecording, 60000);
  } catch(error) {
    out.textContent = '无法使用麦克风：' + error.message;
  }
}
function stopAsrRecording() {
  clearInterval(window._asrRecordTicker);
  const recorder = window._asrRecorder;
  if(recorder && recorder.state==='recording') recorder.stop();
}
async function testVoiceRecognition(fileOverride=null) {
  const file = fileOverride || window._recordedAsrFile || $('testAsrFile').files[0];
  if(!file) return toast('先选择要识别的音频');
  const out = $('testAsrOut');
  const started = Date.now();
  out.textContent = '正在识别 · 0 秒';
  const ticker = setInterval(()=>{ out.textContent = `正在识别 · ${Math.floor((Date.now()-started)/1000)} 秒${window._voiceData?.service?.asr?.loaded ? '' : ' · 首次加载模型'}`; }, 1000);
  const form = new FormData();
  form.append('file', file);
  form.append('language', $('testAsrLanguage').value || 'auto');
  try {
    const result = await api('/api/voice/test-asr', {method:'POST', body:form});
    const confidence = result.confidence == null ? '未提供' : Number(result.confidence).toFixed(3);
    out.textContent = `识别文本：${result.text}
语言：${result.language || '未知'}
情绪：${result.emotion || 'neutral'}
置信度：${confidence}
耗时：${result.elapsed_ms} ms`;
  } catch(error) {
    out.textContent = '识别失败：' + error.message;
  } finally {
    clearInterval(ticker);
    loadVoiceTestState();
  }
}
async function synthesizeVoiceCandidate(profileId, audioId, outputId) {
  const out = $(outputId);
  const started = Date.now();
  out.textContent = '正在切换模型并合成 · 0 秒';
  const ticker = setInterval(()=>{ out.textContent = `正在切换模型并合成 · ${Math.floor((Date.now()-started)/1000)} 秒`; }, 1000);
  try {
    const result = await api('/api/voice/preview', {method:'POST', body:JSON.stringify({
      text:$('testTtsText').value,
      profile:profileId,
      language:$('testTtsLanguage').value,
      emotion:$('testTtsEmotion').value,
      intensity:Number($('testTtsIntensity').value),
      preview_mode:$('testTtsStrictQuality').checked ? 'strict' : 'fast'
    })});
    const audio = $(audioId);
    audio.src = result.audio_url;
    audio.load();
    out.textContent = `${result.elapsed_ms} ms${result.duration_seconds == null ? '' : ` · 音频 ${result.duration_seconds} 秒`}`;
    return result;
  } finally {
    clearInterval(ticker);
  }
}
async function testVoiceComparison() {
  const out = $('testTtsOut');
  const button = $('testTtsCompareButton');
  const profileA = $('testTtsProfileA').value;
  const profileB = $('testTtsProfileB').value;
  if(!profileA || !profileB) return toast('需要两套已就绪的候选语音档案');
  button.disabled = true;
  out.textContent = '正在生成候选 A...';
  try {
    await synthesizeVoiceCandidate(profileA, 'testTtsAudioA', 'testTtsOutA');
    out.textContent = '正在切换模型并生成候选 B...';
    await synthesizeVoiceCandidate(profileB, 'testTtsAudioB', 'testTtsOutB');
    out.textContent = 'A/B 试听已完成，请分别播放比较。';
  } catch(error) {
    out.textContent = '合成失败：' + error.message;
  } finally {
    button.disabled = false;
  }
}
async function testVoiceSynthesis() {
  const profileId = $('testTtsProfileA').value;
  const button = $('testTtsButton');
  if(!profileId) return toast('请先选择语音档案');
  button.disabled = true;
  $('testTtsOut').textContent = '正在生成单候选试听...';
  try {
    const result = await synthesizeVoiceCandidate(profileId, 'testTtsAudioA', 'testTtsOutA');
    const quality = result.quality;
    const qualityText = quality ? ` · 回读错误率 ${Math.round(Number(quality.error_rate || 0) * 100)}%` : ' · 快速模式未执行回读';
    $('testTtsOut').textContent = `试听完成 · ${result.elapsed_ms} ms${qualityText}`;
  } catch(error) {
    $('testTtsOut').textContent = '合成失败：' + error.message;
  } finally {
    button.disabled = false;
  }
}
async function restartServices() {
  const r = await api('/api/restart', {method:'POST', body:'{}'});
  toast(r.message || r.error || '已执行');
}
function setupAdvancedAccordions() {
  document.querySelectorAll('#advanced .accordion-section').forEach(section=>{
    const heading = section.querySelector(':scope > .section-head') || section.querySelector(':scope > h3');
    if(!heading) return;
    section.classList.add('collapsed');
    heading.setAttribute('role','button');
    heading.setAttribute('tabindex','0');
    const toggle = ()=>section.classList.toggle('collapsed');
    heading.addEventListener('click', event=>{
      if(event.target.closest('button')) return;
      toggle();
    });
    heading.addEventListener('keydown', event=>{
      if(event.key === 'Enter' || event.key === ' ') { event.preventDefault(); toggle(); }
    });
  });
}
function openRequestedTab() {
  const raw = new URLSearchParams(window.location.search).get('tab');
  const requested = ['memory','qzone'].includes(raw) ? 'users' : raw;
  if(!requested) return;
  const button = Array.from(document.querySelectorAll('.tab')).find(item =>
    item.getAttribute('onclick') === `showTab(event,'${requested}')`
  );
  if(button) button.click();
}
setupAdvancedAccordions();
openRequestedTab();
loadStatus(); loadProfiles(); loadConfig(); loadReplyVoiceProbability(); loadProactive(); loadUserDirectory(false); loadModalityAccess();
// 目录核心数据先显示；本地自动发布状态与 QQ 动态优先读取。完整记忆摘要
// 的构建较重，等 QQ 动态完成或最多等待 25 秒后再后台加载，避免争抢首屏。
loadDirectoryAutomationState();
// 记忆是用户卡片的核心数据，立即并行加载；QQ 空间慢请求不再阻塞它。
loadMemory().catch(error=>{ if($('userDirectoryStatus')) $('userDirectoryStatus').textContent='记忆读取失败：'+error.message; });
refreshDirectoryQZoneData();
setInterval(()=>{
  if($('evaluation')?.classList.contains('active') && $('evaluationDashboardPanel')?.classList.contains('active')) {
    // 系统评测任务是异步旁路；看板定时刷新队列、趋势和明细，避免手动点刷新才能看到结果。
    loadEvaluation(false);
  }
}, 3000);
// Do not refresh the QQ 动态 page on a fixed hourly cadence. We only check a
// lightweight publication timestamp and rebuild the page after a real post;
// normal viewing/refreshing therefore leaves the persisted schedule untouched.
</script>
</body>
</html>"""
