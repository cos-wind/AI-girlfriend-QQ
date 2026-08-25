from __future__ import annotations

PART = r"""  const s = await api('/api/status');
  const cards = [
    ['Atri 服务', s.atri, s.atri ? '正常' : '未连接'],
    ['NapCat 连接', s.napcat, s.napcat ? '正常' : '未连接'],
    [
      'Ollama',
      Boolean(s.ollama || s.ollama_on_demand),
      s.ollama ? '运行中' : (s.ollama_on_demand ? '按需可用 · 当前空闲' : '不可用')
    ],
    ['语音服务', s.voice, s.voice ? '正常' : '未连接'],
    ['WebUI', s.webui, s.webui ? '正常' : '未连接'],
    ['聊天模型', Boolean(s.model), s.model || '未配置'],
    [
      '视觉模型',
      Boolean(s.vision_available),
      s.vision_model
        ? `${s.vision_model}${s.ollama_on_demand && !s.ollama ? ' · 本地兜底按需启动' : ''}`
        : '未配置'
    ],
    [
      '认知内核',
      Boolean(s.cognition && s.cognition.available),
      s.cognition && s.cognition.enabled
        ? `影子运行 · ${Number(s.cognition.threads || 0)} 条思维线程`
        : '未启用'
    ]
  ];
  if(s.napcat_webui && s.napcat_webui.url) {
    cards.push(['NapCat WebUI', Boolean(s.napcat_webui.reachable), s.napcat_webui.reachable ? '可访问（开发页可打开链接）' : '端口未响应']);
  }
  $('status').innerHTML = cards.map(([k,v,text])=>`<div class="pill"><span>${k}</span><span class="${v?'ok':'bad'}">${escapeHtml(text)}</span></div>`).join('')
  + `<p class="note">机器人 QQ：${escapeHtml(s.bot_qq)}<br>接口：${escapeHtml(s.base_url)}<br>回复模式：${escapeHtml(s.reply_mode)}${s.napcat_detail ? '<br>NapCat：' + escapeHtml(s.napcat_detail) : ''}</p>`;
}
async function loadDeveloper(force=false) {
  try {
    const data = await api('/api/developer');
    const napcat = data.status?.napcat_webui || {};
    const maibot = data.status?.maibot_webui || {};
    const entries = [
      ['ATRI OneBot', data.status?.onebot || '', data.status?.atri],
      ['MaiBot WebUI', maibot.url || 'http://127.0.0.1:8001', maibot.reachable],
      ['NapCat WebUI', napcat.url || '', napcat.reachable]
    ];
    $('developerLinks').innerHTML = entries.map(([label,url,ok]) => {
      // 用字符串拼接生成链接片段，避免嵌套模板字符串导致页面脚本解析中断。
      if (!url) {
        return `<div class="pill"><span>${escapeHtml(label)}</span><span class="bad">未配置</span></div>`;
      }
      const destination = '<a href="' + escapeHtml(url) + '" target="_blank" rel="noreferrer">打开</a>';
       return `<div class="pill"><span>${escapeHtml(label)}</span><span class="${ok ? 'ok' : 'bad'}">${ok ? '就绪' : '未启动'}</span>${destination}</div>`;
    }).join('');
    $('developerLogHint').textContent = `每 ${data.refresh_seconds || 3} 秒读取一次当天日志；聊天正文和 Token 不会写入统一日志。`;
    await loadDeveloperLogs();
    if(force) toast('开发者状态已刷新');
  } catch(error) { $('developerLinks').textContent = '读取开发状态失败：' + error.message; }
}
async function loadDeveloperLogs() {
  const output = $('developerLog');
  if(!output) return;
  try {
    const level = $('developerLogLevel').value;
    const data = await api('/api/logs?level=' + encodeURIComponent(level) + '&limit=320');
    output.textContent = (data.lines || []).join('\n') || '今天还没有统一项目日志。';
    output.scrollTop = output.scrollHeight;
  } catch(error) { output.textContent = '日志读取失败：' + error.message; }
}
async function testCurrentChatModel() {
  const feedback = $('modelFillFeedback');
  if(feedback) {
    feedback.textContent = '正在测试当前聊天模型...';
    feedback.classList.add('show');
  }
  try {
    const r = await api('/api/test-chat', {method:'POST', body:JSON.stringify({text:'只回复 OK，用来测试当前聊天模型是否可用。'})});
    const text = r.used_ai
      ? `当前聊天模型可用。测试回复：${r.reply || ''}`
      : `当前聊天模型没有连上，正在走兜底。错误：${r.error || '未知错误'}
兜底回复：${r.reply || ''}`;
    if(feedback) feedback.textContent = text;
    toast(r.used_ai ? '当前聊天模型测试通过' : '当前聊天模型未连上，已显示错误');
  } catch(e) {
    const text = '当前聊天模型测试失败：' + (e.message || '未知错误');
    if(feedback) feedback.textContent = text;
    toast(text);
  }
}
async function loadProfiles() {
"""
