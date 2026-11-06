from __future__ import annotations

PART = r"""  <header>
    <h1>亚托莉控制台</h1>
    <div class="sub">本地 WebUI，只监听 127.0.0.1。这里可以切换模型、管理用户权限、查看评测与群聊总结。</div>
  </header>
  <div id="accountBanner" class="account-banner" hidden></div>
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
        <button class="tab" onclick="showTab(event,'users')">用户中心</button>
        <button class="tab" onclick="showTab(event,'test')">测试</button>
        <button class="tab" onclick="showTab(event,'evaluation')">评测</button>
        <button class="tab" onclick="showTab(event,'advanced')">高级</button>
      </div>

      <div id="model" class="panel active">
"""
