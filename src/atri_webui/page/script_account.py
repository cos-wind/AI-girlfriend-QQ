from __future__ import annotations

# 账号条：一行放下「当前账号 + 面板显示切换 + 新增账号」。
#
# 设计原则：**不重复**。横幅已经写了当前账号，下拉已经列了所有账号——
# 所以不要再另起一块"账号管理卡片"把账号再列一遍。这里只保留三件事：
#   1. 当前账号是谁（只读展示）
#   2. 面板显示哪个账号（唯一切换入口）
#   3. 新增账号（内联展开的一行表单）
# 待确认、只读、数据目录这些**只在需要时**出现在下面那行提示里。
#
# ⚠️ 这个 PART 必须是**裸 JS**，不能自带 <script> / </script>：
# 所有 script_*.py 的 PART 都拼在同一个 <script> 块里（由 body_advanced.py 开、
# script_voice_test.py 结尾的 </script> 关）。自带标签会在 JS 中间插进一个
# <script>（语法错误）并提前关闭整块脚本，使后面所有 JS 变成页面上的纯文本。
# 这个错误真的发生过，见 tests/test_accounts_webui.py 的
# test_page_has_exactly_one_script_block。
#
# ⚠️ 面板每 5 秒轮询一次。**结构只建一次**（ensureAccountBarShell），
# 轮询只更新文本、选项与提示——否则用户正在填的输入框会被反复重建清空。
# 这个错误也真的发生过，见 test_account_manager_form_is_not_rebuilt_by_polling。
PART = r"""let _accountRefreshTimer = null;

function accountEscape(value) {
  return String(value == null ? '' : value)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function accountShortId(account) {
  if(!account) return '未介入';
  const name = account.display_name || '';
  return name ? `${name}（QQ ${account.qq}）` : `QQ ${account.qq}`;
}

// 自带时间格式化，不依赖 script_qzone.py 里的同名工具——跨模块依赖会在
// 加载顺序变化时静默失效。
function accountTimeText(stamp) {
  const value = Number(stamp);
  if(!value) return '尚未记录';
  const date = new Date(value * 1000);
  if(Number.isNaN(date.getTime())) return '尚未记录';
  const pad = n => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} `
    + `${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function accountBytes(value) {
  const size = Number(value);
  if(!size || size < 0) return '尚无数据';
  if(size < 1024) return size + ' B';
  if(size < 1024 * 1024) return (size / 1024).toFixed(1) + ' KB';
  return (size / 1024 / 1024).toFixed(2) + ' MB';
}

function accountFind(accounts, id) {
  return (accounts || []).find(item => item.account_id === id) || null;
}

// ---- 结构只建一次 -------------------------------------------------------

function ensureAccountBarShell(host) {
  if($('accountCurrentName')) return;   // 已建好，绝不重建
  host.innerHTML =
    '<div class="account-bar">'
    + '<span class="badge active">当前账号</span>'
    + '<strong id="accountCurrentName">—</strong>'
    + '<span class="note" id="accountCurrentNote"></span>'
    + '<span class="account-bar-gap"></span>'
    + '<label class="account-view-label">面板显示'
    + '<select id="accountViewSelect" onchange="selectAccountView(this.value)"></select>'
    + '</label>'
    + '<span id="accountConfirmSlot"></span>'
    + '<button id="accountAddToggle" class="ghost mini" onclick="toggleAddAccountForm()">+ 新增账号</button>'
    + '<button id="accountSwitchNapcat" class="ghost mini" onclick="switchNapcatAccount(this)">切换 QQ 账号</button>'
    + '<span class="note" id="accountNapcatState"></span>'
    + '</div>'
    + '<div id="accountAddInline" class="account-add-inline" hidden>'
    + '<input id="accountAddQq" inputmode="numeric" placeholder="新账号 QQ（纯数字）">'
    + '<input id="accountAddName" placeholder="显示名（可留空）">'
    + '<button onclick="addAccount(this)">添加</button>'
    + '<button class="ghost mini" onclick="toggleAddAccountForm()">取消</button>'
    + '<span class="note" id="accountAddNote"></span>'
    + '</div>'
    // 切换 QQ 账号：NapCat 没有"退出登录"接口，这里的做法是清掉自动登录 + 重启
    // NapCat，然后把登录页给你；新号登进来后由 finishNapcatAccount 收尾。
    + '<div id="accountNapcatPanel" class="account-add-inline" hidden>'
    + '<span class="note" id="accountNapcatPanelText"></span>'
    + '<a id="accountNapcatLoginLink" href="#" target="_blank" rel="noreferrer">打开 NapCat 登录页</a>'
    + '<button id="accountNapcatFinish" onclick="finishNapcatAccount(this)">新号已登录，完成切换</button>'
    + '<button class="ghost mini" onclick="cancelNapcatSwitch(this)">放弃切换</button>'
    + '</div>'
    + '<div id="accountActiveHint" class="account-note-line"></div>';
}

function toggleAddAccountForm(force) {
  const box = $('accountAddInline');
  if(!box) return;
  const open = force === undefined ? box.hidden : !!force;
  box.hidden = !open;
  if(open) {
    const input = $('accountAddQq');
    if(input) { input.value = ''; input.focus(); }
    const name = $('accountAddName');
    if(name) name.value = '';
    setAccountAddNote('');
  }
}

function setAccountAddNote(text) {
  const note = $('accountAddNote');
  if(note) note.textContent = text || '';
}

// ---- 渲染（每 5 秒走一遍，只改内容不改结构）-----------------------------

function renderAccountBanner(data) {
  const host = $('accountBanner');
  if(!host) return;
  if(!data || data.enabled === false) {
    // 账号系统未启用时不占地方——面板保持今天的样子。
    host.hidden = true;
    host.innerHTML = '';
    return;
  }
  host.hidden = false;
  ensureAccountBarShell(host);

  const accounts = data.accounts || [];
  const runningId = data.running_account_id || '';
  const running = accountFind(accounts, runningId);
  const current = data.current || running;

  const nameEl = $('accountCurrentName');
  if(nameEl) nameEl.textContent = current ? accountShortId(current) : '等待 NapCat 登录信息…';
  const noteEl = $('accountCurrentNote');
  if(noteEl) {
    noteEl.textContent = data.follow_napcat
      ? '跟随 NapCat 登录账号'
      : '固定使用 BOT_QQ，不跟随登录变化';
  }

  renderViewOptions(data, accounts, runningId);
  renderConfirmSlot(data, accounts, runningId);
  renderActiveAccountHint(data, accounts, runningId);
}

function renderViewOptions(data, accounts, runningId) {
  const select = $('accountViewSelect');
  if(!select) return;
  const running = accountFind(accounts, runningId);
  const options = ['<option value="auto">跟随运行账号'
    + (running ? '（' + accountEscape(accountShortId(running)) + '）' : '')
    + '</option>'];
  accounts.forEach(account => {
    options.push(
      `<option value="${accountEscape(account.account_id)}">`
      + `${accountEscape(accountShortId(account))}`
      + (account.confirmed ? '' : '（待确认）')
      + '</option>'
    );
  });
  // 只有选项真的变了才重建，否则用户刚打开的下拉会被抽掉。
  const signature = options.join('|');
  if(select.dataset.signature !== signature) {
    select.innerHTML = options.join('');
    select.dataset.signature = signature;
  }
  select.value = data.view_selection || 'auto';
}

function renderConfirmSlot(data, accounts, runningId) {
  const slot = $('accountConfirmSlot');
  if(!slot) return;
  const selected = accountFind(accounts, data.view_selection || '');

  // 按钮只在"真的需要"时才出现（账号条的原则：不重复、不占地方）：
  //   · 选中的账号还没确认 → 确认并启用
  //   · 已确认但已停用       → 启用
  //   · 已确认且启用中       → 停用
  // 运行中的账号不给停用按钮：那等于把正在跑的机器人关掉，属于危险操作。
  let html = '';
  if(selected && !selected.confirmed) {
    html = `<button class="ghost mini" onclick="confirmAccount('${accountEscape(selected.account_id)}',this)">确认并启用</button>`;
  } else if(selected && selected.account_id !== runningId) {
    html = selected.enabled
      ? `<button class="ghost mini" onclick="toggleAccountEnabled('${accountEscape(selected.account_id)}', false, this)">停用</button>`
      : `<button class="ghost mini" onclick="toggleAccountEnabled('${accountEscape(selected.account_id)}', true, this)">启用</button>`;
  }

  // 用户刚点的按钮还在等请求返回时（withButtonBusy 会置 disabled）不要替换 DOM，
  // 否则按钮会在请求返回前被抽走。
  if(slot.querySelector('button[disabled]')) return;
  const signature = selected
    ? `${selected.account_id}|${!!selected.confirmed}|${!!selected.enabled}`
    : '';
  if(slot.dataset.signature === signature) return;
  slot.innerHTML = html;
  slot.dataset.signature = signature;
}

async function toggleAccountEnabled(accountId, enabled, button) {
  return withButtonBusy(button, async () => {
    try {
      await api('/api/account/update', {
        method:'POST',
        body: JSON.stringify({account_id: accountId, enabled: enabled})
      });
      toast(enabled ? '账号已启用' : '账号已停用');
      await loadAccountBanner();
    } catch(error) {
      toast('修改失败：' + (error && error.message ? error.message : error));
    }
  }, '处理中…');
}

function renderActiveAccountHint(data, accounts, runningId) {
  const targets = [$('accountActiveHint'), $('userDirectoryScopeHint')].filter(Boolean);
  if(!targets.length) return;
  // 切换过程中由 selectAccountView 接管提示（它会置 busy），5 秒轮询不能把它覆盖掉
  // ——否则用户点完下拉只看到一闪而过的"正在切换面板数据…"，还以为没反应。
  if(targets[0].dataset.busy === '1') return;

  const running = accountFind(accounts, runningId);
  const viewed = accountFind(accounts, data.view_selection || '');
  const pending = data.pending || [];

  let text = '';
  let readonly = false;
  if(data.read_only && viewed) {
    readonly = true;
    text =
      '<span class="badge red">只读</span> '
      + `下面「用户目录」「记忆」「评测」显示的是 <b>${accountEscape(accountShortId(viewed))}</b> 的数据；`
      + `机器人实际仍在运行 <b>${accountEscape(running ? accountShortId(running) : (runningId || '未介入'))}</b>。`
      + '<br><b>QQ 好友、群列表、QQ 空间动态只属于正在登录的那个账号</b>——'
      + '这个号码没有 NapCat 登录会话，所以拿不到它的好友与动态（这里显示的是空，不是原账号的数据）。'
      + '要查看它的这些数据，需要让 NapCat 登录它。';
  } else if(pending.length) {
    text = `<span class="badge warn">${pending.length} 个待确认账号</span> `
      + pending.map(item => accountEscape(accountShortId(item))).join('、')
      + '：确认前不会创建独立数据区。';
  }

  // 顶部提示常驻；用户中心那份只在只读时出现，避免同一句话在页面上说两遍。
  targets.forEach((el, index) => {
    const show = index === 0 ? !!text : readonly;
    el.className = readonly ? 'account-note-line readonly' : 'account-note-line';
    el.innerHTML = show ? text : '';
  });
}

// ---- 交互 ---------------------------------------------------------------

async function selectAccountView(value) {
  // 切换要重新载入那个账号的记忆（可能是 12MB 的 JSON）与用户目录，有明显耗时。
  const select = $('accountViewSelect');
  const hint = $('accountActiveHint');
  if(select) select.disabled = true;
  if(hint) {
    hint.dataset.busy = '1';
    hint.className = 'account-note-line loading';
    hint.textContent = '正在切换面板数据…';
  }
  try {
    const body = value === 'auto' ? {auto: true} : {view: value};
    await api('/api/account/view', {method:'POST', body: JSON.stringify(body)});
    if(hint) hint.textContent = '正在载入该账号的记忆与用户目录…';
    if(typeof loadMemory === 'function') await loadMemory();
    if(typeof loadUserDirectory === 'function') await loadUserDirectory(true);
    toast(value === 'auto' ? '面板已跟随运行账号' : '面板已切到只读查看');
  } catch(error) {
    toast('切换查看账号失败：' + (error && error.message ? error.message : error));
  } finally {
    if(hint) delete hint.dataset.busy;
    if(select) select.disabled = false;
    await loadAccountBanner();
  }
}

async function confirmAccount(accountId, button) {
  if(!confirm('确认启用这个账号？确认后会在 data/accounts 下为它创建独立数据区，'
      + '并且当 NapCat 登录该号时机器人会切换到它（记忆、评测、人设、配置都独立）。')) return;
  return withButtonBusy(button, async () => {
    try {
      await api('/api/account/confirm', {
        method:'POST', body: JSON.stringify({account_id: accountId})
      });
      toast('账号已确认；下一次探测到该登录号时会切换');
      await loadAccountBanner();
    } catch(error) {
      toast('确认失败：' + (error && error.message ? error.message : error));
    }
  }, '确认中…');
}

async function addAccount(button) {
  const qqInput = $('accountAddQq');
  const nameInput = $('accountAddName');
  const qq = (qqInput ? qqInput.value : '').trim();
  if(!/^[0-9]+$/.test(qq)) {
    setAccountAddNote('QQ 号必须是纯数字。');
    return;
  }
  return withButtonBusy(button, async () => {
    try {
      await api('/api/account/add', {
        method:'POST',
        body: JSON.stringify({qq: qq, display_name: (nameInput ? nameInput.value : '').trim()})
      });
      setAccountAddNote('');
      toggleAddAccountForm(false);
      toast('账号 ' + qq + ' 已新增，可用「面板显示」切过去查看');
      await loadAccountBanner();
    } catch(error) {
      const message = error && error.message ? error.message : String(error);
      setAccountAddNote(message);
      toast('新增失败：' + message);
    }
  }, '添加中…');
}

async function loadAccountBanner() {
  const host = $('accountBanner');
  try {
    const data = await api('/api/account/current');
    renderAccountBanner(data);
  } catch(error) {
    // 端点在 WebUI 进程重启前还不存在，或者账号系统读取失败：
    // 整条隐藏即可，不要在面板上留下一块报错。
    if(host) { host.hidden = true; host.innerHTML = ''; }
    const hint = $('accountActiveHint');
    if(hint) { hint.className = 'account-note-line'; hint.innerHTML = ''; }
  }
}

// ---- 切换 NapCat 登录账号 ------------------------------------------------
//
// 流程：点「切换 QQ 账号」→ 后端清掉自动登录并重启 NapCat（napcat-restart）→
// 用户在 NapCat 页面用新号扫码/输密码 → 这里轮询到新号已登录后**自动收尾**
// （把快速登录设成新号 + 在 ATRI 账号系统里确认该账号），用户不用再点任何东西。
// 关键词是"清掉自动登录"：napcat 启动时会用 BOT_QQ 传 -q，旧会话会把用户拉回原号。

function renderNapcatAccountState(state) {
  const text = $('accountNapcatState');
  const panel = $('accountNapcatPanel');
  if(!text) return;
  if(!state || state.ok === false) {
    text.textContent = state && state.error ? 'NapCat 状态读取失败：' + state.error : '';
    if(panel) panel.hidden = true;
    return;
  }

  const who = state.is_login
    ? `${state.nick || '已登录'}（QQ ${state.uin}）`
    : '未登录';
  const auto = state.quick_account_override === 'off'
    ? '已准备换号（不会自动登回旧号）'
    : (state.quick_account_override
        ? `自动登录 ${state.quick_account_override}`
        : (state.auto_login_account ? `自动登录 ${state.auto_login_account}` : '无自动登录'));
  let extra = '';
  if(state.login_error) extra = ` · ${state.login_error}`;
  else if(!state.is_login && state.phase) extra = ` · 阶段 ${state.phase}`;
  text.textContent = `NapCat：${who} · ${auto}${extra}`;

  if(panel) {
    panel.hidden = !(state.manual_login_pending || state.is_login);
    const link = $('accountNapcatLoginLink');
    if(link && state.webui_url) link.href = state.webui_url;
    const panelText = $('accountNapcatPanelText');
    if(panelText) {
      panelText.textContent = state.is_login
        ? (state.manual_login_pending
            ? `新号 ${state.uin} 已登录，正在收尾…`
            : '已登录；要换号请点「切换 QQ 账号」')
        : 'NapCat 已重启并停在登录页：请用新账号的手机 QQ 扫码（或在该页面选账号密码登录）。';
    }
  }

  // 自动收尾：同一个号只做一次，避免 5 秒轮询反复写配置。
  window._napcatFinishedUins = window._napcatFinishedUins || {};
  if(state.auto_finish_ready && !window._napcatFinishedUins[state.uin]) {
    window._napcatFinishedUins[state.uin] = true;
    finishNapcatAccount(null, true);
  }
}

async function loadNapcatAccountState() {
  if(!$('accountNapcatState')) return;
  try {
    renderNapcatAccountState(await api('/api/account/napcat'));
  } catch(error) {
    renderNapcatAccountState({ok:false, error: (error && error.message) || String(error)});
  }
}

async function switchNapcatAccount(button) {
  if(!confirm('切换 QQ 账号会先退出当前账号并重启 NapCat（几秒钟内机器人离线）。\n'
      + '重启后会停在登录页，用新账号的扫码或账号密码登录即可。继续？')) return;
  return withButtonBusy(button, async () => {
    try {
      const result = await api('/api/account/napcat/switch', {
        method:'POST', body: JSON.stringify({action:'logout'})
      });
      toast(result.message || '已准备切换，请在新打开的 NapCat 页面登录');
      const link = $('accountNapcatLoginLink');
      if(link && result.webui_url) { link.href = result.webui_url; }
      const panel = $('accountNapcatPanel');
      if(panel) panel.hidden = false;
      if(result.webui_url && typeof window.open === 'function') window.open(result.webui_url, '_blank', 'noopener');
      window._napcatFinishedUins = {};
      await loadNapcatAccountState();
    } catch(error) {
      toast('准备切换失败：' + ((error && error.message) || error));
    }
  }, '准备中…');
}

async function finishNapcatAccount(button, automatic) {
  const run = async () => {
    const result = await api('/api/account/napcat/switch', {
      method:'POST', body: JSON.stringify({action:'finish'})
    });
    toast(result.message || '账号切换已完成');
    if(typeof loadAccountBanner === 'function') await loadAccountBanner();
    if(typeof loadUserDirectory === 'function') await loadUserDirectory(true);
    await loadNapcatAccountState();
  };
  if(automatic) {
    try { await run(); }
    catch(error) { toast('自动收尾失败：' + ((error && error.message) || error)); }
    return;
  }
  return withButtonBusy(button, run, '收尾中…');
}

async function cancelNapcatSwitch(button) {
  return withButtonBusy(button, async () => {
    try {
      const result = await api('/api/account/napcat/switch', {
        method:'POST', body: JSON.stringify({action:'cancel'})
      });
      toast(result.message || '已取消切换准备');
      const panel = $('accountNapcatPanel');
      if(panel) panel.hidden = true;
      await loadNapcatAccountState();
    } catch(error) {
      toast('取消失败：' + ((error && error.message) || error));
    }
  }, '取消中…');
}

function startAccountBanner() {
  loadAccountBanner();
  loadNapcatAccountState();
  if(_accountRefreshTimer) clearInterval(_accountRefreshTimer);
  // 换账号发生在 OneBot 侧的探测循环里，面板用低频轮询跟上就够；
  // 切换过程中这个轮询也负责发现"新号已登录"并自动收尾。
  _accountRefreshTimer = setInterval(() => {
    loadAccountBanner();
    loadNapcatAccountState();
  }, 5000);
}

if(document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', startAccountBanner);
} else {
  startAccountBanner();
}
"""
