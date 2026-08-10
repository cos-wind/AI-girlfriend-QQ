from __future__ import annotations


def render_index() -> str:
    return """<!doctype html>
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
    main { max-width:1480px; margin:0 auto; padding:18px; display:block; }
    main > section { min-width:0; }
    aside, section, .surface { background:var(--panel); border:1px solid rgba(255,255,255,.72); border-radius:20px; padding:20px; box-shadow:0 8px 32px rgba(120,80,200,.08),0 2px 8px rgba(120,80,200,.04); backdrop-filter:blur(16px); }
    .global-status { max-width:1480px; margin:18px auto 0; padding:20px 22px; }
    .global-status .section-head { margin-bottom:12px; }
    .global-status .status { grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); }
    .sub,.note,.hint { color:var(--muted); font-size:12px; line-height:1.65; }
    .tabs { display:flex; gap:7px; flex-wrap:wrap; margin-bottom:18px; position:sticky; top:78px; z-index:7; padding:8px; background:rgba(255,255,255,.56); border:1px solid rgba(255,255,255,.76); border-radius:999px; box-shadow:0 8px 24px rgba(120,80,200,.08); backdrop-filter:blur(16px); }
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
    .proactive-layout { display:grid; grid-template-columns:minmax(0,1.18fr) minmax(320px,.82fr); gap:14px; align-items:start; }
    .proactive-layout > * { min-width:0; }
    .proactive-block { border:1px solid rgba(255,255,255,.72); border-radius:18px; padding:16px; background:rgba(255,255,255,.48); min-width:0; }
    .proactive-block h3 { margin-top:0; }
    .proactive-block .grid { grid-template-columns:repeat(2,minmax(0,1fr)); }
    .proactive-block label { min-width:0; }
    .voice-policy-grid .proactive-block { border:0; border-left:3px solid var(--line); border-radius:0; padding:0 0 0 14px; }
    .compact-input { min-width:84px; }
    .weight-grid { display:grid; grid-template-columns:repeat(2,minmax(150px,1fr)); gap:10px; }
    .switch-line { display:flex; align-items:center; gap:9px; min-height:38px; }
    .switch-line input { width:18px; height:18px; }
    .memory-score { font-weight:800; margin-bottom:6px; }
    .memory-plan { display:grid; gap:5px; margin-top:7px; }
    .plan-time-row { display:grid; grid-template-columns:minmax(120px,1fr) auto; gap:6px; align-items:center; }
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
    .music-section-list { display:grid; gap:7px; margin-top:10px; }
    .music-section-item { display:grid; grid-template-columns:36px minmax(0,1fr) auto; gap:9px; align-items:center; border:1px solid var(--line); border-radius:7px; padding:8px 10px; background:#f8fafc; }
    .music-section-item .index { color:var(--blue); font-weight:800; }
    .music-section-item .time { color:var(--muted); font:12px ui-monospace,SFMono-Regular,Consolas,monospace; }
    .music-terminal { min-height:150px; max-height:320px; overflow:auto; white-space:pre-wrap; word-break:break-word; border:1px solid #bfd0e8; border-radius:8px; background:#f4f8fd; color:#18324f; padding:12px; font:12px/1.55 ui-monospace,SFMono-Regular,Consolas,monospace; }
    .music-stage-card .grid { grid-template-columns:1fr; }
    .minecraft-grid { display:grid; grid-template-columns:minmax(320px,.85fr) minmax(440px,1.15fr); gap:14px; align-items:start; }
    .minecraft-status { display:grid; grid-template-columns:repeat(3,minmax(140px,1fr)); gap:10px; margin:12px 0; }
    .minecraft-maids { display:grid; gap:10px; margin-top:12px; }
    .minecraft-maid { border:1px solid rgba(255,255,255,.72); border-radius:18px; padding:16px; background:rgba(255,255,255,.48); display:grid; gap:10px; }
    .minecraft-maid.selected { border-color:var(--blue); box-shadow:0 0 0 2px rgba(37,99,235,.12); }
    .minecraft-maid-head { display:flex; justify-content:space-between; gap:10px; align-items:flex-start; }
    .minecraft-maid-meta { display:grid; grid-template-columns:repeat(4,minmax(90px,1fr)); gap:8px; }
    .minecraft-maid-meta div { background:#f8fafc; border-radius:6px; padding:8px; min-width:0; }
    .minecraft-maid-meta span { display:block; color:var(--muted); font-size:11px; margin-bottom:3px; }
    .minecraft-command-grid { display:grid; grid-template-columns:repeat(4,minmax(90px,1fr)); gap:8px; margin-top:12px; }
    audio { width:100%; min-height:42px; }
    .surface,.profile,.model-card,.profile-column,.proactive-block,.voice-result,.singing-test-block,.singing-job,.music-stage-card,.minecraft-maid,.stat,.fact,.group-info,.entry,.history-item,.thumb,.pill { transition:transform .22s ease,box-shadow .22s ease,border-color .22s ease; animation:fadeUp .55s ease both; }
    .surface:hover,.profile:hover,.model-card:hover,.profile-column:hover,.proactive-block:hover,.voice-result:hover,.singing-test-block:hover,.singing-job:hover,.music-stage-card:hover,.minecraft-maid:hover,.stat:hover,.fact:hover,.group-info:hover,.entry:hover,.history-item:hover,.thumb:hover { transform:translateY(-4px); box-shadow:0 14px 34px rgba(120,80,200,.12); }
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
      .global-status .status,.model-workspace,.split,.singing-test-grid,.minecraft-grid,.voice-module-nav,.music-stage-grid,.music-project-toolbar,.music-stage-layout,.music-control-grid,.music-range-grid,.music-quality,.music-revision-bar,.stepper { grid-template-columns:1fr; }
      .grid,.three,.profile-columns,.stat-grid,.fact-grid,.entry-grid,.proactive-layout,.weight-grid,.voice-status,.voice-compare,.minecraft-status,.minecraft-maid-meta,.minecraft-command-grid { grid-template-columns:1fr; }
      .form-grid > label { grid-template-columns:1fr; gap:6px; }
      button { min-height:44px; }
      .proactive-block .grid { grid-template-columns:1fr; }
      .section-head { flex-direction:column; }
      .section-head .row { width:100%; }
      .dialog { width:98vw; }
    }
    @media (max-width:640px) {
      body { background:#faf5ff; }
      header,aside,section,.surface,.tabs { backdrop-filter:none; }
      header { padding:18px 16px; }
      main { padding:12px; }
      .global-status { margin:12px; padding:16px; }
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
  <header>
    <h1>亚托莉控制台</h1>
    <div class="sub">本地 WebUI，只监听 127.0.0.1。这里可以切换模型、管理表情包、查看和编辑记忆。</div>
  </header>
  <section class="global-status" aria-label="运行状态">
    <div class="section-head">
      <div>
        <h2>运行状态</h2>
        <p class="note">核心服务、模型和连接状态一眼可见。API Key 只显示保存状态，不会展示原文。</p>
      </div>
      <div class="row">
        <button class="ghost" onclick="loadStatus()">↻ 刷新</button>
        <button class="secondary" onclick="restartServices()">后台重启</button>
      </div>
    </div>
    <div class="status" id="status"></div>
  </section>
  <main>
    <section>
      <div class="tabs">
        <button class="tab active" onclick="showTab(event,'model')">模型</button>
        <button class="tab" onclick="showTab(event,'voice')">语音</button>
        <button class="tab" onclick="showTab(event,'stickers')">表情包</button>
        <button class="tab" onclick="showTab(event,'memory')">记忆</button>
        <button class="tab" onclick="showTab(event,'test')">测试</button>
        <button class="tab" onclick="showTab(event,'developer')">开发</button>
        <button class="tab" onclick="showTab(event,'minecraft')">Minecraft</button>
        <button class="tab" onclick="showTab(event,'advanced')">高级</button>
      </div>

      <div id="model" class="panel active">
        <div class="model-workspace">
          <div class="stack">
            <div class="surface">
              <h2>当前启用模型</h2>
              <div id="currentModel" class="current-models">读取中...</div>
              <div class="row">
                <button class="ghost" onclick="testCurrentChatModel()">测试当前聊天模型</button>
              </div>
            </div>
            <div class="surface">
              <div class="section-head">
                <div>
                  <h2>本机已部署模型</h2>
                  <p class="note" id="localModelInfo">读取中...</p>
                </div>
                <div class="row">
                  <button class="ghost" onclick="loadLocalModels({manual:true})">刷新</button>
                </div>
              </div>
              <div class="profile-list" id="localModelList"></div>
              <p class="model-feedback" id="localModelAction"></p>
            </div>
          </div>
          <div class="surface" id="modelProfileEditor">
            <h2 id="profileFormTitle">新建模型档案</h2>
            <p class="model-feedback" id="modelFillFeedback"></p>
            <input id="profileId" type="hidden">
            <div class="preset-panel">
              <h3>从厂商模型库填入</h3>
              <div class="form-grid">
                <label>厂商<select id="providerPreset" onchange="selectProviderPreset()"></select></label>
                <label>模型<select id="providerModelPreset" onchange="selectProviderModelPreset()"></select></label>
              </div>
              <div class="row">
                <button class="ghost" onclick="applySelectedProviderModel()">填入到下方档案</button>
              </div>
              <p class="note">这里只负责自动填接口地址、模型名和推荐参数；保存、启用仍由你手动确认。</p>
            </div>
            <h3>档案参数</h3>
            <div class="form-grid">
              <label>档案名称<input id="profileName" placeholder="例如：DeepSeek 官方"></label>
              <label>用途<select id="profileModelType">
                <option value="chat">聊天模型</option>
                <option value="vision">视觉模型</option>
                <option value="embedding">向量模型</option>
              </select></label>
              <label>服务商<input id="profileProvider" placeholder="例如：DeepSeek / Ollama / OpenAI兼容"></label>
              <label>接口地址<input id="profileBaseUrl" placeholder="https://api.deepseek.com/v1"></label>
              <label>模型名称<input id="profileModel" placeholder="deepseek-v4-flash"></label>
              <label>API Key<input id="profileApiKey" type="password" placeholder="已保存时留空可保持原值"></label>
              <label>温度<input id="profileTemperature" type="number" min="0" max="2" step="0.01" value="0.65"></label>
              <label>重复惩罚<input id="profileFrequencyPenalty" type="number" min="0" max="2" step="0.01" value="0.35"></label>
              <label>最大输出<input id="profileMaxTokens" type="number" min="32" max="4096" step="1" value="260"></label>
            </div>
            <div class="row">
              <button onclick="saveProfile()">保存档案</button>
              <button class="ghost" onclick="activateSelectedProfile()">启用档案</button>
              <button class="secondary" onclick="newProfile()">新建空档案</button>
              <button class="danger" onclick="deleteSelectedProfile()">删除档案</button>
            </div>
          </div>
        </div>
        <div class="surface model-profile-surface">
          <div class="section-head">
            <div>
              <h2>模型档案</h2>
              <p class="note">同一类模型只启用一个；聊天、视觉、向量互不挤占。点“编辑”会把档案带到右上表单。</p>
            </div>
            <div class="row">
              <button class="secondary" onclick="newProfile()">新建空档案</button>
            </div>
          </div>
          <div class="profile-list" id="profileList"></div>
        </div>
      </div>

      <div id="voice" class="panel">
        <div class="stack">
          <div class="voice-module-nav" aria-label="语音模块分类">
            <button id="voiceSpeechTab" class="voice-module-tab active" type="button" onclick="showVoiceModule('speech')">
              <span><strong>语音合成</strong><small>说话、识别、音色档案与通话策略</small></span>
              <span class="service-owner">atri_voice_service</span>
            </button>
            <button id="voiceMusicTab" class="voice-module-tab" type="button" onclick="showVoiceModule('music')">
              <span><strong>歌曲合成</strong><small>导唱转换、歌声音色与试听任务</small></span>
              <span class="service-owner">AI_music</span>
            </button>
          </div>

          <div id="voiceSpeechPanel" class="voice-module-panel active">
            <div class="surface voice-module-hero">
              <div class="section-head">
                <div>
                  <h2>语音合成</h2>
                  <p class="note">由 <span class="mono">atri_voice_service · 127.0.0.1:8790</span> 负责语音识别、GPT-SoVITS 合成和质量检查。失败时 QQ 回复自动回退为文字。</p>
                </div>
                <div class="row"><button class="ghost" onclick="loadVoice()">刷新语音状态</button></div>
              </div>
              <div id="voiceServiceStatus" class="voice-status"></div>
            </div>
            <div class="surface">
              <ol class="stepper" aria-label="语音处理流程">
                <li class="active">输入文本与语言</li>
                <li>模型推理</li>
                <li>生成试听</li>
              </ol>
            </div>

            <div class="surface voice-primary-action">
              <div class="section-head">
                <div><h2>语音试听</h2><p class="note">输入文字后生成可播放音频，不会发送到 QQ 或直播前端。</p></div>
              </div>
              <div class="grid">
                <label>试听文本<input id="voicePreviewText" value="主人，我一直都在这里哦。"></label>
                <label>语言<select id="voicePreviewLanguage" onchange="useVoicePreviewLanguageSample()"><option value="zh">中文</option><option value="en">English</option><option value="ja">日本語</option></select></label>
                <label>情绪<select id="voicePreviewEmotion"><option value="gentle">温柔</option><option value="neutral">自然</option><option value="happy">开心</option><option value="shy">害羞</option><option value="sad">难过</option><option value="sleepy">困倦</option><option value="serious">认真</option><option value="surprised">惊讶</option></select></label>
                <label>声音来源<select id="voicePreviewMode"><option value="speech">模型语音合成</option><option value="singing">匹配原声素材</option></select></label>
              </div>
              <div class="row"><button id="voicePreviewButton" onclick="previewVoice()">生成语音试听</button></div>
              <p class="note" id="voicePreviewInfo">选择中文、English 或日本語会自动切换测试文本。</p>
              <audio id="voicePreviewAudio" controls preload="metadata"></audio>
            </div>

            <div class="split">
              <div class="surface">
                <h2>使用策略</h2>
                <div class="grid">
                  <label class="switch-line"><input id="voiceAsrEnabled" type="checkbox">识别用户语音</label>
                  <label class="switch-line"><input id="voiceTtsEnabled" type="checkbox">允许模型自主发语音</label>
                  <label class="switch-line"><input id="voiceGroupEnabled" type="checkbox">允许群聊语音</label>
                  <label class="switch-line"><input id="voiceReplyToVoice" type="checkbox">语音消息优先考虑语音回复</label>
                  <label>语音服务地址<input id="voiceServiceUrl" value="http://127.0.0.1:8790"></label>
                  <label>当前角色档案<select id="voiceProfileId" onchange="loadSelectedVoiceProfile()"></select></label>
                  <label>单条最大字数<input id="voiceMaxChars" type="number" min="20" max="500"></label>
                  <label>同会话冷却秒数<input id="voiceCooldown" type="number" min="0" max="3600"></label>
                </div>
                <div class="row"><button onclick="saveVoice()">保存语音配置</button></div>
              </div>
              <div class="surface">
                <h2>亚托莉语音档案</h2>
                <div class="grid">
                  <label>显示名称<input id="voiceDisplayName" value="亚托莉"></label>
                  <label>合成引擎<select id="voiceProvider"><option value="gpt_sovits">GPT-SoVITS</option></select></label>
                  <label>引擎接口<input id="voiceApiUrl" value="http://127.0.0.1:9880/tts"></label>
                  <label>参考音频语言<select id="voicePromptLanguage"><option value="ja">日语</option><option value="zh">中文</option><option value="en">英语</option></select></label>
                </div>
                <label>参考音频原文<textarea id="voicePromptText" placeholder="必须与参考音频实际台词一致"></textarea></label>
                <label>参考音频路径<input id="voiceReferencePath" readonly placeholder="尚未上传"></label>
                <div class="row">
                  <input id="voiceReferenceFile" type="file" accept=".wav,.flac,.mp3,.ogg,.m4a,.aac,audio/*">
                  <button class="ghost" onclick="uploadVoiceReference()">上传参考音频</button>
                </div>
                <p class="note">只使用你有权使用的清晰、单人、无背景音乐音频。参考原文和音频不一致会明显降低音色与发音质量。</p>
              </div>
            </div>

            <div class="split">
              <div class="surface">
                <h2>语音识别优化</h2>
                <p class="note">每行填写“正确词 = 常见误识别1, 常见误识别2”，保存后立即生效。</p>
                <label>角色名与专有词纠错<textarea id="voiceAsrLexicon" rows="6" placeholder="亚托莉 = 亚托利, 亚托丽"></textarea></label>
              </div>
              <div class="surface">
                <h2>语音合成优化</h2>
                <p class="note">每行填写“原文 = 中文读法 | English pronunciation | 日本語の読み方”。</p>
                <label>中英日发音词典<textarea id="voiceTtsPronunciations" rows="6" placeholder="ATRI = 亚托莉 | Atri | アトリ"></textarea></label>
              </div>
            </div>

            <div class="surface">
              <div class="section-head"><div><h2>自主语音与通话</h2><p class="note">模型负责判断语境是否适合；这里仅设置边界。</p></div></div>
              <div class="three voice-policy-grid">
                <div class="proactive-block">
                  <h3>触发方式</h3>
                  <div class="grid">
                    <label class="switch-line"><input id="voiceBehaviorEnabled" type="checkbox">启用语音决策策略</label>
                    <label class="switch-line"><input id="voiceExplicitEnabled" type="checkbox">明确要求时允许语音</label>
                    <label class="switch-line"><input id="voiceExplicitGuardEnabled" type="checkbox">漏调工具时仍强制语音</label>
                    <label class="switch-line"><input id="voiceInputReplyEnabled" type="checkbox">允许用语音回应语音</label>
                    <label class="switch-line"><input id="voiceProactiveEnabled" type="checkbox">主动消息可使用语音</label>
                    <label class="switch-line"><input id="voiceOriginalClipEnabled" type="checkbox">优先使用匹配原声</label>
                    <label class="switch-line"><input id="voiceQualityGateEnabled" type="checkbox">发送前检查漏字错字</label>
                    <label class="switch-line"><input id="voiceSingingEnabled" type="checkbox">启用歌唱素材回复</label>
                    <label>允许回读错误率<input id="voiceQualityMaxError" type="number" min="0" max="1" step="0.01"></label>
                    <label>质量检查重试次数<input id="voiceQualityRetries" type="number" min="0" max="3"></label>
                    <label>免打扰开始<input id="voiceQuietStart" type="time"></label>
                    <label>免打扰结束<input id="voiceQuietEnd" type="time"></label>
                  </div>
                </div>
                <div class="proactive-block">
                  <h3>关系阈值</h3>
                  <div class="grid">
                    <label class="switch-line"><input id="voicePrivateAutoEnabled" type="checkbox">私聊可自主发语音</label>
                    <label>私聊最低好感<input id="voicePrivateAffection" type="number" min="0" max="100" step="1"></label>
                    <label>私聊最低消息量<input id="voicePrivateMessages" type="number" min="0" max="100000"></label>
                    <label class="switch-line"><input id="voiceGroupAutoEnabled" type="checkbox">群聊可自主发语音</label>
                    <label>群最低活跃度<input id="voiceGroupActivity" type="number" min="0" max="100" step="1"></label>
                    <label>群最低消息量<input id="voiceGroupMessages" type="number" min="0" max="100000"></label>
                  </div>
                </div>
                <div class="proactive-block">
                  <h3>浏览器通话</h3>
                  <div class="grid">
                    <label class="switch-line"><input id="voiceCallsEnabled" type="checkbox">允许模型邀请私聊通话</label>
                    <label>通话最低好感<input id="voiceCallAffection" type="number" min="0" max="100" step="1"></label>
                    <label>通话最低消息量<input id="voiceCallMessages" type="number" min="0" max="100000"></label>
                    <label>邀请有效分钟<input id="voiceCallExpiry" type="number" min="1" max="1440"></label>
                    <label>最长通话分钟<input id="voiceCallMaxMinutes" type="number" min="1" max="240"></label>
                  </div>
                  <label>用户可访问的通话地址<input id="voiceCallBaseUrl" placeholder="http://127.0.0.1:8787"></label>
                  <div class="row"><button class="ghost" onclick="createVoiceCallTest()">创建本机测试通话</button></div>
                  <div class="natural-box" id="voiceCallTestOut">测试链接不会发送 QQ 消息。</div>
                </div>
              </div>
            </div>
          </div>

          <div id="voiceMusicPanel" class="voice-module-panel">
            <div class="surface voice-module-hero music">
              <div class="section-head">
                <div>
                  <h2>歌曲合成</h2>
                  <p class="note">由 <span class="mono">AI_music</span> 负责导唱处理、Seed-VC 歌声转换、伴奏混音和任务管理；音源目录与语音服务保持同步。</p>
                </div>
                <div class="row"><button class="ghost" onclick="loadSingingJobs()">刷新歌曲任务</button></div>
              </div>
              <div id="musicServiceStatus" class="voice-status"></div>
            </div>
            <div class="surface">
              <ol class="stepper" aria-label="歌曲处理流程">
                <li class="active">人声分离</li>
                <li>模型推理</li>
                <li>混音与导出</li>
              </ol>
            </div>

            <div class="surface music-primary-action">
              <div class="section-head">
                <div><h2>新建歌曲工程</h2><p class="note">上传一次原曲，然后依次完成人声分离、模型推理和后期混音。每个阶段都会保存产物，可单独试听和重新运行。</p></div>
              </div>
              <div class="grid">
                <label>歌曲名称<input id="singingSongName" value="亚托莉歌曲工程" maxlength="120"></label>
                <label>亚托莉歌声参考<select id="singingReferencePath"></select></label>
                <label>素材库原曲<select id="musicSourceLibrary" onchange="selectMusicSource()"><option value="">从固定目录选择，或在下方上传</option></select><span class="param-help">固定目录：C:\\Users\\YOUR_NAME\\Music\\QQmusic-MP3\\</span></label>
                <label>原曲文件路径<input id="singingSourcePath" readonly placeholder="上传或从素材库选择后自动填写"></label>
                <label>乐理分段数量<select id="musicSectionCount"><option value="0">自动（推荐，3–5 段）</option><option value="3">固定 3 段</option><option value="4">固定 4 段</option><option value="5">固定 5 段</option></select><span class="param-help">推荐值：自动。依据节拍、小节、和声色度、音色与能量变化寻找边界，不按固定秒数切割。</span></label>
                <label>工程流程<select id="musicWorkflowMode"><option value="guided">分阶段确认（推荐）</option><option value="automatic">全自动三阶段</option></select><span class="param-help">全自动遇到质量检查失败仍会暂停，避免坏结果继续混音。</span></label>
              </div>
              <div class="row">
                <input id="singingSourceFile" type="file" accept=".wav,.flac,.mp3,.ogg,.m4a,.aac,audio/*">
                <button class="ghost" onclick="uploadSingingSource()">上传原曲</button>
                <button id="musicCreateProjectButton" onclick="createMusicProject()">创建三阶段工程</button>
              </div>
              <p class="note">上传只创建可恢复的歌曲工程，不覆盖成品。确认导出后才保存到 <span class="mono">C:\\Users\\YOUR_NAME\\Music\\AI合成音乐</span>。</p>
            </div>

            <div class="surface">
              <div class="music-project-toolbar">
                <label>当前歌曲工程<select id="musicProjectSelect" onchange="selectMusicProject()"><option value="">尚未创建工程</option></select></label>
                <div class="row"><button id="musicRunPipeline" onclick="runMusicPipeline()">运行完整三阶段</button><button class="ghost" onclick="loadMusicProjects()">刷新工程</button></div>
              </div>
              <div class="natural-box" id="musicProjectState">创建工程后，可以逐阶段生成并试听。</div>
              <div id="musicSectionList" class="music-section-list"><div class="note">完成人声分离后显示自动乐理分段。</div></div>
              <div class="music-revision-bar"><label>历史版本<select id="musicRevisionSelect"><option value="">暂无版本</option></select></label><button class="ghost" onclick="rollbackMusicProject()">恢复选中版本</button><button class="ghost" onclick="recoverMusicProject()">恢复最近自动备份</button></div>
            </div>

            <div class="music-stage-grid">
              <div id="musicStageSeparation" class="music-stage-card">
                <div class="music-stage-head">
                  <h3><span class="music-stage-index">1</span>人声分离</h3>
                  <span id="musicSeparationState" class="music-stage-state">等待</span>
                </div>
                <div class="music-stage-layout">
                  <div>
                    <p class="note">自动乐理分析后，将结构边界吸附到换气/低能量点，输出主唱、和声与立体声伴奏。</p>
                    <div class="grid">
                      <label>分离模型<select id="musicSeparationModel"><option value="mdx_net">MDX-Net（低资源）</option><option value="bs_roformer">BS-Roformer（高质量）</option><option value="demucs">Demucs v4（不同架构）</option></select><span class="param-help">本机推荐先用 MDX；BS-Roformer 权重已就绪；Demucs 首次选择会获取模型权重。</span></label>
                      <label>质量预设<select id="musicSeparationPreset"><option value="quick">快速</option><option value="standard" selected>标准（推荐）</option><option value="extreme">极致</option></select><span class="param-help">极致会提高重叠和 shifts，只建议最终成片使用。</span></label>
                      <label><span>和声处理</span><span class="row"><input id="musicSeparateHarmony" type="checkbox" checked> 分离主唱与和声</span><span class="param-help">快速模式会安全输出空和声轨，避免额外模型负载。</span></label>
                    </div>
                    <div class="music-stage-actions"><button id="musicRunSeparation" onclick="runMusicStage('separation')">开始人声分离</button><button class="ghost" onclick="confirmMusicStage('separation')">确认并继续</button><button class="ghost" onclick="resetMusicStage('separation')">重置本阶段</button></div>
                  </div>
                  <div>
                    <div class="music-track"><strong>主唱（单声道）</strong><canvas id="musicVocalWave" width="900" height="96" class="music-waveform"></canvas><button class="ghost music-preview-button" onclick="loadMusicPreview('musicVocalAudio','musicVocalWave','vocal')">按需加载试听与波形</button><audio id="musicVocalAudio" controls preload="none"></audio></div>
                    <div class="music-track"><strong>和声</strong><canvas id="musicHarmonyWave" width="900" height="96" class="music-waveform"></canvas><button class="ghost music-preview-button" onclick="loadMusicPreview('musicHarmonyAudio','musicHarmonyWave','harmony')">按需加载试听与波形</button><audio id="musicHarmonyAudio" controls preload="none"></audio></div>
                    <div class="music-track"><strong>伴奏（保持立体声）</strong><canvas id="musicInstrumentalWave" width="900" height="96" class="music-waveform"></canvas><button class="ghost music-preview-button" onclick="loadMusicPreview('musicInstrumentalAudio','musicInstrumentalWave','instrumental')">按需加载试听与波形</button><audio id="musicInstrumentalAudio" controls preload="none"></audio></div>
                  </div>
                </div>
              </div>

              <div id="musicStageInference" class="music-stage-card">
                <div class="music-stage-head">
                  <h3><span class="music-stage-index">2</span>模型推理</h3>
                  <span id="musicInferenceState" class="music-stage-state">等待</span>
                </div>
                <p class="note">Seed-VC 44.1k 歌声模型使用 RMVPE 提取 F0；每组保留 2–4 秒上下文并以 equal-power overlap-add 拼接。</p>
                <div class="music-control-grid">
                  <label>移调（半音）<input id="musicPitchShift" type="number" min="-12" max="12" step="0.5" value="0"><span class="param-help">推荐值：0。每 ±12 为一个八度；音区不合适时先在 -2～+2 内试听。</span></label>
                  <label>推理步数<input id="musicDiffusionSteps" type="number" min="10" max="50" value="35"><span class="param-help">参考：20 快速预览，35 推荐，45–50 更细致但更慢、占用更高。</span></label>
                  <label>演唱质感<select id="musicStyle"><option value="natural">自然（推荐）</option><option value="gentle">温柔</option><option value="bright">明亮</option><option value="soft">轻柔</option></select><span class="param-help">调整 Seed-VC 引导强度：自然 0.70、温柔 0.62、明亮 0.82、轻柔 0.56。</span></label>
                  <label>上下文（秒）<input id="musicContextSeconds" type="number" min="2" max="4" step="0.5" value="3"><span class="param-help">推荐 3 秒；越长越平滑但推理更慢。</span></label>
                </div>
                <div class="music-stage-actions"><button id="musicRunInference" onclick="runMusicStage('inference')">开始整曲模型推理</button><button class="ghost" onclick="confirmMusicStage('inference')">确认并继续</button><button class="ghost" onclick="resetMusicStage('inference')">重置本阶段</button></div>
                <div class="music-track"><strong>亚托莉转换人声（拖动波形选择局部）</strong><canvas id="musicConvertedWave" width="1200" height="110" class="music-waveform selectable"></canvas><button class="ghost music-preview-button" onclick="loadMusicPreview('musicConvertedAudio','musicConvertedWave','converted',true)">按需加载可编辑波形与试听</button><audio id="musicConvertedAudio" controls preload="none"></audio></div>
                <div id="musicInferenceQuality" class="music-quality"><div class="note">整曲推理后显示接缝、静音、音高与削波检查。</div></div>
                <div class="music-editor">
                  <strong>局部片段精修</strong><span class="param-help">可拖动上方波形，或直接输入时间；只替换选区，选区外采样保持不变。</span>
                  <div class="music-range-grid">
                    <label>开始（秒或 MM:SS）<input id="musicSelectionStart" type="text" inputmode="decimal" placeholder="0 或 2:58" value="0"></label>
                    <label>结束（秒或 MM:SS）<input id="musicSelectionEnd" type="text" inputmode="decimal" placeholder="15 或 3:01" value="15"></label>
                    <label>情感强度<input id="musicEmotionStrength" type="range" min="0" max="1" step="0.01" value="0.55"><span class="param-help">参考 0.45–0.65。</span></label>
                    <label>气声比例<input id="musicBreathiness" type="range" min="0" max="1" step="0.01" value="0.08"><span class="param-help">参考 0.05–0.15，默认极少原声高频残差。</span></label>
                    <label>颤音<input id="musicVibrato" type="range" min="0" max="1" step="0.01" value="0.15"><span class="param-help">参考 0.10–0.25。</span></label>
                    <label>咬字<input id="musicArticulation" type="range" min="0" max="1" step="0.01" value="0.60"><span class="param-help">日语 0.55–0.65；英语 0.60–0.72。</span></label>
                    <label>共振峰<input id="musicFormantShift" type="number" min="-4" max="4" step="0.1" value="0.6"><span class="param-help">ATRI 参考 +0.3～+1.2，轻微年轻化。</span></label>
                    <label>片段音调（半音）<input id="musicSegmentPitch" type="number" min="-12" max="12" step="0.5" value="0"></label>
                  </div>
                  <div class="music-stage-actions"><button id="musicRerunSegment" onclick="rerunMusicSegment()">只重生成选中片段</button><button class="ghost" onclick="previewSelectedMusicRange()">试听选区</button></div>
                </div>
              </div>

              <div id="musicStageMix" class="music-stage-card">
                <div class="music-stage-head">
                  <h3><span class="music-stage-index">3</span>后期混音</h3>
                  <span id="musicMixState" class="music-stage-state">等待</span>
                </div>
                <p class="note">Pedalboard：高通 → 动态 EQ → 齿音抑制 → 压缩 → 饱和 → Reverb/Delay → Limiter；人声单声道，伴奏保持立体声。</p>
                <div class="music-control-grid">
                  <label>人声增益 dB<input id="musicVocalGain" type="number" min="-12" max="12" step="0.5" value="0"><span class="param-help">推荐值：0 dB。人声靠后可加 +1～+3 dB，刺耳或过近可减 -1～-3 dB。</span></label>
                  <label>伴奏增益 dB<input id="musicInstrumentalGain" type="number" min="-18" max="6" step="0.5" value="-1.7"><span class="param-help">推荐 -1.7 dB；人声被盖住可降至 -3～-5 dB。</span></label>
                  <label>Ducking dB<input id="musicDucking" type="number" min="0" max="12" step="0.5" value="3"><span class="param-help">推荐 2–4 dB，按人声包络自动闪避伴奏。</span></label>
                  <label>存在感 EQ dB<input id="musicEqPresence" type="number" min="-9" max="6" step="0.5" value="-1"><span class="param-help">2.5–5.2 kHz 动态处理；机械刺耳时降低。</span></label>
                  <label>空气感 EQ dB<input id="musicEqAir" type="number" min="-6" max="9" step="0.5" value="1.2"><span class="param-help">9 kHz 高架；ATRI 建议 +0.5～+2 dB。</span></label>
                  <label>压缩阈值 dB<input id="musicCompressorThreshold" type="number" min="-40" max="-6" step="1" value="-18"></label>
                  <label>压缩比<input id="musicCompressorRatio" type="number" min="1" max="10" step="0.1" value="2.5"><span class="param-help">推荐 2:1～3:1。</span></label>
                  <label>齿音抑制<input id="musicDeesser" type="range" min="0" max="1" step="0.01" value="0.35"><span class="param-help">推荐 0.25–0.45。</span></label>
                  <label>饱和 drive dB<input id="musicSaturation" type="number" min="0" max="9" step="0.5" value="1"><span class="param-help">推荐 0.5–1.5 dB。</span></label>
                  <label>混响<input id="musicReverb" type="range" min="0" max="0.45" step="0.01" value="0.08"><span class="param-help">推荐值：0.08。自然空间感通常 0.05–0.12；0 为完全干声。</span></label>
                  <label>延迟 ms<input id="musicDelayMs" type="number" min="0" max="500" step="5" value="90"></label>
                  <label>延迟比例<input id="musicDelayMix" type="range" min="0" max="0.35" step="0.01" value="0.04"><span class="param-help">推荐 0.02–0.08。</span></label>
                </div>
                <div class="music-stage-actions"><button id="musicRunMix" onclick="runMusicStage('mix')">生成工程内混音</button><button class="ghost" onclick="confirmMusicStage('mix')">确认混音</button><button class="ghost" onclick="resetMusicStage('mix')">重置本阶段</button></div>
                <div class="music-track"><strong>最终混音</strong><canvas id="musicMixWave" width="1200" height="96" class="music-waveform"></canvas><button class="ghost music-preview-button" onclick="loadMusicPreview('musicMixAudio','musicMixWave','mix')">按需加载试听与波形</button><audio id="musicMixAudio" controls preload="none"></audio></div>
                <div class="music-editor">
                  <strong>导出成品</strong>
                  <div class="music-control-grid">
                    <label>导出预设<select id="musicExportPreset"><option value="preview">试听</option><option value="live" selected>直播</option><option value="conservative_master">保守母带</option><option value="custom">自定义</option></select></label>
                    <label>格式<select id="musicExportFormat"><option value="wav">WAV 24-bit</option><option value="flac">FLAC</option><option value="mp3">MP3</option></select></label>
                    <label>目标响度 LUFS<input id="musicExportLufs" type="number" min="-24" max="-8" step="0.5" value="-14"><span class="param-help">直播 -14；试听 -16；保守母带 -13。</span></label>
                  </div>
                  <div class="music-stage-actions"><button id="musicExportButton" onclick="exportMusicProject()">导出到 AI合成音乐</button></div>
                </div>
              </div>
            </div>
            <div class="surface">
              <div class="section-head"><div><h2>合成终端 · 简洁进度</h2><p class="note">这里只显示阶段、百分比与可读字幕；模型原始调试日志写入歌曲工程 logs/*.debug.log，不刷屏、不影响桌面。</p></div></div>
              <pre id="musicTerminal" class="music-terminal">选择歌曲工程后显示阶段字幕。</pre>
            </div>
          </div>
        </div>
      </div>

      <div id="stickers" class="panel">
        <h2>表情包管理</h2>
        <div class="grid">
          <label>新建情绪分类<input id="newCategory" placeholder="例如 happy / comfort / tsundere / 摸摸头"></label>
          <label>上传到分类<select id="uploadCategory"></select></label>
        </div>
        <div class="row">
          <button onclick="createCategory()">新建分类</button>
          <input id="stickerFile" type="file" accept=".jpg,.jpeg,.png,.gif,.webp,image/*">
          <button onclick="uploadSticker()">上传表情包</button>
        </div>
        <p class="note" id="stickerInfo"></p>
        <div class="split">
          <div class="scroll"><table><thead><tr><th>分类</th><th>数量</th><th>位置</th></tr></thead><tbody id="stickerRows"></tbody></table></div>
          <div>
            <h3 id="stickerFolderTitle">预览</h3>
            <div class="thumbs" id="stickerPreview"></div>
          </div>
        </div>
      </div>

      <div id="memory" class="panel">
        <h2>记忆管理</h2>
        <div class="toolbar">
          <label>搜索用户 / QQ / 群 / 关键词<input id="memorySearch" oninput="renderMemoryRows()" placeholder="输入昵称、QQ号、群号或记忆关键词"></label>
          <label>类型筛选<select id="memoryTypeFilter" onchange="renderMemoryRows()">
            <option value="all">全部</option>
            <option value="person">人物档案</option>
            <option value="private">私聊</option>
            <option value="group">群聊</option>
            <option value="member">群内用户</option>
            <option value="important">有重要记忆</option>
          </select></label>
          <label>排序<select id="memorySort" onchange="renderMemoryRows()">
            <option value="recent">最近互动</option>
            <option value="messages">消息数量</option>
            <option value="memories">记忆数量</option>
            <option value="affection">亲密状态</option>
          </select></label>
          <label class="switch-line"><input id="memoryImportantOnly" type="checkbox" onchange="renderMemoryRows()">只看重要</label>
          <label class="switch-line"><input id="memoryRecentOnly" type="checkbox" onchange="renderMemoryRows()">最近 7 天</label>
        </div>
        <div class="row">
          <button class="ghost" onclick="loadMemory()">刷新记忆</button>
          <button class="warn" onclick="backupMemory()">手动备份</button>
        </div>
        <p class="note" id="memoryInfo"></p>
        <div class="scroll">
          <table>
            <thead><tr><th>对象</th><th>核心记忆</th><th>状态</th><th>操作</th></tr></thead>
            <tbody id="memoryRows"></tbody>
          </table>
        </div>
      </div>

      <div id="test" class="panel">
        <div class="stack">
          <div class="surface">
            <h2>聊天回复测试</h2>
            <textarea id="testText" placeholder="例如：我今天好累，亚托莉你会怎么回？"></textarea>
            <div class="row"><button onclick="testChat()">生成回复</button></div>
            <div class="out" id="testOut"></div>
          </div>
          <div class="surface">
            <div class="section-head">
              <div><h2>语音识别测试</h2><p class="note" id="testVoiceState">读取语音服务状态...</p></div>
              <div class="row"><button class="ghost" onclick="loadVoiceTestState()">刷新状态</button></div>
            </div>
            <div class="row">
              <label>识别语言<select id="testAsrLanguage"><option value="auto">自动检测</option><option value="zh">中文</option><option value="en">English</option><option value="ja">日本語</option></select></label>
              <input id="testAsrFile" type="file" accept=".wav,.flac,.mp3,.ogg,.m4a,.aac,audio/*" onchange="window._recordedAsrFile=null">
              <button onclick="testVoiceRecognition()">识别文件</button>
              <button id="testAsrRecordButton" class="ghost" onclick="startAsrRecording()">开始说话</button>
              <button id="testAsrStopButton" class="ghost" onclick="stopAsrRecording()" disabled>停止并识别</button>
            </div>
            <div class="natural-box" id="testAsrOut">等待选择音频。</div>
          </div>
          <div class="surface">
            <h2>语音合成测试</h2>
            <div class="grid">
              <label>测试文本<input id="testTtsText" value="主人，今天也请让我陪在你身边。"></label>
              <label>语言<select id="testTtsLanguage" onchange="useVoiceLanguageSample()"><option value="zh">中文</option><option value="en">English</option><option value="ja">日本語</option></select></label>
              <label>情绪<select id="testTtsEmotion"><option value="gentle">温柔</option><option value="neutral">自然</option><option value="happy">开心</option><option value="shy">害羞</option><option value="sad">难过</option><option value="sleepy">困倦</option><option value="serious">认真</option><option value="surprised">惊讶</option></select></label>
              <label>情绪强度<input id="testTtsIntensity" type="range" min="0" max="1" step="0.05" value="0.55"></label>
            </div>
            <div class="row"><button id="testTtsCompareButton" onclick="testVoiceComparison()">生成 A/B 试听</button></div>
            <p class="note" id="testTtsOut">同一文本会依次合成，避免两套模型同时占用显存。</p>
            <div class="voice-compare">
              <div class="voice-result">
                <h3>候选 A</h3>
                <label>语音档案<select id="testTtsProfileA"></select></label>
                <p class="note" id="testTtsOutA">等待生成。</p>
                <audio id="testTtsAudioA" controls></audio>
              </div>
              <div class="voice-result">
                <h3>候选 B</h3>
                <label>语音档案<select id="testTtsProfileB"></select></label>
                <p class="note" id="testTtsOutB">等待生成。</p>
                <audio id="testTtsAudioB" controls></audio>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div id="developer" class="panel">
        <div class="stack">
          <div class="surface">
            <div class="section-head">
              <div><h2>开发者状态与访问入口</h2><p class="note">NapCat Token 仅展示在本机页面；请勿把该链接截图或分享给他人。</p></div>
              <div class="row"><button class="ghost" onclick="loadDeveloper(true)">刷新状态</button></div>
            </div>
            <div id="developerLinks" class="developer-links"><span class="note">正在读取本机服务信息...</span></div>
          </div>
          <div class="surface">
            <div class="section-head">
              <div><h2>实时项目日志</h2><p class="note" id="developerLogHint">每 3 秒读取一次当天日志；聊天正文和 Token 不会写入统一日志。</p></div>
              <div class="row">
                <label>级别<select id="developerLogLevel" onchange="loadDeveloperLogs()"><option value="all">全部</option><option value="debug">Debug</option><option value="info">Info</option><option value="warning">Warn</option><option value="error">Error</option></select></label>
                <button class="ghost" onclick="loadDeveloperLogs()">刷新日志</button>
              </div>
            </div>
            <pre id="developerLog" class="log-view">日志加载中...</pre>
          </div>
        </div>
      </div>

      <div id="minecraft" class="panel">
        <div class="section-head">
          <div>
            <h2>Minecraft 女仆桥接测试</h2>
            <p class="note">独立测试区：后台通过本机桥接服务控制 UMU Little Maid，不会登录第二个账号，也不会向服务器发送任意命令。</p>
          </div>
          <div class="row">
            <button class="ghost" onclick="loadMinecraft()">刷新状态</button>
          </div>
        </div>
        <div class="minecraft-grid">
          <div class="stack">
            <div class="surface">
              <h2>连接配置</h2>
              <label class="switch-line"><input id="minecraftEnabled" type="checkbox">允许亚托莉控制自己的女仆</label>
              <label>本地桥接地址<input id="minecraftBridgeUrl" value="http://127.0.0.1:8792"></label>
              <div class="row">
                <button onclick="saveMinecraftConfig()">保存配置</button>
                <button class="ghost" onclick="loadMinecraft()">放弃修改</button>
              </div>
              <p class="note">只允许 127.0.0.1 或 localhost。先运行 AI_game 中的 <span class="mono">scripts\\start_bridge.ps1</span>，再启动测试 Minecraft。</p>
            </div>
            <div class="surface">
              <h2>安全边界</h2>
              <div class="stack note">
                <div>• 只识别当前玩家拥有的 UMU 女仆。</div>
                <div>• 切换模式时女仆需在 4.5 格内，且玩家主手为空。</div>
                <div>• 只允许跟随、待命、自由、停止和状态刷新。</div>
                <div>• 守卫、治疗、农夫等职业仍由女仆装备决定。</div>
              </div>
            </div>
          </div>
          <div class="stack">
            <div class="surface">
              <div class="section-head">
                <div>
                  <h2>实时状态</h2>
                  <p class="note" id="minecraftStatusText">尚未连接桥接服务。</p>
                </div>
              </div>
              <div id="minecraftStatusCards" class="minecraft-status"></div>
              <label>控制对象<select id="minecraftMaidSelect" onchange="renderMinecraftMaidSelection()"></select></label>
              <div class="minecraft-command-grid">
                <button onclick="sendMinecraftCommand('follow')">跟随</button>
                <button class="secondary" onclick="sendMinecraftCommand('wait')">待命</button>
                <button class="ghost" onclick="sendMinecraftCommand('free')">自由活动</button>
                <button class="danger" onclick="sendMinecraftCommand('stop')">停止</button>
              </div>
              <div id="minecraftMaidList" class="minecraft-maids"><div class="note">等待女仆遥测。</div></div>
            </div>
            <div class="surface">
              <h2>最近执行结果</h2>
              <div class="out" id="minecraftCommandOut">尚未执行测试命令。</div>
            </div>
          </div>
        </div>
      </div>

      <div id="advanced" class="panel">
        <div class="section-head">
          <div>
            <h2>高级配置</h2>
            <p class="note">集中管理消息发送方式和主动互动策略。模型、接口和视觉能力统一在“模型”页面配置。</p>
          </div>
        </div>
        <div class="settings-section accordion-section">
          <h3>回复与发送</h3>
          <div class="grid" id="configForm"></div>
          <p class="note">语音概率仅影响普通消息；用户明显难受或疲惫时会提高到至少 70%。明确要求语音和回应用户语音不受该概率限制。</p>
          <div class="row">
            <button onclick="saveConfig()">保存回复配置</button>
            <button class="ghost" onclick="loadConfig()">放弃页面修改</button>
          </div>
        </div>
        <div class="settings-section accordion-section">
          <div class="section-head">
            <div>
              <h3>主动互动</h3>
              <p class="note">按亲密度和活跃度随机安排；用户与群聊的具体计划统一在“记忆”页面查看。</p>
            </div>
            <div class="row"><button class="ghost" onclick="loadProactive()">刷新状态</button></div>
          </div>
          <div class="proactive-layout">
            <div class="stack">
              <div class="proactive-block">
                <h3>运行规则</h3>
                <p class="note" id="proactiveFeatureState">读取中...</p>
                <div class="grid">
                  <label class="switch-line"><input id="proactiveEngineEnabled" type="checkbox">启用新版主动调度器</label>
                  <label class="switch-line"><input id="proactiveEnabled" type="checkbox">允许发送主动消息</label>
                  <label class="switch-line"><input id="proactiveOwnerOnly" type="checkbox">私聊仅限主人</label>
                  <label class="switch-line"><input id="proactiveUseAi" type="checkbox">优先由聊天模型生成</label>
                  <label class="switch-line"><input id="proactiveGuidedTopics" type="checkbox">话题使用引导式开场</label>
                  <label>时区<input id="proactiveTimezone" value="Asia/Shanghai"></label>
                  <label>免打扰开始<input id="proactiveQuietStart" type="time"></label>
                  <label>免打扰结束<input id="proactiveQuietEnd" type="time"></label>
                  <label>检查间隔（秒）<input id="proactiveCheckSeconds" type="number" min="15" max="3600"></label>
                  <label>连续未回复倍率<input id="proactiveBackoff" type="number" min="1" max="3" step="0.1"></label>
                  <label>参考最近消息数<input id="proactiveHistoryLimit" type="number" min="0" max="20"></label>
                  <label>主动消息最大字数<input id="proactiveMaxChars" type="number" min="20" max="240"></label>
                </div>
              </div>
              <div class="proactive-block">
                <h3>受众门槛</h3>
                <p class="note">主人不受私聊门槛限制；其他用户必须同时满足好感、近期活跃和消息量条件。群聊只读取群内公开上下文。</p>
                <div class="grid">
                  <label>其他用户最低好感<input id="proactivePrivateMinAffection" type="number" min="0" max="100" step="1"></label>
                  <label>私聊活跃期（天）<input id="proactivePrivateActiveDays" type="number" min="1" max="365"></label>
                  <label>私聊最低消息量<input id="proactivePrivateMinMessages" type="number" min="1" max="10000"></label>
                  <label class="switch-line"><input id="proactiveGroupEnabled" type="checkbox">启用活跃群聊</label>
                  <label>群最低活跃度<input id="proactiveGroupMinActivity" type="number" min="0" max="100" step="1"></label>
                  <label>群活跃期（天）<input id="proactiveGroupActiveDays" type="number" min="1" max="90"></label>
                  <label>群最低消息量<input id="proactiveGroupMinMessages" type="number" min="1" max="100000"></label>
                  <label>群随机间隔下限（小时）<input id="proactiveGroupMinHours" type="number" min="0.25" max="168" step="0.25"></label>
                  <label>群随机间隔上限（小时）<input id="proactiveGroupMaxHours" type="number" min="0.25" max="336" step="0.25"></label>
                  <label>单群每日上限<input id="proactiveGroupDailyLimit" type="number" min="0" max="12"></label>
                </div>
              </div>
              <div class="proactive-block">
                <h3>亲密度与频率</h3>
                <div class="scroll"><table>
                  <thead><tr><th>阶段</th><th>启用</th><th>好感范围</th><th>随机间隔（小时）</th><th>每日上限</th></tr></thead>
                  <tbody id="proactiveTierRows"></tbody>
                </table></div>
              </div>
              <div class="proactive-block">
                <h3>私聊内容权重</h3>
                <div class="weight-grid" id="proactiveWeights"></div>
                <p class="note">早安和晚安只在对应时段参与抽取；权重为 0 表示禁用该类型。</p>
              </div>
              <div class="proactive-block">
                <h3>群聊内容权重</h3>
                <div class="weight-grid" id="proactiveGroupWeights"></div>
              </div>
              <div class="row">
                <button onclick="saveProactive()">保存主动互动配置</button>
                <button class="ghost" onclick="loadProactive()">放弃页面修改</button>
              </div>
            </div>
            <div class="stack">
              <div class="proactive-block">
                <h3>文案预览</h3>
                <div class="grid">
                  <label>预览场景<select id="proactivePreviewScope" onchange="renderProactivePreviewTypes()"><option value="private">私聊</option><option value="group">群聊</option></select></label>
                  <label>内容类型<select id="proactivePreviewType"></select></label>
                  <label>QQ / 群号（可留空）<input id="proactivePreviewUser" inputmode="numeric" placeholder="默认使用首个入选目标"></label>
                </div>
                <div class="row"><button onclick="previewProactive()">生成预览</button></div>
                <div class="out" id="proactivePreviewOut">预览不会发送 QQ 消息。</div>
              </div>
              <div class="proactive-block">
                <h3>计划说明</h3>
                <p class="note">每个用户和群聊只保留一份计划。修改门槛或频率后，记忆页会显示最新的入选结果、下次时间、内容类型和未入选原因。</p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  </main>

  <div id="memoryModal" class="modal" onclick="modalBackdrop(event)">
    <div class="dialog">
      <div class="dialog-head">
        <div>
          <div class="dialog-title" id="memoryModalTitle">记忆详情</div>
          <div class="note" id="memoryModalMeta"></div>
        </div>
        <button class="secondary" onclick="closeMemoryModal()">关闭</button>
      </div>
      <div class="mini-tabs">
        <button class="mini-tab active" onclick="showMemoryPane(event,'memoryOverview')">概览</button>
        <button class="mini-tab" onclick="showMemoryPane(event,'memoryProfile')">L1 用户特点</button>
        <button class="mini-tab" onclick="showMemoryPane(event,'memoryEvents')">L2 事件</button>
        <button class="mini-tab" onclick="showMemoryPane(event,'memoryHistory')">L3 最近聊天</button>
        <button class="mini-tab" onclick="showMemoryPane(event,'memoryRaw')">高级 JSON</button>
      </div>
      <div class="dialog-body">
        <div id="memoryOverview" class="memory-pane"></div>
        <div id="memoryProfile" class="memory-pane" style="display:none"></div>
        <div id="memoryEvents" class="memory-pane" style="display:none"></div>
        <div id="memoryHistory" class="memory-pane" style="display:none"></div>
        <div id="memoryRaw" class="memory-pane" style="display:none"></div>
      </div>
      <div class="dialog-foot">
        <span id="memorySaveState" class="saved">未修改</span>
        <div class="row" style="margin:0">
          <button class="ghost" onclick="addMemoryEntryFromActivePane()">新增当前分类</button>
          <button id="memorySaveButton" onclick="saveSelectedMemory()">保存修改</button>
          <button class="danger" onclick="deleteSelectedMemory()">删除此会话记忆</button>
        </div>
      </div>
    </div>
  </div>
  <div id="toast" class="toast"></div>

<script>
const fields = [
  ["REPLY_MODE","回复模式","select"],
  ["MESSAGE_SPLIT_MAX_CHARS","单条字数","number"],
  ["MESSAGE_SPLIT_MAX_PARTS","最多分条","number"],
  ["MESSAGE_SEND_DELAY_MIN","最短发送间隔","number"],
  ["MESSAGE_SEND_DELAY_MAX","最长发送间隔","number"],
  ["STICKER_CHANCE","表情概率","number"],
  ["STICKER_COOLDOWN_SECONDS","表情冷却秒数","number"],
  ["TOOLBOX_OCR_ENABLED","独立 OCR 文字识别","checkbox"],
  ["TOOLBOX_VISION_FALLBACK_MODEL","视觉资源不足兜底模型","text"],
  ["TOOLBOX_VISION_RETRY_COUNT","视觉资源错误重试次数","number"],
  ["TOOLBOX_VISION_RESOURCE_WAIT_SECONDS","视觉等待 GPU 秒数","number"],
  ["TOOLBOX_VISION_UNLOAD_OTHER_OLLAMA_MODELS","视觉前释放其它 Ollama 模型","checkbox"],
  ["REPLY_VOICE_PROBABILITY","语音概率（%）","voice-probability"]
];
const categoryLabels = {
  interest:"兴趣爱好", preference:"偏好/忌口", profile_fact:"用户资料", habit:"生活习惯", communication_style:"聊天习惯",
  schedule:"日程提醒", event:"事件经历", important_interaction:"重要互动"
};
let selectedProfileId = "";
let currentMemoryId = "";
let selectedMemory = null;
let selectedMemoryContent = null;
let memoryDirty = false;
let activeMemoryPane = "memoryOverview";
window._profiles = [];
window._memoryItems = [];
window._localModels = [];
window._selectedLocalModelName = "";
window._activeProfileIds = {};
window._profileTypes = [];
window._proactive = null;
window._minecraftData = null;
function $(id) { return document.getElementById(id); }
function toast(text) {
  const el = $('toast'); el.textContent = text; el.classList.add('show');
  setTimeout(()=>el.classList.remove('show'), 2600);
}
async function api(path, opts={}) {
  const headers = opts.body instanceof FormData ? {} : {'Content-Type':'application/json'};
  const res = await fetch(path, {headers, ...opts});
  const data = await res.json();
  if(!res.ok || data.ok === false) throw new Error(data.error || res.statusText);
  return data;
}
function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, s => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[s]));
}
function showTab(event, id) {
  document.querySelectorAll('.tab').forEach(b=>b.classList.remove('active'));
  document.querySelectorAll('.panel').forEach(p=>p.classList.remove('active'));
  (event.currentTarget || event.target).classList.add('active'); $(id).classList.add('active');
  if(id==='stickers') loadStickers();
  if(id==='memory') loadMemory();
  if(id==='advanced') { loadConfig(); loadReplyVoiceProbability(); loadProactive(); }
  if(id==='model') loadProfiles();
  if(id==='voice') loadVoice();
  if(id==='test') loadVoiceTestState();
  if(id==='developer') loadDeveloper(true);
  if(id==='minecraft') loadMinecraft();
}
function showVoiceModule(module) {
  const speech = module !== 'music';
  $('voiceSpeechTab').classList.toggle('active', speech);
  $('voiceMusicTab').classList.toggle('active', !speech);
  $('voiceSpeechPanel').classList.toggle('active', speech);
  $('voiceMusicPanel').classList.toggle('active', !speech);
  $('voiceSpeechTab').setAttribute('aria-selected', String(speech));
  $('voiceMusicTab').setAttribute('aria-selected', String(!speech));
  window._voiceMusicActive = !speech;
  if(speech) {
    clearTimeout(window._musicProjectTimer);
    releaseMusicMedia();
  } else if(!window._musicProjectsLoaded) {
    loadMusicSources();
    loadMusicProjects();
  }
}

function minecraftMaidTelemetry() {
  const state = window._minecraftData?.bridge?.state || {};
  const telemetry = state.telemetry || {};
  return Array.isArray(telemetry.maids) ? telemetry.maids : [];
}
function renderMinecraftMaidSelection() {
  const maids = minecraftMaidTelemetry();
  const selected = $('minecraftMaidSelect')?.value || '';
  const out = $('minecraftMaidList');
  if(!out) return;
  if(!maids.length) {
    out.innerHTML = '<div class="note">当前没有收到属于玩家的 UMU 女仆。1.21.11 冒烟测试只验证连接，不会显示女仆。</div>';
    return;
  }
  out.innerHTML = maids.map(maid=>{
    const active = maid.uuid===selected;
    const health = Number(maid.health ?? 0);
    const maxHealth = Number(maid.maxHealth ?? 0);
    return `<div class="minecraft-maid ${active?'selected':''}">
      <div class="minecraft-maid-head">
        <div><strong>${escapeHtml(maid.name || 'UMU 女仆')}</strong><div class="memory-meta mono">${escapeHtml(maid.uuid || '')}</div></div>
        <span class="badge ${String(maid.mode || '').toUpperCase()==='FOLLOW'?'active':''}">${escapeHtml(maid.mode || 'UNKNOWN')}</span>
      </div>
      <div class="minecraft-maid-meta">
        <div><span>职业</span><strong>${escapeHtml(maid.job || 'UNKNOWN')}</strong></div>
        <div><span>生命</span><strong>${health.toFixed(1)} / ${maxHealth.toFixed(1)}</strong></div>
        <div><span>距离</span><strong>${Number(maid.distance || 0).toFixed(1)} 格</strong></div>
        <div><span>坐标</span><strong>${Number(maid.x || 0).toFixed(0)}, ${Number(maid.y || 0).toFixed(0)}, ${Number(maid.z || 0).toFixed(0)}</strong></div>
      </div>
      ${active ? '<div class="ok">当前控制对象</div>' : `<button class="ghost" onclick="selectMinecraftMaid('${escapeHtml(maid.uuid || '')}')">选择</button>`}
    </div>`;
  }).join('');
}
function selectMinecraftMaid(uuid) {
  $('minecraftMaidSelect').value = uuid;
  renderMinecraftMaidSelection();
}
function renderMinecraft(data) {
  window._minecraftData = data;
  const config = data.config || {};
  const bridge = data.bridge || {};
  const health = bridge.health || {};
  const state = bridge.state || {};
  const telemetry = state.telemetry || {};
  const maids = minecraftMaidTelemetry();
  $('minecraftEnabled').checked = !!config.enabled;
  $('minecraftBridgeUrl').value = config.bridge_url || 'http://127.0.0.1:8792';
  const connected = !!(health.minecraftConnected || state.minecraftConnected);
  $('minecraftStatusText').textContent = !bridge.reachable
    ? `桥接服务不可达：${bridge.error || '请先启动本地桥接'}`
    : (connected ? 'Minecraft 已连接，遥测正常。' : '桥接服务已启动，等待 Minecraft 客户端连接。');
  $('minecraftStatusCards').innerHTML = [
    ['控制开关', !!config.enabled, config.enabled ? '已允许' : '已禁用'],
    ['本地桥接', !!bridge.reachable, bridge.reachable ? '在线' : '离线'],
    ['Minecraft', connected, connected ? '已连接' : '未连接']
  ].map(([name,ok,text])=>`<div class="stat"><span class="${ok?'ok':'bad'}">${escapeHtml(text)}</span><div class="memory-meta">${escapeHtml(name)}</div></div>`).join('');
  const select = $('minecraftMaidSelect');
  const previous = select.value;
  select.innerHTML = maids.map(maid=>`<option value="${escapeHtml(maid.uuid)}">${escapeHtml(maid.name || 'UMU 女仆')} · ${escapeHtml(maid.mode || 'UNKNOWN')} · ${Number(maid.distance || 0).toFixed(1)}格</option>`).join('');
  if(maids.some(maid=>maid.uuid===previous)) select.value = previous;
  if(!select.options.length) select.innerHTML = '<option value="">没有可控制的女仆</option>';
  renderMinecraftMaidSelection();
  const lastResult = state.lastResult || {};
  if(lastResult.requestId) {
    $('minecraftCommandOut').textContent = `${lastResult.ok ? '执行成功' : '执行失败'}\n${lastResult.detail || ''}\n请求：${lastResult.requestId}`;
  } else if(telemetry.smokeTest) {
    $('minecraftCommandOut').textContent = `1.21.11 冒烟连接成功\nMinecraft ${telemetry.minecraftVersion || ''}\n下一步可以进入 UMU 3.11a 隔离副本测试。`;
  }
  clearTimeout(window._minecraftRefreshTimer);
  if($('minecraft').classList.contains('active')) {
    window._minecraftRefreshTimer = setTimeout(loadMinecraft, connected ? 1800 : 3500);
  }
}
async function loadMinecraft() {
  try {
    renderMinecraft(await api('/api/minecraft'));
  } catch(error) {
    $('minecraftStatusText').textContent = '后台读取失败：' + error.message;
  }
}
async function saveMinecraftConfig() {
  try {
    await api('/api/minecraft/config', {method:'POST', body:JSON.stringify({
      enabled:$('minecraftEnabled').checked,
      bridge_url:$('minecraftBridgeUrl').value.trim()
    })});
    toast('Minecraft 桥接配置已保存');
    await loadMinecraft();
  } catch(error) {
    toast('保存失败：' + error.message);
  }
}
async function sendMinecraftCommand(command) {
  const maidUuid = $('minecraftMaidSelect').value || null;
  const out = $('minecraftCommandOut');
  out.textContent = `正在发送 ${command}...`;
  try {
    const result = await api('/api/minecraft/command', {method:'POST', body:JSON.stringify({
      command,
      maidUuid
    })});
    out.textContent = `命令已接收\n请求：${result.result?.requestId || '状态刷新'}`;
    setTimeout(loadMinecraft, 650);
  } catch(error) {
    out.textContent = '发送失败：' + error.message;
  }
}

function voiceConfigValue(cfg, key) {
  const item = cfg[key] || {};
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
  out.innerHTML=checks.map(check=>`<div class="music-quality-item ${check.passed?'pass':'fail'}"><strong>${check.passed?'通过':'需检查'} · ${escapeHtml(check.label||check.id)}</strong><span class="param-help">${escapeHtml(check.reference||'')} · 实测 ${escapeHtml(check.value??'无有效音高')}</span></div>`).join('');
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
  $('musicBreathiness').value = params.inference?.breathiness ?? .08;
  $('musicVibrato').value = params.inference?.vibrato ?? .15;
  $('musicArticulation').value = params.inference?.articulation ?? .60;
  $('musicFormantShift').value = params.inference?.formant_shift ?? .6;
  $('musicSegmentPitch').value = params.inference?.pitch_shift ?? 0;
  $('musicVocalGain').value = params.mix?.vocal_gain_db ?? 0;
  $('musicInstrumentalGain').value = params.mix?.instrumental_gain_db ?? -1.7;
  $('musicDucking').value = params.mix?.ducking_db ?? 3;
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
    breathiness:Number($('musicBreathiness').value || .08),
    vibrato:Number($('musicVibrato').value || .15),
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
    ducking_db:Number($('musicDucking').value || 3)
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
      breathiness:Number($('musicBreathiness').value||.08),vibrato:Number($('musicVibrato').value||.15),
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
  return ({queued:'等待',running:'处理中',succeeded:'完成',failed:'失败',cancelled:'已取消'})[state] || state || '未知';
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
  const s = await api('/api/status');
  const cards = [
    ['Atri 服务', s.atri, s.atri ? '正常' : '未连接'],
    ['NapCat 连接', s.napcat, s.napcat ? '正常' : '未连接'],
    ['Ollama', s.ollama, s.ollama ? '正常' : '未连接'],
    ['语音服务', s.voice, s.voice ? '正常' : '未连接'],
    ['WebUI', s.webui, s.webui ? '正常' : '未连接'],
    ['聊天模型', Boolean(s.model), s.model || '未配置'],
    ['视觉模型', Boolean(s.vision_model), s.vision_model || '未配置']
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
    const entries = [
      ['ATRI OneBot', data.status?.onebot || '', data.status?.atri],
      ['NapCat WebUI', napcat.url || '', napcat.reachable]
    ];
    $('developerLinks').innerHTML = entries.map(([label,url,ok]) => {
      // 用字符串拼接生成链接片段，避免嵌套模板字符串导致页面脚本解析中断。
      if (!url) {
        return `<div class="pill"><span>${escapeHtml(label)}</span><span class="bad">未配置</span></div>`;
      }
      const destination = '<a href="' + escapeHtml(url) + '" target="_blank" rel="noreferrer">打开</a>';
      return `<div class="pill"><span>${escapeHtml(label)}</span><span class="${ok ? 'ok' : 'bad'}">${ok ? '就绪' : '待检查'}</span>${destination}</div>`;
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
    output.textContent = (data.lines || []).join('\\n') || '今天还没有统一项目日志。';
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
      : `当前聊天模型没有连上，正在走兜底。错误：${r.error || '未知错误'}\n兜底回复：${r.reply || ''}`;
    if(feedback) feedback.textContent = text;
    toast(r.used_ai ? '当前聊天模型测试通过' : '当前聊天模型未连上，已显示错误');
  } catch(e) {
    const text = '当前聊天模型测试失败：' + (e.message || '未知错误');
    if(feedback) feedback.textContent = text;
    toast(text);
  }
}
async function loadProfiles() {
  const data = await api('/api/model-profiles');
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
  morning:'早安', goodnight:'晚安', check_in:'关心近况', continue_topic:'继续上次话题',
  interest_topic:'兴趣话题', guided_topic:'引导式新话题', daily_share:'轻松分享', affection:'想念与亲近', encouragement:'鼓励'
};
function formatProactiveTime(value, timezone) {
  if(!value) return '尚未安排';
  try { return new Date(Number(value) * 1000).toLocaleString('zh-CN', {timeZone:timezone, hour12:false}); }
  catch (_) { return new Date(Number(value) * 1000).toLocaleString('zh-CN', {hour12:false}); }
}
async function loadProactive() {
  const [data, cfg] = await Promise.all([api('/api/proactive'), api('/api/config')]);
  window._proactive = data;
  const p = data.policy || {};
  const engineValue = cfg.PROACTIVE_V2_ENABLED?.raw || cfg.PROACTIVE_V2_ENABLED?.value || '';
  $('proactiveEngineEnabled').checked = String(engineValue).toLowerCase() === 'true';
  $('proactiveEnabled').checked = !!p.enabled;
  $('proactiveOwnerOnly').checked = !!p.owner_only;
  $('proactiveUseAi').checked = !!p.use_ai;
  $('proactiveGuidedTopics').checked = !!p.guided_topics;
  $('proactivePrivateMinAffection').value = p.private_min_affection ?? 70;
  $('proactivePrivateActiveDays').value = p.private_active_days ?? 14;
  $('proactivePrivateMinMessages').value = p.private_min_messages ?? 5;
  $('proactiveGroupEnabled').checked = !!p.group_enabled;
  $('proactiveGroupMinActivity').value = p.group_min_activity ?? 55;
  $('proactiveGroupActiveDays').value = p.group_active_days ?? 3;
  $('proactiveGroupMinMessages').value = p.group_min_messages ?? 12;
  $('proactiveGroupMinHours').value = p.group_min_hours ?? 3;
  $('proactiveGroupMaxHours').value = p.group_max_hours ?? 9;
  $('proactiveGroupDailyLimit').value = p.group_daily_limit ?? 2;
  $('proactiveTimezone').value = p.timezone || 'Asia/Shanghai';
  $('proactiveQuietStart').value = p.quiet_start || '00:30';
  $('proactiveQuietEnd').value = p.quiet_end || '07:00';
  $('proactiveCheckSeconds').value = p.check_seconds || 60;
  $('proactiveBackoff').value = p.ignored_backoff || 1.5;
  $('proactiveHistoryLimit').value = p.history_limit ?? 8;
  $('proactiveMaxChars').value = p.max_chars || 90;
  $('proactiveFeatureState').innerHTML = data.feature_enabled
    ? '<span class="ok">新版调度器已接管私聊、早安及已启用的群聊主动消息；旧版循环处于回退待命状态。</span>'
    : '<span class="bad">新版调度器未启用，当前仍由旧版私聊/早安规则运行。</span>';
  $('proactiveTierRows').innerHTML = (p.tiers || []).map((tier,index)=>`<tr data-tier-index="${index}">
    <td><strong>${escapeHtml(tier.name)}</strong><div class="memory-meta mono">${escapeHtml(tier.id)}</div></td>
    <td><input class="tier-enabled" type="checkbox" ${tier.enabled?'checked':''}></td>
    <td><div class="row" style="margin:0"><input class="tier-min compact-input" type="number" min="0" max="100" step="1" value="${tier.min_affection}"><span>至</span><input class="tier-max compact-input" type="number" min="0" max="101" step="1" value="${tier.max_affection}"></div></td>
    <td><div class="row" style="margin:0"><input class="tier-min-hours compact-input" type="number" min="0.25" max="168" step="0.25" value="${tier.min_hours}"><span>至</span><input class="tier-max-hours compact-input" type="number" min="0.25" max="336" step="0.25" value="${tier.max_hours}"></div></td>
    <td><input class="tier-limit compact-input" type="number" min="0" max="12" step="1" value="${tier.daily_limit}"></td>
  </tr>`).join('');
  $('proactiveWeights').innerHTML = Object.entries(p.content_weights || {}).map(([key,value])=>
    `<label>${escapeHtml(proactiveWeightLabels[key] || key)}<input data-weight="${escapeHtml(key)}" type="number" min="0" max="100" step="1" value="${value}"></label>`
  ).join('');
  $('proactiveGroupWeights').innerHTML = Object.entries(p.group_content_weights || {}).map(([key,value])=>
    `<label>${escapeHtml(proactiveWeightLabels[key] || key)}<input data-group-weight="${escapeHtml(key)}" type="number" min="0" max="100" step="1" value="${value}"></label>`
  ).join('');
  renderProactivePreviewTypes();
  const schedule = data.schedule || {};
  const items = schedule.items || [];
  if(items.length && !$('proactivePreviewUser').value) {
    const firstEligible = items.find(item=>item.eligible) || items[0];
    $('proactivePreviewScope').value = firstEligible.target_type || 'private';
    $('proactivePreviewUser').value = firstEligible.target_id || '';
    renderProactivePreviewTypes();
  }
}
function renderProactivePreviewTypes() {
  const p = (window._proactive || {}).policy || {};
  const scope = $('proactivePreviewScope')?.value || 'private';
  const weights = scope==='group' ? (p.group_content_weights || {}) : (p.content_weights || {});
  const previous = $('proactivePreviewType')?.value;
  $('proactivePreviewType').innerHTML = Object.keys(weights).map(key=>
    `<option value="${escapeHtml(key)}">${escapeHtml(proactiveWeightLabels[key] || key)}</option>`
  ).join('');
  if(previous && Object.hasOwn(weights, previous)) $('proactivePreviewType').value = previous;
  const items = ((window._proactive || {}).schedule || {}).items || [];
  const matching = items.find(item=>item.target_type===scope && item.eligible) || items.find(item=>item.target_type===scope);
  if(matching) $('proactivePreviewUser').value = matching.target_id || '';
}
function collectProactivePolicy() {
  const base = JSON.parse(JSON.stringify((window._proactive || {}).policy || {}));
  base.enabled = $('proactiveEnabled').checked;
  base.owner_only = $('proactiveOwnerOnly').checked;
  base.use_ai = $('proactiveUseAi').checked;
  base.guided_topics = $('proactiveGuidedTopics').checked;
  base.private_min_affection = Number($('proactivePrivateMinAffection').value);
  base.private_active_days = Number($('proactivePrivateActiveDays').value);
  base.private_min_messages = Number($('proactivePrivateMinMessages').value);
  base.group_enabled = $('proactiveGroupEnabled').checked;
  base.group_min_activity = Number($('proactiveGroupMinActivity').value);
  base.group_active_days = Number($('proactiveGroupActiveDays').value);
  base.group_min_messages = Number($('proactiveGroupMinMessages').value);
  base.group_min_hours = Number($('proactiveGroupMinHours').value);
  base.group_max_hours = Number($('proactiveGroupMaxHours').value);
  base.group_daily_limit = Number($('proactiveGroupDailyLimit').value);
  base.timezone = $('proactiveTimezone').value.trim();
  base.quiet_start = $('proactiveQuietStart').value;
  base.quiet_end = $('proactiveQuietEnd').value;
  base.check_seconds = Number($('proactiveCheckSeconds').value);
  base.ignored_backoff = Number($('proactiveBackoff').value);
  base.history_limit = Number($('proactiveHistoryLimit').value);
  base.max_chars = Number($('proactiveMaxChars').value);
  base.tiers = Array.from(document.querySelectorAll('#proactiveTierRows tr')).map((row,index)=>({
    ...(base.tiers[index] || {}),
    enabled:row.querySelector('.tier-enabled').checked,
    min_affection:Number(row.querySelector('.tier-min').value),
    max_affection:Number(row.querySelector('.tier-max').value),
    min_hours:Number(row.querySelector('.tier-min-hours').value),
    max_hours:Number(row.querySelector('.tier-max-hours').value),
    daily_limit:Number(row.querySelector('.tier-limit').value)
  }));
  base.content_weights = {};
  document.querySelectorAll('[data-weight]').forEach(input=>base.content_weights[input.dataset.weight]=Number(input.value));
  base.group_content_weights = {};
  document.querySelectorAll('[data-group-weight]').forEach(input=>base.group_content_weights[input.dataset.groupWeight]=Number(input.value));
  return base;
}
async function saveProactive() {
  await api('/api/config', {method:'POST', body:JSON.stringify({PROACTIVE_V2_ENABLED:$('proactiveEngineEnabled').checked})});
  await api('/api/proactive/save', {method:'POST', body:JSON.stringify(collectProactivePolicy())});
  await loadProactive();
  await loadMemory();
  toast('主动互动配置已保存，记忆页计划已同步更新');
}
async function previewProactive() {
  $('proactivePreviewOut').textContent = '正在生成预览...';
  try {
    const body = {event_type:$('proactivePreviewType').value, scope:$('proactivePreviewScope').value, target_id:$('proactivePreviewUser').value.trim()};
    const result = await api('/api/proactive/preview', {method:'POST', body:JSON.stringify(body)});
    $('proactivePreviewOut').textContent = `${result.reply || result.text || ''}\n\n来源：${result.source || '未知'}${result.error ? `\n模型错误：${result.error}` : ''}`;
  } catch (error) {
    $('proactivePreviewOut').textContent = `预览失败：${error.message}`;
  }
}
async function loadConfig() {
  const cfg = await api('/api/config');
  $('configForm').innerHTML = fields.map(([key,label,type])=>{
    const item = cfg[key] || {}; const value = item.raw || item.value || '';
    if(type==='select') return `<label>${label}<select id="${key}"><option>private</option><option>mention</option><option>smart</option><option>all</option></select></label>`;
    if(type==='checkbox') return `<label>${label}<input id="${key}" type="checkbox" ${String(value).toLowerCase()==='true'?'checked':''}></label>`;
    if(type==='password') return `<label>${label}<input id="${key}" type="password" placeholder="${item.has_secret ? '已保存，留空保持原值' : '未填写'}"></label>`;
    if(type==='voice-probability') {
      const probability = Number(window._advancedVoiceBehavior?.reply_voice_probability ?? 35);
      return `<label>${label}<input id="replyVoiceProbabilityNumber" type="number" min="0" max="100" step="1" value="${probability}"></label>`;
    }
    return `<label>${label}<input id="${key}" type="${type}" step="0.01" value="${escapeHtml(value)}"></label>`;
  }).join('');
  for (const [key,,type] of fields) if(type==='select' && cfg[key]) $(key).value = cfg[key].raw || cfg[key].value;
}
async function loadReplyVoiceProbability() {
  try {
    const data = await api('/api/voice/behavior');
    window._advancedVoiceBehavior = data.behavior || {};
    const value = Number(window._advancedVoiceBehavior.reply_voice_probability ?? 35);
    const input = $('replyVoiceProbabilityNumber');
    if(input) input.value = value;
  } catch(error) {
    toast(`语音概率读取失败：${error.message}`);
  }
}
async function saveReplyVoiceProbability() {
  if(!window._advancedVoiceBehavior) {
    const data = await api('/api/voice/behavior');
    window._advancedVoiceBehavior = data.behavior || {};
  }
  const probability = Math.min(100, Math.max(0, Math.round(Number($('replyVoiceProbabilityNumber').value) || 0)));
  const behavior = {...window._advancedVoiceBehavior, reply_voice_probability:probability};
  await api('/api/voice/save', {method:'POST', body:JSON.stringify({behavior})});
  window._advancedVoiceBehavior = behavior;
  if(window._voiceData) window._voiceData.behavior = behavior;
}
async function saveConfig() {
  const body = {};
  for (const [key,,type] of fields) {
    const el = $(key); if(!el) continue;
    if(type==='voice-probability') continue;
    body[key] = type==='checkbox' ? el.checked : el.value;
  }
  await api('/api/config', {method:'POST', body:JSON.stringify(body)});
  await saveReplyVoiceProbability();
  await loadConfig(); await loadStatus(); await loadProfiles();
  toast('高级配置已保存，新的 QQ 消息会使用新配置');
}
async function loadStickers() {
  const s = await api('/api/stickers');
  $('stickerInfo').textContent = `表情包根目录：${s.path}`;
  const folders = (s.folders||[]).filter(f=>!f.name.startsWith('_deleted'));
  $('uploadCategory').innerHTML = folders.map(f=>`<option value="${escapeHtml(f.name)}">${escapeHtml(f.name)} (${f.count})</option>`).join('');
  $('stickerRows').innerHTML = folders.map((f,i)=>`<tr><td><button class="ghost" onclick="previewFolderByIndex(${i})">${escapeHtml(f.name)}</button></td><td>${f.count}</td><td class="mono">${escapeHtml(f.path)}</td></tr>`).join('');
  window._stickerFolders = folders;
  if (folders.length) previewFolderByIndex(0); else $('stickerPreview').innerHTML = '<p class="note">还没有表情包分类。</p>';
}
function previewFolderByIndex(index) {
  const folder = (window._stickerFolders || [])[index];
  if(!folder) return;
  window._stickerFiles = folder.files || [];
  $('stickerFolderTitle').textContent = `预览：${folder.name}`;
  $('stickerPreview').innerHTML = window._stickerFiles.map((file, fileIndex)=>`
    <div class="thumb">
      <img src="${file.url}" alt="${escapeHtml(file.name)}">
      <small title="${escapeHtml(file.path)}">${escapeHtml(file.name)}</small>
      <button class="danger" onclick="deleteStickerByIndex(${fileIndex})">删除</button>
    </div>`).join('') || '<p class="note">这个分类暂时没有图片。</p>';
}
async function createCategory() {
  const name = $('newCategory').value.trim();
  if(!name) return toast('先输入分类名');
  await api('/api/stickers/category', {method:'POST', body:JSON.stringify({name})});
  $('newCategory').value = ''; await loadStickers(); toast('分类已创建');
}
async function uploadSticker() {
  const file = $('stickerFile').files[0];
  if(!file) return toast('先选择图片');
  const form = new FormData();
  form.append('category', $('uploadCategory').value || 'default');
  form.append('file', file);
  await api('/api/stickers/upload', {method:'POST', body:form});
  $('stickerFile').value = ''; await loadStickers(); toast('表情包已上传');
}
async function deleteStickerByIndex(index) {
  const file = (window._stickerFiles || [])[index];
  if(!file) return toast('没有找到这个文件');
  if(!confirm('删除后会移动到 _deleted 备份文件夹，确认吗？')) return;
  await api('/api/stickers/delete', {method:'POST', body:JSON.stringify({path:file.path})});
  await loadStickers(); toast('已移动到 _deleted');
}

async function loadMemory() {
  const [m, proactive] = await Promise.all([api('/api/memory'), api('/api/proactive')]);
  window._proactive = proactive;
  const plans = new Map(((proactive.schedule || {}).items || []).map(item=>[String(item.conversation_id || ''), item]));
  window._memoryItems = (m.items || []).map(item=>{
    const planId = item.kind === 'person' ? `private:${String(item.id).replace(/^person:/, '')}` : item.id;
    return {...item, proactive_plan:plans.get(planId) || null};
  });
  const planItems = (proactive.schedule || {}).items || [];
  const eligibleCount = planItems.filter(item=>item.eligible).length;
  const retrieval = m.retrieval || {};
  const retrievalText = retrieval.ready
    ? `；检索索引：FTS5 已就绪（${retrieval.entries || 0} 条）`
    : '；检索索引：将在下一次聊天时轻量建立';
  $('memoryInfo').textContent = `记忆文件：${m.path}，显示对象：${m.conversations}，底层记录：${m.raw_conversations || m.conversations}；主动计划入选 ${eligibleCount}/${planItems.length}${retrievalText}`;
  renderMemoryRows();
}
function formatScore(value) {
  if(value === null || value === undefined || value === '') return '暂无';
  const score = Number(value);
  return Number.isFinite(score) ? score.toFixed(1) : '暂无';
}
function renderMemoryPlan(item) {
  if((window._proactive || {}).feature_enabled === false) {
    return '<div class="memory-plan"><span class="badge red">新版主动调度已关闭</span></div>';
  }
  const plan = item.proactive_plan;
  if(!plan) {
    return item.proactive_state
      ? `<div class="memory-plan"><span class="badge ${item.proactive_blocked?'red':'active'}">${escapeHtml(item.proactive_state)}</span></div>`
      : '<div class="memory-meta">暂无主动互动计划</div>';
  }
  const timezone = ((window._proactive || {}).schedule || {}).timezone || ((window._proactive || {}).policy || {}).timezone;
  const nextType = proactiveWeightLabels[plan.next_event_type] || plan.next_event_type || '';
  const nextTime = formatProactiveTime(plan.next_at, timezone);
  const detail = plan.eligible
    ? `<div class="memory-meta">下次内容：${escapeHtml(nextType || '由模型决定')}</div>
       <div class="plan-time-row">
         <input type="password" readonly aria-label="下次主动消息发送时间" value="${escapeHtml(nextTime)}">
         <button type="button" class="ghost" title="显示下次主动消息发送时间" aria-pressed="false" onclick="toggleProactiveTime(this)">查看</button>
       </div>`
    : `<div class="memory-meta">${escapeHtml(plan.eligibility_reason || '未满足当前门槛')}</div>`;
  return `<div class="memory-plan">
    <span class="badge ${plan.eligible?'active':'warn'}">主动互动 ${plan.eligible?'已入选':'未入选'}</span>
    ${detail}
    ${plan.ignored_streak ? `<div class="memory-meta">连续未回应 ${escapeHtml(plan.ignored_streak)} 次</div>` : ''}
  </div>`;
}
function toggleProactiveTime(button) {
  const input = button.parentElement?.querySelector('input');
  if(!input) return;
  const reveal = input.type === 'password';
  input.type = reveal ? 'text' : 'password';
  button.textContent = reveal ? '隐藏' : '查看';
  button.title = reveal ? '隐藏下次主动消息发送时间' : '显示下次主动消息发送时间';
  button.setAttribute('aria-pressed', String(reveal));
}
function memoryMatchesFilter(item) {
  const filter = $('memoryTypeFilter')?.value || 'all';
  if(filter === 'person' && item.kind !== 'person') return false;
  if(filter === 'private' && item.kind !== 'private') return false;
  if(filter === 'group' && item.kind !== 'group') return false;
  if(filter === 'member' && item.kind !== 'member') return false;
  if(filter === 'important' && !(item.memory_counts && item.memory_counts.total > 0)) return false;
  if($('memoryImportantOnly')?.checked && !(item.memory_counts && item.memory_counts.total > 0)) return false;
  if($('memoryRecentOnly')?.checked) {
    const raw = Number(item.last_user_at || 0);
    const seconds = raw > 100000000000 ? raw / 1000 : raw;
    if(!seconds || (Date.now() / 1000 - seconds) > 7 * 86400) return false;
  }
  const q = ($('memorySearch')?.value || '').trim().toLowerCase();
  if(!q) return true;
  return String(item.searchable || '').toLowerCase().includes(q);
}
function renderMemoryRows() {
  const sort = $('memorySort')?.value || 'recent';
  const rows = (window._memoryItems || []).filter(memoryMatchesFilter).sort((a,b)=>{
    if(sort === 'messages') return (b.messages||0) - (a.messages||0);
    if(sort === 'memories') return ((b.memory_counts||{}).total||0) - ((a.memory_counts||{}).total||0);
    if(sort === 'affection') return Number(b.affection||0) - Number(a.affection||0);
    return Number(b.last_user_at||0) - Number(a.last_user_at||0);
  });
  $('memoryRows').innerHTML = rows.map((x)=>`
    <tr>
      <td>
        <div class="memory-name">${escapeHtml(x.display_name || x.id)}</div>
        <div class="memory-meta">${escapeHtml(x.type)} · ${escapeHtml(x.id)}<br>${escapeHtml(x.last_user_at_text || '暂无互动时间')}</div>
      </td>
      <td class="memory-summary">${escapeHtml(x.summary || '暂无可读摘要')}</td>
      <td>
        <div class="memory-score">${x.kind==='group' ? `活跃度 ${formatScore(x.activity)} · ${escapeHtml(x.activity_label || '普通')}` : `好感 ${formatScore(x.affection)} · ${escapeHtml(x.affection_label || '普通')} · ${escapeHtml(x.trust_label || '观察中')}`}</div>
        ${x.kind==='group' ? '' : `<div class="memory-meta">信任：${escapeHtml(x.trust_label || '观察中')}</div>`}
        ${renderMemoryPlan(x)}
        <div class="memory-meta" style="margin-top:6px">消息 ${x.messages||0} · L1 ${((x.memory_counts||{}).l1)||0} · L2 ${((x.memory_counts||{}).l2)||0} · L3 ${((x.memory_counts||{}).l3)||0}${((x.memory_counts||{}).candidates) ? ' · 待确认 ' + x.memory_counts.candidates : ''}${x.related_count ? ' · 来源 ' + x.related_count : ''}</div>
      </td>
      <td><div class="row" style="margin-top:0"><button class="ghost" onclick="toggleMemoryInline(this)">展开</button><button class="ghost" onclick="openMemory('${escapeHtml(x.id)}')">详情 / 编辑</button></div></td>
    </tr>
    <tr class="memory-inline-row" style="display:none"><td colspan="4"><div class="natural-box"><strong>${escapeHtml(x.display_name || x.id)}</strong><br>${escapeHtml(x.summary || '暂无可读摘要')}<br><span class="memory-meta">${escapeHtml(x.type || '')} · L1 ${((x.memory_counts||{}).l1)||0} · L2 ${((x.memory_counts||{}).l2)||0} · L3 ${((x.memory_counts||{}).l3)||0}</span></div></td></tr>`).join('') || '<tr><td colspan="4"><div class="empty">没有匹配的记忆。</div></td></tr>';
}
function toggleMemoryInline(button) {
  const row = button.closest('tr')?.nextElementSibling;
  if(!row) return;
  const open = row.style.display !== 'none';
  row.style.display = open ? 'none' : 'table-row';
  button.textContent = open ? '展开' : '收起';
}
async function openMemory(id) {
  if(memoryDirty && !confirm('当前记忆有未保存修改，确定切换吗？')) return;
  const d = await api('/api/memory/detail?id=' + encodeURIComponent(id));
  currentMemoryId = id;
  selectedMemory = d;
  selectedMemoryContent = JSON.parse(JSON.stringify(d.content || {}));
  memoryDirty = false;
  $('memoryModalTitle').textContent = d.display_name || id;
  $('memoryModalMeta').textContent = `${d.type || ''} · ${id}${d.storage_id ? ' · 保存到 ' + d.storage_id : ''}`;
  $('memoryModal').classList.add('show');
  setSaveState('未修改', false);
  renderMemoryModal();
}
function closeMemoryModal() {
  if(memoryDirty && !confirm('还有未保存修改，确定关闭吗？')) return;
  $('memoryModal').classList.remove('show');
}
function modalBackdrop(event) {
  if(event.target.id === 'memoryModal') closeMemoryModal();
}
function showMemoryPane(event, id) {
  activeMemoryPane = id;
  document.querySelectorAll('.mini-tab').forEach(b=>b.classList.remove('active'));
  document.querySelectorAll('.memory-pane').forEach(p=>p.style.display='none');
  (event.currentTarget || event.target).classList.add('active'); $(id).style.display = 'block';
}
function setSaveState(text, dirty) {
  memoryDirty = dirty;
  const el = $('memorySaveState');
  el.textContent = text;
  el.className = dirty ? 'dirty' : 'saved';
}
function markMemoryDirty() {
  setSaveState('有未保存修改', true);
}
function structuredMemory() {
  selectedMemoryContent.structured_memory = selectedMemoryContent.structured_memory || {};
  for (const key of ['l1','l2','l3','candidates']) {
    if(!Array.isArray(selectedMemoryContent.structured_memory[key])) selectedMemoryContent.structured_memory[key] = [];
  }
  return selectedMemoryContent.structured_memory;
}
function memoryEntryLayerForPane() {
  if(activeMemoryPane === 'memoryEvents') return 'l2';
  if(activeMemoryPane === 'memoryHistory') return 'l3';
  if(activeMemoryPane === 'memoryProfile') return 'l1';
  return 'l1';
}
function formatMemoryTime(value) {
  const n = Number(value || 0);
  if(!Number.isFinite(n) || n <= 0) return '暂无';
  return new Date(n * 1000).toLocaleString();
}
function memoryCountText(counts) {
  counts = counts || {};
  return `L1 ${counts.l1 || 0} / L2 ${counts.l2 || 0} / L3 ${counts.l3 || 0} / 待确认 ${counts.candidates || 0}`;
}
function renderFactGrid(items) {
  return `<div class="fact-grid">${items.map(item=>`
    <div class="fact"><span>${escapeHtml(item.label)}</span><strong>${escapeHtml(item.value ?? '暂无')}</strong></div>
  `).join('')}</div>`;
}
function renderRelationshipControls() {
  const isPerson = selectedMemory.kind === 'person' || selectedMemory.kind === 'private';
  const override = ['allow','deny'].includes(selectedMemoryContent.proactive_override)
    ? selectedMemoryContent.proactive_override
    : 'auto';
  const trustTier = ['approved','trusted','blocked'].includes(selectedMemoryContent.trust_tier)
    ? selectedMemoryContent.trust_tier
    : 'probation';
  return `<div class="relationship-controls">
    <h3>关系与主动互动</h3>
    <div class="grid">
      ${isPerson ? `<label>好感度（0–100）<input id="memoryAffectionScore" type="number" min="0" max="100" step="0.1" value="${escapeHtml(selectedMemoryContent.affection_score ?? 0)}"></label>` : ''}
      ${isPerson ? `<label>账号信任层级<select id="memoryTrustTier">
        <option value="probation" ${trustTier==='probation'?'selected':''}>观察中（仅响应消息）</option>
        <option value="approved" ${trustTier==='approved'?'selected':''}>白名单</option>
        <option value="trusted" ${trustTier==='trusted'?'selected':''}>可信用户</option>
        <option value="blocked" ${trustTier==='blocked'?'selected':''}>屏蔽回复</option>
      </select></label>` : ''}
      ${!isPerson ? `<label>群聊活跃度（0–100）<input id="memoryGroupActivityScore" type="number" min="0" max="100" step="0.1" value="${escapeHtml(selectedMemoryContent.group_activity_score ?? 0)}"></label>` : ''}
      <label>主动互动<select id="memoryProactiveOverride">
        <option value="auto" ${override==='auto'?'selected':''}>跟随全局策略</option>
        <option value="allow" ${override==='allow'?'selected':''}>强制允许</option>
        <option value="deny" ${override==='deny'?'selected':''}>强制禁止</option>
      </select></label>
    </div>
    <div class="row"><button type="button" class="ghost" onclick="saveRelationshipControls()">保存关系设置</button></div>
    <p class="note">强制允许会跳过该对象的好感、活跃期和消息量门槛，但仍遵守总开关、免打扰时段和当前频率设置；强制禁止的优先级最高。</p>
  </div>`;
}
async function saveRelationshipControls() {
  if(!currentMemoryId || !selectedMemoryContent) return toast('先打开一条记忆');
  const override = $('memoryProactiveOverride')?.value || 'auto';
  const scoreInput = $('memoryAffectionScore');
  const activityInput = $('memoryGroupActivityScore');
  const trustTier = $('memoryTrustTier')?.value || 'probation';
  const score = scoreInput ? Number(scoreInput.value) : null;
  const activity = activityInput ? Number(activityInput.value) : null;
  if(scoreInput && (!Number.isFinite(score) || score < 0 || score > 100)) {
    return toast('好感度必须在 0 到 100 之间');
  }
  if(activityInput && (!Number.isFinite(activity) || activity < 0 || activity > 100)) {
    return toast('群聊活跃度必须在 0 到 100 之间');
  }
  try {
    const result = await api('/api/memory/relationship', {method:'POST', body:JSON.stringify({
      id:currentMemoryId,
      affection_score:score,
      group_activity_score:activity,
      proactive_override:override,
      trust_tier:trustTier
    })});
    const relationship = result.relationship || {};
    if(scoreInput) {
      selectedMemoryContent.affection_score = relationship.affection_score;
      selectedMemoryContent.affection_initialized = true;
    }
    if(activityInput) {
      selectedMemoryContent.group_activity_score = relationship.group_activity_score;
    }
    selectedMemoryContent.proactive_override = relationship.proactive_override || 'auto';
    if(scoreInput) selectedMemoryContent.trust_tier = relationship.trust_tier || 'probation';
    await loadMemory();
    const summary = (window._memoryItems || []).find(item=>item.id===currentMemoryId);
    if(summary) selectedMemory.affection_label = summary.affection_label;
    renderMemoryModal();
    toast('关系设置已保存，主动计划已重新评估');
  } catch(error) {
    toast('关系设置保存失败：' + error.message);
  }
}
function renderPersonOverview(counts) {
  const target = selectedMemoryContent.target || {};
  const userId = String(target.user_id || currentMemoryId.replace(/^person:/, '') || '').replace(/^private:/, '');
  const sources = selectedMemory.related_conversations || [];
  return `
    <h3>基本数据</h3>
    ${renderFactGrid([
      {label:'QQ', value:userId || '未知'},
      {label:'底层保存位置', value:selectedMemory.storage_id || currentMemoryId},
      {label:'来源记录', value:String(sources.length || 1)},
      {label:'消息数量', value:String(selectedMemoryContent.message_count || 0)},
      {label:'L1 / L2 / L3', value:`${counts.l1 || 0} / ${counts.l2 || 0} / ${counts.l3 || 0}`},
      {label:'待确认特点', value:String(counts.candidates || 0)},
      {label:'最近互动', value:formatMemoryTime(selectedMemoryContent.last_user_at)},
      {label:'亲密状态', value:`${selectedMemory.affection_label || '普通'}（好感 ${formatScore(selectedMemoryContent.affection_score)}）`},
      {label:'历史条数', value:String(selectedMemory.history_count || 0)}
    ])}
    ${renderRelationshipControls()}
    <div class="natural-box">${escapeHtml(selectedMemory.natural || '暂无可读摘要。')}</div>
    <h3>所在群聊</h3>
    ${renderGroupInfoList(selectedMemory.group_infos || [])}
    <p class="note">人物档案按 QQ 聚合；保存会写回 ${escapeHtml(selectedMemory.storage_id || currentMemoryId)}，并清理同一人的过期群成员旧值。</p>`;
}
function renderGroupInfoList(groups) {
  if(!groups.length) return '<div class="empty">暂无群聊来源。</div>';
  return `<div class="group-info-list">${groups.map(group=>`
    <div class="group-info">
      <div class="group-info-head">
        <div>
          <div class="group-info-title">群 ${escapeHtml(group.group_id || '未知')}</div>
          <div class="memory-meta">${escapeHtml(group.nickname ? '群内昵称：' + group.nickname : group.display_name || group.id)}</div>
        </div>
        <span class="badge">${escapeHtml(group.last_user_at_text || '暂无时间')}</span>
      </div>
      ${renderFactGrid([
        {label:'底层记录', value:group.id || ''},
        {label:'消息数量', value:String(group.messages || 0)},
        {label:'结构化记忆', value:memoryCountText(group.memory_counts || {})},
        {label:'最近互动', value:group.last_user_at_text || formatMemoryTime(group.last_user_at)}
      ])}
      <div class="natural-box">${escapeHtml(group.summary || '暂无可读摘要。')}</div>
    </div>
  `).join('')}</div>`;
}
function renderMemoryModal() {
  if(!selectedMemory || !selectedMemoryContent) return;
  const counts = selectedMemory.memory_counts || {};
  $('memoryOverview').innerHTML = selectedMemory.kind === 'person' ? renderPersonOverview(counts) : `
    <div class="natural-box">${escapeHtml(selectedMemory.natural || '暂无可读摘要。')}</div>
    ${selectedMemory.related_conversations ? `<p class="note">统一人物档案会聚合同一 QQ 的私聊和群成员公开来源；保存会写回 ${escapeHtml(selectedMemory.storage_id || currentMemoryId)}，并清理同一人的过期群成员旧值。</p>` : ''}
    <div class="stat-grid">
      <div class="stat"><strong>${selectedMemoryContent.message_count || 0}</strong><span class="note">消息数量</span></div>
      <div class="stat"><strong>${counts.total || 0}</strong><span class="note">结构化记忆</span></div>
      <div class="stat"><strong>${selectedMemory.history_count || 0}</strong><span class="note">历史条数</span></div>
      <div class="stat"><strong>${selectedMemory.kind==='group' ? formatScore(selectedMemoryContent.group_activity_score) : formatScore(selectedMemoryContent.affection_score)}</strong><span class="note">${selectedMemory.kind==='group'?'群活跃度':'好感度'}</span></div>
    </div>
    ${renderRelationshipControls()}
    <p class="note">编辑下面的档案、事件、习惯或最近聊天后，点击底部“保存修改”。保存前会自动备份。</p>`;
  $('memoryProfile').innerHTML = renderEntryEditor('l1', ['profile_fact','interest','preference','habit','communication_style'], 'L1 已确认的用户特点') + renderEntryEditor('candidates', ['profile_fact','interest','preference','habit','communication_style'], 'L1 待确认特点') + renderRulesEditor();
  $('memoryEvents').innerHTML = renderEntryEditor('l2', ['event','schedule','important_interaction'], 'L2 事件、日程与重要互动');
  $('memoryHistory').innerHTML = renderEntryEditor('l3', ['session_context'], 'L3 当前会话上下文') + renderHistoryEditor() + '<p class="note">L3 是短上下文；完整消息历史单独展示，供画像提取和人工核对使用，不会把全部历史一次性塞进回复提示词。</p>';
  $('memoryRaw').innerHTML = `<p class="note">高级模式会直接保存整个会话 JSON。改错 JSON 会被拦截，不会写入。</p><textarea id="memoryRawEditor" class="json-editor" spellcheck="false">${escapeHtml(JSON.stringify(selectedMemoryContent, null, 2))}</textarea><div class="row"><button class="ghost" onclick="applyRawMemory()">应用 JSON 到编辑器</button></div>`;
}
function renderEntryEditor(layer, categories, title) {
  const memory = structuredMemory();
  const entries = (memory[layer] || []).map((entry, index)=>({entry,index})).filter(({entry})=>categories.includes(entry.category || ''));
  return `<h3>${title}</h3><div class="entry-list">${entries.map(({entry,index})=>renderEntry(layer,index,entry)).join('') || '<div class="empty">暂无内容，可以点击底部“新增当前分类”。</div>'}</div>`;
}
function renderEntry(layer, index, entry) {
  const category = entry.category || '';
  const options = Object.entries(categoryLabels).map(([key,label])=>`<option value="${key}" ${key===category?'selected':''}>${label}</option>`).join('');
  return `<div class="entry">
    <div class="entry-head">
      <strong>${escapeHtml(categoryLabels[category] || category || '未分类')}</strong>
      <button class="danger" onclick="removeMemoryEntry('${layer}',${index})">删除</button>
    </div>
    <div class="entry-grid">
      <label>分类<select onchange="updateMemoryEntry('${layer}',${index},'category',this.value)">${options}</select></label>
      <label>标题 / 键<input value="${escapeHtml(entry.key || entry.memory_key || '')}" oninput="updateMemoryEntry('${layer}',${index},'key',this.value)"></label>
      <label>置信度<input type="number" min="0" max="1" step="0.05" value="${escapeHtml(entry.confidence ?? '')}" oninput="updateMemoryEntry('${layer}',${index},'confidence',this.value,true)"></label>
      <label>状态<select onchange="updateMemoryEntry('${layer}',${index},'state',this.value)">
        <option value="active" ${entry.state !== 'sleeping'?'selected':''}>启用</option>
        <option value="sleeping" ${entry.state === 'sleeping'?'selected':''}>休眠</option>
      </select></label>
    </div>
    <label>内容<textarea oninput="updateMemoryEntry('${layer}',${index},'value',this.value)${layer === 'l3' ? "; updateMemoryEntry('l3'," + index + ",'text',this.value)" : ''}">${escapeHtml(entry.value || entry.text || '')}</textarea></label>
  </div>`;
}
function renderRulesEditor() {
  const accepted = selectedMemoryContent.accepted_iteration_rules || [];
  const rejected = selectedMemoryContent.rejected_iteration_rules || [];
  const block = (items, key, label) => `<h3>${label}</h3><div class="entry-list">${items.map((rule,index)=>`
    <div class="entry">
      <div class="entry-head"><strong>${label} ${index+1}</strong><button class="danger" onclick="removeRule('${key}',${index})">删除</button></div>
      <label>规则<textarea oninput="updateRule('${key}',${index},'rule',this.value)">${escapeHtml(rule.rule || '')}</textarea></label>
      <label>原因<input value="${escapeHtml(rule.reason || '')}" oninput="updateRule('${key}',${index},'reason',this.value)"></label>
    </div>`).join('') || '<div class="empty">暂无规则。</div>'}</div><div class="row"><button class="ghost" onclick="addRule('${key}')">新增${label}</button></div>`;
  return block(accepted,'accepted_iteration_rules','已采纳纠错') + block(rejected,'rejected_iteration_rules','已驳回纠错');
}
function renderHistoryEditor() {
  const history = Array.isArray(selectedMemoryContent.history) ? selectedMemoryContent.history : [];
  const recent = history.map((entry,index)=>({entry,index})).slice(-300).reverse();
  return `<h3>完整消息历史（最多保留 300 条）</h3><p class="note">这里展示当前人物档案保留的完整消息窗口，包含用户和亚托莉的消息；可修正或删除记忆副本，不会撤回 QQ 消息。</p>${recent.map(({entry,index})=>`
    <div class="history-item">
      <div class="entry-head">
        <strong>${entry.role === 'assistant' ? '亚托莉' : '用户'} ${entry.nickname ? ' · ' + escapeHtml(entry.nickname) : ''}</strong>
        <button class="danger" onclick="removeHistory(${index})">删除</button>
      </div>
      <textarea oninput="updateHistory(${index},this.value)">${escapeHtml(entry.text || '')}</textarea>
    </div>`).join('') || '<div class="empty">暂无聊天历史。</div>'}`;
}
function updateMemoryEntry(layer, index, key, value, numeric=false) {
  const memory = structuredMemory();
  if(!memory[layer] || !memory[layer][index]) return;
  memory[layer][index][key] = numeric && value !== '' ? Number(value) : value;
  if(key === 'key') memory[layer][index].memory_key = value;
  markMemoryDirty();
}
function removeMemoryEntry(layer, index) {
  const memory = structuredMemory();
  if(!memory[layer] || !memory[layer][index]) return;
  memory[layer].splice(index, 1);
  markMemoryDirty();
  renderMemoryModal();
}
function addMemoryEntryFromActivePane() {
  if(!selectedMemoryContent) return;
  const layer = memoryEntryLayerForPane();
  const memory = structuredMemory();
  let category = 'profile_fact';
  if(activeMemoryPane === 'memoryEvents') category = 'event';
  if(activeMemoryPane === 'memoryHistory') category = 'session_context';
  const now = Math.floor(Date.now() / 1000);
  memory[layer].push({
    layer: layer.toUpperCase(),
    category,
    key: category + ':新记忆',
    value: '',
    text: layer === 'l3' ? '' : undefined,
    confidence: layer === 'l1' ? 0.8 : 0.7,
    activity: 1.0,
    source: 'webui',
    created_at: now,
    updated_at: now,
    state: 'active',
    associations: []
  });
  markMemoryDirty();
  renderMemoryModal();
}
function updateRule(bucket, index, key, value) {
  selectedMemoryContent[bucket] = selectedMemoryContent[bucket] || [];
  if(!selectedMemoryContent[bucket][index]) return;
  selectedMemoryContent[bucket][index][key] = value;
  markMemoryDirty();
}
function addRule(bucket) {
  selectedMemoryContent[bucket] = selectedMemoryContent[bucket] || [];
  selectedMemoryContent[bucket].push({at:Math.floor(Date.now()/1000), action: bucket.startsWith('accepted') ? 'accept' : 'reject', rule:'', reason:'webui 手动添加'});
  markMemoryDirty();
  renderMemoryModal();
}
function removeRule(bucket, index) {
  selectedMemoryContent[bucket] = selectedMemoryContent[bucket] || [];
  selectedMemoryContent[bucket].splice(index, 1);
  markMemoryDirty();
  renderMemoryModal();
}
function updateHistory(index, value) {
  if(!Array.isArray(selectedMemoryContent.history) || !selectedMemoryContent.history[index]) return;
  selectedMemoryContent.history[index].text = value;
  markMemoryDirty();
}
function removeHistory(index) {
  if(!Array.isArray(selectedMemoryContent.history)) return;
  selectedMemoryContent.history.splice(index, 1);
  markMemoryDirty();
  renderMemoryModal();
}
function applyRawMemory() {
  try {
    selectedMemoryContent = JSON.parse($('memoryRawEditor').value);
  } catch(e) {
    return toast('JSON 格式错误：' + e.message);
  }
  markMemoryDirty();
  renderMemoryModal();
  toast('JSON 已应用，保存后生效');
}
async function saveSelectedMemory() {
  if(!currentMemoryId || !selectedMemoryContent) return toast('先打开一条记忆');
  const btn = $('memorySaveButton');
  btn.disabled = true; btn.textContent = '保存中...';
  try {
    const r = await api('/api/memory/save', {method:'POST', body:JSON.stringify({id:currentMemoryId, content:selectedMemoryContent})});
    setSaveState('已保存，下一轮聊天生效', false);
    toast('记忆已保存，已自动备份');
    await loadMemory();
    const d = await api('/api/memory/detail?id=' + encodeURIComponent(currentMemoryId));
    selectedMemory = d;
    selectedMemoryContent = JSON.parse(JSON.stringify(d.content || {}));
    renderMemoryModal();
  } catch(e) {
    toast('保存失败：' + e.message);
  } finally {
    btn.disabled = false; btn.textContent = '保存修改';
  }
}
async function deleteSelectedMemory() {
  if(!currentMemoryId) return toast('先打开一条记忆');
  if(!confirm('确认删除这个会话的全部记忆？删除前会自动备份。')) return;
  await api('/api/memory/delete', {method:'POST', body:JSON.stringify({id:currentMemoryId})});
  currentMemoryId = ''; selectedMemory = null; selectedMemoryContent = null; memoryDirty = false;
  $('memoryModal').classList.remove('show');
  await loadMemory(); toast('记忆已删除，已自动备份');
}
async function backupMemory() {
  await api('/api/memory/backup', {method:'POST', body:'{}'});
  toast('记忆已备份');
}
async function testChat() {
  $('testOut').textContent='亚托莉生成中...';
  const r = await api('/api/test-chat', {method:'POST', body:JSON.stringify({text:$('testText').value})});
  $('testOut').textContent = r.used_ai
    ? r.reply
    : `当前聊天模型没有连上，正在走兜底。\n错误：${r.error || '未知错误'}\n\n兜底回复：${r.reply}`;
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
  const preferred = candidates.filter(item=>item.ready).map(item=>item.profile_id);
  const available = preferred.length ? profiles.filter(item=>preferred.includes(item.id)) : profiles;
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
    out.textContent = `识别文本：${result.text}\n语言：${result.language || '未知'}\n情绪：${result.emotion || 'neutral'}\n置信度：${confidence}\n耗时：${result.elapsed_ms} ms`;
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
      intensity:Number($('testTtsIntensity').value)
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
async function testVoiceSynthesis() { return testVoiceComparison(); }
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
setupAdvancedAccordions();
loadStatus(); loadProfiles(); loadConfig(); loadReplyVoiceProbability(); loadProactive();
setInterval(()=>{ if($('developer')?.classList.contains('active')) loadDeveloperLogs(); }, 3000);
</script>
</body>
</html>"""
