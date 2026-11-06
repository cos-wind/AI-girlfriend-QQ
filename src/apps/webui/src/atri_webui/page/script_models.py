from __future__ import annotations

PART = r"""  const data = await api('/api/model-profiles');
  window._profiles = data.profiles || [];
  window._providerCatalog = data.provider_catalog || [];
  window._activeProfileIds = data.active_ids || {};
  window._profileTypes = data.profile_types || [];
  $('currentModel').innerHTML = renderCurrentModels(data.current_by_type || {chat:data.current || {}});
  $('profileList').innerHTML = renderProfileColumns(window._profiles);
  renderProviderSelectors();
  await loadLocalModels();
}
function renderProfileColumns(profiles) {
  const types = [
    {id:'chat', name:'聊天模型'},
    {id:'vision', name:'视觉模型'},
    {id:'embedding', name:'向量模型'}
  ];
  return `<div class="profile-columns">${types.map(type=>{
    const rows = profiles
      .map((profile,index)=>({profile,index}))
      .filter(item=>(item.profile.model_type || 'chat') === type.id);
    return `<div class="profile-column">
      <h3><span>${escapeHtml(type.name)}</span><span class="badge">${rows.length}</span></h3>
      ${rows.map(item=>renderProfileCard(item.profile, item.index)).join('') || '<p class="note">暂无此类档案。</p>'}
    </div>`;
  }).join('')}</div>`;
}
function renderProfileCard(p, index) {
  const active = p.id===(window._activeProfileIds || {})[p.model_type];
  return `
    <div class="profile ${active?'active':''}">
      <div class="profile-title">
        <div><strong>${escapeHtml(p.name)}</strong><br><span class="note">${escapeHtml(modelTypeLabel(p.model_type))} · ${escapeHtml(p.provider)} · ${escapeHtml(p.model)}</span></div>
        <span class="badge ${active?'active':''}">${active?'当前启用':'可选择'}</span>
      </div>
      <div class="note">接口：${escapeHtml(p.base_url)}<br>API Key：${p.has_api_key ? '已保存（' + escapeHtml(p.api_key_masked) + '）' : '未填写'}</div>
      <div class="row">
        <button class="ghost" onclick="selectProfileByIndex(${index})">编辑</button>
        ${modelTypeCanActivate(p.model_type) ? `<button onclick="activateProfileByIndex(${index})">启用为${escapeHtml(modelTypeLabel(p.model_type))}</button>` : '<button class="secondary" disabled>仅保存档案</button>'}
        <button class="danger" onclick="deleteProfileByIndex(${index})">删除</button>
      </div>
    </div>`;
}
function renderCurrentModels(currentByType) {
  return ['chat','vision','embedding'].map(type=>{
    const c = currentByType[type] || {};
    const enabled = type === 'chat' ? true : !!c.enabled;
    const title = modelTypeLabel(type);
    const status = enabled && c.model ? '已启用' : '未配置';
    return `<div class="profile ${enabled && c.model ? 'active' : ''}" style="margin-bottom:10px">
      <div class="profile-title">
        <div><strong>${escapeHtml(title)}</strong><br><span class="note">${escapeHtml(c.name || '未配置')} · ${escapeHtml(c.model || '未填写')}</span></div>
        <span class="badge ${enabled && c.model ? 'active' : 'warn'}">${status}</span>
      </div>
      <div class="note">接口：${escapeHtml(c.base_url || '未填写')}<br>API Key：${c.has_api_key ? '已保存（' + escapeHtml(c.api_key_masked) + '）' : '未填写'}${type === 'embedding' ? `<br>向量索引：${escapeHtml(c.indexed_entries ?? 0)} 条（启用后按空闲策略构建）` : ''}${type === 'chat' ? `<br>参数：温度 ${escapeHtml(c.temperature ?? '')}，重复惩罚 ${escapeHtml(c.frequency_penalty ?? '')}，最大输出 ${escapeHtml(c.max_tokens ?? '')}` : ''}</div>
    </div>`;
  }).join('');
}
function modelTypeLabel(type) {
  if(type === 'vision') return '视觉模型';
  if(type === 'embedding') return '向量模型';
  return '聊天模型';
}
function modelTypeCanActivate(type) {
  return type === 'chat' || type === 'vision' || type === 'embedding';
}
function renderProviderSelectors() {
  const providers = window._providerCatalog || [];
  const providerSelect = $('providerPreset');
  const modelSelect = $('providerModelPreset');
  if(!providerSelect || !modelSelect) return;
  providerSelect.innerHTML = providers.map(p=>`<option value="${escapeHtml(p.id)}">${escapeHtml(p.name)}</option>`).join('');
  if(providers.length && !providers.some(p=>p.id === providerSelect.value)) providerSelect.value = providers[0].id;
  renderProviderModelOptions();
}
function selectedProviderPreset() {
  const id = $('providerPreset')?.value || '';
  return (window._providerCatalog || []).find(p=>p.id === id) || null;
}
function renderProviderModelOptions() {
  const provider = selectedProviderPreset();
  const modelSelect = $('providerModelPreset');
  if(!modelSelect) return;
  const models = provider && Array.isArray(provider.models) ? provider.models : [];
  modelSelect.innerHTML = models.map(m=>`<option value="${escapeHtml(m.id)}">${escapeHtml(m.label || m.id)}</option>`).join('');
}
function selectProviderPreset() {
  renderProviderModelOptions();
}
function selectProviderModelPreset() {
  applySelectedProviderModel();
}
function applySelectedProviderModel() {
  const provider = selectedProviderPreset();
  if(!provider) return toast('没有可用厂商预设');
  const model = $('providerModelPreset')?.value || ((provider.models || [])[0] || {}).id || '';
  const modelItem = (provider.models || []).find(m=>m.id === model) || {};
  beginNewModelProfileFromFill();
  fillModelForm({
    name: `${provider.name} ${model}`.trim(),
    model_type: modelItem.model_type || inferModelType(model),
    provider: provider.provider || provider.name,
    base_url: provider.base_url || '',
    model,
    api_key: provider.api_key || '',
    temperature: provider.temperature || '0.65',
    frequency_penalty: provider.frequency_penalty || '0.35',
    max_tokens: provider.max_tokens || '260'
  }, false);
  showProfileFillFeedback(`${provider.name} ${model}`.trim());
}
async function loadLocalModels(options={}) {
  const infoEl = $('localModelInfo');
  const listEl = $('localModelList');
  if(!infoEl || !listEl) return;
  const manual = !!options.manual;
  infoEl.textContent = '正在刷新本机模型...';
  try {
    const data = await api('/api/local-models');
    window._localModels = data.models || [];
    const refreshedAt = new Date().toLocaleTimeString();
    infoEl.textContent = `目录：${data.models_path || ''} · ${data.models_path_exists ? '目录存在' : '目录不存在'} · ${data.ollama_running ? 'Ollama 已连接' : 'Ollama 未连接'} · ${window._localModels.length} 个模型 · ${refreshedAt}`;
    listEl.innerHTML = window._localModels.map((model,index)=>{
      const modelType = inferModelType(model.name);
      const kind = localModelKind(model.name);
      const selected = model.name === window._selectedLocalModelName;
      const runnable = model.source === 'ollama_api' || model.runnable === true;
      const stateText = runnable ? 'Ollama 可运行' : '仅发现模型文件';
      return `
      <div class="model-card ${selected ? 'selected' : ''}" data-model-name="${escapeHtml(model.name)}">
        <div class="model-card-head">
          <div>
            <strong>${escapeHtml(model.name)}</strong>
            <div class="note">${escapeHtml(model.parameter_size || model.family || model.source || 'local')}</div>
          </div>
          <span class="badge ${runnable && modelTypeCanActivate(modelType) ? 'active' : 'warn'}">${escapeHtml(kind)}</span>
        </div>
        <div class="note">来源：${escapeHtml(model.source || 'local')} · ${stateText}</div>
        <div class="row">
          <button class="ghost" onclick="fillLocalModelByIndex(${index})">${runnable ? '填入' : '仅填入'}${escapeHtml(modelTypeLabel(modelType))}档案</button>
        </div>
      </div>`}).join('') || '<p class="note">没有发现本机 Ollama 模型。</p>';
    if(window._selectedLocalModelName) {
      showLocalModelAction(`已填入：${window._selectedLocalModelName}。右侧档案参数已更新，确认后保存或启用。`);
    }
    if(manual) toast(`已刷新本机模型，发现 ${window._localModels.length} 个`);
  } catch(e) {
    infoEl.textContent = '读取本机模型失败：' + e.message;
    listEl.innerHTML = '';
    showLocalModelAction('');
    if(manual) toast('读取本机模型失败：' + e.message);
  }
}
function localModelKind(name) {
  const modelType = inferModelType(name);
  if(modelType === 'embedding') return '向量模型';
  if(modelType === 'vision') return '视觉模型';
  const lower = String(name || '').toLowerCase();
  if(lower.includes('r1') || lower.includes('reason')) return '推理模型';
  return '聊天模型';
}
function inferModelType(name) {
  const lower = String(name || '').toLowerCase();
  if(lower.includes('bge') || lower.includes('embed')) return 'embedding';
  if(lower.includes('vl') || lower.includes('vision')) return 'vision';
  return 'chat';
}
function fillLocalModelByIndex(index) {
  const model = (window._localModels || [])[index];
  if(!model) return;
  const modelType = inferModelType(model.name);
  const runnable = model.source === 'ollama_api' || model.runnable === true;
  window._selectedLocalModelName = model.name;
  beginNewModelProfileFromFill();
  fillModelForm({
    name: `本地 Ollama ${model.name}`,
    model_type: modelType,
    provider: 'Ollama',
    base_url: 'http://127.0.0.1:11434/v1',
    model: model.name,
    api_key: 'ollama',
    temperature: '0.60',
    frequency_penalty: '0.35',
    max_tokens: '260'
  }, false);
  markLocalModelSelected(model.name);
  showLocalModelAction(`已填入：${model.name}（${modelTypeLabel(modelType)}）。${runnable ? 'Ollama 当前可运行。' : '但 Ollama 当前没有注册这个模型，启用后可能仍会兜底。'}右侧档案参数已更新，确认后保存${modelTypeCanActivate(modelType) ? '或启用' : ''}。`);
  showProfileFillFeedback(`本地 Ollama ${model.name}`);
}
function fillModelForm(values, keepExistingName=true) {
  if(!keepExistingName || !$('profileName').value.trim()) $('profileName').value = values.name || '';
  $('profileModelType').value = values.model_type || inferModelType(values.model || '');
  $('profileProvider').value = values.provider || '';
  $('profileBaseUrl').value = values.base_url || '';
  $('profileModel').value = values.model || '';
  if(values.api_key) $('profileApiKey').value = values.api_key;
  $('profileTemperature').value = values.temperature || '0.65';
  $('profileFrequencyPenalty').value = values.frequency_penalty || '0.35';
  $('profileMaxTokens').value = values.max_tokens || '260';
}
function beginNewModelProfileFromFill() {
  selectedProfileId = "";
  $('profileId').value = "";
  $('profileFormTitle').textContent = '新建模型档案';
  for (const id of ['profileName','profileProvider','profileBaseUrl','profileModel','profileApiKey']) $(id).value = '';
  $('profileModelType').value = 'chat';
  $('profileTemperature').value = "0.65";
  $('profileFrequencyPenalty').value = "0.35";
  $('profileMaxTokens').value = "260";
  $('profileApiKey').placeholder = '输入 API Key；本地 Ollama 可填 ollama';
}
function markLocalModelSelected(name) {
  document.querySelectorAll('.model-card').forEach(card=>{
    card.classList.toggle('selected', card.dataset.modelName === name);
  });
}
function showLocalModelAction(text) {
  const el = $('localModelAction');
  if(!el) return;
  el.textContent = text || '';
  el.classList.toggle('show', !!text);
}
function showProfileFillFeedback(label) {
  const type = $('profileModelType')?.value || 'chat';
  const activateHint = modelTypeCanActivate(type)
    ? `检查参数后点击“保存档案”，需要立即生效再点“启用档案”；只会替换当前${modelTypeLabel(type)}。`
    : '当前项目还没有独立向量模型启用配置，可先保存档案备用。';
  const text = `已填入：${label}（${modelTypeLabel(type)}）。${activateHint}`;
  const el = $('modelFillFeedback');
  if(el) {
    el.textContent = text;
    el.classList.add('show');
  }
  toast(text);
  $('modelProfileEditor')?.scrollIntoView({behavior:'smooth', block:'start'});
  setTimeout(()=>$('profileName')?.focus({preventScroll:true}), 180);
}
function selectProfileByIndex(index) { const p = window._profiles[index]; if(p) selectProfile(p); }
function activateProfileByIndex(index) { const p = window._profiles[index]; if(p) activateProfile(p.id); }
function selectProfile(p) {
  selectedProfileId = p.id || "";
  $('profileFormTitle').textContent = '编辑模型档案';
  $('profileId').value = p.id || "";
  $('profileName').value = p.name || "";
  $('profileModelType').value = p.model_type || inferModelType(p.model || "");
  $('profileProvider').value = p.provider || "";
  $('profileBaseUrl').value = p.base_url || "";
  $('profileModel').value = p.model || "";
  $('profileApiKey').value = "";
  $('profileApiKey').placeholder = p.has_api_key ? '已保存，留空保持原值' : '未填写，请输入 API Key';
  $('profileTemperature').value = p.temperature || "0.65";
  $('profileFrequencyPenalty').value = p.frequency_penalty || "0.35";
  $('profileMaxTokens').value = p.max_tokens || "260";
  const feedback = $('modelFillFeedback');
  if(feedback) {
    feedback.textContent = `正在编辑：${p.name}。修改后点“保存档案”；需要生效再点“启用档案”。`;
    feedback.classList.add('show');
  }
  $('modelProfileEditor')?.scrollIntoView({behavior:'smooth', block:'start'});
  setTimeout(()=>$('profileName')?.focus({preventScroll:true}), 180);
}
function profilePayload() {
  return {
    id: $('profileId').value.trim(),
    name: $('profileName').value.trim(),
    model_type: $('profileModelType').value,
    provider: $('profileProvider').value.trim(),
    base_url: $('profileBaseUrl').value.trim(),
    model: $('profileModel').value.trim(),
    api_key: $('profileApiKey').value.trim(),
    temperature: $('profileTemperature').value.trim(),
    frequency_penalty: $('profileFrequencyPenalty').value.trim(),
    max_tokens: $('profileMaxTokens').value.trim()
  };
}
async function saveProfile() {
  const r = await api('/api/model-profiles/save', {method:'POST', body:JSON.stringify(profilePayload())});
  selectProfile(r.profile);
  await loadProfiles();
  toast('模型档案已保存');
}
async function activateProfile(id) {
  try {
    const r = await api('/api/model-profiles/activate', {method:'POST', body:JSON.stringify({id})});
    await loadProfiles(); await loadStatus(); await loadConfig();
    toast(`已启用为${modelTypeLabel(r.profile.model_type)}：${r.profile.name}`);
  } catch(e) {
    toast(e.message || '启用模型档案失败');
  }
}
async function activateSelectedProfile() {
  const id = $('profileId').value.trim() || selectedProfileId;
  if(!id) return toast('先选择或保存一个模型档案');
  await activateProfile(id);
}
async function deleteSelectedProfile() {
  const id = $('profileId').value.trim() || selectedProfileId;
  if(!id) return toast('先选择一个模型档案');
  if(!confirm('确认删除这个模型档案？不会删除 .env 里当前正在使用的配置。')) return;
  await api('/api/model-profiles/delete', {method:'POST', body:JSON.stringify({id})});
  newProfile(); await loadProfiles(); toast('模型档案已删除');
}
async function deleteProfileByIndex(index) {
  const p = window._profiles[index];
  if(!p) return toast('没有找到这个模型档案');
  if(!confirm(`确认删除模型档案“${p.name}”？不会删除 Ollama 模型文件，也不会修改当前 .env 配置。`)) return;
  try {
    await api('/api/model-profiles/delete', {method:'POST', body:JSON.stringify({id:p.id})});
    if(($('profileId').value.trim() || selectedProfileId) === p.id) newProfile();
    await loadProfiles();
    toast('模型档案已删除');
  } catch(e) {
    toast(e.message || '删除模型档案失败');
  }
}
function newProfile() {
  selectedProfileId = "";
  $('profileFormTitle').textContent = '新建模型档案';
  for (const id of ['profileId','profileName','profileProvider','profileBaseUrl','profileModel','profileApiKey']) $(id).value = '';
  $('profileModelType').value = 'chat';
  $('profileApiKey').placeholder = '输入 API Key；本地 Ollama 可填 ollama';
  $('profileTemperature').value = "0.65";
  $('profileFrequencyPenalty').value = "0.35";
  $('profileMaxTokens').value = "260";
  const feedback = $('modelFillFeedback');
  if(feedback) {
    feedback.textContent = '';
    feedback.classList.remove('show');
  }
}
function quickFillDeepSeek() {
  beginNewModelProfileFromFill();
  $('profileName').value = $('profileName').value || 'DeepSeek 官方';
  $('profileModelType').value = 'chat';
  $('profileProvider').value = 'DeepSeek';
  $('profileBaseUrl').value = 'https://api.deepseek.com/v1';
  $('profileModel').value = 'deepseek-v4-flash';
  $('profileTemperature').value = '0.65';
  $('profileFrequencyPenalty').value = '0.35';
  $('profileMaxTokens').value = '260';
  showProfileFillFeedback('DeepSeek 官方 deepseek-v4-flash');
}
function quickFillOllama() {
  beginNewModelProfileFromFill();
  $('profileName').value = $('profileName').value || '本地 Ollama Qwen3 4B';
  $('profileModelType').value = 'chat';
  $('profileProvider').value = 'Ollama';
  $('profileBaseUrl').value = 'http://127.0.0.1:11434/v1';
  $('profileModel').value = 'qwen3:4b-instruct';
  $('profileApiKey').value = 'ollama';
  $('profileTemperature').value = '0.60';
  $('profileFrequencyPenalty').value = '0.35';
  $('profileMaxTokens').value = '180';
  showProfileFillFeedback('本地 Ollama qwen3:4b-instruct');
}
function quickFillOpenAICompatible() {
  beginNewModelProfileFromFill();
  $('profileName').value = $('profileName').value || 'OpenAI 兼容模型';
  $('profileModelType').value = 'chat';
  $('profileProvider').value = 'OpenAI 兼容';
  $('profileBaseUrl').value = 'https://api.openai.com/v1';
  $('profileModel').value = 'gpt-4.1-mini';
  $('profileTemperature').value = '0.65';
  $('profileFrequencyPenalty').value = '0.35';
  $('profileMaxTokens').value = '260';
  showProfileFillFeedback('OpenAI 兼容 gpt-4.1-mini');
}
const proactiveWeightLabels = {
"""
