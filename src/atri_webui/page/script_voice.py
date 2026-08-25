from __future__ import annotations

PART = r"""  const item = cfg[key] || {};
  return item.raw !== '' && item.raw !== undefined ? item.raw : item.value;
}
async function loadVoice() {
  const data = await api('/api/voice');
  window._voiceData = data;
  const cfg = data.config || {};
  const service = data.service || {};
  const asr = service.asr || {};
  const configuredProfile = String(voiceConfigValue(cfg,'VOICE_PROFILE') || 'atri');
  const profileSelect = $('voiceProfileId');
  profileSelect.innerHTML = (data.profiles || []).map(profile=>`<option value="${escapeHtml(profile.id)}">${escapeHtml(profile.display_name || profile.id)}${profile.ready ? '' : ' · 未就绪'}</option>`).join('');
  const fallbackProfile = (data.profiles || []).find(profile=>profile.ready)?.id || (data.profiles || [])[0]?.id || 'atri';
  profileSelect.value = (data.profiles || []).some(profile=>profile.id===configuredProfile) ? configuredProfile : fallbackProfile;
  $('voiceAsrEnabled').checked = String(voiceConfigValue(cfg,'VOICE_ASR_ENABLED')).toLowerCase()==='true';
  $('voiceTtsEnabled').checked = String(voiceConfigValue(cfg,'VOICE_TTS_ENABLED')).toLowerCase()==='true';
  $('voiceGroupEnabled').checked = String(voiceConfigValue(cfg,'VOICE_GROUP_ENABLED')).toLowerCase()==='true';
  $('voiceReplyToVoice').checked = String(voiceConfigValue(cfg,'VOICE_REPLY_TO_VOICE')).toLowerCase()==='true';
  $('voiceServiceUrl').value = voiceConfigValue(cfg,'VOICE_SERVICE_URL') || 'http://127.0.0.1:8790';
  $('voiceMaxChars').value = voiceConfigValue(cfg,'VOICE_MAX_CHARS') || 160;
  $('voiceCooldown').value = voiceConfigValue(cfg,'VOICE_COOLDOWN_SECONDS') || 30;
  $('voiceAsrLexicon').value = data.asr_lexicon_text || '';
  $('voiceTtsPronunciations').value = data.tts_pronunciation_text || '';
  const behavior = data.behavior || {};
  $('voiceBehaviorEnabled').checked = behavior.enabled !== false;
  $('voiceExplicitEnabled').checked = behavior.explicit_requests_enabled !== false;
  $('voiceExplicitGuardEnabled').checked = behavior.explicit_delivery_guard_enabled !== false;
  $('voiceInputReplyEnabled').checked = behavior.reply_to_voice_enabled !== false;
  $('voiceProactiveEnabled').checked = !!behavior.proactive_voice_enabled;
  $('voiceOriginalClipEnabled').checked = behavior.original_clip_enabled !== false;
  $('voiceQualityGateEnabled').checked = behavior.quality_gate_enabled !== false;
  $('voiceSingingEnabled').checked = behavior.singing_enabled !== false;
  $('voiceQualityMaxError').value = behavior.quality_max_error_rate ?? 0.22;
  $('voiceQualityRetries').value = behavior.quality_retries ?? 1;
  $('voicePrivateAutoEnabled').checked = behavior.private_autonomous_enabled !== false;
  $('voicePrivateAffection').value = behavior.private_min_affection ?? 70;
  $('voicePrivateMessages').value = behavior.private_min_messages ?? 5;
  $('voiceGroupAutoEnabled').checked = !!behavior.group_autonomous_enabled;
  $('voiceGroupActivity').value = behavior.group_min_activity ?? 65;
  $('voiceGroupMessages').value = behavior.group_min_messages ?? 20;
  $('voiceQuietStart').value = behavior.quiet_start || '00:30';
  $('voiceQuietEnd').value = behavior.quiet_end || '07:00';
  $('voiceCallsEnabled').checked = !!behavior.calls_enabled;
  $('voiceCallAffection').value = behavior.call_min_affection ?? 85;
  $('voiceCallMessages').value = behavior.call_min_messages ?? 20;
  $('voiceCallBaseUrl').value = behavior.call_base_url || 'http://127.0.0.1:8787';
  $('voiceCallExpiry').value = behavior.call_expiry_minutes ?? 10;
  $('voiceCallMaxMinutes').value = behavior.call_max_minutes ?? 30;
  loadSelectedVoiceProfile();
  const profile = (data.profiles || []).find(p=>p.id===profileSelect.value) || {};
  const library = service.original_library || {};
  const conversationSpeech = service.conversation_speech || {};
  const quality = service.quality_gate || {};
  const singing = service.singing || {};
  $('voiceServiceStatus').innerHTML = [
    ['atri_voice_service', service.ok, service.error || '127.0.0.1:8790'],
    ['语音合成', conversationSpeech.ready, conversationSpeech.ready ? (conversationSpeech.engine || 'GPT-SoVITS') : '等待合成引擎'],
    ['语音识别', asr.dependency_available && !asr.load_error, asr.loaded ? `模型已加载 · ${asr.audio_format || '原始音频'} · ${Number((asr.hotwords || []).length)} 个专有词` : (asr.loading ? '模型正在预热' : (asr.load_error || asr.model || '依赖未安装'))],
    ['角色音色', profile.ready, profile.ready ? '参考音频有效' : '等待参考音频'],
    ['原声素材库', library.available, library.available ? `${Number(library.clips || 0)} 条可检索原声` : (library.root || '素材目录不存在')],
    ['语音质量门', quality.enabled, quality.enabled ? `回读错误率上限 ${Math.round(Number(quality.maximum_error_rate || 0)*100)}% · 最多重试 ${Number(quality.retries || 0)} 次` : '当前未启用']
  ].map(([name,ok,detail])=>`<div class="pill"><div><strong>${escapeHtml(name)}</strong><div class="memory-meta">${escapeHtml(detail)}</div></div><span class="${ok?'ok':'bad'}">${ok?'就绪':'未就绪'}</span></div>`).join('');
  const singingJobs = service.singing_jobs || {};
  const external = singingJobs.external_pipeline || {};
  const manifest = external.manifest || {};
  const musicService = data.music_service || {};
  const projectService = musicService.projects || {};
  $('musicServiceStatus').innerHTML = [
    ['AI_music', musicService.ok, musicService.ok ? `${musicService.url || '127.0.0.1:8793'} · ${manifest.id || external.engine || 'Seed-VC'}` : (musicService.error || '本地桥接未启动')],
    ['三阶段工程', projectService.ready, projectService.ready ? (projectService.busy ? '正在处理歌曲阶段' : '分离、推理、混音均可用') : '工程管线未就绪'],
    ['歌声音色', singing.ready, singing.ready ? `${Number(singing.clips || 0)} 条亚托莉参考音源` : '等待歌唱参考音源'],
    ['任务队列', service.ok, `${Number(singingJobs.running || 0)} 个运行 · ${Number(singingJobs.queued || 0)} 个等待`]
  ].map(([name,ok,detail])=>`<div class="pill"><div><strong>${escapeHtml(name)}</strong><div class="memory-meta">${escapeHtml(detail)}</div></div><span class="${ok?'ok':'bad'}">${ok?'就绪':'未就绪'}</span></div>`).join('');
  const singingState = $('singingTestState');
  if(singingState) {
    singingState.textContent = external.ready
      ? `管线就绪：${manifest.id || 'Seed-VC'} · ${manifest.has_separator ? '人声分离已启用' : '不分离人声'} · ${manifest.has_mixer ? '伴奏混音已启用' : '仅输出人声'}`
      : `歌声转换管线未就绪：${external.load_error || '请检查语音服务配置'}`;
  }
  const referenceSelect = $('singingReferencePath');
  if(referenceSelect) {
    const previousReference = referenceSelect.value;
    referenceSelect.innerHTML = (data.singing_references || []).map(item=>`<option value="${escapeHtml(item.path)}">${escapeHtml(item.relative_path || item.name)}</option>`).join('');
    if((data.singing_references || []).some(item=>item.path===previousReference)) referenceSelect.value = previousReference;
    if(!referenceSelect.options.length) referenceSelect.innerHTML = '<option value="">没有找到唱歌素材</option>';
  }
}
function loadSelectedVoiceProfile() {
  const profile = (window._voiceData?.profiles || []).find(item=>item.id===$('voiceProfileId').value) || {};
  $('voiceDisplayName').value = profile.display_name || '亚托莉';
  $('voiceProvider').value = profile.tts_provider || 'gpt_sovits';
  $('voiceApiUrl').value = profile.api_url || 'http://127.0.0.1:9880/tts';
  $('voicePromptLanguage').value = profile.prompt_language || 'ja';
  $('voicePromptText').value = profile.prompt_text || '';
  $('voiceReferencePath').value = profile.reference_audio || '';
}
async function saveVoice() {
  const profileId = $('voiceProfileId').value.trim() || 'atri';
  const body = {
    config: {
      VOICE_ASR_ENABLED:$('voiceAsrEnabled').checked,
      VOICE_TTS_ENABLED:$('voiceTtsEnabled').checked,
      VOICE_GROUP_ENABLED:$('voiceGroupEnabled').checked,
      VOICE_REPLY_TO_VOICE:$('voiceReplyToVoice').checked,
      VOICE_SERVICE_URL:$('voiceServiceUrl').value.trim(),
      VOICE_PROFILE:profileId,
      VOICE_MAX_CHARS:$('voiceMaxChars').value,
      VOICE_COOLDOWN_SECONDS:$('voiceCooldown').value
    },
    asr_lexicon_text:$('voiceAsrLexicon').value,
    tts_pronunciation_text:$('voiceTtsPronunciations').value,
    behavior: {
      enabled:$('voiceBehaviorEnabled').checked,
      explicit_requests_enabled:$('voiceExplicitEnabled').checked,
      explicit_delivery_guard_enabled:$('voiceExplicitGuardEnabled').checked,
      reply_to_voice_enabled:$('voiceInputReplyEnabled').checked,
      reply_voice_probability:Number(window._voiceData?.behavior?.reply_voice_probability ?? 35),
      emotional_reply_voice_probability:Number(window._voiceData?.behavior?.emotional_reply_voice_probability ?? 70),
      private_autonomous_enabled:$('voicePrivateAutoEnabled').checked,
      private_min_affection:Number($('voicePrivateAffection').value),
      private_min_messages:Number($('voicePrivateMessages').value),
      group_autonomous_enabled:$('voiceGroupAutoEnabled').checked,
      group_min_activity:Number($('voiceGroupActivity').value),
      group_min_messages:Number($('voiceGroupMessages').value),
      proactive_voice_enabled:$('voiceProactiveEnabled').checked,
      original_clip_enabled:$('voiceOriginalClipEnabled').checked,
      quality_gate_enabled:$('voiceQualityGateEnabled').checked,
      quality_max_error_rate:Number($('voiceQualityMaxError').value),
      quality_retries:Number($('voiceQualityRetries').value),
      singing_enabled:$('voiceSingingEnabled').checked,
      quiet_start:$('voiceQuietStart').value,
      quiet_end:$('voiceQuietEnd').value,
      timezone:'Asia/Shanghai',
      calls_enabled:$('voiceCallsEnabled').checked,
      call_min_affection:Number($('voiceCallAffection').value),
      call_min_messages:Number($('voiceCallMessages').value),
      call_base_url:$('voiceCallBaseUrl').value.trim(),
      call_expiry_minutes:Number($('voiceCallExpiry').value),
      call_max_minutes:Number($('voiceCallMaxMinutes').value)
    },
    profile: {
      id:profileId,
      display_name:$('voiceDisplayName').value.trim() || '亚托莉',
      tts_provider:$('voiceProvider').value,
      api_url:$('voiceApiUrl').value.trim(),
      prompt_language:$('voicePromptLanguage').value,
      prompt_text:$('voicePromptText').value.trim()
    }
  };
  await api('/api/voice/save', {method:'POST', body:JSON.stringify(body)});
  await loadVoice();
  toast('语音配置已保存，新消息立即使用');
}
async function uploadVoiceReference() {
  const file = $('voiceReferenceFile').files[0];
  if(!file) return toast('先选择参考音频');
  const form = new FormData();
  form.append('profile_id', $('voiceProfileId').value.trim() || 'atri');
  form.append('file', file);
  await api('/api/voice/reference', {method:'POST', body:form});
  await loadVoice();
  toast('参考音频已保存');
}
async function uploadSingingSource() {
  const file = $('singingSourceFile').files[0];
  if(!file) return toast('先选择导唱或歌曲音频');
  const out = $('musicProjectState');
  out.textContent = '正在上传原曲到固定素材库...';
  const form = new FormData();
  form.append('file', file);
  try {
    const result = await api('/api/voice/singing/source', {method:'POST', body:form});
    $('singingSourcePath').value = result.path || '';
    await loadMusicSources(result.path || '');
    out.textContent = `原曲已进入 QQmusic-MP3 素材库：${result.name || file.name}`;
  } catch(error) {
    out.textContent = '上传失败：' + error.message;
  }
}
function deliverySourceTitle(path) {
"""
