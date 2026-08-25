from __future__ import annotations

PART = r"""  const name = String(path || '').split(/[\/]/).pop() || '';
  return name.replace(/\.[^.]+$/, '');
}
function renderDeliverySongs(data) {
  const source = $('deliveryMusicSource');
  const files = Array.isArray(data.complete_files) ? data.complete_files : [];
  const current = source.value;
  source.innerHTML = files.length
    ? files.map(file=>`<option value="${escapeHtml(file.path)}">${escapeHtml(file.name)}</option>`).join('')
    : '<option value="">完整音乐目录暂无文件</option>';
  if(files.some(file=>file.path===current)) source.value = current;
  if(source.value && !$('deliveryMusicTitle').value.trim()) $('deliveryMusicTitle').value = deliverySourceTitle(source.value);
  source.onchange = ()=>{ if(!$('deliveryMusicTitle').value.trim()) $('deliveryMusicTitle').value = deliverySourceTitle(source.value); };
  $('completeMusicList').innerHTML = files.length ? files.map(file=>`
    <div class="music-delivery-song">
      <strong>《${escapeHtml(deliverySourceTitle(file.name))}》</strong>
      <div class="memory-meta">${escapeHtml(file.name)} · ${(Number(file.size||0)/1024/1024).toFixed(1)} MB · QQ 发送整首</div>
    </div>`).join('') : '<p class="note">完整音乐目录为空。导入歌曲后即可按文件名点播整首。</p>';
  const songs = Array.isArray(data.songs) ? data.songs : [];
  $('deliveryMusicList').innerHTML = songs.length ? songs.map(song=>`
    <div class="music-delivery-song">
      <strong>《${escapeHtml(song.title)}》</strong><div class="memory-meta">${escapeHtml(song.path || '')} · ${(song.segments||[]).length} 段</div>
      ${(song.segments||[]).map(segment=>`<div class="music-delivery-segment"><span class="badge active">${Number(segment.index)} · ${Number(segment.duration_seconds||0).toFixed(1)}s</span><div><div class="memory-meta">${escapeHtml(segment.label || segment.name || '')}</div><audio controls preload="metadata" src="${escapeHtml(segment.url)}"></audio></div></div>`).join('')}
    </div>`).join('') : '<p class="note">片段目录为空。这不会影响 QQ 从完整音乐目录发送整首歌曲。</p>';
}
async function loadDeliverySongs() {
  if(!$('deliveryMusicList')) return;
  try { renderDeliverySongs(await api('/api/music/delivery-songs')); }
  catch(error) { $('deliveryMusicList').innerHTML = `<p class="note">片段库读取失败：${escapeHtml(error.message)}</p>`; }
}
async function uploadDeliveryMusic() {
  const file = $('deliveryMusicFile').files[0];
  if(!file) return toast('先选择已合成的完整歌曲');
  const state = $('completeMusicState');
  state.textContent = '正在导入完整音乐…';
  const form = new FormData(); form.append('file', file);
  try {
    const result = await api('/api/music/delivery-source', {method:'POST', body:form});
    $('deliveryMusicFile').value = '';
    $('deliveryMusicTitle').value = deliverySourceTitle(result.path || result.name);
    await loadDeliverySongs();
    $('deliveryMusicSource').value = result.path || '';
    state.textContent = `已导入 ${result.name}；现在可以按歌名发送整首 QQ 语音。`;
    toast('完整音乐已导入，已加入 QQ 整首点歌清单');
  } catch(error) { state.textContent = '导入失败：' + error.message; }
}
async function segmentDeliveryMusic() {
  const source = $('deliveryMusicSource').value;
  if(!source) return toast('先导入或选择完整歌曲');
  const button = $('deliveryMusicSegmentButton'), state = $('deliveryMusicState');
  button.disabled = true;
  state.textContent = '正在分析小节并导出 WebUI 试听片段。处理期间不影响亚托莉正常回复…';
  try {
    const result = await api('/api/music/delivery-segment', {method:'POST', body:JSON.stringify({
      source_path:source,
      title:$('deliveryMusicTitle').value.trim() || deliverySourceTitle(source),
      target_seconds:Number($('deliveryMusicTarget').value || 30),
      replace_existing:true
    })});
    $('deliveryMusicOutputPath').textContent = result.path || 'data/music/完整音乐片段';
    state.textContent = `《${result.title}》已保存 ${result.segments} 段，仅供 WebUI 管理和试听。`;
    await loadDeliverySongs();
    toast('歌曲片段已保存；QQ 点歌仍发送完整歌曲');
  } catch(error) { state.textContent = '分段失败：' + error.message; }
  finally { button.disabled = false; }
}
async function importMusicStems() {
  const project = window._musicProject;
  if(!project) return toast('请先创建或选择歌曲工程');
  const vocal = $('musicImportedVocalFile').files[0];
  const instrumental = $('musicImportedInstrumentalFile').files[0];
  const harmony = $('musicImportedHarmonyFile').files[0];
  if(!vocal || !instrumental) return toast('主唱与伴奏音频必须选择');
  const button = $('musicImportStemsButton');
  button.disabled = true;
  $('musicProjectState').textContent = '正在上传并导入外部分离音频，请保持页面打开...';
  const form = new FormData();
  form.append('id', project.id);
  form.append('vocal', vocal);
  form.append('instrumental', instrumental);
  if(harmony) form.append('harmony', harmony);
  try {
    const data = await api('/api/music/project/stems', {method:'POST', body:form});
    renderMusicProject(data.project);
    await loadMusicTerminal(data.project.id, 'separation');
    $('musicImportedVocalFile').value = '';
    $('musicImportedInstrumentalFile').value = '';
    $('musicImportedHarmonyFile').value = '';
    toast('外部分离音频已导入，可确认后进入模型推理');
  } catch(error) {
    $('musicProjectState').textContent = '导入外部分离音频失败：' + error.message;
  } finally {
    button.disabled = false;
  }
}
async function loadMusicSources(preferredPath='') {
  const select = $('musicSourceLibrary');
  if(!select) return;
  try {
    const data = await api('/api/music/sources');
    const sources = Array.isArray(data.sources) ? data.sources : [];
    const current = preferredPath || $('singingSourcePath').value || select.value;
    select.innerHTML = '<option value="">从固定目录选择，或在下方上传</option>' + sources.map(source=>`<option value="${escapeHtml(source.path)}">${escapeHtml(source.name)}</option>`).join('');
    if(sources.some(source=>source.path===current)) select.value = current;
    if(select.value) $('singingSourcePath').value = select.value;
  } catch(error) {
    toast('歌曲素材库读取失败：' + error.message);
  }
}
function selectMusicSource() {
  $('singingSourcePath').value = $('musicSourceLibrary').value || '';
}
function musicStageLabel(status) {
  return ({pending:'等待',running:'处理中',succeeded:'已完成',failed:'失败'})[status] || status || '等待';
}
function musicArtifactUrl(project, name) {
  const path = project?.artifact_urls?.[name];
  return path ? `/api/music/project/audio?id=${encodeURIComponent(project.id)}&name=${encodeURIComponent(name)}` : '';
}
function setMusicAudio(audioId, canvasId, url) {
  const audio = $(audioId);
  const canvas = $(canvasId);
  if(!audio || !canvas) return;
  if(audio.dataset.audioUrl !== (url || '')) {
    audio.pause();
    audio.removeAttribute('src');
    audio.load();
    audio.dataset.audioUrl = url || '';
    canvas.dataset.waveKey = '';
    drawEmptyMusicWaveform(canvas);
  }
}
function releaseMusicMedia() {
  for(const [audioId,canvasId] of [
    ['musicVocalAudio','musicVocalWave'],
    ['musicHarmonyAudio','musicHarmonyWave'],
    ['musicInstrumentalAudio','musicInstrumentalWave'],
    ['musicConvertedAudio','musicConvertedWave'],
    ['musicMixAudio','musicMixWave']
  ]) {
    const audio = $(audioId), canvas = $(canvasId);
    if(audio) { audio.pause(); audio.removeAttribute('src'); audio.load(); }
    if(canvas) { canvas.dataset.waveKey=''; drawEmptyMusicWaveform(canvas); }
  }
}
function drawEmptyMusicWaveform(canvas) {
  const width = Math.max(240, Math.floor(canvas.clientWidth || 480));
  const height = Math.max(64, Math.floor(canvas.clientHeight || 78));
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext('2d');
  context.fillStyle = '#eef2f7'; context.fillRect(0,0,width,height);
  context.strokeStyle = '#cbd5e1'; context.beginPath(); context.moveTo(0,height/2); context.lineTo(width,height/2); context.stroke();
}
async function loadMusicPreview(audioId, canvasId, name, selectable=false) {
  const project = window._musicProject;
  const audio = $(audioId), canvas = $(canvasId);
  if(!project || !audio || !canvas) return toast('当前音轨尚未生成');
  const url = musicArtifactUrl(project, name);
  if(!url) return toast('当前音轨尚未生成');
  if(audio.getAttribute('src') !== url) {
    audio.src = url;
    audio.load();
  }
  await drawMusicWaveform(canvas, project.id, name);
  if(selectable) setupMusicSelection(canvas);
  toast('试听已按需加载，不会在进入页面时占用整曲内存');
}
async function drawMusicWaveform(canvas, projectId, name) {
  const key = `${projectId}:${name}`;
  if(canvas.dataset.waveKey === key) return;
  drawEmptyMusicWaveform(canvas);
  try {
    const data = await api(`/api/music/project/waveform?id=${encodeURIComponent(projectId)}&name=${encodeURIComponent(name)}`);
    const peaks = Array.isArray(data.peaks) ? data.peaks : [];
    if(!peaks.length) throw new Error('波形为空');
    window._musicWaveData = window._musicWaveData || {};
    window._musicWaveData[canvas.id] = {peaks,duration:Number(data.duration_seconds || 0)};
    paintMusicWaveform(canvas);
    canvas.dataset.waveKey = key;
  } catch(error) {
    canvas.dataset.waveKey = '';
    toast('波形加载失败：' + error.message);
  }
}
function paintMusicWaveform(canvas) {
  const data = window._musicWaveData?.[canvas.id];
  if(!data) return drawEmptyMusicWaveform(canvas);
  const width = canvas.width, height = canvas.height, center = height/2;
  const context = canvas.getContext('2d');
  context.fillStyle = '#eef2f7'; context.fillRect(0,0,width,height);
  context.strokeStyle = '#2563eb'; context.lineWidth = 1; context.beginPath();
  for(let x=0; x<width; x++) {
    const peak = Number(data.peaks[Math.min(data.peaks.length-1, Math.floor(x * data.peaks.length / width))] || 0);
    context.moveTo(x, center - peak * center * .9); context.lineTo(x, center + peak * center * .9);
  }
  context.stroke();
  if(canvas.id==='musicConvertedWave' && data.duration>0) {
    const start = Math.max(0, parseMusicTimeSeconds($('musicSelectionStart').value || 0));
    const end = Math.min(data.duration, parseMusicTimeSeconds($('musicSelectionEnd').value || 0));
    if(end>start) {
      const left = start / data.duration * width, right = end / data.duration * width;
      context.fillStyle = 'rgba(37,99,235,.18)'; context.fillRect(left,0,right-left,height);
      context.strokeStyle = '#1d4ed8'; context.lineWidth = 2; context.strokeRect(left+1,1,Math.max(1,right-left-2),height-2);
    }
  }
}
function parseMusicTimeSeconds(value) {
  const text = String(value ?? '').trim();
  if(text.includes(':')) {
    const parts = text.split(':');
    if(parts.length !== 2 && parts.length !== 3) return NaN;
    const seconds = Number(parts[parts.length - 1]);
    const minutes = Number(parts[parts.length - 2]);
    const hours = parts.length === 3 ? Number(parts[0]) : 0;
    if(!Number.isFinite(hours) || !Number.isFinite(minutes) || !Number.isFinite(seconds) || hours < 0 || minutes < 0 || seconds < 0 || seconds >= 60) return NaN;
    return hours * 3600 + minutes * 60 + seconds;
  }
  const seconds = Number(text);
  return Number.isFinite(seconds) ? seconds : NaN;
}
function setupMusicSelection(canvas) {
  if(canvas.dataset.selectionReady==='1') return;
  canvas.dataset.selectionReady = '1';
  let anchor = null;
  const secondsAt = event => {
    const data = window._musicWaveData?.[canvas.id];
    const rect = canvas.getBoundingClientRect();
    return data ? Math.max(0,Math.min(data.duration,(event.clientX-rect.left)/rect.width*data.duration)) : 0;
  };
  canvas.addEventListener('pointerdown', event=>{ anchor=secondsAt(event); canvas.setPointerCapture(event.pointerId); });
  canvas.addEventListener('pointermove', event=>{
    if(anchor===null) return;
    const cursor=secondsAt(event), start=Math.min(anchor,cursor), end=Math.max(anchor,cursor);
    $('musicSelectionStart').value=start.toFixed(2); $('musicSelectionEnd').value=Math.max(start+.05,end).toFixed(2); paintMusicWaveform(canvas);
  });
  canvas.addEventListener('pointerup', event=>{ if(anchor!==null){ const cursor=secondsAt(event); selectMusicRange(Math.min(anchor,cursor),Math.max(anchor,cursor)); } anchor=null; });
}
function selectMusicRange(start,end) {
  $('musicSelectionStart').value=Math.max(0,start).toFixed(2);
  $('musicSelectionEnd').value=Math.max(start+.05,end).toFixed(2);
  const canvas=$('musicConvertedWave'); if(canvas) paintMusicWaveform(canvas);
}
function previewSelectedMusicRange() {
  const audio=$('musicConvertedAudio'), project=window._musicProject;
  if(!audio || !project) return;
  const url=musicArtifactUrl(project,'converted');
  if(!url) return toast('请先完成整曲推理');
  if(audio.getAttribute('src')!==url){ audio.src=url; audio.load(); }
  const start=parseMusicTimeSeconds($('musicSelectionStart').value||0), end=parseMusicTimeSeconds($('musicSelectionEnd').value||0);
  if(!Number.isFinite(start) || !Number.isFinite(end) || end<=start) return toast('请输入有效的秒数或 MM:SS 时间');
  if(end-start<.25) return toast('局部精修至少选择 0.25 秒，避免模型在断句处产生卡顿');
  audio.currentTime=start; audio.play();
  clearTimeout(window._musicRangeTimer); window._musicRangeTimer=setTimeout(()=>audio.pause(),Math.max(50,(end-start)*1000));
}
function formatMusicTime(seconds) {
  const value = Math.max(0, Number(seconds || 0));
  const minutes = Math.floor(value / 60);
  return `${minutes}:${String(Math.floor(value % 60)).padStart(2,'0')}`;
}
function renderMusicSections(analysis, phrasePlan) {
  const out = $('musicSectionList');
  if(!out) return;
  const sections = Array.isArray(analysis?.sections) ? analysis.sections : [];
  if(!sections.length) {
    out.innerHTML = '<div class="note">完成人声分离后显示自动乐理分段。</div>';
    return;
  }
  const summary = `<div class="note">${escapeHtml(analysis.tempo_bpm || '—')} BPM · ${escapeHtml(analysis.estimated_key || '调性待定')} · ${escapeHtml(analysis.meter_hint || '')} · ${sections.length} 段</div>`;
  const phrases = Array.isArray(phrasePlan?.phrases) ? phrasePlan.phrases : [];
  const phraseButtons = phrases.length ? `<div class="row"><span class="param-help">换气乐句：</span>${phrases.slice(0,30).map(phrase=>`<button class="ghost" onclick="selectMusicRange(${Number(phrase.start_seconds)},${Number(phrase.end_seconds)})">${escapeHtml(phrase.id)} · ${formatMusicTime(phrase.start_seconds)}–${formatMusicTime(phrase.end_seconds)}</button>`).join('')}</div>` : '';
  out.innerHTML = summary + sections.map(section=>`<div class="music-section-item"><span class="index">${Number(section.index || 0)}</span><span><strong>${escapeHtml(section.label || '乐段')}</strong><span class="param-help">${escapeHtml(section.reason || '')}</span></span><span class="time">${formatMusicTime(section.start_seconds)}–${formatMusicTime(section.end_seconds)}</span></div>`).join('') + phraseButtons;
}
function renderMusicQuality(quality) {
  const out=$('musicInferenceQuality'); if(!out) return;
  const checks=Array.isArray(quality?.checks)?quality.checks:[];
  if(!checks.length){ out.innerHTML='<div class="note">整曲推理后显示接缝、静音、音高与削波检查。</div>'; return; }
  const eventGroups=quality?.events&&typeof quality.events==='object'?Object.values(quality.events):[];
  const events=eventGroups.flatMap(group=>Array.isArray(group)?group:[]).sort((a,b)=>Number(a.start_seconds||0)-Number(b.start_seconds||0));
  const eventButtons=events.length?`<div class="row"><span class="param-help">可疑时间点：</span>${events.slice(0,30).map(event=>`<button class="ghost" onclick="selectMusicRange(${Number(event.start_seconds)},${Number(event.end_seconds)});previewSelectedMusicRange()">${formatMusicTime(event.start_seconds)}–${formatMusicTime(event.end_seconds)}</button>`).join('')}</div>`:'';
  out.innerHTML=checks.map(check=>`<div class="music-quality-item ${check.passed?'pass':'fail'}"><strong>${check.passed?'通过':'需检查'} · ${escapeHtml(check.label||check.id)}</strong><span class="param-help">${escapeHtml(check.reference||'')} · 实测 ${escapeHtml(check.value??'无有效音高')}</span></div>`).join('')+eventButtons;
}
function renderMusicRevisions(project) {
  const select=$('musicRevisionSelect'); if(!select) return;
  const revisions=Array.isArray(project?.revisions)?project.revisions:[];
  select.innerHTML=revisions.length?revisions.slice().reverse().map(revision=>`<option value="${escapeHtml(revision.id)}">${escapeHtml(revision.label||revision.stage)} · ${escapeHtml(revision.id)}</option>`).join(''):'<option value="">暂无版本</option>';
}
async function loadMusicTerminal(projectId, stage) {
  const terminal = $('musicTerminal');
  if(!terminal || !projectId || !stage) return;
  try {
    const data = await api(`/api/music/project/log?id=${encodeURIComponent(projectId)}&stage=${encodeURIComponent(stage)}`);
    terminal.textContent = data.log || '当前阶段尚未产生终端字幕。';
    terminal.scrollTop = terminal.scrollHeight;
  } catch(error) {
    terminal.textContent = '终端字幕读取失败：' + error.message;
  }
}
function renderMusicProject(project) {
  window._musicProject = project || null;
  if(!project) {
    $('musicProjectState').textContent = '创建工程后，可以逐阶段生成并试听。';
    ['Separation','Inference','Mix'].forEach(name=>{
      $('music'+name+'State').textContent = '等待';
      $('music'+name+'State').className = 'music-stage-state';
    });
    renderMusicSections(null, null);
    renderMusicQuality(null);
    renderMusicRevisions(null);
    releaseMusicMedia();
    $('musicTerminal').textContent = '选择歌曲工程后显示阶段字幕。';
    return;
  }
  const stages = project.stages || {};
  const separation = stages.separation || {};
  const inference = stages.inference || {};
  const mix = stages.mix || {};
  const exportPath = project.artifacts?.export ? ` · 已导出：${project.artifacts.export}` : '';
  $('musicProjectState').textContent = `${project.name} · ${project.message || ''}${project.error ? ' · '+project.error : ''}${exportPath}`;
  renderMusicSections(project.analysis, project.phrase_plan);
  renderMusicQuality(project.quality?.inference);
  renderMusicRevisions(project);
  for(const [name,stage] of [['Separation',separation],['Inference',inference],['Mix',mix]]) {
    const state = stage.status || 'pending';
    $('music'+name+'State').textContent = musicStageLabel(state);
    $('music'+name+'State').className = 'music-stage-state ' + state;
    const card = $('musicStage'+name);
    card.classList.remove('ready','running','succeeded','failed');
    card.classList.add(state==='pending' ? 'ready' : state);
  }
  const busy = project.state === 'running' || project.state === 'exporting';
  const guided = project.parameters?.workflow?.mode !== 'automatic';
  $('musicRunSeparation').disabled = busy;
  $('musicRunInference').disabled = busy || separation.status !== 'succeeded' || (guided && separation.confirmation!=='confirmed');
  $('musicRunMix').disabled = busy || inference.status !== 'succeeded' || (guided && inference.confirmation!=='confirmed');
  $('musicRunPipeline').disabled = busy;
  $('musicRerunSegment').disabled = busy || inference.status !== 'succeeded';
  $('musicExportButton').disabled = busy || mix.status !== 'succeeded';
  const params = project.parameters || {};
  $('musicWorkflowMode').value = params.workflow?.mode || 'guided';
  $('musicSectionCount').value = params.separation?.section_count ?? 0;
  $('musicSeparationModel').value = params.separation?.model || 'mdx_net';
  $('musicSeparationPreset').value = params.separation?.preset || 'standard';
  $('musicSeparateHarmony').checked = params.separation?.separate_harmony !== false;
  $('musicPitchShift').value = params.inference?.pitch_shift ?? 0;
  $('musicDiffusionSteps').value = params.inference?.diffusion_steps ?? 35;
  $('musicStyle').value = params.inference?.style || 'natural';
  $('musicContextSeconds').value = params.inference?.context_seconds ?? 3;
  $('musicEmotionStrength').value = params.inference?.emotion_strength ?? .55;
  $('musicBreathiness').value = params.inference?.breathiness ?? .02;
  $('musicVibrato').value = params.inference?.vibrato ?? 0;
  $('musicArticulation').value = params.inference?.articulation ?? .60;
  $('musicFormantShift').value = params.inference?.formant_shift ?? .6;
  $('musicSegmentPitch').value = params.inference?.pitch_shift ?? 0;
  $('musicVocalGain').value = params.mix?.vocal_gain_db ?? 0;
  $('musicInstrumentalGain').value = params.mix?.instrumental_gain_db ?? -1.7;
  $('musicDucking').value = params.mix?.ducking_db ?? 3;
  $('musicHarmonyGain').value = params.mix?.harmony_gain_db ?? -120;
  $('musicEqPresence').value = params.mix?.eq_presence_db ?? -1;
  $('musicEqAir').value = params.mix?.eq_air_db ?? 1.2;
  $('musicCompressorThreshold').value = params.mix?.compressor_threshold_db ?? -18;
  $('musicCompressorRatio').value = params.mix?.compressor_ratio ?? 2.5;
  $('musicDeesser').value = params.mix?.deesser_strength ?? .35;
  $('musicSaturation').value = params.mix?.saturation_db ?? 1;
  $('musicReverb').value = params.mix?.reverb ?? 0.08;
  $('musicDelayMs').value = params.mix?.delay_ms ?? 90;
  $('musicDelayMix').value = params.mix?.delay_mix ?? .04;
  $('musicExportPreset').value = params.export?.preset || 'live';
  $('musicExportFormat').value = params.export?.format || 'wav';
  $('musicExportLufs').value = params.export?.lufs ?? -14;
  if(window._musicSelectionProject!==project.id) {
    const firstPhrase=project.phrase_plan?.phrases?.[0];
    selectMusicRange(Number(firstPhrase?.start_seconds||0),Number(firstPhrase?.end_seconds||Math.min(15,project.phrase_plan?.duration_seconds||15)));
    window._musicSelectionProject=project.id;
  }
  setMusicAudio('musicVocalAudio','musicVocalWave',musicArtifactUrl(project,'vocal'));
  setMusicAudio('musicHarmonyAudio','musicHarmonyWave',musicArtifactUrl(project,'harmony'));
  setMusicAudio('musicInstrumentalAudio','musicInstrumentalWave',musicArtifactUrl(project,'instrumental'));
  setMusicAudio('musicConvertedAudio','musicConvertedWave',musicArtifactUrl(project,'converted'));
  setMusicAudio('musicMixAudio','musicMixWave',musicArtifactUrl(project,'mix'));
  clearTimeout(window._musicProjectTimer);
  if(busy && window._voiceMusicActive) window._musicProjectTimer = setTimeout(()=>loadMusicProject(project.id), 2500);
}
async function loadMusicProjects() {
  if(window._musicProjectsPromise) return window._musicProjectsPromise;
  const state = $('musicProjectState');
  if(!state) return;
  window._musicProjectsPromise = (async()=>{ try {
    const data = await api('/api/music/projects');
    const projects = Array.isArray(data.projects) ? data.projects : [];
    const select = $('musicProjectSelect');
    const current = select.value || window._musicProject?.id || '';
    select.innerHTML = projects.map(project=>`<option value="${escapeHtml(project.id)}">${escapeHtml(project.name)} · ${escapeHtml(project.message || project.state)}</option>`).join('');
    if(projects.some(project=>project.id===current)) select.value = current;
    if(!select.options.length) {
      select.innerHTML = '<option value="">尚未创建工程</option>';
      renderMusicProject(null);
      return;
    }
    await loadMusicProject(select.value);
    window._musicProjectsLoaded = true;
  } catch(error) {
    state.textContent = '歌曲工程读取失败：' + error.message;
  } finally {
    window._musicProjectsPromise = null;
  }})();
  return window._musicProjectsPromise;
}
async function loadMusicProject(projectId) {
  if(!projectId) return renderMusicProject(null);
  try {
    const data = await api('/api/music/project?id=' + encodeURIComponent(projectId));
    renderMusicProject(data.project);
    await loadMusicTerminal(data.project.id, data.project.current_stage || 'separation');
  } catch(error) {
    $('musicProjectState').textContent = '工程读取失败：' + error.message;
  }
}
function selectMusicProject() {
  loadMusicProject($('musicProjectSelect').value);
}
async function createMusicProject() {
  const source = $('singingSourcePath').value.trim();
  const reference = $('singingReferencePath').value.trim();
  if(!source) return toast('请先上传原曲');
  if(!reference) return toast('没有可用的亚托莉歌声参考');
  const button = $('musicCreateProjectButton');
  button.disabled = true;
  $('musicProjectState').textContent = '正在创建歌曲工程并复制素材...';
  try {
    const data = await api('/api/music/project/create', {method:'POST', body:JSON.stringify({
      name:$('singingSongName').value.trim() || '亚托莉歌曲工程',
      source_audio_path:source,
      reference_audio_path:reference,
      workflow_mode:$('musicWorkflowMode').value,
      section_count:Number($('musicSectionCount').value || 0),
      model:$('musicSeparationModel').value,
      preset:$('musicSeparationPreset').value,
      separate_harmony:$('musicSeparateHarmony').checked,
      context_seconds:Number($('musicContextSeconds').value || 3)
    })});
    await loadMusicProjects();
    $('musicProjectSelect').value = data.project.id;
    await loadMusicProject(data.project.id);
    toast('歌曲工程已创建');
  } catch(error) {
    $('musicProjectState').textContent = '工程创建失败：' + error.message;
  } finally {
    button.disabled = false;
  }
}
function musicStageParameters(stage) {
  if(stage==='separation') return {
    section_count:Number($('musicSectionCount').value || 0),
    model:$('musicSeparationModel').value,
    preset:$('musicSeparationPreset').value,
    separate_harmony:$('musicSeparateHarmony').checked
  };
  if(stage==='inference') return {
    pitch_shift:Number($('musicPitchShift').value || 0),
    diffusion_steps:Number($('musicDiffusionSteps').value || 35),
    style:$('musicStyle').value,
    context_seconds:Number($('musicContextSeconds').value || 3),
    emotion_strength:Number($('musicEmotionStrength').value || .55),
    breathiness:Number($('musicBreathiness').value || 0),
    vibrato:Number($('musicVibrato').value || 0),
    articulation:Number($('musicArticulation').value || .60),
    formant_shift:Number($('musicFormantShift').value || 0)
  };
  return {
    vocal_gain_db:Number($('musicVocalGain').value || 0),
    instrumental_gain_db:Number($('musicInstrumentalGain').value || -1.7),
    eq_presence_db:Number($('musicEqPresence').value || -1),
    eq_air_db:Number($('musicEqAir').value || 1.2),
    compressor_threshold_db:Number($('musicCompressorThreshold').value || -18),
    compressor_ratio:Number($('musicCompressorRatio').value || 2.5),
    deesser_strength:Number($('musicDeesser').value || .35),
    saturation_db:Number($('musicSaturation').value || 1),
    reverb:Number($('musicReverb').value || .08),
    delay_ms:Number($('musicDelayMs').value || 90),
    delay_mix:Number($('musicDelayMix').value || .04),
    ducking_db:Number($('musicDucking').value || 3),
    harmony_gain_db:Number($('musicHarmonyGain').value || -120)
  };
}
async function runMusicStage(stage) {
  const project = window._musicProject;
  if(!project) return toast('请先创建或选择歌曲工程');
  const parameters = musicStageParameters(stage);
  const button = $({separation:'musicRunSeparation',inference:'musicRunInference',mix:'musicRunMix'}[stage]);
  button.disabled = true;
  try {
    const data = await api('/api/music/project/stage', {method:'POST', body:JSON.stringify({id:project.id,stage,parameters})});
    renderMusicProject(data.project);
  } catch(error) {
    $('musicProjectState').textContent = '阶段提交失败：' + error.message;
    button.disabled = false;
  }
}
async function runMusicPipeline() {
  const project=window._musicProject; if(!project) return toast('请先创建歌曲工程');
  const button=$('musicRunPipeline'); button.disabled=true;
  try {
    const data=await api('/api/music/project/pipeline',{method:'POST',body:JSON.stringify({
      id:project.id,
      mode:$('musicWorkflowMode').value,
      parameters:{separation:musicStageParameters('separation'),inference:musicStageParameters('inference'),mix:musicStageParameters('mix')}
    })});
    renderMusicProject(data.project);
  } catch(error) { $('musicProjectState').textContent='完整流程启动失败：'+error.message; button.disabled=false; }
}
async function confirmMusicStage(stage) {
  const project=window._musicProject; if(!project) return;
  try {
    const data=await api('/api/music/project/confirm',{method:'POST',body:JSON.stringify({id:project.id,stage})});
    renderMusicProject(data.project);
  } catch(error) { toast('阶段确认失败：'+error.message); }
}
async function resetMusicStage(stage) {
  const project=window._musicProject; if(!project) return;
  if(!confirm('重置会切回该阶段，但历史版本仍可恢复。继续吗？')) return;
  try {
    const data=await api('/api/music/project/reset',{method:'POST',body:JSON.stringify({id:project.id,stage})});
    renderMusicProject(data.project);
  } catch(error) { toast('阶段重置失败：'+error.message); }
}
async function rollbackMusicProject() {
  const project=window._musicProject, revisionId=$('musicRevisionSelect').value;
  if(!project || !revisionId) return toast('请选择历史版本');
  if(!confirm('恢复后当前状态也会先自动备份。确认恢复所选版本吗？')) return;
  try {
    const data=await api('/api/music/project/rollback',{method:'POST',body:JSON.stringify({id:project.id,revision_id:revisionId})});
    renderMusicProject(data.project);
  } catch(error) { toast('版本恢复失败：'+error.message); }
}
async function recoverMusicProject() {
  const project=window._musicProject; if(!project) return;
  try {
    const data=await api('/api/music/project/recover',{method:'POST',body:JSON.stringify({id:project.id})});
    renderMusicProject(data.project);
  } catch(error) { toast('自动备份恢复失败：'+error.message); }
}
async function rerunMusicSegment() {
  const project=window._musicProject; if(!project) return;
  const start=parseMusicTimeSeconds($('musicSelectionStart').value||0), end=parseMusicTimeSeconds($('musicSelectionEnd').value||0);
  if(!Number.isFinite(start) || !Number.isFinite(end) || end<=start) return toast('请输入有效的秒数或 MM:SS 时间');
  if(end-start<.25) return toast('局部精修至少选择 0.25 秒，避免模型在断句处产生卡顿');
  const button=$('musicRerunSegment'); button.disabled=true;
  try {
    const data=await api('/api/music/project/segment',{method:'POST',body:JSON.stringify({
      id:project.id,start_seconds:start,end_seconds:end,
      pitch_shift:Number($('musicSegmentPitch').value||0),
      diffusion_steps:Number($('musicDiffusionSteps').value||35),style:$('musicStyle').value,
      context_seconds:Number($('musicContextSeconds').value||3),
      emotion_strength:Number($('musicEmotionStrength').value||.55),
      breathiness:Number($('musicBreathiness').value||0),vibrato:Number($('musicVibrato').value||0),
      articulation:Number($('musicArticulation').value||.60),formant_shift:Number($('musicFormantShift').value||0)
    })});
    renderMusicProject(data.project);
  } catch(error) { toast('局部重跑失败：'+error.message); button.disabled=false; }
}
async function exportMusicProject() {
  const project=window._musicProject; if(!project) return;
  const button=$('musicExportButton'); button.disabled=true;
  try {
    const data=await api('/api/music/project/export',{method:'POST',body:JSON.stringify({
      id:project.id,preset:$('musicExportPreset').value,format:$('musicExportFormat').value,
      lufs:Number($('musicExportLufs').value||-14),true_peak_db:-1
    })});
    renderMusicProject(data.project);
  } catch(error) { toast('导出失败：'+error.message); button.disabled=false; }
}
function singingStateText(state) {
"""
