from __future__ import annotations

from atri_shared.web_components import MODEL_EDITOR

PART = r"""        <div class="model-workspace">
          <div class="stack">
            <div class="surface">
              <h2>当前启用模型</h2>
              <div id="currentModel" class="current-models">读取中...</div>
              <p class="note">当前启用的聊天模型同时作为回复质量评测的 Judge；切换并启用模型后，评测旁路会自动跟随。</p>
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
""" + MODEL_EDITOR + r"""
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

      <div id="users" class="panel">
"""
