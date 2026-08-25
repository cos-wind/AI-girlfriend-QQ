from __future__ import annotations

PART = r"""        <div class="section-head">
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
"""
