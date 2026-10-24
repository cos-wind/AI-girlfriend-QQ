from __future__ import annotations

DOCUMENT_HEAD = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>亚托莉控制台</title>
  <style>
    :root {
      --bg:#faf5ff; --panel:rgba(255,255,255,.58); --ink:#312e4a; --muted:#6f6680; --line:rgba(167,139,250,.2);
      --blue:#7dd3fc; --blue-soft:rgba(125,211,252,.14); --violet:#a78bfa; --green:#15803d; --red:#e11d48;
      --amber:#a16207; --soft:rgba(253,246,249,.72); --dark:#312e4a;
    }
    * { box-sizing:border-box; }
    body { margin:0; font-family:"Quicksand","Nunito","PingFang SC","Rounded Mplus 1c","Microsoft YaHei",sans-serif; background:radial-gradient(circle at 8% 4%,rgba(125,211,252,.22),transparent 30%),radial-gradient(circle at 92% 12%,rgba(167,139,250,.18),transparent 28%),linear-gradient(135deg,#faf5ff,#fdf6f9 58%,#f4f8ff); background-attachment:fixed; color:var(--ink); font-size:14px; line-height:1.65; }
    header { background:rgba(255,255,255,.62); border-bottom:1px solid rgba(255,255,255,.72); padding:22px 24px; position:sticky; top:0; z-index:8; backdrop-filter:blur(18px); box-shadow:0 8px 24px rgba(120,80,200,.06); }
    h1 { margin:0 0 6px; font-size:22px; font-weight:700; letter-spacing:.02em; background:linear-gradient(135deg,#38bdf8,#8b5cf6); -webkit-background-clip:text; background-clip:text; color:transparent; }
    h2 { margin:0 0 14px; font-size:16px; font-weight:600; color:var(--ink); }
    h3 { margin:16px 0 10px; font-size:14px; font-weight:600; color:var(--ink); }
    p { margin:1.2em 0; }
    :root { --content-gutter:clamp(12px,2vw,32px); --content-max:1920px; }
    main { width:min(calc(100% - (2 * var(--content-gutter))),var(--content-max)); margin:0 auto; padding:18px 0 32px; display:block; }
    main > section { min-width:0; }
    aside, section, .surface { background:var(--panel); border:1px solid rgba(255,255,255,.72); border-radius:20px; padding:20px; box-shadow:0 8px 32px rgba(120,80,200,.08),0 2px 8px rgba(120,80,200,.04); backdrop-filter:blur(16px); }
    .global-status { width:min(calc(100% - (2 * var(--content-gutter))),var(--content-max)); margin:18px auto 0; padding:20px 22px; }
    /* 账号条：一行放下「当前账号 + 面板显示切换 + 新增账号」，不重复列账号。
       账号系统关闭时整条 hidden，面板保持今天的样子。 */
    .account-banner { width:min(calc(100% - (2 * var(--content-gutter))),var(--content-max)); margin:18px auto 0; padding:12px 18px; background:#fffdf7; border:1px solid #ded4c9; border-left:4px solid #f2a286; border-radius:14px; }
    .account-banner[hidden] { display:none; }
    .account-bar { display:flex; align-items:center; gap:10px; flex-wrap:wrap; }
    .account-bar strong { font-size:14px; }
    .account-bar-gap { flex:1 1 16px; }
    .account-view-label { display:flex; align-items:center; gap:6px; font-size:13px; color:var(--ink); }
    .account-view-label select { max-width:260px; }
    /* 新增账号：默认收起的一行内联表单，不占地方。 */
    .account-add-inline { display:flex; align-items:center; gap:8px; flex-wrap:wrap; margin-top:10px; padding-top:10px; border-top:1px dashed rgba(167,139,250,.25); }
    .account-add-inline[hidden] { display:none; }
    .account-add-inline input { min-width:170px; }
    /* 只在需要时出现的一行提示：待确认 / 只读 / 切换进度。 */
    .account-note-line { margin-top:8px; padding:8px 12px; border-radius:10px; background:rgba(125,211,252,.12); font-size:12px; line-height:1.7; }
    .account-note-line:empty { display:none; }
    .account-note-line.readonly { background:rgba(244,201,210,.28); }
    .account-note-line.loading { background:rgba(248,223,182,.5); position:relative; overflow:hidden; }
    .account-note-line.loading:after { content:""; position:absolute; left:0; bottom:0; height:2px; width:40%; background:#f2a286; animation:accountLoadSlide 1.1s ease-in-out infinite; }
    @keyframes accountLoadSlide { 0% { left:-40%; } 100% { left:100%; } }
    /* 管理入口折叠在顶部：默认收起，不占地方；展开后是新增表单与账号卡片。 */
    .account-manager-details { width:min(calc(100% - (2 * var(--content-gutter))),var(--content-max)); margin:8px auto 0; padding:0 14px; background:#fffdf7; border:1px solid #ded4c9; border-radius:12px; }
    .account-manager-details[hidden] { display:none; }
    .account-manager-details > summary { cursor:pointer; padding:10px 0; font-size:13px; color:var(--muted); list-style:revert; }
    .account-manager-details[open] { padding-bottom:12px; }
    .global-status .section-head { margin-bottom:12px; }
    .global-status .status { grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); }
    .sub,.note,.hint { color:var(--muted); font-size:12px; line-height:1.65; }
    .tabs { display:flex; gap:7px; flex-wrap:wrap; margin-bottom:18px; position:sticky; top:78px; z-index:7; padding:8px; background:rgba(255,255,255,.56); border:1px solid rgba(255,255,255,.76); border-radius:999px; box-shadow:0 8px 24px rgba(120,80,200,.08); backdrop-filter:blur(16px); }
    .tabs .tab { flex:1 1 120px; }
    button { min-height:40px; border:1px solid rgba(255,255,255,.45); border-radius:999px; background:linear-gradient(135deg,#7dd3fc,#a78bfa); color:#312e4a; padding:9px 16px; cursor:pointer; font-weight:700; transition:transform .18s cubic-bezier(.2,1.4,.4,1),filter .18s ease,box-shadow .18s ease; box-shadow:0 4px 12px rgba(125,211,252,.18); }
    button:hover { filter:brightness(1.03); transform:scale(1.02); box-shadow:0 7px 18px rgba(125,211,252,.28); }
    button:active { transform:scale(.96); }
    button.secondary { background:rgba(255,255,255,.52); color:#645879; border-color:rgba(167,139,250,.25); box-shadow:none; }
    button.ghost { background:rgba(255,255,255,.44); color:#6350b2; border-color:rgba(167,139,250,.3); box-shadow:none; }
    button.warn { background:linear-gradient(135deg,#fcd34d,#fbbf24); color:#5b4300; }
    button.danger { background:linear-gradient(135deg,#fb7185,#f43f5e); color:#fff; }
    button:disabled { opacity:.55; cursor:not-allowed; }
    .tab { background:rgba(255,255,255,.34); color:var(--muted); border-color:transparent; box-shadow:none; }
    .tab.active { background:linear-gradient(135deg,#7dd3fc,#a78bfa); color:#312e4a; box-shadow:0 4px 12px rgba(125,211,252,.4); }
    .panel { display:none; }
    .panel.active { display:block; }
    .status { display:grid; gap:10px; }
    .pill { display:flex; justify-content:space-between; gap:10px; align-items:center; padding:12px 14px; border:1px solid rgba(255,255,255,.76); border-radius:16px; background:rgba(255,255,255,.46); min-height:62px; }
    .ok { color:#047857; font-weight:700; }
    .bad { color:#be123c; font-weight:700; }
    /* 状态条里的「未运行 / 未连接」等异常值只做淡灰提示：这些服务本来就是手动启动、
       平时不运行，常驻红色太抢眼。组合类的优先级高于 .bad，所以只影响显式加了
       .soft 的地方，其它页面的错误提示仍然是红的。 */
    .bad.soft { color:#8b8b9a; font-weight:600; }
    .grid { display:grid; grid-template-columns:repeat(2,minmax(220px,1fr)); gap:12px; }
    .form-grid { display:grid; gap:10px; }
    .form-grid > label { display:grid; grid-template-columns:minmax(120px,1fr) minmax(0,3fr); align-items:center; gap:12px; }
    .form-grid > label > input, .form-grid > label > select, .form-grid > label > textarea { min-width:0; }
    .three { display:grid; grid-template-columns:repeat(3,minmax(160px,1fr)); gap:12px; }
    .split { display:grid; grid-template-columns:minmax(360px,.95fr) minmax(420px,1.05fr); gap:14px; }
    #model.panel.active { display:block; }
    .model-workspace { display:block; }
    .model-profile-surface { margin-top:20px; }
    #model .model-profile-surface { margin-top:20px; }
    #modelProfileEditor { position:static; margin-top:20px; }
    label { display:grid; gap:6px; color:var(--muted); font-size:14px; font-weight:500; }
    input, select, textarea { width:100%; border:1px solid rgba(167,139,250,.2); border-radius:14px; padding:11px 13px; font:inherit; background:rgba(255,255,255,.52); color:var(--ink); outline:none; transition:border-color .18s ease,box-shadow .18s ease,background .18s ease; }
    input:focus, select:focus, textarea:focus { border-color:var(--violet); background:rgba(255,255,255,.75); box-shadow:0 0 0 4px rgba(167,139,250,.15); }
    textarea { min-height:130px; resize:vertical; line-height:1.5; }
    .json-editor { min-height:340px; font-family:Consolas,"Microsoft YaHei UI",monospace; }
    .row { display:flex; gap:10px; flex-wrap:wrap; align-items:center; margin-top:16px; }
    .stack { display:grid; gap:12px; }
    .toolbar { display:flex; gap:10px; flex-wrap:wrap; align-items:end; margin:10px 0 14px; }
    .toolbar label { min-width:170px; flex:1; }
    .scroll { max-height:640px; overflow:auto; border:1px solid rgba(167,139,250,.18); border-radius:16px; background:rgba(255,255,255,.42); }
    .log-view { min-height:420px; max-height:68vh; overflow:auto; margin:0; padding:16px; border:1px solid rgba(167,139,250,.18); border-radius:16px; background:rgba(49,46,74,.92); color:#e9e3ff; font:12px/1.7 Consolas,"Microsoft YaHei UI",monospace; white-space:pre-wrap; word-break:break-word; }
    .developer-links { display:grid; gap:10px; }
    .developer-links a { color:#6350b2; font-weight:700; overflow-wrap:anywhere; }
    .insight-subpanel { display:none; }
    .insight-subpanel.active { display:grid; gap:14px; }
    #evaluationDashboardPanel.active { display:grid; grid-template-columns:repeat(12,minmax(0,1fr)); gap:14px; align-items:start; }
    #evaluationDashboardPanel > .surface:first-child,
    #evaluationDashboardPanel > .surface:nth-of-type(4) { grid-column:1 / -1; }
    #evaluationDashboardPanel > .surface:nth-of-type(2) { grid-column:span 8; }
    #evaluationDashboardPanel > .split { grid-column:span 4; display:grid; grid-template-columns:1fr; gap:14px; }
    #evaluationDashboardPanel > .surface:nth-of-type(3) { grid-column:1 / -1; }
    #evaluationDashboardPanel > .surface:nth-of-type(5) { grid-column:1 / -1; }
    #evaluationDashboardPanel > .surface { min-width:0; }
    .score-grid { display:grid; grid-template-columns:repeat(6,minmax(120px,1fr)); gap:10px; }
    .score-card { border:1px solid rgba(255,255,255,.76); border-radius:16px; padding:14px; background:rgba(255,255,255,.5); }
    .score-card strong { display:block; font-size:22px; }
    .score-low { color:var(--red); }
    .score-mid { color:var(--amber); }
    .score-high { color:var(--green); }
    .trend-chart { width:100%; min-height:230px; border:1px solid rgba(167,139,250,.18); border-radius:16px; background:rgba(255,255,255,.42); }
    .score-pills { display:flex; flex-wrap:wrap; gap:5px; }
    .score-mini { border-radius:999px; padding:2px 7px; background:rgba(167,139,250,.15); font-size:11px; white-space:nowrap; }
    .summary-detail { min-height:240px; max-height:620px; overflow:auto; white-space:pre-wrap; }
    .summary-plan-table { min-width:1040px; }
    .summary-plan-table th { white-space:nowrap; }
    .summary-plan { min-width:180px; display:grid; gap:7px; padding:4px 0; }
    .summary-plan .switch-line { display:flex; align-items:center; gap:7px; color:var(--ink); font-size:13px; }
    .summary-plan .switch-line input { width:auto; }
    .summary-plan input[type="datetime-local"] { min-width:205px; padding:7px 9px; }
    button.mini { min-height:30px; padding:5px 10px; font-size:12px; justify-self:start; }
    .summary-plan .summary-last-sent { color:var(--muted); font-size:11px; }
    .summary-actions { display:flex; flex-wrap:wrap; gap:7px; align-items:center; }
    .summary-group-details { margin-top:14px; padding:14px; border:1px solid rgba(167,139,250,.18); border-radius:16px; background:rgba(255,255,255,.42); }
    .summary-detail-row > td { padding:0 12px 14px; background:rgba(255,255,255,.25); }
    .summary-detail-list { display:grid; gap:9px; margin-top:10px; }
    .summary-detail-item { padding:11px 13px; border:1px solid rgba(167,139,250,.18); border-radius:13px; background:rgba(255,255,255,.58); }
    .summary-detail-item .summary-detail-content { margin-top:7px; white-space:pre-wrap; overflow-wrap:anywhere; color:var(--ink); }
    .summary-task-progress { margin:10px 0; padding:11px 13px; border:1px solid rgba(96,165,250,.28); border-radius:13px; background:linear-gradient(120deg,rgba(224,242,254,.78),rgba(245,243,255,.72)); }
    .summary-progress-track { height:8px; overflow:hidden; margin:8px 0 6px; border-radius:999px; background:rgba(148,163,184,.20); }
    .summary-progress-track span { display:block; height:100%; border-radius:inherit; background:linear-gradient(90deg,#60a5fa,#8b5cf6); transition:width .35s ease; }
    .summary-timeline { display:grid; gap:12px; margin-top:12px; }
    .summary-timeline-day { padding-left:13px; border-left:3px solid rgba(96,165,250,.48); }
    .summary-timeline-day h4 { margin:0 0 7px; color:var(--ink); }
    .summary-timeline-item { display:flex; align-items:center; justify-content:space-between; gap:12px; padding:9px 11px; border:1px solid rgba(167,139,250,.18); border-radius:11px; background:rgba(255,255,255,.58); }
    .summary-timeline-item + .summary-timeline-item { margin-top:7px; }
    .evaluation-model-grid { display:grid; grid-template-columns:repeat(3,minmax(180px,1fr)); gap:10px; margin-top:12px; }
    .evaluation-model-card { border:1px solid rgba(167,139,250,.2); border-radius:16px; padding:13px; background:rgba(255,255,255,.48); }
    .evaluation-model-card strong { display:block; font-size:20px; margin:4px 0; }
    .evaluation-model-card .mini-stats { display:flex; flex-wrap:wrap; gap:8px; font-size:12px; color:var(--muted); }
    .delivery-grid { display:grid; grid-template-columns:repeat(4,minmax(140px,1fr)); gap:10px; margin-top:12px; }
    .delivery-card { border:1px solid rgba(167,139,250,.2); border-radius:16px; padding:13px; background:rgba(255,255,255,.48); }
    .delivery-card strong { display:block; font-size:20px; margin:4px 0; }
    .delivery-success { color:var(--green); }
    .delivery-failed { color:var(--red); }
    /* 评测记录可能含字面量转义串或长模型输出，必须在表格内部断行，不能撑宽整页。 */
    #evaluationDashboardPanel > .surface,#evaluationDashboardPanel > .split { min-width:0; }
    #evaluationDashboardPanel .split > .surface { min-width:0; }
    #evaluationDashboardPanel .scroll { width:100%; max-width:100%; min-width:0; }
    #evaluationDashboardPanel table { table-layout:fixed; }
    #evaluationDashboardPanel th,#evaluationDashboardPanel td { overflow-wrap:anywhere; word-break:break-word; }
    #evaluationDashboardPanel .natural-box { overflow-wrap:anywhere; word-break:break-word; }
    table { width:100%; border-collapse:collapse; font-size:13px; }
    th,td { text-align:left; border-bottom:1px dashed rgba(167,139,250,.18); padding:12px; vertical-align:top; }
    thead { background:rgba(167,139,250,.05); }
    tbody tr:nth-child(even) { background:rgba(255,255,255,.2); }
    tr:hover { background:rgba(125,211,252,.08) !important; }
    .profile-list { display:grid; gap:16px; }
    .current-models { display:grid; gap:12px; border-left:3px solid var(--violet); padding-left:16px; }
    .profile-columns { display:grid; grid-template-columns:repeat(auto-fit,minmax(300px,1fr)); gap:20px; align-items:start; }
    .profile-column { display:grid; gap:14px; border:1px solid rgba(255,255,255,.72); border-radius:18px; padding:16px; background:rgba(253,246,249,.56); min-width:0; }
    .profile-column h3 { margin:0; display:flex; justify-content:space-between; gap:8px; align-items:center; }
    .profile-column .profile { background:rgba(255,255,255,.64); }
    .profile { border:1px solid rgba(255,255,255,.78); border-radius:18px; padding:18px; background:rgba(255,255,255,.58); display:grid; gap:10px; }
    .profile.active { border-color:var(--violet); box-shadow:0 0 0 3px rgba(167,139,250,.14),0 10px 28px rgba(120,80,200,.1); }
    .profile-title { display:flex; justify-content:space-between; gap:10px; align-items:flex-start; }
    .section-head { display:flex; justify-content:space-between; gap:12px; align-items:flex-start; margin-bottom:10px; }
    .section-head h2 { margin:0; }
    .section-head .row { margin:0; }
    .preset-panel { border:1px solid rgba(255,255,255,.74); border-radius:18px; background:rgba(253,246,249,.62); padding:16px; margin-bottom:18px; display:grid; gap:12px; }
    .preset-panel h3 { margin:0; }
    .model-card { border:1px solid rgba(255,255,255,.78); border-radius:18px; background:rgba(255,255,255,.56); padding:16px; display:grid; gap:10px; }
    .model-card.selected { border-color:var(--violet); box-shadow:0 0 0 3px rgba(167,139,250,.14),0 10px 28px rgba(120,80,200,.1); }
    .model-card-head { display:flex; justify-content:space-between; gap:10px; align-items:flex-start; }
    .model-card strong { overflow-wrap:anywhere; }
    .model-card .row { margin-top:2px; }
    .model-feedback { display:none; border:1px solid #bfdbfe; background:#eff6ff; color:#1d4ed8; border-radius:7px; padding:9px 10px; margin:10px 0 0; }
    .model-feedback.show { display:block; }
    .badge { display:inline-flex; align-items:center; border-radius:999px; padding:4px 10px; font-size:12px; background:rgba(196,181,253,.3); color:#4c1d95; white-space:nowrap; box-shadow:inset 0 1px 0 rgba(255,255,255,.7); }
    .badge.active { background:#6ee7b7; color:#064e3b; }
    .badge.warn { background:#fcd34d; color:#713f12; }
    .badge.red { background:#fb7185; color:#fff; }
    .mono { font-family:Consolas,monospace; }
    .out,.natural-box { white-space:pre-wrap; background:rgba(49,46,74,.9); color:#fff; border-radius:16px; padding:16px; min-height:90px; line-height:1.65; }
    .natural-box { background:rgba(255,255,255,.48); color:var(--ink); border:1px solid rgba(255,255,255,.72); }
    .thumbs { display:grid; grid-template-columns:repeat(auto-fill,minmax(112px,1fr)); gap:10px; }
    .thumb { border:1px solid rgba(255,255,255,.72); border-radius:16px; padding:10px; background:rgba(255,255,255,.52); }
    .thumb img { width:100%; height:92px; object-fit:contain; background:rgba(255,255,255,.5); border-radius:12px; }
    .thumb small { display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:var(--muted); margin:6px 0; }
    details { border:1px solid rgba(255,255,255,.72); border-radius:16px; padding:12px 14px; background:rgba(255,255,255,.5); }
    summary { cursor:pointer; font-weight:700; }
    .toast { position:fixed; right:18px; bottom:18px; max-width:420px; background:rgba(49,46,74,.86); color:#fff; padding:13px 16px 13px 40px; border:1px solid rgba(255,255,255,.35); border-radius:18px; box-shadow:0 10px 28px rgba(120,80,200,.22); backdrop-filter:blur(16px); opacity:0; pointer-events:none; transform:translateY(8px); transition:.18s ease; z-index:30; }
    .toast::before { content:'✦'; position:absolute; left:16px; color:#7dd3fc; animation:twinkle 1.4s ease-in-out infinite; }
    .toast.show { opacity:1; transform:translateY(0); }
    .memory-name { font-weight:700; margin-bottom:4px; }
    .memory-meta { color:var(--muted); font-size:12px; line-height:1.55; }
    .memory-summary { line-height:1.6; max-width:620px; }
    .user-directory-scroll { max-height:none; min-height:520px; }
    .user-directory-list { display:grid; grid-template-columns:minmax(0,1fr); gap:10px; padding:14px; width:100%; }
    .user-directory-section-title { padding:8px 4px 2px; color:var(--muted); font-weight:700; font-size:12px; letter-spacing:.04em; }
    .user-directory-entry { display:grid; gap:8px; padding:4px; border-radius:17px; content-visibility:auto; contain-intrinsic-size:0 132px; }
    .user-directory-row { width:100%; text-align:left; border:1px solid rgba(100,116,139,.22); border-radius:14px; padding:13px 15px; background:rgba(248,250,252,.86); color:var(--ink); box-shadow:0 3px 10px rgba(51,65,85,.06); transition:.18s ease; }
    .user-directory-row:hover { transform:translateY(-1px); border-color:rgba(99,102,241,.45); box-shadow:0 7px 18px rgba(51,65,85,.11); }
    .user-directory-row.selected { border-color:var(--violet); box-shadow:0 0 0 3px rgba(167,139,250,.16),0 8px 20px rgba(51,65,85,.10); background:rgba(255,255,255,.98); }
    .user-directory-row.group-row { border-left:5px solid var(--blue); background:linear-gradient(135deg,rgba(239,246,255,.96),rgba(248,250,252,.95)); }
    .user-directory-row.bot-row { border:2px solid var(--violet); border-left:6px solid var(--violet); background:linear-gradient(135deg,rgba(224,242,254,.98),rgba(237,233,254,.98)); }
    .user-directory-row strong { display:block; }
    .user-directory-row .memory-meta { display:block; margin-top:3px; }
    .user-directory-inline-detail { padding:16px; border:1px solid rgba(99,102,241,.22); border-radius:16px; background:linear-gradient(180deg,rgba(255,255,255,.94),rgba(248,250,252,.82)); box-shadow:inset 0 1px 0 rgba(255,255,255,.85); }
    .user-directory-badges { display:flex; flex-wrap:wrap; gap:6px; margin:10px 0; }
    .user-directory-facts { display:grid; grid-template-columns:repeat(2,minmax(140px,1fr)); gap:8px; margin:12px 0; }
    .user-directory-fact { padding:10px 12px; border:1px solid rgba(167,139,250,.18); border-radius:12px; background:rgba(255,255,255,.48); }
    .user-directory-fact span { display:block; color:var(--muted); font-size:11px; }
    .user-directory-fact strong { display:block; margin-top:3px; overflow-wrap:anywhere; }
    .user-directory-context { margin-top:12px; padding:13px; border:1px solid rgba(100,116,139,.18); border-radius:12px; background:rgba(241,245,249,.68); }
    .user-directory-context h4 { margin:0; }
    .user-directory-context.memory-context { border-color:rgba(167,139,250,.32); background:linear-gradient(135deg,rgba(237,233,254,.58),rgba(255,255,255,.72)); }
    .user-directory-context.qzone-context { border-color:rgba(125,211,252,.34); background:linear-gradient(135deg,rgba(224,242,254,.62),rgba(255,255,255,.72)); }
    .user-directory-context.proactive-context { border-color:rgba(129,140,248,.36); background:linear-gradient(135deg,rgba(224,231,255,.72),rgba(240,249,255,.78)); }
    .user-directory-context.summary-context { border-color:rgba(52,211,153,.34); background:linear-gradient(135deg,rgba(209,250,229,.58),rgba(255,255,255,.72)); }
    .user-directory-context .qzone-comment { min-height:74px; }
    .user-directory-context .summary-plan-grid { grid-template-columns:repeat(3,minmax(0,1fr)); }
    .user-directory-context .summary-plan { background:rgba(255,255,255,.62); }
    .user-directory-row.bot-row + .user-directory-inline-detail { border-color:rgba(125,211,252,.45); }
    .user-directory-row.owner-row { border-left:5px solid #f59e0b; background:linear-gradient(135deg,rgba(255,247,237,.96),rgba(255,255,255,.95)); }
    .user-directory-inline-memory { display:block; margin-top:8px; padding:10px 11px; border:1px solid rgba(167,139,250,.2); border-radius:10px; background:linear-gradient(135deg,rgba(237,233,254,.52),rgba(240,249,255,.52)); font-weight:500; }
    .user-directory-inline-memory > strong { display:block; margin-bottom:7px; color:#4338ca; }
    .user-directory-inline-memory .card-context-values { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:7px; margin-top:2px; }
    .user-directory-inline-memory .card-context-values > span { display:block; padding:6px 8px; border-radius:8px; border:1px solid rgba(99,102,241,.14); background:rgba(255,255,255,.7); white-space:normal; }
    .user-directory-inline-memory .card-context-values > span:nth-child(1) { color:#9a3412; background:rgba(255,237,213,.8); border-color:rgba(251,146,60,.3); }
    .user-directory-inline-memory .card-context-values > span:nth-child(2) { color:#166534; background:rgba(220,252,231,.8); border-color:rgba(74,222,128,.3); }
    .user-directory-inline-memory .card-context-values > span:nth-child(3) { color:#5b21b6; background:rgba(237,233,254,.85); border-color:rgba(167,139,250,.3); }
    .user-directory-inline-memory .card-context-values > span:nth-child(4) { color:#075985; background:rgba(224,242,254,.85); border-color:rgba(56,189,248,.3); }
    .user-directory-inline-memory .card-context-summary { display:block; margin-top:9px; padding-top:8px; border-top:1px dashed rgba(99,102,241,.2); line-height:1.75; white-space:pre-wrap; overflow-wrap:anywhere; }
    .user-directory-inline-memory .memory-meta { display:block; margin-top:8px; }
    .qzone-auto-switches { display:flex; flex-wrap:wrap; gap:10px; align-items:center; margin:10px 0; padding:9px 11px; border:1px solid rgba(56,189,248,.22); border-radius:10px; background:rgba(224,242,254,.46); }
    .qzone-auto-switches label { display:flex; align-items:center; gap:7px; color:#075985; font-size:12px; }
    .qzone-auto-switches input { width:17px; height:17px; }
    .atri-pool { display:grid; gap:7px; margin-top:10px; }
    .atri-pool-item { padding:9px 10px; border:1px solid rgba(99,102,241,.18); border-radius:11px; background:rgba(255,255,255,.62); }
    .atri-pool-item .pool-head { display:flex; justify-content:space-between; gap:8px; align-items:center; }
    .atri-pool-item .pool-content { margin-top:4px; white-space:pre-wrap; overflow-wrap:anywhere; line-height:1.5; }
    .user-directory-full-qzone { margin-top:10px; display:grid; gap:8px; }
    .atri-directory-publisher { border-color:rgba(125,211,252,.34); background:linear-gradient(135deg,rgba(125,211,252,.14),rgba(167,139,250,.12)); }
    .user-directory-integrated-toolbar { display:flex; flex-wrap:wrap; align-items:center; gap:10px; margin:12px 0 4px; padding:11px 13px; border:1px solid rgba(125,211,252,.24); border-radius:12px; background:rgba(125,211,252,.08); }
    .user-directory-integrated-toolbar .note:last-child { flex:1 1 280px; }
    .qzone-model-global-control { min-width:240px; }
    .user-directory-group-summary { margin-top:12px; }
    .summary-plan-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:8px; margin-top:10px; }
    .summary-plan-grid .summary-plan { display:grid; gap:6px; padding:9px; border:1px solid rgba(167,139,250,.16); border-radius:10px; }
    .directory-group-summary-history { display:grid; gap:8px; margin-top:10px; }
    @media (max-width:800px) { .summary-plan-grid { grid-template-columns:1fr; } }
    .empty { color:var(--muted); padding:22px; text-align:center; }
    .modal { position:fixed; inset:0; display:none; align-items:stretch; justify-content:flex-end; background:rgba(15,23,42,.38); padding:0; z-index:20; }
    .modal.show { display:flex; }
    .dialog { width:min(560px,100vw); height:100%; max-height:none; overflow:hidden; background:rgba(255,255,255,.78); border-radius:22px 0 0 22px; border:1px solid rgba(255,255,255,.8); box-shadow:-18px 0 45px rgba(120,80,200,.2); backdrop-filter:blur(20px); display:grid; grid-template-rows:auto auto 1fr auto; }
    .dialog-head { padding:16px 18px; border-bottom:1px solid var(--line); display:flex; gap:12px; justify-content:space-between; align-items:flex-start; }
    .dialog-title { font-size:18px; font-weight:800; }
    .dialog-body { overflow:auto; padding:18px; background:rgba(253,246,249,.48); }
    .dialog-foot { padding:14px 18px; border-top:1px solid rgba(167,139,250,.16); background:rgba(255,255,255,.5); display:flex; justify-content:space-between; gap:12px; align-items:center; }
    .mini-tabs { display:flex; gap:8px; flex-wrap:wrap; padding:12px 18px; border-bottom:1px solid rgba(167,139,250,.16); background:rgba(255,255,255,.44); }
    .mini-tab { background:rgba(255,255,255,.45); color:var(--muted); }
    .mini-tab.active { background:linear-gradient(135deg,#7dd3fc,#a78bfa); color:#312e4a; }
    .stat-grid { display:grid; grid-template-columns:repeat(4,minmax(130px,1fr)); gap:10px; margin:12px 0; }
    .stat { border:1px solid rgba(255,255,255,.72); border-radius:16px; background:rgba(255,255,255,.48); padding:14px; }
    .stat strong { display:block; font-size:18px; margin-bottom:2px; }
    .fact-grid { display:grid; grid-template-columns:repeat(2,minmax(220px,1fr)); gap:10px; margin:12px 0; }
    .fact { border:1px solid rgba(255,255,255,.72); border-radius:16px; background:rgba(255,255,255,.48); padding:14px; min-width:0; }
    .fact span { display:block; color:var(--muted); font-size:12px; margin-bottom:4px; }
    .fact strong { display:block; font-size:14px; overflow-wrap:anywhere; }
    .group-info-list { display:grid; gap:10px; margin-top:8px; }
    .group-info { border:1px solid rgba(255,255,255,.72); border-radius:16px; background:rgba(255,255,255,.48); padding:14px; display:grid; gap:8px; }
    .group-info-head { display:flex; justify-content:space-between; gap:10px; align-items:flex-start; }
    .group-info-title { font-weight:800; overflow-wrap:anywhere; }
    .entry-list { display:grid; gap:10px; }
    .entry { border:1px solid rgba(255,255,255,.72); border-radius:16px; background:rgba(255,255,255,.48); padding:14px; display:grid; gap:10px; }
    .entry-head { display:flex; justify-content:space-between; gap:10px; align-items:center; }
    .entry-grid { display:grid; grid-template-columns:180px 1fr 130px 130px; gap:10px; }
    .history-item { border:1px solid rgba(255,255,255,.72); border-radius:16px; background:rgba(255,255,255,.48); padding:14px; display:grid; gap:8px; margin-bottom:8px; }
    .dirty { color:var(--amber); font-weight:700; }
    .saved { color:var(--green); font-weight:700; }
    .settings-section { border:1px solid var(--line); border-radius:8px; padding:0 14px 14px; margin-top:14px; background:#fff; }
    .settings-section > h3, .settings-section > .section-head { padding:14px 0 10px; margin:0; border-bottom:1px solid var(--line); }
    .settings-section.accordion-section.collapsed > :not(h3):not(.section-head) { display:none; }
    .settings-section.accordion-section > h3, .settings-section.accordion-section > .section-head { cursor:pointer; }
    .settings-section h3 { margin-top:0; }
    .proactive-layout { display:grid; grid-template-columns:minmax(0,.92fr) minmax(560px,1.08fr); gap:14px; align-items:start; }
    .proactive-layout > * { min-width:0; }
    .proactive-block { border:1px solid rgba(255,255,255,.72); border-radius:18px; padding:16px; background:rgba(255,255,255,.48); min-width:0; }
    .proactive-block h3 { margin-top:0; }
    /* 小卡片各自独立成列：数值分档那种宽表格通栏，门槛/权重/预览这类窄卡片并排。 */
    .card-columns { columns:360px 3; column-gap:14px; }
    .card-columns > .proactive-block { break-inside:avoid; margin:0 0 14px; display:inline-block; width:100%; }
    .test-extension { margin-top:14px; padding:12px 14px; border:1px dashed rgba(167,139,250,.35); border-radius:16px; background:rgba(255,255,255,.32); }
    .test-extension > summary { cursor:pointer; font-weight:700; }
    .test-extension .grid { margin-top:10px; }
    .proactive-block .grid { grid-template-columns:repeat(2,minmax(0,1fr)); }
    .proactive-block label { min-width:0; }
    .voice-policy-grid .proactive-block { border:0; border-left:3px solid var(--line); border-radius:0; padding:0 0 0 14px; }
    .compact-input { min-width:84px; }
    /* 分档面板：三个维度共用一张卡片，用页签切换，避免同一组数字出现多个入口。 */
    .tier-workbench { border-color:rgba(167,139,250,.3); }
    .tier-tabs { display:flex; flex-wrap:wrap; gap:8px; margin:2px 0 14px; }
    .tier-tab { background:rgba(255,255,255,.6); border:1px solid rgba(167,139,250,.28); color:var(--ink); border-radius:999px; padding:8px 16px; font-size:13px; cursor:pointer; display:inline-flex; align-items:center; gap:8px; box-shadow:none; }
    .tier-tab:hover { border-color:rgba(167,139,250,.55); color:var(--ink); }
    .tier-tab.active { background:linear-gradient(120deg,rgba(167,139,250,.9),rgba(96,178,255,.85)); border-color:transparent; color:#fff; }
    .tier-tab-badge { font-size:11px; padding:1px 8px; border-radius:999px; background:rgba(255,255,255,.42); color:inherit; }
    .tier-pane { display:none; }
    .tier-pane.active { display:block; animation:fadeUp .3s ease both; }
    /* 页签里嵌一块小配置（例如群聊主动消息）：用左边框弱化层级，不再套一层卡片阴影。 */
    .tile-subblock { margin-top:12px; padding:14px 0 0 14px; border:0; border-left:3px solid rgba(96,178,255,.4); border-radius:0; background:transparent; }
    .tile-subblock h4 { margin:0 0 6px; }
    .tier-summary-item { display:grid; gap:2px; padding:10px 12px; border:1px solid rgba(167,139,250,.18); border-radius:14px; background:rgba(255,255,255,.45); margin-bottom:8px; }
    .tier-summary-item span { font-size:12px; opacity:.78; }
    .weight-title { margin:12px 0 6px; font-size:12px; letter-spacing:.06em; opacity:.66; }
    /* 亲密度分档：回复侧与主动侧共用一张表，用分组表头区分两组频率参数。
       10 列要在常见分辨率下一屏放完（否则最右边的「主动发起」会被裁掉），
       所以单元格和输入框都比默认更紧凑。 */
    .tier-table-scroll { max-height:none; }
    .tier-table { min-width:940px; }
    .tier-table-group { min-width:860px; }
    .tier-table th { white-space:nowrap; padding:9px 8px; font-size:12px; }
    .tier-table td { padding:9px 8px; }
    .tier-table .tier-col-stage { min-width:78px; }
    .tier-table .tier-col-switch { min-width:46px; }
    .tier-table .tier-col-range { min-width:150px; }
    .tier-table .compact-input { min-width:0; width:100%; padding:8px 9px; }
    .tier-table .row { gap:5px; }
    .tier-table .tier-group { text-align:center; letter-spacing:.03em; }
    .tier-table .tier-group-head th { border-bottom:1px solid rgba(167,139,250,.28); }
    .tier-table .tier-group-reply { background:rgba(167,139,250,.09); }
    .tier-table .tier-group-proactive { background:rgba(96,178,255,.13); }
    .tier-table tbody td.tier-group-proactive-cell { background:rgba(96,178,255,.05); }
    .tier-table tbody tr:hover td { background:rgba(255,255,255,.32); }
    .tier-table tbody td.tier-group-proactive-cell:hover { background:rgba(96,178,255,.1); }
    .weight-grid { display:grid; grid-template-columns:repeat(2,minmax(150px,1fr)); gap:10px; }
    .weight-grid-compact { grid-template-columns:repeat(2,minmax(104px,1fr)); gap:8px; }
    .weight-grid-compact label { font-size:12px; }
    .weight-grid-compact input { padding:8px 9px; }
    .switch-line { display:flex; align-items:center; gap:9px; min-height:38px; }
    .switch-line input { width:18px; height:18px; }
    .memory-score { font-weight:800; margin-bottom:6px; }
    .memory-plan { display:grid; gap:5px; margin-top:7px; width:fit-content; max-width:100%; }
    .plan-time-row { display:grid; grid-template-columns:minmax(140px,auto) auto; gap:6px; align-items:center; max-width:100%; }
    .plan-time-row input { min-width:0; padding:6px 8px; font-size:12px; }
    .plan-time-row button { padding:6px 9px; font-size:12px; }
    .relationship-controls { border-top:1px solid var(--line); border-bottom:1px solid var(--line); padding:14px 0; margin:14px 0; }
    .relationship-controls h3 { margin-top:0; }
    .voice-status { display:grid; grid-template-columns:repeat(3,minmax(160px,1fr)); gap:10px; }
    .voice-module-nav { display:grid; grid-template-columns:repeat(2,minmax(260px,1fr)); gap:12px; }
    .voice-module-tab { display:flex; align-items:center; justify-content:space-between; gap:16px; padding:16px 18px; border:1px solid rgba(255,255,255,.72); border-radius:18px; background:rgba(255,255,255,.48); color:var(--ink); text-align:left; }
    .voice-module-tab:hover { border-color:#9bb7f5; background:var(--blue-soft); }
    .voice-module-tab.active { border-color:var(--blue); background:var(--blue-soft); box-shadow:0 0 0 2px rgba(37,99,235,.1); }
    .voice-module-tab strong,.voice-module-tab small { display:block; }
    .voice-module-tab strong { font-size:16px; }
    .voice-module-tab small { margin-top:4px; color:var(--muted); font-weight:500; }
    .service-owner { flex:0 0 auto; border:1px solid #b8c9ee; border-radius:999px; padding:5px 9px; color:#315da8; background:#fff; font:700 11px Consolas,monospace; }
    .voice-module-panel { display:none; }
    .voice-module-panel.active { display:grid; gap:12px; }
    .voice-module-hero { border-left:4px solid var(--blue); }
    .voice-module-hero.music { border-left-color:#7c3aed; }
    .voice-module-hero .section-head { margin-bottom:12px; }
    .voice-primary-action { border:1px solid #c7d7fa; background:linear-gradient(135deg,#f8fbff,#edf3ff); }
    .music-primary-action { border:1px solid #d8c8fb; background:linear-gradient(135deg,#fbfaff,#f3efff); }
    .music-import-box { margin:12px 0 16px; padding:14px; border:1px dashed #9b86d9; border-radius:14px; background:rgba(248,246,255,.82); display:grid; gap:10px; }
    .music-import-box strong { color:#4d3d86; }
    .music-delivery-grid { display:grid; grid-template-columns:minmax(260px,.85fr) minmax(320px,1.15fr); gap:14px; align-items:start; }
    .music-delivery-list { display:grid; gap:10px; }
    .music-delivery-song { padding:13px; border:1px solid rgba(167,139,250,.22); border-radius:16px; background:rgba(255,255,255,.52); }
    .music-delivery-song strong { color:#312e4a; }
    .voice-compare { display:grid; grid-template-columns:repeat(2,minmax(260px,1fr)); gap:12px; margin-top:14px; }
    .voice-result { border:1px solid rgba(255,255,255,.72); border-radius:18px; padding:16px; background:rgba(255,255,255,.48); min-width:0; }
    .voice-result h3 { margin:0 0 10px; }
    .voice-result audio { margin-top:10px; }
    .singing-test-grid { display:grid; grid-template-columns:minmax(280px,0.9fr) minmax(360px,1.1fr); gap:14px; }
    .singing-test-block { border:1px solid rgba(255,255,255,.72); border-radius:18px; padding:16px; background:rgba(255,255,255,.48); min-width:0; }
    .singing-test-block h3 { margin:0 0 12px; }
    .singing-job-list { display:grid; gap:8px; margin-top:10px; }
    .singing-job { display:grid; grid-template-columns:minmax(140px,1fr) 90px 56px auto; gap:10px; align-items:center; border:1px solid rgba(255,255,255,.72); border-radius:16px; padding:14px; background:rgba(255,255,255,.48); }
    .singing-job strong,.singing-job small { display:block; }
    .singing-job small { color:var(--muted); margin-top:3px; overflow-wrap:anywhere; }
    .singing-progress { height:6px; border-radius:999px; background:#e8ecf2; overflow:hidden; margin-top:6px; }
    .singing-progress span { display:block; height:100%; background:var(--blue); }
    .singing-state { font-weight:800; font-size:12px; }
    .singing-state.succeeded { color:var(--green); }
    .singing-state.failed,.singing-state.cancelled { color:var(--red); }
    .singing-state.running,.singing-state.queued { color:var(--blue); }
    .singing-job button { padding:6px 9px; font-size:12px; }
    .music-project-toolbar { display:grid; grid-template-columns:minmax(240px,1fr) auto; gap:12px; align-items:end; }
    .music-stage-grid { display:grid; grid-template-columns:1fr; gap:14px; align-items:start; }
    .music-stage-card { border:1px solid rgba(255,255,255,.72); border-radius:20px; background:rgba(255,255,255,.48); padding:18px; min-width:0; }
    .music-stage-layout { display:grid; grid-template-columns:minmax(260px,.72fr) minmax(0,1.28fr); gap:16px; align-items:start; }
    .music-control-grid { display:grid; grid-template-columns:repeat(3,minmax(150px,1fr)); gap:10px; }
    .music-stage-actions { display:flex; flex-wrap:wrap; gap:8px; margin-top:10px; }
    .music-editor { border:1px solid #cad6ea; background:#f8fbff; border-radius:7px; padding:12px; margin-top:10px; }
    .music-range-grid { display:grid; grid-template-columns:repeat(4,minmax(120px,1fr)); gap:9px; }
    .music-quality { display:grid; grid-template-columns:repeat(4,minmax(130px,1fr)); gap:8px; margin-top:10px; }
    .music-quality-item { padding:8px; border-radius:6px; background:#f2f4f7; font-size:12px; }
    .music-quality-item.pass { background:#eaf7ef; color:#176b36; }
    .music-quality-item.fail { background:#fff0f0; color:#a32626; }
    .music-revision-bar { display:grid; grid-template-columns:minmax(220px,1fr) auto auto; gap:8px; align-items:end; margin-top:10px; }
    .music-stage-card.ready { border-color:#8eb0f5; box-shadow:0 0 0 2px rgba(37,99,235,.08); }
    .music-stage-card.succeeded { border-color:#8fd1a4; }
    .music-stage-card.failed { border-color:#e9a3a3; }
    .music-stage-head { display:flex; justify-content:space-between; gap:8px; align-items:flex-start; margin-bottom:10px; }
    .music-stage-head h3 { margin:0; }
    .music-stage-index { display:inline-grid; place-items:center; width:24px; height:24px; border-radius:999px; margin-right:7px; background:var(--blue-soft); color:var(--blue); font-size:12px; }
    .music-stage-state { font-size:12px; font-weight:800; color:var(--muted); }
    .music-stage-state.running { color:var(--blue); }
    .music-stage-state.succeeded { color:var(--green); }
    .music-stage-state.failed { color:var(--red); }
    .stepper { display:grid; grid-template-columns:repeat(3,1fr); gap:10px; padding:0; margin:0; list-style:none; counter-reset:stage; }
    .stepper li { position:relative; padding:10px 12px 10px 38px; border:1px solid var(--line); border-radius:8px; background:#f8fafc; color:var(--muted); font-weight:700; }
    .stepper li::before { counter-increment:stage; content:counter(stage); position:absolute; left:11px; top:10px; width:20px; height:20px; display:grid; place-items:center; border-radius:50%; background:#e2e8f0; color:#475569; font-size:12px; }
    .stepper li.active { color:var(--blue); border-color:#9bb7f5; background:var(--blue-soft); }
    .stepper li.active::before { background:var(--blue); color:#fff; }
    .stepper li.done { color:var(--green); border-color:#9fd6ae; background:#f0fdf4; }
    .stepper li.done::before { content:'✓'; background:var(--green); color:#fff; }
    .music-track { border-top:1px solid var(--line); padding-top:10px; margin-top:10px; }
    .music-track strong { display:block; font-size:12px; margin-bottom:5px; }
    .music-waveform { width:100%; height:78px; display:block; border-radius:5px; background:#eef2f7; }
    .music-waveform.selectable { cursor:crosshair; touch-action:none; outline:1px solid #bfcee8; }
    .music-track audio { margin-top:6px; }
    .music-preview-button { margin-top:7px; width:100%; }
    .param-help { display:block; color:var(--muted); font-size:11px; font-weight:500; line-height:1.45; margin-top:4px; }
    .service-switch { margin-top:10px; gap:12px; }
    .service-switch .param-help { margin-top:0; flex:1 1 320px; }
    .music-section-list { display:grid; gap:7px; margin-top:10px; }
    .music-section-item { display:grid; grid-template-columns:36px minmax(0,1fr) auto; gap:9px; align-items:center; border:1px solid var(--line); border-radius:7px; padding:8px 10px; background:#f8fafc; }
    .music-section-item .index { color:var(--blue); font-weight:800; }
    .music-section-item .time { color:var(--muted); font:12px ui-monospace,SFMono-Regular,Consolas,monospace; }
    .music-terminal { min-height:150px; max-height:320px; overflow:auto; white-space:pre-wrap; word-break:break-word; border:1px solid #bfd0e8; border-radius:8px; background:#f4f8fd; color:#18324f; padding:12px; font:12px/1.55 ui-monospace,SFMono-Regular,Consolas,monospace; }
    .music-stage-card .grid { grid-template-columns:1fr; }
    .qzone-layout { display:grid; grid-template-columns:minmax(280px,.65fr) minmax(440px,1.35fr); gap:14px; align-items:start; }
    .qzone-feed-list { display:grid; gap:12px; }
    .qzone-feed { border:1px solid rgba(167,139,250,.2); border-radius:18px; padding:16px; background:rgba(255,255,255,.5); }
    .qzone-feed-head { display:flex; justify-content:space-between; gap:12px; align-items:flex-start; }
    .qzone-feed-content { margin:12px 0; white-space:pre-wrap; overflow-wrap:anywhere; }
    .qzone-comment { min-height:82px; }
    .qzone-automation-head { display:flex; justify-content:space-between; gap:14px; align-items:flex-start; margin-bottom:14px; }
    .qzone-automation-head h2 { margin:0 0 4px; }
    .qzone-automation-grid { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1fr); gap:14px; align-items:start; }
    .qzone-form-grid { grid-template-columns:repeat(2,minmax(0,1fr)); }
    .qzone-content-pool,.qzone-target-list,.qzone-log-list { display:grid; gap:9px; margin-top:12px; max-height:420px; overflow:auto; }
    .qzone-content-item,.qzone-target-item,.qzone-log-item { border:1px solid rgba(167,139,250,.2); border-radius:15px; padding:12px; background:rgba(255,255,255,.48); }
    .qzone-content-item,.qzone-target-item { display:grid; gap:8px; }
    .qzone-content-head,.qzone-target-head,.qzone-log-head { display:flex; justify-content:space-between; gap:10px; align-items:flex-start; }
    .qzone-content-text { white-space:pre-wrap; overflow-wrap:anywhere; }
    .qzone-log-item { font-size:12px; }
    .qzone-log-content { margin-top:5px; white-space:pre-wrap; overflow-wrap:anywhere; color:var(--muted); }
    .qzone-target-item label { display:flex; align-items:center; gap:8px; }
    .qzone-target-item input[type=checkbox] { width:18px; height:18px; }
    .qzone-stat-line { display:flex; flex-wrap:wrap; gap:8px; margin-top:10px; }
    .qzone-stat-line .badge { min-width:92px; justify-content:center; }
    .qzone-feed-browser { margin-bottom:14px; }
    .qzone-feed-toolbar { display:grid; grid-template-columns:minmax(180px,1.5fr) minmax(220px,2fr) 90px auto; gap:10px; align-items:center; margin:10px 0; }
    .qzone-feed-toolbar + .qzone-feed-toolbar { grid-template-columns:minmax(180px,1fr) auto auto; }
    .qzone-feed-actions { display:flex; flex-wrap:wrap; gap:8px; margin-top:12px; }
    .qzone-feed-actions button { min-height:36px; padding:7px 12px; }
    .qzone-person-row { display:grid; gap:12px; padding:18px; border:1px solid rgba(167,139,250,.2); border-radius:20px; background:rgba(255,255,255,.56); }
    .qzone-person-row.pinned { border-color:rgba(96,165,250,.55); box-shadow:0 12px 28px rgba(96,165,250,.12); }
    .qzone-person-head { display:flex; justify-content:space-between; gap:12px; align-items:flex-start; }
    .qzone-person-name { display:flex; gap:8px; align-items:center; flex-wrap:wrap; }
    .qzone-person-switches { display:flex; gap:12px; flex-wrap:wrap; }
    .qzone-person-switches label { display:flex; align-items:center; gap:6px; font-size:12px; color:var(--muted); }
    .qzone-person-switches input { width:17px; height:17px; }
    .qzone-inline-detail { margin-top:4px; padding:14px 0 0; border-top:1px solid var(--line); }
    .qzone-detail-list { display:grid; gap:10px; margin-top:12px; }
    .qzone-detail-item { padding:13px; border:1px solid var(--line); border-radius:14px; background:rgba(255,255,255,.42); }
    .qzone-atri-publisher { display:grid; gap:10px; padding:14px; border-radius:16px; background:rgba(219,234,254,.38); border:1px solid rgba(96,165,250,.28); }
    .qzone-atri-publisher .form-grid { margin-top:0; }
    .qzone-next-post { display:grid; gap:5px; padding:10px 12px; border-radius:12px; background:rgba(255,255,255,.5); border:1px solid rgba(96,165,250,.2); }
    .qzone-next-post-content { white-space:pre-wrap; overflow-wrap:anywhere; color:var(--text); }
    .qzone-manual-actions { display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin-top:8px; }
    .qzone-manual-actions input,.qzone-manual-actions textarea { flex:1 1 260px; min-width:220px; min-height:38px; box-sizing:border-box; }
    .qzone-manual-actions textarea { resize:vertical; }
    .qzone-list-foot { margin:12px 2px 0; }
    audio { width:100%; min-height:42px; }
    .surface,.profile,.model-card,.profile-column,.proactive-block,.voice-result,.singing-test-block,.singing-job,.music-stage-card,.stat,.fact,.group-info,.entry,.history-item,.thumb,.pill { transition:transform .22s ease,box-shadow .22s ease,border-color .22s ease; animation:fadeUp .55s ease both; }
    .surface:hover,.profile:hover,.model-card:hover,.profile-column:hover,.proactive-block:hover,.voice-result:hover,.singing-test-block:hover,.singing-job:hover,.music-stage-card:hover,.stat:hover,.fact:hover,.group-info:hover,.entry:hover,.history-item:hover,.thumb:hover { transform:translateY(-4px); box-shadow:0 14px 34px rgba(120,80,200,.12); }
    .panel.active { animation:panelIn .25s ease both; }
    .status:empty::after { content:'●  ●  ●'; display:block; color:#7dd3fc; letter-spacing:5px; text-align:center; animation:breathe 1.1s ease-in-out infinite; }
    @keyframes fadeUp { from { opacity:0; transform:translateY(12px); } to { opacity:1; transform:translateY(0); } }
    @keyframes panelIn { from { opacity:0; transform:translateY(6px); } to { opacity:1; transform:translateY(0); } }
    @keyframes breathe { 0%,100% { opacity:.35; transform:translateY(0); } 50% { opacity:1; transform:translateY(-2px); } }
    @keyframes twinkle { 0%,100% { transform:rotate(0) scale(.85); opacity:.55; } 50% { transform:rotate(18deg) scale(1.18); opacity:1; } }
    @media (max-width:1280px) {
      #model.panel.active { display:block; }
      .model-workspace { display:block; }
      #model .model-profile-surface { margin-top:14px; }
      #modelProfileEditor { position:static; }
    }
    @media (max-width:980px) {
      .global-status .status,.model-workspace,.split,.singing-test-grid,.qzone-layout,.qzone-automation-grid,.voice-module-nav,.music-stage-grid,.music-project-toolbar,.music-stage-layout,.music-control-grid,.music-range-grid,.music-quality,.music-revision-bar,.stepper,.score-grid,.evaluation-model-grid,.delivery-grid { grid-template-columns:1fr; }
      #evaluationDashboardPanel.active { display:grid; grid-template-columns:1fr; }
      #evaluationDashboardPanel > .surface,
      #evaluationDashboardPanel > .split { grid-column:1 / -1; }
      .grid,.three,.profile-columns,.stat-grid,.fact-grid,.entry-grid,.proactive-layout,.weight-grid,.voice-status,.voice-compare,.user-directory-inline-memory .card-context-values { grid-template-columns:1fr; }
      /* 窄屏下小卡片不再分列，逐张纵向排。 */
      .card-columns { columns:1; }
      .qzone-form-grid,.qzone-feed-toolbar { grid-template-columns:1fr; }
      .form-grid > label { grid-template-columns:1fr; gap:6px; }
      button { min-height:44px; }
      .proactive-block .grid { grid-template-columns:1fr; }
      .section-head { flex-direction:column; }
      .section-head .row { width:100%; }
      .dialog { width:98vw; }
    }
    @media (min-width:981px) and (max-width:1280px) {
      #evaluationDashboardPanel > .surface:nth-of-type(2) { grid-column:1 / -1; }
      #evaluationDashboardPanel > .split { grid-column:1 / -1; grid-template-columns:repeat(2,minmax(0,1fr)); }
    }
    @media (max-width:640px) {
      body { background:#faf5ff; }
      header,aside,section,.surface,.tabs { backdrop-filter:none; }
      header { padding:18px 16px; }
      main { width:calc(100% - 24px); padding:12px 0 24px; }
      .global-status { width:calc(100% - 24px); margin:12px auto; padding:16px; }
      .tabs { top:70px; border-radius:20px; }
      .tabs .tab { flex:1 1 calc(33.333% - 8px); }
      .surface,aside,section { border-radius:18px; padding:16px; }
      .dialog { border-radius:20px 0 0 20px; }
    }
    @media (prefers-reduced-motion:reduce) {
      *,*::before,*::after { animation-duration:.01ms !important; animation-iteration-count:1 !important; transition-duration:.01ms !important; }
    }
  </style>
</head>
<body>
"""
