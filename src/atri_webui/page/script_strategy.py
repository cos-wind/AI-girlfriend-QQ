from __future__ import annotations

PART = r"""window._replyStrategy = null;
const replyStrategyModeLabels = {
  auto:'自动判断', allow:'允许聊天', deny:'不回复', quiet:'只记录',
  mention:'仅 @ 回复', smart:'smart', silence:'silence'
};
// 群聊只有三种模式，和「对象例外」里那段说明一一对应；私聊没有 @ 的概念，用另一组。
// 名字故意保留英文：这三个词是配置里真实存的值，中文标签反而对不上 json。
const replyStrategyGroupModeChoices = [
  ['smart','smart：被 @ 或触发词就回'],
  ['mention','mention：仅被 @ 才回'],
  ['silence','silence：沉默，只观察'],
];
const replyStrategyUserModeChoices = [
  ['auto','跟随分档'], ['allow','强制允许'], ['deny','禁止回复'], ['quiet','只记录'],
];
// 群聊侧的历史值按等价语义折算，必须和 backend 的 GROUP_MODE_ALIASES 保持一致，
// 否则旧配置在界面上会选不中任何一项，保存后又写回一个后端不认的值。
const replyStrategyGroupModeAliases = {auto:'smart', allow:'smart', quiet:'silence', deny:'silence'};
function replyStrategyModeChoicesFor(kind) {
  return String(kind) === 'group' ? replyStrategyGroupModeChoices : replyStrategyUserModeChoices;
}
// 后端策略里还没有这两张表时用它兜底，保证页面可以编辑；保存后会以后端返回值为准。
// 数值与 reply_strategy.DEFAULT_TIERS / DEFAULT_ACTIVITY_TIERS 保持一致：都是具体数值，
// 不再用 0 当"继承全局默认"的占位（那样界面只能显示 0，看不出实际生效值）。
const replyStrategyAffectionTierFallback = [
  {id:'low', name:'较低', min_affection:0, max_affection:35, enabled:false, per_hour:30, per_day:200, cooldown_seconds:0, target_chars:48, max_parts:2, min_hours:18, max_hours:30, daily_limit:0},
  {id:'normal', name:'普通', min_affection:35, max_affection:55, enabled:true, per_hour:3, per_day:15, cooldown_seconds:0, target_chars:48, max_parts:2, min_hours:10, max_hours:24, daily_limit:1},
  {id:'familiar', name:'熟悉', min_affection:55, max_affection:70, enabled:true, per_hour:5, per_day:25, cooldown_seconds:0, target_chars:64, max_parts:2, min_hours:5, max_hours:14, daily_limit:2},
  {id:'close', name:'亲近', min_affection:70, max_affection:85, enabled:true, per_hour:8, per_day:40, cooldown_seconds:0, target_chars:72, max_parts:3, min_hours:2.5, max_hours:9, daily_limit:3},
  {id:'intimate', name:'亲密', min_affection:85, max_affection:101, enabled:true, per_hour:12, per_day:60, cooldown_seconds:0, target_chars:80, max_parts:3, min_hours:1.5, max_hours:6, daily_limit:4}
];
const replyStrategyActivityTierFallback = [
  {id:'quiet', name:'安静', min_activity:0, max_activity:20, enabled:false, per_hour:8, per_day:40, cooldown_seconds:180, continuation_max:3, target_chars:48},
  {id:'normal', name:'一般', min_activity:20, max_activity:45, enabled:true, per_hour:4, per_day:20, cooldown_seconds:180, continuation_max:2, target_chars:40},
  {id:'active', name:'活跃', min_activity:45, max_activity:70, enabled:true, per_hour:8, per_day:40, cooldown_seconds:180, continuation_max:3, target_chars:44},
  {id:'hot', name:'高热', min_activity:70, max_activity:101, enabled:true, per_hour:12, per_day:60, cooldown_seconds:240, continuation_max:3, target_chars:48}
];
function replyStrategyNormalizeMode(value, kind) {
  const mode = String(value || '').trim().toLowerCase();
  if(String(kind) === 'group') {
    const canonical = replyStrategyGroupModeAliases[mode] || mode;
    return replyStrategyGroupModeChoices.some(item=>item[0] === canonical) ? canonical : 'smart';
  }
  return replyStrategyUserModeChoices.some(item=>item[0] === mode) ? mode : 'auto';
}
function replyStrategyNumberValue(value) {
  if(value === null || value === undefined || value === '') return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}
function replyStrategyFieldNumber(input, fallback) {
  if(!input) return fallback;
  const raw = String(input.value === null || input.value === undefined ? '' : input.value).trim();
  if(!raw) return fallback;
  const number = replyStrategyNumberValue(raw);
  return number === null ? fallback : number;
}
function replyStrategyCellNumber(row, selector, fallback) {
  return replyStrategyFieldNumber(row ? row.querySelector(selector) : null, fallback);
}
function replyStrategyTextValue(value, fallback) {
  const text = String(value === null || value === undefined ? '' : value).trim();
  return text === '' ? fallback : text;
}
function replyStrategyCellText(value) {
  return value === null || value === undefined ? '' : String(value);
}
function replyStrategyIsNumericId(value) {
  const text = String(value === null || value === undefined ? '' : value).trim();
  if(!text) return false;
  for(const char of text) {
    if(char < '0' || char > '9') return false;
  }
  return true;
}
function replyStrategyPolicy() {
  return (window._replyStrategy || {}).policy || {};
}
function replyStrategyRuleFor(kind, id) {
  const policy = replyStrategyPolicy();
  const bucket = String(kind) === 'group' ? (policy.groups || {}) : (policy.users || {});
  return bucket[String(id)] || null;
}
function replyStrategyRuleText(rule, kind) {
  if(!rule) return '跟随全局默认';
  const mode = replyStrategyNormalizeMode(rule.mode, kind);
  const bits = [replyStrategyModeLabels[mode]];
  if(rule.per_hour !== null && rule.per_hour !== undefined) bits.push('每小时 ' + rule.per_hour);
  if(rule.per_day !== null && rule.per_day !== undefined) bits.push('每日 ' + rule.per_day);
  return bits.join(' · ');
}
function replyStrategyModeOptions(selected, kind) {
  const mode = replyStrategyNormalizeMode(selected, kind);
  return replyStrategyModeChoicesFor(kind).map(item=>
    `<option value="${item[0]}"${item[0] === mode ? ' selected' : ''}>${item[1]}</option>`
  ).join('');
}
function replyStrategyTierTitle(tier, index) {
  const name = replyStrategyTextValue((tier || {}).name, '档位 ' + (index + 1));
  const id = replyStrategyTextValue((tier || {}).id, '');
  return '<strong>' + escapeHtml(name) + '</strong>'
    + (id ? '<div class="memory-meta mono">' + escapeHtml(id) + '</div>' : '');
}
function replyStrategyObjectName(kind, identifier, objects) {
  const list = Array.isArray(objects) ? objects : [];
  const hit = list.find(item => item && String(item.kind || '') === kind && String(item.id || '') === String(identifier));
  const name = hit ? String(hit.name || '').trim() : '';
  if(name) return name;
  return (kind === 'group' ? '群 ' : 'QQ ') + identifier;
}
// 用量摘要：状态行已从界面移除，这里只用来在「重置计数」后弹一条 toast，
// 否则重置按钮会变成一个没有任何反馈的动作。
function replyStrategyStateText(policy, counters) {
  let hourTotal = 0;
  let dayTotal = 0;
  Object.values(counters || {}).forEach(item => {
    hourTotal += Number((item || {}).hour_count || 0);
    dayTotal += Number((item || {}).day_count || 0);
  });
  const objectCount = Object.keys((policy || {}).users || {}).length + Object.keys((policy || {}).groups || {}).length;
  return '本小时已回 ' + hourTotal + ' 次 · 今日 ' + dayTotal
    + ' 次 · 例外对象 ' + objectCount + ' 个';
}
// 亲密度分档只渲染一次：好感范围、档位名、启用状态对「被动回复」和「主动发起」
// 是同一份数据，历史上两张表各填一遍好感范围，改一处漏一处。这里以回复策略的
// affection_tiers 为唯一来源，主动互动侧的 pending 值（旧配置迁移 / 刚在页面上
// 改过）在渲染时覆盖上去。
function replyStrategyTierNumber(tier, applyTo, source) {
  const value = (source || {})[applyTo];
  return value === null || value === undefined ? '' : String(value);
}
// 取主动侧字段的"权威值"。优先级：主动互动 policy（最权威，含迁移后的值）
// → 回复策略 policy（后端已解析出具体数值）→ 内置兜底常量。
//
// 这样即便 window._proactive 因为加载顺序/失败而缺失，间隔与每日上限也不会渲染成
// 空输入框 —— 空输入框会在保存时被 Number('') 变成 0，把档位数据写坏。
function replyStrategyEffectiveTier(explicit, key, fallbacks) {
  if(explicit && explicit[key] !== null && explicit[key] !== undefined) return explicit[key];
  for(const source of fallbacks){
    const value = source && source[key];
    if(value !== null && value !== undefined) return value;
  }
  return '';
}
function replyStrategyFallbacksFor(tier, kind) {
  const strategyTiers = ((window._replyStrategy || {}).policy || {})[kind === 'group' ? 'activity_tiers' : 'affection_tiers'];
  const defaults = (kind === 'group' ? replyStrategyActivityTierFallback : replyStrategyAffectionTierFallback)
    .find(item=>String(item.id) === String((tier || {}).id)) || {};
  const fromStrategy = (Array.isArray(strategyTiers) ? strategyTiers : [])
    .find(item=>String(item.id) === String((tier || {}).id)) || {};
  return [fromStrategy, defaults];
}
function replyStrategyRenderTiers(tiers) {
  const body = $('affectionTierRows');
  if(!body) return;
  const list = Array.isArray(tiers) && tiers.length ? tiers : replyStrategyAffectionTierFallback;
  const pending = replyStrategyPendingProactiveTiers();
  body.innerHTML = list.map((tier,index)=>{
    const explicit = pending[String(tier.id)];
    const fallbacks = replyStrategyFallbacksFor(tier, 'user');
    const field = (key) => replyStrategyEffectiveTier(explicit, key, fallbacks);
    const proactive = {min_hours: field('min_hours'), max_hours: field('max_hours'), daily_limit: field('daily_limit')};
    return `<tr data-tier-index="${index}" data-tier-id="${escapeHtml(tier.id || '')}">
    <td>${replyStrategyTierTitle(tier,index)}</td>
    <td><input class="tier-enabled" type="checkbox" ${tier.enabled ? 'checked' : ''}></td>
    <td><div class="row" style="margin:0"><input class="tier-min compact-input" type="number" min="0" max="100" step="1" value="${replyStrategyCellText(tier.min_affection)}"><span>至</span><input class="tier-max compact-input" type="number" min="0" max="101" step="1" value="${replyStrategyCellText(tier.max_affection)}"></div></td>
    <td><input class="tier-target-chars compact-input" type="number" min="0" max="2000" step="1" placeholder="0" value="${replyStrategyCellText(tier.target_chars)}"></td>
    <td><input class="tier-max-parts compact-input" type="number" min="0" max="20" step="1" placeholder="0" value="${replyStrategyCellText(tier.max_parts)}"></td>
    <td class="tier-group-proactive-cell"><div class="row" style="margin:0"><input class="tier-min-hours compact-input" type="number" min="0.25" max="168" step="0.25" value="${replyStrategyCellText(proactive.min_hours)}"><span>至</span><input class="tier-max-hours compact-input" type="number" min="0.25" max="336" step="0.25" value="${replyStrategyCellText(proactive.max_hours)}"></div></td>
    <td class="tier-group-proactive-cell"><input class="tier-daily-limit compact-input" type="number" min="0" max="12" step="1" value="${replyStrategyCellText(proactive.daily_limit)}"></td>
  </tr>`;
  }).join('');
}
function replyStrategyCollectTiers(baseTiers) {
  const rows = Array.from(document.querySelectorAll('#affectionTierRows tr[data-tier-index]'));
  if(!rows.length) return baseTiers;
  return rows.map((row,index)=>{
    const base = baseTiers[index] || replyStrategyAffectionTierFallback[index] || {};
    return Object.assign({}, base, {
      id: replyStrategyTextValue(base.id, row.dataset.tierId || ('affection-' + index)),
      name: replyStrategyTextValue(base.name, '档位 ' + (index + 1)),
      enabled: Boolean(row.querySelector('.tier-enabled') && row.querySelector('.tier-enabled').checked),
      min_affection: replyStrategyCellNumber(row, '.tier-min', replyStrategyNumberValue(base.min_affection) ?? 0),
      max_affection: replyStrategyCellNumber(row, '.tier-max', replyStrategyNumberValue(base.max_affection) ?? 0),
      // 频率与冷却已从界面和判定里移除；这里不再收集，保持服务端原值。
      target_chars: replyStrategyCellNumberOrBase(row, '.tier-target-chars', base.target_chars, 48),
      max_parts: replyStrategyCellNumberOrBase(row, '.tier-max-parts', base.max_parts, 2),
      // 主动互动侧：同一张表的后两列，两个保存入口都会带上它们。
      // 空输入框回落到 base，绝不写成 0（那会等于把间隔清零）。
      min_hours: replyStrategyCellNumberOrBase(row, '.tier-min-hours', base.min_hours, 3),
      max_hours: replyStrategyCellNumberOrBase(row, '.tier-max-hours', base.max_hours, 9),
      daily_limit: replyStrategyCellNumberOrBase(row, '.tier-daily-limit', base.daily_limit, 0)
    });
  });
}
function renderReplyStrategyActivityTiers(tiers) {
  const body = $('replyActivityTierRows');
  if(!body) return;
  const list = (Array.isArray(tiers) && tiers.length) ? tiers : replyStrategyActivityTierFallback;
  const pending = replyStrategyPendingGroupProactiveTiers();
  body.innerHTML = list.map((tier,index)=>{
    const explicit = pending[String(tier.id)];
    const fallbacks = replyStrategyFallbacksFor(tier, 'group');
    const field = (key) => replyStrategyEffectiveTier(explicit, key, fallbacks);
    const proactive = {min_hours: field('min_hours'), max_hours: field('max_hours'), daily_limit: field('daily_limit')};
    return `<tr data-tier-index="${index}" data-tier-id="${escapeHtml(tier.id || '')}">
    <td>${replyStrategyTierTitle(tier,index)}</td>
    <td><input class="tier-enabled" type="checkbox" ${tier.enabled ? 'checked' : ''}></td>
    <td><div class="row" style="margin:0"><input class="tier-min compact-input" type="number" min="0" max="100" step="1" value="${replyStrategyCellText(tier.min_activity)}"><span>至</span><input class="tier-max compact-input" type="number" min="0" max="101" step="1" value="${replyStrategyCellText(tier.max_activity)}"></div></td>
    <td><input class="tier-target-chars compact-input" type="number" min="0" max="2000" step="1" placeholder="0" value="${replyStrategyCellText(tier.target_chars)}"></td>
    <td class="tier-group-proactive-cell"><div class="row" style="margin:0"><input class="tier-min-hours compact-input" type="number" min="0.25" max="168" step="0.25" value="${replyStrategyCellText(proactive.min_hours)}"><span>至</span><input class="tier-max-hours compact-input" type="number" min="0.25" max="336" step="0.25" value="${replyStrategyCellText(proactive.max_hours)}"></div></td>
    <td class="tier-group-proactive-cell"><input class="tier-daily-limit compact-input" type="number" min="0" max="12" step="1" value="${replyStrategyCellText(proactive.daily_limit)}"></td>
  </tr>`;
  }).join('');
}
function renderReplyStrategyExceptions(policy, objects) {
  const body = $('replyExceptionRows');
  if(!body) return;
  const rows = [];
  [['user', (policy || {}).users || {}], ['group', (policy || {}).groups || {}]].forEach(pair=>{
    const kind = pair[0];
    const bucket = pair[1] || {};
    Object.keys(bucket).sort().forEach(identifier=>{
      const rule = bucket[identifier] || {};
      rows.push(`<tr data-exception-kind="${kind}" data-exception-id="${escapeHtml(identifier)}">
      <td><strong>${escapeHtml(replyStrategyObjectName(kind,identifier,objects))}</strong><div class="memory-meta mono">${escapeHtml(identifier)}</div></td>
      <td>${kind === 'group' ? '群聊' : '用户'}</td>
      <td><select class="exception-mode">${replyStrategyModeOptions(rule.mode, kind)}</select></td>
      <td><input class="exception-per-hour compact-input" type="number" min="0" max="5000" step="1" placeholder="跟随" value="${replyStrategyCellText(rule.per_hour)}"></td>
      <td><input class="exception-per-day compact-input" type="number" min="0" max="5000" step="1" placeholder="跟随" value="${replyStrategyCellText(rule.per_day)}"></td>
      <td><button class="danger" onclick="removeReplyExceptionObject(this)">移除</button></td>
    </tr>`);
    });
  });
  body.innerHTML = rows.length ? rows.join('')
    : '<tr><td colspan="6" class="note">还没有例外对象。分档对绝大多数对象已经够用，只有要单独放行或单独禁言时才需要新增。</td></tr>';
}
async function loadReplyStrategy() {
  let data;
  try {
    data = await api('/api/reply-strategy');
  } catch(error) {
    // 状态行已移除，读取失败时用 toast 提示，避免静默失败。
    toast('回复策略读取失败：' + error.message);
    return;
  }
  window._replyStrategy = data || {};
  const policy = (data || {}).policy || {};
  const defaults = policy.defaults || {};
  // 「回复规则」卡片已删除：enabled / unlisted_mode / 活跃时段 / group_require_mention
  // 都没有界面控件了。这几项的值仍然原样保存在 window._replyStrategy 里，保存时
  // 不会被本页改写（改它们要直接改 data/webui/reply_strategy.json）。
  // 群聊的 @ 要求现在只由「对象例外」的模式表达（smart / mention / silence）。
  // 渲染与取数分开：渲染里任何一处出错都不该拖垮后面几块表格。
  // 历史事故：这里调用了一个已被删除的 renderProactiveTierSummary()，异常被
  // try/catch 吞掉，导致它后面的群聊分档表和例外名单一起变空。
  renderPart('用户分档', ()=>{
    // 亲密度分档由 loadProactive() 统一渲染（它拿到的 policy.tiers 已经带上主动侧字段）；
    // 这里只在主动互动还没加载过时兜底，避免高级页先打开回复策略时表格空着。
    if(typeof replyStrategyTiersLoaded === 'undefined' || !replyStrategyTiersLoaded) {
      replyStrategyRenderTiers(policy.affection_tiers);
    }
    renderTierTabBadges(policy.affection_tiers);
  });
  renderPart('群聊分档', ()=>renderReplyStrategyActivityTiers(policy.activity_tiers));
  renderPart('例外名单', ()=>renderReplyStrategyExceptions(policy, (data || {}).objects));
}
// 单独包一层：某一块渲染失败时记日志并继续，不再让整页配置一起变成空白。
function renderPart(name, render) {
  try {
    render();
  } catch(error) {
    if(typeof console !== 'undefined' && console.error) console.error('[webui] ' + name + ' 渲染失败', error);
    toast(name + '渲染失败：' + (error && error.message || error));
  }
}
// 主动互动侧的两个新字段跟着同一张表走：loadProactive() 会把服务端返回的
// policy.tiers 记在这里，既用于渲染，也用于「只保存回复侧」时把主动侧数值带回去，
// 避免保存回复策略时把刚配好的主动间隔清成 0。
function replyStrategyPendingProactiveTiers() {
  const tiers = (window._proactive || {}).policy?.tiers;
  const map = {};
  (Array.isArray(tiers) ? tiers : []).forEach(tier=>{
    if(!tier || !tier.id) return;
    map[String(tier.id)] = {
      min_hours: tier.min_hours,
      max_hours: tier.max_hours,
      daily_limit: tier.daily_limit
    };
  });
  return map;
}
// 群聊主动消息的间隔与每日上限：服务端目前只有一个全局值（group_min_hours /
// group_max_hours / group_daily_limit），界面上按档位展示，各档取同一个值。
function replyStrategyPendingGroupProactiveTiers() {
  const p = (window._proactive || {}).policy || {};
  const map = {};
  (Array.isArray(p.activity_tiers) ? p.activity_tiers : []).forEach(tier=>{
    if(!tier || !tier.id) return;
    map[String(tier.id)] = {
      min_hours: tier.min_hours,
      max_hours: tier.max_hours,
      daily_limit: tier.daily_limit
    };
  });
  return map;
}
// 读单元格数字，但**绝不让空输入框变成 0**。
//
// `replyStrategyCellNumber(row, sel, 0)` 在输入框为空时会返回 0，于是一次"没显示
// 数值"的渲染就能把档位里的间隔/每日上限永久写成 0。空值一律回落到 base（即服务端
// 上一次的已知值），只有用户真的把 0 填进去才算 0。
function replyStrategyCellNumberOrBase(row, selector, baseValue, fallback) {
  const input = row.querySelector(selector);
  const raw = input ? String(input.value === null || input.value === undefined ? '' : input.value).trim() : '';
  if(raw === '') {
    const fromBase = replyStrategyNumberValue(baseValue);
    return fromBase === null ? fallback : fromBase;
  }
  return replyStrategyCellNumber(row, selector, fallback);
}
// 以服务端返回的档位表（reply_strategy 为底、主动互动侧数值覆盖）为准收集当前 DOM 快照。
function collectAffectionTiers() {
  const base = (((window._replyStrategy || {}).policy || {}).affection_tiers) || replyStrategyAffectionTierFallback;
  const pending = replyStrategyPendingProactiveTiers();
  const merged = base.map(tier=>{
    const override = pending[String(tier.id)];
    return override ? Object.assign({}, tier, override) : tier;
  });
  return replyStrategyCollectTiers(merged);
}
function collectReplyStrategyActivityTiers(baseTiers) {
  const rows = Array.from(document.querySelectorAll('#replyActivityTierRows tr[data-tier-index]'));
  if(!rows.length) return baseTiers;
  return rows.map((row,index)=>{
    const base = baseTiers[index] || replyStrategyActivityTierFallback[index] || {};
    return Object.assign({}, base, {
      id: replyStrategyTextValue(base.id, 'activity-' + index),
      name: replyStrategyTextValue(base.name, '档位 ' + (index + 1)),
      enabled: Boolean(row.querySelector('.tier-enabled') && row.querySelector('.tier-enabled').checked),
      min_activity: replyStrategyCellNumber(row, '.tier-min', replyStrategyNumberValue(base.min_activity) ?? 0),
      max_activity: replyStrategyCellNumber(row, '.tier-max', replyStrategyNumberValue(base.max_activity) ?? 0),
      // 频率 / 冷却 / 连聊上限已移除；这里不再收集，保持服务端原值。
      target_chars: replyStrategyCellNumberOrBase(row, '.tier-target-chars', base.target_chars, 44),
      // 主动发起：与用户分档同构，只不过群聊这一侧目前只有一个全局间隔。
      min_hours: replyStrategyCellNumberOrBase(row, '.tier-min-hours', base.min_hours, 3),
      max_hours: replyStrategyCellNumberOrBase(row, '.tier-max-hours', base.max_hours, 9),
      daily_limit: replyStrategyCellNumberOrBase(row, '.tier-daily-limit', base.daily_limit, 2)
    });
  });
}
function collectReplyStrategyExceptions(base) {
  const users = Object.assign({}, base.users || {});
  const groups = Object.assign({}, base.groups || {});
  document.querySelectorAll('#replyExceptionRows tr[data-exception-id]').forEach(row=>{
    const kind = String(row.dataset.exceptionKind || '') === 'group' ? 'group' : 'user';
    const identifier = String(row.dataset.exceptionId || '').trim();
    if(!identifier) return;
    const bucket = kind === 'group' ? groups : users;
    const entry = Object.assign({}, bucket[identifier] || {});
    const modeSelect = row.querySelector('.exception-mode');
    entry.mode = replyStrategyNormalizeMode(modeSelect && modeSelect.value, kind);
    // 数字留空表示跟随分档，交给后端按 null 处理；填 0 才是"这一项不限制"。
    entry.per_hour = replyStrategyCellNumber(row, '.exception-per-hour', null);
    entry.per_day = replyStrategyCellNumber(row, '.exception-per-day', null);
    bucket[identifier] = entry;
  });
  base.users = users;
  base.groups = groups;
  return base;
}
function collectReplyStrategyPolicy() {
  // 以服务端返回的整份 policy 为底稿，只覆盖本页字段；用户中心写进去的
  // 对象级规则和本页没有暴露的字段因此不会被这张表单清掉。
  const base = JSON.parse(JSON.stringify(replyStrategyPolicy()));
  base.version = Number(base.version) || 1;
  // enabled / unlisted_mode / 活跃时段 / group_require_mention：控件已移除，保持服务端原值
  // （不再从 DOM 读取，否则会因为找不到元素而被写成关闭）。策略现在是常开的，
  // 改这几项要直接改 data/webui/reply_strategy.json。
  const defaults = Object.assign({}, base.defaults || {});
  // 受众门槛字段已废除，不再提交；旧配置里残留的同名字段由后端 normalize 直接忽略。
  base.defaults = defaults;
  base.affection_tiers = collectAffectionTiers();
  base.activity_tiers = collectReplyStrategyActivityTiers(base.activity_tiers || []);
  return collectReplyStrategyExceptions(base);
}
// 回复策略和主动互动共用「亲密度分档」这一张表，所以两个保存按钮都必须提交两侧的
// 完整配置：只提交一半会把另一侧刚配好的值写回旧值（历史上两张表分开时不会互相
// 影响，合并成一张后就要一起落盘）。
async function saveReplyAndProactive(button, pendingText) {
  return withButtonBusy(button, async () => {
    // 分两段执行，**不要共用一个 catch**：
    // 1) 落盘段：任一 POST 失败 => 真的没保存
    // 2) 刷新段：POST 都已成功 => 数据已保存，只是页面重载出问题
    //
    // 历史事故：两段共用 catch，导致"数据其实已经写进去了，界面却弹保存失败"，
    // 用户完全无法判断到底存没存。错误信息必须把这件事说清楚。
    const steps = [];
    try {
      if($('proactiveEngineEnabled')) {
        steps.push('/api/config');
        await api('/api/config', {method:'POST', body:JSON.stringify({PROACTIVE_V2_ENABLED:$('proactiveEngineEnabled').checked})});
      }
      steps.push('/api/reply-strategy');
      const result = await api('/api/reply-strategy', {method:'POST', body:JSON.stringify(collectReplyStrategyPolicy())});
      if(result && result.policy) window._replyStrategy = Object.assign({}, window._replyStrategy || {}, {policy:result.policy});
      steps.push('/api/proactive/save');
      await api('/api/proactive/save', {method:'POST', body:JSON.stringify(collectProactivePolicy())});
    } catch(error) {
      const failed = steps[steps.length - 1];
      toast('保存失败于 ' + failed + '：' + (error && error.message || error));
      if(typeof console !== 'undefined' && console.error) console.error('[webui] 保存失败于 ' + failed, error);
      return;
    }

    // 到这里数据已经落盘，后面只是刷新界面。
    const refreshErrors = [];
    await Promise.all([
      refreshPart('回复策略', loadReplyStrategy, refreshErrors),
      refreshPart('主动互动', loadProactive, refreshErrors),
      refreshPart('记忆页', loadMemory, refreshErrors),
    ]);
    if(refreshErrors.length) {
      toast('配置已保存（' + refreshErrors.length + ' 处界面刷新失败：' + refreshErrors.join('、') + '，刷新页面即可）');
      if(typeof console !== 'undefined' && console.error) console.error('[webui] 刷新失败', refreshErrors);
      return;
    }
    toast('配置已保存，回复策略与主动互动已同步，记忆页计划已更新');
  }, pendingText || '保存中…');
}
// 每个刷新步骤单独兜错：任何一处失败都不该影响"已保存"这个事实。
async function refreshPart(name, reload, collector) {
  try {
    await reload();
  } catch(error) {
    collector.push(name);
    if(typeof console !== 'undefined' && console.error) console.error('[webui] ' + name + ' 刷新失败', error);
  }
}
async function saveReplyStrategy(button) {
  return saveReplyAndProactive(button, '保存中…');
}
async function resetReplyStrategyCounters(button) {
  return withButtonBusy(button, async () => {
    try {
      await api('/api/reply-strategy/reset-counters', {method:'POST', body:'{}'});
      // 状态行已移除，所以把清零后的用量直接报在 toast 里，让这次点击有反馈。
      const policy = replyStrategyPolicy();
      toast('频率计数已重置（' + replyStrategyStateText(policy, {}) + '）');
      await loadReplyStrategy();
    } catch(error) { toast('重置失败：' + error.message); }
  }, '重置中…');
}
async function addReplyExceptionObject(button) {
  const input = $('replyExceptionNewObject');
  const kindSelect = $('replyExceptionNewKind');
  const identifier = String(input && input.value || '').trim();
  if(!replyStrategyIsNumericId(identifier)) {
    toast('请填写纯数字的 QQ 号或群号');
    return;
  }
  const kind = String(kindSelect && kindSelect.value || 'user') === 'group' ? 'group' : 'user';
  // 群聊默认 smart（不额外收紧，等于原来"强制允许"），私聊默认 allow。
  const defaultMode = kind === 'group' ? 'smart' : 'allow';
  return withButtonBusy(button, async () => {
    try {
      await api('/api/reply-strategy/object', {method:'POST', body:JSON.stringify({kind:kind, id:identifier, name:'', rule:{mode:defaultMode}})});
      if(input) input.value = '';
      await loadReplyStrategy();
      toast('已新增例外对象 ' + identifier + '，模式默认 ' + defaultMode);
    } catch(error) { toast('新增失败：' + error.message); }
  }, '新增中…');
}
async function removeReplyExceptionObject(button) {
  const row = button && button.closest ? button.closest('tr') : null;
  if(!row) return;
  const kind = String(row.dataset.exceptionKind || '') === 'group' ? 'group' : 'user';
  const identifier = String(row.dataset.exceptionId || '').trim();
  if(!identifier) return;
  return withButtonBusy(button, async () => {
    try {
      await api('/api/reply-strategy/object', {method:'POST', body:JSON.stringify({kind:kind, id:identifier, name:'', rule:{}, remove:true})});
      await loadReplyStrategy();
      toast('已移除例外对象 ' + identifier + '，会回到分档判断');
    } catch(error) { toast('移除失败：' + error.message); }
  }, '移除中…');
}
async function ensureReplyStrategyLoaded() {
  if(!window._replyStrategy) await loadReplyStrategy();
}
"""
